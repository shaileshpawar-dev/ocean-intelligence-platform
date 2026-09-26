# Data sources

What the water platform reads, how each source was verified, and what was
deliberately not integrated. Every claim in this document was checked against
the live source on 2026-09-20/21, not inferred from a website's existence.

## Integrated

### CPCB Surface Water Quality (Manual) — via the National Water Data Portal

| | |
|---|---|
| Publisher | Central Pollution Control Board, published by the National Water Informatics Centre |
| Portal | <https://nwdp.nwic.gov.in/dataset/?organization=cpcb> |
| Access | CKAN API, **public, no key, no registration** |
| Licence | "Other (Open)" as declared on the portal |
| Datasets | Physical, chemical and biological parameters — 315 CSV resources |
| Coverage | 35 state/UT codes, three periods each: 1961–2020, 2021–2025, 2026–2030 |
| Adapter | `backend/app/water/providers/nwdp_cpcb.py` |
| Declared cadence | Monthly (the programme's sampling interval) |

**Verified facts that shaped the design:**

- `/api/3/action/datastore_search` works unauthenticated for every resource
  (all 315 are `datastore_active`), with paging up to 1,000 rows.
- `/api/3/action/datastore_search_sql` is **disabled** ("Action name not
  known"), so aggregation happens in-process after paging.
- The **2026–2030 resources exist but are empty** placeholders. The adapter
  skips them.
- **The newest data anywhere is from 2021.** Every sampled state's 2021–2025
  resource contains only 2021 rows; the 1961–2020 resources hold mostly
  2018–2019 monthly series. This is why the platform reports "no recent data"
  for every water body and shows the last measured status with its date.
- The **`River`, `Basin` and `Tributary` columns are empty** in every row
  sampled nationwide (0 of 3,000+). Water-body identity is parsed from the
  station name — see `data-model.md`.
- Values are text. `'-'`, `''` and `None` all mean "not measured"; censored
  values such as `'<0.01'` occur. Timestamps are `DD-MM-YYYY HH:MM`.
- Conductivity headers say `mS/cm`, but published magnitudes (hundreds to
  thousands for urban lakes) are µS/cm. The parser treats magnitude as
  decisive and documents the assumption in `parameters.py`.
- District names are inconsistent: `MUMBAI CITY` alongside `Mumbai Suburban`;
  `Bangalore Urban` alongside post-rename spellings elsewhere. All-caps names
  are recased; official renamings are resolved by an alias table.

**Parameters published (43 canonical):** temperature, turbidity, conductivity,
colour, odour, total solids; pH, dissolved oxygen, TDS, ammonia, nitrate,
nitrite+nitrate, total phosphorus, chloride, sulphate, fluoride, hardness,
alkalinity, calcium, magnesium, sodium, potassium, carbonate, bicarbonate,
boron, SAR; arsenic, cadmium, chromium, lead, mercury, nickel, iron,
manganese, copper, zinc; BOD, COD, faecal coliform, total coliform.

**Ingested locally in this session:** Maharashtra, Delhi, Uttar Pradesh,
Karnataka, Tamil Nadu, West Bengal and Gujarat — 42 resources, 177,112
observations, 1,190 stations, 765 water bodies. The other 28 states are one
command away: `python -m app.water.cli ingest --states <codes>`.

### Reference standards (not a data feed)

| Document | Used for |
|---|---|
| CPCB, *Designated Best Use Water Quality Criteria* | Class A–E limits in `water/standards.py` |
| CPCB, *Polluted River Stretches: Criteria and Status* | 3 mg/L BOD threshold and priority bands I–V |

Both were verified via search results quoting the criteria; the CPCB site's
TLS certificate was expired at the time, so the PDF itself could not be
fetched directly. The numeric values match across independent sources.

## Water-quality sources

| Source | Agency | Coverage | Newest data | Identity |
|---|---|---|---|---|
| `cpcb_rtwqms` | Central Pollution Control Board | **40 stations, 6 states** (Ganga basin only) | **hourly** | named for the place, resolved by the river they stand on |
| `cpcb_nwdp` | Central Pollution Control Board | 35 state/UT codes, 211 resources | mostly 2021 (a few stations 2025) | `River` empty — parsed from station names |
| `cwc_nwdp` | Central Water Commission | 29 states, 169 fetchable resources | **2025** | `River`/`Basin`/`Tributary` populated — read as drainage, not identity |

Both are CKAN datastore resources on the National Water Data Portal, public
and unauthenticated. Neither overwrites the other: an observation belongs to
one source and the UI shows which agency measured what, and when.

**CWC's `River` column is usually a basin name.** In the rows sampled it
repeats `Basin` 72% of the time (100% for Uttar Pradesh), and the watercourse
is in `Tributary`: Sikkim publishes `River=Brahmaputra, Basin=Brahmaputra,
Tributary=Teesta` for every station in the state. Where the two columns
differ — every Odisha row, `Basin="Brahmani and Baitarni"`,
`River="Baitarani"` — the `River` column does name a river. `Tributary` uses
`-` for "not on a tributary", and carries reach numbering such as
`Bhagirathi-II (WB)*`. How the platform reads all this, and what it refuses
to conclude, is in
[water-geospatial.md](water-geospatial.md#2-canonical-identity).

Checked for newer data and **not** usable from this environment:
India-WRIS (`indiawris.gov.in` resolves but every connection is reset),
`rtwqms.cpcb.gov.in` (no such host), data.gov.in (requires an API key for the
same CPCB tables). State pollution-control-board portals publish reports
rather than machine-readable feeds; the Karnataka (KSPCB, to 2022) and Sikkim
(2025–26) tables on NWDP are candidates for a future phase.

## Geospatial sources (Phase 2, extended in Phase 3)

Each verified live before use; access dates are 2026-09-21/22.

| Source | Used for | Access | Licence |
|---|---|---|---|
| **OpenStreetMap regional extract (Geofabrik, `india-latest.osm.pbf`)** | Bulk geometry: 42k named water lines, 31k named water areas, matched offline | Public download, ~1.7 GB | ODbL 1.0 |
| OpenStreetMap via Overpass API (`overpass-api.de`) | One-off geometry refreshes only; replaced for bulk work | Public, no key; heavily rate-limited | ODbL 1.0 |
| NRSC Bhuvan WMS (`bhuvan-vec1.nrsc.gov.in/bhuvan/wms`, layer `basemap:waterbody_DEM`) | Map overlay of surface water bodies | Public WMS; WFS disabled, so raster only | © NRSC/ISRO, attributed |
| geoBoundaries IND ADM1 / ADM2 (commit `9469f09`) | State and district boundaries, city extents | Public GitHub release | CC BY 2.5 IN (ADM1), ODbL (ADM2) |
| Microsoft Planetary Computer — Sentinel-2 L2A (STAC + data API) | Satellite scenes and an NDTI proxy for matched lakes | Public, no key | Copernicus Sentinel data, free and open |
| EP Rules 1986, Schedule item 93 (CPCB-hosted PDF) | Bathing-water criteria, the river reference | Read directly | Government publication |

## Not integrated, and why

Listed so their absence is visible rather than mistaken for coverage.

| Source | Status | Reason |
|---|---|---|
| CPCB polluted-river-stretch report (PRS) | Import path only | Published as PDF; report URLs returned an HTML stub/404. A validated CSV importer exists; no rows are loaded. |
| CPCB designated-best-use criteria PDF | Values cross-checked | The PDF was unreachable (expired TLS certificate); class values were verified from independent sources. |
| Bhuvan vector water bodies / other Bhuvan layers | Not used | WFS returns ServiceUnavailable; many listed WMS layers are broken. Only `waterbody_DEM` was verified to render. |
| India-WRIS / WBIS water-body inventory | Not used | No openly machine-readable download was found. |
| CPCB real-time water quality (`rtwqmsdb1.cpcb.gov.in`) | Not integrated | A dashboard application; no documented public API was found. |
| MPCB (Maharashtra) | Not integrated | Reports and bulletins, not a verified machine-readable feed. |
| Central Water Commission | Not integrated | Hydrological (level/flow), not water quality. |
| data.gov.in OGD | Not integrated | Mirrors the CPCB tables but needs an API key; NWDP gives the same data without one. |
| Official / field photographs | Not integrated | No source found; the imagery model supports them. |

A provider that cannot reach real data is not registered, so it cannot
appear in the UI as a working integration.

## Adding a provider

Implement `WaterDataProvider` (`water/providers/base.py`): `info`, `plans()`
and `fetch()`. Two rules are part of the contract:

1. **Never fabricate.** On failure raise `ProviderUnavailableError`; never
   return an empty iterator that the caller would read as "no data".
2. **Declare a cadence**, or `Cadence.UNKNOWN`. Freshness is judged against
   it.

Register it in `water/providers/__init__.py`. Ingestion, matching,
validation, de-duplication and status then apply unchanged.
