/**
 * Entry page.
 *
 * Sets the product's claim honestly: this is a monitoring platform that
 * separates what it measured from what it inferred. The evidence ladder is
 * shown on the landing page because it is the differentiator, not a footnote.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Bot,
  Radar,
  Search,
  ShieldCheck,
  TrendingUp,
  Waves,
} from "lucide-react";
import { api } from "@/lib/api";
import { EvidenceBadge, StatusBadge } from "@/components/ui";

const CAPABILITIES = [
  {
    icon: Radar,
    title: "Satellite detection",
    body: "Sentinel-1 C-band SAR screening for dark formations, refined at finer scale where a slick-plausible claim becomes defensible.",
  },
  {
    icon: TrendingUp,
    title: "Temporal forecasting",
    body: "Detection-activity forecasts with 80% prediction intervals, backtested against a naive baseline and reported honestly when they lose.",
  },
  {
    icon: ShieldCheck,
    title: "Deterministic risk",
    body: "A six-factor risk score computed arithmetically. Contributions sum to the score, and unevaluated factors are declared, never zero-filled.",
  },
  {
    icon: Search,
    title: "Grounded research",
    body: "Retrieval over real marine-pollution instruments. When the corpus has no answer, the assistant declines rather than inventing one.",
  },
  {
    icon: Bot,
    title: "Agent analysis",
    body: "A five-stage workflow — detection, context, research, risk, report — that terminates in a bounded number of tool calls.",
  },
  {
    icon: Waves,
    title: "Evidence provenance",
    body: "Every value carries how it came to exist. Observed, detected, inferred, forecast and retrieved are never blurred together.",
  },
];

export default function Landing() {
  const { data: health, isError } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: 1,
  });

  return (
    <div className="landing">
      <div className="landing-bg" aria-hidden="true">
        <svg viewBox="0 0 1440 420" preserveAspectRatio="none">
          <defs>
            <linearGradient id="lg1" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.16" />
              <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="lg2" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.30" />
              <stop offset="100%" stopColor="#0369a1" stopOpacity="0.16" />
            </linearGradient>
          </defs>
          <path
            d="M0 220 C 240 160, 400 280, 720 230 S 1200 150, 1440 210 L1440 420 L0 420 Z"
            fill="url(#lg1)"
          />
          <path
            d="M0 280 C 260 230, 460 330, 780 285 S 1220 220, 1440 270"
            fill="none"
            stroke="url(#lg2)"
            strokeWidth="1.6"
          />
          <path
            d="M0 320 C 300 275, 500 365, 820 322 S 1240 265, 1440 310"
            fill="none"
            stroke="url(#lg2)"
            strokeWidth="1.1"
            opacity="0.7"
          />
        </svg>
      </div>

      <header className="landing-nav">
        <div className="brand">
          <span className="brand-mark">
            <Waves size={17} strokeWidth={2.4} />
          </span>
          <span className="brand-text">
            <strong>OceanAI</strong>
            <em>Ocean Intelligence</em>
          </span>
        </div>
        <div className="landing-nav-right">
          {isError ? (
            <StatusBadge tone="error" label="API unreachable" />
          ) : health ? (
            <StatusBadge tone="ok" label="System operational" pulse />
          ) : null}
          <Link className="btn btn-ghost" to="/app/research">
            Explore Research
          </Link>
          <Link className="btn btn-primary" to="/app/overview">
            Open Command Center <ArrowRight size={14} />
          </Link>
        </div>
      </header>

      <section className="hero">
        <p className="hero-eyebrow">Environmental Intelligence Platform</p>
        <h1>
          Ocean monitoring that says
          <br />
          <span className="hero-accent">what it actually knows.</span>
        </h1>
        <p className="hero-lede">
          OceanAI ingests Sentinel-1 satellite observations, screens them for
          pollution signatures, scores environmental risk deterministically and
          forecasts regional activity — while keeping measurement, detection,
          inference and forecast strictly apart.
        </p>

        <div className="hero-cta">
          <Link className="btn btn-primary btn-lg" to="/app/overview">
            Open Command Center <ArrowRight size={15} />
          </Link>
          <Link className="btn btn-outline btn-lg" to="/app/map">
            View Ocean Map
          </Link>
        </div>

        <div className="hero-ladder">
          <span className="ladder-label">Every value carries its provenance</span>
          <div className="ladder-badges">
            <EvidenceBadge level="OBSERVED" />
            <EvidenceBadge level="DETECTED" />
            <EvidenceBadge level="INFERRED" />
            <EvidenceBadge level="FORECAST" />
            <EvidenceBadge level="RETRIEVED" />
          </div>
        </div>
      </section>

      <section className="landing-grid">
        {CAPABILITIES.map((capability) => (
          <article className="landing-card" key={capability.title}>
            <span className="landing-card-icon">
              <capability.icon size={17} strokeWidth={2} />
            </span>
            <h3>{capability.title}</h3>
            <p>{capability.body}</p>
          </article>
        ))}
      </section>

      <footer className="landing-foot">
        <span>
          OceanAI — Ocean Intelligence Platform
          {health?.version ? ` · v${health.version}` : ""}
          {health?.demo_mode ? " · demo mode" : ""}
        </span>
        <a href="/docs" className="landing-link">
          API documentation
        </a>
      </footer>
    </div>
  );
}
