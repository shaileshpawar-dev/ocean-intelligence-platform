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
  | "NO_RECENT_DATA";

export type WaterEvidenceType =
  | "MEASURED"
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
  | "not_measured";

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

export interface ComparisonResult {
  parameter: string;
  label: string;
  value: number | null;
  unit: string | null;
  designated_use: string;
  designated_use_label: string;
  compliance: Compliance;
  failed: boolean;
  exceedance_factor: number | null;
  limit_min: number | null;
  limit_max: number | null;
  standard_source: string | null;
  standard_url: string | null;
  explanation: string;
}

export interface StatusDetail {
  status: WaterStatus;
  label: string;
  designated_use: string;
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

export interface WaterBodyDetail extends Omit<WaterBodySummary, "latest_available_status"> {
  basin: string | null;
  sub_basin: string | null;
  aliases: string[];
  status_detail: StatusDetail;
  latest_available_status: StatusDetail | null;
  parameters: WaterParameterReading[];
  stations: StationSummary[];
  sources: WaterSource[];
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
}

export interface SearchHit {
  type: "water_body" | "state" | "district" | "station";
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
  name: string;
  slug: string;
  state: string;
  state_slug: string;
  latitude: number | null;
  longitude: number | null;
  water_body_count: number;
  station_count: number;
  by_type: Record<string, number>;
  water_bodies: WaterBodySummary[];
  stations: StationSummary[];
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
  sources: {
    key: string;
    name: string;
    organisation: string;
    is_available: boolean;
    expected_cadence: string;
    last_success_at: string | null;
    last_error: string | null;
  }[];
  last_ingestion: {
    run_id: string;
    source: string;
    status: string;
    records_inserted: number;
    started_at: string;
    finished_at: string | null;
  } | null;
}

export interface StandardsSummary {
  default_use: string;
  default_use_label: string;
  classes: Record<string, string>;
  thresholds_by_use: Record<
    string,
    {
      parameter: string;
      min: number | null;
      max: number | null;
      unit: string | null;
      describes: string;
    }[]
  >;
  polluted_stretch: {
    bod_threshold_mg_l: number;
    bands: {
      priority: string;
      min: number;
      max: number | null;
      describes: string;
    }[];
    source: string;
    source_url: string;
  };
  sources: { name: string; url: string }[];
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
