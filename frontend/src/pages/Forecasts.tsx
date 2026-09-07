/**
 * Forecasts.
 *
 * Observed history and forecast are drawn on one axis but never with the same
 * mark: history is a solid line with points, the forecast is dashed inside a
 * shaded prediction interval, and a labelled divider separates them. The
 * `beats_naive` verdict is shown prominently — a model that loses to
 * last-value-carried-forward is reported as such rather than presented as
 * insight.
 */

import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { api } from "@/lib/api";
import {
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
  Unavailable,
  Value,
} from "@/components/ui";

const HORIZONS = [7, 10, 14, 21];
const MODELS = [
  { key: "holt", label: "Holt linear damped" },
  { key: "moving_average", label: "Moving average" },
  { key: "naive", label: "Naive last-value" },
];

export default function Forecasts() {
  const [horizon, setHorizon] = useState(7);
  const [model, setModel] = useState("holt");
  const [region, setRegion] = useState<string | null>(null);

  const trends = useQuery({
    queryKey: ["trends", 60],
    queryFn: () => api.trends(60),
  });

  const regions = useMemo(
    () =>
      (trends.data?.items ?? [])
        .filter((trend) => trend.coverage_days >= 2)
        .sort((a, b) => (b.latest_risk ?? 0) - (a.latest_risk ?? 0)),
    [trends.data],
  );

  const active = region ?? regions[0]?.region_code ?? null;
  const activeTrend = regions.find((trend) => trend.region_code === active);

  const [forecast] = useQueries({
    queries: [
      {
        queryKey: ["forecast", active, horizon, model],
        queryFn: () => api.forecast(active!, horizon, model),
        enabled: Boolean(active),
      },
    ],
  });

  // History and forecast share one x-axis but occupy different series keys, so
  // Recharts cannot accidentally draw them as one continuous line.
  const chart = useMemo(() => {
    if (!activeTrend) return [];
    const history = activeTrend.series
      .filter((point) => point.mean_risk !== null)
      .map((point) => ({
        label: point.date.slice(5),
        observed: point.mean_risk as number,
      }));

    const points = forecast.data?.status === "ok" ? forecast.data.points : [];
    const bridge = history.length
      ? [{ ...history[history.length - 1] }]
      : [];
    const projected = points.map((point) => ({
      label: point.target_date.slice(5),
      forecast: point.value,
      band: [point.lower, point.upper] as [number, number],
    }));

    if (bridge.length && projected.length) {
      // Join the two series so the dashed line starts at the last observation.
      const last = history[history.length - 1];
      return [
        ...history.slice(0, -1),
        { ...last, forecast: last.observed, band: [last.observed, last.observed] },
        ...projected,
      ];
    }
    return [...history, ...projected];
  }, [activeTrend, forecast.data]);

  const divider = activeTrend
    ? activeTrend.series.filter((point) => point.mean_risk !== null).length - 1
    : -1;

  if (trends.isLoading) return <LoadingSkeleton rows={3} height={120} />;
  if (trends.isError)
    return <ErrorState error={trends.error} onRetry={() => trends.refetch()} />;

  if (regions.length === 0) {
    return (
      <>
        <PageHeader title="Forecasts" subtitle="Detection-activity forecasting." />
        <SectionCard>
          <div className="state-block">
            <span className="state-icon neutral">
              <Info size={20} />
            </span>
            <h3>Insufficient history</h3>
            <p>
              No region has enough observed history to fit a forecast. Run
              ingestion cycles over several days to accumulate the daily
              aggregates a time-series model needs.
            </p>
          </div>
        </SectionCard>
      </>
    );
  }

  const beatsNaive = forecast.data?.beats_naive;

  return (
    <>
      <PageHeader
        title="Forecasts"
        subtitle="Forecasts of this platform's own detection activity — not the physical movement of a pollutant."
      />

      <SectionCard padded={false}>
        <div className="toolbar">
          <select
            className="select grow"
            value={active ?? ""}
            onChange={(event) => setRegion(event.target.value)}
            aria-label="Region"
          >
            {regions.map((trend) => (
              <option key={trend.region_code} value={trend.region_code}>
                {trend.region_name} · {trend.coverage_days}d observed
              </option>
            ))}
          </select>
          <select
            className="select"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            aria-label="Model"
          >
            {MODELS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="segmented" role="group" aria-label="Horizon">
            {HORIZONS.map((option) => (
              <button
                key={option}
                className={horizon === option ? "active" : ""}
                onClick={() => setHorizon(option)}
              >
                +{option}d
              </button>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title={activeTrend?.region_name ?? "Forecast"}
        description="Left of the divider is observed. Right is projected."
        actions={
          <div className="badge-row">
            <EvidenceBadge level="OBSERVED" />
            <EvidenceBadge level="FORECAST" />
          </div>
        }
      >
        {forecast.isLoading ? (
          <LoadingSkeleton rows={1} height={280} />
        ) : forecast.isError ? (
          <ErrorState error={forecast.error} />
        ) : forecast.data?.status !== "ok" ? (
          <div className="state-block">
            <span className="state-icon warn">
              <AlertTriangle size={20} />
            </span>
            <h3>No forecast produced</h3>
            <p>{forecast.data?.message ?? "Forecast unavailable for this region."}</p>
            <p className="state-alt">
              The forecaster refuses rather than extrapolating from too few
              points. An explicit refusal is more useful than a curve fitted to
              noise.
            </p>
          </div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart
                data={chart}
                margin={{ top: 8, right: 12, left: -14, bottom: 0 }}
              >
                <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    fontSize: 12,
                    boxShadow: "var(--shadow-md)",
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
                  iconType="plainline"
                />
                {divider > 0 && (
                  <ReferenceLine
                    x={chart[divider]?.label}
                    stroke="var(--text-muted)"
                    strokeDasharray="3 3"
                    label={{
                      value: "now",
                      position: "top",
                      style: { fontSize: 10, fill: "var(--text-muted)" },
                    }}
                  />
                )}
                <Area
                  dataKey="band"
                  name="80% prediction interval"
                  stroke="none"
                  fill="var(--ev-forecast)"
                  fillOpacity={0.16}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="observed"
                  name="Observed"
                  stroke="#0284c7"
                  strokeWidth={2.2}
                  dot={{ r: 2.4, fill: "#0284c7" }}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast"
                  stroke="#0891b2"
                  strokeWidth={2.2}
                  strokeDasharray="6 4"
                  dot={false}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>

            <div
              className={`forecast-verdict ${beatsNaive === false ? "warn" : "ok"}`}
            >
              {beatsNaive === false ? (
                <AlertTriangle size={15} />
              ) : (
                <CheckCircle2 size={15} />
              )}
              <div>
                <strong>{forecast.data.model_name}</strong> · fitted on{" "}
                {forecast.data.n_observations} observations · backtest MAE{" "}
                <Value value={forecast.data.backtest_mae} digits={3} /> vs naive{" "}
                <Value value={forecast.data.naive_mae} digits={3} /> →{" "}
                <strong>
                  {beatsNaive === null
                    ? "no backtest available"
                    : beatsNaive
                      ? "beats the naive baseline"
                      : "does NOT beat the naive baseline"}
                </strong>
                {beatsNaive === false && (
                  <span>
                    {" "}
                    Treat the trend direction as indicative and the point values
                    as weakly supported.
                  </span>
                )}
              </div>
            </div>

            <div className="forecast-bands">
              {forecast.data.bands.map((band) => (
                <div className="band-row" key={band.date}>
                  <span className="band-h">+{band.horizon_days}d</span>
                  <span className="band-date">{band.date}</span>
                  <span className="band-risk">{band.risk.toFixed(1)}</span>
                  <span
                    className="band-sev"
                    style={{
                      color:
                        band.severity === "CRITICAL"
                          ? "var(--sev-critical)"
                          : band.severity === "HIGH"
                            ? "var(--sev-high)"
                            : band.severity === "MEDIUM"
                              ? "var(--sev-medium)"
                              : "var(--sev-low)",
                    }}
                  >
                    {band.severity}
                  </span>
                  <span className="band-range">
                    [{band.lower.toFixed(1)} – {band.upper.toFixed(1)}]
                    {band.severity_lower !== band.severity_upper && (
                      <em>
                        {" "}
                        spans {band.severity_lower}–{band.severity_upper}
                      </em>
                    )}
                  </span>
                </div>
              ))}
            </div>

            <ul className="caveat-list tight">
              {forecast.data.caveats.map((caveat, index) => (
                <li key={index}>{caveat}</li>
              ))}
            </ul>
          </>
        )}
      </SectionCard>

      {activeTrend && (
        <SectionCard title="Observed coverage">
          <div className="coverage-row">
            <div>
              <span className="coverage-label">Observed days</span>
              <strong>
                {activeTrend.coverage_days} / {activeTrend.window_days}
              </strong>
            </div>
            <div className="coverage-bar">
              <span style={{ width: `${activeTrend.coverage_ratio * 100}%` }} />
            </div>
            <div>
              <span className="coverage-label">Coverage ratio</span>
              <strong>{(activeTrend.coverage_ratio * 100).toFixed(0)}%</strong>
            </div>
          </div>
          <p className="muted-note">
            A low coverage ratio means satellite revisit gaps, not calm water.
            Days without an acquisition are forward-filled to build the regular
            daily grid a smoothing model requires.
          </p>
          <div className="kv">
            <span>Trend slope</span>
            <span>
              {activeTrend.slope_per_day !== null ? (
                `${activeTrend.slope_per_day > 0 ? "+" : ""}${activeTrend.slope_per_day.toFixed(3)} risk points/day`
              ) : (
                <Unavailable reason="Fewer than three observed days" />
              )}
            </span>
          </div>
        </SectionCard>
      )}
    </>
  );
}
