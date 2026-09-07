/**
 * Interactive ocean map.
 *
 * Screening cells are drawn as rectangles from their real bounding boxes and
 * refinement sub-cells nest inside their parents, so the two-stage detection
 * pipeline is legible at a glance. Cells observed with no detection are drawn
 * too — a cell that was looked at and found clean is a result, and hiding it
 * would imply everywhere unmarked is unmonitored.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MapContainer, Rectangle, TileLayer, Tooltip } from "react-leaflet";
import { Layers, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Severity, Zone } from "@/lib/types";
import {
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  RiskBadge,
  SimulatedBanner,
  Unavailable,
  formatDateTime,
  severityColor,
  titleise,
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
        subtitle={`${zones.length} monitored cells · ${detected} with an active detection`}
      />

      {data?.provenance.contains_simulated_data && <SimulatedBanner />}

      <div className="map-shell">
        <div className="map-frame">
          <MapContainer
            center={[20, 40]}
            zoom={3}
            minZoom={2}
            scrollWheelZoom
            worldCopyJump
            style={{ height: "100%", width: "100%" }}
          >
            {/* Standard OSM tiles: no API key, no sign-up. The CARTO light
                basemap looks better but now requires a key, and a map that
                renders "API KEY REQUIRED" across the ocean is worse than a
                plainer one that works. */}
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />
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
                  eventHandlers={{ click: () => setSelected(zone) }}
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

        {selected && (
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
