/**
 * Water body detail.
 *
 * The page answers, in order: what is this, what do we know, when was it
 * measured, what did it show, how has it changed, and where did every number
 * come from.
 *
 * The two-status treatment is the heart of it. "Current data availability"
 * is answered honestly — for most Indian water bodies the current condition
 * cannot be established, because the source extracts are years old. "Latest
 * measured status" is answered fully, with the date and the reference
 * standard attached. Collapsing the two would either overstate what is known
 * about today or discard a real, checkable finding about the past.
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
import { MapContainer, CircleMarker, GeoJSON, TileLayer, Tooltip } from "react-leaflet";
import type { GeoJsonObject } from "geojson";
import { ArrowLeft, Database, Info, MapPin } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";
import {
  AvailabilityPanel,
  DataQualityPanel,
  ImageryPanel,
  ReferencePanel,
  SourcesPanel,
} from "@/components/waterPanels";
import type { StationSummary, WaterBodyDetail as Detail } from "@/lib/waterTypes";
import {
  LatestAvailableStatus,
  MatchConfidenceNote,
  ParameterCard,
  StatusExplanation,
  WaterTypeTag,
  formatDay,
} from "@/components/water";

const RELATION_LABEL: Record<string, string> = {
  within_geometry: "Inside the outline",
  on_geometry: "On the mapped shape",
  near_geometry: "Near the mapped shape",
  name_match_only: "Named for it, but not near the mapped shape",
  name_match: "Matched by name (no shape to test against)",
};

export default function WaterBodyDetail() {
  const { slug = "" } = useParams();
  const [reference, setReference] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["water-body", slug, reference],
    queryFn: () => api.waterBody(slug, reference),
    enabled: Boolean(slug),
    placeholderData: (previous) => previous,
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
        <SectionCard title="Current data availability">
          <AvailabilityPanel availability={body.availability} />
        </SectionCard>

        <SectionCard title="Latest measured status">
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

      <div className="wb-status-grid">
        <SectionCard
          title="Reference standard"
          description="Which standard the values are compared against, and why."
        >
          <ReferencePanel reference={body.reference} chosen={reference} onChoose={setReference} />
        </SectionCard>
        <SectionCard
          title="Data quality"
          description="From objective metadata only; each factor and the rule are shown."
        >
          <DataQualityPanel quality={body.data_quality} />
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
                  <th>Sampling position</th>
                  <th>Relation to shape</th>
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
                    <td>{station.position_descriptor ?? "—"}</td>
                    <td>
                      {RELATION_LABEL[station.relationship_type ?? "name_match"] ??
                        station.relationship_type}
                      {station.geometry_distance_m != null && station.geometry_distance_m > 0 && (
                        <span className="muted-note">
                          {" "}
                          ({(station.geometry_distance_m / 1000).toFixed(2)} km)
                        </span>
                      )}
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

      {/* -- Map ------------------------------------------------------- */}
      <SectionCard
        title="Map"
        description={
          body.geometry
            ? `Shape from ${body.geometry.provenance.source} (${body.geometry.provenance.confidence} confidence).`
            : body.geometry_status_text ||
              "No shape is available; the point is the mean position of the stations."
        }
      >
        <DetailMap body={body} />
        {body.geometry && (
          <p className="muted-note">
            {body.geometry.provenance.clipped_note} {body.geometry.provenance.licence}. OSM
            elements: {body.geometry.provenance.source_ids.slice(0, 6).join(", ")}
            {body.geometry.provenance.source_ids.length > 6 ? "…" : ""}. Matched{" "}
            {formatDay(body.geometry.provenance.retrieved_at)}.
          </p>
        )}
        {body.latitude != null && body.longitude != null && !body.geometry && (
          <p className="muted-note">
            <MapPin size={12} /> {body.latitude.toFixed(4)}, {body.longitude.toFixed(4)} (station
            mean, not a surveyed centre)
          </p>
        )}
      </SectionCard>

      {/* -- Imagery --------------------------------------------------- */}
      <SectionCard title="Satellite evidence" description="Visual evidence, not measurement.">
        <ImageryPanel images={body.imagery} note={body.imagery_note} />
      </SectionCard>

      {/* -- Sources --------------------------------------------------- */}
      <SectionCard
        title="Sources"
        description="Where every number, shape and label on this page came from."
        actions={<Database size={15} className="text-muted" />}
      >
        <SourcesPanel entries={body.sources_panel} />
      </SectionCard>
    </>
  );
}

/* ------------------------------------------------------------------ */

/** The water body's matched shape, in water blue, with its stations on it. */
function DetailMap({ body }: { body: Detail }) {
  const located = body.stations.filter(
    (s): s is StationSummary & { latitude: number; longitude: number } =>
      s.latitude != null && s.longitude != null,
  );
  const bounds: [[number, number], [number, number]] | null = body.geometry
    ? [
        [body.geometry.bbox[1], body.geometry.bbox[0]],
        [body.geometry.bbox[3], body.geometry.bbox[2]],
      ]
    : located.length > 1
      ? [
          [Math.min(...located.map((s) => s.latitude)), Math.min(...located.map((s) => s.longitude))],
          [Math.max(...located.map((s) => s.latitude)), Math.max(...located.map((s) => s.longitude))],
        ]
      : null;
  const centre: [number, number] | null =
    body.latitude != null && body.longitude != null ? [body.latitude, body.longitude] : null;
  if (!bounds && !centre) {
    return <p className="muted-note">No position is recorded for this water body.</p>;
  }
  const isLine = body.geometry?.geometry_type.includes("Line");
  return (
    <div className="detail-map">
      <MapContainer
        {...(bounds ? { bounds, boundsOptions: { padding: [24, 24] } } : { center: centre!, zoom: 11 })}
        scrollWheelZoom={false}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {body.geometry && (
          <GeoJSON
            data={body.geometry.geometry as unknown as GeoJsonObject}
            style={() =>
              isLine
                ? { color: "#1d6fb8", weight: 4, opacity: 0.95 }
                : { color: "#1d6fb8", weight: 1.5, fillColor: "#3b8fd9", fillOpacity: 0.45 }
            }
          />
        )}
        {!body.geometry && centre && (
          <CircleMarker
            center={centre}
            radius={9}
            pathOptions={{ color: "#ffffff", weight: 2, fillColor: "#0369a1", fillOpacity: 0.9 }}
          />
        )}
        {located.map((s) => (
          <CircleMarker
            key={s.id}
            center={[s.latitude, s.longitude]}
            radius={5}
            pathOptions={{
              color: "#0c4a6e",
              weight: 1.5,
              fillColor: s.relationship_type === "name_match_only" ? "#f59e0b" : "#ffffff",
              fillOpacity: 1,
            }}
          >
            <Tooltip direction="top" offset={[0, -4]}>
              <strong>{s.name}</strong>
              <br />
              {RELATION_LABEL[s.relationship_type ?? "name_match"] ?? s.relationship_type}
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}

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
