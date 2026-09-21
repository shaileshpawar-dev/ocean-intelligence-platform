/**
 * Data sources and ingestion quality.
 *
 * Counts of records that failed validation are shown as prominently as the
 * ones that passed. The pipeline flags bad data and keeps it rather than
 * dropping it, precisely so this page can exist: a discarded record is
 * invisible, and invisible problems never get fixed.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Info,
  Radio,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import { StatCard, formatDay } from "@/components/water";

const FLAG_META: Record<string, { label: string; tone: string; hint: string }> = {
  ok: {
    label: "Valid",
    tone: "ok",
    hint: "Parsed cleanly and passed every validation rule.",
  },
  suspect: {
    label: "Suspect",
    tone: "warn",
    hint: "Stored, but a rule fired — implausible magnitude, censored value or an odd coordinate.",
  },
  invalid: {
    label: "Invalid",
    tone: "bad",
    hint: "Could not be parsed into the parameter's type. Kept with its raw text so it can be inspected.",
  },
};

export default function DataSources() {
  const overview = useQuery({
    queryKey: ["water-overview"],
    queryFn: api.waterOverview,
  });
  const quality = useQuery({
    queryKey: ["water-quality-report"],
    queryFn: api.waterQualityReport,
  });

  if (overview.isLoading || quality.isLoading) {
    return <LoadingSkeleton rows={4} height={90} />;
  }
  if (overview.isError) {
    return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;
  }

  const data = overview.data;
  const q = quality.data;
  if (!data) return null;

  const totalObs = Object.values(q?.observations_by_flag ?? {}).reduce(
    (a, b) => a + b,
    0,
  );

  return (
    <>
      <PageHeader
        title="Data sources"
        subtitle="Where the platform's numbers come from, whether each source is reachable, and what the last ingestion actually produced."
        actions={<Database size={16} className="text-muted" />}
      />

      <SectionCard title="Providers">
        {data.sources.map((source) => (
          <div className="provider-card" key={source.key}>
            <div className="provider-head">
              <div>
                <strong>{source.name}</strong>
                <p className="muted-note">{source.organisation}</p>
              </div>
              <span
                className={`wstatus wstatus-${source.is_available ? "ok" : "bad"} wstatus-sm`}
              >
                <Radio size={11} aria-hidden />
                {source.is_available ? "Available" : "Unavailable"}
              </span>
            </div>
            <dl className="source-facts">
              <div>
                <dt>Expected cadence</dt>
                <dd>{source.expected_cadence}</dd>
              </div>
              <div>
                <dt>Last successful sync</dt>
                <dd>{formatDay(source.last_success_at)}</dd>
              </div>
            </dl>
            {source.last_error && (
              <p className="provider-error">
                <AlertTriangle size={12} /> {source.last_error}
              </p>
            )}
          </div>
        ))}

        <p className="muted-note">
          <Info size={12} /> Only providers that read a genuinely accessible
          source are registered. Sources the platform cannot currently reach
          are documented as unimplemented rather than given a stub that would
          look like a working integration.
        </p>
      </SectionCard>

      {data.last_ingestion && (
        <SectionCard
          title="Last ingestion run"
          description="Per-run counts are retained so a source that quietly starts returning half as many rows shows up as history rather than as a mystery."
        >
          <div className="stat-row">
            <StatCard label="Run" value={<code>{data.last_ingestion.run_id}</code>} />
            <StatCard
              label="Outcome"
              value={data.last_ingestion.status}
              tone={data.last_ingestion.status === "success" ? "ok" : "warn"}
            />
            <StatCard
              label="Records inserted"
              value={data.last_ingestion.records_inserted.toLocaleString()}
            />
            <StatCard
              label="Finished"
              value={formatDay(data.last_ingestion.finished_at)}
            />
          </div>
        </SectionCard>
      )}

      {q && (
        <>
          <SectionCard
            title="Observation quality"
            description="Records that fail validation are flagged and kept, never silently dropped."
          >
            <div className="quality-grid">
              {Object.entries(q.observations_by_flag).map(([flag, count]) => {
                const meta = FLAG_META[flag] ?? {
                  label: flag,
                  tone: "unknown",
                  hint: "",
                };
                const pct = totalObs ? ((count / totalObs) * 100).toFixed(1) : "0";
                return (
                  <div className={`quality-card quality-${meta.tone}`} key={flag}>
                    <span className="quality-label">
                      {meta.tone === "ok" ? (
                        <CheckCircle2 size={13} aria-hidden />
                      ) : (
                        <AlertTriangle size={13} aria-hidden />
                      )}
                      {meta.label}
                    </span>
                    <span className="quality-value">{count.toLocaleString()}</span>
                    <span className="quality-pct">{pct}% of observations</span>
                    <span className="muted-note">{meta.hint}</span>
                  </div>
                );
              })}
            </div>
          </SectionCard>

          <SectionCard title="Station geolocation">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Coordinate quality</th>
                    <th className="num">Stations</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(q.stations_by_geo_quality).map(([key, count]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td className="num">{count}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>Not linked to a water body</td>
                    <td className="num">{q.stations_without_water_body}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            {q.notes.map((note) => (
              <p className="muted-note" key={note}>
                <Info size={12} /> {note}
              </p>
            ))}
          </SectionCard>
        </>
      )}
    </>
  );
}
