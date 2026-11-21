# How an optical reading becomes a detection

The platform measures three published band-ratio indices over each monitored
region from Sentinel-2 L2A: NDCI (chlorophyll-a), NDTI (suspended sediment)
and FDI (floating material). Most readings are unremarkable. This is the rule
that decides which are not.

## The method, in one paragraph

A reading is raised as a detection when it sits in the **top 1% of what this
platform has measured in that same region over the preceding twelve months**.
The threshold is the region's own 99th percentile, computed from its own
stored readings, and a region needs at least 40 clear acquisitions before it
gets one at all — below that a percentile is just the highest reading, and no
events are raised rather than falling back to a figure borrowed from
somewhere else. Readings computed from fewer than 100 water pixels are
excluded before the percentile is taken, because an index averaged over a
handful of pixels is arithmetic rather than a measurement. Each event records
the threshold it cleared, how many readings the baseline rests on, and the
window those readings span.

## Why per region and not one threshold

Because the water is not the same everywhere, and a single cut-off encodes
geography as if it were pollution. Measured across the monitored regions, the
99th percentile of NDTI ranges from **0.142** in the quieter cells to
**0.313** off the Krishna–Godavari delta. A platform-wide threshold set
anywhere in that range would mark the river mouths as anomalous every day of
the year — which is not a finding, it is a description of where rivers are —
while missing a genuine excursion in clear water offshore.

An earlier version of this rule used one global threshold taken from a
30-day sample, and it failed in exactly that way twice over. NDTI's 95th
percentile across those 30 November days was **−0.008**, every reading
negative; over a full year it is **+0.028**. The sample was winter and the
year contains the monsoon, so the threshold flagged **14% of all readings**.
A detector that fires on one reading in seven is measuring the season.

## What a detection does and does not claim

It claims: *this reading is unusual for this stretch of water, as this
platform has measured it over the last year.* Every event carries that
sentence — "Statistical anomaly: top 1% of this region's last 12 months
(Sentinel-2 NDCI)" — as its first caveat, and the interface shows it on the
badge and on the detail page.

It does not claim that the water is polluted, that a limit has been exceeded,
or that an incident has occurred. There is no regulatory threshold anywhere
in this rule. A region can produce a detection on a day when the water is
entirely healthy and merely unusual, and that is the correct behaviour for a
screening tool.

The signature names what the instrument can support, not a cause:

| Index | Signature | What it responds to |
|---|---|---|
| NDCI | `algae_bloom_signature` | Chlorophyll-a. Productive water, which may be a bloom, an upwelling or a nutrient plume. |
| FDI | `floating_material` | Anything floating that is brighter in the near-infrared than the water. Not plastic — the index cannot identify a material. |
| NDTI | `turbidity_plume` | Suspended sediment, frequently natural on this coast. |

## The absolute check, for chlorophyll only

"Unusual here" and "high in anyone's terms" are different questions, and for
chlorophyll both can be answered. Alongside the regional anomaly, every NDCI
event also reports whether the reading exceeds
`MultiSensorIntegrator.ALGAL_BLOOM_NDCI_THRESHOLD` (**0.08**), a
literature-based absolute level independent of what the region usually looks
like. Both figures appear on the event, and neither replaces the other: an
event that is both unusual locally and high absolutely is worth more than one
that is only either.

No equivalent absolute exists for FDI or NDTI that transfers between water
types. Biermann et al. (2020) threshold FDI against local background rather
than a constant, which is the same reasoning this page is built on.

## Reproducing it

```powershell
python scripts/fetch_sentinel2_indices.py --days 365
```

```powershell
python scripts/rebuild_real_events.py --rebuild-events
```

The first fetches and caches the readings; the second recomputes every
region's baseline and raises events against it. Both are idempotent. The
builder prints the method it used, the number of regions that had enough
history, and the counts per signature.

## Current state

As of 21 November 2026: **3,006 readings** across 36 regions spanning
21 Nov 2025 – 20 Nov 2026, of which 2,744 clear the water-pixel floor.
**34 regions** have enough history for a baseline. **123 events** — 41 algal
bloom, 41 floating material, 41 turbidity plume — which is what one percent
per region per index should look like.
