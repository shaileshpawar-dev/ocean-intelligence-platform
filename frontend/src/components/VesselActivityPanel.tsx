/**
 * Real vessel activity per region, from Global Fishing Watch.
 *
 * Aggregate figures only — hours and vessel counts by flag state. No vessel
 * identity appears here, and that is a deliberate limit rather than a gap.
 * The detections this platform holds are research benchmark patches and
 * demonstration events, so attaching a real ship to one would name an
 * identifiable vessel as the source of a spill that never happened. "How
 * busy is this water" is the question GFW can answer honestly alongside a
 * dark formation, and it implicates nobody.
 *
 * A region reading "none observed" means GFW answered and saw no apparent
 * fishing effort — not that the request failed. The two are rendered
 * differently for that reason.
 */

import type { UseQueryResult } from "@tanstack/react-query";
import { Ship } from "lucide-react";
import type { VesselActivityResponse } from "@/lib/types";
import { EvidenceBadge, SectionCard } from "@/components/ui";

export default function VesselActivityPanel({
  query,
}: {
  query: UseQueryResult<VesselActivityResponse>;
}) {
  const data = query.data;
  if (query.isLoading || !data || !data.available) return null;

  const { totals, provenance } = data;
  const active = data.items.filter((item) => item.total_hours > 0);
  const quiet = data.items.length - active.length;

  return (
    <SectionCard
      title="Vessel activity"
      description={`AIS-derived apparent fishing effort, ${data.items[0]?.window_from} to ${data.items[0]?.window_to}`}
      actions={
        <div className="badge-row">
          <a
            className="badge-real"
            href={provenance.attribution_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            <Ship size={12} /> {provenance.attribution}
          </a>
          <EvidenceBadge level="INFERRED" />
        </div>
      }
    >
      <div className="metric-grid compact">
        <div className="mini-metric">
          <span className="mini-metric-label">Vessel-hours</span>
          <strong>{totals.total_vessel_hours.toLocaleString()}</strong>
        </div>
        <div className="mini-metric">
          <span className="mini-metric-label">Vessels seen</span>
          <strong>{totals.total_vessels.toLocaleString()}</strong>
        </div>
        <div className="mini-metric">
          <span className="mini-metric-label">Regions with activity</span>
          <strong>
            {totals.regions_with_activity} / {totals.regions_answered}
          </strong>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Region</th>
              <th>Vessel-hours</th>
              <th>Vessels</th>
              <th>Busiest flags</th>
            </tr>
          </thead>
          <tbody>
            {active.slice(0, 8).map((item) => (
              <tr key={item.cell_code}>
                <td>{item.region_name}</td>
                <td className="mono">{item.total_hours.toLocaleString()}</td>
                <td className="mono">{item.vessel_count.toLocaleString()}</td>
                <td>
                  {item.top_flags.map((entry) => (
                    <span key={entry.flag} className="tag tone-neutral">
                      {entry.flag} {Math.round(entry.hours).toLocaleString()}h
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted-note">
        Busiest {Math.min(8, active.length)} of {totals.regions_answered}{" "}
        regions.{" "}
        {quiet > 0 && (
          <>
            {quiet} returned <strong>none observed</strong> — GFW answered and
            saw no effort there.{" "}
          </>
        )}
        {provenance.identity_note}
      </p>
    </SectionCard>
  );
}
