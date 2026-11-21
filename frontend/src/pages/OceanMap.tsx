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
import { CircleMarker, MapContainer, Polygon, Rectangle, TileLayer, Tooltip } from "react-leaflet";
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
  const [showCandidates, setShowCandidates] = useState(true);
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateMapPoint | null>(null);

  // Full-scene SAR detection state (Phase 14.2)
  const [showFullScenes, setShowFullScenes] = useState(true);
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [selectedFootprint, setSelectedFootprint] = useState<CandidateFootprintFeature | null>(null);

  const { data: candidateMapPoints } = useQuery({
    queryKey: ["sar-candidate-map-points"],
    queryFn: () => api.sarCandidateMapPoints(),
  });

  const { data: sarScenesData } = useQuery({
    queryKey: ["sar-scenes"],
    queryFn: () => api.sarScenes({ limit: 200 }),
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
        subtitle={`${zones.length} monitored cells · ${detected} with an active detection · ${sarScenesData?.total ?? 0} SAR acquisition scenes`}
      />

      <MarineScopeNote />

      {data?.provenance.contains_simulated_data && <SimulatedBanner />}
      <SimulatedBanner detail="The full-scene SAR overlay and its footprint probabilities remain SYNTHETIC demonstration outputs — that layer alone. Detection markers come from measured Sentinel-2 acquisitions, and candidate points are the PANGAEA research benchmark." />

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

            {/* Full-Scene Sentinel-1 SAR acquisition frames */}
            {showFullScenes &&
              sarScenesData?.scenes.map((scene) => {
                const [minLon, minLat, maxLon, maxLat] = scene.bbox;
                const isSelected = scene.scene_id === selectedSceneId;
                return (
                  <Rectangle
                    key={scene.scene_id}
                    bounds={[
                      [minLat, minLon],
                      [maxLat, maxLon],
                    ]}
                    pathOptions={{
                      color: isSelected ? "#06b6d4" : "#0284c7",
                      weight: isSelected ? 2.5 : 1.2,
                      dashArray: isSelected ? undefined : "4, 4",
                      fillColor: "#0284c7",
                      fillOpacity: isSelected ? 0.08 : 0.03,
                    }}
                    eventHandlers={{
                      click: () => {
                        setSelectedSceneId(scene.scene_id);
                        setSelected(null);
                        setSelectedCandidate(null);
                        setSelectedFootprint(null);
                      },
                    }}
                  >
                    <Tooltip sticky>
                      <strong>Synthetic SAR Scene (Demo)</strong>
                      <br />
                      <span className="mono text-xs">{scene.scene_id}</span>
                      <br />
                      <span>{scene.platform} · {scene.polarization}</span>
                      <br />
                      <span>Candidate hits: {scene.candidate_count}</span>
                      {scene.candidate_tiles_detected !== null && (
                        <span> · Synthetic tiles: {scene.candidate_tiles_detected}</span>
                      )}
                    </Tooltip>
                  </Rectangle>
                );
              })}

            {/* Overlapping candidate footprints for selected SAR scene */}
            {showFullScenes &&
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
                checked={showCandidates}
                onChange={(event) => setShowCandidates(event.target.checked)}
              />
              SAR Candidates (Experimental)
            </label>
            <label className="map-toggle">
              <input
                type="checkbox"
                checked={showFullScenes}
                onChange={(event) => setShowFullScenes(event.target.checked)}
              />
              Full-Scene SAR (Synthetic Demo)
            </label>

            {showFullScenes && sarScenesData?.scenes && sarScenesData.scenes.length > 0 && (
              <label className="map-select-label">
                Active Synthetic Scene
                <select
                  className="map-select"
                  value={selectedSceneId || ""}
                  onChange={(event) => {
                    setSelectedSceneId(event.target.value || null);
                    setSelectedFootprint(null);
                  }}
                >
                  <option value="">(Select scene to view footprints)</option>
                  {sarScenesData.scenes.map((s) => (
                    <option key={s.scene_id} value={s.scene_id}>
                      {s.scene_id.substring(0, 30)}... ({s.candidate_count} hits)
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

            {showFullScenes && (
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
