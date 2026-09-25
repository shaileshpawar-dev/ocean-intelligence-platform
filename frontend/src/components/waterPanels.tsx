/**
 * Phase 2 evidence panels: availability, data quality, reference, sources,
 * imagery. Each renders only what the API returned; none computes a value.
 */

import { CalendarClock, ExternalLink, Image as ImageIcon, Info, Scale } from "lucide-react";
import type {
  Availability,
  DataQuality,
  DataQualityLevel,
  ReferenceSelection,
  SourcePanelEntry,
  WaterImageEvidence,
} from "@/lib/waterTypes";
import { WaterEvidenceBadge, formatDay } from "@/components/water";

/**
 * LATEST MEASURED STATUS and CURRENT DATA AVAILABILITY, kept apart: the first
 * is a dated fact, the second says whether anything can be said about today.
 */
export function AvailabilityPanel({ availability }: { availability: Availability }) {
  const current = availability.describes_present_state;
  return (
    <div className={`availability ${current ? "availability-ok" : "availability-stale"}`}>
      <p className="availability-row">
        <span className="availability-label">Latest available observation</span>
        <strong>
          <CalendarClock size={13} aria-hidden />{" "}
          {formatDay(availability.latest_available_observation)}
        </strong>
      </p>
      <p className="availability-row">
        <span className="availability-label">Current condition</span>
        <strong>{availability.current_condition}</strong>
      </p>
      {availability.newest_source && (
        <p className="availability-row">
          <span className="availability-label">Newest source</span>
          <strong>
            {availability.newest_source.name} ·{" "}
            {formatDay(availability.newest_source.latest_observed_at)}
          </strong>
        </p>
      )}
      {availability.older_sources?.length > 0 && (
        <p className="muted-note">
          Also measured by{" "}
          {availability.older_sources
            .map((s) => `${s.name} (to ${formatDay(s.latest_observed_at)})`)
            .join(", ")}
          . Sources are kept separate; their values are never combined.
        </p>
      )}
      {availability.summary && <p className="muted-note">{availability.summary}</p>}
    </div>
  );
}

const QUALITY_TONE: Record<DataQualityLevel, string> = {
  HIGH: "ok",
  MODERATE: "warn",
  LIMITED: "bad",
  INSUFFICIENT: "unknown",
};

export function DataQualityBadge({ level }: { level: DataQualityLevel }) {
  return (
    <span className={`dq dq-${QUALITY_TONE[level]}`} title="Data quality, from objective metadata">
      Data quality: {level.charAt(0) + level.slice(1).toLowerCase()}
    </span>
  );
}

export function DataQualityPanel({ quality }: { quality: DataQuality }) {
  return (
    <div className="dq-panel">
      <DataQualityBadge level={quality.level} />
      <ul className="dq-factors">
        {quality.factors.map((f) => (
          <li key={f.factor} className={f.meets ? "dq-meets" : "dq-misses"}>
            <span aria-hidden>{f.meets ? "✓" : "✕"}</span>
            <span>
              <strong>{f.factor}:</strong> {String(f.value)}
              <span className="muted-note"> — {f.rule}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="muted-note">
        {quality.rule} Excludes: {quality.excludes}
      </p>
    </div>
  );
}

export function ReferencePanel({
  reference,
  onChoose,
  chosen,
}: {
  reference: ReferenceSelection;
  onChoose?: (value: string | null) => void;
  chosen?: string | null;
}) {
  return (
    <div className="reference-panel">
      <div className="reference-head">
        <Scale size={14} aria-hidden />
        {reference.standard_name ? (
          <span>
            <strong>{reference.standard_name}</strong>{" "}
            <span className="mono muted-note">{reference.standard_code}</span>
          </span>
        ) : (
          <strong>Reference comparison unavailable</strong>
        )}
      </div>
      <p className="muted-note">
        <Info size={12} aria-hidden /> {reference.basis_label}. {reference.reason}
      </p>
      {reference.source_url && (
        <p className="reference-source">
          {reference.legal_basis}{" "}
          <a href={reference.source_url} target="_blank" rel="noreferrer noopener">
            Source <ExternalLink size={11} aria-hidden />
          </a>
        </p>
      )}
      {onChoose && (
        <label className="reference-choose">
          Compare against a designated use instead:{" "}
          <select
            value={chosen ?? ""}
            onChange={(e) => onChoose(e.target.value || null)}
            aria-label="Choose a reference standard"
          >
            <option value="">Platform selection</option>
            <option value="A">Class A — drinking without treatment</option>
            <option value="B">Class B — outdoor bathing</option>
            <option value="C">Class C — drinking after treatment</option>
            <option value="D">Class D — wildlife and fisheries</option>
            <option value="E">Class E — irrigation, industrial</option>
          </select>
        </label>
      )}
    </div>
  );
}

export function SourcesPanel({ entries }: { entries: SourcePanelEntry[] }) {
  if (!entries.length) return <p className="muted-note">No sources recorded.</p>;
  return (
    <table className="data-table sources-table">
      <thead>
        <tr>
          <th>Role</th>
          <th>Source</th>
          <th>Licence</th>
          <th>Data date</th>
          <th>Retrieved</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={`${e.role}-${e.name}`}>
            <td>{e.role}</td>
            <td>
              {e.url ? (
                <a href={e.url} target="_blank" rel="noreferrer noopener">
                  {e.name}
                </a>
              ) : (
                e.name
              )}
              {e.organisation && <span className="muted-note"> · {e.organisation}</span>}
            </td>
            <td className="muted-note">{e.licence ?? "—"}</td>
            <td>{e.latest == null ? "—" : typeof e.latest === "number" ? e.latest : formatDay(e.latest)}</td>
            <td>{e.retrieved_at ? formatDay(e.retrieved_at) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Satellite scenes as visual evidence. The proxy, where present, is printed
 * with its label, "no unit" and its caveat — never beside a laboratory value
 * as if comparable.
 */
export function ImageryPanel({ images, note }: { images: WaterImageEvidence[]; note: string }) {
  if (!images.length) {
    return (
      <p className="muted-note">
        <ImageIcon size={13} aria-hidden /> No satellite scene has been retrieved for this
        water body. Scenes are only attempted for lakes and reservoirs with a matched
        outline, and only kept when the water itself was clear of cloud.
      </p>
    );
  }
  return (
    <div className="imagery">
      <p className="muted-note">{note}</p>
      {images.map((img) => (
        <figure key={img.image_id} className="imagery-item">
          {img.thumbnail_url && (
            <a href={img.full_image_url ?? img.thumbnail_url} target="_blank" rel="noreferrer noopener">
              <img
                src={img.thumbnail_url}
                alt={`${img.sensor ?? "Satellite"} true-colour scene, ${img.acquisition_date ?? ""}`}
                loading="lazy"
                width={256}
              />
            </a>
          )}
          <figcaption>
            <WaterEvidenceBadge type="SATELLITE_OBSERVED" /> {img.sensor} ·{" "}
            {formatDay(img.acquisition_date)} · water {Math.round((img.water_fraction ?? 0) * 100)}%
            of outline, cloud {Math.round((img.cloud_fraction ?? 0) * 100)}%
            {img.proxy && (
              <span className="imagery-proxy">
                {img.proxy.label}: <strong>{img.proxy.median.toFixed(3)}</strong> (index, no unit).{" "}
                {img.proxy.caveat}
              </span>
            )}
            <span className="muted-note">
              {img.source} via {img.provider}. {img.licence}
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
