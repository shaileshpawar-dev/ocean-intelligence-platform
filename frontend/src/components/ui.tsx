/**
 * Shared UI primitives.
 *
 * The evidence and honesty components here are not decoration: they are how
 * the platform's central distinction (observed vs detected vs inferred vs
 * forecast vs retrieved) reaches the screen. `Unavailable` and `NotEvaluated`
 * exist so a missing value has a designed appearance and can never be
 * silently rendered as a zero.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Droplets,
  Info,
  Inbox,
  Layers,
  Leaf,
  Moon,
  Package,
  RefreshCw,
  ServerCrash,
  Waves as WavesIcon,
} from "lucide-react";
import type { EvidenceLevel, Severity } from "@/lib/types";

/* -------------------------------------------------------------------------
   Evidence
   ------------------------------------------------------------------------- */

/** What each detection signature is, in one line, with its own colour.
 *
 *  The wording matters as much as the colour. A signature names *what was
 *  seen by a given instrument*, not what caused it: FDI responds to anything
 *  floating and cannot identify plastic, NDTI responds to sediment that is
 *  usually a river doing its job, and a SAR dark formation is a flat patch
 *  whose cause is undetermined. Each label here is written to survive being
 *  read on its own, because on a crowded page that is how it will be read.
 */
export const SIGNATURE_META: Record<
  string,
  { label: string; hint: string; colour: string; Icon: typeof AlertTriangle }
> = {
  oil_like_signature: {
    label: "Oil-like",
    hint: "Dark formation whose shape and contrast are consistent with a surface film. Not a confirmed spill.",
    colour: "var(--sig-oil, #B91C1C)",
    Icon: Droplets,
  },
  dark_formation: {
    label: "Dark formation",
    hint: "Low-backscatter patch in radar, cause undetermined. Calm water and rain cells look the same.",
    colour: "var(--sig-dark, #6B21A8)",
    Icon: Moon,
  },
  algae_bloom_signature: {
    label: "Algal bloom",
    hint: "Elevated chlorophyll-a in Sentinel-2 (NDCI). Productive water, which may be a bloom, upwelling or a nutrient plume.",
    colour: "var(--sig-algae, #15803D)",
    Icon: Leaf,
  },
  floating_material: {
    label: "Floating material",
    hint: "Near-infrared brighter than the surrounding water (FDI). Says something is floating; does not identify it, and is not evidence of plastic.",
    colour: "var(--sig-floating, #C2410C)",
    Icon: Package,
  },
  turbidity_plume: {
    label: "Turbidity plume",
    hint: "Elevated suspended sediment (NDTI). Frequently natural on this coast — river discharge and runoff raise it.",
    colour: "var(--sig-turbidity, #A16207)",
    Icon: WavesIcon,
  },
  plastic_debris_signature: {
    label: "Floating material (legacy)",
    hint: "A deprecated label kept only for stored rows. The index behind it cannot identify plastic; new detections use Floating material.",
    colour: "var(--sig-floating, #C2410C)",
    Icon: Package,
  },
  surface_anomaly: {
    label: "Surface anomaly",
    hint: "Anomalous but unclassifiable under the available instrument.",
    colour: "var(--sig-anomaly, #0E7490)",
    Icon: Layers,
  },
  no_anomaly: {
    label: "No anomaly",
    hint: "Measured and found unremarkable. An explicit negative is data too.",
    colour: "var(--sig-none, #64748B)",
    Icon: Info,
  },
};

export function signatureMeta(signature: string) {
  return (
    SIGNATURE_META[signature] ?? {
      label: signature.replace(/_/g, " "),
      hint: "",
      colour: "var(--sig-none, #64748B)",
      Icon: Layers,
    }
  );
}

/** A detection signature, with its colour and icon. */
export function SignatureBadge({
  signature,
  showHint = false,
}: {
  signature: string;
  showHint?: boolean;
}) {
  const meta = signatureMeta(signature);
  const { Icon } = meta;
  return (
    <span className="signature-badge" style={{ color: meta.colour }} title={meta.hint}>
      <Icon size={13} aria-hidden />
      <span>{meta.label}</span>
      {showHint && meta.hint && <em className="signature-hint">{meta.hint}</em>}
    </span>
  );
}

/** Legend for whichever signatures are actually present in a view. */
export function SignatureLegend({ signatures }: { signatures: string[] }) {
  const seen = [...new Set(signatures)].filter((s) => s in SIGNATURE_META);
  if (seen.length === 0) return null;
  return (
    <div className="signature-legend">
      {seen.map((signature) => {
        const meta = signatureMeta(signature);
        const { Icon } = meta;
        return (
          <span key={signature} className="signature-legend-item">
            <Icon size={13} aria-hidden style={{ color: meta.colour }} />
            <strong style={{ color: meta.colour }}>{meta.label}</strong>
            <span>{meta.hint}</span>
          </span>
        );
      })}
    </div>
  );
}

const EVIDENCE_META: Record<
  string,
  { label: string; hint: string; fg: string; bg: string; border: string }
> = {
  OBSERVED: {
    label: "OBSERVED",
    hint: "Directly measured from sensor data",
    fg: "var(--ev-observed)",
    bg: "var(--ev-observed-bg)",
    border: "var(--ev-observed-border)",
  },
  DETECTED: {
    label: "DETECTED",
    hint: "Detector output, carries uncertainty",
    fg: "var(--ev-detected)",
    bg: "var(--ev-detected-bg)",
    border: "var(--ev-detected-border)",
  },
  INFERRED: {
    label: "INFERRED",
    hint: "Derived by reasoning over detections and context",
    fg: "var(--ev-inferred)",
    bg: "var(--ev-inferred-bg)",
    border: "var(--ev-inferred-border)",
  },
  FORECAST: {
    label: "FORECAST",
    hint: "A projection about the future, not an observation",
    fg: "var(--ev-forecast)",
    bg: "var(--ev-forecast-bg)",
    border: "var(--ev-forecast-border)",
  },
  RETRIEVED: {
    label: "RETRIEVED",
    hint: "Text retrieved from the verified corpus",
    fg: "var(--ev-retrieved)",
    bg: "var(--ev-retrieved-bg)",
    border: "var(--ev-retrieved-border)",
  },
  SIMULATED: {
    label: "SIMULATED",
    hint: "Synthetic demo data — describes no real acquisition",
    fg: "var(--ev-simulated)",
    bg: "var(--ev-simulated-bg)",
    border: "var(--ev-simulated-border)",
  },
};

export function EvidenceBadge({
  level,
  detail,
  size = "sm",
}: {
  level: EvidenceLevel | string;
  detail?: string;
  size?: "sm" | "md";
}) {
  const meta = EVIDENCE_META[String(level).toUpperCase()] ?? {
    label: String(level).toUpperCase(),
    hint: "",
    fg: "var(--neutral)",
    bg: "var(--neutral-bg)",
    border: "var(--neutral-border)",
  };
  return (
    <span
      className={`ev-badge ev-${size}`}
      title={detail ? `${meta.hint} — ${detail}` : meta.hint}
      style={{ color: meta.fg, background: meta.bg, borderColor: meta.border }}
    >
      <span className="ev-dot" style={{ background: meta.fg }} />
      {meta.label}
      {detail && <span className="ev-detail">{detail}</span>}
    </span>
  );
}

/** The five-level key, shown once per page where provenance matters. */
export function EvidenceLegend() {
  return (
    <div className="ev-legend" role="list" aria-label="Evidence levels">
      {(["OBSERVED", "DETECTED", "INFERRED", "FORECAST", "RETRIEVED"] as const).map(
        (level) => (
          <div className="ev-legend-item" role="listitem" key={level}>
            <EvidenceBadge level={level} />
            <span>{EVIDENCE_META[level].hint}</span>
          </div>
        ),
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Severity and status
   ------------------------------------------------------------------------- */

const SEVERITY_COLOR: Record<Severity, { fg: string; bg: string }> = {
  LOW: { fg: "var(--sev-low)", bg: "var(--sev-low-bg)" },
  MEDIUM: { fg: "var(--sev-medium)", bg: "var(--sev-medium-bg)" },
  HIGH: { fg: "var(--sev-high)", bg: "var(--sev-high-bg)" },
  CRITICAL: { fg: "var(--sev-critical)", bg: "var(--sev-critical-bg)" },
};

export function severityColor(severity: Severity | null | undefined): string {
  return severity ? SEVERITY_COLOR[severity].fg : "var(--neutral)";
}

export function RiskBadge({
  severity,
  score,
}: {
  severity: Severity | null;
  score?: number | null;
}) {
  if (!severity) return <Unavailable />;
  const { fg, bg } = SEVERITY_COLOR[severity];
  return (
    <span className="risk-badge" style={{ color: fg, background: bg, borderColor: fg }}>
      {severity}
      {score !== null && score !== undefined && (
        <strong>{score.toFixed(1)}</strong>
      )}
    </span>
  );
}

export type StatusTone = "ok" | "warn" | "error" | "neutral" | "info";

export function StatusBadge({
  tone,
  label,
  pulse = false,
}: {
  tone: StatusTone;
  label: string;
  pulse?: boolean;
}) {
  return (
    <span className={`status-badge tone-${tone}`}>
      <span className={`status-dot${pulse ? " pulse" : ""}`} />
      {label}
    </span>
  );
}

/* -------------------------------------------------------------------------
   Honest absence
   ------------------------------------------------------------------------- */

/** A value the backend did not provide. Never render 0 in its place. */
export function Unavailable({ reason }: { reason?: string }) {
  return (
    <span className="unavailable" title={reason ?? "No value returned by the API"}>
      Unavailable
    </span>
  );
}

/** A metric that exists but has never been measured. */
export function NotEvaluated({ hint }: { hint?: string }) {
  return (
    <span
      className="not-evaluated"
      title={
        hint ??
        "This metric has not been measured. It is reported as null rather than filled with a plausible number."
      }
    >
      Not evaluated
    </span>
  );
}

/** Render a nullable number, or the honest absence marker. */
export function Value({
  value,
  suffix = "",
  digits = 2,
  fallback = "unavailable",
}: {
  value: number | null | undefined;
  suffix?: string;
  digits?: number;
  fallback?: "unavailable" | "not-evaluated" | "dash";
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    if (fallback === "not-evaluated") return <NotEvaluated />;
    if (fallback === "dash") return <span className="text-muted">—</span>;
    return <Unavailable />;
  }
  return (
    <>
      {value.toLocaleString(undefined, { maximumFractionDigits: digits })}
      {suffix && <span className="unit">{suffix}</span>}
    </>
  );
}

/* -------------------------------------------------------------------------
   Layout blocks
   ------------------------------------------------------------------------- */

export function PageHeader({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-header-row">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="page-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

export function SectionCard({
  title,
  description,
  actions,
  children,
  padded = true,
  className = "",
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  padded?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {description && <p className="card-desc">{description}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      <div className={padded ? "card-body" : ""}>{children}</div>
    </section>
  );
}

export function MetricCard({
  icon,
  label,
  value,
  detail,
  tone = "neutral",
  evidence,
  footer,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: StatusTone;
  evidence?: EvidenceLevel | string;
  footer?: ReactNode;
}) {
  return (
    <div className={`metric-card tone-${tone}`}>
      <div className="metric-top">
        <span className="metric-icon">{icon}</span>
        <span className="metric-label">{label}</span>
        {evidence && <EvidenceBadge level={evidence} />}
      </div>
      <div className="metric-value">{value}</div>
      {detail && <p className="metric-detail">{detail}</p>}
      {footer && <div className="metric-footer">{footer}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Async states
   ------------------------------------------------------------------------- */

export function LoadingSkeleton({
  rows = 3,
  height = 56,
}: {
  rows?: number;
  height?: number;
}) {
  return (
    <div className="skeleton-stack" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  message,
  icon,
  action,
}: {
  title: string;
  message: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state-block">
      <span className="state-icon neutral">{icon ?? <Inbox size={20} />}</span>
      <h3>{title}</h3>
      <p>{message}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  emptyTitle,
  emptyHint,
}: {
  error: unknown;
  onRetry?: () => void;
  /** Heading to use when the failure is a 404 rather than a fault. */
  emptyTitle?: string;
  /** Explanation to use for a 404. "Not found" and "broken" deserve
   *  different words: one is a normal outcome, the other is a bug. */
  emptyHint?: string;
}) {
  const message =
    error && typeof error === "object" && "friendly" in error
      ? String((error as { friendly: string }).friendly)
      : "Something went wrong loading this data.";
  const insufficient =
    error && typeof error === "object" && "isInsufficientData" in error
      ? Boolean((error as { isInsufficientData: boolean }).isInsufficientData)
      : false;
  const missing =
    error && typeof error === "object" && "isEmpty" in error
      ? Boolean((error as { isEmpty: boolean }).isEmpty)
      : false;

  const notFound = missing && Boolean(emptyTitle);

  return (
    <div className="state-block">
      <span className={`state-icon ${insufficient || notFound ? "warn" : "error"}`}>
        {insufficient || notFound ? <Info size={20} /> : <ServerCrash size={20} />}
      </span>
      <h3>
        {notFound
          ? emptyTitle
          : insufficient
            ? "Insufficient data"
            : "Data unavailable"}
      </h3>
      <p>{notFound ? emptyHint : message}</p>
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  );
}

/** Prominent, unmissable banner for demo-mode data. */
export function SimulatedBanner({ detail }: { detail?: string }) {
  return (
    <div className="sim-banner" role="status">
      <AlertTriangle size={15} />
      <div>
        <strong>Simulated data</strong>
        <span>
          {detail ??
            "Demo mode is active. These records are synthetic, tagged SIMULATED by the API, and describe no real satellite acquisition."}
        </span>
      </div>
    </div>
  );
}

/** Where a measurement's inputs came from, when that is not live traffic.
 *
 *  Deliberately not a SimulatedBanner: the inferences behind a replayed
 *  benchmark are real, and only the window timestamps are assigned. Calling
 *  that "simulated data" would understate the measurement and overstate the
 *  caveat at the same time.
 */
export function ProvenanceNote({ children }: { children: ReactNode }) {
  return (
    <div className="provenance-note" role="note">
      <Info size={15} />
      <span>{children}</span>
    </div>
  );
}

/** What the marine module is, and is not.
 *
 *  The regions are now India's EEZ, matching the rest of the platform, but
 *  the events in them are still synthetic. That distinction is the whole
 *  point of this note: a realistic region name is exactly what would let a
 *  simulated detection pass for a real one, so it is said once per page
 *  rather than left to be inferred. The one page holding measured data --
 *  Candidate Review -- is pointed at rather than lost among the rest.
 */
export function MarineScopeNote({ full = false }: { full?: boolean }) {
  return (
    <div className="provenance-note" role="note">
      <Info size={15} />
      <span>
        {full ? (
          <>
            <strong>Indian EEZ, simulated events.</strong> The marine module
            monitors 15 regions across India's exclusive economic zone — the
            Arabian Sea and Gujarat approaches, the Konkan, Malabar and
            Coromandel coasts, the Gulfs of Kutch, Khambhat and Mannar, the
            Bay of Bengal, the Krishna–Godavari offshore basin, and the
            Andaman &amp; Nicobar and Lakshadweep seas. The regions are real;
            every pollution event in them is <strong>SIMULATED</strong>. The
            real measured data in this module is the 306 Sentinel-1 benchmark
            candidates in{" "}
            <Link to="/app/candidate-review">Candidate Review</Link>.
          </>
        ) : (
          <>
            Indian EEZ regions; events are <strong>SIMULATED</strong>. The
            real data is the 306 Sentinel-1 candidates in{" "}
            <Link to="/app/candidate-review">Candidate Review</Link>.
          </>
        )}
      </span>
    </div>
  );
}

/** A page whose backing capability does not exist in this deployment. */
export function NotAvailableInBackend({
  feature,
  reason,
  alternative,
}: {
  feature: string;
  reason: string;
  alternative?: string;
}) {
  return (
    <div className="state-block tall">
      <span className="state-icon neutral">
        <Info size={20} />
      </span>
      <h3>{feature} — not available</h3>
      <p>{reason}</p>
      {alternative && <p className="state-alt">{alternative}</p>}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Small helpers
   ------------------------------------------------------------------------- */

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`tag tone-${tone}`}>{children}</span>;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A calendar date, with no time of day.
 *
 *  A satellite acquisition date is a date, not an instant: rendering
 *  "2026-11-20" through formatDateTime would invent a midnight the scene was
 *  not taken at, and shift it by a timezone on top. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  // Parsed as UTC noon so a local-timezone offset cannot move the day.
  const date = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function titleise(text: string | null | undefined): string {
  if (!text) return "—";
  return text.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
