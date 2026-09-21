/**
 * Reference standards.
 *
 * This page exists so that "why is this river marked polluted?" has a public,
 * checkable answer. Every threshold the status engine applies is listed here
 * with the document it came from and a link to that document. A platform that
 * classifies water quality without showing its criteria is asking to be taken
 * on trust, which is precisely what this one refuses to do.
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Info, Scale } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";

export default function WaterStandards() {
  const standards = useQuery({
    queryKey: ["water-standards"],
    queryFn: api.waterStandards,
  });

  if (standards.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (standards.isError) {
    return (
      <ErrorState error={standards.error} onRetry={() => standards.refetch()} />
    );
  }

  const data = standards.data;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title="Reference standards"
        subtitle="The criteria this platform applies, and where each one comes from."
        actions={<Scale size={16} className="text-muted" />}
      />

      <SectionCard title="Designated best use">
        <p className="muted-note">
          "Is this river polluted?" has no answer until someone says{" "}
          <em>polluted for what</em>. Water unfit to drink untreated may be
          perfectly fit for irrigation. CPCB encodes exactly that idea in five
          designated-use classes, each with its own limits. This platform
          defaults to <strong>class {data.default_use}</strong> —{" "}
          {data.default_use_label} — because it matches the use most monitored
          Indian river stretches are actually put to, and its BOD limit
          coincides with the national polluted-stretch threshold.
        </p>

        <div className="use-classes">
          {Object.entries(data.classes).map(([code, label]) => (
            <div
              className={`use-class ${code === data.default_use ? "is-default" : ""}`}
              key={code}
            >
              <span className="use-code">Class {code}</span>
              <span className="use-label">{label}</span>
              {code === data.default_use && (
                <span className="use-default-tag">platform default</span>
              )}
            </div>
          ))}
        </div>
      </SectionCard>

      {Object.entries(data.thresholds_by_use).map(([use, limits]) => (
        <SectionCard
          key={use}
          title={`Class ${use} — ${data.classes[use]}`}
          description={`${limits.length} parameter${limits.length === 1 ? "" : "s"} governed. Parameters absent from this list are not judged under this class.`}
        >
          {limits.length === 0 ? (
            <p className="muted-note">This class specifies no numeric limits.</p>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Minimum</th>
                    <th>Maximum</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {limits.map((limit) => (
                    <tr key={limit.parameter}>
                      <td>{limit.describes}</td>
                      <td>{limit.min ?? "—"}</td>
                      <td>{limit.max ?? "—"}</td>
                      <td>{limit.unit ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      ))}

      <SectionCard
        title="Polluted river stretches"
        description="The national criterion used to identify and prioritise polluted locations."
      >
        <p className="muted-note">
          A monitoring location whose biochemical oxygen demand exceeds{" "}
          <strong>{data.polluted_stretch.bod_threshold_mg_l} mg/L</strong> is
          treated as polluted. Two or more such locations in continuous
          sequence on the same river constitute a Polluted River Stretch.
        </p>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Priority</th>
                <th>BOD range</th>
              </tr>
            </thead>
            <tbody>
              {data.polluted_stretch.bands.map((band) => (
                <tr key={band.priority}>
                  <td>
                    <strong>Priority {band.priority}</strong>
                  </td>
                  <td>{band.describes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <a
          className="btn btn-outline btn-sm"
          href={data.polluted_stretch.source_url}
          target="_blank"
          rel="noreferrer noopener"
        >
          {data.polluted_stretch.source} <ExternalLink size={12} />
        </a>
      </SectionCard>

      <SectionCard title="Sources">
        <ul className="source-links">
          {data.sources.map((source) => (
            <li key={source.url}>
              <a href={source.url} target="_blank" rel="noreferrer noopener">
                {source.name} <ExternalLink size={11} />
              </a>
            </li>
          ))}
        </ul>
        {data.notes.map((note) => (
          <p className="muted-note" key={note}>
            <Info size={12} /> {note}
          </p>
        ))}
      </SectionCard>
    </>
  );
}
