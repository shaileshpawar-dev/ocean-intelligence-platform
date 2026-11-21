/**
 * Current sea conditions for the monitored regions, from Open-Meteo.
 *
 * Two things this panel is for. The obvious one is context: wind, wave height
 * and sea-surface temperature where the platform is looking.
 *
 * The less obvious one matters more. Below about 3 m/s the sea surface goes
 * flat, and a flat sea in C-band SAR looks like oil. So the count of regions
 * under that threshold is a live statement about how much of today's
 * dark-formation evidence is ambiguous — the caveat the detector carries in
 * the abstract, attached to actual weather.
 *
 * These are model values, not observations. Open-Meteo serves numerical
 * weather prediction output, so the badge says INFERRED and names the
 * provider. An empty cache says so rather than showing a calm sea.
 */

import type { UseQueryResult } from "@tanstack/react-query";
import { Thermometer, Waves, Wind } from "lucide-react";
import type { MarineConditionsResponse } from "@/lib/types";
import { EvidenceBadge, SectionCard, formatDateTime } from "@/components/ui";

/** A number with its unit, or an explicit dash. Never a zero for "unknown". */
function reading(value: number | null, unit: string, places = 1) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  return (
    <>
      {value.toFixed(places)}
      <span className="text-muted"> {unit}</span>
    </>
  );
}

export default function MarineConditionsPanel({
  query,
}: {
  query: UseQueryResult<MarineConditionsResponse>;
}) {
  const data = query.data;
  if (query.isLoading || !data) return null;

  if (!data.available) {
    return (
      <SectionCard
        title="Sea conditions"
        description="No conditions have been fetched."
      >
        <p className="muted-note">{data.detail}</p>
      </SectionCard>
    );
  }

  const totals = data.totals;
  const lowWind = data.items.filter((item) => item.sar_ambiguous);
  // Windiest first: the calm end is the interesting end, so it goes last and
  // is called out in the note below rather than buried mid-table.
  const sorted = [...data.items].sort(
    (a, b) => (b.wind_speed_ms ?? -1) - (a.wind_speed_ms ?? -1),
  );
  const shown = [...sorted.slice(0, 4), ...sorted.slice(-4)];

  return (
    <SectionCard
      title="Sea conditions"
      description={`Open-Meteo, fetched ${formatDateTime(data.fetched_at)}`}
      actions={
        <div className="badge-row">
          <span className="badge-real">
            <Wind size={12} /> Real · Open-Meteo
          </span>
          <EvidenceBadge level="INFERRED" />
        </div>
      }
    >
      {totals && lowWind.length > 0 && (
        <div className="provenance-note" role="note">
          <Wind size={15} />
          <span>
            <strong>
              {totals.low_wind_regions} of {totals.regions} regions are below{" "}
              {totals.low_wind_threshold_ms} m/s right now.
            </strong>{" "}
            A sea that calm goes flat, and a flat sea in C-band SAR looks like
            oil — so any dark formation reported in those regions today is
            ambiguous on the physics, before any model is involved.
          </span>
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Region</th>
              <th>
                <Wind size={12} /> Wind
              </th>
              <th>Gust</th>
              <th>
                <Waves size={12} /> Wave height
              </th>
              <th>Period</th>
              <th>
                <Thermometer size={12} /> SST
              </th>
              <th>SAR legibility</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((item) => (
              <tr
                key={item.cell_code}
                className={item.sar_ambiguous ? "row-caveated" : undefined}
              >
                <td>{item.region_name}</td>
                <td className="mono">{reading(item.wind_speed_ms, "m/s")}</td>
                <td className="mono">{reading(item.wind_gust_ms, "m/s")}</td>
                <td className="mono">{reading(item.wave_height_m, "m", 2)}</td>
                <td className="mono">{reading(item.wave_period_s, "s")}</td>
                <td className="mono">{reading(item.sea_surface_temp_c, "°C")}</td>
                <td>
                  {item.sar_ambiguous === null ? (
                    <span className="text-muted">unknown</span>
                  ) : item.sar_ambiguous ? (
                    <span className="tag tone-warning">low wind — ambiguous</span>
                  ) : (
                    <span className="tag tone-neutral">within range</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted-note">
        Showing the four windiest and four calmest of {data.items.length}{" "}
        regions. {data.provenance.attribution}.
      </p>
    </SectionCard>
  );
}
