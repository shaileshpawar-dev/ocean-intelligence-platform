/**
 * India water map — the platform's primary surface.
 *
 * Design decisions worth stating:
 *
 * **Real shapes where they exist, points where they do not.** Rivers are
 * drawn as lines and lakes as polygons only when an OpenStreetMap geometry was
 * matched to the CPCB stations; everything else stays a point at the mean of
 * its stations. Nothing is buffered or drawn to look like a shape.
 *
 * **Water stays blue.** Status never recolours the water. With the status
 * overlay on, a river gets a coloured casing under its blue line and a lake a
 * coloured outline; points carry the colour as before.
 *
 * **Everything is fetched per viewport** (bbox + zoom), with server-side
 * clustering for stations and zoom-simplified geometry, so the national view
 * stays light.
 *
 * **Layers come from the API.** Sources, attributions and the Bhuvan WMS
 * endpoint are served by `/map/layers`, not hardcoded here.
 *
 * **Colour encodes the last measurement, not the present**, and every place
 * that shows it says so with the date.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Marker,
  TileLayer,
  Tooltip,
  WMSTileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import type { LatLngBoundsExpression, PathOptions } from "leaflet";
import type { Feature, GeoJsonObject } from "geojson";
import {
  CalendarClock,
  Filter,
  Layers,
  Loader2,
  MapPin,
  MessageSquareText,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  BoundaryFeature,
  ClusterItem,
  GeometryFeature,
  MapFeature,
  MapLayerDef,
  SearchHit,
  WaterBodyType,
  WaterStatus,
} from "@/lib/waterTypes";
import {
  LatestAvailableStatus,
  STATUS_META,
  TYPE_META,
  WaterStatusBadge,
  WaterTypeTag,
  formatDay,
} from "@/components/water";
import { AvailabilityPanel, DataQualityBadge } from "@/components/waterPanels";
import { ErrorState } from "@/components/ui";

/* India, comfortably framed including the island territories. */
const INDIA_CENTRE: [number, number] = [22.0, 79.0];
const INDIA_BOUNDS: LatLngBoundsExpression = [
  [4.0, 64.0],
  [39.5, 100.5],
];
const GEOMETRY_MIN_ZOOM = 6;
const POINT_LIMIT = 1500;

const WATER_BLUE = "#1d6fb8";
const WATER_FILL = "#3b8fd9";

/**
 * Status colours. Only markers, casings and outlines carry them — the water
 * stays blue. "Unknown" is grey rather than green: absence of data must never
 * look like a clean bill of health.
 */
const STATUS_COLOUR: Record<WaterStatus, string> = {
  WITHIN_REFERENCE: "#0e9f6e",
  ELEVATED: "#d97706",
  HIGH_CONCERN: "#e02424",
  POLLUTED_STRETCH: "#9b1c1c",
  INSUFFICIENT_DATA: "#94a3b8",
  NO_RECENT_DATA: "#94a3b8",
  NO_APPLICABLE_REFERENCE: "#64748b",
};
const UNKNOWN_COLOUR = "#94a3b8";

function colourFor(status: WaterStatus | null | undefined): string {
  return status ? STATUS_COLOUR[status] : UNKNOWN_COLOUR;
}

function radiusFor(feature: MapFeature, zoom: number): number {
  const base = zoom >= 9 ? 7 : zoom >= 7 ? 6 : 5;
  return feature.station_count > 3 ? base + 2 : base;
}

type LayerState = Record<string, boolean>;

export default function IndiaWaterMap() {
  const navigate = useNavigate();
  const [bbox, setBbox] = useState<string | null>(null);
  const [zoom, setZoom] = useState(5);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<WaterBodyType | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<WaterStatus | "ALL">("ALL");
  const [layers, setLayers] = useState<LayerState | null>(null);
  const [panel, setPanel] = useState<"filters" | "layers" | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number, number] | null>(null);
  const [fitBox, setFitBox] = useState<[[number, number], [number, number]] | null>(null);

  // URL state: ?highlight=a,b rings results from an answer, ?bbox= frames
  // them, ?focus= opens one, ?state= selects a state, ?city= frames a city.
  const [params, setParams] = useSearchParams();
  const highlighted = useMemo(
    () => new Set((params.get("highlight") ?? "").split(",").filter(Boolean)),
    [params],
  );
  const frame = useMemo(() => parseBox(params.get("bbox")), [params]);
  const focusSlug = params.get("focus");
  const stateFilter = params.get("state");
  const citySlug = params.get("city");

  const setStateFilter = useCallback(
    (code: string | null) => {
      const next = new URLSearchParams(params);
      if (code) next.set("state", code);
      else next.delete("state");
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  /* -- Layer catalogue ---------------------------------------------- */
  const catalogue = useQuery({ queryKey: ["map-layers"], queryFn: api.mapLayers, staleTime: Infinity });
  const layerDefs = useMemo(() => {
    const out: Record<string, MapLayerDef> = {};
    for (const g of catalogue.data?.groups ?? []) for (const l of g.layers) out[l.key] = l;
    return out;
  }, [catalogue.data]);
  useEffect(() => {
    if (catalogue.data && layers === null) {
      const initial: LayerState = {};
      for (const g of catalogue.data.groups) for (const l of g.layers) initial[l.key] = l.default;
      setLayers(initial);
    }
  }, [catalogue.data, layers]);
  const on = (key: string) => Boolean(layers?.[key]);

  /* -- Data ------------------------------------------------------------ */
  const focusTarget = useQuery({
    queryKey: ["water-body", focusSlug],
    queryFn: () => api.waterBody(focusSlug as string),
    enabled: Boolean(focusSlug),
  });
  useEffect(() => {
    const t = focusTarget.data;
    if (t && t.latitude != null && t.longitude != null) {
      setFlyTo([t.latitude, t.longitude, 12]);
      setSelectedSlug(t.slug);
    }
  }, [focusTarget.data]);

  const city = useQuery({
    queryKey: ["city", citySlug],
    queryFn: () => api.city(citySlug as string),
    enabled: Boolean(citySlug),
  });
  useEffect(() => {
    const b = city.data?.bbox;
    if (b) setFitBox([[b[1], b[0]], [b[3], b[2]]]);
  }, [city.data]);

  const filters = {
    water_type: typeFilter === "ALL" ? null : typeFilter,
    status: statusFilter === "ALL" ? null : statusFilter,
    state: stateFilter,
  };

  const bodies = useQuery({
    queryKey: ["map-water-bodies", bbox, filters],
    queryFn: () => api.mapWaterBodies({ bbox, ...filters, limit: POINT_LIMIT }),
    enabled: bbox !== null && on("water_points"),
    placeholderData: (previous) => previous,
  });

  const geometries = useQuery({
    queryKey: ["map-geometries", bbox, zoom, filters],
    queryFn: () => api.mapGeometries({ bbox, zoom, ...filters }),
    enabled: bbox !== null && on("water_geometry") && zoom >= GEOMETRY_MIN_ZOOM,
    placeholderData: (previous) => previous,
  });

  const clusters = useQuery({
    queryKey: ["map-clusters", bbox, zoom, stateFilter],
    queryFn: () => api.stationClusters({ bbox, zoom, state: stateFilter }),
    enabled: bbox !== null && on("stations"),
    placeholderData: (previous) => previous,
  });

  const boundaryZoom = zoom <= 5 ? 4 : zoom <= 7 ? 6 : 8;
  const stateBoundaries = useQuery({
    queryKey: ["state-boundaries", boundaryZoom],
    queryFn: () => api.stateBoundaries(boundaryZoom),
    enabled: on("states"),
    staleTime: Infinity,
    placeholderData: (previous) => previous,
  });

  const districtBoundaries = useQuery({
    queryKey: ["district-boundaries", stateFilter, boundaryZoom],
    queryFn: () => api.districtBoundaries({ state: stateFilter, zoom: boundaryZoom }),
    enabled: on("districts") && Boolean(stateFilter),
    staleTime: Infinity,
  });

  const states = useQuery({ queryKey: ["states"], queryFn: api.states, staleTime: Infinity });

  const geometryFeatures = useMemo(() => geometries.data?.features ?? [], [geometries.data]);
  const drawnShapes = on("water_geometry") && zoom >= GEOMETRY_MIN_ZOOM;
  const shapedSlugs = useMemo(
    () => new Set(drawnShapes ? geometryFeatures.map((f) => f.properties.slug) : []),
    [drawnShapes, geometryFeatures],
  );
  const points = useMemo(
    () => (bodies.data?.items ?? []).filter((f) => !shapedSlugs.has(f.slug)),
    [bodies.data, shapedSlugs],
  );

  // Frame the selected state once its boundary is known.
  const selectedStateFeature = useMemo(
    () =>
      (stateBoundaries.data?.features ?? []).find(
        (f) => f.properties.state_code === stateFilter,
      ),
    [stateBoundaries.data, stateFilter],
  );
  const lastFramedState = useRef<string | null>(null);
  useEffect(() => {
    if (selectedStateFeature && lastFramedState.current !== stateFilter) {
      const [minx, miny, maxx, maxy] = selectedStateFeature.properties.bbox;
      setFitBox([[miny, minx], [maxy, maxx]]);
      lastFramedState.current = stateFilter;
    }
    if (!stateFilter) lastFramedState.current = null;
  }, [selectedStateFeature, stateFilter]);

  const handleViewport = useCallback((box: string, nextZoom: number) => {
    setBbox(box);
    setZoom(nextZoom);
  }, []);

  const handlePick = useCallback(
    (hit: SearchHit) => {
      if (hit.type === "city" && hit.bbox) {
        const [a, b, c, d] = hit.bbox; // min_lat, min_lon, max_lat, max_lon
        setFitBox([[a, b], [c, d]]);
        return;
      }
      if (hit.type === "state") {
        const code = (states.data?.items ?? []).find((s) => s.slug === hit.slug)?.code;
        if (code) setStateFilter(code);
        return;
      }
      if (hit.latitude != null && hit.longitude != null) {
        setFlyTo([hit.latitude, hit.longitude, hit.type === "water_body" ? 12 : 10]);
      }
      if (hit.type === "water_body") setSelectedSlug(hit.slug);
      if (hit.type === "station") navigate(hit.href);
    },
    [navigate, setStateFilter, states.data],
  );

  const loading = bodies.isFetching || geometries.isFetching || clusters.isFetching;
  const shownCount = points.length + (drawnShapes ? geometryFeatures.length : 0);
  const nothingInView =
    !loading && bodies.data !== undefined && shownCount === 0 && (clusters.data?.items.length ?? 0) === 0;

  const wms = layerDefs.bhuvan_waterbodies;
  const showWms = on("bhuvan_waterbodies") && wms?.wms && zoom >= (wms.min_zoom ?? 0);

  return (
    <div className={`wmap-shell ${selectedSlug ? "has-panel" : ""}`}>
      <MapContainer
        center={INDIA_CENTRE}
        zoom={5}
        minZoom={4}
        maxBounds={INDIA_BOUNDS}
        maxBoundsViscosity={0.6}
        scrollWheelZoom
        className="wmap-canvas"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {showWms && wms?.wms && (
          <WMSTileLayer
            url={wms.wms.url}
            params={{
              layers: wms.wms.layers,
              format: wms.wms.format,
              transparent: wms.wms.transparent,
              version: wms.wms.version,
            }}
            opacity={0.8}
            attribution={wms.attribution}
          />
        )}

        <ViewportReporter onChange={handleViewport} />
        <SizeWatcher trigger={selectedSlug} />
        <FlyController target={flyTo} />
        <FrameController box={focusSlug ? null : (fitBox ?? frame)} />

        {on("states") && stateBoundaries.data && (
          <StateLayer
            key={`states-${boundaryZoom}-${stateFilter ?? ""}`}
            features={stateBoundaries.data.features}
            selected={stateFilter}
            attribution={layerDefs.states?.attribution}
            onSelect={setStateFilter}
          />
        )}
        {on("districts") && districtBoundaries.data && (
          <GeoJSON
            key={`districts-${stateFilter}-${boundaryZoom}`}
            data={districtBoundaries.data as unknown as GeoJsonObject}
            style={() => ({ color: "#64748b", weight: 0.8, dashArray: "3 3", fillOpacity: 0 })}
            onEachFeature={(feature, layer) => {
              layer.bindTooltip((feature as BoundaryFeature).properties.name, { sticky: true });
            }}
          />
        )}

        {drawnShapes && geometryFeatures.length > 0 && (
          <HydrologyLayer
            key={`geo-${geometries.dataUpdatedAt}-${on("status_overlay")}-${[...highlighted].join()}`}
            features={geometryFeatures}
            statusOverlay={on("status_overlay")}
            highlighted={highlighted}
            onSelect={setSelectedSlug}
          />
        )}

        {on("water_points") &&
          points.map((feature) => (
            <CircleMarker
              key={`wb-${feature.id}`}
              center={[feature.latitude, feature.longitude]}
              radius={radiusFor(feature, zoom) + (highlighted.has(feature.slug) ? 3 : 0)}
              pathOptions={{
                color: highlighted.has(feature.slug) ? "#0c4a6e" : "#ffffff",
                weight: highlighted.has(feature.slug) ? 3 : 1.5,
                fillColor: on("status_overlay")
                  ? colourFor(feature.latest_available_status)
                  : WATER_FILL,
                fillOpacity: 0.85,
              }}
              eventHandlers={{ click: () => setSelectedSlug(feature.slug) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <strong>{feature.name}</strong>
                <br />
                {TYPE_META[feature.water_type]?.label ?? feature.water_type}
                <br />
                {feature.latest_available_status
                  ? `${STATUS_META[feature.latest_available_status].label} when last measured`
                  : "Not assessed"}
                <br />
                <span className="tooltip-date">{formatDay(feature.latest_observed_at)}</span>
              </Tooltip>
            </CircleMarker>
          ))}

        {on("stations") &&
          (clusters.data?.items ?? []).map((item, i) => (
            <ClusterMarker key={clusterKey(item, i)} item={item} statusOverlay={on("status_overlay")} />
          ))}
      </MapContainer>

      {highlighted.size > 0 && (
        <div className="wmap-banner" role="status">
          <Sparkles size={14} aria-hidden />
          <span>
            Showing {highlighted.size} water bod{highlighted.size === 1 ? "y" : "ies"} from an answer
          </span>
          <button type="button" onClick={() => setParams({})} aria-label="Clear highlighted results">
            Clear
          </button>
        </div>
      )}

      <div className="wmap-search-wrap">
        <MapSearch onPick={handlePick} />
      </div>

      <div className="wmap-controls">
        <button
          type="button"
          className={`wmap-ctl ${panel === "filters" ? "is-active" : ""}`}
          onClick={() => setPanel((p) => (p === "filters" ? null : "filters"))}
          aria-expanded={panel === "filters"}
        >
          <Filter size={15} aria-hidden /> Filters
        </button>
        <button
          type="button"
          className={`wmap-ctl ${panel === "layers" ? "is-active" : ""}`}
          onClick={() => setPanel((p) => (p === "layers" ? null : "layers"))}
          aria-expanded={panel === "layers"}
        >
          <Layers size={15} aria-hidden /> Layers
        </button>
      </div>

      {panel === "filters" && (
        <div className="wmap-filters">
          <div className="wmap-filter-group">
            <label htmlFor="state-filter">State / UT</label>
            <select
              id="state-filter"
              value={stateFilter ?? ""}
              onChange={(e) => setStateFilter(e.target.value || null)}
            >
              <option value="">All India</option>
              {(states.data?.items ?? [])
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name}
                  </option>
                ))}
            </select>
          </div>
          <div className="wmap-filter-group">
            <label htmlFor="type-filter">Water type</label>
            <select
              id="type-filter"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as WaterBodyType | "ALL")}
            >
              <option value="ALL">All types</option>
              {Object.entries(TYPE_META).map(([key, meta]) => (
                <option key={key} value={key}>
                  {meta.label}
                </option>
              ))}
            </select>
          </div>
          <div className="wmap-filter-group">
            <label htmlFor="status-filter">Status when last measured</label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as WaterStatus | "ALL")}
            >
              <option value="ALL">Any status</option>
              {Object.entries(STATUS_META).map(([key, meta]) => (
                <option key={key} value={key}>
                  {meta.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="wmap-filter-reset"
            onClick={() => {
              setTypeFilter("ALL");
              setStatusFilter("ALL");
              setStateFilter(null);
            }}
          >
            Reset
          </button>
        </div>
      )}

      {panel === "layers" && catalogue.data && layers && (
        <div className="wmap-filters wmap-layers" role="group" aria-label="Map layers">
          {catalogue.data.groups.map((group) => (
            <fieldset key={group.key} className="wmap-layer-group">
              <legend>{group.label}</legend>
              {group.layers
                .filter((l) => l.kind !== "detail_only")
                .map((l) => (
                  <label key={l.key} className="wmap-layer-row" title={l.note}>
                    <input
                      type="checkbox"
                      checked={Boolean(layers[l.key])}
                      disabled={l.key === "districts" && !stateFilter}
                      onChange={(e) => setLayers({ ...layers, [l.key]: e.target.checked })}
                    />
                    <span>
                      {l.label}
                      {l.min_zoom && zoom < l.min_zoom && layers[l.key] && (
                        <span className="muted-note"> (zoom in to see)</span>
                      )}
                      {l.key === "districts" && !stateFilter && (
                        <span className="muted-note"> (choose a state)</span>
                      )}
                    </span>
                  </label>
                ))}
              {group.layers
                .filter((l) => l.kind === "detail_only")
                .map((l) => (
                  <p key={l.key} className="muted-note">
                    {l.label}: {l.note}
                  </p>
                ))}
            </fieldset>
          ))}
          {geometries.data?.truncated && (
            <p className="muted-note">Zoom in to see every matched geometry in view.</p>
          )}
        </div>
      )}

      <div className="wmap-legend">
        <p className="wmap-legend-title">Status when last measured</p>
        {(
          [
            "POLLUTED_STRETCH",
            "HIGH_CONCERN",
            "ELEVATED",
            "WITHIN_REFERENCE",
            "NO_APPLICABLE_REFERENCE",
            "NO_RECENT_DATA",
          ] as WaterStatus[]
        ).map((key) => (
          <div className="wmap-legend-row" key={key}>
            <span className="wmap-legend-dot" style={{ background: STATUS_COLOUR[key] }} aria-hidden />
            <span>{STATUS_META[key].label}</span>
          </div>
        ))}
        <div className="wmap-legend-row">
          <span className="wmap-legend-line" style={{ background: WATER_BLUE }} aria-hidden />
          <span>Matched river / lake shape</span>
        </div>
        <p className="wmap-legend-note">
          Water stays blue; colour shows what the most recent measurement found, with its date —
          not the water body&rsquo;s condition today.
        </p>
      </div>

      <div className="wmap-count">
        {loading ? (
          <>
            <Loader2 size={13} className="spin" aria-hidden /> Loading…
          </>
        ) : (
          <>
            <MapPin size={13} aria-hidden />{" "}
            {(bodies.data?.items.length ?? 0) >= POINT_LIMIT
              ? `${POINT_LIMIT.toLocaleString()} most-sampled shown — zoom in for all`
              : `${shownCount} water bodies in view`}
            {stateFilter && <> · {stateFilter}</>}
          </>
        )}
      </div>

      {nothingInView && (
        <div className="wmap-empty" role="status">
          <p>
            <strong>No monitored water bodies in this view.</strong>
          </p>
          <p className="muted-note">
            Only water bodies with a CPCB monitoring station appear. An empty area means no
            station in the source data, not clean water.
          </p>
        </div>
      )}

      {(bodies.isError || geometries.isError || clusters.isError) && (
        <div className="wmap-error">
          <ErrorState
            error={bodies.error ?? geometries.error ?? clusters.error}
            onRetry={() => {
              bodies.refetch();
              geometries.refetch();
              clusters.refetch();
            }}
          />
        </div>
      )}

      {selectedSlug && (
        <aside className="wmap-panel" aria-label="Water body details">
          <button
            type="button"
            className="wmap-panel-close"
            onClick={() => setSelectedSlug(null)}
            aria-label="Close details"
          >
            <X size={16} />
          </button>
          <MapPanel slug={selectedSlug} />
        </aside>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Layers                                                              */
/* ------------------------------------------------------------------ */

function StateLayer({
  features,
  selected,
  attribution,
  onSelect,
}: {
  features: BoundaryFeature[];
  selected: string | null;
  attribution?: string;
  onSelect: (code: string | null) => void;
}) {
  const base = (f: BoundaryFeature): PathOptions => {
    const isSelected = f.properties.state_code != null && f.properties.state_code === selected;
    return {
      color: isSelected ? "#0c4a6e" : "#475569",
      weight: isSelected ? 2.2 : 0.9,
      fillColor: "#0c4a6e",
      fillOpacity: isSelected ? 0.04 : 0,
    };
  };
  return (
    <GeoJSON
      data={{ type: "FeatureCollection", features } as unknown as GeoJsonObject}
      attribution={attribution}
      style={(f) => base(f as unknown as BoundaryFeature)}
      onEachFeature={(feature: Feature, layer) => {
        const f = feature as unknown as BoundaryFeature;
        const path = layer as L.Path;
        layer.bindTooltip(
          `${f.properties.name}${f.properties.has_water_data ? "" : " — no water data in the source"}`,
          { sticky: true },
        );
        layer.on({
          mouseover: () => path.setStyle({ weight: 2, color: "#0c4a6e" }),
          mouseout: () => path.setStyle(base(f)),
          click: () => {
            if (f.properties.state_code) {
              onSelect(f.properties.state_code === selected ? null : f.properties.state_code);
            }
          },
        });
      }}
    />
  );
}

function HydrologyLayer({
  features,
  statusOverlay,
  highlighted,
  onSelect,
}: {
  features: GeometryFeature[];
  statusOverlay: boolean;
  highlighted: Set<string>;
  onSelect: (slug: string) => void;
}) {
  const collection = { type: "FeatureCollection", features } as unknown as GeoJsonObject;
  const isLine = (f: GeometryFeature) => f.geometry.type.includes("Line");
  const bind = (feature: Feature, layer: L.Layer) => {
    const f = feature as unknown as GeometryFeature;
    const status = f.properties.latest_available_status;
    layer.bindTooltip(
      `<strong>${escapeHtml(f.properties.name)}</strong><br/>${
        status ? `${STATUS_META[status].label} when last measured` : "Not assessed"
      }${f.properties.clipped ? "<br/><em>Monitored reaches only</em>" : ""}`,
      { sticky: true },
    );
    layer.on({ click: () => onSelect(f.properties.slug) });
  };
  return (
    <>
      {statusOverlay && (
        // Casing: a wider status-coloured line under each river, so the
        // river itself is still drawn in water blue on top.
        <GeoJSON
          data={collection}
          filter={(f) => isLine(f as unknown as GeometryFeature)}
          style={(f) => ({
            color: colourFor((f as unknown as GeometryFeature).properties.latest_available_status),
            weight: 8,
            opacity: 0.45,
            lineCap: "round",
          })}
          interactive={false}
        />
      )}
      <GeoJSON
        data={collection}
        style={(feature) => {
          const f = feature as unknown as GeometryFeature;
          const hl = highlighted.has(f.properties.slug);
          if (isLine(f)) return { color: hl ? "#0c4a6e" : WATER_BLUE, weight: hl ? 5 : 3, opacity: 0.95 };
          return {
            color: statusOverlay ? colourFor(f.properties.latest_available_status) : WATER_BLUE,
            weight: hl ? 3.5 : statusOverlay ? 2.5 : 1,
            fillColor: WATER_FILL,
            fillOpacity: 0.45,
          };
        }}
        onEachFeature={bind}
      />
    </>
  );
}

function clusterKey(item: ClusterItem, i: number): string {
  return item.kind === "station" ? `st-${item.id}` : `cl-${i}-${item.count}-${item.latitude.toFixed(3)}`;
}

function ClusterMarker({ item, statusOverlay }: { item: ClusterItem; statusOverlay: boolean }) {
  const map = useMap();
  if (item.kind === "station") {
    return (
      <CircleMarker
        center={[item.latitude, item.longitude]}
        radius={3.5}
        pathOptions={{ color: "#1e3a8a", weight: 1, fillColor: "#60a5fa", fillOpacity: 0.95 }}
      >
        <Tooltip direction="top" offset={[0, -4]}>
          <strong>{item.name}</strong>
          <br />
          CPCB monitoring station
          <br />
          <span className="tooltip-date">latest {formatDay(item.latest_observed_at)}</span>
        </Tooltip>
      </CircleMarker>
    );
  }
  const ring = statusOverlay ? colourFor(item.worst_latest_available_status) : "#1e3a8a";
  const size = item.count >= 100 ? 40 : item.count >= 20 ? 34 : 28;
  const icon = L.divIcon({
    className: "wmap-cluster",
    html: `<span style="width:${size}px;height:${size}px;border-color:${ring}">${item.count}</span>`,
    iconSize: [size, size],
  });
  return (
    <Marker
      position={[item.latitude, item.longitude]}
      icon={icon}
      eventHandlers={{
        click: () => map.flyTo([item.latitude, item.longitude], Math.min(map.getZoom() + 2, 13)),
      }}
      keyboard
      title={`${item.count} monitoring stations — zoom in`}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Panel                                                               */
/* ------------------------------------------------------------------ */

function MapPanel({ slug }: { slug: string }) {
  const detail = useQuery({ queryKey: ["water-body", slug], queryFn: () => api.waterBody(slug) });
  const d = detail.data;
  return (
    <>
      {detail.isLoading && <p className="muted-note">Loading measurements…</p>}
      {d && (
        <>
          <h2 className="wmap-panel-title">{d.name}</h2>
          <div className="wmap-panel-tags">
            <WaterTypeTag type={d.water_type} />
            <DataQualityBadge level={d.data_quality.level} />
          </div>
          <p className="wmap-panel-place">{[d.district, d.state].filter(Boolean).join(", ")}</p>

          <div className="wmap-panel-block">
            <span className="wmap-panel-label">Latest measured status</span>
            {d.latest_available_status ? (
              <LatestAvailableStatus detail={d.latest_available_status} observedAt={d.latest_observed_at} />
            ) : (
              <WaterStatusBadge status={null} />
            )}
            <p className="muted-note">
              {d.reference.standard_name
                ? `Compared against ${d.reference.standard_name}.`
                : "Reference comparison unavailable."}
            </p>
          </div>

          <div className="wmap-panel-block">
            <span className="wmap-panel-label">Current data availability</span>
            <AvailabilityPanel availability={d.availability} />
          </div>

          <dl className="wmap-panel-facts">
            <div>
              <dt>Monitoring stations</dt>
              <dd>{d.station_count}</dd>
            </div>
            <div>
              <dt>Observations</dt>
              <dd>{d.observation_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Latest observation</dt>
              <dd>
                <CalendarClock size={12} aria-hidden /> {formatDay(d.latest_observed_at)}
              </dd>
            </div>
            <div>
              <dt>Shape</dt>
              <dd>{d.geometry ? `${d.geometry.geometry_type} · OSM, ${d.geometry.provenance.confidence}` : d.geometry_status_text}</dd>
            </div>
          </dl>

          <Link className="btn btn-primary btn-sm" to={`/app/water/${d.slug}`}>
            Open full record
          </Link>
        </>
      )}
      {detail.isError && <ErrorState error={detail.error} onRetry={() => detail.refetch()} />}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Map plumbing                                                        */
/* ------------------------------------------------------------------ */

/** Reports the viewport so features can be fetched for it alone. */
function ViewportReporter({ onChange }: { onChange: (bbox: string, zoom: number) => void }) {
  const report = (map: ReturnType<typeof useMap>) => {
    // Before layout the container has no size and the bounds collapse to a
    // line; a request for that box would return nothing and flash "empty".
    if (map.getSize().x === 0 || map.getSize().y === 0) return;
    const b = map.getBounds();
    onChange(
      [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].map((n) => n.toFixed(4)).join(","),
      map.getZoom(),
    );
  };
  const map = useMapEvents({ moveend: () => report(map), zoomend: () => report(map) });
  useEffect(() => {
    report(map);
    map.whenReady(() => {
      map.invalidateSize();
      report(map);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** The docked panel changes the map's width; Leaflet must be told. */
function SizeWatcher({ trigger }: { trigger: unknown }) {
  const map = useMap();
  useEffect(() => {
    const t = window.setTimeout(() => map.invalidateSize(), 50);
    return () => window.clearTimeout(t);
  }, [trigger, map]);
  return null;
}

function parseBox(raw: string | null): [[number, number], [number, number]] | null {
  if (!raw) return null;
  const parts = raw.split(",").map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
  return [
    [parts[0], parts[1]],
    [parts[2], parts[3]],
  ];
}

/** Frames the map around a box, once per distinct box. */
function FrameController({ box }: { box: [[number, number], [number, number]] | null }) {
  const map = useMap();
  const key = box ? box.flat().join(",") : "";
  useEffect(() => {
    if (box) map.fitBounds(box, { padding: [40, 40], maxZoom: 12 });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Flies the map when a search result is chosen. */
function FlyController({ target }: { target: [number, number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    map.flyTo([target[0], target[1]], target[2], { duration: 0.8 });
    // On a phone the detail sheet covers the lower ~60% of the map, so the
    // target is nudged into the visible upper part once the flight ends.
    if (window.innerWidth <= 860) {
      map.once("moveend", () => map.panBy([0, map.getSize().y * 0.28], { animate: true }));
    }
  }, [target, map]);
  return null;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/* ------------------------------------------------------------------ */
/* Search                                                              */
/* ------------------------------------------------------------------ */

function MapSearch({ onPick }: { onPick: (hit: SearchHit) => void }) {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);

  const results = useQuery({
    queryKey: ["water-search", term],
    queryFn: () => api.waterSearch(term, 12),
    enabled: term.trim().length >= 2,
  });
  const hits = results.data?.items ?? [];
  const askSuggested = results.data?.ask_suggested ?? false;
  const ask = () => navigate(`/app/water-ai?q=${encodeURIComponent(term.trim())}`);

  return (
    <div className="wmap-search">
      <Search size={16} aria-hidden className="wmap-search-icon" />
      <input
        type="text"
        value={term}
        placeholder="Search a river, lake, city or state — or ask a question"
        aria-label="Search water bodies, cities and states, or ask a question"
        onChange={(e) => {
          setTerm(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && askSuggested) ask();
        }}
      />
      {term && (
        <button
          type="button"
          className="wmap-search-clear"
          onClick={() => {
            setTerm("");
            setOpen(false);
          }}
          aria-label="Clear search"
        >
          <X size={14} />
        </button>
      )}

      {open && term.trim().length >= 2 && (
        <div className="wmap-search-results">
          {askSuggested && (
            <button type="button" className="wmap-search-hit wmap-search-ask" onClick={ask}>
              <span className="hit-title">
                <MessageSquareText size={13} aria-hidden /> Ask: “{term.trim()}”
              </span>
              <span className="hit-sub">Answered from stored data, with citations</span>
            </button>
          )}
          {results.isFetching && <p className="muted-note">Searching…</p>}
          {!results.isFetching && hits.length === 0 && !askSuggested && (
            <p className="muted-note">
              Nothing matches “{term}”. Only water bodies that appear in ingested CPCB data, the
              curated cities and states are searchable.
            </p>
          )}
          {hits.map((hit) => (
            <button
              type="button"
              key={`${hit.type}-${hit.slug}-${hit.title}`}
              className="wmap-search-hit"
              onClick={() => {
                onPick(hit);
                setOpen(false);
              }}
            >
              <span className="hit-title">{hit.title}</span>
              <span className="hit-sub">{hit.subtitle || hit.type}</span>
              {hit.latest_available_status && (
                <WaterStatusBadge status={hit.latest_available_status} size="sm" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
