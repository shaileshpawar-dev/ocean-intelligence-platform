/**
 * Centralised, typed API client.
 *
 * Every network call in the application goes through here. Components never
 * call `fetch` directly, so error handling, base-URL resolution and status
 * semantics are defined once.
 *
 * The base URL comes from `VITE_API_BASE_URL` and falls back to a same-origin
 * relative path, which is what the production build uses when FastAPI serves
 * the SPA. No URL and no credential is ever hardcoded.
 */

import type {
  AgentCatalogue,
  AgentRunResult,
  AgentRunSummary,
  Alert,
  CandidateEvaluation,
  CorpusStats,
  DetectorInfo,
  DriftReport,
  Forecast,
  HealthResponse,
  ListResponse,
  Metrics,
  ModelVersion,
  Overview,
  PollutionEvent,
  PollutionEventDetail,
  RegionTrend,
  ReportDetail,
  ReportSummary,
  ResearchAnswer,
  RiskAssessment,
  SARCandidate,
  SARCandidateDetail,
  SARCandidateSummary,
  CandidateMapPoint,
  CandidateReviewCreateIn,
  OpticalScene,
  SARCandidateOpticalEvidence,
  CandidateFootprintCollection,
  SARSceneListResponse,
  MultiSensorAssessment,
  CandidateVesselAssociation,
  DriftSimulation,
  Vessel,
  MarineReceptor,
  CandidateImpactAssessment,
  Zone,
} from "./types";
import type {
  AvailableParameter,
  DistrictDetail,
  ListEnvelope,
  MapFeature,
  BoundaryCollection,
  CitySummary,
  ClusterResponse,
  GeometryCollection,
  MapLayerCatalogue,
  SearchResponse,
  WaterCoverage,
  ParameterTrend,
  StandardsSummary,
  StateDetail,
  StateSummary,
  StationDetail,
  StationSummary,
  WaterBodyDetail,
  WaterBodySummary,
  WaterOverview,
  WaterQualityReport,
  WaterAnswer,
  WaterSource,
} from "./waterTypes";

const BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "";

export const API_ROOT = `${BASE}/api/v1`;

/**
 * An API failure carrying enough context for the UI to respond specifically
 * rather than showing one generic error for everything.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly url: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** No data yet, as opposed to something being broken. */
  get isEmpty(): boolean {
    return this.status === 404;
  }

  /** The backend declined because it lacks enough data to answer honestly. */
  get isInsufficientData(): boolean {
    return this.status === 409 || this.status === 422;
  }

  get isAuth(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isServer(): boolean {
    return this.status >= 500;
  }

  /** A message safe to show a user: never leaks a stack trace or internals. */
  get friendly(): string {
    if (this.isAuth) return "Not authorised. Check API credentials.";
    if (this.isEmpty) return "Not found.";
    if (this.isInsufficientData) return this.detail || "Insufficient data.";
    if (this.status === 0)
      return "Cannot reach the API. Check that the backend is running.";
    if (this.isServer)
      return "The service reported an internal error. Check server logs.";
    return this.detail || `Request failed (${this.status}).`;
  }
}

/** Pull the most useful message out of a FastAPI error body. */
function extractDetail(body: unknown, fallback: string): string {
  if (typeof body === "string" && body) return body;
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    const detail = record.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors arrive as a list of {loc, msg, type}.
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as Record<string, unknown>;
      if (typeof first?.msg === "string") return first.msg;
    }
    if (typeof record.error === "string") return record.error;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_ROOT}${path}`;
  let response: Response;

  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    // Network-level failure: the server is unreachable, not erroring.
    throw new ApiError(0, "Network request failed", url);
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* a non-JSON error body is not itself an error */
    }
    throw new ApiError(
      response.status,
      extractDetail(body, response.statusText),
      url,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

/** Build a query string, dropping null/undefined so defaults stay server-side. */
function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/* =========================================================================
   Endpoints — every one of these exists on the OceanAI backend.
   ========================================================================= */

export const api = {
  /* -- system ----------------------------------------------------------- */
  health: () => get<HealthResponse>("/health"),
  overview: () => get<Overview>("/overview"),

  /* -- pollution -------------------------------------------------------- */
  zones: (limit = 1000) => get<ListResponse<Zone>>(`/pollution-zones${qs({ limit })}`),

  events: (params: {
    limit?: number;
    offset?: number;
    severity?: string | null;
    signature?: string | null;
    parent_region?: string | null;
    since_days?: number | null;
  } = {}) => get<ListResponse<PollutionEvent>>(`/pollution-events${qs(params)}`),

  event: (eventId: string) =>
    get<PollutionEventDetail>(`/pollution-events/${encodeURIComponent(eventId)}`),

  alerts: (minSeverity = "HIGH") =>
    get<ListResponse<Alert>>(`/alerts${qs({ min_severity: minSeverity })}`),

  /* -- temporal --------------------------------------------------------- */
  trends: (days = 30, parentRegion?: string | null) =>
    get<ListResponse<RegionTrend>>(
      `/trends${qs({ days, parent_region: parentRegion })}`,
    ),

  forecast: (regionCode: string, horizon = 7, model = "holt", historyDays = 60) =>
    get<Forecast>(
      `/forecast/${encodeURIComponent(regionCode)}${qs({
        horizon,
        model,
        history_days: historyDays,
      })}`,
    ),

  risk: (eventId: string) =>
    get<RiskAssessment>(`/risk/${encodeURIComponent(eventId)}`),

  /* -- satellite -------------------------------------------------------- */
  ingest: (lookbackDays?: number) =>
    post<Record<string, unknown>>(`/satellite/ingest${qs({ lookback_days: lookbackDays })}`),

  refine: (maxCells = 5) =>
    post<Record<string, unknown>>(`/satellite/refine${qs({ max_cells: maxCells })}`),

  thumbnail: (regionCode: string, dimensions = 512) =>
    get<{
      region_code: string;
      region_name: string;
      bbox: number[];
      url: string | null;
      source: string;
      available: boolean;
      detail: string | null;
    }>(`/satellite/thumbnail/${encodeURIComponent(regionCode)}${qs({ dimensions })}`),

  /* -- ml --------------------------------------------------------------- */
  models: () => get<ModelVersion[]>("/models"),
  detectors: () => get<DetectorInfo[]>("/models/detectors"),
  metrics: (days = 7) => get<Metrics>(`/metrics${qs({ days })}`),
  drift: (baselineDays = 30, currentDays = 7) =>
    get<DriftReport>(
      `/drift${qs({ baseline_days: baselineDays, current_days: currentDays })}`,
    ),
  candidateEvaluation: (threshold = 0.5) =>
    get<CandidateEvaluation>(
      `/models/sar-candidates/evaluation${qs({ threshold })}`,
    ),

  /* -- intelligence ----------------------------------------------------- */
  research: (question: string, limit = 5, docType?: string | null) =>
    post<ResearchAnswer>("/research", { question, limit, doc_type: docType ?? null }),

  researchSearch: (q: string, limit = 8, docType?: string | null) =>
    get<{ query: string; count: number; results: Record<string, unknown>[] }>(
      `/research/search${qs({ q, limit, doc_type: docType })}`,
    ),

  corpus: () => get<CorpusStats>("/research/corpus"),

  agents: () => get<AgentCatalogue>("/agents"),
  agentRuns: (limit = 20) =>
    get<{ count: number; items: AgentRunSummary[] }>(`/agents/runs${qs({ limit })}`),
  analyzeEvent: (eventId: string) =>
    post<AgentRunResult>("/agents/analyze-event", { event_id: eventId }),

  reports: (limit = 20) =>
    get<{ count: number; items: ReportSummary[] }>(`/reports${qs({ limit })}`),
  report: (reportId: string) =>
    get<ReportDetail>(`/reports/${encodeURIComponent(reportId)}`),
  reportText: (reportId: string) =>
    get<{ report_id: string; text: string }>(
      `/reports/${encodeURIComponent(reportId)}/text`,
    ),
  generateReport: (eventId: string) =>
    post<ReportDetail>("/reports/generate", { event_id: eventId }),

  /* -- India water intelligence ----------------------------------------
     Every endpoint below is backed by CPCB observations ingested from the
     National Water Informatics Centre. None of it is generated or seeded. */

  waterOverview: () => get<WaterOverview>("/water-overview"),

  waterBodies: (params: {
    state?: string | null;
    district?: string | null;
    water_type?: string | null;
    status?: string | null;
    q?: string | null;
    bbox?: string | null;
    limit?: number;
    offset?: number;
  } = {}) =>
    get<ListEnvelope<WaterBodySummary>>(`/water-bodies${qs(params)}`),

  /** `reference` overrides the selected standard: a class letter (A-E) or a code. */
  waterBody: (slug: string, reference?: string | null) =>
    get<WaterBodyDetail>(
      `/water-bodies/${encodeURIComponent(slug)}${qs({ reference })}`,
    ),

  waterBodyParameters: (slug: string) =>
    get<{ count: number; items: AvailableParameter[] }>(
      `/water-bodies/${encodeURIComponent(slug)}/parameters`,
    ),

  waterTrend: (slug: string, parameter: string, days?: number | null) =>
    get<ParameterTrend>(
      `/water-bodies/${encodeURIComponent(slug)}/trend${qs({ parameter, days })}`,
    ),

  waterBodySources: (slug: string) =>
    get<{ count: number; items: WaterSource[] }>(
      `/water-bodies/${encodeURIComponent(slug)}/sources`,
    ),

  station: (stationId: number) => get<StationDetail>(`/stations/${stationId}`),

  stations: (params: { state?: string | null; bbox?: string | null; limit?: number } = {}) =>
    get<ListEnvelope<StationSummary>>(`/stations${qs(params)}`),

  mapWaterBodies: (params: {
    bbox?: string | null;
    state?: string | null;
    water_type?: string | null;
    status?: string | null;
    limit?: number;
  } = {}) => get<{ count: number; items: MapFeature[] }>(`/map/water-bodies${qs(params)}`),

  mapStations: (params: { bbox?: string | null; state?: string | null; limit?: number } = {}) =>
    get<{ count: number; items: StationSummary[] }>(`/map/stations${qs(params)}`),

  waterNear: (lat: number, lon: number, radiusKm = 25, extra: {
    water_type?: string | null;
    status?: string | null;
    limit?: number;
  } = {}) =>
    get<ListEnvelope<WaterBodySummary> & { radius_km: number }>(
      `/map/near${qs({ lat, lon, radius_km: radiusKm, ...extra })}`,
    ),

  states: () => get<{ count: number; items: StateSummary[] }>("/states"),
  state: (slug: string) => get<StateDetail>(`/states/${encodeURIComponent(slug)}`),
  city: (slug: string) => get<DistrictDetail>(`/cities/${encodeURIComponent(slug)}`),
  cities: () => get<{ count: number; items: CitySummary[] }>("/cities"),

  /* -- Geography layers ------------------------------------------------ */
  mapLayers: () => get<MapLayerCatalogue>("/map/layers"),

  mapGeometries: (params: {
    bbox?: string | null;
    zoom?: number | null;
    state?: string | null;
    water_type?: string | null;
    status?: string | null;
  }) => get<GeometryCollection>(`/map/geometries${qs(params)}`),

  stationClusters: (params: { bbox?: string | null; zoom: number; state?: string | null }) =>
    get<ClusterResponse>(`/map/station-clusters${qs(params)}`),

  stateBoundaries: (zoom?: number | null) =>
    get<BoundaryCollection>(`/boundaries/states${qs({ zoom })}`),

  districtBoundaries: (params: { state?: string | null; bbox?: string | null; zoom?: number | null }) =>
    get<BoundaryCollection>(`/boundaries/districts${qs(params)}`),

  waterCoverage: () => get<WaterCoverage>("/water-coverage"),

  waterSearch: (q: string, limit = 25) => get<SearchResponse>(`/search${qs({ q, limit })}`),

  waterStandards: () => get<StandardsSummary>("/water-standards"),
  waterQualityReport: () => get<WaterQualityReport>("/water-quality-report"),

  /** Grounded Q&A. Figures come from stored observations, never a model. */
  waterAsk: (question: string) => post<WaterAnswer>("/water/ask", { question }),

  /* -- SAR Candidate Review & Analyst Workflow (Phase 13.2) ----------- */
  sarCandidates: (params: {
    screening_status?: string | null;
    review_status?: string | null;
    model_version?: string | null;
    is_coastal?: boolean | null;
    split?: string | null;
    search?: string | null;
    start_date?: string | null;
    end_date?: string | null;
    limit?: number;
    offset?: number;
  } = {}) => get<ListResponse<SARCandidate>>(`/sar-candidates${qs(params)}`),

  sarCandidateSummary: () => get<SARCandidateSummary>("/sar-candidates/summary"),

  sarCandidateMapPoints: () => get<CandidateMapPoint[]>("/sar-candidates/map-points"),

  sarCandidateDetail: (candidateId: string) =>
    get<SARCandidateDetail>(`/sar-candidates/${encodeURIComponent(candidateId)}`),

  submitCandidateReview: (candidateId: string, payload: CandidateReviewCreateIn) =>
    post<SARCandidateDetail>(`/sar-candidates/${encodeURIComponent(candidateId)}/reviews`, payload),

  sarCandidateImageUrl: (candidateId: string) =>
    `${API_ROOT}/sar-candidates/${encodeURIComponent(candidateId)}/image`,

  /* -- Sentinel-2 Optical Evidence (Phase 14.1) ---------------------- */
  sarCandidateOpticalScenes: (candidateId: string) =>
    get<OpticalScene[]>(`/sar-candidates/${encodeURIComponent(candidateId)}/optical-scenes`),

  sarCandidateOpticalEvidence: (candidateId: string) =>
    get<SARCandidateOpticalEvidence[]>(`/sar-candidates/${encodeURIComponent(candidateId)}/optical-evidence`),

  processCandidateOpticalEvidence: (
    candidateId: string,
    payload: { scene_id?: string | null; chip_size?: number } = {},
  ) =>
    post<SARCandidateOpticalEvidence>(
      `/sar-candidates/${encodeURIComponent(candidateId)}/optical-evidence/process`,
      payload,
    ),

  sarCandidateOpticalImageUrl: (
    candidateId: string,
    evidenceId: number,
    productType: "rgb" | "false_color" | "scl" | "ndci",
  ) =>
    `${API_ROOT}/sar-candidates/${encodeURIComponent(candidateId)}/optical-evidence/${evidenceId}/image/${productType}`,

  /* -- Full-Scene SAR Processing (Phase 14.2) ----------------------- */
  sarScenes: (params: { limit?: number; offset?: number; search?: string | null } = {}) =>
    get<SARSceneListResponse>(`/sar-scenes${qs(params)}`),

  sarSceneMetadata: (sceneId: string) =>
    get<Record<string, unknown>>(`/sar-scenes/${encodeURIComponent(sceneId)}`),

  processSarScene: (
    sceneId: string,
    payload: { confidence_threshold?: number; tile_size?: number; overlap_pct?: number } = {},
  ) => post<Record<string, unknown>>(`/sar-scenes/${encodeURIComponent(sceneId)}/process`, payload),

  sarSceneFootprints: (sceneId: string) =>
    get<CandidateFootprintCollection>(`/sar-scenes/${encodeURIComponent(sceneId)}/footprints`),

  sarSceneHeatmapUrl: (sceneId: string) =>
    `${API_ROOT}/sar-scenes/${encodeURIComponent(sceneId)}/heatmap`,

  /* -- Multi-Sensor Evidence Fusion (Phase 14.3) -------------------- */
  sarCandidateFusion: (candidateId: string) =>
    get<MultiSensorAssessment>(`/sar-candidates/${encodeURIComponent(candidateId)}/fusion`),

  /* -- AIS Vessel Tracking & Association (Phase 15) ----------------- */
  vessels: (params: { vessel_type?: string | null; risk_profile?: string | null; search?: string | null; limit?: number } = {}) =>
    get<Vessel[]>(`/vessels${qs(params)}`),

  vesselDetail: (mmsi: string) =>
    get<Vessel>(`/vessels/${encodeURIComponent(mmsi)}`),

  candidateVessels: (candidateId: string) =>
    get<CandidateVesselAssociation[]>(`/sar-candidates/${encodeURIComponent(candidateId)}/vessels`),

  correlateCandidateVessels: (candidateId: string) =>
    post<CandidateVesselAssociation[]>(`/sar-candidates/${encodeURIComponent(candidateId)}/vessels/correlate`, {}),

  /* -- Lagrangian Oil Drift Simulation (Phase 16) ------------------- */
  candidateDrift: (candidateId: string) =>
    get<DriftSimulation>(`/sar-candidates/${encodeURIComponent(candidateId)}/drift`),

  runCandidateDrift: (
    candidateId: string,
    payload: { duration_hours?: number; oil_type?: string; spill_volume_m3?: number } = {},
  ) =>
    post<DriftSimulation>(`/sar-candidates/${encodeURIComponent(candidateId)}/drift`, payload),

  /* -- Environmental Impact & Marine Protected Areas (Phase 17) ----- */
  receptors: (params: { category?: string | null; search?: string | null } = {}) =>
    get<MarineReceptor[]>(`/receptors${qs(params)}`),

  candidateImpact: (candidateId: string) =>
    get<CandidateImpactAssessment>(`/sar-candidates/${encodeURIComponent(candidateId)}/impact`),

  evaluateCandidateImpact: (candidateId: string) =>
    post<CandidateImpactAssessment>(`/sar-candidates/${encodeURIComponent(candidateId)}/impact/evaluate`, {}),
};
