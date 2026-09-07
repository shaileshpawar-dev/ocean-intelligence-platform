/**
 * System Health.
 *
 * Status is derived only from the real /health component list. A component the
 * backend reports as unavailable is shown unavailable, with the reason it gave.
 */

import { useQueries } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleSlash } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  Unavailable,
  formatDateTime,
} from "@/components/ui";

export default function SystemHealth() {
  const [health, corpus, agents, metrics] = useQueries({
    queries: [
      { queryKey: ["health"], queryFn: api.health },
      { queryKey: ["corpus"], queryFn: api.corpus },
      { queryKey: ["agents"], queryFn: api.agents },
      { queryKey: ["metrics", 7], queryFn: () => api.metrics(7) },
    ],
  });

  if (health.isLoading) return <LoadingSkeleton rows={4} height={70} />;
  if (health.isError)
    return <ErrorState error={health.error} onRetry={() => health.refetch()} />;

  const components = health.data?.components ?? [];

  // Subsystems the /health payload does not enumerate, each derived from the
  // endpoint that actually serves it rather than assumed healthy.
  const derived = [
    {
      name: "rag:corpus",
      available: !corpus.isError && (corpus.data?.documents ?? 0) > 0,
      detail: corpus.isError
        ? "Corpus endpoint unreachable"
        : `${corpus.data?.documents ?? 0} documents · ${corpus.data?.chunks ?? 0} passages`,
    },
    {
      name: "agents:workflow",
      available: !agents.isError && (agents.data?.stages.length ?? 0) > 0,
      detail: agents.isError
        ? "Agent catalogue unreachable"
        : `${agents.data?.stages.length ?? 0} stages · ${agents.data?.tools.length ?? 0} tools`,
    },
    {
      name: "monitoring:predictions",
      available: (metrics.data?.volume.total_requests ?? 0) > 0,
      detail:
        (metrics.data?.volume.total_requests ?? 0) > 0
          ? `${metrics.data?.volume.total_requests} logged request(s)`
          : "No predictions logged yet — not an error",
    },
  ];

  const all = [...components, ...derived];

  return (
    <>
      <PageHeader
        title="System Health"
        subtitle="Live status of every subsystem, derived from the API rather than assumed."
        actions={
          health.data ? (
            <span className="muted-note">
              Checked {formatDateTime(health.data.checked_at)}
            </span>
          ) : null
        }
      />

      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-top">
            <span className="metric-label">Service</span>
          </div>
          <div className="metric-value metric-text">{health.data?.app_name}</div>
          <p className="metric-detail">
            v{health.data?.version} · {health.data?.environment}
            {health.data?.demo_mode ? " · demo mode" : ""}
          </p>
        </div>
        <div className="metric-card">
          <div className="metric-top">
            <span className="metric-label">Overall</span>
          </div>
          <div className="metric-value metric-text">
            {health.data?.status === "ok" ? "Operational" : "Degraded"}
          </div>
          <p className="metric-detail">
            {all.filter((component) => component.available).length} of {all.length}{" "}
            subsystems available
          </p>
        </div>
      </div>

      <SectionCard title="Subsystems">
        <ul className="health-list">
          {all.map((component) => (
            <li key={component.name}>
              <span
                className={`health-dot ${component.available ? "ok" : "off"}`}
                aria-hidden="true"
              >
                {component.available ? (
                  <CircleCheck size={15} />
                ) : component.detail?.toLowerCase().includes("unreachable") ? (
                  <CircleAlert size={15} />
                ) : (
                  <CircleSlash size={15} />
                )}
              </span>
              <span className="health-name mono">{component.name}</span>
              <span
                className={`health-status ${component.available ? "ok" : "off"}`}
              >
                {component.available ? "Operational" : "Unavailable"}
              </span>
              <span className="health-detail muted-note">
                {component.detail ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard title="Inference metrics">
        <div className="kv">
          <span>Requests ({metrics.data?.window_days ?? 7}d)</span>
          <span>{metrics.data?.volume.total_requests ?? 0}</span>
        </div>
        <div className="kv">
          <span>Success rate</span>
          <span>
            {metrics.data?.volume.success_rate !== null &&
            metrics.data?.volume.success_rate !== undefined
              ? `${(metrics.data.volume.success_rate * 100).toFixed(1)}%`
              : <Unavailable reason="No requests logged" />}
          </span>
        </div>
        <div className="kv">
          <span>Latency p50 / p95</span>
          <span>
            {metrics.data?.latency.p50_ms !== null &&
            metrics.data?.latency.p50_ms !== undefined
              ? `${metrics.data.latency.p50_ms} ms / ${metrics.data.latency.p95_ms} ms`
              : <Unavailable reason="No predictions logged" />}
          </span>
        </div>
        <p className="muted-note">
          Measured from the prediction log. Zero traffic reports null rather
          than zero — a 0 ms latency would read as instantaneous.
        </p>
      </SectionCard>
    </>
  );
}
