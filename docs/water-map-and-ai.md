# Water map and Water Intelligence Q&A

## The map (`frontend/src/pages/IndiaWaterMap.tsx`)

The map is the primary surface at `/app/map`, full-bleed, not a dashboard
widget. Leaflet was kept: the existing integration was stable and nothing
required a framework change.

- **Per-viewport loading.** Every pan/zoom sends the bounding box to
  `GET /api/v1/map/water-bodies?bbox=…`; the server filters in SQL against the
  lat/lon index and caps features. The client never downloads the country.
- **Colour = what the last measurement found**, not the present. Present-tense
  status is "no recent data" everywhere (the newest CPCB data is from 2021), so
  colouring by it would make a uniformly grey, useless map. The legend and
  every tooltip say "when last measured" and show the date.
- **Unknown is grey, never green.** Absence of data must not look clean. Water
  stays blue; only markers carry status colour.
- **Colour is never the only channel.** Tooltips and panels carry text labels;
  status pills pair an icon with a word.
- **Layers:** water bodies (default) and monitoring stations (toggle).
  Filters: water type, status when last measured.
- **Search** flies to a result and opens its panel once the viewport fetch
  returns it.
- **Mobile:** the detail panel becomes a bottom sheet; controls move below the
  search bar.

Deep links — used by the Q&A page so a citation lands on its evidence:

| Param | Effect |
|---|---|
| `?highlight=a,b` | Ring those water bodies and show a "from an answer" banner |
| `?bbox=minLat,minLon,maxLat,maxLon` | Frame the map on them |
| `?focus=slug` | Fly to one and open its panel |

Not built: marker clustering (feature counts per viewport are small enough at
current coverage; revisit when all 35 states are ingested), administrative
boundary layers and basin layers (no verified boundary source was ingested).

The marine ocean map is preserved at `/app/ocean-map`.

## Q&A (`backend/app/water/rag.py`, `POST /api/v1/water/ask`)

A bounded five-stage pipeline — the water-side adaptation of the agent
workflow. The marine agent is unchanged.

```
IDENTIFY  classify intent; resolve water bodies, districts, states,
          parameters and type words by deterministic DB lookup
OBSERVE   read status, latest parameters, trends, spatial results
RESEARCH  retrieve CPCB criteria passages (standards questions only)
ANALYZE   compare against limits, filter by measured breach, year means
REPORT    template the answer from the records
```

Every stage call is recorded in `trace` with arguments, result and timing.
There is no planner and no loop.

### Guarantees, enforced by construction

- **No model produces a value.** Figures are read from observation rows and
  templated. `llm_used` is `false` in every response.
- **Every figure is cited** with date, station and `source_reference`
  (CKAN resource id and row id).
- **Absence is stated.** A parameter nobody measured yields
  "No mercury measurement is recorded for Mithi River. No value is estimated
  in its place." and `status: no_evidence`.
- **Unknown places are refused**, not answered from general knowledge.
- **"Current" is never said.** Dates and freshness accompany every status.

### Entity resolution

- Longest whole-word match wins, so "Mula Mutha" is not read as "Mutha".
- Official city renamings are expanded (Bengaluru → Bangalore, Chennai →
  Madras, …) because the source mixes old and new names.
- Plural type words narrow results: "rivers" excludes creeks and beaches.
- "Near a district" means within the radius of **any of that district's
  stations** — a single averaged centroid put "Bengaluru" 56 km from
  Bellandur Lake.

### Supported questions (verified on real data)

| Question | Behaviour |
|---|---|
| Latest status of Mithi River | Dual status, dated; key indicators cited |
| How much mercury is in Mithi River? | `no_evidence`, no number |
| Polluted rivers near Mumbai | Spatial, type-filtered, map action |
| Rivers in Maharashtra / Delhi with elevated BOD | Measured breaches only |
| Has the Godavari improved? | Annual means with sample counts and missing years |
| Compare Mithi River and Mahim Creek | Side by side, with a date caveat |
| What is the BOD limit for a polluted stretch? | Retrieved CPCB passages |
| Tell me about the Thames | Refused |

### Response shape

`status` (`grounded` / `partial` / `no_evidence`), `headline`, `sections`,
`citations` (each with `href` to the map), `limitations`, `map_action`
(`water_body_slugs`, `focus`, `bbox`), `resolution`, `trace`.

### Limits

Intent classification is regex-based and will misroute unusual phrasings;
it fails towards `no_evidence`, never towards a fabricated answer. No LLM
synthesis is wired into the water path; an optional phrasing layer could sit
on top of the templated answer, but facts would still come from records.
