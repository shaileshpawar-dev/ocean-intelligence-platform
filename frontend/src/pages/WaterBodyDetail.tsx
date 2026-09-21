/**
 * Water body detail.
 *
 * The page answers, in order: what is this, what do we know, when was it
 * measured, what did it show, how has it changed, and where did every number
 * come from.
 *
 * The two-status treatment is the heart of it. "Right now" is answered
 * honestly — for most Indian water bodies that means "no recent data",
 * because the newest CPCB publication is from 2021. "When last measured" is
 * answered fully, with the date attached to every claim. Collapsing the two
 * would either overstate what is known about today or discard a real,
 * checkable finding about the past.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MapContainer, CircleMarker, TileLayer } from "react-leaflet";
import { ArrowLeft, Database, ExternalLink, Info, MapPin } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import {
  FreshnessNote,
  LatestAvailableStatus,
  MatchConfidenceNote,
  ParameterCard,
  StatusExplanation,
  WaterStatusBadge,
  WaterTypeTag,
  formatDay,
} from "@/components/water";

export default function WaterBodyDetail() {
  const { slug = "" } = useParams();

  const detail = useQuery({
    queryKey: ["water-body", slug],
    queryFn: () => api.waterBody(slug),
    enabled: Boolean(slug),
  });

  if (detail.isLoading) {
    return <LoadingSkeleton rows={5} height={90} />;
  }

  if (detail.isError) {
    return (
      <ErrorState
        error={detail.error}
        onRetry={() => detail.refetch()}
        emptyTitle="Water body not found"
        emptyHint="No water body with this identifier exists in the ingested data."
      />
    );
  }

  const body = detail.data;
  if (!body) return null;

  const byFamily = {
    biological: body.parameters.filter((p) => p.family === "biological"),
    chemical: body.parameters.filter((p) => p.family === "chemical"),
    physical: body.parameters.filter((p) => p.family === "physical"),
  };

  return (
    <>
      <PageHeader
        title={body.name}
        subtitle={
          [body.district, body.state].filter(Boolean).join(", ") ||
          "Location not stated by the source"
        }
        actions={
          <Link className="btn btn-outline btn-sm" to="/app/map">
            <ArrowLeft size={13} /> Back to map
          </Link>
        }
      />

      <div className="wb-tags">
        <WaterTypeTag type={body.water_type} />
        {body.basin && <span className="chip">Basin: {body.basin}</span>}
        <span className="chip">{body.station_count} stations</span>
        <span className="chip">
          {body.observation_count.toLocaleString()} observations
        </span>
      </div>

      <MatchConfidenceNote
        confidence={body.match_confidence}
        method={body.match_method}
      />

      {/* -- Status ---------------------------------------------------- */}
      <div className="wb-status-grid">
        <SectionCard title="Right now">
          <WaterStatusBadge status={body.status_detail.status} />
          <FreshnessNote detail={body.status_detail} />
        </SectionCard>

        <SectionCard title="When last measured">
          {body.latest_available_status ? (
            <LatestAvailableStatus
              detail={body.latest_available_status}
              observedAt={body.latest_observed_at}
            />
          ) : (
            <p className="muted-note">
              No measurement has ever been recorded for this water body.
            </p>
          )}
        </SectionCard>
      </div>

      {/* -- Why this status ------------------------------------------- */}
      <SectionCard
        title="Why this status?"
        description="Every band is reached by a stated rule over named parameters against a cited standard."
      >
        <StatusExplanation
          detail={body.latest_available_status ?? body.status_detail}
        />
      </SectionCard>

      {/* -- Parameters ------------------------------------------------ */}
      <SectionCard
        title="Water quality"
        description="Latest value for every parameter actually measured. Parameters nobody sampled are listed as not measured rather than shown as zero."
      >
        {body.parameters.length === 0 ? (
          <p className="muted-note">
            No parameter values are recorded for this water body.
          </p>
        ) : (
          <>
            {(["biological", "chemical", "physical"] as const).map((family) =>
              byFamily[family].length ? (
                <div key={family} className="param-family">
                  <h3 className="param-family-title">{family}</h3>
                  <div className="param-grid">
                    {byFamily[family].map((reading) => (
                      <ParameterCard key={reading.parameter} reading={reading} />
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </>
        )}
      </SectionCard>

      {/* -- Trend ----------------------------------------------------- */}
      <TrendSection slug={slug} />

      {/* -- Stations -------------------------------------------------- */}
      <SectionCard title={`Monitoring stations (${body.stations.length})`}>
        {body.stations.length === 0 ? (
          <p className="muted-note">No stations are linked to this water body.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Station</th>
                  <th>District</th>
                  <th className="num">Observations</th>
                  <th>Latest</th>
                </tr>
              </thead>
              <tbody>
                {body.stations.map((station) => (
                  <tr key={station.id}>
                    <td>
                      <Link to={`/app/stations/${station.id}`}>{station.name}</Link>
                    </td>
                    <td>{station.district ?? "—"}</td>
                    <td className="num">{station.observation_count}</td>
                    <td>{formatDay(station.latest_observed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* -- Location -------------------------------------------------- */}
      {body.latitude != null && body.longitude != null && (
        <SectionCard
          title="Location"
          description="Centroid is the mean position of this water body's monitoring stations, not a surveyed centre."
        >
          <div className="wb-map">
            <MapContainer
              center={[body.latitude, body.longitude]}
              zoom={11}
              scrollWheelZoom={false}
              style={{ height: 280, borderRadius: 12 }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <CircleMarker
                center={[body.latitude, body.longitude]}
                radius={9}
                pathOptions={{
                  color: "#ffffff",
                  weight: 2,
                  fillColor: "#0369a1",
                  fillOpacity: 0.9,
                }}
              />
              {body.stations
                .filter((s) => s.latitude != null && s.longitude != null)
                .map((s) => (
                  <CircleMarker
                    key={s.id}
                    center={[s.latitude as number, s.longitude as number]}
                    radius={4}
                    pathOptions={{
                      color: "#1e40af",
                      weight: 1,
                      fillColor: "#60a5fa",
                      fillOpacity: 0.9,
                    }}
                  />
                ))}
            </MapContainer>
          </div>
          <p className="muted-note">
            <MapPin size={12} /> {body.latitude.toFixed(4)},{" "}
            {body.longitude.toFixed(4)}
          </p>
        </SectionCard>
      )}

      {/* -- Sources --------------------------------------------------- */}
      <SectionCard
        title="Sources"
        description="Where every number on this page came from."
        actions={<Database size={15} className="text-muted" />}
      >
        {body.sources.map((source) => (
          <div className="source-card" key={source.key}>
            <div className="source-head">
              <strong>{source.name}</strong>
              {source.url && (
                <a href={source.url} target="_blank" rel="noreferrer noopener">
                  Open dataset <ExternalLink size={11} />
                </a>
              )}
            </div>
            <dl className="source-facts">
              <div>
                <dt>Organisation</dt>
                <dd>{source.organisation}</dd>
              </div>
              <div>
                <dt>Dataset</dt>
                <dd>{source.dataset ?? "—"}</dd>
              </div>
              <div>
                <dt>Licence</dt>
                <dd>{source.licence ?? "—"}</dd>
              </div>
              <div>
                <dt>Expected cadence</dt>
                <dd>{source.expected_cadence}</dd>
              </div>
              <div>
                <dt>Observations</dt>
                <dd>{source.observation_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Latest observation</dt>
                <dd>{formatDay(source.latest_observed_at)}</dd>
              </div>
              <div>
                <dt>Retrieved by this platform</dt>
                <dd>{formatDay(source.retrieved_at)}</dd>
              </div>
            </dl>
          </div>
        ))}
      </SectionCard>
    </>
  );
}

/* ------------------------------------------------------------------ */

/** A gap longer than this between samples is drawn as a break, not a line. */
const GAP_MS = 120 * 86_400_000;

/**
 * Insert a null point wherever monitoring stopped for longer than GAP_MS.
 *
 * Without this the line runs straight across a two-year silence, drawing a
 * trajectory nobody measured. With `connectNulls={false}` the null splits the
 * line, so the gap stays visibly empty.
 */
function withGaps(
  points: { observed_at: string; value: number }[],
): { t: number; value: number | null }[] {
  const out: { t: number; value: number | null }[] = [];
  let previous: number | null = null;
  for (const point of points) {
    const t = new Date(point.observed_at).getTime();
    if (previous !== null && t - previous > GAP_MS) {
      out.push({ t: previous + (t - previous) / 2, value: null });
    }
    out.push({ t, value: point.value });
    previous = t;
  }
  return out;
}

/**
 * Historical trend.
 *
 * Only parameters with at least two observations are offered. A single point
 * is not a trend, and drawing a flat line through one value would imply a
 * stability nobody measured.
 */
function TrendSection({ slug }: { slug: string }) {
  const available = useQuery({
    queryKey: ["water-params", slug],
    queryFn: () => api.waterBodyParameters(slug),
  });

  const plottable = (available.data?.items ?? []).filter((p) => p.plottable);
  const [parameter, setParameter] = useState<string | null>(null);
  const active = parameter ?? plottable[0]?.parameter ?? null;

  const trend = useQuery({
    queryKey: ["water-trend", slug, active],
    queryFn: () => api.waterTrend(slug, active as string),
    enabled: Boolean(active),
  });

  if (available.isLoading) {
    return (
      <SectionCard title="Historical trend">
        <LoadingSkeleton rows={2} height={40} />
      </SectionCard>
    );
  }

  if (plottable.length === 0) {
    return (
      <SectionCard title="Historical trend">
        <p className="muted-note">
          <Info size={13} /> No parameter on this water body has more than one
          observation, so no trend can be drawn. This is a gap in the source
          data, not a period of stability.
        </p>
      </SectionCard>
    );
  }

  const series = trend.data;
  const limit = series?.points.length
    ? undefined
    : undefined;

  return (
    <SectionCard
      title="Historical trend"
      description="Observed values only. Gaps are left as gaps — no interpolation."
      actions={
        <select
          value={active ?? ""}
          onChange={(e) => setParameter(e.target.value)}
          aria-label="Choose parameter to plot"
          className="trend-select"
        >
          {plottable.map((p) => (
            <option key={p.parameter} value={p.parameter}>
              {p.label} ({p.point_count})
            </option>
          ))}
        </select>
      }
    >
      {trend.isLoading && <LoadingSkeleton rows={1} height={220} />}

      {series && series.points.length > 0 && (
        <>
          <div className="trend-chart">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={withGaps(series.points)}
              >
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  tickFormatter={(t) =>
                    new Date(t).toLocaleDateString(undefined, {
                      month: "short",
                      year: "2-digit",
                    })
                  }
                  fontSize={11}
                />
                <YAxis
                  fontSize={11}
                  label={{
                    value: series.unit ?? "",
                    angle: -90,
                    position: "insideLeft",
                    fontSize: 11,
                  }}
                />
                <RTooltip
                  labelFormatter={(t) => formatDay(new Date(Number(t)).toISOString())}
                  formatter={(value: number) => [
                    `${value} ${series.unit ?? ""}`,
                    series.label,
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#0369a1"
                  strokeWidth={2}
                  dot={{ r: 2.5 }}
                  connectNulls={false}
                />
                {limit !== undefined && (
                  <ReferenceLine y={limit} stroke="#e02424" strokeDasharray="4 4" />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <dl className="trend-facts">
            <div>
              <dt>Observations</dt>
              <dd>{series.point_count}</dd>
            </div>
            <div>
              <dt>Range</dt>
              <dd>
                {series.min} – {series.max} {series.unit}
              </dd>
            </div>
            <div>
              <dt>Mean</dt>
              <dd>
                {series.mean} {series.unit}
              </dd>
            </div>
            <div>
              <dt>Covers</dt>
              <dd>
                {formatDay(series.first_observed_at)} –{" "}
                {formatDay(series.last_observed_at)}
              </dd>
            </div>
          </dl>
        </>
      )}

      {series && series.points.length === 0 && (
        <p className="muted-note">
          No values recorded for {series.label} on this water body.
        </p>
      )}
    </SectionCard>
  );
}
