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
  /** Where those observations came from. The SAR count is zero now that the
   *  seeded rows are gone; the measured Sentinel-2 readings are their own
   *  table, and counting only the former reported "0 observations" on a
   *  platform holding three thousand. */
  observations_breakdown?: {
    sentinel2_index_readings: number;
    sar_scene_statistics: number;
  };
  flagged_extent_km2?: number;
  flagged_extent_note?: string;
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
  /** The one detector whose output the platform presents. */
  is_active?: boolean;
  /** True for the demonstration stub. */
  is_simulated?: boolean;
}

export interface LatencySummary {
  n: number;
  mean_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
  /** Which models these percentiles cover. One number over two detectors
   *  describes neither, so the card names them. */
  models: string[];
  /** The single model name, or "mixed" when the window holds more than one. */
  model_label: string | null;
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

/** The SAR screener scored against the stored candidates' own ground truth.
 *
 *  Computed live from the database rather than read from a metrics file, so
 *  the threshold can be moved and the matrix recomputed. The scores are
 *  uncalibrated, which `note` states on every response. */
export interface CandidateEvaluation {
  n: number;
  positives: number;
  negatives: number;
  skipped: number;
  threshold: number;
  model: string | string[] | null;
  scores_are_calibrated: boolean;
  confusion: { tp: number; fp: number; tn: number; fn: number };
  precision: number | null;
  recall: number | null;
  f1: number | null;
  fpr: number | null;
  accuracy: number;
  roc: { fpr: number; tpr: number; threshold: number }[];
  auc: number | null;
  positive_subsets: string[];
  negative_subsets: string[];
  note: string;
  detail?: string;
}

/** What a drift window actually holds, read back from the logged rows. */
export interface DriftWindowProvenance {
  n: number;
  /** Rows the confidence PSI could actually use. Lower than `n` when a
   *  window holds rows that logged no confidence. */
  scored_n: number;
  replayed_n: number;
  is_replayed: boolean;
  splits: Record<string, number>;
  dominant_split: string | null;
}

/** One record in the knowledge graph. `evidence_level` is whatever the row
 *  itself declares; null means the record is configuration or process, not a
 *  measurement, and must not borrow a level from its neighbours. */
export interface GraphNode {
  id: string;
  type: string;
  label: string;
  evidence_level: string | null;
  attrs: Record<string, unknown>;
}

/** A link between two records.
 *
 *  `foreign_key` is a declared relationship: a row holds the other row's key.
 *  `resolved_reference` is an identifier read out of a JSON column that does
 *  resolve to a real row, but which nothing in the schema protects — drawn
 *  dashed so the weaker guarantee is visible. Nothing here is inferred. */
export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  edge_kind: "foreign_key" | "resolved_reference" | string;
}

export interface KnowledgeGraphResponse {
  center: string | null;
  center_type: string | null;
  depth: number;
  limit: number;
  truncated: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
  edge_kind_counts: Record<string, number>;
  unresolved_citations: number;
  notes: string[];
}

export interface KnowledgeGraphSummary {
  node_counts: Record<string, number>;
  edge_counts: Record<string, number>;
  total_nodes: number;
  total_edges: number;
  edge_kinds: Record<string, number>;
  unresolved_citations: number;
  node_types: string[];
  max_nodes_per_request: number;
  notes: string[];
}

export interface DriftReport {
  overall_status: string;
  baseline_window_days: number;
  current_window_days: number;
  min_samples_required: number;
  thresholds: { warning: number; drift: number };
  checks: DriftCheck[];
  action: string;
  /** `note` is null when neither window was replayed, so a live deployment
   *  never carries a caveat about a batch it does not contain. */
  provenance: {
    baseline: DriftWindowProvenance;
    current: DriftWindowProvenance;
    note: string | null;
  };
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
  /** Present only when a generated summary passed its number check and was
   *  cached. Null is the normal state: no provider, a provider that failed,
   *  or a summary that was discarded for carrying an unsupported figure. */
  ai_summary: AISummary | null;
}

/** A language model's prose over this report's computed values. */
export interface AISummary {
  label: string;
  text: string;
  model: string | null;
  generated_at: string | null;
  /** How many figures were verified against the evidence before storing. */
  numbers_checked: number | null;
  note: string;
}

/* -------------------------------------------------------------------------
   SAR Candidates & Analyst Review Workflow (Phase 13.2)
   ------------------------------------------------------------------------- */

export type SARCandidateScreeningStatus =
  | "candidate_requires_review"
  | "low_wind_ambiguity_review"
  | "no_candidate_detected";

export type SARCandidateReviewStatus =
  | "awaiting_review"
  | "potential_oil_slick"
  | "rejected_lookalike"
  | "inconclusive"
  | "requires_additional_evidence";

export interface SARCandidate {
  candidate_id: string;
  image_name: string;
  component_id: number | null;
  latitude: number;
  longitude: number;
  is_coastal: boolean;
  acquisition_timestamp: string;
  detector_name: string;
  model_version: string;
  raw_confidence: number;
  confidence_is_calibrated: boolean;
  wind_speed_ms: number | null;
  wind_direction_deg: number | null;
  era5_source: string;
  grid_latitude: number | null;
  grid_longitude: number | null;
  temporal_offset_minutes: number | null;
  grid_distance_km: number | null;
  quality_status: string;
  environmental_warnings: string[];
  screening_status: SARCandidateScreeningStatus | string;
  retained_for_analyst_review: boolean;
  review_status: SARCandidateReviewStatus | string;
  latest_review_decision: string | null;
  latest_reviewed_at: string | null;
  latest_reviewer_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SARCandidateReview {
  review_id: string;
  previous_status: string;
  decision: string;
  reviewer_id: string;
  reviewed_at: string;
  model_version: string;
  notes: string | null;
  evidence_references: Record<string, unknown> | null;
  created_at: string;
}

export interface OpticalScene {
  scene_id: string;
  platform: string;
  acquisition_time: string;
  temporal_delta_hours: number;
  temporal_delta_days: number;
  temporal_window: "primary_3d" | "secondary_10d" | string;
  cloud_cover_pct: number;
  cloud_category: "clean" | "moderate" | "contaminated" | "covered" | string;
  quality_grade: string;
  tile_id: string;
  available_bands: string[];
  has_scl: boolean;
  is_best_match: boolean;
}

export interface SARCandidateOpticalEvidence {
  id: number;
  candidate_id: string;
  scene_id: string;
  platform: string;
  acquisition_timestamp: string;
  temporal_offset_hours: number;
  temporal_window: string;
  scene_cloud_cover_pct: number;
  tile_id?: string | null;
  local_water_fraction: number;
  local_cloud_fraction: number;
  local_shadow_fraction: number;
  local_valid_pixel_fraction: number;
  mean_ndci: number | null;
  p90_ndci: number | null;
  mean_ndti: number | null;
  mean_swir_ratio: number | null;
  optical_quality_flag: string;
  has_rgb_image: boolean;
  has_false_color_image: boolean;
  has_scl_mask: boolean;
  has_ndci_map: boolean;
  processing_status: string;
  created_at: string;
}

export interface SARCandidateDetail extends SARCandidate {
  interpretation: string;
  reviews: SARCandidateReview[];
  optical_evidence: SARCandidateOpticalEvidence[];
}

export interface CandidateReviewCreateIn {
  decision: string;
  reviewer_id?: string;
  notes?: string | null;
  evidence_references?: Record<string, unknown> | null;
}

export interface SARCandidateSummary {
  total_candidates: number;
  total_monitored_samples?: number;
  total_evaluated_samples?: number;
  eligible_candidates?: number;
  standard_review_candidates: number;
  standard_wind_review?: number;
  low_wind_ambiguity_candidates: number;
  low_wind_ambiguity?: number;
  high_wind_ambiguity_candidates?: number;
  high_wind_ambiguity?: number;
  wind_unavailable_candidates?: number;
  wind_unavailable?: number;
  no_candidate_detected: number;
  background_non_detections?: number;
  awaiting_analyst_review: number;
  reviewed_candidates: number;
  decisions: Record<string, number>;
}

export interface CandidateMapPoint {
  candidate_id: string;
  image_name: string;
  latitude: number;
  longitude: number;
  screening_status: string;
  review_status: string;
  raw_confidence: number;
  wind_speed_ms: number | null;
  is_coastal: boolean;
  acquisition_timestamp: string;
  map_state: string;
  color: string;
}

/* -------------------------------------------------------------------------
   Full-Scene Sentinel-1 SAR Processing (Phase 14.2)
   ------------------------------------------------------------------------- */

export interface SARSceneListItem {
  scene_id: string;
  platform: string;
  polarization: string;
  acquisition_time: string;
  bbox: [number, number, number, number];
  candidate_count: number;
  is_processed: boolean;
  candidate_tiles_detected: number | null;
  footprints_geojson_url: string;
  heatmap_url: string;
}

export interface SARSceneListResponse {
  total: number;
  scenes: SARSceneListItem[];
}

export interface CandidateFootprintProperties {
  footprint_id: string;
  tile_indices: [number, number];
  centroid: [number, number];
  confidence_p_oil: number;
  confidence_pct: number;
  mean_backscatter_db: number;
  contrast_db: number;
  area_km2: number;
  screening_status: string;
  model_version: string;
}

export interface CandidateFootprintFeature {
  type: 'Feature';
  id: string;
  geometry: {
    type: 'Polygon';
    coordinates: number[][][];
  };
  properties: CandidateFootprintProperties;
}

export interface CandidateFootprintCollection {
  type: 'FeatureCollection';
  name: string;
  features: CandidateFootprintFeature[];
  metadata: {
    scene_id: string;
    platform: string;
    polarization: string;
    acquisition_time: string;
    bbox: [number, number, number, number];
    model_version: string;
    tile_size: number;
    overlap_pct: number;
    stride: number;
    total_tiles_evaluated: number;
    candidate_tiles_detected: number;
    generated_at: string;
  };
}

/* -------------------------------------------------------------------------
   Multi-Sensor Evidence Fusion (Phase 14.3)
   ------------------------------------------------------------------------- */

export interface EvidenceItem {
  modality: string;
  sensor: string;
  acquisition_time_utc: string;
  temporal_offset_hours: number | null;
  signature: string;
  confidence: number;
  consistency: "supporting" | "conflicting" | "inconclusive" | "unavailable";
  description: string;
  metrics: Record<string, unknown>;
}

export interface MultiSensorAssessment {
  candidate_id: string;
  latitude: number;
  longitude: number;
  sar_screening_status: string;
  wind_classification: string;
  optical_verification_status: string;
  concordance_score: number;
  concordance_level: string;
  triangulation_summary: string;
  recommended_action: string;
  evidence_items: EvidenceItem[];
  generated_at: string;
}

/* -------------------------------------------------------------------------
   AIS Vessel Tracking & Incident Association (Phase 15)
   ------------------------------------------------------------------------- */

export interface VesselPosition {
  id: number;
  mmsi: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  speed_knots: number;
  heading_deg: number;
  nav_status: string;
  destination?: string | null;
}

export interface Vessel {
  mmsi: string;
  imo?: string | null;
  name: string;
  callsign?: string | null;
  vessel_type: string;
  flag_country: string;
  length_m?: number | null;
  width_m?: number | null;
  draught_m?: number | null;
  risk_profile: string;
  positions?: VesselPosition[];
}

export interface CandidateVesselAssociation {
  id: number;
  candidate_id: string;
  mmsi: string;
  vessel_name: string;
  vessel_type: string;
  flag_country: string;
  association_type: string;
  spatial_distance_km: number;
  temporal_offset_minutes: number;
  interpolated_lat: number;
  interpolated_lon: number;
  association_score: number;
  is_primary_suspect: boolean;
  notes?: string | null;
}

/* -------------------------------------------------------------------------
   Lagrangian Oil Drift Simulation (Phase 16)
   ------------------------------------------------------------------------- */

export interface HourlyDriftSnapshot {
  hour: number;
  timestamp_utc: string;
  centroid_lat: number;
  centroid_lon: number;
  spread_radius_km: number;
  evaporated_pct: number;
  floating_pct: number;
  beached_pct: number;
  dispersed_pct: number;
  active_particles: number;
  beached_particles: number;
  dispersed_particles: number;
}

export interface DriftSimulation {
  simulation_id: string;
  candidate_id?: string | null;
  origin_lat: number;
  origin_lon: number;
  start_time: string;
  duration_hours: number;
  oil_type: string;
  spill_volume_m3: number;
  wind_speed_ms: number;
  wind_direction_deg: number;
  current_speed_ms: number;
  current_direction_deg: number;
  final_evaporated_pct: number;
  final_floating_pct: number;
  final_beached_pct: number;
  final_dispersed_pct: number;
  beaching_risk_level: string;
  time_to_shore_hours?: number | null;
  mass_balance_timeline: HourlyDriftSnapshot[];
  geojson: Record<string, unknown>;
}

/* -------------------------------------------------------------------------
   Environmental Impact & Marine Protected Areas (Phase 17)
   ------------------------------------------------------------------------- */

export interface MarineReceptor {
  receptor_id: string;
  name: string;
  category: string;
  jurisdiction: string;
  latitude: number;
  longitude: number;
  vulnerability_weight: number;
  description?: string | null;
}

export interface CandidateEnvironmentalImpact {
  id: number;
  candidate_id: string;
  receptor_id: string;
  receptor_name: string;
  category: string;
  distance_km: number;
  estimated_arrival_hours?: number | null;
  impact_severity: string;
  vulnerability_score: number;
  priority_action?: string | null;
}

export interface CandidateImpactAssessment {
  candidate_id: string;
  max_vulnerability_score: number;
  highest_severity: string;
  proximate_receptors_count: number;
  impacts: CandidateEnvironmentalImpact[];
  overall_mitigation_summary: string;
}

/* -------------------------------------------------------------------------
   Real Sentinel-2 optical indices

   Measured values, not a demonstration. `characterises_region` is false when
   too few water pixels were in frame for the indices to mean anything, in
   which case the page prints no number for that row.
   ------------------------------------------------------------------------- */

export interface OpticalIndexReading {
  region_code: string;
  region_name: string;
  observed_on: string;
  ndci_mean: number;
  ndci_p50: number;
  ndti_mean: number;
  ndti_p50: number;
  fdi_mean: number;
  fdi_p90: number;
  /** Always "possible floating material". Never "plastic". */
  fdi_label: string;
  water_pixels: number;
  total_pixels: number;
  water_fraction: number;
  has_thumbnail: boolean;
  /** Independent CMEMS chlorophyll for the same region, or null if not
   *  fetched. Shown beside NDCI; neither is adjusted to match the other. */
  chlorophyll_cross_check: ChlorophyllCrossCheck | null;
  max_cloud_pct: number;
  evidence_level: string;
  source: string;
  attribution: string;
  characterises_region: boolean;
  caveat: string | null;
}

export interface OpticalIndexNote {
  name: string;
  formula: string;
  reference: string;
  means: string;
}

export interface OpticalIndexResponse {
  items: OpticalIndexReading[];
  provenance: {
    evidence_level: string;
    is_real: boolean;
    source: string;
    attribution: string;
    contains_simulated_data: boolean;
    note: string;
  };
  totals: {
    readings_stored: number;
    regions_with_data: number;
    regions_total: number;
    newest_acquisition: string | null;
    min_water_pixels: number;
  };
  indices: Record<"ndci" | "ndti" | "fdi", OpticalIndexNote>;
}

/* -------------------------------------------------------------------------
   Open-Meteo sea conditions

   Model output, not observation: INFERRED. `sar_ambiguous` is true when wind
   is below the threshold at which a flat sea looks like oil in SAR, and null
   when wind is unknown — which is not the same as "fine".
   ------------------------------------------------------------------------- */

export interface MarineCondition {
  cell_code: string;
  region_name: string;
  latitude: number;
  longitude: number;
  observed_at: string | null;
  wind_speed_ms: number | null;
  wind_direction_deg: number | null;
  wind_gust_ms: number | null;
  wave_height_m: number | null;
  wave_period_s: number | null;
  sea_surface_temp_c: number | null;
  sar_ambiguous: boolean | null;
  low_wind_threshold_ms: number;
  evidence_level: string;
  provider: string;
  attribution: string;
}

export interface MarineConditionsResponse {
  items: MarineCondition[];
  fetched_at: string | null;
  available: boolean;
  detail: string | null;
  totals?: {
    regions: number;
    with_wind: number;
    low_wind_regions: number;
    low_wind_threshold_ms: number;
  };
  provenance: {
    provider: string;
    attribution: string;
    evidence_level: string;
    contains_simulated_data?: boolean;
    note?: string;
  };
}

/** An independent chlorophyll-a retrieval from Copernicus Marine. */
export interface ChlorophyllCrossCheck {
  chl_mg_m3: number;
  valid_on: string;
  valid_pixels: number | null;
  evidence_level: string;
  product: string;
  attribution: string;
  note: string;
}

/* -------------------------------------------------------------------------
   Global Fishing Watch vessel activity

   Aggregate only — no vessel identity. See app/vision/gfw_client.py: naming
   a real ship against a benchmark or demonstration detection would be an
   accusation about something that did not happen.
   ------------------------------------------------------------------------- */

export interface VesselActivity {
  cell_code: string;
  region_name: string;
  window_from: string;
  window_to: string;
  total_hours: number;
  vessel_count: number;
  grid_cells: number;
  top_flags: { flag: string; hours: number }[];
  evidence_level: string;
  product: string;
  provider: string;
  attribution: string;
  attribution_url: string;
  note: string;
}

export interface VesselActivityResponse {
  items: VesselActivity[];
  available: boolean;
  totals: {
    regions_answered: number;
    regions_with_activity: number;
    total_vessel_hours: number;
    total_vessels: number;
  };
  provenance: {
    provider: string;
    attribution: string;
    attribution_url: string;
    evidence_level: string;
    product: string;
    contains_simulated_data: boolean;
    note: string;
    identity_note: string;
  };
}

/* -------------------------------------------------------------------------
   Historical incident replay

   A documented real incident put through the same SAR pipeline. Validation
   evidence, not a monitoring product — and negatives are served exactly like
   positives, because a finding that only appears when it is favourable is
   not a finding.
   ------------------------------------------------------------------------- */

export interface IncidentReplay {
  incident: {
    name: string;
    imo: string;
    flag: string;
    sank_at: string;
    latitude: number;
    longitude: number;
    position_text: string;
    distance_text: string;
    cargo_text: string;
    citation: string;
    region_code: string;
  };
  label: string;
  screening: {
    tiles_screened: number;
    passes: {
      day: string;
      days_after: number;
      tiles: number;
      max_p_oil: number;
      flagged: number;
      wind_speed_ms: number | null;
      wind_source: string | null;
    }[];
    max_p_oil: number;
    flagged_tiles: number;
    detected: boolean;
    prepared_tile_mean: number | null;
    training_tile_mean: number;
    model: string;
    window: string;
  };
  thumbnail: string | null;
  verdict: string;
  interpretation: string;
}

export interface IncidentReplayResponse {
  items: IncidentReplay[];
  available: boolean;
  note: string;
}
