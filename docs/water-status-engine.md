# Water status engine and reference standards

`backend/app/water/status.py`, `standards.py`, `reference_catalog.py`,
`freshness.py`, `classifications.py`.

## What it refuses to produce

- No 0–100 "pollution score". A single number implies a precision monthly grab
  samples cannot support, hides which parameter drove it, and lets unmeasured
  parameters average away a real exceedance.
- No comparison against a standard nobody established applies. There is **no
  default standard** (Phase 1 applied CPCB class C to everything; that is gone).
- No "polluted stretch" label unless an official source published one.
- No present-tense status from an observation too old to support it.

## Four evidence layers, kept separate to the API

| Layer | What it is | Where it comes from |
|---|---|---|
| `MEASURED` | The values, as sampled, with their dates | CPCB via NWDP |
| `REFERENCE_COMPARISON` | Each value against the selected standard, or "no applicable reference" | `reference_catalog.py` |
| `SOURCE_CLASSIFICATION` | An official classification such as a CPCB polluted river stretch | Imported tables only (`classifications.py`) |
| `DERIVED_STATUS` | The band the platform reads from the three above, with every input listed | `status.py` |

`SATELLITE_OBSERVED` is a fifth, separate kind of evidence (see
[geospatial](water-geospatial.md#satellite-evidence)); it never feeds a status.

## How a standard is chosen

`standards.select_reference()` takes the first rule that applies:

1. **Selected by the user** — `?reference=A..E` or a standard code on the API,
   the "compare against" selector on a water-body page.
2. **Designated use recorded for the water body** — only from an authoritative
   source (`water_bodies.designated_use` + `designated_use_source`). None is
   loaded today; CPCB does not publish designated use in this dataset.
3. **Station classification from the source** — hook in place; the source
   publishes none.
4. **National assessment category** — rivers only: CPCB assesses river
   monitoring locations against the *Primary Water Quality Criteria for
   Bathing Water* (Environment (Protection) Rules 1986, Schedule item 93) when
   identifying polluted river stretches, so rivers are compared against that
   standard, and the UI says it was chosen on that basis.
5. **None** — lakes, ponds, reservoirs, creeks, drains, coastal and
   groundwater points show their measurements with *"Reference comparison
   unavailable"* and the reason (e.g. groundwater would need IS 10500, which is
   not loaded).

## Standards as data

Every limit lives in `reference_catalog.py` and is mirrored into the
`reference_standards` / `reference_thresholds` tables (`cli seed-standards`,
also run by `ingest`). A threshold has a type (`minimum`, `maximum`, `range`),
values, an optional **desirable** level, a unit and a note; a standard has its
code, issuing body, legal basis, source URL and a note on how it was verified.

| Standard | Verified |
|---|---|
| EP Rules 1986 item 93 — bathing water: faecal coliform 500 desirable / 2,500 max MPN/100 mL; pH 6.5–8.5; DO ≥ 5 mg/L; BOD ≤ 3 mg/L | Read from the CPCB-hosted PDF of the schedule, 2026-09-21 |
| CPCB Designated Best Use, classes A–E | Cross-checked against independent sources quoting the table; the CPCB PDF itself was unreachable (expired TLS certificate) |

Exceeding a *desirable* level is reported (`above_desirable`) but is not a
breach. A parameter a standard does not govern evaluates to `no_standard`,
never to compliance. Direction matters: dissolved oxygen fails when **low**;
pH is two-sided.

## Bands, in order

| Status | Reached when |
|---|---|
| `NO_RECENT_DATA` | Nothing observed, or the latest observation is too old for the source's cadence ("the current condition cannot be established") |
| `POLLUTED_STRETCH` | An imported official classification lists this water body — **only** then |
| `NO_APPLICABLE_REFERENCE` | No standard applies; values shown as measured |
| `INSUFFICIENT_DATA` | None of the governed parameters was measured |
| `HIGH_CONCERN` | A breach at ≥ 3× its limit, or three or more breaches |
| `ELEVATED` | One or two breaches, none severe |
| `WITHIN_REFERENCE` | Every evaluated parameter within the standard |

Comparisons are computed whatever the freshness, so the dated
"latest measured status" (the clock stood at the observation date) still
shows what the last sample found. Rolling up takes the **worst** real finding;
"we do not know" bands rank below every finding.

## Polluted river stretches

CPCB's PRS assessments are published only as PDF reports, and the report
URLs returned an HTML stub or 404 when this was built. The platform therefore
ships the model and a validated CSV importer (`cli import-classifications`),
and **no rows**. Import rules: required `state, river, priority (I–V)`;
optional `stretch, bod_max_mg_l`; a source reference is mandatory; rivers are
matched by canonical name **within the same state** only; invalid rows are
rejected with line numbers; re-importing an assessment year replaces it. The
PRS BOD bands appear on the standards page as context only.

## Freshness

Judged against each source's declared cadence. Monthly source: recent within
one period, overdue after two, `NO_RECENT_DATA` after twelve. Wording is always
"latest available observation", never "current".

## Tests

`test_water_domain.py` (standards, selection, engine), `test_water_classifications.py`,
`test_water_pipeline.py`, `test_water_rag_geo.py` (evidence layers).
