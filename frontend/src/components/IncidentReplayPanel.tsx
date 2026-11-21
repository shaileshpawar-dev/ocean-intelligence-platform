/**
 * A documented real incident, replayed through the SAR detector.
 *
 * Screening ordinary water and finding nothing proves very little: a
 * detector that always answered "no" would produce the same output. This
 * takes an incident that is known to have happened — position, date and
 * cargo from an official source — and asks the same pipeline the same
 * question over the satellite passes that followed.
 *
 * The negative result is shown exactly as a positive one would be, with its
 * reasoning. A finding that only reaches the page when it is favourable is
 * not a finding, and the conditions that weaken this particular negative
 * (wind speed, dispersant, revisit gap) are on screen rather than in a
 * footnote.
 */

import type { UseQueryResult } from "@tanstack/react-query";
import { ExternalLink, Ship, Wind } from "lucide-react";
import { api } from "@/lib/api";
import type { IncidentReplayResponse } from "@/lib/types";
import { EvidenceBadge, SectionCard, formatDate } from "@/components/ui";

export default function IncidentReplayPanel({
  query,
}: {
  query: UseQueryResult<IncidentReplayResponse>;
}) {
  const data = query.data;
  if (query.isLoading || !data || !data.available) return null;

  return (
    <>
      {data.items.map((replay) => {
        const { incident, screening } = replay;
        const detected = screening.detected;
        return (
          <SectionCard
            key={incident.imo}
            title={replay.label}
            description={`${incident.position_text} · ${incident.distance_text}`}
            actions={
              <div className="badge-row">
                <span className={detected ? "badge-real" : "badge-ai"}>
                  <Ship size={12} /> {replay.verdict}
                </span>
                <EvidenceBadge level="DETECTED" />
              </div>
            }
          >
            <div className="replay-body">
              {replay.thumbnail && (
                <figure className="replay-figure">
                  <img
                    src={api.incidentReplayThumbnailUrl(replay.thumbnail)}
                    alt={`Sentinel-1 VV backscatter over the ${incident.name} position`}
                    loading="lazy"
                  />
                  <figcaption>
                    Sentinel-1 VV, {screening.window}. The tile the detector
                    actually saw.
                  </figcaption>
                </figure>
              )}

              <div className="replay-detail">
                <p>
                  <strong>{incident.name}</strong> (IMO {incident.imo},{" "}
                  {incident.flag}) sank on {formatDate(incident.sank_at)} carrying{" "}
                  {incident.cargo_text}.
                </p>

                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Pass</th>
                        <th>After</th>
                        <th>Tiles</th>
                        <th>Max p(oil)</th>
                        <th>
                          <Wind size={12} /> Wind
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {screening.passes.map((pass) => (
                        <tr key={pass.day}>
                          <td>{formatDate(pass.day)}</td>
                          <td className="mono">+{pass.days_after}d</td>
                          <td className="mono">{pass.tiles}</td>
                          <td className="mono">{pass.max_p_oil.toFixed(4)}</td>
                          <td className="mono">
                            {pass.wind_speed_ms === null
                              ? "—"
                              : `${pass.wind_speed_ms.toFixed(1)} m/s`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p className="provenance-note" role="note">
                  <span>
                    <strong>{replay.verdict}.</strong> {replay.interpretation}
                  </span>
                </p>

                <p className="muted-note">
                  {screening.tiles_screened} tiles through{" "}
                  <strong>{screening.model}</strong>. Prepared tile brightness{" "}
                  {screening.prepared_tile_mean ?? "—"} against the training
                  patches&rsquo; {screening.training_tile_mean} — the model is
                  still being applied outside the distribution its accuracy was
                  measured on.
                </p>

                <p className="muted-note">
                  <ExternalLink size={11} aria-hidden /> Source:{" "}
                  {incident.citation}
                </p>
              </div>
            </div>
          </SectionCard>
        );
      })}
    </>
  );
}
