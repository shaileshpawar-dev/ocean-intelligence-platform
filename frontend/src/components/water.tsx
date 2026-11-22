/**
 * Water intelligence UI primitives.
 *
 * The rule these components exist to enforce: a status is never shown without
 * the date it refers to. `WaterStatusBadge` on its own answers "what is this
 * like now?", and for most Indian water bodies the honest answer is "no
 * recent data". `LatestAvailableStatus` answers "what did the last
 * measurement find?" and always renders the date alongside, because the same
 * words without the date would be a claim about today that the data does not
 * support.
 *
 * Colour is never the only signal. Every status carries an icon and a text
 * label, so the meaning survives greyscale printing, colour-blindness and a
 * screen reader.
 */

import type { ReactNode } from "react";
import {
  AlertTriangle,
  CalendarClock,
  Check,
  CircleHelp,
  Droplets,
  Scale,
  FlaskConical,
  Info,
  MapPin,
  Minus,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Waves,
} from "lucide-react";
import type {
  ComparisonResult,
  DataAvailability,
  StatusDetail,
  WaterBodyType,
  WaterEvidenceType,
  WaterParameterReading,
  WaterStatus,
} from "@/lib/waterTypes";

/* ------------------------------------------------------------------ */
/* Status                                                              */
/* ------------------------------------------------------------------ */

export const STATUS_META: Record<
  WaterStatus,
  { label: string; tone: string; icon: typeof ShieldCheck; description: string }
> = {
  WITHIN_REFERENCE: {
    label: "Within reference",
    tone: "ok",
    icon: ShieldCheck,
    description: "Every evaluable parameter satisfies the reference standard applied.",
  },
  ELEVATED: {
    label: "Elevated",
    tone: "warn",
    icon: AlertTriangle,
    description: "At least one parameter breaches its limit, none severely.",
  },
  HIGH_CONCERN: {
    label: "High concern",
    tone: "bad",
    icon: ShieldAlert,
    description: "A severe breach, or several simultaneous breaches.",
  },
  POLLUTED_STRETCH: {
    label: "Polluted stretch",
    tone: "critical",
    icon: ShieldAlert,
    description:
      "Listed by an official source (CPCB) as a polluted river stretch. Never assigned from observations alone.",
  },
  INSUFFICIENT_DATA: {
    label: "Insufficient data",
    tone: "unknown",
    icon: CircleHelp,
    description:
      "Observations exist but none of the parameters the standard governs were measured.",
  },
  NO_RECENT_DATA: {
    label: "No recent data",
    tone: "unknown",
    icon: CalendarClock,
    description:
      "The latest observation is too old to describe this water body's present state.",
  },
  NO_APPLICABLE_REFERENCE: {
    label: "No applicable reference",
    tone: "unknown",
    icon: Scale,
    description:
      "Measured, but no standard is established as applying to this water body, so no judgement is made.",
  },
};

export function WaterStatusBadge({
  status,
  size = "md",
}: {
  status: WaterStatus | null | undefined;
  size?: "sm" | "md";
}) {
  if (!status) {
    return (
      <span className="wstatus wstatus-unknown wstatus-sm">
        <CircleHelp size={12} aria-hidden />
        Not assessed
      </span>
    );
  }
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={`wstatus wstatus-${meta.tone} wstatus-${size}`}
      title={meta.description}
    >
      <Icon size={size === "sm" ? 12 : 14} aria-hidden />
      {meta.label}
    </span>
  );
}

/**
 * The historical verdict, never shown without its date.
 *
 * This is the component that makes years-old official data useful without
 * becoming dishonest: "as of 02 Dec 2021, BOD was above the bathing-water limit" is
 * a true and checkable statement, where the same sentence in the present
 * tense would not be.
 */
export function LatestAvailableStatus({
  detail,
  observedAt,
  describesNow,
}: {
  detail: StatusDetail | null | undefined;
  observedAt?: string | null;
  /** Whether the reading is recent enough to describe the water body now.
   *  Comes from the backend's freshness assessment, which judges the age
   *  against the cadence of the source that produced it: hourly for the
   *  real-time analysers, monthly for the manual programmes. */
  describesNow?: boolean;
}) {
  if (!detail) return null;
  const asOf = detail.as_of ?? observedAt ?? detail.freshness?.observed_at ?? null;
  const present =
    describesNow ?? detail.describes_present_state ?? false;
  return (
    <div className="latest-status">
      <div className="latest-status-head">
        <WaterStatusBadge status={detail.status} />
        {(detail.source_classifications ?? [])
          .filter((c) => c.priority)
          .slice(0, 1)
          .map((c) => (
            <span
              key={c.source_reference}
              className="priority-band"
              title={`${c.source}${c.assessment_year ? `, ${c.assessment_year}` : ""}`}
            >
              {c.source} priority {c.priority}
            </span>
          ))}
      </div>
      <p className="latest-status-asof">
        <CalendarClock size={13} aria-hidden />
        <span>
          {present ? (
            <>
              As measured on <strong>{formatDay(asOf)}</strong> — recent enough
              to describe this water body now.
            </>
          ) : (
            <>
              As measured on <strong>{formatDay(asOf)}</strong> — not a
              statement about this water body today.
            </>
          )}
        </span>
      </p>
    </div>
  );
}


/** What is known about a water body, and what is not.
 *
 *  Written so the absences read as findings rather than as a panel that
 *  failed to load: "no real-time data" is the answer for 2,714 of India's
 *  2,740 monitored water bodies, and the reader should see that plainly.
 */
export function DataAvailabilityPanel({
  availability,
}: {
  availability: DataAvailability | undefined;
}) {
  if (!availability) return null;
  const rows: { label: string; yes: boolean; detail: string }[] = [
    {
      label: "Real-time data",
      yes: availability.real_time,
      detail: availability.real_time_detail,
    },
    {
      label: "Historical data",
      yes: availability.historical,
      detail: availability.historical_detail,
    },
    {
      label: "Mapped shape",
      yes: availability.geometry,
      detail: availability.geometry
        ? "Matched to an OpenStreetMap feature"
        : "No shape matched; the water body is shown as a point",
    },
    {
      label: "Satellite evidence",
      yes: availability.satellite_evidence,
      detail: availability.satellite_evidence
        ? "At least one scene passed the cloud and water checks"
        : "No cloud-free scene has been accepted for this water body",
    },
    {
      label: "Official classification",
      yes: availability.official_classification,
      detail: availability.official_classification
        ? "An official assessment is recorded"
        : "No official classification has been imported",
    },
  ];
  return (
    <ul className="availability-list">
      {rows.map((row) => (
        <li key={row.label} className={row.yes ? "is-yes" : "is-no"}>
          <span className="availability-mark" aria-hidden>
            {row.yes ? <Check size={14} /> : <Minus size={14} />}
          </span>
          <span className="availability-label">{row.label}</span>
          <span className="availability-answer">{row.yes ? "Yes" : "No"}</span>
          <span className="availability-detail">{row.detail}</span>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/* Evidence                                                            */
/* ------------------------------------------------------------------ */

const EVIDENCE_META: Record<
  WaterEvidenceType,
  { label: string; tone: string; hint: string }
> = {
  MEASURED: {
    label: "Measured",
    tone: "measured",
    hint: "Laboratory or field instrument measurement of the named quantity.",
  },
  REFERENCE_COMPARISON: {
    label: "Reference comparison",
    tone: "inferred",
    hint: "A measured value compared with a published standard, which is named.",
  },
  SOURCE_CLASSIFICATION: {
    label: "Official classification",
    tone: "reported",
    hint: "A classification published by an official source, shown as published.",
  },
  DERIVED_STATUS: {
    label: "Derived status",
    tone: "inferred",
    hint: "A band derived by fixed rules from the measurements and reference, with every input listed.",
  },
  SATELLITE_OBSERVED: {
    label: "Satellite-derived",
    tone: "satellite",
    hint: "Derived from satellite reflectance. A proxy, not a laboratory value.",
  },
  IMAGE_DETECTED: {
    label: "Image-detected",
    tone: "detected",
    hint: "Output of a detector run on an image. Describes appearance only.",
  },
  REPORTED: {
    label: "Reported",
    tone: "reported",
    hint: "Asserted by a document or bulletin; not independently verified.",
  },
  INFERRED: {
    label: "Inferred",
    tone: "inferred",
    hint: "Derived by reasoning over other evidence. The weakest claim.",
  },
  FORECAST: {
    label: "Forecast",
    tone: "forecast",
    hint: "A projection about the future.",
  },
  RETRIEVED: {
    label: "Retrieved",
    tone: "retrieved",
    hint: "A passage retrieved from the document corpus, quoted as found.",
  },
};

export function WaterEvidenceBadge({ type }: { type: WaterEvidenceType }) {
  const meta = EVIDENCE_META[type] ?? EVIDENCE_META.INFERRED;
  return (
    <span className={`wevidence wevidence-${meta.tone}`} title={meta.hint}>
      {meta.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Water body type                                                     */
/* ------------------------------------------------------------------ */

export const TYPE_META: Record<WaterBodyType, { label: string; icon: string }> = {
  river: { label: "River", icon: "〜" },
  river_stretch: { label: "River stretch", icon: "〜" },
  lake: { label: "Lake", icon: "◎" },
  pond: { label: "Pond / tank", icon: "○" },
  reservoir: { label: "Reservoir", icon: "▣" },
  canal: { label: "Canal", icon: "═" },
  creek: { label: "Creek", icon: "≈" },
  estuary: { label: "Estuary", icon: "⊃" },
  coastal: { label: "Coastal", icon: "⌇" },
  marine: { label: "Marine", icon: "⌇" },
  groundwater: { label: "Groundwater", icon: "⊥" },
  drain: { label: "Drain", icon: "┈" },
  other: { label: "Unclassified", icon: "?" },
};

export function WaterTypeTag({ type }: { type: WaterBodyType }) {
  const meta = TYPE_META[type] ?? TYPE_META.other;
  return (
    <span className={`wtype wtype-${type}`}>
      <span aria-hidden className="wtype-glyph">
        {meta.icon}
      </span>
      {meta.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Parameters                                                          */
/* ------------------------------------------------------------------ */

/**
 * One measured parameter.
 *
 * A parameter the applied standard does not cover shows "sets no limit"
 * rather than a tick: rendering an ungoverned value as compliant would be an
 * invention.
 */
export function ParameterCard({ reading }: { reading: WaterParameterReading }) {
  const c = reading.comparison;
  const tone =
    c.compliance === "exceeds" || c.compliance === "below"
      ? "bad"
      : c.compliance === "within"
        ? "ok"
        : "unknown";

  return (
    <div className={`param-card param-${tone}`}>
      <div className="param-head">
        <span className="param-label">{reading.label}</span>
        <WaterEvidenceBadge type={reading.evidence_type} />
      </div>

      <div className="param-value">
        {reading.value !== null ? (
          <>
            <strong>{formatNumber(reading.value)}</strong>
            {reading.unit && <span className="param-unit">{reading.unit}</span>}
          </>
        ) : reading.qualitative_value ? (
          <strong>{reading.qualitative_value}</strong>
        ) : (
          <span className="param-missing">Not measured</span>
        )}
        {reading.higher_is_worse === false && (
          <span className="param-direction" title="Lower values are worse for this parameter">
            <TrendingDown size={12} aria-hidden /> lower is worse
          </span>
        )}
      </div>

      <ComplianceLine comparison={c} />

      <div className="param-foot">
        <CalendarClock size={11} aria-hidden />
        {formatDay(reading.observed_at)}
        {reading.station && <span className="param-station"> · {reading.station}</span>}
      </div>
    </div>
  );
}

function standardShort(c: ComparisonResult): string {
  return c.standard_name ?? "the reference";
}

export function ComplianceLine({ comparison }: { comparison: ComparisonResult }) {
  if (comparison.compliance === "no_reference") {
    return (
      <p className="param-compliance param-compliance-unknown">
        <Minus size={11} aria-hidden /> Shown as measured; no applicable reference
      </p>
    );
  }
  if (comparison.compliance === "no_standard") {
    return (
      <p className="param-compliance param-compliance-unknown">
        <Minus size={11} aria-hidden /> {standardShort(comparison)} sets no limit
      </p>
    );
  }
  if (comparison.compliance === "not_measured") {
    return (
      <p className="param-compliance param-compliance-unknown">
        <CircleHelp size={11} aria-hidden /> Not measured
      </p>
    );
  }
  if (comparison.failed) {
    return (
      <p className="param-compliance param-compliance-bad">
        <TrendingUp size={11} aria-hidden />
        {comparison.compliance === "exceeds"
          ? `Above the limit of ${comparison.limit_max} (${standardShort(comparison)})`
          : `Below the minimum of ${comparison.limit_min} (${standardShort(comparison)})`}
        {comparison.exceedance_factor && comparison.exceedance_factor >= 1.5
          ? ` (${comparison.exceedance_factor.toFixed(1)}×)`
          : ""}
      </p>
    );
  }
  return (
    <p className="param-compliance param-compliance-ok">
      <ShieldCheck size={11} aria-hidden /> Within the limit ({standardShort(comparison)})
      {comparison.above_desirable && comparison.desirable != null && (
        <span className="param-desirable"> · above the desirable level of {comparison.desirable}</span>
      )}
    </p>
  );
}

/* ------------------------------------------------------------------ */
/* Explanation                                                         */
/* ------------------------------------------------------------------ */

/** "Why this status?" — rendered from the engine's own reasons. */
export function StatusExplanation({ detail }: { detail: StatusDetail }) {
  return (
    <div className="status-why">
      <ul className="status-reasons">
        {detail.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>

      {detail.failing_parameters.length > 0 && (
        <div className="status-standards">
          <h4>Limits applied</h4>
          <ul>
            {detail.failing_parameters.map((c) => (
              <li key={c.parameter}>
                <strong>{c.label}</strong> — {c.explanation}{" "}
                {c.standard_url && (
                  <a href={c.standard_url} target="_blank" rel="noreferrer noopener">
                    {c.standard_source}
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.missing_parameters.length > 0 && (
        <p className="status-missing">
          <Info size={12} aria-hidden /> Not evaluated because they were not
          measured: {detail.missing_parameters.join(", ")}.
        </p>
      )}

      {(detail.limitations ?? []).length > 0 && (
        <ul className="status-limitations">
          {(detail.limitations ?? []).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}

      <p className="status-engine">
        Determined by {detail.engine_version}
        {detail.reference?.standard_name
          ? ` against ${detail.reference.standard_name} (${detail.reference.basis_label.toLowerCase()}).`
          : " with no applicable reference standard."}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Freshness                                                           */
/* ------------------------------------------------------------------ */

export function FreshnessNote({ detail }: { detail: StatusDetail }) {
  const f = detail.freshness;
  const tone = f.describes_present_state ? "ok" : "stale";
  return (
    <div className={`freshness freshness-${tone}`}>
      <CalendarClock size={14} aria-hidden />
      <div>
        <p className="freshness-summary">{f.summary}</p>
        <p className="freshness-meta">
          Source cadence: {f.expected_cadence_label}
          {f.age_days !== null && <> · Observation age: {Math.round(f.age_days)} days</>}
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Small helpers                                                       */
/* ------------------------------------------------------------------ */

export function MatchConfidenceNote({
  confidence,
  method,
}: {
  confidence: number;
  method: string;
}) {
  if (method === "source_field") return null;
  const wording =
    method === "type_propagated"
      ? "Type inferred from other stations on the same named water body."
      : method === "unclassified"
        ? "The source does not state what kind of water body this is."
        : method === "source_sub_basin"
          ? "The source names a basin and a sub-basin for these stations, not the watercourse. This is the sub-basin, which can be coarser than the stream actually sampled."
          : "Name parsed from the monitoring station label.";
  return (
    <p className="match-note">
      <Info size={12} aria-hidden /> {wording} Identification confidence{" "}
      {(confidence * 100).toFixed(0)}%.
    </p>
  );
}

export function WaterIcon({ type }: { type: WaterBodyType }) {
  if (type === "groundwater") return <Droplets size={14} aria-hidden />;
  if (type === "coastal" || type === "marine") return <Waves size={14} aria-hidden />;
  if (type === "lake" || type === "pond" || type === "reservoir")
    return <MapPin size={14} aria-hidden />;
  return <FlaskConical size={14} aria-hidden />;
}

export function StatCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className={`wstat wstat-${tone}`}>
      <span className="wstat-label">{label}</span>
      <span className="wstat-value">{value}</span>
      {hint && <span className="wstat-hint">{hint}</span>}
    </div>
  );
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "date unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "date unknown";
  // UTC, because that is how observations are stored and how every sentence
  // the backend writes about them is dated. Rendering in the reader's zone
  // made one page show the same reading as "Sep 27" and "26 Sep".
  return date.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 10000) return value.toLocaleString();
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(Math.abs(value) < 1 ? 3 : 2);
}
