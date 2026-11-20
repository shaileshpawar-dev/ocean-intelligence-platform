/**
 * Model Performance.
 *
 * Unmeasured metrics render as "Not evaluated", never as zero and never as a
 * plausible-looking number. That distinction is the whole point of this page:
 * a null mAP is an honest statement that no evaluation has been run.
 */

import { useQueries } from "@tanstack/react-query";
import { Cpu, Info } from "lucide-react";
import { api } from "@/lib/api";
import CandidateEvaluationPanel from "@/components/CandidateEvaluationPanel";
import {
  ErrorState,
  LoadingSkeleton,
  MetricCard,
  NotEvaluated,
  PageHeader,
  SectionCard,
  Unavailable,
  Value,
  formatDateTime,
  titleise,
} from "@/components/ui";

const LIFECYCLE = ["development", "staging", "production", "archived"];

export default function Models() {
  const [models, detectors, metrics] = useQueries({
    queries: [
      { queryKey: ["models"], queryFn: api.models },
      { queryKey: ["detectors"], queryFn: api.detectors },
      { queryKey: ["metrics", 7], queryFn: () => api.metrics(7) },
    ],
  });

  if (models.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (models.isError)
    return <ErrorState error={models.error} onRetry={() => models.refetch()} />;

  const rows = models.data ?? [];
  const evaluated = rows.filter((model) => model.metrics_source !== null);

  return (
    <>
      <PageHeader
        title="Model Performance"
        subtitle="Registered models and their measured metrics. Null means not evaluated."
      />

      <div className="metric-grid">
        <MetricCard
          icon={<Cpu size={15} />}
          label="Registered models"
          value={rows.length}
          detail={`${rows.filter((model) => model.is_deployed).length} deployed`}
        />
        <MetricCard
          icon={<Info size={15} />}
          label="Evaluated models"
          value={evaluated.length}
          detail={
            evaluated.length === 0
              ? "No evaluation run has recorded metrics yet"
              : "Metrics written by an evaluation run"
          }
          tone={evaluated.length === 0 ? "warn" : "ok"}
        />
        <MetricCard
          icon={<Cpu size={15} />}
          label="Inference p95"
          value={
            metrics.data?.latency.p95_ms !== null &&
            metrics.data?.latency.p95_ms !== undefined ? (
              <>
                {metrics.data.latency.p95_ms}
                <span className="unit">ms</span>
              </>
            ) : (
              <Unavailable reason="No predictions logged" />
            )
          }
          detail={`${metrics.data?.volume.total_requests ?? 0} request(s) logged`}
        />
      </div>

      <CandidateEvaluationPanel />

      {rows.map((model) => (
        <SectionCard
          key={`${model.name}:${model.version}`}
          title={model.name}
          description={`${model.task} · ${model.framework ?? "—"}`}
          actions={
            <div className="badge-row">
              <span className="tag tone-neutral mono">{model.version}</span>
              {model.is_deployed && <span className="tag tone-ok">deployed</span>}
            </div>
          }
        >
          <div className="lifecycle">
            {LIFECYCLE.map((stage) => (
              <span
                key={stage}
                className={`lifecycle-step${model.status === stage ? " active" : ""}`}
              >
                {stage}
              </span>
            ))}
          </div>

          <div className="metrics-table">
            {(
              [
                ["mAP@50", model.map50],
                ["mAP@50-95", model.map50_95],
                ["Precision", model.precision],
                ["Recall", model.recall],
                ["F1", model.f1],
                ["IoU", model.iou],
              ] as const
            ).map(([label, value]) => (
              <div className="metric-cell" key={label}>
                <span>{label}</span>
                <strong>
                  {value === null ? (
                    <NotEvaluated />
                  ) : (
                    value.toFixed(3)
                  )}
                </strong>
              </div>
            ))}
            <div className="metric-cell">
              <span>Mean latency</span>
              <strong>
                <Value
                  value={model.mean_latency_ms}
                  suffix=" ms"
                  digits={1}
                  fallback="not-evaluated"
                />
              </strong>
            </div>
          </div>

          {model.metrics_source === null && (
            <div className="inline-note">
              <Info size={14} />
              <span>
                No evaluation run has recorded metrics for this model. Values
                stay null rather than being filled with plausible numbers. Run{" "}
                <code>python -m ml.evaluation.evaluate_detector --register</code>{" "}
                against a labelled dataset to populate them.
              </span>
            </div>
          )}

          <div className="kv">
            <span>Dataset version</span>
            <span className="mono">{model.dataset_version ?? <Unavailable />}</span>
          </div>
          <div className="kv">
            <span>Trained</span>
            <span>{model.trained_at ? formatDateTime(model.trained_at) : <Unavailable />}</span>
          </div>
          {model.class_names && (
            <div className="kv">
              <span>Classes</span>
              <span className="wrap">
                {model.class_names.map((name) => titleise(name)).join(", ")}
              </span>
            </div>
          )}
          {model.notes && <p className="model-notes">{model.notes}</p>}
        </SectionCard>
      ))}

      <SectionCard
        title="Runtime detectors"
        description="What each loaded detector is permitted to claim. Emitting anything outside its set raises."
      >
        {detectors.isLoading ? (
          <LoadingSkeleton rows={2} height={60} />
        ) : detectors.isError ? (
          <ErrorState error={detectors.error} />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Detector</th>
                  <th>Status</th>
                  <th>May claim</th>
                  <th>Trained labels</th>
                </tr>
              </thead>
              <tbody>
                {detectors.data?.map((detector) => (
                  <tr key={detector.name}>
                    <td>
                      <strong>{detector.name}</strong>
                      <span className="cell-sub mono">{detector.version}</span>
                    </td>
                    <td>
                      <span
                        className={`tag tone-${detector.available ? "ok" : "error"}`}
                      >
                        {detector.available ? "available" : "unavailable"}
                      </span>
                    </td>
                    <td className="wrap small">
                      {detector.supported_signatures
                        .map((signature) => titleise(signature.replace("_signature", "")))
                        .join(", ")}
                    </td>
                    <td className="wrap small mono">
                      {detector.class_names
                        ? Object.entries(detector.class_names)
                            .map(([id, name]) => `${id} ${name}`)
                            .join(", ")
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </>
  );
}
