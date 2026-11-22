/**
 * Interactive ocean map.
 *
 * Screening cells are drawn as rectangles from their real bounding boxes and
 * refinement sub-cells nest inside their parents, so the two-stage detection
 * pipeline is legible at a glance. Cells observed with no detection are drawn
 * too — a cell that was looked at and found clean is a result, and hiding it
 * would imply everywhere unmarked is unmonitored.
 *
 * Phase 14.2 adds full-scene Sentinel-1 SAR acquisition coverage boxes and
 * overlapping-window candidate footprint envelopes (stamped from 25% overlap inference).
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CircleMarker,
  MapContainer,
  Polygon,
  Polyline,
  Rectangle,
  TileLayer,
  Tooltip,
} from "react-leaflet";
import { Layers, X } from "lucide-react";
import { api } from "@/lib/api";
import type {
  CandidateFootprintFeature,
  CandidateMapPoint,
  Severity,
  Zone,
} from "@/lib/types";
import {
  ErrorState,
  EvidenceBadge,
  formatDateTime,
  LoadingSkeleton,
  MarineScopeNote,
  PageHeader,
  RiskBadge,
  severityColor,
  SimulatedBanner,
  titleise,
  Unavailable,
  ProvenanceNote,
} from "@/components/ui";

const CLEAN = "#94a3b8";

function colourFor(zone: Zone): string {
  return zone.severity ? severityColor(zone.severity) : CLEAN;
}

export default function OceanMap() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["zones"],
    queryFn: () => api.zones(1000),
  });

  const [selected, setSelected] = useState<Zone | null>(null);
  const [showClean, setShowClean] = useState(true);
  const [showRefined, setShowRefined] = useState(true);
  const [minSeverity, setMinSeverity] = useState<Severity | "ALL">("ALL");
  // Off by default: the benchmark set is Mediterranean, so it sits
  // outside this platform's area of interest and should not be the
  // first thing a reader sees on a map of India.
  const [showCandidates, setShowCandidates] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateMapPoint | null>(null);

  // Full-scene SAR detection state (Phase 14.2)
  const [showScreenedTiles, setShowScreenedTiles] = useState(true);
  // Real data layers, all on by default: this is now the main content of
  // the map rather than an overlay on a demonstration.
  const [showVessels, setShowVessels] = useState(true);
  const [showCurrents, setShowCurrents] = useState(true);
  const [showChlorophyll, setShowChlorophyll] = useState(false);
  const [showReplay, setShowReplay] = useState(true);
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [selectedFootprint, setSelectedFootprint] = useState<CandidateFootprintFeature | null>(null);

  const conditions = useQuery({
    queryKey: ["marine-conditions"],
    queryFn: () => api.marineConditions(),
  });
  const vessels = useQuery({
    queryKey: ["vessel-activity"],
    queryFn: () => api.vesselActivity(),
  });
  const replay = useQuery({
    queryKey: ["incident-replay"],
    queryFn: () => api.incidentReplay(),
  });
  // Real screened Sentinel-1 tiles, replacing the synthetic full-scene
  // overlay. Footprints and scores from acquisitions that happened.
  const s1 = useQuery({
    queryKey: ["sentinel1-screening"],
    queryFn: () => api.sentinel1Screening(),
  });

  const { data: candidateMapPoints } = useQuery({
    queryKey: ["sar-candidate-map-points"],
    queryFn: () => api.sarCandidateMapPoints(),
  });

  const { data: footprintsData } = useQuery({
    queryKey: ["sar-scene-footprints", selectedSceneId],
    queryFn: () => (selectedSceneId ? api.sarSceneFootprints(selectedSceneId) : null),
    enabled: !!selectedSceneId,
  });

  const zones = data?.items ?? [];
  const rank: Record<Severity, number> = {
    LOW: 0,
    MEDIUM: 1,
    HIGH: 2,
    CRITICAL: 3,
  };

  const visible = useMemo(() => {
    return zones.filter((zone) => {
      const refined = zone.region_code.includes("__");
      if (refined && !showRefined) return false;
      if (!zone.severity) return showClean && !refined;
      if (minSeverity !== "ALL" && rank[zone.severity] < rank[minSeverity]) {
        return false;
      }
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zones, showClean, showRefined, minSeverity]);

  const detected = zones.filter((zone) => zone.severity).length;

  if (isLoading) return <LoadingSkeleton rows={2} height={280} />;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <>
      <PageHeader
        title="Ocean Map"
        subtitle={[
          `${zones.length} monitored cells`,
          `${detected} with an active detection`,
          vessels.data?.totals
            ? `${vessels.data.totals.total_vessel_hours.toLocaleString()} vessel-hours`
            : null,
          s1.data?.totals
            ? `${s1.data.totals.tiles} Sentinel-1 tiles screened`
            : null,
          conditions.data?.items.some((c) => c.surface_current)
            ? `${conditions.data.items.filter((c) => c.surface_current).length} current fields`
            : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      />

      <MarineScopeNote />

      {data?.provenance.contains_simulated_data && <SimulatedBanner />}
      <ProvenanceNote>
        <strong>Every layer on this map is real.</strong> Detection markers
        come from measured Sentinel-2 acquisitions; the Sentinel-1 rectangles
        are tiles actually fetched and screened, scored by{" "}
        <code>sar-oil-slick-v2.2</code>; vessel activity, currents and
        chlorophyll come from Global Fishing Watch and Copernicus Marine. The
        benchmark layer, off by default, is the PANGAEA research set.
      </ProvenanceNote>

      <div className="map-shell">
        <div className="map-frame">
          {/* Indian EEZ. The monitored regions span 8.0-23.3 N and
              64.0-94.4 E, so this centre and zoom frame all 40 cells --
              Lakshadweep in the west to the Andamans in the east -- without
              the user having to pan. It used to open on [20, 40], the Red
              Sea, left over from the global region set. */}
          <MapContainer
            center={[15.5, 79]}
            zoom={4}
            minZoom={2}
            scrollWheelZoom
            worldCopyJump
            style={{ height: "100%", width: "100%" }}
          >
            {/* Standard OSM tiles: no API key, no sign-up */}
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />

            {/* Real screened Sentinel-1 tiles. Each rectangle is a tile
                that was fetched from Copernicus, prepared with the fixed
                decibel window and put through the v2.2 classifier. This
                replaced a synthetic overlay that drew plausible probability
                fields over nothing. */}
            {showScreenedTiles &&
              s1.data?.tiles
                .filter(
                  (tile) =>
                    !selectedSceneId || tile.scene_id === selectedSceneId,
                )
                .map((tile, index) => {
                  const [minLon, minLat, maxLon, maxLat] = tile.bbox;
                  return (
                    <Rectangle
                      key={`s1-${tile.scene_id}-${index}`}
                      bounds={[
                        [minLat, minLon],
                        [maxLat, maxLon],
                      ]}
                      pathOptions={{
                        color: tile.flagged ? "#B91C1C" : "#0284c7",
                        weight: tile.flagged ? 2 : 1,
                        fillColor: tile.flagged ? "#B91C1C" : "#0284c7",
                        fillOpacity: tile.flagged ? 0.25 : 0.06,
                      }}
                      eventHandlers={{
                        click: () => {
                          setSelectedSceneId(tile.scene_id);
                          setSelected(null);
                          setSelectedCandidate(null);
                          setSelectedFootprint(null);
                        },
                      }}
                    >
                      <Tooltip sticky>
                        <strong>Screened Sentinel-1 tile</strong>
                        <br />
                        <span className="mono text-xs">{tile.scene_id}</span>
                        <br />
                        <span>
                          {tile.region} · acquired {tile.acquired_on}
                        </span>
                        <br />
                        <span>
                          {tile.flagged
                            ? "Flagged"
                            : "No anomaly"}{" "}
                          · confidence {tile.confidence.toFixed(3)}
                        </span>
                        <br />
                        <em>Contains modified Copernicus Sentinel data</em>
                      </Tooltip>
                    </Rectangle>
                  );
                })}


            {/* Overlapping candidate footprints for selected SAR scene */}
            {showScreenedTiles &&
              footprintsData?.features.map((feature) => {
                const coords = feature.geometry.coordinates[0];
                const latLngs = coords.map(([lon, lat]) => [lat, lon] as [number, number]);
                const isFtSelected = selectedFootprint?.id === feature.id;
                return (
                  <Polygon
                    key={feature.id}
                    positions={latLngs}
                    pathOptions={{
                      color: isFtSelected ? "#f97316" : "#eab308",
                      weight: isFtSelected ? 2.5 : 1.5,
                      fillColor: "#f59e0b",
                      fillOpacity: isFtSelected ? 0.65 : 0.35,
                    }}
                    eventHandlers={{
                      click: () => {
                        setSelectedFootprint(feature);
                        setSelected(null);
                        setSelectedCandidate(null);
                      },
                    }}
                  >
                    <Tooltip sticky>
                      <strong>SAR Candidate Footprint: {feature.id}</strong>
                      <br />
                      <span>Model score (uncalibrated): {feature.properties.confidence_pct}%</span>
                      <br />
                      <span>
                        Contrast: {feature.properties.contrast_db} dB · Backscatter:{" "}
                        {feature.properties.mean_backscatter_db} dB
                      </span>
                    </Tooltip>
                  </Polygon>
                );
              })}

            {/* SAR Candidates Point Markers */}
            {/* Real vessel activity, aggregated. Radius scales with the
                square root of vessel-hours so a busy region reads as busy
                without a single cell swallowing the map. */}
            {showVessels &&
              vessels.data?.items
                .filter((item) => item.total_hours > 0)
                .map((item) => {
                  const region = conditions.data?.items.find(
                    (c) => c.cell_code === item.cell_code,
                  );
                  if (!region) return null;
                  return (
                    <CircleMarker
                      key={`gfw-${item.cell_code}`}
                      center={[region.latitude, region.longitude]}
                      radius={Math.min(26, 4 + Math.sqrt(item.total_hours) / 6)}
                      pathOptions={{
                        color: "#0E7490",
                        fillColor: "#0E7490",
                        fillOpacity: 0.18,
                        weight: 1.5,
                      }}
                    >
                      <Tooltip sticky>
                        <strong>{item.region_name}</strong>
                        <br />
                        {item.total_hours.toLocaleString()} vessel-hours ·{" "}
                        {item.vessel_count.toLocaleString()} vessels
                        <br />
                        <span>
                          {item.top_flags
                            .slice(0, 3)
                            .map((f) => `${f.flag} ${Math.round(f.hours)}h`)
                            .join(", ")}
                        </span>
                        <br />
                        <em>Powered by Global Fishing Watch · INFERRED</em>
                      </Tooltip>
                    </CircleMarker>
                  );
                })}

            {/* Surface currents. Drawn as a line from the region centre in
                the direction the water flows toward -- the oceanographic
                convention, which is 180 degrees from the meteorological one
                and worth stating on the tooltip for that reason. */}
            {showCurrents &&
              conditions.data?.items
                .filter((item) => item.surface_current)
                .map((item) => {
                  const current = item.surface_current!;
                  const bearing = (current.direction_deg * Math.PI) / 180;
                  // Length scaled for legibility, not to scale.
                  const length = Math.min(0.5, 0.12 + current.speed_ms * 1.2);
                  const end: [number, number] = [
                    item.latitude + Math.cos(bearing) * length,
                    item.longitude +
                      (Math.sin(bearing) * length) /
                        Math.max(Math.cos((item.latitude * Math.PI) / 180), 0.1),
                  ];
                  return (
                    <Polyline
                      key={`cur-${item.cell_code}`}
                      positions={[[item.latitude, item.longitude], end]}
                      pathOptions={{ color: "#2563EB", weight: 2, opacity: 0.8 }}
                    >
                      <Tooltip sticky>
                        <strong>{item.region_name}</strong>
                        <br />
                        {current.speed_ms.toFixed(3)} m/s toward{" "}
                        {current.direction_deg.toFixed(0)}&deg;
                        <br />
                        <span>Valid {current.valid_on}</span>
                        <br />
                        <em>Copernicus Marine · INFERRED · flows toward</em>
                      </Tooltip>
                    </Polyline>
                  );
                })}

            {/* Chlorophyll-a from Copernicus Marine ocean colour. Off by
                default: it is a cross-check for the NDCI readings rather
                than a detection layer. */}
            {showChlorophyll &&
              conditions.data?.items
                .filter((item) => item.chlorophyll)
                .map((item) => (
                  <CircleMarker
                    key={`chl-${item.cell_code}`}
                    center={[item.latitude, item.longitude]}
                    radius={9}
                    pathOptions={{
                      color: "#15803D",
                      fillColor: "#15803D",
                      fillOpacity: Math.min(
                        0.75,
                        0.12 + (item.chlorophyll!.chl_mg_m3 ?? 0) / 4,
                      ),
                      weight: 1,
                    }}
                  >
                    <Tooltip sticky>
                      <strong>{item.region_name}</strong>
                      <br />
                      Chlorophyll-a {item.chlorophyll!.chl_mg_m3.toFixed(2)} mg/m&sup3;
                      <br />
                      <span>Valid {item.chlorophyll!.valid_on}</span>
                      <br />
                      <em>Copernicus Marine ocean colour · OBSERVED</em>
                    </Tooltip>
                  </CircleMarker>
                ))}

            {/* The historical incident replay position. */}
            {showReplay &&
              replay.data?.items.map((item) => (
                <CircleMarker
                  key={`replay-${item.incident.imo}`}
                  center={[item.incident.latitude, item.incident.longitude]}
                  radius={10}
                  pathOptions={{
                    color: "#B91C1C",
                    fillColor: "transparent",
                    weight: 2.5,
                    dashArray: "4 3",
                  }}
                >
                  <Tooltip sticky>
                    <strong>{item.incident.name}</strong> (IMO {item.incident.imo})
                    <br />
                    Sank {item.incident.sank_at.slice(0, 10)} ·{" "}
                    {item.incident.position_text}
                    <br />
                    <span>
                      {item.screening.tiles_screened} tiles screened ·{" "}
                      {item.verdict}
                    </span>
                    <br />
                    <em>Historical incident replay</em>
                  </Tooltip>
                </CircleMarker>
              ))}

            {showCandidates &&
              candidateMapPoints?.map((cand) => (
                <CircleMarker
                  key={cand.candidate_id}
                  center={[cand.latitude, cand.longitude]}
                  radius={6}
                  pathOptions={{
                    color: cand.color,
                    fillColor: cand.color,
                    fillOpacity: 0.85,
                    weight: 1.5,
                  }}
                  eventHandlers={{
                    click: () => {
                      setSelectedCandidate(cand);
                      setSelected(null);
                      setSelectedFootprint(null);
                    },
                  }}
                >
                  <Tooltip sticky>
                    <strong>{cand.candidate_id}</strong>
                    <br />
                    <span>Screening: {titleise(cand.screening_status.replace(/_/g, " "))}</span>
                    <br />
                    <span>
                      Score: {(cand.raw_confidence * 100).toFixed(1)}% · Wind:{" "}
                      {cand.wind_speed_ms !== null ? `${cand.wind_speed_ms.toFixed(1)} m/s` : "—"}
                    </span>
                  </Tooltip>
                </CircleMarker>
              ))}

            {visible.map((zone) => {
              const [w, s, e, n] = zone.bbox;
              const refined = zone.region_code.includes("__");
              const colour = colourFor(zone);
              return (
                <Rectangle
                  key={zone.region_code}
                  bounds={[
                    [s, w],
                    [n, e],
                  ]}
                  pathOptions={{
                    color: refined ? "#7c3aed" : colour,
                    weight: refined ? 1.2 : zone.severity ? 1.6 : 1,
                    fillColor: colour,
                    fillOpacity: zone.severity ? (refined ? 0.6 : 0.28) : 0.14,
                  }}
                  eventHandlers={{
                    click: () => {
                      setSelected(zone);
                      setSelectedCandidate(null);
                      setSelectedFootprint(null);
                    },
                  }}
                >
                  <Tooltip sticky>
                    <strong>{zone.region_name}</strong>
                    <br />
                    {zone.severity
                      ? `${titleise(zone.signature)} · ${zone.severity}`
                      : "Observed — no anomaly"}
                  </Tooltip>
                </Rectangle>
              );
            })}
          </MapContainer>

          <div className="map-legend">
            <p className="map-legend-title">
              <Layers size={12} /> Layers
            </p>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showClean}
                onChange={(event) => setShowClean(event.target.checked)}
              />
              Observed · no anomaly
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showRefined}
                onChange={(event) => setShowRefined(event.target.checked)}
              />
              Stage-2 refined sub-cells
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showVessels}
                onChange={(event) => setShowVessels(event.target.checked)}
              />
              Vessel activity (Global Fishing Watch)
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showCurrents}
                onChange={(event) => setShowCurrents(event.target.checked)}
              />
              Surface currents (Copernicus Marine)
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showChlorophyll}
                onChange={(event) => setShowChlorophyll(event.target.checked)}
              />
              Chlorophyll-a (Copernicus Marine)
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showReplay}
                onChange={(event) => setShowReplay(event.target.checked)}
              />
              Historical incident replay
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showCandidates}
                onChange={(event) => setShowCandidates(event.target.checked)}
              />
              Benchmark dataset (Mediterranean, PANGAEA 980773)
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showScreenedTiles}
                onChange={(event) => setShowScreenedTiles(event.target.checked)}
              />
              Screened Sentinel-1 tiles (real)
            </label>

            {showScreenedTiles && s1.data?.scenes && s1.data.scenes.length > 0 && (
              <label className="map-select-label">
                Scene (real acquisition)
                <select
                  className="map-select"
                  value={selectedSceneId || ""}
                  onChange={(event) => {
                    setSelectedSceneId(event.target.value || null);
                    setSelectedFootprint(null);
                  }}
                >
                  <option value="">All screened acquisitions</option>
                  {s1.data.scenes.map((scene) => (
                    <option key={scene.scene_id} value={scene.scene_id}>
                      {scene.acquired_on} · {scene.region} ({scene.tiles} tiles,{" "}
                      {scene.flagged} flagged)
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label className="map-select-label">
              Minimum severity
              <select
                className="map-select"
                value={minSeverity}
                onChange={(event) =>
                  setMinSeverity(event.target.value as Severity | "ALL")
                }
              >
                <option value="ALL">All</option>
                <option value="LOW">Low+</option>
                <option value="MEDIUM">Medium+</option>
                <option value="HIGH">High+</option>
                <option value="CRITICAL">Critical</option>
              </select>
            </label>

            {showCandidates && (
              <div className="candidate-legend-block">
                <p className="candidate-legend-title">SAR Screening States</p>
                <div className="candidate-legend-items">
                  <span><i style={{ background: "#06b6d4" }} /> Standard</span>
                  <span><i style={{ background: "#ec4899" }} /> Low-wind</span>
                  <span><i style={{ background: "#f97316" }} /> Reviewed Slick</span>
                  <span><i style={{ background: "#64748b" }} /> Rejected</span>
                </div>
              </div>
            )}

            {showScreenedTiles && (
              <div className="candidate-legend-block">
                <p className="candidate-legend-title">Full-Scene Inference</p>
                <div className="candidate-legend-items">
                  <span><i style={{ background: "#0284c7" }} /> Scene Swath</span>
                  <span><i style={{ background: "#f59e0b" }} /> Candidate Tile</span>
                </div>
              </div>
            )}

            <div className="map-ramp">
              {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as Severity[]).map((severity) => (
                <span key={severity}>
                  <i style={{ background: severityColor(severity) }} />
                  {severity[0]}
                </span>
              ))}
              <span>
                <i style={{ background: CLEAN, opacity: 0.5 }} />
                clean
              </span>
            </div>
          </div>
        </div>

        {/* Footprint Side Panel */}
        {selectedFootprint && (
          <aside className="map-panel">
            <div className="map-panel-head">
              <div>
                <h2>SAR Candidate Footprint</h2>
                <p className="muted-note mono">{selectedFootprint.properties.footprint_id}</p>
              </div>
              <button
                className="icon-btn"
                onClick={() => setSelectedFootprint(null)}
                aria-label="Close footprint panel"
              >
                <X size={16} />
              </button>
            </div>

            <div className="map-panel-body">
              <div className="kv">
                <span>Scene Identifier</span>
                <span className="mono text-xs" style={{ wordBreak: "break-all" }}>{selectedSceneId}</span>
              </div>
              <div className="kv">
                <span>Tile Coordinates</span>
                <span className="mono text-xs">
                  Row {selectedFootprint.properties.tile_indices[0]}, Col {selectedFootprint.properties.tile_indices[1]}
                </span>
              </div>
              <div className="kv">
                <span>Model Version</span>
                <span className="mono text-xs">{selectedFootprint.properties.model_version}</span>
              </div>
              <div className="kv">
                <span>CNN Confidence</span>
                <span className="mono font-bold" style={{ color: "#ea580c" }}>
                  {selectedFootprint.properties.confidence_pct}%
                </span>
              </div>
              <div className="kv">
                <span>Contrast (ΔdB)</span>
                <span className="mono">{selectedFootprint.properties.contrast_db} dB</span>
              </div>
              <div className="kv">
                <span>Mean Backscatter</span>
                <span className="mono">{selectedFootprint.properties.mean_backscatter_db} dB</span>
              </div>
              <div className="kv">
                <span>Footprint Area</span>
                <span className="mono">{selectedFootprint.properties.area_km2} km²</span>
              </div>
              <div className="kv">
                <span>Centroid</span>
                <span className="mono text-xs">
                  {selectedFootprint.properties.centroid[0].toFixed(3)}°N, {selectedFootprint.properties.centroid[1].toFixed(3)}°E
                </span>
              </div>
              <div className="kv">
                <span>Screening Status</span>
                <span className="mono text-xs">{titleise(selectedFootprint.properties.screening_status.replace(/_/g, " "))}</span>
              </div>

              <div className="optical-scientific-notice" style={{ marginTop: "1rem" }}>
                <strong>Tiled Footprint Envelope:</strong> Geospatial bounding box reconstructed from
                25% overlapping sliding window inference. Sub-pixel boundaries are not manufactured.
              </div>

              <div className="map-panel-actions" style={{ marginTop: "1rem" }}>
                <Link className="btn btn-primary btn-sm w-full" to={`/app/candidate-review`}>
                  Open Marine Review Dashboard
                </Link>
              </div>
            </div>
          </aside>
        )}

        {/* Candidate Side Panel */}
        {selectedCandidate && !selectedFootprint && (
          <aside className="map-panel">
            <div className="map-panel-head">
              <div>
                <h2>SAR Candidate</h2>
                <p className="muted-note mono">{selectedCandidate.candidate_id}</p>
              </div>
              <button
                className="icon-btn"
                onClick={() => setSelectedCandidate(null)}
                aria-label="Close candidate panel"
              >
                <X size={16} />
              </button>
            </div>

            <div className="map-panel-body">
              <div className="sar-map-preview">
                <img
                  src={api.sarCandidateImageUrl(selectedCandidate.candidate_id)}
                  alt={selectedCandidate.candidate_id}
                  className="sar-map-thumb"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
              </div>

              <div className="kv">
                <span>Screening State</span>
                <span className="mono text-xs">{titleise(selectedCandidate.screening_status.replace(/_/g, " "))}</span>
              </div>
              <div className="kv">
                <span>Review Status</span>
                <span className="mono text-xs">{titleise(selectedCandidate.review_status.replace(/_/g, " "))}</span>
              </div>
              <div className="kv">
                <span>V2.2 Confidence</span>
                <span className="mono font-bold">{(selectedCandidate.raw_confidence * 100).toFixed(1)}%</span>
              </div>
              <div className="kv">
                <span>ERA5 Wind Speed</span>
                <span className="mono">
                  {selectedCandidate.wind_speed_ms !== null
                    ? `${selectedCandidate.wind_speed_ms.toFixed(2)} m/s`
                    : "—"}
                </span>
              </div>
              <div className="kv">
                <span>Location</span>
                <span className="mono text-xs">
                  {selectedCandidate.latitude.toFixed(3)}°N, {selectedCandidate.longitude.toFixed(3)}°E
                  {selectedCandidate.is_coastal ? " (Coastal)" : " (Offshore)"}
                </span>
              </div>
              <div className="kv">
                <span>Acquired</span>
                <span className="mono text-xs">{formatDateTime(selectedCandidate.acquisition_timestamp)}</span>
              </div>

              <div className="map-panel-actions">
                <Link
                  className="btn btn-primary btn-sm w-full"
                  to={`/app/candidate-review`}
                >
                  Open in Candidate Review Dashboard
                </Link>
              </div>
            </div>
          </aside>
        )}

        {/* Screening Cell Side Panel */}
        {selected && !selectedCandidate && !selectedFootprint && (
          <aside className="map-panel">
            <div className="map-panel-head">
              <div>
                <h2>{selected.region_name}</h2>
                <p className="muted-note">{selected.parent_region}</p>
              </div>
              <button
                className="icon-btn"
                onClick={() => setSelected(null)}
                aria-label="Close detail panel"
              >
                <X size={16} />
              </button>
            </div>

            <div className="map-panel-body">
              <div className="kv">
                <span>Status</span>
                <span>
                  {selected.severity ? (
                    <RiskBadge
                      severity={selected.severity}
                      score={selected.risk_score}
                    />
                  ) : (
                    <span className="clean-chip">Observed · no anomaly</span>
                  )}
                </span>
              </div>
              <div className="kv">
                <span>Signature</span>
                <span>
                  {selected.signature ? titleise(selected.signature) : "—"}
                </span>
              </div>
              <div className="kv">
                <span>Confidence</span>
                <span>
                  {selected.confidence !== null ? (
                    `${(selected.confidence * 100).toFixed(1)}%`
                  ) : (
                    <Unavailable />
                  )}
                </span>
              </div>
              <div className="kv">
                <span>Mean backscatter</span>
                <span>
                  {selected.mean_backscatter_db !== null ? (
                    `${selected.mean_backscatter_db} dB`
                  ) : (
                    <Unavailable />
                  )}
                </span>
              </div>
              <div className="kv">
                <span>Platform</span>
                <span>{selected.platform}</span>
              </div>
              <div className="kv">
                <span>Last observed</span>
                <span>{formatDateTime(selected.last_observed_at)}</span>
              </div>
              <div className="kv">
                <span>Evidence</span>
                <span>
                  <EvidenceBadge level={selected.observation_evidence_level} />
                </span>
              </div>

              {selected.event_id ? (
                <div className="map-panel-actions">
                  <Link
                    className="btn btn-primary btn-sm"
                    to={`/app/risk/${selected.event_id}`}
                  >
                    Risk breakdown
                  </Link>
                  <Link
                    className="btn btn-outline btn-sm"
                    to={`/app/agents?event=${selected.event_id}`}
                  >
                    Agent analysis
                  </Link>
                </div>
              ) : (
                <p className="muted-note">
                  This cell was observed and no anomaly was detected. An explicit
                  negative is a result, not a gap in coverage.
                </p>
              )}
            </div>
          </aside>
        )}
      </div>
    </>
  );
}
