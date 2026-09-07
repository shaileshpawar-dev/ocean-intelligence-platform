/**
 * Reports.
 *
 * A report is rendered by evidence section, in the order the platform's
 * epistemics require: what was measured, what was detected, what was inferred,
 * what is projected, and what was retrieved. Download uses the backend's real
 * `/reports/{id}/text` endpoint; no client-side PDF is invented.
 */

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, FileText, Play } from "lucide-react";
import { api } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  SimulatedBanner,
  formatDateTime,
  titleise,
} from "@/components/ui";

const SECTION_ORDER = [
  ["observed", "OBSERVED", "Measured from sensor data"],
  ["detected", "DETECTED", "Detector output, carries uncertainty"],
  ["inferred", "INFERRED", "Derived by the deterministic risk engine"],
  ["forecast", "FORECAST", "A projection, not an observation"],
  ["retrieved_evidence", "RETRIEVED", "Sources from the verified corpus"],
] as const;

function renderValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted">none</span>;
    if (typeof value[0] === "object") return `${value.length} item(s)`;
    return value.join(", ");
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function Reports() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [eventId, setEventId] = useState<string | null>(null);

  const list = useQuery({ queryKey: ["reports"], queryFn: () => api.reports(50) });
  const events = useQuery({
    queryKey: ["events", "report-picker"],
    queryFn: () => api.events({ limit: 200 }),
  });

  const detail = useQuery({
    queryKey: ["report", reportId],
    queryFn: () => api.report(reportId!),
    enabled: Boolean(reportId),
  });

  const generate = useMutation({
    mutationFn: (id: string) => api.generateReport(id),
    onSuccess: (report) => {
      list.refetch();
      navigate(`/app/reports/${report.report_id}`);
    },
  });

  const download = useMutation({
    mutationFn: (id: string) => api.reportText(id),
    onSuccess: (payload) => {
      const blob = new Blob([payload.text], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${payload.report_id}.txt`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });

  const active = eventId ?? events.data?.items[0]?.event_id ?? null;

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Environmental intelligence reports, sectioned by evidence level."
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <select
            className="select grow"
            value={active ?? ""}
            onChange={(event) => setEventId(event.target.value)}
            aria-label="Detection"
          >
            {events.data?.items.map((event) => (
              <option key={event.event_id} value={event.event_id}>
                {titleise(event.signature)} · {event.region_name}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            disabled={!active || generate.isPending}
            onClick={() => active && generate.mutate(active)}
          >
            <Play size={14} />
            {generate.isPending ? "Generating…" : "Generate report"}
          </button>
        </div>
      </SectionCard>

      {generate.isError && <ErrorState error={generate.error} />}

      {reportId ? (
        detail.isLoading ? (
          <LoadingSkeleton rows={4} height={80} />
        ) : detail.isError ? (
          <ErrorState error={detail.error} />
        ) : detail.data ? (
          <>
            {detail.data.contains_simulated_data && <SimulatedBanner />}
            <SectionCard
              title={detail.data.title}
              description={`${detail.data.generated_by} · ${formatDateTime(detail.data.created_at)}`}
              actions={
                <div className="badge-row">
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={() => download.mutate(detail.data!.report_id)}
                    disabled={download.isPending}
                  >
                    <Download size={13} />
                    {download.isPending ? "Preparing…" : "Download .txt"}
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => navigate("/app/reports")}
                  >
                    Back to list
                  </button>
                </div>
              }
            >
              {detail.data.summary && (
                <p className="narrative">{detail.data.summary}</p>
              )}
            </SectionCard>

            {SECTION_ORDER.map(([key, level, description]) => {
              const section = detail.data!.sections?.[key];
              if (!section) return null;
              const entries = Object.entries(section).filter(
                ([field]) => field !== "evidence_level",
              );
              return (
                <SectionCard
                  key={key}
                  title={titleise(key)}
                  description={description}
                  actions={<EvidenceBadge level={level} />}
                >
                  <dl className="report-dl">
                    {entries.map(([field, value]) => (
                      <div key={field}>
                        <dt>{titleise(field)}</dt>
                        <dd>{renderValue(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </SectionCard>
              );
            })}
          </>
        ) : null
      ) : (
        <SectionCard title="Generated reports">
          {list.isLoading ? (
            <LoadingSkeleton rows={4} height={44} />
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} />
          ) : (list.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No reports yet"
              message="Select a detection above and generate a report to produce one."
              icon={<FileText size={20} />}
            />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th className="num">Sources</th>
                    <th>Provenance</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data?.items.map((report) => (
                    <tr
                      key={report.report_id}
                      onClick={() => navigate(`/app/reports/${report.report_id}`)}
                      tabIndex={0}
                      onKeyDown={(event) => {
                        if (event.key === "Enter")
                          navigate(`/app/reports/${report.report_id}`);
                      }}
                    >
                      <td>
                        <strong>{report.title}</strong>
                        <span className="cell-sub mono">{report.report_id}</span>
                      </td>
                      <td className="num">{report.source_count}</td>
                      <td>
                        {report.contains_simulated_data ? (
                          <EvidenceBadge level="SIMULATED" />
                        ) : (
                          <EvidenceBadge level="DETECTED" />
                        )}
                      </td>
                      <td className="muted-note">
                        {formatDateTime(report.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}
    </>
  );
}
