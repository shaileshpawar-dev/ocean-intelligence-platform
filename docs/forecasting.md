# Forecasting

## Scope: what is being forecast

The platform forecasts **detection activity** — the trend in its own risk
scores and event counts for a region. `ForecastKind.DETECTION_ACTIVITY` is
stamped on every response.

It does **not** forecast physical pollutant dispersion. That distinction is
the single most important thing in this document, so it gets its own section.

### Why not dispersion

Predicting where a slick will drift requires, at minimum:

| Input | Source | Do we have it? |
|---|---|---|
| Surface currents | HYCOM, CMEMS, OSCAR | No |
| Wind fields (10 m) | ERA5, ASCAT, GFS | No |
| Wave spectra | WaveWatch III | No |
| Oil type and API gravity | Incident reporting | No |
| Weathering state | Time-since-release + type | No |
| Initial slick geometry | Full-resolution segmentation | No |

Those feed a Lagrangian particle-transport model — GNOME (NOAA), OpenDrift
(MET Norway), or MEDSLIK-II. The physics is advection plus diffusion plus a
weathering model for evaporation, emulsification and dispersion.

The predecessor's `/predict-spread` endpoint returned this:

```python
{"model": "LSTM-mock", "predictions": [
    {"hours_ahead": 24, "zones": [
        {"class": "oil_spill", "lat": 13.1, "lon": 55.9, "spread_km2": 42.5}]}]}
```

Hardcoded constants, labelled as an LSTM, with a physical unit attached. A
number with a unit but no model behind it is worse than no number, because a
reader assumes the unit implies a measurement.

That endpoint is gone. `ForecastKind.PHYSICAL_DISPERSION` exists in the enum
solely so the boundary is nameable; nothing returns it.

### What activity forecasting is actually good for

A legitimate operational question: *"is this region getting worse?"* If a
region's mean risk has climbed over three weeks, that is worth an analyst's
attention regardless of whether any individual detection is confirmed. It is
a monitoring signal, not a physical prediction.

The honest caveat, which the API attaches: if satellite coverage changes or a
detection threshold is tuned, the forecast moves without anything changing in
the water. It forecasts *the platform's behaviour*, which correlates with —
but is not — the state of the ocean.

## Model progression

Deliberately simple-first. Each model is backtested against the naive
baseline, and the API reports whether it won.

```
naive (last value)  →  moving average  →  Holt linear damped  →  [deferred]
```

### 1. Naive — last value carried forward

The baseline every other model must beat. For short, noisy series this is a
genuinely strong competitor, which is exactly why it is the yardstick.

### 2. Moving average

Trailing *k*-day mean. Robust to single-day spikes; cannot represent trend.

### 3. Holt linear with damped trend (default)

Two smoothing equations — level and trend — plus a damping factor φ:

```
forecast_t   = level + φ · trend
level_t      = α · value + (1 − α) · forecast_t
trend_t      = β · (level_t − level_{t−1}) + (1 − β) · φ · trend_{t−1}

h-step:  level + trend · Σ(φ^i for i in 1..h)
```

Defaults: α = 0.4, β = 0.15, φ = 0.90.

Chosen because pollution-activity series are short, noisy, and non-seasonal
at daily scale, and because what a user actually wants is the *direction*.

**Damping matters.** Without φ, a week of increases extrapolates linearly and
produces absurd values ten days out. `test_damping_prevents_runaway_extrapolation`
guards this.

### Why no LSTM or PatchTST

Not out of principle — out of arithmetic. A deep sequence model needs
hundreds to thousands of observations per series to beat exponential
smoothing. This platform has tens of days per region.

Fitting an LSTM to 30 points produces a smooth, confident-looking curve that
carries no more information than the last value, while being far harder to
audit. The progression is documented so the upgrade path is clear once real
history accumulates; the trigger condition is straightforward: **when a deep
model beats Holt on backtested MAE across most regions, switch.** Until then
it would be decoration.

## Backtesting

Every fit computes one-step-ahead residuals over the historical series:

```
backtest_mae  — mean absolute one-step error for this model
naive_mae     — the same for last-value-carried-forward
beats_naive   — backtest_mae < naive_mae
```

`beats_naive: false` is reported plainly, and the message says so:

> "This model did not beat the naive last-value baseline in backtesting;
> treat the trend as weakly supported."

This is unusual to expose in a product API, and it is the point. A forecast
whose error is worse than the baseline is not insight, and hiding that would
be the same category of dishonesty as the fabricated confidence scores this
project was built to remove.

## Prediction intervals

Residual standard deviation σ from the in-sample one-step errors, widened
with the square root of the horizon:

```
interval(h) = value(h) ± z₈₀ · σ · √h        z₈₀ = 1.2816
```

**Assumptions, all approximate:** residuals are normally distributed,
homoscedastic, and independent. None holds strictly. Exact intervals require
the state-space (innovations) form of the model.

The intervals are still worth showing — they communicate that uncertainty
grows with horizon, which a bare point estimate actively conceals — but they
are labelled as an approximation in every response.

### Severity bands

`forecast_to_severity_bands()` maps the point estimate *and* both interval
bounds through the severity thresholds:

```
+7d  2026-08-28   risk 69.6  HIGH  [63.8 .. 75.5]  (HIGH..CRITICAL)
```

Showing `severity_lower` and `severity_upper` prevents the classic dashboard
failure where a band-straddling forecast is rendered as a confident single
label.

## Data preparation

Smoothing models need a regular daily grid. `get_region_series()` builds one
by forward-filling days with no satellite coverage.

This is a necessary distortion and it is disclosed twice: as a forecast caveat,
and via `coverage_ratio` on `/trends`, which reports observed days over window
length. A `coverage_ratio` of 0.33 means two thirds of that flat line is
interpolation, not calm water.

## Refusals

`min_observations` per model: naive 2, moving average 5, Holt 7. Below that
the forecaster returns `INSUFFICIENT_DATA` with a message naming what was
needed and what was available, and an empty `points` list.

An explicit refusal is more useful than a curve fitted to noise. `TestInsufficientData`
runs in the scientific-integrity CI job.

## Feeding the risk engine

`trend_slope()` — OLS slope of daily mean risk against day index — is passed
to the risk engine's `historical_trend` factor. Regions with fewer than three
observed days are omitted from `region_trend_slopes()` entirely, so the risk
engine records the factor as *missing* rather than assuming flat. Assuming
flat would mean an unmonitored region silently scores as stable.

## Extension path

1. **Multi-series / hierarchical.** Regions within a sea correlate; pooling
   would help the sparse ones.
2. **Exogenous regressors.** Wind, season, shipping density as covariates.
3. **Proper state-space** (statsmodels `ETSModel`) for exact intervals and
   likelihood-based model selection.
4. **Probabilistic forecasts** — quantile regression or conformal prediction
   for distribution-free coverage guarantees.
5. **Deep models** once history justifies them, gated on beating Holt.
6. **Dispersion modelling** — a separate project requiring the met-ocean
   ingestion listed above. It would be a genuine addition, not a relabelling
   of this one.
