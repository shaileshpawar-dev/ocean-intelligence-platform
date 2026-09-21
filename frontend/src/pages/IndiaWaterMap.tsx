/**
 * India water map — the platform's primary surface.
 *
 * Design decisions worth stating:
 *
 * **The map is the page.** Not a widget inside a dashboard. Filters and the
 * detail panel float over it, so the geography always has the full viewport.
 *
 * **Features are fetched per viewport.** The map sends its bounding box and
 * the backend filters in SQL against an index. Loading every station in India
 * at zoom 5 would be both slow and pointless.
 *
 * **Colour encodes the last measurement, not the present.** Every Indian
 * water body here currently has a present-tense status of "no recent data",
 * because the newest CPCB publication is from 2021. Colouring by that would
 * produce a uniformly grey and useless map, so markers are coloured by what
 * the most recent measurement found — and the panel, the legend and every
 * tooltip say so with the date attached.
 *
 * **Colour is never the only channel.** Marker shape varies by water-body
 * type and every marker carries a text label in its tooltip.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import {
  CalendarClock,
  Filter,
  Sparkles,
  Layers,
  Loader2,
  MapPin,
  Search,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  MapFeature,
  SearchHit,
  StationSummary,
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
import { ErrorState } from "@/components/ui";

/* India, comfortably framed including the island territories. */
const INDIA_CENTRE: [number, number] = [22.0, 79.0];
const INDIA_BOUNDS: LatLngBoundsExpression = [
  [6.0, 68.0],
  [37.5, 97.5],
];

/**
 * Status colours.
 *
 * Deliberately not a red/green wash over the whole map: water stays blue and
 * only the status markers carry warning colour, so the map still reads as a
 * map. "Unknown" is grey rather than green — absence of data must never look
 * like a clean bill of health.
 */
const STATUS_COLOUR: Record<WaterStatus, string> = {
  WITHIN_REFERENCE: "#0e9f6e",
  ELEVATED: "#d97706",
  HIGH_CONCERN: "#e02424",
  POLLUTED_STRETCH: "#9b1c1c",
  INSUFFICIENT_DATA: "#94a3b8",
  NO_RECENT_DATA: "#94a3b8",
};

const UNKNOWN_COLOUR = "#94a3b8";

function colourFor(status: WaterStatus | null | undefined): string {
  return status ? STATUS_COLOUR[status] : UNKNOWN_COLOUR;
}

function radiusFor(feature: MapFeature, zoom: number): number {
  const base = zoom >= 9 ? 7 : zoom >= 7 ? 6 : 5;
  return feature.station_count > 3 ? base + 2 : base;
}

type LayerKey = "waterBodies" | "stations";

export default function IndiaWaterMap() {
  const [bbox, setBbox] = useState<string | null>(null);
  const [zoom, setZoom] = useState(5);
  const [selected, setSelected] = useState<MapFeature | null>(null);
  const [typeFilter, setTypeFilter] = useState<WaterBodyType | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<WaterStatus | "ALL">("ALL");
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    waterBodies: true,
    stations: false,
  });
  const [showFilters, setShowFilters] = useState(false);
  const [flyTo, setFlyTo] = useState<[number, number, number] | null>(null);
  // A searched water body is selected once the viewport fetch that the
  // fly-to triggers has returned it, so the panel opens on real map data.
  const [pendingSlug, setPendingSlug] = useState<string | null>(null);

  // Links from the Q&A page: ?highlight=a,b rings those water bodies,
  // ?bbox= frames them, ?focus= flies to one and opens its panel. This is
  // what makes a citation click land on the evidence.
  const [params, setParams] = useSearchParams();
  const highlighted = useMemo(
    () => new Set((params.get("highlight") ?? "").split(",").filter(Boolean)),
    [params],
  );
  const frame = useMemo(() => parseBox(params.get("bbox")), [params]);
  const focusSlug = params.get("focus");

  const focusTarget = useQuery({
    queryKey: ["water-body", focusSlug],
    queryFn: () => api.waterBody(focusSlug as string),
    enabled: Boolean(focusSlug),
  });

  useEffect(() => {
    const target = focusTarget.data;
    if (target && target.latitude != null && target.longitude != null) {
      setFlyTo([target.latitude, target.longitude, 12]);
      setPendingSlug(target.slug);
    }
  }, [focusTarget.data]);

  const bodies = useQuery({
    queryKey: ["map-water-bodies", bbox, typeFilter, statusFilter],
    queryFn: () =>
      api.mapWaterBodies({
        bbox,
        water_type: typeFilter === "ALL" ? null : typeFilter,
        status: statusFilter === "ALL" ? null : statusFilter,
        limit: 1200,
      }),
    placeholderData: (previous) => previous,
  });

  const stations = useQuery({
    queryKey: ["map-stations", bbox],
    queryFn: () => api.mapStations({ bbox, limit: 1200 }),
    enabled: layers.stations,
    placeholderData: (previous) => previous,
  });

  const features = useMemo(() => bodies.data?.items ?? [], [bodies.data]);

  useEffect(() => {
    if (!pendingSlug) return;
    const match = features.find((f) => f.slug === pendingSlug);
    if (match) {
      setSelected(match);
      setPendingSlug(null);
    }
  }, [features, pendingSlug]);

  const handleViewport = useCallback((box: string, nextZoom: number) => {
    setBbox(box);
    setZoom(nextZoom);
  }, []);

  const handlePick = useCallback((hit: SearchHit) => {
    if (hit.latitude != null && hit.longitude != null) {
      setFlyTo([hit.latitude, hit.longitude, hit.type === "water_body" ? 12 : 10]);
    }
    if (hit.type === "water_body") setPendingSlug(hit.slug);
  }, []);

  return (
    <div className="wmap-shell">
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

        <ViewportReporter onChange={handleViewport} />
        <FlyController target={flyTo} />
        <FrameController box={focusSlug ? null : frame} />

        {layers.waterBodies &&
          features.map((feature) => (
            <CircleMarker
              key={`wb-${feature.id}`}
              center={[feature.latitude, feature.longitude]}
              radius={radiusFor(feature, zoom) + (highlighted.has(feature.slug) ? 3 : 0)}
              pathOptions={{
                color: highlighted.has(feature.slug) ? "#0c4a6e" : "#ffffff",
                weight: highlighted.has(feature.slug) ? 3 : 1.5,
                fillColor: colourFor(feature.latest_available_status),
                fillOpacity: 0.85,
              }}
              eventHandlers={{ click: () => setSelected(feature) }}
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
                <span className="tooltip-date">
                  {formatDay(feature.latest_observed_at)}
                </span>
              </Tooltip>
            </CircleMarker>
          ))}

        {layers.stations &&
          (stations.data?.items ?? [])
            .filter((s): s is StationSummary & { latitude: number; longitude: number } =>
              s.latitude != null && s.longitude != null,
            )
            .map((station) => (
              <CircleMarker
                key={`st-${station.id}`}
                center={[station.latitude, station.longitude]}
                radius={3}
                pathOptions={{
                  color: "#1e40af",
                  weight: 1,
                  fillColor: "#60a5fa",
                  fillOpacity: 0.9,
                }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <strong>{station.name}</strong>
                  <br />
                  {station.observation_count} observations
                  <br />
                  <span className="tooltip-date">
                    latest {formatDay(station.latest_observed_at)}
                  </span>
                </Tooltip>
              </CircleMarker>
            ))}
      </MapContainer>

      {highlighted.size > 0 && (
        <div className="wmap-banner" role="status">
          <Sparkles size={14} aria-hidden />
          <span>
            Showing {highlighted.size} water bod
            {highlighted.size === 1 ? "y" : "ies"} from an answer
          </span>
          <button
            type="button"
            onClick={() => setParams({})}
            aria-label="Clear highlighted results"
          >
            Clear
          </button>
        </div>
      )}

      {/* -- Floating search ------------------------------------------- */}
      <div className="wmap-search-wrap">
        <MapSearch onPick={handlePick} />
      </div>

      {/* -- Floating controls ----------------------------------------- */}
      <div className="wmap-controls">
        <button
          type="button"
          className={`wmap-ctl ${showFilters ? "is-active" : ""}`}
          onClick={() => setShowFilters((v) => !v)}
          aria-expanded={showFilters}
        >
          <Filter size={15} aria-hidden /> Filters
        </button>
        <button
          type="button"
          className={`wmap-ctl ${layers.stations ? "is-active" : ""}`}
          onClick={() =>
            setLayers((l) => ({ ...l, stations: !l.stations }))
          }
          aria-pressed={layers.stations}
        >
          <Layers size={15} aria-hidden /> Stations
        </button>
      </div>

      {showFilters && (
        <div className="wmap-filters">
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
            }}
          >
            Reset
          </button>
        </div>
      )}

      {/* -- Legend ---------------------------------------------------- */}
      <div className="wmap-legend">
        <p className="wmap-legend-title">Status when last measured</p>
        {(
          [
            "POLLUTED_STRETCH",
            "HIGH_CONCERN",
            "ELEVATED",
            "WITHIN_REFERENCE",
            "NO_RECENT_DATA",
          ] as WaterStatus[]
        ).map((key) => (
          <div className="wmap-legend-row" key={key}>
            <span
              className="wmap-legend-dot"
              style={{ background: STATUS_COLOUR[key] }}
              aria-hidden
            />
            <span>{STATUS_META[key].label}</span>
          </div>
        ))}
        <p className="wmap-legend-note">
          Colour shows what the most recent measurement found, with its date —
          not the water body&rsquo;s condition today.
        </p>
      </div>

      {/* -- Count / loading ------------------------------------------- */}
      <div className="wmap-count">
        {bodies.isFetching ? (
          <>
            <Loader2 size={13} className="spin" aria-hidden /> Loading…
          </>
        ) : (
          <>
            <MapPin size={13} aria-hidden /> {features.length} water bodies in view
          </>
        )}
      </div>

      {bodies.isError && (
        <div className="wmap-error">
          <ErrorState error={bodies.error} onRetry={() => bodies.refetch()} />
        </div>
      )}

      {/* -- Detail panel ---------------------------------------------- */}
      {selected && (
        <aside className="wmap-panel" aria-label={`Details for ${selected.name}`}>
          <button
            type="button"
            className="wmap-panel-close"
            onClick={() => setSelected(null)}
            aria-label="Close details"
          >
            <X size={16} />
          </button>
          <MapPanel feature={selected} />
        </aside>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function MapPanel({ feature }: { feature: MapFeature }) {
  const detail = useQuery({
    queryKey: ["water-body", feature.slug],
    queryFn: () => api.waterBody(feature.slug),
  });

  return (
    <>
      <h2 className="wmap-panel-title">{feature.name}</h2>
      <div className="wmap-panel-tags">
        <WaterTypeTag type={feature.water_type} />
      </div>

      {detail.isLoading && <p className="muted-note">Loading measurements…</p>}

      {detail.data && (
        <>
          <p className="wmap-panel-place">
            {[detail.data.district, detail.data.state].filter(Boolean).join(", ")}
          </p>

          <div className="wmap-panel-block">
            <span className="wmap-panel-label">Right now</span>
            <WaterStatusBadge status={detail.data.status_detail.status} />
            <p className="muted-note">
              {detail.data.status_detail.freshness.summary}
            </p>
          </div>

          {detail.data.latest_available_status && (
            <div className="wmap-panel-block">
              <span className="wmap-panel-label">When last measured</span>
              <LatestAvailableStatus
                detail={detail.data.latest_available_status}
                observedAt={detail.data.latest_observed_at}
              />
            </div>
          )}

          <dl className="wmap-panel-facts">
            <div>
              <dt>Monitoring stations</dt>
              <dd>{feature.station_count}</dd>
            </div>
            <div>
              <dt>Observations</dt>
              <dd>{feature.observation_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Latest observation</dt>
              <dd>
                <CalendarClock size={12} aria-hidden />{" "}
                {formatDay(feature.latest_observed_at)}
              </dd>
            </div>
          </dl>

          <Link className="btn btn-primary btn-sm" to={`/app/water/${feature.slug}`}>
            Open full record
          </Link>
        </>
      )}

      {detail.isError && (
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

/** Reports the viewport so features can be fetched for it alone. */
function ViewportReporter({
  onChange,
}: {
  onChange: (bbox: string, zoom: number) => void;
}) {
  const report = (map: ReturnType<typeof useMap>) => {
    const b = map.getBounds();
    onChange(
      [
        b.getSouth().toFixed(4),
        b.getWest().toFixed(4),
        b.getNorth().toFixed(4),
        b.getEast().toFixed(4),
      ].join(","),
      map.getZoom(),
    );
  };

  const map = useMapEvents({
    moveend: () => report(map),
    zoomend: () => report(map),
  });

  // Report once on mount so the first fetch is scoped too.
  useMemo(() => report(map), []); // eslint-disable-line react-hooks/exhaustive-deps
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

/** Frames the map around an answer's results, once per distinct box. */
function FrameController({
  box,
}: {
  box: [[number, number], [number, number]] | null;
}) {
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
  useMemo(() => {
    if (target) map.flyTo([target[0], target[1]], target[2], { duration: 0.8 });
  }, [target, map]);
  return null;
}

/* ------------------------------------------------------------------ */

function MapSearch({ onPick }: { onPick: (hit: SearchHit) => void }) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);

  const results = useQuery({
    queryKey: ["water-search", term],
    queryFn: () => api.waterSearch(term, 12),
    enabled: term.trim().length >= 2,
  });

  const hits = results.data?.items ?? [];

  return (
    <div className="wmap-search">
      <Search size={16} aria-hidden className="wmap-search-icon" />
      <input
        type="text"
        value={term}
        placeholder="Search any river, lake, city or state…"
        aria-label="Search water bodies, cities and states"
        onChange={(e) => {
          setTerm(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
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
          {results.isFetching && <p className="muted-note">Searching…</p>}
          {!results.isFetching && hits.length === 0 && (
            <p className="muted-note">
              Nothing matches “{term}”. Only water bodies that appear in
              ingested CPCB data are searchable.
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
