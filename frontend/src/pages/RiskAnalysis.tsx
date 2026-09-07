/**
 * Risk Analysis.
 *
 * The score is arithmetic, and this page proves it: the contribution bars sum
 * to the reported score, and the "partial assessment" warning is prominent
 * rather than a footnote. A score computed from four factors is not the same
 * claim as one computed from six, and the UI must not let those look alike.
 */

import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  RiskBadge,
  SectionCard,
  Unavailable,
  titleise,
} from "@/components/ui";

const FACTOR_COLOURS = [
  "#dc2626",
  "#ea580c",
  "#d97706",
  "#0284c7",
  "#7c3aed",
  "#0f766e",
];

/** Semi-circular gauge. Renders only a value the backend actually returned. */
function RiskGauge({ score, severity }: { score: number; severity: string }) {
  const radius = 92;
  const circumference = Math.PI * radius;
  const progress = Math.min(100, Math.max(0, score)) / 100;
  const colour =
    severity === "CRITICAL"
      ? "var(--sev-critical)"
      : severity === "HIGH"
        ? "var(--sev-high)"
        : severity === "MEDIUM"
          ? "var(--sev-medium)"
          : "var(--sev-low)";

  return (
    <div className="gauge">
      <svg viewBox="0 0 220 124" role="img" aria-label={`Risk ${score} of 100`}>
        <path
          d="M18 112 A 92 92 0 0 1 202 112"
          fill="none"
          stroke="var(--border)"
          strokeWidth="15"
          strokeLinecap="round"
        />
        <path
          d="M18 112 A 92 92 0 0 1 202 112"
          fill="none"
          stroke={colour}
          strokeWidth="15"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          style={{ transition: "stroke-dashoffset 600ms var(--ease)" }}
        />
      </svg>
      <div className="gauge-value">
        <strong style={{ color: colour }}>{score.toFixed(1)}</strong>
        <span>/ 100</span>
      </div>
    </div>
  );
}

export default function RiskAnalysis() {
  const { eventId } = useParams();
  const [selected, setSelected] = useState<string | null>(eventId ?? null);

  const events = useQuery({
    queryKey: ["events", "risk-picker"],
    queryFn: () => api.events({ limit: 200 }),
  });

  const active = selected ?? eventId ?? events.data?.items[0]?.event_id ?? null;

  const detail = useQuery({
    queryKey: ["event", active],
    queryFn: () => api.event(active!),
    enabled: Boolean(active),
  });

  if (events.isLoading) return <LoadingSkeleton rows={3} height={110} />;
  if (events.isError)
    return <ErrorState error={events.error} onRetry={() => events.refetch()} />;

  if ((events.data?.items.length ?? 0) === 0) {
    return (
      <>
        <PageHeader title="Risk Analysis" subtitle="Deterministic environmental risk scoring." />
        <SectionCard>
          <EmptyState
            title="No detections to assess"
            message="Risk is computed per detection. Run a satellite ingestion cycle to produce events."
          />
        </SectionCard>
      </>
    );
  }

  const assessment = detail.data?.risk_assessment ?? null;
  const awarded = assessment
    ? assessment.contributions.reduce((sum, item) => sum + item.points, 0)
    : 0;
  const available = assessment
    ? assessment.contributions.reduce((sum, item) => sum + item.max_points, 0)
    : 0;

  return (
    <>
      <PageHeader
        title="Risk Analysis"
        subtitle="A six-factor deterministic score. No language model produces or adjusts this number."
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <select
            className="select grow"
            value={active ?? ""}
            onChange={(event) => setSelected(event.target.value)}
            aria-label="Detection"
          >
            {events.data?.items.map((event) => (
              <option key={event.event_id} value={event.event_id}>
                {titleise(event.signature)} · {event.region_name} ·{" "}
                {event.risk_score?.toFixed(1) ?? "—"}
              </option>
            ))}
          </select>
        </div>
      </SectionCard>

      {detail.isLoading && <LoadingSkeleton rows={3} height={130} />}
      {detail.isError && <ErrorState error={detail.error} />}

      {detail.data && !assessment && (
        <SectionCard>
          <EmptyState
            title="No stored assessment"
            message="This detection has no persisted risk assessment. It may predate the risk engine or have failed scoring."
            icon={<ShieldAlert size={20} />}
          />
        </SectionCard>
      )}

      {detail.data && assessment && (
        <>
          <div className="risk-hero">
            <SectionCard>
              <div className="risk-hero-inner">
                <RiskGauge score={assessment.score} severity={assessment.severity} />
                <div className="risk-hero-meta">
                  <RiskBadge severity={assessment.severity} />
                  <EvidenceBadge level={assessment.evidence_level} />
                  <p className="risk-region">{detail.data.region_name}</p>
                  <p className="muted-note mono">{assessment.engine_version}</p>
                  <p className="muted-note">
                    {awarded.toFixed(1)} of {available} evaluable points →
                    renormalised to {assessment.score.toFixed(1)}
                  </p>
                </div>
              </div>
            </SectionCard>

            {assessment.missing_factors.length > 0 && (
              <div className="partial-warning">
                <AlertTriangle size={17} />
                <div>
                  <strong>Partial assessment</strong>
                  <p>
                    {assessment.missing_factors.map(titleise).join(", ")}{" "}
                    {assessment.missing_factors.length === 1 ? "was" : "were"} not
                    evaluated. The score is renormalised over the factors that
                    could be evaluated — this is a <em>partial</em> assessment,
                    not a low one. Treating unknown inputs as zero would make an
                    unmeasured event appear safe.
                  </p>
                </div>
              </div>
            )}
          </div>

          <SectionCard
            title="Contribution breakdown"
            description="These points sum to the score above. Every figure is reconstructible."
          >
            <div className="contrib-stack" aria-hidden="true">
              {assessment.contributions
                .slice()
                .sort((a, b) => b.points - a.points)
                .map((contribution, index) => (
                  <span
                    key={contribution.factor}
                    style={{
                      width: `${(contribution.points / (available + assessment.missing_factors.length * 15)) * 100}%`,
                      background: FACTOR_COLOURS[index % FACTOR_COLOURS.length],
                    }}
                  />
                ))}
              <span
                className="contrib-gap"
                style={{
                  width: `${((available - awarded) / (available + assessment.missing_factors.length * 15)) * 100}%`,
                }}
              />
              {assessment.missing_factors.length > 0 && (
                <span
                  className="contrib-excluded"
                  style={{
                    width: `${((assessment.missing_factors.length * 15) / (available + assessment.missing_factors.length * 15)) * 100}%`,
                  }}
                />
              )}
            </div>

            <ul className="contrib-list">
              {assessment.contributions
                .slice()
                .sort((a, b) => b.points - a.points)
                .map((contribution, index) => (
                  <li key={contribution.factor}>
                    <span
                      className="contrib-dot"
                      style={{
                        background: FACTOR_COLOURS[index % FACTOR_COLOURS.length],
                      }}
                    />
                    <div className="contrib-body">
                      <div className="contrib-head">
                        <strong>{titleise(contribution.factor)}</strong>
                        <span className="contrib-points">
                          {contribution.points.toFixed(1)}
                          <em>/ {contribution.max_points}</em>
                        </span>
                      </div>
                      <p>{contribution.detail}</p>
                      <EvidenceBadge level={contribution.evidence_level} />
                    </div>
                  </li>
                ))}

              {assessment.missing_factors.map((factor) => (
                <li key={factor} className="contrib-missing">
                  <span className="contrib-dot hatched" />
                  <div className="contrib-body">
                    <div className="contrib-head">
                      <strong>{titleise(factor)}</strong>
                      <span className="contrib-points">
                        <Unavailable reason="Input data not available for this factor" />
                      </span>
                    </div>
                    <p>
                      Excluded from the denominator. Not evaluated, and
                      deliberately not counted as zero.
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </SectionCard>

          {detail.data.caveats.length > 0 && (
            <SectionCard title="Caveats carried by this detection">
              <ul className="caveat-list">
                {detail.data.caveats.map((caveat, index) => (
                  <li key={index}>{caveat}</li>
                ))}
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </>
  );
}
