/**
 * Command Center.
 *
 * Every KPI here is read straight off `/overview`, `/health`, `/metrics` and
 * `/drift`. Where the API returns null the card shows "Unavailable" or "Not
 * evaluated" rather than a zero — a 0 ms latency reads as instantaneous, and
 * a 0 mAP reads as a broken model.
 */

import { Link } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Cpu,
  Gauge,
  HeartPulse,
  Radar,
  Waves,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import {
  EvidenceBadge,
  EvidenceLegend,
  ErrorState,
  LoadingSkeleton,
  MetricCard,
  NotEvaluated,
  PageHeader,
  RiskBadge,
  SectionCard,
  SimulatedBanner,
  StatusBadge,
  Unavailable,
  formatDateTime,
  titleise,
} from "@/components/ui";

const DRIFT_TONE: Record<string, "ok" | "warn" | "error" | "neutral"> = {
  ok: "ok",
  warning: "warn",
  drift_detected: "error",
  insufficient_data: "neutral",
};

export default function Overview() {
  const results = useQueries({
    queries: [
      { queryKey: ["overview"], queryFn: api.overview },
      { queryKey: ["health"], queryFn: api.health },
      { queryKey: ["metrics", 7], queryFn: () => api.metrics(7) },
      { queryKey: ["drift"], queryFn: () => api.drift() },
      { queryKey: ["alerts", "HIGH"], queryFn: () => api.alerts("HIGH") },
      { queryKey: ["trends", 30], queryFn: () => api.trends(30) },
      { queryKey: ["models"], queryFn: api.models },
    ],
  });

  const [overview, health, metrics, drift, alerts, trends, models] = results;

  if (results.every((result) => result.isLoading)) {
    return <LoadingSkeleton rows={5} height={96} />;
  }
  if (overview.isError) {
    return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;
  }

  const production = models.data?.find((model) => model.is_deployed);
  const alertItems = alerts.data?.items ?? [];

  // Aggregate the per-region series into one platform-wide daily curve.
  const daily = new Map<string, { date: string; risk: number; n: number }>();
  for (const trend of trends.data?.items ?? []) {
    for (const point of trend.series) {
      if (point.mean_risk === null) continue;
      const existing = daily.get(point.date) ?? { date: point.date, risk: 0, n: 0 };
      existing.risk += point.mean_risk;
      existing.n += 1;
      daily.set(point.date, existing);
    }
  }
  const activity = [...daily.values()]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((entry) => ({
      date: entry.date.slice(5),
      risk: Number((entry.risk / entry.n).toFixed(2)),
    }));

  const driftStatus = drift.data?.overall_status ?? null;

  return (
    <>
      <PageHeader
        title="Ocean Intelligence Command Center"
        subtitle="Real-time environmental monitoring, AI analysis and ML operations."
        actions={
          health.data ? (
            <div className="header-status">
              <StatusBadge
                tone={health.data.status === "ok" ? "ok" : "warn"}
                label={
                  health.data.status === "ok"
                    ? "System operational"
                    : "System degraded"
                }
                pulse={health.data.status === "ok"}
              />
              <span className="muted-note">
                Updated {formatDateTime(health.data.checked_at)}
              </span>
            </div>
          ) : null
        }
      />

      {overview.data?.contains_simulated_data && (
        <SimulatedBanner
          detail={`Demo mode is active. All ${overview.data.total_events} detections are synthetic, tagged SIMULATED by the API, and describe no real satellite acquisition.`}
        />
      )}

      <div className="metric-grid">
        <MetricCard
          icon={<AlertTriangle size={15} />}
          label="Pollution Events"
          value={overview.data?.total_events ?? <Unavailable />}
          detail={`${overview.data?.critical_events ?? 0} critical · ${overview.data?.high_events ?? 0} high`}
          tone={
            (overview.data?.critical_events ?? 0) > 0 ? "error" : "neutral"
          }
          evidence="DETECTED"
        />
        <MetricCard
          icon={<Radar size={15} />}
          label="Satellite Observations"
          value={overview.data?.observations ?? <Unavailable />}
          detail="Measurements stored across all monitored cells"
          tone="ok"
          evidence="OBSERVED"
        />
        <MetricCard
          icon={<Waves size={15} />}
          label="Slick-scale Extent"
          value={
            overview.data ? (
              <>
                {Math.round(overview.data.slick_scale_area_km2).toLocaleString()}
                <span className="unit">km²</span>
              </>
            ) : (
              <Unavailable />
            )
          }
          detail="Slick-plausible signatures only — not total dark water"
          tone="warn"
          evidence="INFERRED"
        />
        <MetricCard
          icon={<Cpu size={15} />}
          label="Production Model"
          value={
            production ? (
              <span className="metric-text">{production.version}</span>
            ) : (
              <Unavailable reason="No model marked as deployed" />
            )
          }
          detail={production?.name ?? "No deployed model"}
          tone="neutral"
          footer={
            production ? (
              production.map50 === null ? (
                <NotEvaluated hint="This model has no recorded evaluation run. Metrics stay null rather than being filled with a plausible number." />
              ) : (
                <span className="metric-sub">mAP@50 {production.map50}</span>
              )
            ) : null
          }
        />
        <MetricCard
          icon={<Activity size={15} />}
          label="Inference Latency"
          value={
            metrics.data?.latency.p50_ms !== null &&
            metrics.data?.latency.p50_ms !== undefined ? (
              <>
                {metrics.data.latency.p50_ms}
                <span className="unit">ms p50</span>
              </>
            ) : (
              <Unavailable reason="No predictions logged in this window" />
            )
          }
          detail={
            metrics.data
              ? `${metrics.data.volume.total_requests} request(s) in ${metrics.data.window_days}d`
              : undefined
          }
          tone="neutral"
        />
        <MetricCard
          icon={<Gauge size={15} />}
          label="Drift Status"
          value={
            driftStatus ? (
              <span className="metric-text">{titleise(driftStatus)}</span>
            ) : (
              <Unavailable />
            )
          }
          detail={
            driftStatus === "insufficient_data"
              ? "Not enough samples to issue a verdict — not the same as no drift"
              : drift.data?.action
          }
          tone={driftStatus ? (DRIFT_TONE[driftStatus] ?? "neutral") : "neutral"}
        />
      </div>

      <div className="two-col">
        <SectionCard
          title="Detection activity"
          description="Platform-wide daily mean risk across all monitored regions."
          actions={<EvidenceBadge level="OBSERVED" />}
        >
          {trends.isLoading ? (
            <LoadingSkeleton rows={1} height={220} />
          ) : activity.length < 2 ? (
            <p className="muted-note pad">
              Not enough observed history to plot a trend. Run an ingestion
              cycle to accumulate daily aggregates.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={activity} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  tickLine={false}
                  axisLine={false}
                  label={{
                    value: "risk",
                    angle: -90,
                    position: "insideLeft",
                    style: { fontSize: 10, fill: "var(--text-muted)" },
                  }}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    fontSize: 12,
                    boxShadow: "var(--shadow-md)",
                  }}
                  formatter={(value: number) => [`${value} / 100`, "Mean risk"]}
                />
                <Area
                  type="monotone"
                  dataKey="risk"
                  stroke="#0284c7"
                  strokeWidth={2}
                  fill="url(#riskFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </SectionCard>

        <SectionCard
          title="Active alerts"
          description="Events at or above HIGH severity."
          actions={
            <Link className="btn btn-ghost btn-sm" to="/app/events">
              All events <ArrowRight size={13} />
            </Link>
          }
        >
          {alerts.isLoading ? (
            <LoadingSkeleton rows={3} height={52} />
          ) : alertItems.length === 0 ? (
            <p className="muted-note pad">
              No events at or above HIGH severity.
            </p>
          ) : (
            <ul className="alert-list">
              {alertItems.slice(0, 6).map((alert) => (
                <li key={alert.event_id}>
                  <Link to={`/app/risk/${alert.event_id}`} className="alert-row">
                    <RiskBadge severity={alert.severity} score={alert.risk_score} />
                    <span className="alert-body">
                      <strong>{titleise(alert.signature)}</strong>
                      <span>{alert.region_name}</span>
                    </span>
                    <span className="alert-conf">
                      {(alert.confidence * 100).toFixed(0)}%
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>

      <SectionCard
        title="Evidence ladder"
        description="OceanAI keeps these categories strictly apart. Every figure in this console is labelled with the one it belongs to."
        actions={
          <Link className="btn btn-ghost btn-sm" to="/app/health">
            <HeartPulse size={13} /> System health
          </Link>
        }
      >
        <EvidenceLegend />
      </SectionCard>
    </>
  );
}
