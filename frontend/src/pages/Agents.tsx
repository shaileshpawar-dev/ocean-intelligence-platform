/**
 * Agent Analysis.
 *
 * Renders the real workflow trace: five stages, the tools each actually
 * called, and the timings. The LLM provider is reported from the run itself,
 * so the page never claims a model was involved when the run used none.
 */

import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bot,
  Check,
  ChevronRight,
  CircleDashed,
  Play,
  Wrench,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentFinding } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  formatDateTime,
  titleise,
} from "@/components/ui";

const STAGE_ORDER = ["detection", "context", "research", "risk", "report"];

export default function Agents() {
  const [params] = useSearchParams();
  const preset = params.get("event");
  const [eventId, setEventId] = useState<string | null>(preset);
  const [openStage, setOpenStage] = useState<string | null>("detection");

  const catalogue = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const events = useQuery({
    queryKey: ["events", "agent-picker"],
    queryFn: () => api.events({ limit: 200 }),
  });
  const runs = useQuery({ queryKey: ["agent-runs"], queryFn: () => api.agentRuns(10) });

  const analyse = useMutation({
    mutationFn: (id: string) => api.analyzeEvent(id),
    onSuccess: () => runs.refetch(),
  });

  const active = eventId ?? events.data?.items[0]?.event_id ?? null;
  const result = analyse.data;
  const findings = new Map<string, AgentFinding>(
    (result?.findings ?? []).map((finding) => [finding.agent, finding]),
  );

  return (
    <>
      <PageHeader
        title="Agent Analysis"
        subtitle="A five-stage workflow that terminates in a bounded number of tool calls. Agents never call each other."
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <select
            className="select grow"
            value={active ?? ""}
            onChange={(event) => setEventId(event.target.value)}
            aria-label="Detection to analyse"
          >
            {events.data?.items.map((event) => (
              <option key={event.event_id} value={event.event_id}>
                {titleise(event.signature)} · {event.region_name} ·{" "}
                {event.risk_score?.toFixed(1) ?? "—"}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            disabled={!active || analyse.isPending}
            onClick={() => active && analyse.mutate(active)}
          >
            <Play size={14} />
            {analyse.isPending ? "Running…" : "Run workflow"}
          </button>
        </div>
      </SectionCard>

      {catalogue.data && (
        <SectionCard
          title={catalogue.data.workflow}
          description={catalogue.data.control_flow}
          actions={
            <span
              className={`tag tone-${catalogue.data.llm.available ? "info" : "neutral"}`}
            >
              <Bot size={11} /> LLM:{" "}
              {catalogue.data.llm.available
                ? `${catalogue.data.llm.provider}${catalogue.data.llm.model ? ` · ${catalogue.data.llm.model}` : ""}`
                : "not configured"}
            </span>
          }
        >
          <ul className="caveat-list tight">
            {catalogue.data.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      {analyse.isPending && <LoadingSkeleton rows={5} height={62} />}
      {analyse.isError && <ErrorState error={analyse.error} />}

      {result && (
        <>
          <SectionCard
            title="Workflow trace"
            description={`${result.status} · ${result.duration_ms.toFixed(0)} ms · ${result.tool_calls.length} tool calls · LLM: ${result.llm_provider}`}
          >
            <ol className="agent-timeline">
              {STAGE_ORDER.map((stage, index) => {
                const finding = findings.get(stage);
                const stageTools = result.tool_calls.filter(
                  (call) => call.agent === stage,
                );
                const open = openStage === stage;
                return (
                  <li
                    key={stage}
                    className={`agent-stage${finding ? (finding.ok ? " ok" : " failed") : " pending"}`}
                  >
                    <button
                      className="agent-stage-head"
                      onClick={() => setOpenStage(open ? null : stage)}
                      aria-expanded={open}
                    >
                      <span className="agent-node">
                        {finding ? (
                          finding.ok ? (
                            <Check size={13} />
                          ) : (
                            <X size={13} />
                          )
                        ) : (
                          <CircleDashed size={13} />
                        )}
                      </span>
                      <span className="agent-index">{index + 1}</span>
                      <span className="agent-name">{stage.toUpperCase()}</span>
                      {finding && <EvidenceBadge level={finding.evidence_level} />}
                      <span className="agent-summary">
                        {finding?.summary ?? "Not reached"}
                      </span>
                      <ChevronRight
                        size={14}
                        className={`agent-chevron${open ? " open" : ""}`}
                      />
                    </button>

                    {open && finding && (
                      <div className="agent-detail">
                        {stageTools.length > 0 && (
                          <>
                            <p className="agent-detail-title">
                              <Wrench size={12} /> Tool calls
                            </p>
                            <table className="mini-table">
                              <tbody>
                                {stageTools.map((call, callIndex) => (
                                  <tr key={callIndex}>
                                    <td className="mono">{call.tool}</td>
                                    <td className="num">
                                      {call.duration_ms.toFixed(1)} ms
                                    </td>
                                    <td>
                                      <span
                                        className={`tag tone-${call.success ? "ok" : "error"}`}
                                      >
                                        {call.success ? "ok" : "failed"}
                                      </span>
                                    </td>
                                    <td className="muted-note">{call.summary}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </>
                        )}
                        {finding.concerns.length > 0 && (
                          <>
                            <p className="agent-detail-title">Concerns raised</p>
                            <ul className="caveat-list tight">
                              {finding.concerns.map((concern, concernIndex) => (
                                <li key={concernIndex}>{concern}</li>
                              ))}
                            </ul>
                          </>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
          </SectionCard>

          {result.report && (
            <SectionCard
              title="Assembled report"
              description={`Narrative produced by: ${result.report.narrative_provider}`}
              actions={result.report_id ? <span className="mono tag tone-neutral">{result.report_id}</span> : null}
            >
              <p className="narrative">{result.report.narrative}</p>

              {result.report.recommendations.length > 0 && (
                <>
                  <h3 className="detail-section">Recommended actions</h3>
                  <ul className="rec-list">
                    {result.report.recommendations.map((rec, index) => (
                      <li key={index}>{rec}</li>
                    ))}
                  </ul>
                </>
              )}

              {result.report.limitations.length > 0 && (
                <>
                  <h3 className="detail-section">Stated limitations</h3>
                  <ul className="caveat-list tight">
                    {result.report.limitations.map((limitation, index) => (
                      <li key={index}>{limitation}</li>
                    ))}
                  </ul>
                </>
              )}
            </SectionCard>
          )}
        </>
      )}

      <SectionCard title="Recent runs">
        {runs.isLoading ? (
          <LoadingSkeleton rows={3} height={40} />
        ) : (runs.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No runs yet"
            message="Select a detection above and run the workflow to produce a trace."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Workflow</th>
                  <th>Status</th>
                  <th className="num">Duration</th>
                  <th className="num">Tools</th>
                  <th>LLM</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.data?.items.map((run) => (
                  <tr key={run.workflow_id}>
                    <td className="mono">{run.workflow_id}</td>
                    <td>
                      <span
                        className={`tag tone-${run.status === "success" ? "ok" : "error"}`}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="num">
                      {run.duration_ms ? `${run.duration_ms.toFixed(0)} ms` : "—"}
                    </td>
                    <td className="num">{run.tool_calls}</td>
                    <td className="mono">{run.llm_provider ?? "none"}</td>
                    <td className="muted-note">{formatDateTime(run.started_at)}</td>
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
