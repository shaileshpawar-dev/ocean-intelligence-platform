# Water status engine

`backend/app/water/status.py`, `standards.py`, `freshness.py`.

## What it refuses to produce

No 0–100 "pollution score". A single number implies a precision monthly grab
samples cannot support, hides which parameter drove it, and lets unmeasured
parameters average away a real exceedance. The engine returns a **band**, the
**named parameters** that put it there, and the **cited limit** each breached.

## Bands

| Status | Reached when |
|---|---|
| `NO_RECENT_DATA` | Nothing ever observed, or the latest observation is too old for its source's cadence |
| `INSUFFICIENT_DATA` | Observations exist, but none of the parameters the selected standard governs |
| `POLLUTED_STRETCH` | BOD above 3 mg/L — CPCB's national polluted-location criterion — with priority band I–V |
| `HIGH_CONCERN` | A breach at ≥3× its limit, or three or more simultaneous breaches |
| `ELEVATED` | One or two breaches, none severe |
| `WITHIN_REFERENCE` | Every evaluable parameter satisfies the standard |

Gates run in that order. Freshness runs first on purpose: no amount of
parameter analysis turns a 2021 sample into a statement about today.

Rolling stations up to a water body takes the **worst** real finding; the two
"we do not know" bands rank below every finding, so a silent station can never
mask a measured breach.

## Two statuses per water body

The newest CPCB data is from 2021, so the present-tense status of every water
body is honestly `NO_RECENT_DATA`. Reporting only that would discard the real
finding. So each body carries:

- **`status`** — "what is it like now?" Usually `NO_RECENT_DATA`.
- **`latest_available_status`** — the verdict as of the latest measurement
  date, computed by standing the clock at that date. Always displayed with the
  date, and its explanation states that it describes that sample, not today.

The map colours by the second and says so in its legend.

## Standards

CPCB Designated Best Use classes A–E, with every threshold carrying its
source document and URL. Only parameters a class actually specifies are
listed — class D says nothing about coliform, class E nothing about BOD — and
a parameter with no limit evaluates to `no_standard`, **not** to compliance.

Class **C** (drinking-water source after conventional treatment) is the
default: it is what most monitored river stretches are used for, and its BOD
limit coincides with the national polluted-stretch threshold. The API accepts
`designated_use=A..E` per request.

Direction matters: dissolved oxygen fails when it is **below** its minimum;
pH is two-sided.

## Freshness

Judged against each source's declared cadence, not a global rule. For a
monthly source: recent within one period, overdue after two, `NO_RECENT_DATA`
after twelve. Irregular/unknown cadences use a three-year absolute horizon.
Summaries always say "latest available observation", never "current".

## Measured, not zero

Missing tokens (`-`, `NA`, empty, `None`) become *no observation*, never 0.
Zero BOD would read as pristine water; that is the single most dangerous bug
this pipeline could have, and there is a test for every null token the
source actually publishes.

## Tests

`backend/tests/test_water_domain.py` (73) and `test_water_pipeline.py` (36).
