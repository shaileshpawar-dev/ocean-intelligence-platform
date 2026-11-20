/**
 * Drift Monitoring.
 *
 * `insufficient_data` is rendered as its own state, never collapsed into
 * "no drift". A verdict from eight samples is noise, and reporting it as
 * healthy is worse than reporting nothing.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, HelpCircle, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  MetricCard,
  PageHeader,
  ProvenanceNote,
  SectionCard,
  Unavailable,
  titleise,
} from "@/components/ui";

const STATUS_META: Record<
  string,
  { tone: "ok" | "warn" | "error" | "neutral"; icon: typeof CheckCircle2; label: string }
> = {
  ok: { tone: "ok", icon: CheckCircle2, label: "Stable" },
  warning: { tone: "warn", icon: AlertTriangle, label: "Warning" },
  drift_detected: { tone: "error", icon: ShieldAlert, label: "Drift detected" },
  insufficient_data: {
    tone: "neutral",
    icon: HelpCircle,
    label: "Insufficient data",
  },
};

export default function Drift() {
  const [baseline, setBaseline] = useState(30);
  const [current, setCurrent] = useState(7);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["drift", baseline, current],
    queryFn: () => api.drift(baseline, current),
  });

  if (isLoading) return <LoadingSkeleton rows={3} height={100} />;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const overall = STATUS_META[data.overall_status] ?? STATUS_META.insufficient_data;
  const OverallIcon = overall.icon;

  return (
    <>
      <PageHeader
        title="Drift Monitoring"
        subtitle="Population Stability Index over non-overlapping baseline and current windows."
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <label className="inline-field">
            Baseline window
            <select
              className="select"
              value={baseline}
              onChange={(event) => setBaseline(Number(event.target.value))}
            >
              {[14, 30, 60, 90].map((days) => (
                <option key={days} value={days}>
                  {days} days
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Current window
            <select
              className="select"
              value={current}
              onChange={(event) => setCurrent(Number(event.target.value))}
            >
              {[3, 7, 14, 30].map((days) => (
                <option key={days} value={days}>
                  {days} days
                </option>
              ))}
            </select>
          </label>
        </div>
      </SectionCard>

      {data.provenance?.note && (
        <ProvenanceNote>{data.provenance.note}</ProvenanceNote>
      )}

      <div className="metric-grid">
        <MetricCard
          icon={<OverallIcon size={15} />}
          label="Overall status"
          value={<span className="metric-text">{overall.label}</span>}
          detail={
            data.overall_status === "insufficient_data"
              ? "Not enough samples to issue a verdict. This is NOT the same as 'no drift'."
              : undefined
          }
          tone={overall.tone}
        />
        <MetricCard
          icon={<HelpCircle size={15} />}
          label="Minimum samples"
          value={data.min_samples_required}
          detail="Per window, before a verdict is meaningful"
        />
        <MetricCard
          icon={<AlertTriangle size={15} />}
          label="Thresholds"
          value={
            <span className="metric-text">
              {data.thresholds.warning} / {data.thresholds.drift}
            </span>
          }
          detail="PSI warning / drift boundaries"
        />
      </div>

      {data.overall_status === "insufficient_data" && (
        <div className="partial-warning neutral">
          <HelpCircle size={17} />
          <div>
            <strong>Concept drift — unavailable</strong>
            <p>
              Insufficient labelled data for drift evaluation. Fewer than{" "}
              {data.min_samples_required} samples exist in one or both windows,
              so no verdict is issued. An unavailable verdict is deliberately
              not converted into "no drift".
            </p>
          </div>
        </div>
      )}

      <SectionCard title="Checks" description={data.action}>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Status</th>
                <th className="num">PSI</th>
                <th className="num">Baseline n</th>
                <th className="num">Current n</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.checks.map((check) => {
                const meta = STATUS_META[check.status] ?? STATUS_META.insufficient_data;
                return (
                  <tr key={check.metric}>
                    <td>
                      <strong>{titleise(check.metric)}</strong>
                    </td>
                    <td>
                      <span className={`tag tone-${meta.tone}`}>{meta.label}</span>
                    </td>
                    <td className="num">
                      {check.psi === null ? <Unavailable /> : check.psi.toFixed(4)}
                    </td>
                    <td className="num">{check.baseline_n}</td>
                    <td className="num">{check.current_n}</td>
                    <td className="muted-note wrap small">{check.message}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Retraining policy">
        <div className="inline-note">
          <ShieldAlert size={14} />
          <span>
            Drift flags for human review; it never triggers retraining
            automatically. Drift is a symptom with many causes — a seasonal
            shift, a changed monitoring region, or an upstream preprocessing
            bug. Retraining blindly on the last of those bakes the bug into the
            weights.
          </span>
        </div>
      </SectionCard>
    </>
  );
}
