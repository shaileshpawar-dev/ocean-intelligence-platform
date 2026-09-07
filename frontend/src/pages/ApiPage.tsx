/**
 * API reference.
 *
 * Lists only endpoints that exist on this backend, grouped as the routers are.
 * Base URL and environment come from the running service, not a constant.
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, KeyRound } from "lucide-react";
import { API_ROOT, api } from "@/lib/api";
import {
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  StatusBadge,
} from "@/components/ui";

const ENDPOINTS: { group: string; items: [string, string, string][] }[] = [
  {
    group: "System",
    items: [
      ["GET", "/health", "Liveness plus per-component availability"],
      ["GET", "/overview", "Dashboard headline counters"],
      ["GET", "/metrics", "Measured latency and request volume"],
    ],
  },
  {
    group: "Pollution",
    items: [
      ["GET", "/pollution-zones", "Current state of every monitored cell"],
      ["GET", "/pollution-events", "Detections, filterable by severity and signature"],
      ["GET", "/pollution-events/{id}", "Event with risk breakdown and measurement"],
      ["GET", "/alerts", "Events at or above a severity threshold"],
    ],
  },
  {
    group: "Satellite",
    items: [
      ["POST", "/satellite/ingest", "Stage-1 sweep: observe, detect, score, persist"],
      ["POST", "/satellite/refine", "Stage-2: subdivide flagged cells, re-observe"],
      ["GET", "/satellite/thumbnail/{region}", "SAR preview URL, or explicit null"],
      ["POST", "/detect", "Run the image detector on an upload"],
    ],
  },
  {
    group: "Analytics",
    items: [
      ["GET", "/trends", "Per-region daily series with coverage ratio"],
      ["GET", "/forecast/{region}", "Activity forecast with prediction intervals"],
      ["GET", "/risk/{event_id}", "Explainable per-factor risk breakdown"],
    ],
  },
  {
    group: "Machine learning",
    items: [
      ["GET", "/models", "Registry with measured metrics (null if unevaluated)"],
      ["GET", "/models/detectors", "Runtime detector status and permitted claims"],
      ["GET", "/drift", "PSI drift checks over two windows"],
    ],
  },
  {
    group: "Intelligence",
    items: [
      ["POST", "/research", "Grounded answer with cited sources"],
      ["GET", "/research/search", "Raw retrieval with BM25 scores"],
      ["GET", "/research/corpus", "Corpus size and composition"],
      ["POST", "/agents/analyze-event", "Run the five-stage workflow"],
      ["GET", "/agents", "Workflow, stages, tools and LLM status"],
      ["GET", "/agents/runs", "Recent workflow runs"],
      ["POST", "/reports/generate", "Generate an intelligence report"],
      ["GET", "/reports", "List generated reports"],
      ["GET", "/reports/{id}", "Report with provenance map"],
      ["GET", "/reports/{id}/text", "Fixed-width briefing rendering"],
    ],
  },
];

export default function ApiPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  return (
    <>
      <PageHeader
        title="API"
        subtitle="Every endpoint this console consumes, on the running service."
        actions={
          <a
            className="btn btn-outline btn-sm"
            href="/docs"
            target="_blank"
            rel="noreferrer noopener"
          >
            OpenAPI docs <ExternalLink size={12} />
          </a>
        }
      />

      <SectionCard title="Service">
        {health.isLoading ? (
          <LoadingSkeleton rows={2} height={34} />
        ) : (
          <>
            <div className="kv">
              <span>API base URL</span>
              <span className="mono">
                {API_ROOT || `${window.location.origin}/api/v1`}
              </span>
            </div>
            <div className="kv">
              <span>Service</span>
              <span>{health.data?.app_name ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Version</span>
              <span className="mono">{health.data?.version ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Environment</span>
              <span className="mono">{health.data?.environment ?? "—"}</span>
            </div>
            <div className="kv">
              <span>Status</span>
              <span>
                <StatusBadge
                  tone={health.data?.status === "ok" ? "ok" : "warn"}
                  label={health.data?.status === "ok" ? "Operational" : "Degraded"}
                />
              </span>
            </div>
            <div className="kv">
              <span>Authentication</span>
              <span>
                <KeyRound size={12} /> None required — the API is unauthenticated
                in this deployment
              </span>
            </div>
          </>
        )}
      </SectionCard>

      {ENDPOINTS.map((group) => (
        <SectionCard key={group.group} title={group.group}>
          <div className="table-wrap">
            <table className="data-table endpoints">
              <tbody>
                {group.items.map(([method, path, description]) => (
                  <tr key={`${method}-${path}`}>
                    <td className="endpoint-method">
                      <span className={`method ${method.toLowerCase()}`}>
                        {method}
                      </span>
                    </td>
                    <td className="mono endpoint-path">/api/v1{path}</td>
                    <td className="muted-note">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      ))}
    </>
  );
}
