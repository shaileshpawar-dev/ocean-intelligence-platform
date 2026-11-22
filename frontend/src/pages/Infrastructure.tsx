/**
 * Infrastructure.
 *
 * Reports only what the running service actually discloses about itself.
 * Cloud topology is not inferred: the frontend has no visibility into ECS or
 * the load balancer, and claiming otherwise would be guesswork.
 */

import { useQuery } from "@tanstack/react-query";
import { Boxes, Info } from "lucide-react";
import { api } from "@/lib/api";
import {
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  StatusBadge,
} from "@/components/ui";

export default function Infrastructure() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const runtime = [
    ["Frontend", "React 18 + TypeScript, built with Vite, served as static assets by FastAPI"],
    ["API", "FastAPI with Pydantic schemas and SQLAlchemy 2.0"],
    ["Database", "SQLite by default; PostgreSQL via DATABASE_URL"],
    ["Detection", "Sentinel-1 SAR dark-formation screening + optional YOLOv8 optical water pollution detector"],
    ["Retrieval", "BM25 over a local corpus — no vector database required"],
    ["LLM", "Optional. Gemini / OpenAI / Anthropic, selected by LLM_PROVIDER"],
  ];

  return (
    <>
      <PageHeader
        title="Infrastructure"
        subtitle="Runtime composition of this deployment."
      />

      <SectionCard title="Service">
        {health.isLoading ? (
          <LoadingSkeleton rows={2} height={34} />
        ) : (
          <>
            <div className="kv">
              <span>Environment</span>
              <span className="mono">{health.data?.environment ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Version</span>
              <span className="mono">{health.data?.version ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Demo mode</span>
              <span>{health.data?.demo_mode ? "Enabled" : "Disabled"}</span>
            </div>
            <div className="kv">
              <span>Health</span>
              <span>
                <StatusBadge
                  tone={health.data?.status === "ok" ? "ok" : "warn"}
                  label={health.data?.status === "ok" ? "Operational" : "Degraded"}
                />
              </span>
            </div>
          </>
        )}
      </SectionCard>

      <SectionCard
        title="Runtime composition"
        actions={<Boxes size={15} className="text-muted" />}
      >
        <dl className="report-dl">
          {runtime.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </SectionCard>

      <SectionCard title="Deployment topology">
        <div className="inline-note">
          <Info size={14} />
          <span>
            The frontend has no visibility into cloud topology — container
            orchestration, load balancing and networking are not exposed
            through the API, and this page will not guess at them. Consult your
            infrastructure console for ECS task, target group and ALB state.
          </span>
        </div>
      </SectionCard>
    </>
  );
}
