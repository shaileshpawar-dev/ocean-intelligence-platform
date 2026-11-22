/**
 * Ask about India's water.
 *
 * The answer is rendered from structure, not from prose: a headline, the
 * water bodies or list it concerns, numbered citations, stated limitations,
 * and a button that puts the result on the map. Every citation links to the
 * map at the evidence's location, so the question → answer → evidence loop is
 * one click long.
 *
 * `no_evidence` is rendered as a clear refusal, never softened into a vague
 * answer: a question about mercury in a river where nobody measured mercury
 * must produce "no measurement exists", not a number.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Ban,
  BookOpen,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  MapPin,
  Send,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import type { MapAction, WaterAnswer, WaterCitation } from "@/lib/waterTypes";
import { ErrorState, PageHeader, SectionCard } from "@/components/ui";
import {
  WaterEvidenceBadge,
  WaterStatusBadge,
  formatDay,
} from "@/components/water";
import type { WaterStatus } from "@/lib/waterTypes";

const EXAMPLES = [
  "What is the latest available status of Mithi River?",
  "Show polluted rivers near Mumbai",
  "Lakes near Bengaluru",
  "Which rivers are within 20 km of Pune?",
  "High-concern water bodies in Maharashtra",
  "Monitoring stations near Chennai",
  "Has the Godavari improved over time?",
  "How much mercury is in Mithi River right now?",
];

function mapHref(action: MapAction): string {
  const params = new URLSearchParams();
  const slugs = action.water_body_slugs ?? [];
  if (slugs.length) params.set("highlight", slugs.slice(0, 40).join(","));
  if (action.bbox) params.set("bbox", action.bbox.map((n) => n.toFixed(4)).join(","));
  if (action.focus) params.set("focus", action.focus);
  return `/app/map?${params.toString()}`;
}

export default function WaterAI() {
  const [params] = useSearchParams();
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const ask = useMutation({ mutationFn: (q: string) => api.waterAsk(q) });

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3) return;
    setQuestion(text);
    ask.mutate(text);
  };

  // Questions typed into the map search arrive as ?q= and are asked at once.
  const initial = params.get("q");
  useEffect(() => {
    if (initial && initial.trim().length >= 3) ask.mutate(initial.trim());
  }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader
        title="Ask about India's water"
        subtitle="Answers are assembled from stored observations — CPCB and CWC manual sampling, and CPCB's hourly real-time analysers — against the reference criteria, with every figure cited and dated. Nothing is estimated, and sources are never combined."
      />

      <SectionCard>
        <form
          className="ask-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
        >
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Which rivers near Pune are polluted?"
            aria-label="Your question"
            maxLength={500}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={ask.isPending || question.trim().length < 3}
          >
            <Send size={14} /> {ask.isPending ? "Looking up…" : "Ask"}
          </button>
        </form>

        <div className="ask-examples">
          {EXAMPLES.map((example) => (
            <button
              type="button"
              key={example}
              className="ask-example"
              onClick={() => submit(example)}
            >
              {example}
            </button>
          ))}
        </div>
      </SectionCard>

      {ask.isError && <ErrorState error={ask.error} onRetry={() => submit(question)} />}
      {ask.data && <AnswerView answer={ask.data} />}
    </>
  );
}

/* ------------------------------------------------------------------ */

function AnswerView({ answer }: { answer: WaterAnswer }) {
  const navigate = useNavigate();
  const [showTrace, setShowTrace] = useState(false);
  const refused = answer.status === "no_evidence";

  return (
    <>
      <SectionCard>
        <div className={`answer-head answer-${answer.status}`}>
          <span className="answer-icon" aria-hidden>
            {refused ? <Ban size={18} /> : <ShieldCheck size={18} />}
          </span>
          <div>
            <p className="answer-kind">
              {refused
                ? "No evidence — no answer given"
                : answer.status === "partial"
                  ? "Partly supported by the records"
                  : "Grounded in stored records"}
            </p>
            <p className="answer-headline">{answer.headline}</p>
          </div>
        </div>

        {answer.map_action && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => navigate(mapHref(answer.map_action as MapAction))}
          >
            <MapPin size={13} />{" "}
            {answer.map_action.water_body_slugs?.length
              ? `Show ${answer.map_action.water_body_slugs.length} on the map`
              : "Show on the map"}
          </button>
        )}

        {answer.sections.map((section, index) => (
          <SectionBody key={index} section={section} />
        ))}
      </SectionCard>

      {answer.citations.length > 0 && (
        <SectionCard
          title={`Evidence (${answer.citations.length})`}
          description="Each item is a stored record. Select one to see it on the map."
        >
          <ol className="citation-list">
            {answer.citations.map((c) => (
              <CitationItem key={c.position} citation={c} />
            ))}
          </ol>
        </SectionCard>
      )}

      {answer.limitations.length > 0 && (
        <SectionCard title="Limitations">
          <ul className="status-reasons">
            {answer.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard>
        <button
          type="button"
          className="trace-toggle"
          onClick={() => setShowTrace((v) => !v)}
          aria-expanded={showTrace}
        >
          {showTrace ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          How this answer was produced ({answer.trace.length} steps,{" "}
          {answer.llm_used ? "language model used" : "no language model"})
        </button>
        {showTrace && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Tool</th>
                  <th>Result</th>
                  <th className="num">ms</th>
                </tr>
              </thead>
              <tbody>
                {answer.trace.map((step, i) => (
                  <tr key={i}>
                    <td>
                      <span className="chip">{step.stage}</span>
                    </td>
                    <td className="mono">{step.tool}</td>
                    <td>{step.result}</td>
                    <td className="num">{step.duration_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted-note">
              Resolved: {describeResolution(answer)} · pipeline{" "}
              {answer.pipeline_version}
            </p>
          </div>
        )}
      </SectionCard>
    </>
  );
}

function describeResolution(answer: WaterAnswer): string {
  const r = answer.resolution;
  const parts = [
    ...r.water_bodies,
    ...r.districts,
    ...r.states,
    ...r.parameters,
    ...r.water_types.map((t) => `type: ${t}`),
  ];
  return parts.length ? parts.join(", ") : "nothing matched";
}

/* ------------------------------------------------------------------ */

type Indicator = {
  label: string;
  value: string;
  verdict: string;
  failed: boolean;
  observed_at: string | null;
  cite: number;
};

type ListItem = {
  name: string;
  slug: string;
  water_type?: string;
  distance_km?: number;
  detail?: string;
  latest_available_status?: WaterStatus | null;
  latest_observed_at?: string | null;
  cite: number;
};

function SectionBody({ section }: { section: Record<string, unknown> }) {
  const kind = section.kind as string;

  if (kind === "water_body") {
    const indicators = (section.indicators as Indicator[]) ?? [];
    return (
      <div className="answer-block">
        <h3>
          <Link to={`/app/water/${section.slug as string}`}>
            {section.water_body as string}
          </Link>{" "}
          <span className="muted-note">{section.place as string}</span>
        </h3>
        <dl className="answer-facts">
          <div>
            <dt>When last measured</dt>
            <dd>
              {section.latest_available_status as string}{" "}
              <sup>[{section.status_cite as number}]</sup>
            </dd>
          </div>
          <div>
            <dt>Right now</dt>
            <dd>{section.present_status as string}</dd>
          </div>
        </dl>
        {indicators.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Indicator</th>
                <th>Value</th>
                <th>Against the reference</th>
                <th>Measured</th>
              </tr>
            </thead>
            <tbody>
              {indicators.map((ind) => (
                <tr key={ind.label}>
                  <td>{ind.label}</td>
                  <td className="mono">
                    {ind.value} <sup>[{ind.cite}]</sup>
                  </td>
                  <td className={ind.failed ? "text-bad" : ""}>{ind.verdict}</td>
                  <td>{formatDay(ind.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {section.evidence_layers ? (
          <EvidenceLayers layers={section.evidence_layers as EvidenceLayerMap} />
        ) : null}
      </div>
    );
  }

  if (kind === "stations") {
    const items =
      (section.items as {
        id: number;
        name: string;
        water_body: string | null;
        water_body_slug: string | null;
        distance_km: number;
        latest_observed_at: string | null;
        cite: number;
      }[]) ?? [];
    return (
      <div className="answer-block">
        <table className="data-table">
          <thead>
            <tr>
              <th>Monitoring station</th>
              <th>Water body</th>
              <th>Distance</th>
              <th>Latest observation</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  <Link to={`/app/stations/${item.id}`}>{item.name}</Link>{" "}
                  <sup>[{item.cite}]</sup>
                </td>
                <td>
                  {item.water_body_slug ? (
                    <Link to={`/app/water/${item.water_body_slug}`}>{item.water_body}</Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="mono">{item.distance_km} km</td>
                <td>{formatDay(item.latest_observed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (kind === "list") {
    const items = (section.items as ListItem[]) ?? [];
    return (
      <div className="answer-block">
        <table className="data-table">
          <thead>
            <tr>
              <th>Water body</th>
              <th>When last measured</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.slug}>
                <td>
                  <Link to={`/app/water/${item.slug}`}>{item.name}</Link>{" "}
                  <sup>[{item.cite}]</sup>
                </td>
                <td>
                  <WaterStatusBadge status={item.latest_available_status} size="sm" />
                </td>
                <td className="muted-note">
                  {item.distance_km !== undefined
                    ? `${item.distance_km} km · ${formatDay(item.latest_observed_at)}`
                    : item.detail}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (kind === "trend") {
    const means = section.annual_means as Record<string, number>;
    const samples = section.samples_per_year as Record<string, number>;
    return (
      <div className="answer-block">
        <table className="data-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Mean {section.label as string}</th>
              <th className="num">Samples</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(means).map((year) => (
              <tr key={year}>
                <td>{year}</td>
                <td className="mono">
                  {means[year]} {section.unit as string}
                </td>
                <td className="num">{samples[year]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (kind === "passages") {
    const items = (section.items as { title: string; text: string; cite: number }[]) ?? [];
    return (
      <div className="answer-block">
        {items.map((p) => (
          <blockquote className="passage" key={p.cite}>
            <p className="passage-title">
              <BookOpen size={12} /> {p.title} <sup>[{p.cite}]</sup>
            </p>
            <p>{p.text}</p>
          </blockquote>
        ))}
      </div>
    );
  }

  return null;
}

function CitationItem({ citation }: { citation: WaterCitation }) {
  const navigate = useNavigate();
  const target = citation.water_body_slug
    ? `/app/map?focus=${encodeURIComponent(citation.water_body_slug)}&highlight=${encodeURIComponent(citation.water_body_slug)}`
    : null;

  return (
    <li className="citation">
      <span className="citation-num">{citation.position}</span>
      <div className="citation-body">
        <p className="citation-title">
          {citation.title} <WaterEvidenceBadge type={citation.evidence_type} />
        </p>
        <p className="citation-detail">{citation.detail}</p>
        <p className="citation-meta">
          {citation.observed_at && (
            <>
              <CalendarClock size={11} /> {formatDay(citation.observed_at)} ·{" "}
            </>
          )}
          {citation.source}
          {citation.source_reference && (
            <>
              {" "}
              · <code>{citation.source_reference}</code>
            </>
          )}
        </p>
      </div>
      {target ? (
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={() => navigate(target)}
        >
          <MapPin size={12} /> Map
        </button>
      ) : citation.url ? (
        <a
          className="btn btn-outline btn-sm"
          href={citation.url}
          target="_blank"
          rel="noreferrer noopener"
        >
          Source
        </a>
      ) : null}
    </li>
  );
}

type EvidenceLayerMap = {
  MEASURED: { count: number; latest: string | null; source: string };
  REFERENCE_COMPARISON: {
    standard: string | null;
    basis: string | null;
    unavailable_reason: string | null;
  };
  SOURCE_CLASSIFICATION: { source: string; priority: string | null; assessment_year: number | null }[];
  DERIVED_STATUS: { label: string | null; as_of: string | null };
  SATELLITE_OBSERVED: { label: string; value: number; date: string } | null;
};

/** The answer split by kind of evidence, so none is read as another. */
function EvidenceLayers({ layers }: { layers: EvidenceLayerMap }) {
  const ref = layers.REFERENCE_COMPARISON;
  return (
    <dl className="evidence-layers">
      <div>
        <dt>
          <WaterEvidenceBadge type="MEASURED" />
        </dt>
        <dd>
          {layers.MEASURED.count} indicator{layers.MEASURED.count === 1 ? "" : "s"}, latest{" "}
          {formatDay(layers.MEASURED.latest)} · {layers.MEASURED.source}
        </dd>
      </div>
      <div>
        <dt>
          <WaterEvidenceBadge type="REFERENCE_COMPARISON" />
        </dt>
        <dd>
          {ref.standard
            ? `${ref.standard} (${(ref.basis ?? "").toLowerCase()})`
            : `Reference comparison unavailable. ${ref.unavailable_reason ?? ""}`}
        </dd>
      </div>
      <div>
        <dt>
          <WaterEvidenceBadge type="SOURCE_CLASSIFICATION" />
        </dt>
        <dd>
          {layers.SOURCE_CLASSIFICATION.length
            ? layers.SOURCE_CLASSIFICATION.map(
                (c) =>
                  `${c.source}${c.priority ? `, priority ${c.priority}` : ""}${
                    c.assessment_year ? ` (${c.assessment_year})` : ""
                  }`,
              ).join("; ")
            : "None published for this water body in the platform's data."}
        </dd>
      </div>
      <div>
        <dt>
          <WaterEvidenceBadge type="DERIVED_STATUS" />
        </dt>
        <dd>
          {layers.DERIVED_STATUS.label ?? "Not assessed"}, as of{" "}
          {formatDay(layers.DERIVED_STATUS.as_of)} — not a statement about today.
        </dd>
      </div>
      {layers.SATELLITE_OBSERVED && (
        <div>
          <dt>
            <WaterEvidenceBadge type="SATELLITE_OBSERVED" />
          </dt>
          <dd>
            {layers.SATELLITE_OBSERVED.label}: {layers.SATELLITE_OBSERVED.value.toFixed(3)} (index,
            no unit) on {formatDay(layers.SATELLITE_OBSERVED.date)}. Not a measurement.
          </dd>
        </div>
      )}
    </dl>
  );
}
