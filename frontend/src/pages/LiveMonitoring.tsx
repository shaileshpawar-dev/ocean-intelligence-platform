/**
 * Live Monitoring.
 *
 * A short-poll view of current platform activity. Ingestion and refinement can
 * be triggered here because they are the two operations that actually change
 * what the rest of the console shows.
 */

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCw, Satellite, ZoomIn } from "lucide-react";
import { api } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  EvidenceBadge,
  formatDateTime,
  formatTime,
  LoadingSkeleton,
  MarineScopeNote,
  MetricCard,
  PageHeader,
  RiskBadge,
  SectionCard,
  titleise,
  Unavailable,
} from "@/components/ui";

export default function LiveMonitoring() {
  const queryClient = useQueryClient();

  const [health, overview, events, metrics, detectors] = useQueries({
    queries: [
      { queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 },
      { queryKey: ["overview"], queryFn: api.overview, refetchInterval: 30_000 },
      {
        queryKey: ["events", "live"],
        queryFn: () => api.events({ limit: 25 }),
        refetchInterval: 30_000,
      },
      { queryKey: ["metrics", 7], queryFn: () => api.metrics(7) },
      { queryKey: ["detectors"], queryFn: api.detectors },
    ],
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries();
  };

  const ingest = useMutation({ mutationFn: () => api.ingest(), onSuccess: invalidateAll });
  const refine = useMutation({
    mutationFn: () => api.refine(5),
    onSuccess: invalidateAll,
  });

  const activeDetector = detectors.data?.find((detector) => detector.available);

  if (health.isLoading && overview.isLoading) {
    return <LoadingSkeleton rows={4} height={88} />;
  }

  return (
    <>
      <PageHeader
        title="Live Monitoring"
        subtitle="Current platform activity, recent detections and pipeline controls."
        actions={
          <div className="badge-row">
            <button
              className="btn btn-outline btn-sm"
              onClick={() => ingest.mutate()}
              disabled={ingest.isPending}
            >
              <Satellite size={13} />
              {ingest.isPending ? "Ingesting…" : "Run ingestion"}
            </button>
            <button
              className="btn btn-outline btn-sm"
              onClick={() => refine.mutate()}
              disabled={refine.isPending}
            >
              <ZoomIn size={13} />
              {refine.isPending ? "Refining…" : "Stage-2 refine"}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={invalidateAll}>
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
        }
      />

      <MarineScopeNote />

      {(ingest.isError || refine.isError) && (
        <ErrorState error={ingest.error ?? refine.error} />
      )}

      {(ingest.data || refine.data) && (
        <div className="inline-note success">
          <Activity size={14} />
          <span>
            {ingest.data
              ? `Ingestion complete — ${String(ingest.data.observations_stored)} observation(s) stored, ${String(ingest.data.events_created)} event(s) created, ${String(ingest.data.negatives_recorded)} cell(s) explicitly clean.`
              : `Refinement complete — ${String(refine.data?.cells_refined)} cell(s) refined, ${String(refine.data?.events_created)} event(s) created.`}
          </span>
        </div>
      )}

      <div className="metric-grid">
        <MetricCard
          icon={<Activity size={15} />}
          label="Service status"
          value={
            <span className="metric-text">
              {health.data?.status === "ok" ? "Operational" : "Degraded"}
            </span>
          }
          detail={`Checked ${formatTime(health.data?.checked_at)}`}
          tone={health.data?.status === "ok" ? "ok" : "warn"}
        />
        <MetricCard
          icon={<Satellite size={15} />}
          label="Observations"
          value={overview.data?.observations ?? <Unavailable />}
          detail="Stored satellite measurements"
          evidence="OBSERVED"
        />
        <MetricCard
          icon={<Activity size={15} />}
          label="Active detector"
          value={
            activeDetector ? (
              <span className="metric-text">{activeDetector.name}</span>
            ) : (
              <Unavailable reason="No detector reported available" />
            )
          }
          detail={activeDetector?.version}
        />
        <MetricCard
          icon={<Activity size={15} />}
          label="Requests logged"
          value={metrics.data?.volume.total_requests ?? 0}
          detail={
            metrics.data?.latency.p50_ms !== null &&
            metrics.data?.latency.p50_ms !== undefined
              ? `p50 ${metrics.data.latency.p50_ms} ms · ${
                  metrics.data.latency.model_label ?? "unknown model"
                }`
              : "No latency recorded yet"
          }
        />
      </div>

      <SectionCard
        title="Recent detections"
        description="Newest first, as returned by the API."
      >
        {events.isLoading ? (
          <LoadingSkeleton rows={5} height={44} />
        ) : events.isError ? (
          <ErrorState error={events.error} onRetry={() => events.refetch()} />
        ) : (events.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No detections yet"
            message="Run an ingestion cycle to screen the monitored cells."
          />
        ) : (
          <ul className="activity-feed">
            {events.data?.items.slice(0, 12).map((event) => (
              <li key={event.event_id}>
                <span className="feed-time mono">
                  {formatTime(event.detected_at)}
                </span>
                <span className="feed-dot" />
                <span className="feed-body">
                  <strong>{titleise(event.signature)}</strong>
                  <span className="muted-note">
                    {event.region_name} · confidence{" "}
                    {(event.confidence * 100).toFixed(1)}%
                  </span>
                </span>
                <EvidenceBadge level={event.evidence_level} />
                <RiskBadge severity={event.severity} score={event.risk_score} />
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard title="Pipeline">
        <div className="kv">
          <span>Last health check</span>
          <span>{formatDateTime(health.data?.checked_at)}</span>
        </div>
        <div className="kv">
          <span>Demo mode</span>
          <span>{health.data?.demo_mode ? "Enabled" : "Disabled"}</span>
        </div>
        <div className="kv">
          <span>Environment</span>
          <span className="mono">{health.data?.environment ?? "—"}</span>
        </div>
      </SectionCard>
    </>
  );
}
