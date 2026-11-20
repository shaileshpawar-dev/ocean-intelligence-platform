/**
 * Pollution Events.
 *
 * A detection is a claim, not a confirmed incident, so every row carries its
 * evidence level and every detail panel leads with the caveats the detector
 * attached rather than burying them.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Filter, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Severity } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  EvidenceBadge,
  formatDateTime,
  LoadingSkeleton,
  MarineScopeNote,
  PageHeader,
  RiskBadge,
  SectionCard,
  SimulatedBanner,
  titleise,
  Unavailable,
  Value,
} from "@/components/ui";

const SEVERITIES: (Severity | "ALL")[] = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

function EventDetailPanel({ eventId, onClose }: { eventId: string; onClose: () => void }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => api.event(eventId),
  });

  return (
    <aside className="detail-panel" aria-label="Detection detail">
      <div className="detail-head">
        <div>
          <h2>{data ? titleise(data.signature) : "Detection"}</h2>
          <p className="muted-note mono">{eventId}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>

      <div className="detail-body">
        {isLoading && <LoadingSkeleton rows={4} height={44} />}
        {isError && <ErrorState error={error} />}
        {data && (
          <>
            <div className="detail-hero">
              <RiskBadge severity={data.severity} score={data.risk_score} />
              <EvidenceBadge level={data.evidence_level} />
            </div>

            <h3 className="detail-section">Detection</h3>
            <div className="kv">
              <span>Signature</span>
              <span>{titleise(data.signature)}</span>
            </div>
            <div className="kv">
              <span>Confidence</span>
              <span>
                {(data.confidence * 100).toFixed(2)}%
                <em className="cal-flag">
                  {data.confidence_is_calibrated ? "calibrated" : "uncalibrated score"}
                </em>
              </span>
            </div>
            <div className="kv">
              <span>Method</span>
              <span className="mono">{data.detection_method}</span>
            </div>
            <div className="kv">
              <span>Model</span>
              <span className="mono">{data.model_version ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Area</span>
              <span>
                <Value value={data.estimated_area_km2} suffix=" km²" digits={0} />
              </span>
            </div>

            <h3 className="detail-section">Location</h3>
            <div className="kv">
              <span>Region</span>
              <span>{data.region_name}</span>
            </div>
            <div className="kv">
              <span>Coordinates</span>
              <span className="mono">
                {data.latitude.toFixed(3)}, {data.longitude.toFixed(3)}
              </span>
            </div>
            <div className="kv">
              <span>Distance to coast</span>
              <span>
                <Value
                  value={data.geographic_context?.distance_to_coast_km ?? null}
                  suffix=" km"
                  digits={0}
                />
              </span>
            </div>
            <div className="kv">
              <span>Nearest protected area</span>
              <span className="wrap">
                {data.geographic_context?.nearest_protected_area ?? <Unavailable />}
              </span>
            </div>

            {data.observation && (
              <>
                <h3 className="detail-section">
                  Source measurement <EvidenceBadge level="OBSERVED" />
                </h3>
                <div className="kv">
                  <span>Collection</span>
                  <span className="mono">{data.observation.collection}</span>
                </div>
                <div className="kv">
                  <span>Acquired</span>
                  <span>{formatDateTime(data.observation.acquired_at)}</span>
                </div>
                <div className="kv">
                  <span>Mean backscatter</span>
                  <span>
                    <Value value={data.observation.mean_db} suffix=" dB" />
                  </span>
                </div>
                <div className="kv">
                  <span>Contrast p90−p10</span>
                  <span>
                    {data.observation.p90_db !== null && data.observation.p10_db !== null
                      ? `${(data.observation.p90_db - data.observation.p10_db).toFixed(1)} dB`
                      : "—"}
                  </span>
                </div>
              </>
            )}

            {data.caveats.length > 0 && (
              <>
                <h3 className="detail-section">Caveats on this claim</h3>
                <ul className="caveat-list">
                  {data.caveats.map((caveat, index) => (
                    <li key={index}>{caveat}</li>
                  ))}
                </ul>
              </>
            )}

            <div className="detail-actions">
              <Link className="btn btn-primary btn-sm" to={`/app/risk/${eventId}`}>
                Risk breakdown
              </Link>
              <Link
                className="btn btn-outline btn-sm"
                to={`/app/agents?event=${eventId}`}
              >
                Run agent analysis
              </Link>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

export default function Events() {
  const { eventId } = useParams();
  const navigate = useNavigate();
  const [severity, setSeverity] = useState<Severity | "ALL">("ALL");
  const [signature, setSignature] = useState<string>("ALL");
  const [query, setQuery] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["events", severity, signature],
    queryFn: () =>
      api.events({
        limit: 500,
        severity: severity === "ALL" ? null : severity,
        signature: signature === "ALL" ? null : signature,
      }),
  });

  const all = data?.items ?? [];
  const signatures = [...new Set(all.map((event) => event.signature))];
  const rows = all.filter((event) =>
    query
      ? (event.region_name ?? "").toLowerCase().includes(query.toLowerCase())
      : true,
  );

  return (
    <>
      <PageHeader
        title="Pollution Events"
        subtitle="Detections made by the platform, ranked by risk. Each is a claim with stated uncertainty, not a confirmed incident."
      />

      <MarineScopeNote />

      {data?.provenance.contains_simulated_data && <SimulatedBanner />}

      <SectionCard padded={false}>
        <div className="toolbar">
          <span className="toolbar-icon">
            <Filter size={14} />
          </span>
          <input
            className="input"
            placeholder="Filter by region…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Filter by region"
          />
          <select
            className="select"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity | "ALL")}
            aria-label="Severity"
          >
            {SEVERITIES.map((option) => (
              <option key={option} value={option}>
                {option === "ALL" ? "All severities" : option}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={signature}
            onChange={(event) => setSignature(event.target.value)}
            aria-label="Signature"
          >
            <option value="ALL">All signatures</option>
            {signatures.map((option) => (
              <option key={option} value={option}>
                {titleise(option)}
              </option>
            ))}
          </select>
          <span className="toolbar-count">
            {rows.length} of {all.length}
          </span>
        </div>

        {isLoading ? (
          <LoadingSkeleton rows={6} height={46} />
        ) : isError ? (
          <ErrorState error={error} onRetry={() => refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No matching detections"
            message="No events match the current filter. Try widening the severity or clearing the region filter."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Signature / Region</th>
                  <th>Evidence</th>
                  <th className="num">Confidence</th>
                  <th className="num">Area km²</th>
                  <th className="num">Risk</th>
                  <th>Severity</th>
                  <th>Detected</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((event) => (
                  <tr
                    key={event.event_id}
                    onClick={() => navigate(`/app/events/${event.event_id}`)}
                    className={eventId === event.event_id ? "selected" : ""}
                    tabIndex={0}
                    onKeyDown={(keyEvent) => {
                      if (keyEvent.key === "Enter")
                        navigate(`/app/events/${event.event_id}`);
                    }}
                  >
                    <td>
                      <strong>{titleise(event.signature)}</strong>
                      <span className="cell-sub">{event.region_name}</span>
                    </td>
                    <td>
                      <EvidenceBadge level={event.evidence_level} />
                    </td>
                    <td className="num">{(event.confidence * 100).toFixed(1)}%</td>
                    <td className="num">
                      <Value
                        value={event.estimated_area_km2}
                        digits={0}
                        fallback="dash"
                      />
                    </td>
                    <td className="num">
                      <Value value={event.risk_score} digits={1} fallback="dash" />
                    </td>
                    <td>
                      <RiskBadge severity={event.severity} />
                    </td>
                    <td className="muted-note">
                      {formatDateTime(event.detected_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {eventId && (
        <EventDetailPanel
          eventId={eventId}
          onClose={() => navigate("/app/events")}
        />
      )}
    </>
  );
}
