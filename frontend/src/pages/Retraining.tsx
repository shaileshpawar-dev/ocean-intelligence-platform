/**
 * Retraining.
 *
 * The platform deliberately does not retrain automatically. That is a design
 * decision, not a missing feature, so this page explains the policy rather
 * than pretending an automated pipeline exists.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  titleise,
} from "@/components/ui";

export default function Retraining() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const drift = useQuery({ queryKey: ["drift"], queryFn: () => api.drift() });

  const production = models.data?.find((model) => model.is_deployed);

  return (
    <>
      <PageHeader
        title="Retraining"
        subtitle="Retraining policy and current trigger state."
      />

      <div className="status-callout neutral">
        <ShieldAlert size={18} />
        <div>
          <strong>Not configured — by design</strong>
          <p>
            OceanAI has no automated retraining pipeline. Drift raises a flag
            for human review; it never triggers retraining on its own. Drift is
            a symptom with several causes — a seasonal shift in sea state, a
            change to the monitored regions, or an upstream preprocessing bug.
            Retraining automatically on the last of those bakes the bug into the
            weights.
          </p>
        </div>
      </div>

      <SectionCard title="Current model">
        {models.isLoading ? (
          <LoadingSkeleton rows={2} height={40} />
        ) : models.isError ? (
          <ErrorState error={models.error} />
        ) : production ? (
          <>
            <div className="kv">
              <span>Model</span>
              <span className="mono">
                {production.name}:{production.version}
              </span>
            </div>
            <div className="kv">
              <span>Status</span>
              <span>{titleise(production.status)}</span>
            </div>
            <div className="kv">
              <span>Dataset version</span>
              <span className="mono">{production.dataset_version ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Evaluated</span>
              <span>
                {production.metrics_source
                  ? production.metrics_source
                  : "Never — no evaluation run recorded"}
              </span>
            </div>
          </>
        ) : (
          <p className="muted-note">No model is currently marked as deployed.</p>
        )}
      </SectionCard>

      <SectionCard title="Trigger state">
        {drift.isLoading ? (
          <LoadingSkeleton rows={2} height={36} />
        ) : drift.isError ? (
          <ErrorState error={drift.error} />
        ) : (
          <>
            <div className="kv">
              <span>Drift verdict</span>
              <span>{titleise(drift.data?.overall_status ?? "unknown")}</span>
            </div>
            <div className="kv">
              <span>Policy</span>
              <span className="wrap">{drift.data?.action}</span>
            </div>
            <p className="muted-note">
              A retraining candidate is raised only after a sustained drift
              signal has been reviewed and the input pipeline verified. Then it
              is run deliberately, against a new dataset version.
            </p>
            <div className="center-actions">
              <Link className="btn btn-outline btn-sm" to="/app/drift">
                Drift monitoring
              </Link>
            </div>
          </>
        )}
      </SectionCard>
    </>
  );
}
