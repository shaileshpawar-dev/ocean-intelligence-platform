/**
 * Types mirroring the OceanAI backend's real response schemas.
 *
 * Every shape here was read off the live API (`/openapi.json` and actual
 * responses), not invented. Fields the backend can legitimately return as
 * null are typed `| null` rather than optional, because "not measured" is a
 * meaningful value in this system and the UI must render it as such.
 */

/** How a value came to exist. The platform's core provenance vocabulary. */
export type EvidenceLevel =
  | "OBSERVED"
  | "DETECTED"
  | "INFERRED"
  | "FORECAST"
  | "SIMULATED";

/** Ordinal risk band derived from the deterministic engine. */
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/** What the sensing modality can actually support as a claim. */
export type PollutionSignature =
  | "oil_like_signature"
  | "dark_formation"
  | "algae_bloom_signature"
  | "plastic_debris_signature"
  | "surface_anomaly"
  | "no_anomaly";

/* -------------------------------------------------------------------------
   Envelope
   ------------------------------------------------------------------------- */

export interface DataProvenance {
  source: string;
  contains_simulated_data: boolean;
  evidence_levels: string[];
  generated_at: string;
  notes: string[];
}

export interface ListResponse<T> {
  count: number;
  items: T[];
  provenance: DataProvenance;
}

/* -------------------------------------------------------------------------
   System
   ------------------------------------------------------------------------- */

export interface HealthComponent {
  name: string;
  available: boolean;
  detail: string | null;
}

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  environment: string;
  demo_mode: boolean;
  components: HealthComponent[];
  checked_at: string;
}

export interface Overview {
  total_events: number;
  critical_events: number;
  high_events: number;
  slick_scale_area_km2: number;
  dark_water_extent_km2: number;
  observations: number;
  simulated_events: number;
  contains_simulated_data: boolean;
  notes: string[];
}

/* -------------------------------------------------------------------------
   Pollution
   ------------------------------------------------------------------------- */

export interface PollutionEvent {
  event_id: string;
  region_code: string | null;
  region_name: string | null;
  parent_region: string | null;
  signature: PollutionSignature | string;
  detection_method: string;
  evidence_level: EvidenceLevel | string;
  confidence: number;
  /** False means confidence is a ranking score, not a probability. */
  confidence_is_calibrated: boolean;
  latitude: number;
  longitude: number;
  bbox: number[] | null;
  estimated_area_km2: number | null;
  area_method: string | null;
  risk_score: number | null;
  severity: Severity | null;
  detected_at: string;
  model_version: string | null;
  caveats: string[];
  is_simulated: boolean;
}

export interface RiskContribution {
  factor: string;
  points: number;
  max_points: number;
  detail: string;
  evidence_level: string;
}

export interface RiskAssessment {
  assessment_id: string;
  score: number;
  severity: Severity;
  engine_version: string;
  contributions: RiskContribution[];
  /** Non-empty means the score is a PARTIAL assessment, not a low one. */
  missing_factors: string[];
  narrative: string | null;
  evidence_level: string;
}

export interface Observation {
  observation_id: string;
  collection: string;
  platform: string;
  scene_id: string | null;
  acquired_at: string;
  polarisation: string | null;
  orbit_pass: string | null;
  scale_m: number | null;
  mean_db: number | null;
  p10_db: number | null;
  p90_db: number | null;
  stddev_db: number | null;
  evidence_level: string;
}

export interface GeographicContext {
  distance_to_coast_km: number | null;
  nearest_protected_area: string | null;
  distance_to_protected_area_km: number | null;
}

export interface PollutionEventDetail extends PollutionEvent {
  risk_assessment: RiskAssessment | null;
  observation: Observation | null;
  geographic_context: GeographicContext | null;
}

export interface Zone {
  region_code: string;
  region_name: string;
  parent_region: string | null;
  latitude: number;
  longitude: number;
  bbox: number[];
  last_observed_at: string;
  mean_backscatter_db: number | null;
  platform: string;
  observation_evidence_level: string;
  /** Null means the cell was observed and nothing was detected. */
  signature: string | null;
  confidence: number | null;
  risk_score: number | null;
  severity: Severity | null;
  event_id: string | null;
  is_simulated: boolean;
}

export interface Alert {
  event_id: string;
  severity: Severity;
  risk_score: number | null;
  signature: string;
  region_name: string;
  parent_region: string | null;
  confidence: number;
  detected_at: string;
  message: string;
  is_simulated: boolean;
  caveats: string[];
}

/* -------------------------------------------------------------------------
   Temporal
   ------------------------------------------------------------------------- */

export interface TrendPoint {
  date: string;
  event_count: number;
  mean_risk: number | null;
  max_risk: number | null;
  mean_confidence: number | null;
  total_area_km2: number | null;
  mean_backscatter_db: number | null;
  evidence_level: string;
}

export interface RegionTrend {
  region_code: string;
  region_name: string;
  parent_region: string | null;
  series: TrendPoint[];
  latest_risk: number | null;
  change: number | null;
  slope_per_day: number | null;
  coverage_days: number;
  window_days: number;
  /** Low ratio means satellite revisit gaps, not calm water. */
  coverage_ratio: number;
  contains_simulated_data: boolean;
}

export interface ForecastPoint {
  target_date: string;
  horizon_days: number;
  value: number;
  lower: number;
  upper: number;
  interval_confidence: number;
}

export interface ForecastBand {
  date: string;
  horizon_days: number;
  risk: number;
  severity: Severity;
  lower: number;
  upper: number;
  severity_lower: Severity;
  severity_upper: Severity;
  interval_confidence: number;
}

export interface Forecast {
  region_code: string;
  model_name: string;
  /** Always "detection_activity". Never physical dispersion. */
  forecast_kind: string;
  status: "ok" | "insufficient_data" | "not_supported" | string;
  points: ForecastPoint[];
  bands: ForecastBand[];
  n_observations: number;
  backtest_mae: number | null;
  naive_mae: number | null;
  /** False means the model did not beat last-value-carried-forward. */
  beats_naive: boolean | null;
  message: string;
  caveats: string[];
}

/* -------------------------------------------------------------------------
   ML
   ------------------------------------------------------------------------- */

export interface ModelVersion {
  name: string;
  version: string;
  task: string;
  framework: string | null;
  status: string;
  is_deployed: boolean;
  dataset_version: string | null;
  trained_at: string | null;
  /** Null means NOT EVALUATED. Never render as zero. */
  map50: number | null;
  map50_95: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  iou: number | null;
  mean_latency_ms: number | null;
  class_names: string[] | null;
  metrics_source: string | null;
  notes: string | null;
}

export interface DetectorInfo {
  name: string;
  version: string;
  method: string;
  available: boolean;
  supported_signatures: string[];
  class_names: Record<string, string> | null;
  checkpoint: string | null;
}

export interface LatencySummary {
  n: number;
  mean_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  detail?: string;
}

export interface Metrics {
  window_days: number;
  latency: LatencySummary;
  volume: {
    total_requests: number;
    failed_requests: number;
    success_rate: number | null;
    class_distribution: Record<string, number>;
  };
}

export interface DriftCheck {
  metric: string;
  status: "ok" | "warning" | "drift_detected" | "insufficient_data" | string;
  psi: number | null;
  baseline_n: number;
  current_n: number;
  message: string;
  detail: Record<string, unknown>;
}

export interface DriftReport {
  overall_status: string;
  baseline_window_days: number;
  current_window_days: number;
  min_samples_required: number;
  thresholds: { warning: number; drift: number };
  checks: DriftCheck[];
  action: string;
}

/* -------------------------------------------------------------------------
   Intelligence
   ------------------------------------------------------------------------- */

export interface ResearchSource {
  position: number;
  document_id: string;
  title: string;
  doc_type: string;
  publication: string | null;
  year: number | null;
  source_url: string | null;
  relevance: number;
  matched_terms: string[];
  excerpt: string;
  notice: string;
}

export interface ResearchAnswer {
  question: string;
  /** no_evidence means the assistant declined. Never render a fabricated answer. */
  status: "grounded" | "retrieval_only" | "no_evidence" | string;
  answer: string;
  sources: ResearchSource[];
  source_count: number;
  llm_provider: string;
  llm_model: string | null;
  notes: string[];
}

export interface CorpusStats {
  documents: number;
  chunks: number;
  by_type: Record<string, number>;
  retriever: string;
  reranker: string;
  notes: string[];
}

export interface AgentFinding {
  agent: string;
  ok: boolean;
  summary: string;
  data: Record<string, unknown>;
  evidence_level: string;
  concerns: string[];
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  duration_ms: number;
  success: boolean;
  summary: string;
  error: string | null;
  agent?: string;
}

export interface AgentRunResult {
  workflow_id: string;
  workflow_name: string;
  event_id: string;
  status: string;
  duration_ms: number;
  llm_provider: string;
  findings: AgentFinding[];
  tool_calls: ToolCall[];
  report: {
    sections: Record<string, Record<string, unknown>>;
    recommendations: string[];
    limitations: string[];
    narrative: string;
    narrative_provider: string;
  } | null;
  report_id?: string;
}

export interface AgentStage {
  name: string;
  purpose: string;
}

export interface AgentCatalogue {
  workflow: string;
  control_flow: string;
  stages: AgentStage[];
  notes: string[];
  tools: { name: string; description: string }[];
  llm: { provider: string; available: boolean; model?: string; detail?: string };
}

export interface AgentRunSummary {
  workflow_id: string;
  workflow_name: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  llm_provider: string | null;
  tool_calls: number;
  error: string | null;
}

export interface ReportSummary {
  report_id: string;
  title: string;
  workflow_id: string | null;
  created_at: string;
  contains_simulated_data: boolean;
  source_count: number;
}

export interface ReportDetail {
  report_id: string;
  title: string;
  summary: string | null;
  sections: Record<string, Record<string, unknown>>;
  provenance: Record<string, string> | null;
  sources: Record<string, unknown>[] | null;
  generated_by: string;
  workflow_id: string | null;
  created_at: string;
  contains_simulated_data: boolean;
}
