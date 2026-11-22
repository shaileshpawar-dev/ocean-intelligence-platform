/**
 * Reference standards.
 *
 * This page exists so that "why is this river marked high concern?" has a
 * public, checkable answer. Every threshold the status engine can apply is
 * listed with the document it came from, and the order in which a standard is
 * chosen for a water body is stated — including the case where none is.
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Info, Scale } from "lucide-react";
import { api } from "@/lib/api";
import type { StandardDefinition, StandardThreshold } from "@/lib/waterTypes";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";

function limitText(t: StandardThreshold): string {
  const unit = t.unit ? ` ${t.unit}` : "";
  if (t.type === "range") return `${t.min} – ${t.max}${unit}`;
  if (t.type === "minimum") return `at least ${t.min}${unit}`;
  if (t.type === "maximum") return `at most ${t.max}${unit}`;
  return "categorical";
}

export default function WaterStandards() {
  const standards = useQuery({
    queryKey: ["water-standards"],
    queryFn: api.waterStandards,
  });

  if (standards.isLoading) return <LoadingSkeleton rows={4} height={90} />;
  if (standards.isError) {
    return <ErrorState error={standards.error} onRetry={() => standards.refetch()} />;
  }
  const data = standards.data;
  if (!data) return null;

  const national = data.standards.find(
    (s) => s.code === data.national_assessment.standard_code,
  );
  const others = data.standards.filter((s) => s.code !== data.national_assessment.standard_code);

  return (
    <>
      <PageHeader
        title="Reference standards"
        subtitle="The criteria this platform can apply, where each comes from, and how one is chosen."
        actions={<Scale size={16} className="text-muted" />}
      />

      <SectionCard title="How a standard is chosen">
        <p className="muted-note">
          "Is this water polluted?" has no answer until someone says <em>polluted for what</em>.
          No standard is applied by default. For each water body the first applicable rule
          below decides; when none applies the platform shows the measurements and says
          "Reference comparison unavailable" rather than borrowing a standard.
        </p>
        <ol className="standards-order">
          {data.selection_order.map((step) => (
            <li key={step.basis}>{step.label}</li>
          ))}
        </ol>
        <p className="standards-note">
          <Info size={13} aria-hidden /> {data.national_assessment.reason} Applies to:{" "}
          {data.national_assessment.applies_to.join(", ").replace(/_/g, " ")}.
        </p>
      </SectionCard>

      {national && (
        <SectionCard title="National assessment reference (rivers)">
          <StandardTable standard={national} />
        </SectionCard>
      )}

      <SectionCard title="CPCB designated best use classes">
        <p className="muted-note">
          Applied only when a designated use is recorded for a water body by an authoritative
          source, or when you choose one on a water body's page.
        </p>
        {others.map((standard) => (
          <StandardTable key={standard.code} standard={standard} />
        ))}
      </SectionCard>

      <SectionCard title="CPCB polluted-river-stretch priorities (context only)">
        <p className="muted-note">
          CPCB groups the stretches it identifies as polluted into five priorities by BOD.
          The platform labels a water body a polluted stretch only when an official
          classification is imported for it; it never assigns these priorities itself.
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Priority</th>
              <th>BOD range</th>
            </tr>
          </thead>
          <tbody>
            {data.polluted_stretch_bands.map((band) => (
              <tr key={band.priority}>
                <td>{band.priority}</td>
                <td>{band.describes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>

      <SectionCard title="Notes">
        <ul className="standards-notes">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </SectionCard>
    </>
  );
}

function StandardTable({ standard }: { standard: StandardDefinition }) {
  return (
    <div className="standard-block">
      <h3 className="standard-title">
        {standard.name}{" "}
        <span className="mono muted-note">{standard.code}</span>
      </h3>
      {standard.category && <p className="muted-note">{standard.category}</p>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Limit</th>
            <th>Desirable</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {standard.thresholds.map((t) => (
            <tr key={t.parameter}>
              <td>{t.label}</td>
              <td className="mono">{limitText(t)}</td>
              <td className="mono">
                {t.desirable != null ? `${t.desirable}${t.unit ? ` ${t.unit}` : ""}` : "—"}
              </td>
              <td className="muted-note">{t.note ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="standard-source">
        {standard.legal_basis} · {standard.issuing_body} ·{" "}
        <a href={standard.source_url} target="_blank" rel="noreferrer noopener">
          Source document <ExternalLink size={11} aria-hidden />
        </a>
      </p>
      <p className="standard-verified muted-note">{standard.verified_note}</p>
    </div>
  );
}
