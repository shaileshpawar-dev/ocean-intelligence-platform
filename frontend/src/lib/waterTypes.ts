/**
 * India Water Intelligence types.
 *
 * Kept in their own module rather than appended to `types.ts` because the
 * water domain and the marine-pollution domain are genuinely separate
 * vocabularies. A laboratory BOD measurement and a SAR dark-formation
 * detection are different kinds of claim, and sharing one `Severity` type
 * between them would be the first step to conflating them.
 *
 * Note the two status fields on every water body. `status` answers "what is
 * this water body like now?" and is honestly `NO_RECENT_DATA` whenever the
 * source has not published recently. `latest_available_status` answers "what
 * did the most recent measurement find?" — it is a true statement about a
 * past date, and the UI must never render it without that date attached.
 */

export type WaterStatus =
  | "WITHIN_REFERENCE"
  | "ELEVATED"
  | "HIGH_CONCERN"
  | "POLLUTED_STRETCH"
  | "INSUFFICIENT_DATA"
  | "NO_RECENT_DATA"
  | "NO_APPLICABLE_REFERENCE";

export type WaterEvidenceType =
  | "MEASURED"
  | "REFERENCE_COMPARISON"
  | "SOURCE_CLASSIFICATION"
  | "DERIVED_STATUS"
  | "SATELLITE_OBSERVED"
  | "IMAGE_DETECTED"
  | "REPORTED"
  | "INFERRED"
  | "FORECAST"
  | "RETRIEVED";

export type WaterBodyType =
  | "river"
  | "river_stretch"
  | "lake"
  | "pond"
  | "reservoir"
  | "canal"
  | "creek"
  | "estuary"
  | "coastal"
  | "marine"
  | "groundwater"
  | "drain"
  | "other";

export type ParameterFamily = "physical" | "chemical" | "biological";

export type Compliance =
  | "within"
  | "exceeds"
  | "below"
  | "no_standard"
  | "not_measured"
  | "no_reference";

export interface WaterBodySummary {
  id: number;
  slug: string;
  name: string;
  water_type: WaterBodyType;
  state: string | null;
  state_slug: string | null;
  district: string | null;
  district_slug: string | null;
  latitude: number | null;
  longitude: number | null;
  station_count: number;
  observation_count: number;
  latest_observed_at: string | null;
  status: WaterStatus | null;
  latest_available_status: WaterStatus | null;
  match_confidence: number;
  match_method: string;
  distance_km?: number;
}

export interface Freshness {
  freshness: string;
  label: string;
  observed_at: string | null;
  age_days: number | null;
  expected_cadence: string;
  expected_cadence_label: string;
  describes_present_state: boolean;
  summary: string;
}

/** How a reference standard was chosen for a water body — or why none was. */
export interface ReferenceSelection {
  available: boolean;
  basis:
    | "user_selected"
    | "water_body_designated_use"
    | "station_classification"
    | "national_assessment_category"
    | "none";
  basis_label: string;
  reason: string;
  standard_code: string | null;
  standard_name: string | null;
  category: string | null;
  legal_basis: string | null;
  issuing_body: string | null;
  effective_date: string | null;
  source_url: string | null;
  verified_note: string | null;
}

export interface ComparisonResult {
  parameter: string;
  label: string;
  value: number | null;
  unit: string | null;
  compliance: Compliance;
  failed: boolean;
  evidence_type: "REFERENCE_COMPARISON";
  exceedance_factor: number | null;
  above_desirable: boolean;
  threshold_type: "minimum" | "maximum" | "range" | null;
  limit_min: number | null;
  limit_max: number | null;
  desirable: number | null;
  standard_code: string | null;
  standard_name: string | null;
  standard_source: string | null;
  standard_url: string | null;
  designated_use: string | null;
  explanation: string;
}

export interface SourceClassificationItem {
  evidence_type: "SOURCE_CLASSIFICATION";
  source: string;
  classification_type: string;
  assessment_year: number | null;
  priority: string | null;
  stretch_name: string | null;
  source_reference: string;
}

export interface StatusDetail {
  status: WaterStatus;
  label: string;
  evidence_type?: "DERIVED_STATUS";
  reference: ReferenceSelection;
  source_classifications: SourceClassificationItem[];
  measurements?: {
    parameter: string;
    label: string;
    value: number | null;
    unit: string | null;
    observed_at: string;
    source: string | null;
    evidence_type: "MEASURED";
  }[];
  limitations?: string[];
  designated_use: string | null;
  designated_use_label: string;
  describes_present_state: boolean;
  freshness: Freshness;
  reasons: string[];
  priority_band: string | null;
  priority_description: string | null;
  evaluated_parameters: number;
  missing_parameters: string[];
  failing_parameters: ComparisonResult[];
  comparisons: ComparisonResult[];
  engine_version: string;
  as_of?: string | null;
  note?: string;
}

export interface WaterParameterReading {
  parameter: string;
  label: string;
  family: ParameterFamily;
  value: number | null;
  raw_value?: number | null;
  unit: string | null;
  qualitative_value: string | null;
  observed_at: string | null;
  station: string | null;
  quality_flag: string;
  source_reference: string | null;
  evidence_type: WaterEvidenceType;
  comparison: ComparisonResult;
  higher_is_worse: boolean | null;
}

export interface StationSummary {
  id: number;
  code: string;
  name: string;
  slug: string;
  latitude: number | null;
  longitude: number | null;
  geo_quality: string;
  agency: string | null;
  district: string | null;
  water_body: string | null;
  water_body_slug: string | null;
  observation_count: number;
  latest_observed_at: string | null;
  position_descriptor?: string | null;
  relationship_type?: string | null;
  geometry_distance_m?: number | null;
}

export interface WaterSource {
  key: string;
  name: string;
  organisation: string;
  url: string | null;
  dataset: string | null;
  licence: string | null;
  expected_cadence: string;
  observation_count: number;
  latest_observed_at: string | null;
  retrieved_at: string | null;
}

export type GeoJsonGeometry =
  | { type: "Point"; coordinates: number[] }
  | { type: "LineString"; coordinates: number[][] }
  | { type: "MultiLineString"; coordinates: number[][][] }
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] };

export interface GeometryProvenance {
  source: string;
  source_ids: string[];
  licence: string | null;
  retrieved_at: string | null;
  version: string | null;
  confidence: "high" | "medium";
  match_method: string;
  match_notes: string[];
  feature_count: number;
  clipped: boolean;
  clipped_note: string | null;
}

export interface WaterGeometry {
  geometry: GeoJsonGeometry;
  geometry_type: GeoJsonGeometry["type"];
  bbox: [number, number, number, number];
  provenance: GeometryProvenance;
}

export type DataQualityLevel = "HIGH" | "MODERATE" | "LIMITED" | "INSUFFICIENT";

export interface DataQuality {
  level: DataQualityLevel;
  factors: { factor: string; value: string | number; meets: boolean; rule: string }[];
  rule: string;
  excludes: string;
}

/** What one agency has for one water body. Facts, not a ranking. */
export interface SourceRecency {
  key: string;
  name: string;
  organisation: string;
  source_type: string;
  observation_method: string | null;
  expected_cadence: string;
  reliability_note: string | null;
  observation_count: number;
  parameter_count: number;
  first_observed_at: string | null;
  latest_observed_at: string | null;
}

export interface Availability {
  newest_source: {
    key: string;
    name: string;
    organisation: string;
    latest_observed_at: string | null;
    observation_method: string | null;
  } | null;
  older_sources: { key: string; name: string; latest_observed_at: string | null }[];
  latest_available_observation: string | null;
  age_days: number | null;
  expected_cadence: string | null;
  describes_present_state: boolean;
  current_condition: string;
  summary: string | null;
}

export interface SourcePanelEntry {
  role: string;
  name: string | null;
  organisation: string | null;
  url: string | null;
  licence: string | null;
  latest: string | number | null;
  retrieved_at: string | null;
  records: number | null;
}

export interface SatelliteProxy {
  name: string;
  label: string;
  evidence_type: "SATELLITE_OBSERVED";
  median: number;
  mean: number;
  pixels: number;
  unit: null;
  calibrated: false;
  caveat: string;
}

export interface WaterImageEvidence {
  image_id: string;
  evidence_type: "SATELLITE" | "OFFICIAL_PHOTO" | "FIELD_PHOTO" | "REPORT_IMAGE" | "REFERENCE";
  source: string;
  provider: string | null;
  sensor: string | null;
  scene_id: string | null;
  acquisition_date: string | null;
  thumbnail_url: string | null;
  full_image_url: string | null;
  bbox: [number, number, number, number];
  licence: string | null;
  retrieved_at: string | null;
  water_fraction: number | null;
  cloud_fraction: number | null;
  proxy: SatelliteProxy | null;
  scenes_tried: { scene_id: string; date: string; rejected?: string; accepted?: boolean }[];
}

export interface WaterBodyDetail extends Omit<WaterBodySummary, "latest_available_status"> {
  /** What is known, and what is not. */
  data_availability?: DataAvailability;
  basin: string | null;
  sub_basin: string | null;
  aliases: string[];
  status_detail: StatusDetail;
  latest_available_status: StatusDetail | null;
  parameters: WaterParameterReading[];
  reference: ReferenceSelection;
  designated_use_recorded: string | null;
  stations: StationSummary[];
  sources: WaterSource[];
  geometry: WaterGeometry | null;
  geometry_status: string;
  geometry_status_text: string;
  data_quality: DataQuality;
  availability: Availability;
  sources_panel: SourcePanelEntry[];
  sources_by_recency: SourceRecency[];
  imagery: WaterImageEvidence[];
  imagery_note: string;
}

export interface StationDetail extends StationSummary {
  status_detail: StatusDetail;
  latest_available_status: StatusDetail | null;
  parameters: WaterParameterReading[];
}

export interface TrendPoint {
  observed_at: string;
  value: number;
  station: string | null;
  quality_flag: string;
  /** Which agency measured it. Series are never merged across sources. */
  source: string;
  source_name: string;
}

export interface ParameterTrend {
  water_body: string;
  slug: string;
  parameter: string;
  label: string;
  unit: string | null;
  family: string;
  higher_is_worse: boolean | null;
  point_count: number;
  points: TrendPoint[];
  first_observed_at: string | null;
  last_observed_at: string | null;
  min: number | null;
  max: number | null;
  mean: number | null;
  sufficient: boolean;
  note: string | null;
}

export interface AvailableParameter {
  parameter: string;
  label: string;
  family: string;
  unit: string | null;
  point_count: number;
  first_observed_at: string | null;
  last_observed_at: string | null;
  plottable: boolean;
}

export interface MapFeature {
  id: number;
  slug: string;
  name: string;
  water_type: WaterBodyType;
  latitude: number;
  longitude: number;
  status: WaterStatus | null;
  latest_available_status: WaterStatus | null;
  station_count: number;
  observation_count: number;
  latest_observed_at: string | null;
  has_geometry?: boolean;
}

export interface GeometryFeature {
  type: "Feature";
  geometry: GeoJsonGeometry;
  properties: {
    slug: string;
    name: string;
    water_type: WaterBodyType;
    geometry_type: string;
    latest_available_status: WaterStatus | null;
    status: WaterStatus | null;
    confidence: string;
    source: string;
    clipped: boolean;
  };
}

export interface GeometryCollection {
  type: "FeatureCollection";
  features: GeometryFeature[];
  count: number;
  truncated: boolean;
  attribution: string;
}

export interface BoundaryFeature {
  type: "Feature";
  geometry: GeoJsonGeometry;
  properties: {
    name: string;
    level: "state" | "district";
    parent: string | null;
    state_code: string | null;
    state_slug: string | null;
    has_water_data: boolean;
    centroid: [number, number];
    bbox: [number, number, number, number];
  };
}

export interface BoundaryCollection {
  type: "FeatureCollection";
  features: BoundaryFeature[];
  count: number;
  source: string;
  licence: string;
  vintage: string;
  disclaimer: string;
}

export type ClusterItem =
  | {
      kind: "cluster";
      count: number;
      latitude: number;
      longitude: number;
      worst_latest_available_status: WaterStatus | null;
      status_counts: Record<string, number>;
    }
  | {
      kind: "station";
      id: number;
      name: string;
      latitude: number;
      longitude: number;
      water_body_slug?: string | null;
      latest_available_status: WaterStatus | null;
      latest_observed_at: string | null;
    };

export interface ClusterResponse {
  zoom: number;
  clustered: boolean;
  items: ClusterItem[];
}

export interface MapLayerDef {
  key: string;
  label: string;
  kind: "geojson" | "wms" | "clusters" | "points" | "style" | "detail_only";
  endpoint?: string;
  default: boolean;
  min_zoom?: number;
  attribution?: string;
  note?: string;
  wms?: {
    url: string;
    layers: string;
    format: string;
    transparent: boolean;
    version: string;
    verified: string;
  };
}

export interface MapLayerCatalogue {
  groups: { key: string; label: string; layers: MapLayerDef[] }[];
}

export interface CitySummary {
  name: string;
  slug: string;
  state: string | null;
  state_slug: string | null;
  aliases: string[];
  latitude: number | null;
  longitude: number | null;
  bbox: [number, number, number, number] | null;
  definition: string;
  position_source: string;
}

export interface SearchResponse {
  query: string;
  count: number;
  items: SearchHit[];
  ask_suggested: boolean;
  intent: string | null;
}

export interface SearchHit {
  type: "water_body" | "state" | "district" | "station" | "city";
  bbox?: [number, number, number, number] | null;
  title: string;
  subtitle: string;
  slug: string;
  href: string;
  water_type?: WaterBodyType;
  status?: WaterStatus | null;
  latest_available_status?: WaterStatus | null;
  latest_observed_at?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  rank?: number;
}

export interface StateSummary {
  code: string;
  name: string;
  slug: string;
  water_body_count: number;
  station_count: number;
  latest_observed_at: string | null;
}

export interface StateDetail extends StateSummary {
  observation_count: number;
  by_type: Record<string, number>;
  status_distribution: Record<string, number>;
  historical_status_distribution: Record<string, number>;
  districts: {
    name: string;
    slug: string;
    water_body_count: number;
    latitude: number | null;
    longitude: number | null;
  }[];
  notable: WaterBodySummary[];
}

export interface DistrictDetail {
  kind?: "district" | "city";
  /** City fields, present when kind === "city". */
  definition?: string;
  position_source?: string;
  aliases?: string[];
  bbox?: [number, number, number, number] | null;
  districts?: { name: string; slug: string }[];
  latest_available_status_counts?: Record<string, number>;
  latest_observed_at?: string | null;
  empty_reason?: string | null;
  name: string;
  slug: string;
  state: string | null;
  state_slug: string | null;
  latitude: number | null;
  longitude: number | null;
  water_body_count: number;
  station_count: number;
  by_type: Record<string, number>;
  water_bodies: WaterBodySummary[];
  stations: StationSummary[];
}

/** What kinds of knowledge exist for one water body. Absence is the point:
 *  a reader should see that there is no real-time data without inferring it
 *  from an empty panel. */
export interface DataAvailability {
  real_time: boolean;
  real_time_detail: string;
  latest_measurement: string | null;
  latest_source: string | null;
  age_days: number | null;
  historical: boolean;
  historical_detail: string;
  geometry: boolean;
  satellite_evidence: boolean;
  official_classification: boolean;
  parameters_measured: number;
}

export interface WaterOverview {
  water_bodies: number;
  monitoring_stations: number;
  observations: number;
  states_covered: number;
  districts_covered: number;
  latest_observation_at: string | null;
  status_distribution: Record<string, number>;
  /** What each body's most recent measurement found. Always date-qualified. */
  historical_status_distribution: Record<string, number>;
  without_recent_data: number;
  /** The four-way split: how many water bodies can be described now, how
   *  many only historically, how many not at all. */
  coverage: {
    total: number;
    current: number;
    recent: number;
    historical_only: number;
    no_data: number;
    current_within_days: number;
    recent_within_days: number;
    note: string;
  };
  sources: {
    key: string;
    name: string;
    organisation: string;
    is_available: boolean;
    expected_cadence: string;
    last_success_at: string | null;
    last_error: string | null;
    /** Computed from the provider's last real fetch, never configured.
     *  See water_service.source_status. */
    status?: DataSourceStatus;
  }[];
  /** Every external service the platform reads, with state derived from
   *  what each one last actually produced. */
  external_providers?: ExternalProvider[];
  last_ingestion: {
    run_id: string;
    source: string;
    status: string;
    records_inserted: number;
    started_at: string;
    finished_at: string | null;
  } | null;
}

export interface StandardThreshold {
  parameter: string;
  label: string;
  type: "minimum" | "maximum" | "range" | "categorical";
  min: number | null;
  max: number | null;
  desirable: number | null;
  unit: string | null;
  note: string | null;
}

export interface StandardDefinition {
  code: string;
  name: string;
  category: string | null;
  issuing_body: string;
  legal_basis: string;
  source_url: string;
  verified_note: string;
  version?: string | null;
  effective_date?: string | null;
  thresholds: StandardThreshold[];
}

export interface StandardsSummary {
  selection_order: { basis: string; label: string }[];
  national_assessment: { applies_to: string[]; standard_code: string; reason: string };
  standards: StandardDefinition[];
  polluted_stretch_bands: { priority: string; min: number; max: number | null; describes: string }[];
  notes: string[];
}

export interface WaterQualityReport {
  observations_by_flag: Record<string, number>;
  stations_by_geo_quality: Record<string, number>;
  stations_without_water_body: number;
  notes: string[];
}

export interface ListEnvelope<T> {
  count: number;
  total?: number;
  limit?: number;
  offset?: number;
  items: T[];
  provenance?: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Water Q&A                                                           */
/* ------------------------------------------------------------------ */

export type WaterAnswerStatus = "grounded" | "partial" | "no_evidence";

export interface WaterCitation {
  position: number;
  kind: "observation" | "status" | "document" | "water_body" | "station" | "satellite";
  title: string;
  detail: string;
  evidence_type: WaterEvidenceType;
  water_body_slug: string | null;
  station_id: number | null;
  observed_at: string | null;
  source: string | null;
  source_reference: string | null;
  url: string | null;
  latitude: number | null;
  longitude: number | null;
  href: string | null;
}

export interface MapAction {
  type: "highlight" | "fit";
  water_body_slugs?: string[];
  focus?: string | null;
  bbox: [number, number, number, number] | null;
  href: string;
}

export interface WaterTraceStep {
  stage: "IDENTIFY" | "OBSERVE" | "RESEARCH" | "ANALYZE" | "REPORT";
  tool: string;
  arguments: Record<string, unknown>;
  result: string;
  duration_ms: number;
}

export interface WaterAnswer {
  question: string;
  intent: string;
  status: WaterAnswerStatus;
  headline: string;
  sections: Record<string, unknown>[];
  citations: WaterCitation[];
  limitations: string[];
  map_action: MapAction | null;
  resolution: {
    water_bodies: string[];
    cities?: string[];
    districts: string[];
    states: string[];
    parameters: string[];
    radius_km: number | null;
    water_types: string[];
  };
  trace: WaterTraceStep[];
  pipeline_version: string;
  llm_used: boolean;
  notes: string[];
  answered_at: string;
}

/* ------------------------------------------------------------------ */
/* Coverage                                                            */
/* ------------------------------------------------------------------ */

export interface WaterCoverage {
  generated_at: string;
  provider: string;
  totals: {
    states_available_in_source: number;
    states_loaded: number;
    states_without_data: string[];
    districts: number;
    cities: number;
    water_bodies: number;
    water_bodies_by_type: Record<string, number>;
    stations: number;
    stations_with_coordinates: number;
    observations: number;
    date_min: string | null;
    date_max: string | null;
    geometries: number;
    geometry_status: Record<string, number>;
    boundaries: Record<string, number>;
  };
  states: {
    code: string;
    name: string;
    in_source: boolean;
    source_resources: number;
    loaded: boolean;
    districts: number;
    water_bodies: number;
    water_bodies_by_type: Record<string, number>;
    stations: number;
    observations: number;
    date_min: string | null;
    date_max: string | null;
    note: string;
  }[];
}

/** A provider's current state, derived from its last real fetch result.
 *
 *  "sync_paused" is distinct from "unavailable" on purpose: a server that
 *  answers and refuses is not an outage, and reporting it as one sends
 *  somebody looking for a network fault that does not exist. */
export interface DataSourceStatus {
  state: "live" | "stale" | "sync_paused" | "unavailable";
  label: string;
  tone: "ok" | "warn" | "bad";
  /** One sentence for the card. */
  detail: string;
  records_held: number;
  /** The raw error, for the Technical details toggle only. */
  technical_detail: string | null;
}

/** An external data service, as the Data Sources page shows it.
 *
 *  Distinct from the Indian water providers above, which have database rows
 *  and an ingestion history. These are derived on each request from what the
 *  source last produced: rows in a table, files in a cache, a timestamp on a
 *  cached response. Nothing about them is configured. */
export interface ExternalProvider {
  key: string;
  name: string;
  organisation: string;
  /** What this source actually feeds, in one sentence. */
  what_it_feeds: string;
  expected_cadence: string;
  attribution: string;
  url: string | null;
  evidence_level: string | null;
  status: DataSourceStatus;
  last_success_at: string | null;
}
