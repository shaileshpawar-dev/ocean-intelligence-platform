/**
 * Marine Candidate Review Dashboard (Phase 13.2)
 *
 * Analyst-facing candidate review workflow connecting Sentinel-1 SAR candidate detections,
 * CNN V2.2 experimental model, ERA5 environmental reanalysis context, and human audit history.
 */

import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Ship,
  GitMerge,
  Clock,
  Compass,
  Info,
  RefreshCw,
  Search,
  ShieldAlert,
  Layers,
  Sparkles,
  Sun,
  Wind,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CandidateReviewCreateIn } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  LoadingSkeleton,
  MetricCard,
  PageHeader,
  SectionCard,
  SimulatedBanner,
  StatusBadge,
  formatDateTime,
  titleise,
} from "@/components/ui";

const SCREENING_OPTIONS = [
  { value: "ALL", label: "All Screening States" },
  { value: "candidate_requires_review", label: "Standard Review (Wind 3–12 m/s)" },
  { value: "low_wind_ambiguity_review", label: "Low-Wind Ambiguity (< 3 m/s)" },
  { value: "high_wind_ambiguity_review", label: "High-Wind Ambiguity (> 12 m/s)" },
  { value: "no_candidate_detected", label: "No Candidate Detected (< 0.50)" },
];

const REVIEW_OPTIONS = [
  { value: "ALL", label: "All Review Statuses" },
  { value: "awaiting_review", label: "Awaiting Review" },
  { value: "potential_oil_slick", label: "Potential Oil Slick" },
  { value: "rejected_lookalike", label: "Rejected Look-alike" },
  { value: "inconclusive", label: "Inconclusive" },
  { value: "requires_additional_evidence", label: "Requires Evidence" },
];

function screeningBadge(status: string) {
  switch (status) {
    case "candidate_requires_review":
      return <StatusBadge tone="warn" label="Standard Review" />;
    case "low_wind_ambiguity_review":
      return <StatusBadge tone="info" label="Low-Wind Ambiguity" />;
    case "high_wind_ambiguity_review":
    case "candidate_flagged_high_wind":
      return <StatusBadge tone="info" label="High-Wind Ambiguity" />;
    case "no_candidate_detected":
      return <StatusBadge tone="neutral" label="No Candidate" />;
    default:
      return <StatusBadge tone="neutral" label={titleise(status)} />;
  }
}

function decisionBadge(decision: string | null) {
  if (!decision || decision === "awaiting_review") {
    return <span className="decision-chip chip-pending">Awaiting Review</span>;
  }
  switch (decision) {
    case "potential_oil_slick":
      return <span className="decision-chip chip-slick">Potential Oil Slick</span>;
    case "rejected_lookalike":
      return <span className="decision-chip chip-rejected">Rejected Look-alike</span>;
    case "inconclusive":
      return <span className="decision-chip chip-inconclusive">Inconclusive</span>;
    case "requires_additional_evidence":
      return <span className="decision-chip chip-evidence">Requires Evidence</span>;
    default:
      return <span className="decision-chip">{titleise(decision)}</span>;
  }
}

function windSpeedColor(speed: number | null): string {
  if (speed === null) return "var(--neutral)";
  if (speed < 3.0) return "#ec4899"; // pink/magenta: low-wind ambiguity
  if (speed <= 10.0) return "#10b981"; // green: favorable slick formation window
  return "#f59e0b"; // amber: rough sea, dispersion
}

/* -------------------------------------------------------------------------
   Candidate Detail & Review Drawer
   ------------------------------------------------------------------------- */

function CandidateDetailDrawer({
  candidateId,
  onClose,
}: {
  candidateId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sar-candidate-detail", candidateId],
    queryFn: () => api.sarCandidateDetail(candidateId),
  });

  const [decision, setDecision] = useState<string>("potential_oil_slick");
  const [reviewerId, setReviewerId] = useState<string>("analyst_local");
  const [notes, setNotes] = useState<string>("");
  const [submitSuccess, setSubmitSuccess] = useState<boolean>(false);

  const [activeOpticalProduct, setActiveOpticalProduct] = useState<"rgb" | "false_color" | "scl" | "ndci">("rgb");
  const [showScenePicker, setShowScenePicker] = useState<boolean>(false);

  const { data: fusionData, isLoading: fusionLoading } = useQuery({
    queryKey: ["candidate-fusion", candidateId],
    queryFn: () => api.sarCandidateFusion(candidateId),
    enabled: !!candidateId,
  });

  const { data: vesselAssocs, isLoading: vesselsLoading } = useQuery({
    queryKey: ["candidate-vessels", candidateId],
    queryFn: () => api.candidateVessels(candidateId),
    enabled: !!candidateId,
  });

  const correlateMutation = useMutation({
    mutationFn: () => api.correlateCandidateVessels(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-vessels", candidateId] });
    },
  });

  const { data: driftData, isLoading: driftLoading } = useQuery({
    queryKey: ["candidate-drift", candidateId],
    queryFn: () => api.candidateDrift(candidateId),
    enabled: !!candidateId,
  });

  const runDriftMutation = useMutation({
    mutationFn: (durationHours: number) =>
      api.runCandidateDrift(candidateId, { duration_hours: durationHours }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-drift", candidateId] });
    },
  });

  const { data: impactData, isLoading: impactLoading } = useQuery({
    queryKey: ["candidate-impact", candidateId],
    queryFn: () => api.candidateImpact(candidateId),
    enabled: !!candidateId,
  });

  const evaluateImpactMutation = useMutation({
    mutationFn: () => api.evaluateCandidateImpact(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-impact", candidateId] });
    },
  });



  const {
    data: opticalScenes,
    isLoading: scenesLoading,
  } = useQuery({
    queryKey: ["candidate-optical-scenes", candidateId],
    queryFn: () => api.sarCandidateOpticalScenes(candidateId),
    enabled: !!candidateId,
  });

  const processOpticalMutation = useMutation({
    mutationFn: (sceneId?: string | null) =>
      api.processCandidateOpticalEvidence(candidateId, { scene_id: sceneId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sar-candidate-detail", candidateId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-fusion", candidateId] });
      refetch();
    },
  });

  const reviewMutation = useMutation({
    mutationFn: (payload: CandidateReviewCreateIn) =>
      api.submitCandidateReview(candidateId, payload),
    onSuccess: () => {
      setSubmitSuccess(true);
      setTimeout(() => setSubmitSuccess(false), 3000);
      queryClient.invalidateQueries({ queryKey: ["sar-candidate-detail", candidateId] });
      queryClient.invalidateQueries({ queryKey: ["sar-candidates"] });
      queryClient.invalidateQueries({ queryKey: ["sar-candidate-summary"] });
      queryClient.invalidateQueries({ queryKey: ["sar-candidate-map-points"] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    reviewMutation.mutate({
      decision,
      reviewer_id: reviewerId.trim() || "analyst_local",
      notes: notes.trim() || null,
    });
  };

  return (
    <aside className="detail-panel candidate-drawer" aria-label="SAR Candidate Detail">
      <div className="detail-head">
        <div>
          <h2>Candidate Inspection</h2>
          <p className="muted-note mono">{candidateId}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close detail drawer">
          <X size={16} />
        </button>
      </div>

      <div className="detail-body">
        {isLoading && <LoadingSkeleton rows={6} height={48} />}
        {isError && <ErrorState error={error} onRetry={() => refetch()} />}

        {data && (
          <>
            {/* SAR Patch Image Preview */}
            <div className="sar-image-container">
              <div className="sar-image-header">
                <span className="sar-image-tag">Historical Sentinel-1 SAR Research Patch</span>
                <span className="mono">{data.image_name}</span>
              </div>
              <img
                src={api.sarCandidateImageUrl(data.candidate_id)}
                alt={`SAR radar patch for candidate ${data.candidate_id}`}
                className="sar-patch-img"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
              <p className="sar-image-caption">
                256x256 pixel patch · VV polarization backscatter amplitude · frozen research sample, not a live acquisition
              </p>
            </div>

            {/* Status Hero */}
            <div className="candidate-hero-banner">
              <div>
                <span className="hero-label">Screening State</span>
                <div>{screeningBadge(data.screening_status)}</div>
              </div>
              <div>
                <span className="hero-label">Review Status</span>
                <div>{decisionBadge(data.review_status)}</div>
              </div>
            </div>

            {/* Model Detection */}
            <h3 className="detail-section">Detection & Model Inference</h3>
            <div className="kv">
              <span>Detector / Model</span>
              <span className="mono">{data.model_version}</span>
            </div>
            <div className="kv">
              <span>Raw Model Score</span>
              <span className="mono font-bold">
                {(data.raw_confidence * 100).toFixed(1)}%
              </span>
            </div>
            <div className="kv">
              <span>Calibration Status</span>
              <span className="cal-flag">
                {data.confidence_is_calibrated ? "Calibrated probability" : "Uncalibrated ranking score"}
              </span>
            </div>
            <div className="kv">
              <span>Formation Component</span>
              <span className="mono">
                {data.component_id !== null ? `Component #${data.component_id}` : "Single formation"}
              </span>
            </div>

            {/* ERA5 Environmental Context */}
            <h3 className="detail-section">ERA5 Environmental Context</h3>
            <div className="kv">
              <span>10m Wind Speed</span>
              <span
                style={{
                  color: windSpeedColor(data.wind_speed_ms),
                  fontWeight: 650,
                }}
              >
                {data.wind_speed_ms !== null ? `${data.wind_speed_ms.toFixed(2)} m/s` : "Unavailable"}
              </span>
            </div>
            <div className="kv">
              <span>10m Wind Direction</span>
              <span>
                {data.wind_direction_deg !== null
                  ? `${data.wind_direction_deg.toFixed(1)}°`
                  : "Unavailable"}
              </span>
            </div>
            <div className="kv">
              <span>Collocation Grid</span>
              <span className="mono text-xs">
                {data.grid_latitude?.toFixed(2)}°N, {data.grid_longitude?.toFixed(2)}°E
              </span>
            </div>
            <div className="kv">
              <span>Grid Distance / Temporal</span>
              <span className="mono text-xs">
                {data.grid_distance_km?.toFixed(1)} km · {data.temporal_offset_minutes?.toFixed(0)} min
              </span>
            </div>
            <div className="kv">
              <span>Quality Status</span>
              <span className="mono text-xs">{data.quality_status}</span>
            </div>

            {/* Environmental Warnings */}
            {data.environmental_warnings && data.environmental_warnings.length > 0 && (
              <div className="warning-callout">
                <div className="warning-callout-head">
                  <AlertTriangle size={15} />
                  <strong>Environmental Flags</strong>
                </div>
                <ul>
                  {data.environmental_warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Physical Interpretation */}
            <h3 className="detail-section">Physical Interpretation</h3>
            <div className="interpretation-card">
              <Info size={16} className="interpretation-icon" />
              <p>{data.interpretation}</p>
            </div>

            {/* Location & Time */}
            <h3 className="detail-section">Geography & Acquisition</h3>
            <div className="kv">
              <span>Coordinates</span>
              <span className="mono">
                {data.latitude.toFixed(4)}°N, {data.longitude.toFixed(4)}°E
              </span>
            </div>
            <div className="kv">
              <span>Coastal Proximity</span>
              <span>{data.is_coastal ? "Coastal (< 25 km)" : "Open Offshore"}</span>
            </div>
            <div className="kv">
              <span>Acquisition Time</span>
              <span className="mono text-xs">{formatDateTime(data.acquisition_timestamp)}</span>
            </div>

            {/* Sentinel-2 Optical Evidence (Phase 14.1) */}
            <h3 className="detail-section optical-section-head">
              <span className="flex items-center gap-1.5">
                <Sun size={16} className="text-amber-400" />
                Sentinel-2 Optical Evidence (Synthetic Products)
              </span>
              {data.optical_evidence && data.optical_evidence.length > 0 && (
                <button
                  type="button"
                  className="btn btn-xs btn-secondary"
                  onClick={() => setShowScenePicker(!showScenePicker)}
                >
                  <Layers size={12} /> {showScenePicker ? "Close Scenes" : "Browse Scenes"}
                </button>
              )}
            </h3>

            {/* If scenes picker is toggled open */}
            {showScenePicker && (
              <div className="optical-scene-picker-box">
                <div className="picker-head">
                  <span className="text-xs font-semibold">Copernicus Discovered Scenes ({opticalScenes?.length ?? 0})</span>
                  <button type="button" className="btn-close-mini" onClick={() => setShowScenePicker(false)}>×</button>
                </div>
                {scenesLoading && <p className="text-xs text-muted">Searching Copernicus Data Space...</p>}
                <div className="scene-cards-list">
                  {opticalScenes?.map((s) => (
                    <div key={s.scene_id} className={`scene-select-card ${s.is_best_match ? 'card-best' : ''}`}>
                      <div className="scene-card-top">
                        <span className="scene-platform">{s.platform}</span>
                        <span className="scene-delta">{s.temporal_delta_hours > 0 ? `+${s.temporal_delta_hours}h` : `${s.temporal_delta_hours}h`}</span>
                        <span className="scene-cloud">{s.cloud_cover_pct.toFixed(1)}% cloud</span>
                      </div>
                      <div className="scene-card-id mono text-2xs truncate">{s.scene_id}</div>
                      <div className="scene-card-bot">
                        <span className="scene-grade text-2xs">{s.quality_grade}</span>
                        <button
                          type="button"
                          className="btn btn-2xs btn-primary"
                          disabled={processOpticalMutation.isPending}
                          onClick={() => {
                            processOpticalMutation.mutate(s.scene_id);
                            setShowScenePicker(false);
                          }}
                        >
                          {processOpticalMutation.isPending ? "Extracting..." : "Extract Chip"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* When optical evidence exists */}
            {data.optical_evidence && data.optical_evidence.length > 0 ? (
              (() => {
                const opt = data.optical_evidence[0];
                return (
                  <div className="optical-evidence-card">
                    <SimulatedBanner detail="SYNTHETIC optical products: reflectance bands and rendered indices are generated arrays, not measured Sentinel-2 surface reflectance. Scene metadata is real Copernicus STAC metadata." />
                    {/* Scene Metadata Bar */}
                    <div className="optical-meta-bar">
                      <div className="flex items-center gap-2">
                        <span className="badge-platform">{opt.platform}</span>
                        <span className="mono text-2xs">{opt.tile_id || "L2A"}</span>
                      </div>
                      <span className={`temporal-badge ${Math.abs(opt.temporal_offset_hours) <= 24 ? 'badge-near' : 'badge-far'}`}>
                        <Clock size={11} /> {opt.temporal_offset_hours > 0 ? `+${opt.temporal_offset_hours.toFixed(1)}h` : `${opt.temporal_offset_hours.toFixed(1)}h`} vs SAR
                      </span>
                    </div>

                    {/* Product Selector Tabs */}
                    <div className="optical-tabs-row">
                      <button
                        type="button"
                        className={`opt-tab ${activeOpticalProduct === "rgb" ? "active" : ""}`}
                        onClick={() => setActiveOpticalProduct("rgb")}
                      >
                        True-Colour
                      </button>
                      <button
                        type="button"
                        className={`opt-tab ${activeOpticalProduct === "false_color" ? "active" : ""}`}
                        onClick={() => setActiveOpticalProduct("false_color")}
                      >
                        False-Colour (SWIR)
                      </button>
                      <button
                        type="button"
                        className={`opt-tab ${activeOpticalProduct === "scl" ? "active" : ""}`}
                        onClick={() => setActiveOpticalProduct("scl")}
                      >
                        SCL Mask
                      </button>
                      <button
                        type="button"
                        className={`opt-tab ${activeOpticalProduct === "ndci" ? "active" : ""}`}
                        onClick={() => setActiveOpticalProduct("ndci")}
                      >
                        NDCI Algal Map
                      </button>
                    </div>

                    {/* Image Viewer */}
                    <div className="optical-img-frame">
                      <img
                        src={api.sarCandidateOpticalImageUrl(data.candidate_id, opt.id, activeOpticalProduct)}
                        alt={`Sentinel-2 optical product ${activeOpticalProduct} for ${data.candidate_id}`}
                        className="optical-preview-img"
                      />
                      <div className="optical-img-caption">
                        {activeOpticalProduct === "rgb" && "Simulated True-Colour RGB (B04, B03, B02) · not measured reflectance"}
                        {activeOpticalProduct === "false_color" && "Simulated SWIR Composite (B11, B08, B04) · illustrative contrast only"}
                        {activeOpticalProduct === "scl" && "Simulated Scene Classification (SCL 20m) · illustrative mask"}
                        {activeOpticalProduct === "ndci" && "Simulated NDCI Index (B05-B04)/(B05+B04) · not a chlorophyll measurement"}
                      </div>
                    </div>

                    {/* Quality Breakdown Bars */}
                    <div className="optical-quality-grid">
                      <div className="opt-metric">
                        <span className="lbl">Water Fraction</span>
                        <span className="val font-semibold text-sky-400">{(opt.local_water_fraction * 100).toFixed(1)}%</span>
                      </div>
                      <div className="opt-metric">
                        <span className="lbl">Cloud Contamination</span>
                        <span className={`val font-semibold ${opt.local_cloud_fraction > 0.2 ? 'text-amber-400' : 'text-slate-300'}`}>
                          {(opt.local_cloud_fraction * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="opt-metric">
                        <span className="lbl">Cloud Shadow</span>
                        <span className="val font-semibold text-slate-400">{(opt.local_shadow_fraction * 100).toFixed(1)}%</span>
                      </div>
                      <div className="opt-metric">
                        <span className="lbl">Quality Flag</span>
                        <span className={`badge-opt-flag ${opt.optical_quality_flag.toLowerCase()}`}>
                          {opt.optical_quality_flag}
                        </span>
                      </div>
                    </div>

                    {/* Spectral Indicators Row */}
                    <div className="spectral-row">
                      <div className="spec-item">
                        <span className="spec-lbl">Mean NDCI (Algal):</span>
                        <span className="spec-val mono">{opt.mean_ndci !== null ? opt.mean_ndci.toFixed(3) : "—"}</span>
                      </div>
                      <div className="spec-item">
                        <span className="spec-lbl">Turbidity (NDTI):</span>
                        <span className="spec-val mono">{opt.mean_ndti !== null ? opt.mean_ndti.toFixed(3) : "—"}</span>
                      </div>
                      <div className="spec-item">
                        <span className="spec-lbl">SWIR/NIR Ratio:</span>
                        <span className="spec-val mono">{opt.mean_swir_ratio !== null ? opt.mean_swir_ratio.toFixed(2) : "—"}</span>
                      </div>
                    </div>

                    {/* Scientific Guardrail Callout */}
                    <div className="guardrail-notice">
                      <ShieldAlert size={14} className="guardrail-icon" />
                      <span>
                        <strong>Scientific Guardrail:</strong> NDCI is an environmental chlorophyll-a/turbidity indicator, NOT proof of oil.
                        Elevated NDCI suggests radar damping may stem from biogenic algal surfactants.
                      </span>
                    </div>
                  </div>
                );
              })()
            ) : (
              <div className="optical-empty-card">
                <div className="empty-content">
                  <Sun size={20} className="text-amber-400 mb-1" />
                  <p className="text-xs font-medium">No optical evidence processed yet for this candidate.</p>
                  <p className="text-2xs text-muted mb-3">
                    {opticalScenes && opticalScenes.length > 0
                      ? `${opticalScenes.length} intersecting Sentinel-2 L2A scene(s) discovered in Copernicus Data Space.`
                      : "Searching Copernicus Data Space for collocated Level-2A imagery..."}
                  </p>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={processOpticalMutation.isPending}
                    onClick={() => processOpticalMutation.mutate(null)}
                  >
                    {processOpticalMutation.isPending ? (
                      <>
                        <RefreshCw size={13} className="animate-spin" /> Extracting COG Window...
                      </>
                    ) : (
                      <>
                        <Sparkles size={13} /> Extract & Process Optical Evidence
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Multi-Sensor Evidence Fusion (Phase 14.3) */}
            <h3 className="detail-section optical-section-head">
              <span className="flex items-center gap-1.5">
                <GitMerge size={16} className="text-cyan-400" />
                Multi-Sensor Evidence Fusion
              </span>
              {fusionData && (
                <span className={`fusion-concordance-chip ${fusionData.concordance_level.toLowerCase()}`}>
                  {fusionData.concordance_level.replace(/_/g, " ")} · {fusionData.concordance_score.toFixed(2)} rule score
                </span>
              )}
            </h3>

            {fusionLoading && <p className="text-xs text-muted">Triangulating multi-sensor evidence...</p>}

            {fusionData && (
              <div className="fusion-assessment-box">
                <SimulatedBanner detail="Rule-based concordance over simulated optical inputs. The rule score is not a calibrated probability and does not establish that oil is present." />
                <div className="fusion-summary-card">
                  <div className="fusion-summary-text">
                    <p className="text-xs font-semibold mb-1">Physical Evidence Synthesis</p>
                    <p className="text-xs text-muted mb-2">{fusionData.triangulation_summary}</p>
                    <div className="fusion-action-pill">
                      <strong>Rule Output:</strong> {fusionData.recommended_action}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn btn-xs btn-secondary mt-2"
                    onClick={() => {
                      if (fusionData.concordance_level === "MULTI_SENSOR_CONCORDANCE") {
                        setDecision("potential_oil_slick");
                      } else if (fusionData.concordance_level === "BIOGENIC_LOOKALIKE") {
                        setDecision("rejected_lookalike");
                      } else if (fusionData.concordance_level === "CALM_WATER_AMBIGUITY") {
                        setDecision("inconclusive");
                      } else {
                        setDecision("requires_additional_evidence");
                      }
                      setNotes(`[Multi-Sensor Synthesis]: ${fusionData.triangulation_summary}`);
                    }}
                  >
                    <Sparkles size={12} /> Adopt Recommendation & Populate Notes
                  </button>
                </div>

                {/* Evidence Items Timeline */}
                <div className="fusion-evidence-timeline">
                  {fusionData.evidence_items.map((item, idx) => (
                    <div key={idx} className={`fusion-item-card consistency-${item.consistency}`}>
                      <div className="fusion-item-head">
                        <span className="fusion-item-sensor font-medium text-xs">{item.sensor}</span>
                        <span className={`consistency-badge badge-${item.consistency}`}>
                          {item.consistency === "supporting" && <CheckCircle2 size={11} />}
                          {item.consistency === "conflicting" && <AlertTriangle size={11} />}
                          {item.consistency === "inconclusive" && <Info size={11} />}
                          {item.consistency}
                        </span>
                      </div>
                      <p className="fusion-item-desc text-2xs text-muted">{item.description}</p>
                      <div className="fusion-item-meta mono text-2xs">
                        <span>Signature: {item.signature}</span>
                        {item.temporal_offset_hours !== null && (
                          <span> · Δt: {item.temporal_offset_hours > 0 ? `+${item.temporal_offset_hours}h` : `${item.temporal_offset_hours}h`}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AIS Vessel Tracking & Association (Phase 15) */}
            <h3 className="detail-section vessel-section-head">
              <span className="flex items-center gap-1.5">
                <Ship size={16} className="text-blue-400" />
                AIS Vessel Intelligence (Demonstration)
              </span>
              <button
                type="button"
                className="btn btn-xs btn-secondary"
                disabled={correlateMutation.isPending}
                onClick={() => correlateMutation.mutate()}
              >
                <RefreshCw size={11} className={correlateMutation.isPending ? "animate-spin" : ""} />
                {correlateMutation.isPending ? "Correlating..." : "Re-run Demo Correlation"}
              </button>
            </h3>

            <SimulatedBanner detail="DEMONSTRATION DATA: vessels and tracks are seeded synthetic positions, not live AIS. Association scores are proximity heuristics and do not identify a responsible vessel." />

            {vesselsLoading && <p className="text-xs text-muted">Correlating proximate AIS vessel tracks...</p>}

            {vesselAssocs && vesselAssocs.length > 0 ? (
              <div className="vessel-assoc-list">
                {vesselAssocs.map((v) => (
                  <div
                    key={v.id}
                    className={`vessel-assoc-card ${v.is_primary_suspect ? "card-primary-suspect" : ""}`}
                  >
                    <div className="vessel-card-head">
                      <div className="vessel-name-link">
                        <span>{v.vessel_name}</span>
                        <span className="text-2xs text-muted font-normal">({v.vessel_type} · {v.flag_country})</span>
                      </div>
                      {v.is_primary_suspect && (
                        <span className="suspect-chip">Nearest Demo Vessel</span>
                      )}
                    </div>
                    <div className="vessel-card-metrics">
                      <span>CPA: <strong>{v.spatial_distance_km.toFixed(1)} km</strong></span>
                      <span>Δt: <strong>{Math.abs(v.temporal_offset_minutes).toFixed(0)} min</strong></span>
                      <span>Heuristic Score: <strong>{(v.association_score * 100).toFixed(0)}%</strong></span>
                      <span>Type: <strong className="mono">{v.association_type === "SOURCE_SUSPECT" ? "Demo nearest track" : v.association_type === "CO_OCCURRING" ? "Demo regional track" : v.association_type}</strong></span>
                    </div>
                    {v.notes && <p className="text-2xs text-muted mt-1">{v.notes}</p>}
                    <div className="mt-2 flex justify-end">
                      <button
                        type="button"
                        className="btn btn-xs btn-secondary"
                        onClick={() => {
                          setNotes(
                            (prev) =>
                              (prev ? prev + "\n" : "") +
                              `[AIS Demo Association]: ${v.vessel_name} (${v.vessel_type}, MMSI ${v.mmsi}) CPA ${v.spatial_distance_km} km at offset ${v.temporal_offset_minutes} min. Heuristic association score: ${(v.association_score * 100).toFixed(0)}% (not vessel attribution).`
                          );
                        }}
                      >
                        <Sparkles size={11} /> Attach Track to Review
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="optical-empty-card mb-4">
                <div className="empty-content">
                  <Ship size={18} className="text-blue-400 mb-1" />
                  <p className="text-xs font-medium">No synthetic vessel tracks within the 50 km demonstration window.</p>
                  <p className="text-2xs text-muted">
                    No seeded demonstration transponder positions were correlated for this overpass.
                  </p>
                </div>
              </div>
            )}

            {/* Lagrangian Oil Drift Simulation (Phase 16) */}
            <h3 className="detail-section drift-section-head">
              <span className="flex items-center gap-1.5">
                <Compass size={16} className="text-emerald-400" />
                Lagrangian Oil Drift Simulation
              </span>
              {driftData && (
                <span className={`beaching-badge ${driftData.beaching_risk_level.toLowerCase()}`}>
                  {driftData.beaching_risk_level} Simulated Beaching Risk
                </span>
              )}
            </h3>

            <SimulatedBanner detail="SIMULATION: constant default wind and current forcing, a synthetic spill origin, and a particle model. Output is a workflow demonstration, not an operational drift forecast." />

            {driftLoading && <p className="text-xs text-muted">Simulating Lagrangian particle advection & weathering...</p>}

            {driftData && (
              <div className="drift-card">
                <div className="drift-metrics-grid">
                  <div className="drift-metric-item">
                    <span className="d-lbl">Oil Type & Volume</span>
                    <span className="d-val">{driftData.oil_type} ({driftData.spill_volume_m3} m³)</span>
                  </div>
                  <div className="drift-metric-item">
                    <span className="d-lbl">Simulation Duration</span>
                    <span className="d-val">{driftData.duration_hours}h Forward Drift</span>
                  </div>
                  <div className="drift-metric-item">
                    <span className="d-lbl">Simulated Shoreline Contact</span>
                    <span className="d-val">
                      {typeof driftData.time_to_shore_hours === "number"
                        ? `Contact in ${driftData.time_to_shore_hours.toFixed(1)}h`
                        : "No simulated contact"}
                    </span>
                  </div>
                </div>

                <div className="mass-balance-bar-wrap">
                  <div className="flex justify-between text-2xs font-semibold">
                    <span>Weathering Mass Balance</span>
                    <span>{driftData.final_floating_pct}% Remaining on Surface</span>
                  </div>
                  <div className="mass-balance-bar">
                    <div
                      className="mass-seg-floating"
                      style={{ width: `${driftData.final_floating_pct}%` }}
                      title={`Floating: ${driftData.final_floating_pct}%`}
                    />
                    <div
                      className="mass-seg-evap"
                      style={{ width: `${driftData.final_evaporated_pct}%` }}
                      title={`Evaporated: ${driftData.final_evaporated_pct}%`}
                    />
                    <div
                      className="mass-seg-disp"
                      style={{ width: `${driftData.final_dispersed_pct}%` }}
                      title={`Dispersed: ${driftData.final_dispersed_pct}%`}
                    />
                    <div
                      className="mass-seg-beached"
                      style={{ width: `${driftData.final_beached_pct}%` }}
                      title={`Beached: ${driftData.final_beached_pct}%`}
                    />
                  </div>
                  <div className="mass-balance-legend">
                    <span><i className="mass-seg-floating" /> Floating ({driftData.final_floating_pct}%)</span>
                    <span><i className="mass-seg-evap" /> Evaporated ({driftData.final_evaporated_pct}%)</span>
                    <span><i className="mass-seg-disp" /> Dispersed ({driftData.final_dispersed_pct}%)</span>
                    <span><i className="mass-seg-beached" /> Beached ({driftData.final_beached_pct}%)</span>
                  </div>
                </div>

                <div className="mt-2 flex justify-between items-center">
                  <div className="flex gap-1">
                    {[24, 48, 72].map((dur) => (
                      <button
                        key={dur}
                        type="button"
                        className={`btn btn-2xs ${driftData.duration_hours === dur ? 'btn-primary' : 'btn-secondary'}`}
                        disabled={runDriftMutation.isPending}
                        onClick={() => runDriftMutation.mutate(dur)}
                      >
                        {dur}h
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="btn btn-xs btn-secondary"
                    onClick={() => {
                      setNotes(
                        (prev) =>
                          (prev ? prev + "\n" : "") +
                          `[Drift Simulation]: Simulated ${driftData.beaching_risk_level} beaching risk over ${driftData.duration_hours}h (${typeof driftData.time_to_shore_hours === "number" ? `simulated shoreline contact in ${driftData.time_to_shore_hours}h` : 'no simulated contact'}). Mass balance: ${driftData.final_evaporated_pct}% evaporated, ${driftData.final_floating_pct}% floating, ${driftData.final_beached_pct}% beached.`
                      );
                    }}
                  >
                    <Sparkles size={11} /> Attach Drift Risk to Review
                  </button>
                </div>
              </div>
            )}

            {/* Environmental Impact & Receptor Intelligence (Phase 17) */}
            <h3 className="detail-section impact-section-head">
              <span className="flex items-center gap-1.5">
                <ShieldAlert size={16} className="text-rose-400" />
                Environmental Impact Screening (Demonstration)
              </span>
              {impactData && (
                <span className={`impact-severity-badge severity-${impactData.highest_severity.toLowerCase()}`}>
                  {impactData.highest_severity} Exposure ({impactData.max_vulnerability_score.toFixed(0)}/100)
                </span>
              )}
            </h3>

            <SimulatedBanner detail="DEMONSTRATION SCREENING: proximity is measured to nine static receptor points, not PostGIS Marine Protected Area boundaries. The vulnerability score is illustrative and not an operational impact assessment." />

            {impactLoading && <p className="text-xs text-muted">Screening proximity to Marine Protected Areas & critical receptors...</p>}

            {impactData && (
              <div className="impact-box">
                <div className="impact-summary-card">
                  <div className="impact-summary-text">
                    <p className="text-xs font-semibold mb-1">Illustrative Receptor Screening</p>
                    <p className="text-xs text-muted mb-2">{impactData.overall_mitigation_summary}</p>
                    <div className="impact-stat-row">
                      <span>Proximate Receptors: <strong>{impactData.proximate_receptors_count}</strong></span>
                      <span>Max Vulnerability Score: <strong>{impactData.max_vulnerability_score.toFixed(1)} / 100</strong></span>
                      <span>Highest Severity: <strong className={`severity-text-${impactData.highest_severity.toLowerCase()}`}>{impactData.highest_severity}</strong></span>
                    </div>
                  </div>
                  <div className="mt-2 flex justify-between items-center">
                    <button
                      type="button"
                      className="btn btn-2xs btn-secondary"
                      disabled={evaluateImpactMutation.isPending}
                      onClick={() => evaluateImpactMutation.mutate()}
                    >
                      <RefreshCw size={11} className={evaluateImpactMutation.isPending ? "animate-spin" : ""} />
                      {evaluateImpactMutation.isPending ? "Re-evaluating..." : "Re-evaluate Exposure"}
                    </button>
                    {impactData.impacts.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-xs btn-secondary"
                        onClick={() => {
                          const top = impactData.impacts[0];
                          setNotes(
                            (prev) =>
                              (prev ? prev + "\n" : "") +
                              `[Environmental Priority]: Highest severity ${impactData.highest_severity} (Score: ${impactData.max_vulnerability_score}/100). Proximate to ${top.receptor_name} (${top.distance_km} km${top.estimated_arrival_hours ? `, est. arrival ~${top.estimated_arrival_hours}h` : ""}). Priority Action: ${top.priority_action || impactData.overall_mitigation_summary}`
                          );
                        }}
                      >
                        <Sparkles size={11} /> Attach Environmental Priority to Review
                      </button>
                    )}
                  </div>
                </div>

                {impactData.impacts.length > 0 && (
                  <div className="receptor-impact-list">
                    {impactData.impacts.map((imp) => (
                      <div key={imp.id} className={`receptor-card severity-border-${imp.impact_severity.toLowerCase()}`}>
                        <div className="receptor-card-head">
                          <span className="receptor-name font-semibold text-xs">{imp.receptor_name}</span>
                          <span className={`impact-chip chip-${imp.impact_severity.toLowerCase()}`}>
                            {imp.impact_severity}
                          </span>
                        </div>
                        <div className="receptor-card-metrics">
                          <span>Category: <strong>{imp.category.replace(/_/g, " ")}</strong></span>
                          <span>Proximity: <strong>{imp.distance_km.toFixed(1)} km</strong></span>
                          <span>Score: <strong>{imp.vulnerability_score.toFixed(1)} / 100</strong></span>
                          {typeof imp.estimated_arrival_hours === "number" && (
                            <span>Est. Arrival: <strong>~{imp.estimated_arrival_hours.toFixed(1)}h</strong></span>
                          )}
                        </div>
                        {imp.priority_action && (
                          <p className="receptor-action text-2xs mt-1 text-muted">
                            <strong>Action:</strong> {imp.priority_action}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Analyst Review Action Form */}
            <h3 className="detail-section">Analyst Review Action</h3>
            <div className="local-mode-notice">
              <Info size={14} />
              <span>
                <strong>Local Development Mode:</strong> Reviewer identity is self-reported for local audit trail traceability, not an authenticated enterprise SSO session.
              </span>
            </div>
            <form onSubmit={handleSubmit} className="review-form">
              <div className="form-group">
                <label className="form-label" htmlFor="review-decision-select">
                  Review Decision
                </label>
                <select
                  id="review-decision-select"
                  className="form-select"
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                  disabled={reviewMutation.isPending}
                >
                  <option value="potential_oil_slick">
                    Flag as Potential Oil Slick (Candidate Slick)
                  </option>
                  <option value="rejected_lookalike">
                    Reject as Look-alike (Biogenic Film / Wind Shadow)
                  </option>
                  <option value="inconclusive">
                    Inconclusive (Insufficient Radar Contrast)
                  </option>
                  <option value="requires_additional_evidence">
                    Requires Additional Evidence (Sentinel-2 / AIS Corroboration)
                  </option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="reviewer-id-input">
                  Reviewer ID (Local Traceability)
                </label>
                <input
                  id="reviewer-id-input"
                  type="text"
                  className="form-input"
                  value={reviewerId}
                  onChange={(e) => setReviewerId(e.target.value)}
                  placeholder="analyst_local"
                  disabled={reviewMutation.isPending}
                />
                <span className="field-hint">Self-reported identifier for audit log attribution.</span>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="review-notes-textarea">
                  Analyst Justification & Notes
                </label>
                <textarea
                  id="review-notes-textarea"
                  className="form-textarea"
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Record morphological justification, wind threshold notes, or corroborating sensor data..."
                  disabled={reviewMutation.isPending}
                />
              </div>

              <button
                type="submit"
                className="btn btn-primary w-full"
                disabled={reviewMutation.isPending}
              >
                {reviewMutation.isPending ? "Recording Review..." : "Record Decision"}
              </button>

              {submitSuccess && (
                <div className="review-success-badge">
                  <CheckCircle2 size={16} />
                  <span>Review decision saved to audit log successfully</span>
                </div>
              )}
            </form>

            {/* Audit History Timeline */}
            <h3 className="detail-section">
              Audit History ({data.reviews?.length ?? 0})
            </h3>
            {data.reviews && data.reviews.length > 0 ? (
              <div className="audit-timeline">
                {data.reviews.map((rev) => (
                  <div key={rev.review_id} className="audit-item">
                    <div className="audit-item-head">
                      {decisionBadge(rev.decision)}
                      <span className="audit-time mono">{formatDateTime(rev.reviewed_at)}</span>
                    </div>
                    <div className="audit-meta">
                      <span>Reviewer: <strong>{rev.reviewer_id}</strong> (local attribution)</span>
                      <span>Model: <span className="mono">{rev.model_version}</span></span>
                    </div>
                    {rev.notes && <p className="audit-notes">"{rev.notes}"</p>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted-note text-sm">
                No review decisions recorded yet. This candidate is currently awaiting analyst review.
              </p>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

/* -------------------------------------------------------------------------
   Main Candidate Review Dashboard Page
   ------------------------------------------------------------------------- */

export default function CandidateReview() {
  const { candidateId: urlCandidateId } = useParams();
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    urlCandidateId ?? null
  );

  // Filter states
  const [searchTerm, setSearchTerm] = useState("");
  const [screeningFilter, setScreeningFilter] = useState("ALL");
  const [reviewFilter, setReviewFilter] = useState("ALL");
  const [coastalFilter, setCoastalFilter] = useState<string>("ALL");
  const pageSize = 50;
  const [pageOffset, setPageOffset] = useState<number>(0);

  // KPI Summary
  const {
    data: summary,
    isLoading: summaryLoading,
    refetch: refetchSummary,
  } = useQuery({
    queryKey: ["sar-candidate-summary"],
    queryFn: () => api.sarCandidateSummary(),
  });

  // Candidate List Query
  const {
    data: candidateList,
    isLoading: listLoading,
    isError: listError,
    error: listErrorObj,
    refetch: refetchList,
  } = useQuery({
    queryKey: [
      "sar-candidates",
      screeningFilter,
      reviewFilter,
      coastalFilter,
      searchTerm,
      pageSize,
      pageOffset,
    ],
    queryFn: () =>
      api.sarCandidates({
        screening_status: screeningFilter === "ALL" ? null : screeningFilter,
        review_status: reviewFilter === "ALL" ? null : reviewFilter,
        is_coastal:
          coastalFilter === "ALL" ? null : coastalFilter === "coastal",
        search: searchTerm.trim() || null,
        limit: pageSize,
        offset: pageOffset,
      }),
  });

  const candidates = candidateList?.items ?? [];
  const totalCount = candidateList?.count ?? 0;

  const workflowAwaiting = summary?.awaiting_analyst_review ?? 0;
  const workflowReviewed = summary?.reviewed_candidates ?? 0;
  const workflowEligible = summary?.eligible_candidates ?? 0;
  const standardWind = summary?.standard_wind_review ?? summary?.standard_review_candidates ?? 0;
  const lowWind = summary?.low_wind_ambiguity ?? summary?.low_wind_ambiguity_candidates ?? 0;
  const highWind = summary?.high_wind_ambiguity ?? summary?.high_wind_ambiguity_candidates ?? 0;
  const windUnavailable = summary?.wind_unavailable ?? summary?.wind_unavailable_candidates ?? 0;
  const noCandidate =
    summary?.background_non_detections ?? summary?.no_candidate_detected ?? 0;
  const totalSamples =
    summary?.total_evaluated_samples ??
    summary?.total_monitored_samples ??
    summary?.total_candidates ??
    0;
  const workflowCaption = `${workflowAwaiting} awaiting + ${workflowReviewed} reviewed = ${workflowEligible} eligible`;
  const dispositionCaption = `${standardWind} + ${lowWind} + ${highWind} + ${windUnavailable} + ${noCandidate} = ${totalSamples} total`;

  const handleResetFilters = () => {
    setSearchTerm("");
    setScreeningFilter("ALL");
    setReviewFilter("ALL");
    setCoastalFilter("ALL");
    setPageOffset(0);
  };

  return (
    <>
      <PageHeader
        title="SAR Candidate Review Dashboard"
        subtitle="Research replay of a frozen Sentinel-1 SAR audit set, collocated with ERA5 wind context and analyst decision history. Scores are uncalibrated rankings, not validated probabilities."
        actions={
          <div className="header-tags">
            <span className="env-pill">Research Replay</span>
            <span className="env-pill">Experimental V2.2</span>
            <span className="env-pill">ERA5 Collocated</span>
            <span className="env-pill">Local Review Mode</span>
          </div>
        }
      />

      <SimulatedBanner detail="Research replay: this is a frozen historical SAR audit set. Optical, AIS and drift panels are synthetic demonstrations. Model scores are uncalibrated and do not identify a confirmed pollution incident." />

      {/* Workflow & Triage Pipeline (Overlapping Funnel Metrics) */}
      <div className="kpi-group">
        <div className="kpi-group-header">
          <span className="kpi-group-title">Workflow & Review Pipeline</span>
          <span className="kpi-group-caption">Cumulative triage funnel · {workflowCaption}</span>
        </div>
        <div className="metric-grid candidate-kpis candidate-workflow-kpis">
          <MetricCard
            icon={<ShieldAlert size={20} />}
            label="Total Evaluated Samples"
            value={summaryLoading ? "..." : (summary?.total_evaluated_samples ?? summary?.total_monitored_samples ?? summary?.total_candidates ?? 0)}
            detail="Evaluated historical SAR patches"
            tone="neutral"
          />
          <MetricCard
            icon={<CheckCircle2 size={20} />}
            label="Eligible Candidates"
            value={summaryLoading ? "..." : (summary?.eligible_candidates ?? 0)}
            detail="Detections (p_oil ≥ 0.50)"
            tone="warn"
          />
          <MetricCard
            icon={<Clock size={20} />}
            label="Awaiting Review"
            value={summaryLoading ? "..." : (summary?.awaiting_analyst_review ?? 0)}
            detail="Eligible candidates pending review"
            tone="neutral"
          />
          <MetricCard
            icon={<CheckCircle2 size={20} />}
            label="Reviewed Candidates"
            value={summaryLoading ? "..." : (summary?.reviewed_candidates ?? 0)}
            detail="Application-enforced append-only review history"
            tone="ok"
          />
        </div>
      </div>

      {/* Mutually Exclusive Environmental & Sample Disposition */}
      <div className="kpi-group">
        <div className="kpi-group-header">
          <span className="kpi-group-title">Sample Disposition (Mutually Exclusive)</span>
          <span className="kpi-group-caption">Exhaustive accounting · {dispositionCaption}</span>
        </div>
        <div className="metric-grid candidate-kpis candidate-disposition-kpis">
          <MetricCard
            icon={<Wind size={20} />}
            label="Standard Wind Review"
            value={summaryLoading ? "..." : (summary?.standard_wind_review ?? summary?.standard_review_candidates ?? 0)}
            detail="Favorable wind (3.0–12.0 m/s)"
            tone="warn"
          />
          <MetricCard
            icon={<Compass size={20} />}
            label="Low-Wind Ambiguity"
            value={summaryLoading ? "..." : (summary?.low_wind_ambiguity ?? summary?.low_wind_ambiguity_candidates ?? 0)}
            detail="Calm seas (< 3.0 m/s) · Ambiguous"
            tone="info"
          />
          <MetricCard
            icon={<Wind size={20} />}
            label="High-Wind Ambiguity"
            value={summaryLoading ? "..." : (summary?.high_wind_ambiguity ?? summary?.high_wind_ambiguity_candidates ?? 0)}
            detail="Dispersion (> 12.0 m/s) · Ambiguous"
            tone="info"
          />
          <MetricCard
            icon={<AlertTriangle size={20} />}
            label="Wind Unavailable"
            value={summaryLoading ? "..." : (summary?.wind_unavailable ?? summary?.wind_unavailable_candidates ?? 0)}
            detail="Missing ERA5 reanalysis"
            tone="neutral"
          />
          <MetricCard
            icon={<ShieldAlert size={20} />}
            label="Background Non-Detections"
            value={summaryLoading ? "..." : (summary?.background_non_detections ?? summary?.no_candidate_detected ?? 0)}
            detail="Non-candidates (p_oil < 0.50)"
            tone="neutral"
          />
        </div>
      </div>

      {/* Filters and Controls */}
      <SectionCard title="Candidate Filter & Query">
        <div className="candidate-filter-bar">
          <div className="search-box">
            <Search size={16} className="search-icon" />
            <input
              type="text"
              placeholder="Search candidate ID or patch name..."
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setPageOffset(0);
              }}
              className="search-input"
            />
            {searchTerm && (
              <button
                className="search-clear"
                onClick={() => setSearchTerm("")}
                aria-label="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>

          <div className="filter-select-group">
            <select
              value={screeningFilter}
              onChange={(e) => {
                setScreeningFilter(e.target.value);
                setPageOffset(0);
              }}
              className="filter-select"
            >
              {SCREENING_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <select
              value={reviewFilter}
              onChange={(e) => {
                setReviewFilter(e.target.value);
                setPageOffset(0);
              }}
              className="filter-select"
            >
              {REVIEW_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <select
              value={coastalFilter}
              onChange={(e) => {
                setCoastalFilter(e.target.value);
                setPageOffset(0);
              }}
              className="filter-select"
            >
              <option value="ALL">All Environments</option>
              <option value="coastal">Coastal (&lt; 25 km)</option>
              <option value="offshore">Open Offshore</option>
            </select>

            <button
              className="btn btn-secondary btn-sm"
              onClick={handleResetFilters}
              title="Reset all filters"
            >
              <RefreshCw size={14} /> Reset
            </button>
          </div>
        </div>
      </SectionCard>

      {/* Candidate Table */}
      <SectionCard
        title={`Candidates (${totalCount})`}
        description="Filterable list of experimental Sentinel-1 SAR candidates collocated with ERA5 10m wind fields."
        actions={
          <div className="table-actions-row">
            <span className="text-xs text-muted">
              Showing {candidates.length} of {totalCount}
            </span>
          </div>
        }
      >
        {listLoading && <LoadingSkeleton rows={8} height={42} />}
        {listError && (
          <ErrorState
            error={listErrorObj}
            onRetry={() => {
              refetchList();
              refetchSummary();
            }}
          />
        )}

        {!listLoading && !listError && candidates.length === 0 && (
          <EmptyState
            title="No candidates match your filters"
            message="Try broadening your screening status, review status, or text search criteria."
            action={
              <button className="btn btn-secondary btn-sm" onClick={handleResetFilters}>
                Clear Filters
              </button>
            }
          />
        )}

        {!listLoading && !listError && candidates.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Candidate ID</th>
                  <th>Image Patch</th>
                  <th>Location</th>
                  <th>Acquired</th>
                  <th>V2.2 Score</th>
                  <th>ERA5 Wind</th>
                  <th>Screening State</th>
                  <th>Review Decision</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((cand) => {
                  const isSelected = selectedCandidateId === cand.candidate_id;
                  return (
                    <tr
                      key={cand.candidate_id}
                      className={isSelected ? "selected-row" : ""}
                      onClick={() => setSelectedCandidateId(cand.candidate_id)}
                      style={{ cursor: "pointer" }}
                    >
                      <td className="mono font-medium text-xs">
                        {cand.candidate_id}
                      </td>
                      <td className="mono text-xs">{cand.image_name}</td>
                      <td>
                        <div className="location-cell">
                          <span className="mono text-xs">
                            {cand.latitude.toFixed(2)}°, {cand.longitude.toFixed(2)}°
                          </span>
                          {cand.is_coastal && (
                            <span className="coastal-badge">Coastal</span>
                          )}
                        </div>
                      </td>
                      <td className="text-xs text-muted">
                        {formatDateTime(cand.acquisition_timestamp)}
                      </td>
                      <td>
                        <span className="mono font-semibold">
                          {(cand.raw_confidence * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td>
                        <div className="wind-cell">
                          <span
                            className="mono font-medium"
                            style={{ color: windSpeedColor(cand.wind_speed_ms) }}
                          >
                            {cand.wind_speed_ms !== null
                              ? `${cand.wind_speed_ms.toFixed(1)} m/s`
                              : "—"}
                          </span>
                          {cand.wind_direction_deg !== null && (
                            <span className="wind-deg text-muted text-xs">
                              {cand.wind_direction_deg.toFixed(0)}°
                            </span>
                          )}
                        </div>
                      </td>
                      <td>{screeningBadge(cand.screening_status)}</td>
                      <td>{decisionBadge(cand.review_status)}</td>
                      <td>
                        <button
                          className="btn btn-xs btn-primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCandidateId(cand.candidate_id);
                          }}
                        >
                          Inspect <ArrowRight size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination controls */}
        {totalCount > pageSize && (
          <div className="pagination-bar">
            <span className="text-xs text-muted">
              Page {Math.floor(pageOffset / pageSize) + 1} of{" "}
              {Math.ceil(totalCount / pageSize)}
            </span>
            <div className="pagination-btns">
              <button
                className="btn btn-sm btn-secondary"
                disabled={pageOffset === 0}
                onClick={() => setPageOffset(Math.max(0, pageOffset - pageSize))}
              >
                Previous
              </button>
              <button
                className="btn btn-sm btn-secondary"
                disabled={pageOffset + pageSize >= totalCount}
                onClick={() => setPageOffset(pageOffset + pageSize)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </SectionCard>

      {/* Detail & Review Drawer */}
      {selectedCandidateId && (
        <CandidateDetailDrawer
          candidateId={selectedCandidateId}
          onClose={() => setSelectedCandidateId(null)}
        />
      )}
    </>
  );
}
