/**
 * Real Satellite Observations.
 *
 * The one marine page whose numbers are measurements. Every row came from a
 * Sentinel-2 acquisition on the date it names, computed by Copernicus over
 * the pixels its scene classification layer marks as water.
 *
 * Two things this page is careful about:
 *
 * A reading computed from a handful of water pixels is marked rather than
 * printed plainly. The cell was under cloud or mostly land on that pass, and
 * an index over eight pixels is arithmetically valid and meaningless.
 *
 * FDI is called "possible floating material" and never "plastic". The index
 * responds to anything floating and brighter than water in the near-infrared
 * -- seaweed, foam, timber, spume, sun glint. Biermann's own paper needs
 * further spectral analysis to tell those apart. The word does not appear on
 * this page, in any state.
 */

import { useQuery } from "@tanstack/react-query";
import { Info, Satellite, Waves } from "lucide-react";
import { api } from "@/lib/api";
import IncidentReplayPanel from "@/components/IncidentReplayPanel";
import {
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  MetricCard,
  PageHeader,
  ProvenanceNote,
  SectionCard,
  formatDate,
} from "@/components/ui";

/** Fixed-width signed number, so a column of them reads as a column. */
function signed(value: number, places: number) {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}`;
}

export default function OpticalObservations() {
  const indices = useQuery({
    queryKey: ["optical-indices"],
    queryFn: () => api.opticalIndices(),
  });
  // A documented incident put through the same detector. Validation
  // evidence for the SAR side, shown here because this is the page about
  // what the platform has actually measured.
  const replay = useQuery({
    queryKey: ["incident-replay"],
    queryFn: () => api.incidentReplay(),
  });

  if (indices.isLoading) return <LoadingSkeleton rows={5} height={90} />;
  if (indices.isError)
    return <ErrorState error={indices.error} onRetry={() => indices.refetch()} />;

  const data = indices.data;
  if (!data) return null;
  const { items, totals, provenance, indices: notes } = data;
  const lowWater = items.filter((item) => !item.characterises_region);
  const crossChecked = items.filter((item) => item.chlorophyll_cross_check).length;

  return (
    <>
      <PageHeader
        title="Real Satellite Observations"
        subtitle="Sentinel-2 water-quality indices, measured over Indian coastal waters."
        actions={
          <span className="badge-real">
            <Satellite size={12} /> Real · Sentinel-2
          </span>
        }
      />

      <ProvenanceNote>
        <strong>These are measurements.</strong> {provenance.note}{" "}
        <em>{provenance.attribution}</em>
      </ProvenanceNote>

      <div className="metric-grid">
        <MetricCard
          icon={<Satellite size={15} />}
          label="Readings stored"
          value={totals.readings_stored}
          detail={`newest ${formatDate(totals.newest_acquisition)}`}
        />
        <MetricCard
          icon={<Waves size={15} />}
          label="Regions with data"
          value={`${totals.regions_with_data} / ${totals.regions_total}`}
          detail="the rest had no clear acquisition"
        />
        <MetricCard
          icon={<Info size={15} />}
          label="Evidence level"
          value="OBSERVED"
          detail="not simulated, not inferred"
        />
      </div>

      <IncidentReplayPanel query={replay} />

      <SectionCard
        title="Latest acquisition per region"
        description="One row per region: its most recent Sentinel-2 pass that cleared the cloud limit."
        actions={<EvidenceBadge level="OBSERVED" />}
      >
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Region</th>
                <th>Scene</th>
                <th>Acquired</th>
                <th>NDCI</th>
                <th>Chl-a (CMEMS)</th>
                <th>NDTI</th>
                <th>FDI</th>
                <th>Water in frame</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={`${item.region_code}-${item.observed_on}`}
                  className={item.characterises_region ? undefined : "row-caveated"}
                >
                  <td>{item.region_name}</td>
                  <td>
                    {/* The scene the numbers came from. Rendered only when
                        the API says one is cached: a missing scene shows
                        nothing rather than a stock image, and asking for one
                        that is not there just to catch the 404 would fill
                        the console with failures that are not errors. */}
                    {item.has_thumbnail ? (
                      <img
                        className="scene-thumb"
                        src={api.opticalThumbnailUrl(
                          item.region_code,
                          item.observed_on,
                        )}
                        alt={`Sentinel-2 true colour, ${item.region_name}, ${item.observed_on}`}
                        loading="lazy"
                      />
                    ) : (
                      <span className="text-muted" title="No cached scene image">
                        —
                      </span>
                    )}
                  </td>
                  <td>{formatDate(item.observed_on)}</td>
                  <td className="mono">
                    {item.characterises_region ? signed(item.ndci_mean, 3) : "—"}
                  </td>
                  {/* The cross-check, not a second opinion we reconcile.
                      NDCI is computed here from raw reflectance; this is a
                      validated multi-sensor product. Shown side by side so a
                      disagreement is visible rather than averaged away. */}
                  <td className="mono">
                    {item.chlorophyll_cross_check ? (
                      <span
                        title={`${item.chlorophyll_cross_check.product}, valid ${item.chlorophyll_cross_check.valid_on}`}
                      >
                        {item.chlorophyll_cross_check.chl_mg_m3.toFixed(2)}
                        <span className="text-muted"> mg/m³</span>
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="mono">
                    {item.characterises_region ? signed(item.ndti_mean, 3) : "—"}
                  </td>
                  <td className="mono">
                    {item.characterises_region ? signed(item.fdi_mean, 4) : "—"}
                  </td>
                  <td className="mono">
                    {(item.water_fraction * 100).toFixed(0)}%
                    <span className="text-muted">
                      {" "}
                      ({item.water_pixels.toLocaleString()} px)
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {lowWater.length > 0 && (
          <ProvenanceNote>
            <strong>
              {lowWater.length} region{lowWater.length === 1 ? "" : "s"} shown
              without values.
            </strong>{" "}
            Fewer than {totals.min_water_pixels} water pixels were in frame on
            that pass — the cell was almost entirely land or cloud. The
            acquisition is recorded, but an index over that little sea does not
            describe the region, so no number is printed for it.
          </ProvenanceNote>
        )}
      </SectionCard>

      {crossChecked > 0 && (
        <ProvenanceNote>
          <strong>
            Chlorophyll is shown twice, on purpose, for {crossChecked} of{" "}
            {items.length} regions.
          </strong>{" "}
          NDCI is a two-band ratio this platform computes from raw Sentinel-2
          reflectance. The Chl-a column is Copernicus Marine's validated,
          atmospherically-corrected multi-sensor retrieval of the same
          quantity. Neither is adjusted to agree with the other: where they
          track together the NDCI reading is worth more, and where they
          diverge that is the useful part.
        </ProvenanceNote>
      )}

      <SectionCard
        title="What these indices measure"
        description="Each is a published band ratio. None of them is a pollutant concentration."
      >
        <dl className="report-dl">
          {(["ndci", "ndti", "fdi"] as const).map((key) => (
            <div key={key}>
              <dt>
                {notes[key].name}{" "}
                <span className="text-muted mono">{notes[key].formula}</span>
              </dt>
              <dd>
                {notes[key].means}{" "}
                <span className="text-muted">{notes[key].reference}</span>
              </dd>
            </div>
          ))}
        </dl>
      </SectionCard>
    </>
  );
}
