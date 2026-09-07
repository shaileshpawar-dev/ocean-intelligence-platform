/**
 * Experiments.
 *
 * This backend exposes no experiment-tracking endpoint. Rather than inventing
 * runs, the page states that plainly and points at what does exist.
 */

import { Link } from "react-router-dom";
import { PageHeader, NotAvailableInBackend, SectionCard } from "@/components/ui";

export default function Experiments() {
  return (
    <>
      <PageHeader
        title="Experiments"
        subtitle="Experiment tracking and run comparison."
      />
      <SectionCard>
        <NotAvailableInBackend
          feature="Experiment tracking"
          reason="This deployment exposes no experiment-tracking endpoint. The OceanAI backend records model versions and their evaluated metrics, but it does not yet track training runs, hyperparameter sweeps or run comparisons."
          alternative="MLflow integration is the planned next step; the model_versions table is deliberately shaped to map onto it. Until then, registered models and their measured metrics are on the Model Performance page."
        />
        <div className="center-actions">
          <Link className="btn btn-primary btn-sm" to="/app/models">
            Model Performance
          </Link>
        </div>
      </SectionCard>
    </>
  );
}
