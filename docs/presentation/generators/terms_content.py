"""The content of the OceanAI terminology guide.

Each entry is (term, what_it_is, in_oceanai, know_this). ``know_this`` is
the figure or sentence to have ready if an examiner pushes on that term; it
may be None where there is nothing specific to quote.

Every figure here was read from the running application or its database on
24 November 2026, or from the source code constant that produces it.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared - everyone should be able to answer these, whichever module they own
# ---------------------------------------------------------------------------
SHARED = [
    (
        "Evidence level (the “evidence ladder”)",
        "A label stored on every value saying what kind of knowledge it is. "
        "The six levels are OBSERVED (an instrument reported it), MEASURED "
        "(computed directly from an instrument's pixels), DETECTED (a "
        "detector or rule raised it from measurements), INFERRED (a model "
        "produced it from other inputs), FORECAST (a projection into the "
        "future) and RETRIEVED (fetched from a document corpus).",
        "It is a database column, not a styling choice, so it cannot be lost "
        "between the database and the screen. The interface renders each tier "
        "differently and reports mix tiers explicitly rather than blending "
        "them.",
        "If asked why it matters: a chlorophyll index computed from a cloudy "
        "scene and a laboratory sample are both numbers; without the level, "
        "a reader cannot tell which one carries more weight.",
    ),
    (
        "Provenance",
        "The record of where a value came from: which organisation, which "
        "instrument or programme, which station or scene, and at what time it "
        "was measured.",
        "Stored per row alongside the value. The Data Sources page shows all "
        "nine providers with their expected cadence, last successful sync, "
        "record count, evidence level and licence attribution.",
        "Nine external providers: CPCB, CWC (via NWDP), Copernicus "
        "Sentinel-1, Sentinel-2, Copernicus Marine, Open-Meteo, Global "
        "Fishing Watch, PANGAEA 980773 and Google Gemini.",
    ),
    (
        "Cadence and the refusal horizon",
        "Cadence is how often a source is expected to report — hourly for "
        "an automatic analyser, every few days for a satellite, years apart "
        "for some manual programmes. The refusal horizon is the rule that "
        "when a reading is older than its source's own cadence allows, the "
        "platform describes when a reading was taken rather than what the "
        "water is like now.",
        "This produces the single most distinctive behaviour in the "
        "application: a water body with a 2021 sample is reported as "
        "“Current condition: cannot be established from this dataset” "
        "with the measurement date attached, never as a green or red status.",
        "On 24 November 2026 the India Overview read: 0 water bodies current, "
        "26 recent (inside 90 days), 2,714 historical-only. The three sum to "
        "2,740.",
    ),
    (
        "Statistical anomaly vs. confirmed incident",
        "An anomaly is a reading that is unusual for its own place and time. "
        "A confirmed incident is an event somebody has established actually "
        "happened. They are not the same claim and the second is much "
        "stronger.",
        "Every marine detection in this platform is the first kind. The "
        "banner on each page and the “stat.” marker on each event say "
        "so in words.",
        "The exact label: “Statistical anomaly: top 1% of this region's "
        "last 12 months (Sentinel-2 <index>).”",
    ),
    (
        "Risk score",
        "A 0–100 number expressing potential impact if a detection were "
        "confirmed — built from exposure, proximity and sea state. It is "
        "not a probability that anything happened.",
        "Produced by a deterministic six-factor engine. No language model "
        "writes or adjusts it, and every point is reconstructible from the "
        "contribution breakdown on the Risk Analysis page.",
        "The definition shown in the interface: “Risk score = potential "
        "impact if confirmed (exposure, proximity, sea state). Not a "
        "confirmed incident.”",
    ),
    (
        "Demo mode and simulated rows",
        "Demo mode is a switch that lets an application serve invented "
        "records so that a demonstration looks full. A simulated row is such "
        "an invented record.",
        "Demo mode is off and the database holds zero simulated rows. The 666 "
        "seeded events and 2,400 synthetic observations the project once "
        "carried were deleted on 21 November 2026 after a backup.",
        "One panel still shows a model's output rather than a measurement "
        "— the drift projection, which is what a drift model is for — "
        "and it is labelled where it appears.",
    ),
    (
        "Separation of ingestion from serving",
        "An architectural rule: the jobs that fetch and write data are "
        "separate processes from the application that answers requests. The "
        "serving process only reads.",
        "A freshly started container serves exactly what the jobs produced "
        "and never fetches on request. This is what makes the system "
        "reproducible from a database dump and what lets the whole test suite "
        "run with the network removed.",
        "If asked “is the demo live?” — the data is real but it is "
        "served from the database, so no step of the demo depends on an "
        "external service being up.",
    ),
    (
        "Response cache",
        "A copy on disk of every payload an external provider ever returned.",
        "Written by the ingestion jobs as well as being processed. It is why "
        "a provider outage cannot break the demonstration, and why a figure "
        "can be traced back to the exact bytes a provider sent.",
        None,
    ),
]

# ---------------------------------------------------------------------------
# Shailesh - India Water Intelligence
# ---------------------------------------------------------------------------
WATER = [
    (
        "CPCB — Central Pollution Control Board",
        "India's national pollution regulator, under the Ministry of "
        "Environment, Forest and Climate Change. It runs both a manual "
        "water-sampling programme and a smaller network of automatic "
        "real-time analysers.",
        "The largest single source of water-quality values in the platform "
        "after CWC, and the only source that can ever describe a water body "
        "today, because only its automatic analysers report hourly.",
        "CPCB real-time: 1,397 readings, last successful sync 21 November "
        "2026.",
    ),
    (
        "CWC — Central Water Commission",
        "The central agency for water resources, which maintains its own "
        "gauging and sampling stations on the major river systems.",
        "The bulk of the historical record. CWC and CPCB are never averaged "
        "together — they are different programmes measuring with different "
        "methods on different schedules.",
        "CWC manual: 4,017,920 records. CPCB manual: 582,192. Together with "
        "the real-time feed this is the 4,601,509 total.",
    ),
    (
        "NWDP — National Water Data Portal",
        "The government portal through which CPCB and CWC publish their "
        "station data as periodic extracts.",
        "The platform's ingestion route for both manual programmes. Both "
        "feeds currently read “Sync paused”: the server answers, but a "
        "firewall in front of it returns HTTP 403 to automated clients.",
        "“Sync paused” is not an outage. The distinction is deliberate "
        "— the platform reports that it was refused, not that the source "
        "is down.",
    ),
    (
        "Water body, monitoring station, observation",
        "A water body is a named river, lake, pond or coastal stretch. A "
        "monitoring station is a physical sampling location on one. An "
        "observation is a single parameter measured at a station at a time.",
        "The three are separate tables with declared foreign keys, so every "
        "observation can be traced to its station and its water body, and a "
        "water body's record length can be computed rather than claimed.",
        "2,740 water bodies, 4,951 stations, 4,601,509 observations, across "
        "35 states and union territories and 613 districts.",
    ),
    (
        "Parameter",
        "The specific property measured — dissolved oxygen, pH, biochemical "
        "oxygen demand, faecal coliform, conductivity, temperature and so on "
        "— each with its own unit.",
        "Stored with the value and the unit, never flattened into a single "
        "“quality score”, because different parameters answer different "
        "questions and are governed by different limits.",
        None,
    ),
    (
        "DO — Dissolved oxygen",
        "The amount of oxygen dissolved in the water, in mg/L. Aquatic life "
        "needs it; organic pollution consumes it. Higher is better.",
        "One of the four core parameters the data-quality check looks for. "
        "A Class C water body requires 4 mg/L or more.",
        "Higher is healthier — the opposite direction to BOD and coliform.",
    ),
    (
        "BOD — Biochemical oxygen demand",
        "How much oxygen micro-organisms consume while breaking down organic "
        "matter in a sample, in mg/L. It is an indirect measure of organic "
        "pollution load, usually over five days at 20 °C.",
        "A core parameter. Class C allows 3 mg/L or less. Lower is better.",
        None,
    ),
    (
        "pH",
        "How acidic or alkaline the water is, on a logarithmic scale where 7 "
        "is neutral.",
        "A core parameter. Most CPCB classes require roughly 6 to 9, or 6.0 "
        "to 8.5 for Class E.",
        None,
    ),
    (
        "Faecal coliform",
        "Bacteria from the gut of warm-blooded animals, counted as Most "
        "Probable Number per 100 mL. Their presence indicates sewage "
        "contamination and therefore a health risk for bathing or drinking.",
        "The parameter that most often drives a “High concern” status on "
        "Indian rivers in this dataset. Class C allows 5,000 MPN/100 mL or "
        "less.",
        "On the Ganga River page, the “Why this status?” panel names the "
        "faecal coliform rule, the limit it exceeded and the standard the "
        "limit came from.",
    ),
    (
        "Designated Best Use (Classes A to E)",
        "CPCB's classification principle: of all the uses a water body "
        "serves, the one demanding the highest quality is its designated best "
        "use, and the water is judged against that. Class A is a drinking "
        "water source needing only disinfection; B is organised outdoor "
        "bathing; C is a drinking source after conventional treatment; D is "
        "propagation of wildlife and fisheries; E is irrigation, industrial "
        "cooling and controlled waste disposal.",
        "This is why the platform stores which standard it compared against "
        "rather than applying one universal limit. A value that fails Class A "
        "may pass Class D, and saying “polluted” without naming the class "
        "is meaningless.",
        "Requirements fall progressively from A to E, and meeting one class "
        "also satisfies every class below it.",
    ),
    (
        "Primary Water Quality Criteria",
        "The published numeric limits attached to each designated-best-use "
        "class — the actual thresholds for DO, BOD, pH, coliform and the "
        "rest.",
        "Held in the reference-standards table with its authority and "
        "designated use. The Ganga page cites “Primary Water Quality "
        "Criteria for Bathing Water” and links the Environment (Protection) "
        "Rules, 1986 schedule it comes from.",
        None,
    ),
    (
        "Reference standard, and “applies by rule”",
        "The standard a measurement is compared against. In the data model "
        "there is no foreign key from an observation to a standard — which "
        "standard applies is decided by a rule at query time, from the water "
        "body's designated use and the parameter.",
        "On the class diagram this is drawn as a dashed dependency rather "
        "than a solid association, precisely because the database does not "
        "hold that link.",
        "If asked why there is no arrow there: because inventing one would "
        "assert a relationship the database does not have.",
    ),
    (
        "Current / recent / historical-only",
        "The three freshness buckets a water body can fall into: a reading "
        "inside two days, inside ninety days, or older than that.",
        "Every water body sits in exactly one bucket and the three always sum "
        "to the total, so nothing can hide in a rounding.",
        "24 November 2026: 0 current, 26 recent, 2,714 historical-only, "
        "summing to 2,740.",
    ),
    (
        "Geometry matching",
        "Attaching a real shape to a named water body, rather than a dot on "
        "a map, by matching the name and position against an OpenStreetMap "
        "extract offline.",
        "A water body with a matched shape renders as its true outline; one "
        "without says so. The Ganga page reports “Mapped shape: Yes — "
        "matched to an OpenStreetMap feature” as a fact about the data, not "
        "about the river.",
        None,
    ),
    (
        "RAG — Retrieval-Augmented Generation",
        "A technique where a system retrieves relevant stored records first "
        "and answers only from them, instead of generating an answer from a "
        "language model's own memory.",
        "The “Ask about India's water” page is retrieval over the stored "
        "observations with no language model writing the answer. Every figure "
        "carries a citation and a date, and the system refuses when the "
        "corpus cannot support an answer.",
        "The demonstration question: “What is the latest available status "
        "of Mithi River?” It answers “high concern as of 02 Dec 2021” "
        "and refuses “high concern now.”",
    ),
    (
        "TLS certificate pinning",
        "Requiring that a specific server present one specific certificate, "
        "rather than trusting any certificate a public authority has signed. "
        "It defends against an intermediary impersonating the server.",
        "Used for exactly one government host, scoped by SHA-256 fingerprint. "
        "It is narrow on purpose: pinning broadly would break every other "
        "connection the moment a certificate rotates.",
        "It also fixed a real diagnosis error — a missing root certificate "
        "on one laptop had been recorded as a national CPCB outage.",
    ),
    (
        "Data quality score",
        "A rating of how much a water body's record can support, computed "
        "from objective facts: how many distinct months were sampled, how "
        "long the record runs, and how many core parameters were measured.",
        "Shown with the facts that produced it, so a reader can disagree with "
        "the rating and still use the facts.",
        "Ganga River: quality High — 745 sampling months, 63.1 years of "
        "record, 4 of 4 core parameters measured.",
    ),
]

# ---------------------------------------------------------------------------
# Santosh - Marine Monitoring
# ---------------------------------------------------------------------------
MARINE = [
    (
        "SAR — Synthetic Aperture Radar",
        "A radar that synthesises a large antenna from the satellite's own "
        "motion to achieve fine resolution. It supplies its own illumination, "
        "so it works at night and sees through cloud — the reason it is "
        "used for oil-spill surveillance.",
        "Sentinel-1 carries the SAR instrument this platform screens. The "
        "radar half of the system exists because the optical half is blind "
        "under cloud.",
        None,
    ),
    (
        "Sentinel-1, and GRD",
        "A European Space Agency radar mission in the Copernicus programme. "
        "GRD — Ground Range Detected — is the product level where the "
        "radar signal has been detected, multi-looked and projected to ground "
        "range, giving an image of backscatter amplitude.",
        "The product the oil-slick classifier screens. 100 tiles across 9 "
        "real acquisitions have been screened, with 0 oil detections.",
        "Expected cadence about 6 days per region.",
    ),
    (
        "Sentinel-2, MSI and Level-2A",
        "The optical mission of the same programme. MSI is its "
        "MultiSpectral Instrument. Level-2A means the imagery has been "
        "atmospherically corrected, so pixel values are surface reflectance "
        "rather than top-of-atmosphere radiance.",
        "Every water-quality index in the platform is computed from Level-2A "
        "surface reflectance. Using Level-1C instead would mean measuring the "
        "atmosphere as much as the water.",
        "3,006 index readings across 36 of 40 regions, newest 20 November "
        "2026. Cadence about 5 days per region, cloud permitting.",
    ),
    (
        "Backscatter and VV polarisation",
        "Backscatter is how much of the radar pulse the surface sends back "
        "toward the satellite. VV means the pulse was transmitted and "
        "received in vertical polarisation — the channel most sensitive to "
        "the small surface waves that oil suppresses.",
        "The benchmark patches are VV amplitude. The calibration problem the "
        "project found and partly fixed was in exactly this quantity.",
        "Prepared tiles still average about 34 brightness units darker than "
        "the training patches (112.6 against a training mean of 147).",
    ),
    (
        "Dark formation",
        "A patch of sea that returns less radar energy than its surroundings "
        "and therefore appears dark. Oil films cause this; so do several "
        "other things.",
        "What the detector actually finds. Calling it an oil spill is a "
        "further claim the radar alone cannot support, which is why the "
        "platform keeps the two words apart.",
        None,
    ),
    (
        "Look-alike",
        "Anything that produces a dark formation without being oil — "
        "biogenic films from algae, rain cells, wind shadows behind "
        "headlands, and above all calm water.",
        "The PANGAEA benchmark deliberately carries a large look-alike set "
        "alongside the oil set, because a detector that has never seen a "
        "look-alike will call every dark patch oil.",
        None,
    ),
    (
        "Low-wind ambiguity",
        "Below roughly 3 m/s the sea surface goes flat on its own, so it "
        "returns little radar energy and looks exactly like an oil film. "
        "Above about 12 m/s the opposite happens — the slick is dispersed "
        "and stops being visible.",
        "Every candidate carries the wind speed at acquisition from ERA5. "
        "Candidates in the low-wind band are held as ambiguous rather than "
        "counted as detections.",
        "Of 306 candidates: 136 under favourable wind (3–12 m/s), 70 "
        "low-wind ambiguous, 0 high-wind, 1 with no wind data, 99 where the "
        "detector found nothing.",
    ),
    (
        "Capillary waves and damping",
        "The small, centimetre-scale waves that radar at this wavelength "
        "actually responds to. An oil film raises the water's surface tension "
        "and damps them, which is the physical mechanism behind the dark "
        "patch.",
        "This is the one-sentence physics answer for why SAR can see oil at "
        "all, and why wind matters so much: with no wind there are no "
        "capillary waves to damp.",
        None,
    ),
    (
        "Spectral bands",
        "Sentinel-2 measures reflectance in separate wavelength bands. The "
        "ones used here are B02 blue, B03 green, B04 red, B05 red-edge, B06 "
        "red-edge, B08 near-infrared and B11 short-wave infrared.",
        "Six bands plus the scene classification layer are fetched per "
        "candidate in a single Process API request and the indices computed "
        "from them.",
        None,
    ),
    (
        "NDCI — Normalized Difference Chlorophyll Index",
        "(B05 − B04) / (B05 + B04). A red-edge against red ratio that "
        "tracks chlorophyll-a in turbid productive coastal water. From Mishra "
        "and Mishra (2012).",
        "The algal-bloom indicator. It has a literature-based absolute floor "
        "of 0.08, so an NDCI detection satisfies both criteria.",
        "The paper reports R² near 0.9 against MERIS data, but the authors "
        "are explicit that an absolute concentration needs local calibration "
        "— which is why 0.08 is used as an indicative level, not a limit.",
    ),
    (
        "NDTI — Normalized Difference Turbidity Index",
        "(B04 − B03) / (B04 + B03). A red against green ratio that tracks "
        "suspended sediment. From Lacaux et al. (2007), who defined it while "
        "mapping pond turbidity in the Ferlo region of Senegal.",
        "The turbidity indicator. Its absolute floor is set at 0.0 — the "
        "sign convention — and nothing higher, because the published "
        "numeric levels are calibrations for Senegalese ponds and do not "
        "transfer to the Bay of Bengal.",
        "A 30-day window gave a p95 of −0.008 — every value negative. "
        "The twelve-month window gives +0.028. The first threshold had been "
        "fitted to winter.",
    ),
    (
        "FDI — Floating Debris Index",
        "B08 − (B06 + (B11 − B06) × 1.7722). A near-infrared value "
        "measured against a baseline interpolated between the red-edge and "
        "short-wave infrared bands. From Biermann et al. (2020).",
        "The floating-material indicator. It is the one index with no "
        "absolute floor, because the paper publishes none — it classifies "
        "using a Naive Bayes model over FDI together with NDVI. FDI "
        "detections are therefore labelled “relative anomaly only”.",
        "The word “threshold” appears zero times in that paper. This was "
        "checked in the paper itself, not assumed. Never call an FDI "
        "detection plastic.",
    ),
    (
        "SCL — Scene Classification Layer",
        "A per-pixel map that ships with Sentinel-2 Level-2A labelling each "
        "pixel as water, cloud, cloud shadow, vegetation, snow and so on. "
        "Class 6 is water.",
        "Indices are computed over SCL water pixels only. Without it, a "
        "coastal cell would report an index value for a beach or a cloud.",
        "At least 100 valid water pixels are required before an index reading "
        "is produced at all.",
    ),
    (
        "Cloud-free window, ±5 days",
        "How far in time the platform will look for an optical scene to put "
        "beside a radar candidate.",
        "Narrowed from ±10 days to ±5 during the final work. Beyond "
        "about one satellite revisit the scene describes different water, "
        "because a slick moves and weathers within days. When no cloud-free "
        "scene exists in the window the panel shows nothing and says why.",
        "Of 25 candidates sampled, 23 had a usable scene and 2 did not. There "
        "is no synthetic fallback — the generator was deleted, not "
        "disabled.",
    ),
    (
        "EEZ, monitoring region, cell",
        "The Exclusive Economic Zone is the belt of sea, out to 200 nautical "
        "miles, where a coastal state has sovereign rights over resources. A "
        "monitoring region is a named stretch of it; a cell is a subdivision "
        "with its own bounding box.",
        "15 regions divided into 40 cells across India's EEZ, from the Gulf "
        "of Kutch to the Andamans. They were re-cut from an inherited global "
        "demonstration set, and the risk engine's coastal and protected-area "
        "factors now point at real Indian receptors.",
        "36 of 40 cells have Sentinel-2 data; the other four had no "
        "acquisition that cleared the cloud limit.",
    ),
    (
        "Per-region p99 baseline",
        "The 99th percentile of one region's own index values over the "
        "preceding twelve months — the level only the top one per cent of "
        "that region's readings exceed.",
        "Computed per region rather than globally, so a naturally turbid "
        "coastal cell is not flagged permanently while a genuinely unusual "
        "reading elsewhere is missed.",
        "At least 40 baseline readings are required before the percentile is "
        "trusted. NDTI's p99 runs from 0.142 to 0.313 across these waters "
        "— a single global threshold could not serve both ends.",
    ),
    (
        "Absolute floor",
        "A fixed level taken from published literature or physics that a "
        "reading must also exceed, independent of how unusual it is locally.",
        "The second of the two criteria. A top-1% reading that does not clear "
        "the floor raises no event, because being unusual for a place is not "
        "the same as being a concern.",
        "Counts moved from 41/41/41 to 41 floating material, 35 algal bloom, "
        "32 turbidity when the second criterion was added. The first set was "
        "describing the method, not the sea.",
    ),
    (
        "Relative anomaly only",
        "The label applied when an index has no citable absolute floor, so "
        "the detection rests on the statistical criterion alone.",
        "Applied to every floating-material detection, because Biermann "
        "publishes no FDI threshold.",
        "This is the honest alternative to inventing a number and citing a "
        "paper that does not contain it.",
    ),
    (
        "PANGAEA 980773",
        "A published Sentinel-1 benchmark of oil slicks in the Eastern "
        "Mediterranean, by Yang and Singha (2025), released CC BY 4.0 with "
        "object-level annotations and a large set of look-alike patches.",
        "The source of all 306 SAR candidates. Its 881 patch images are "
        "stored and served, so each candidate shows the actual radar patch "
        "the detector scored.",
        "It is Mediterranean, not Indian. That is exactly why the platform "
        "says the model's measured accuracy does not transfer to Indian "
        "waters.",
    ),
    (
        "ERA5 and collocation",
        "ERA5 is the ECMWF global atmospheric reanalysis — a physically "
        "consistent reconstruction of past weather. Collocation means "
        "matching a reanalysis value to an observation in space and time.",
        "Each candidate carries 10 m wind speed and direction collocated from "
        "ERA5, with the grid distance and time offset shown, so a reviewer "
        "can judge how well matched it is.",
        "Example from candidate cand_s1_0040: 7.15 m/s at 287.9°, grid "
        "distance 17.5 km, 0 min offset.",
    ),
    (
        "Copernicus Marine Service",
        "The EU marine arm of Copernicus, publishing modelled ocean physics "
        "(currents, temperature) and ocean-colour products (chlorophyll).",
        "Supplies the surface currents that drive the drift projection, and "
        "an independent chlorophyll-a product used to cross-check this "
        "platform's own NDCI.",
        "Currents are INFERRED (a model); chlorophyll from ocean colour is "
        "OBSERVED. The two are stored at different evidence levels on "
        "purpose.",
    ),
    (
        "Open-Meteo",
        "A free weather and marine forecast API.",
        "Supplies wind, wave height and sea-surface temperature per region, "
        "and the low-wind flag that marks SAR evidence as ambiguous.",
        "40 regions, hourly cadence, evidence level INFERRED — it is a "
        "weather model, not a measurement.",
    ),
    (
        "AIS and Global Fishing Watch",
        "AIS is the Automatic Identification System, the transponder that "
        "ships broadcast position with. Global Fishing Watch derives apparent "
        "fishing effort from those broadcasts, published as hours and vessel "
        "counts on a grid.",
        "Used only in aggregate: hours and counts by flag state, never a "
        "vessel identity. The panel is labelled “Vessel activity nearby "
        "(Powered by Global Fishing Watch)”.",
        "60,403 vessel-hours across 25 of 40 regions. The word "
        "“apparent” is GFW's own: the activity is inferred from a track, "
        "not reported by the vessel.",
    ),
    (
        "Why no vessel is ever named",
        "A design decision, not a technical limit. GFW can identify "
        "individual vessels.",
        "The platform's detections are benchmark patches and statistical "
        "anomalies, not confirmed spills. Naming a real ship as the source of "
        "one would be an accusation about something never established, on a "
        "page built to be screenshotted — and a caveat underneath does not "
        "survive a crop. The suspect panel was removed rather than softened.",
        "If asked: “Deliberately absent. Global Fishing Watch answers the "
        "question it can answer honestly — how busy was this water.”",
    ),
    (
        "Drift projection (Lagrangian particle model)",
        "Releasing virtual particles at a point and advancing them under "
        "currents and wind to project where surface material would travel. "
        "The standard open framework for this is OpenDrift (Dagestad et al., "
        "2018).",
        "The one panel in the platform that is model output rather than "
        "measurement. The forcing is real — Copernicus Marine currents and "
        "Open-Meteo wind for that place and date — but the release point "
        "and volume are chosen, so the track shows how this water moves, not "
        "where a real release went.",
        "It is labelled on the panel itself, and is the reason the honest "
        "answer to “is anything simulated?” is “one panel, and it says "
        "so” rather than “no”.",
    ),
    (
        "Historical incident replay — MSC ELSA 3",
        "Pointing the detector at a documented real spill to see whether it "
        "would have found it.",
        "MSC ELSA 3 (IMO 9123221) sank at 07:50 on 25 May 2025 at "
        "09°18.75′N 076°08.16′E, about 13 nautical miles "
        "south-west of Kochi, carrying 367 t of heavy fuel oil and 84.4 t of "
        "diesel. Position, time, IMO and cargo come from the Kerala State "
        "Disaster Management Authority SITREP-3.",
        "Four passes, not detected on any: 28 May (+3 d, 12 tiles, max p(oil) "
        "0.0033, wind 9.3 m/s); 2 June (+8 d, 2 tiles, 0.0008, 3.4 m/s); "
        "9 June (+15 d, 12 tiles, 0.0623, 5.4 m/s); 14 June (+20 d, 5 tiles, "
        "0.0005, 8.2 m/s).",
    ),
    (
        "Why that negative result is published",
        "Because a detector that always answered “no” would score "
        "identically on open water. The replay was the test that could "
        "distinguish a working detector from a silent one.",
        "It is published with the reasons it is weak evidence: the first pass "
        "was three days later into a 9.3 m/s wind that roughens the sea "
        "enough to suppress slick contrast, dispersant had been applied, oil "
        "weathers within days, and the model is operating outside the "
        "distribution it was trained on.",
        "It does not establish that no slick was present. A test asserts the "
        "result stays on the page — a finding that only appears when "
        "favourable is not a finding.",
    ),
    (
        "Attribution",
        "The licence conditions that come with free public data.",
        "Required wherever the data appears: “Contains modified Copernicus "
        "Sentinel data”, “Generated using E.U. Copernicus Marine Service "
        "Information”, “Weather and marine data by Open-Meteo.com”, "
        "“Powered by Global Fishing Watch”, and PANGAEA 980773 under "
        "CC BY 4.0.",
        None,
    ),
]

# ---------------------------------------------------------------------------
# Hemant - Intelligence
# ---------------------------------------------------------------------------
INTELLIGENCE = [
    (
        "Deterministic scoring",
        "A score produced by a fixed, written-down formula, so the same "
        "inputs always give the same output and every point can be traced to "
        "the rule that awarded it.",
        "The risk engine is deterministic by design. No model produces or "
        "adjusts the number, which is what makes the contribution breakdown "
        "on the Risk Analysis page meaningful rather than decorative.",
        "If asked why not a model: because an examiner can ask why a factor "
        "scored what it did, and a deterministic engine can answer.",
    ),
    (
        "The six risk factors and their weights",
        "The engine distributes 100 points across six factors: signature "
        "severity 20, affected area 20, detection confidence 15, coastal "
        "proximity 15, protected-area proximity 15, historical trend 15.",
        "The weights are a documented product judgement, not a physical "
        "constant, and the code says so. Any score can be traced back to the "
        "weighting that produced it.",
        "Worked example on screen: Bay of Bengal Z4 scores 69.7 of 100 — "
        "affected area 20.0/20, signature severity 13.0/20, detection "
        "confidence 11.3/15, coastal proximity 9.3/15.",
    ),
    (
        "Partial assessment and renormalisation",
        "When one factor cannot be evaluated, the score is computed over the "
        "factors that could be and rescaled to 100, with the page saying it "
        "is partial.",
        "The alternative — scoring an unknown factor as zero — would "
        "make an unmeasured event look safe. That is the failure mode this "
        "behaviour exists to prevent.",
        "The Bay of Bengal Z4 example reads “59.3 of 85 evaluable points "
        "— renormalised to 69.7”, with a note that historical trend was "
        "not evaluated.",
    ),
    (
        "Severity bands",
        "LOW, MEDIUM, HIGH and CRITICAL — named ranges of the 0–100 "
        "risk score.",
        "A band is a label for potential impact if confirmed. The interface "
        "carries that definition as text beside the badge, not only as a "
        "tooltip, because CRITICAL next to a statistical anomaly otherwise "
        "reads as a confirmed emergency.",
        "108 events, 25 of them CRITICAL.",
    ),
    (
        "Signature",
        "The kind of thing a detection looks like: algal bloom, floating "
        "material, turbidity plume, or an oil-like signature from radar.",
        "Each signature carries its own intrinsic concern weight into the "
        "risk score, ordered by how directly it implies harm and how well the "
        "sensing method can actually support the claim.",
        "41 floating material, 35 algal bloom, 32 turbidity plume.",
    ),
    (
        "Receptor",
        "Something that would be harmed if pollution reached it — a "
        "fishery, a mangrove, a protected reserve, a bathing beach.",
        "The risk engine measures proximity to receptors. It currently uses "
        "28 curated centroid points rather than true protected-area "
        "boundaries, which under-states proximity for large reserves — and "
        "the page says so.",
        "The named gap: integrating WDPA (World Database on Protected Areas) "
        "boundaries is listed as future work.",
    ),
    (
        "Zone history and daily buckets",
        "Aggregating detections and index readings into one record per region "
        "per day, so a time series exists to analyse.",
        "Rebuilt from stored readings after every fetch. A region with no "
        "qualifying reading gets no bucket — absence is left as absence "
        "rather than filled with a zero.",
        "105 daily buckets across the 40 regions.",
    ),
    (
        "Holt linear damped",
        "A time-series forecasting method that models level and trend "
        "exponentially, with a damping parameter that flattens the trend as "
        "the horizon lengthens rather than extrapolating it forever.",
        "The forecaster used on detection activity and measured Sentinel-2 "
        "indices. It forecasts the platform's own detection activity, not the "
        "physical movement of a pollutant — the page states this.",
        None,
    ),
    (
        "Naive baseline and beats_naive",
        "The naive baseline predicts that tomorrow equals today "
        "(last-value-carried-forward). A forecaster that cannot beat it has "
        "not earned its complexity.",
        "Every forecast chart is backtested against it and reports the result "
        "in words. On Odisha Coast W: backtest MAE 0.176 against naive 0.176 "
        "— “does NOT beat the naive baseline”.",
        "0 of 40 regions beat the naive baseline, and this is printed on "
        "every chart rather than omitted.",
    ),
    (
        "MAE — Mean Absolute Error",
        "The average size of the forecast's mistakes, in the same units as "
        "the thing being forecast. Lower is better.",
        "The metric used for the backtest comparison, chosen because it is "
        "directly interpretable rather than squared.",
        None,
    ),
    (
        "Prediction interval",
        "A band around a forecast expected to contain the true value a stated "
        "proportion of the time — here 80%.",
        "Drawn on the forecast chart and widening with the square root of the "
        "horizon. The page notes this is an approximation assuming normally "
        "distributed, homoscedastic one-step residuals, not an exact "
        "state-space interval.",
        None,
    ),
    (
        "Knowledge graph",
        "A view of the data as nodes and the links between them.",
        "Built only from relationships the database actually declares. Solid "
        "edges are foreign keys; dashed edges are citations resolved from "
        "report sources. Nothing is inferred from proximity, name similarity "
        "or an embedding.",
        "611 nodes, 253 edges, 0 unresolved citations. Centring on "
        "Lakshadweep Sea NE at 2 hops gives 13 nodes and 12 edges.",
    ),
    (
        "Why SAR candidates are not in the graph",
        "Because sar_candidates declares no foreign key to a region. The two "
        "really are separate components in the schema.",
        "Drawing an edge there would mean inventing one, which is the single "
        "thing this graph is built not to do. The class diagram shows the "
        "same absence for the same reason.",
        "This is a good question to be asked — the answer demonstrates the "
        "principle rather than apologising for a gap.",
    ),
    (
        "Agent run and report",
        "An agent run is one pass of the analysis pipeline over a region's "
        "evidence; a report is the document it produces.",
        "Reports are sectioned by evidence level, so what was observed is "
        "kept separate from what was detected and what was inferred. No "
        "language model writes the structure — the structure is the "
        "output.",
        None,
    ),
    (
        "The Gemini narrative, and why it is not evidence",
        "A large language model writes a short prose summary of a report.",
        "Generated once, number-checked against the stored evidence before "
        "being saved, and cached in the database — so it is never "
        "generated on page load and the figures in it cannot drift from the "
        "data. The model name is shown in the label.",
        "If asked “is the AI making things up?” — the prose is "
        "labelled “AI-generated summary”, every figure in it was "
        "verified against the evidence before storage, and no decision in the "
        "platform depends on it.",
    ),
]

# ---------------------------------------------------------------------------
# Shreya - AI Research
# ---------------------------------------------------------------------------
AI_RESEARCH = [
    (
        "CNN — Convolutional Neural Network",
        "A neural network that slides learned filters across an image, so it "
        "detects a pattern wherever it appears rather than learning each "
        "position separately.",
        "The oil-slick classifier, sar-oil-slick-v2.2, is a CNN scoring "
        "256×256 Sentinel-1 VV patches.",
        "Registered as 2.2.0-experimental. “Experimental” is part of the "
        "name on purpose.",
    ),
    (
        "Training, validation and test splits",
        "Training data fits the model; validation data tunes it; test data is "
        "held back and used once, to measure it.",
        "The reported metrics come from a leakage-free 100-sample split. The "
        "dev and validation sets are deliberately kept outside the drift "
        "comparison windows, because comparing against data the model was "
        "tuned on measures nothing.",
        None,
    ),
    (
        "Leakage",
        "When information from the test set reaches the model during "
        "training — through shared scenes, duplicated patches or a "
        "careless split — producing a score that cannot be reproduced on "
        "genuinely new data.",
        "The split is described as leakage-free because it was constructed to "
        "avoid exactly this, and the figure is reported as such rather than "
        "as a bare accuracy.",
        None,
    ),
    (
        "Confusion matrix",
        "The four outcomes of a binary classifier: true positives (oil, "
        "called oil), false positives (clean, called oil), true negatives "
        "(clean, called clean) and false negatives (oil, missed).",
        "Computed live from the 306 stored candidates and recomputed as the "
        "threshold slider moves.",
        "At threshold 0.50: 136 true positive, 18 missed slick, 71 false "
        "alarm, 81 true negative.",
    ),
    (
        "Precision",
        "Of everything the model called oil, the fraction that really was "
        "oil. TP / (TP + FP). It answers: can I trust an alarm?",
        "Live value 65.7%. In an operational setting, a third of alarms would "
        "be wasted investigations.",
        None,
    ),
    (
        "Recall (sensitivity)",
        "Of all the real oil, the fraction the model found. TP / (TP + FN). "
        "It answers: how much do I miss?",
        "Live value 88.3%. The model is tuned to miss little, which is why "
        "precision is lower — the two trade off against each other.",
        None,
    ),
    (
        "F1 score",
        "The harmonic mean of precision and recall, a single number balancing "
        "the two. It punishes a model that is excellent at one and poor at "
        "the other.",
        "Live value 0.753 over all 306 candidates. The registry card reports "
        "0.765 from the 100-sample test split — a different sample, and the "
        "page explains the difference rather than hiding it.",
        "If asked which is right: both, for different sets. Neither is wrong; "
        "they are different samples.",
    ),
    (
        "False-positive rate",
        "Of all the genuinely clean sea, the fraction the model wrongly "
        "flagged. FP / (FP + TN).",
        "Live value 46.7%. It is on the screen because it is true, not "
        "because it flatters the model — and it is the clearest single "
        "argument for why the model needs retraining on Indian data.",
        None,
    ),
    (
        "ROC curve and AUC",
        "The Receiver Operating Characteristic plots recall against "
        "false-positive rate as the decision threshold sweeps from 0 to 1. "
        "AUC, the area under it, summarises the model's ranking ability "
        "independently of any one threshold: 1.0 is perfect, 0.5 is chance.",
        "Drawn live with the dashed diagonal marking chance. AUC 0.771.",
        "Because AUC is threshold-independent, moving the slider changes the "
        "confusion matrix but never the curve. That is a good thing to say "
        "while demonstrating it.",
    ),
    (
        "Threshold and operating point",
        "The score above which the model's output is treated as a positive. "
        "Choosing it is a decision about which error is worse, not a property "
        "of the model.",
        "The slider sits at 0.50 and is explicitly illustrative. Candidates "
        "are described as “uncalibrated rankings, not validated "
        "probabilities”.",
        None,
    ),
    (
        "Calibration",
        "Whether a model's 0.9 really means 90% of such cases are positive. "
        "An uncalibrated model can rank well while its numbers mean nothing "
        "as probabilities.",
        "This model is uncalibrated and every page says so, which is why its "
        "outputs are called scores rather than probabilities.",
        None,
    ),
    (
        "Off-distribution",
        "Running a model on data drawn from a different population than it "
        "was trained on — here, Indian waters when the training set is "
        "Eastern Mediterranean.",
        "Stated wherever a live screening result is shown. It is also the "
        "reason the MSC ELSA 3 non-detection is weak evidence rather than "
        "proof the detector fails.",
        "Prepared tiles average 112.6 brightness against a training mean of "
        "147 — about 34 units darker.",
    ),
    (
        "Saturation (a real bug, found and mostly fixed)",
        "When a model returns the same extreme score for everything, so its "
        "output carries no information.",
        "Live screening once returned confidence 1.000 for 100 of 100 tiles. "
        "The cause was tile preparation — a per-tile percentile stretch and "
        "too permissive a validity floor — not the model: the 306 benchmark "
        "patches reproduced their stored scores to within 1%.",
        "After fixing the dB window and raising the validity floor to 98%, "
        "22 of 100 saturate and ordinary open water scores about 0.05. Not "
        "fully solved, and reported that way.",
    ),
    (
        "Inference latency",
        "How long one prediction takes, usually quoted as a median (p50) "
        "because averages are dragged by rare slow calls.",
        "Measured from real prediction logs, not estimated.",
        "49.41 ms over 152 requests for sar-oil-slick-v2.2; 407 prediction "
        "logs in total.",
    ),
    (
        "Prediction log",
        "A stored record of each inference: the input, the score, the latency "
        "and when it ran.",
        "The substrate for both the live metrics and drift monitoring. "
        "Without it, neither could be computed after the fact.",
        None,
    ),
    (
        "Drift",
        "When the data a deployed model sees stops resembling the data it was "
        "trained and measured on, so its past accuracy stops being a guide to "
        "its current accuracy.",
        "Monitored continuously and reported honestly. The platform has never "
        "tuned the result away.",
        None,
    ),
    (
        "PSI — Population Stability Index",
        "A measure of how far one distribution has moved from another, "
        "computed by binning both and summing (current − baseline) × "
        "ln(current / baseline) across bins. Conventional reading: below 0.1 "
        "stable, 0.1 to 0.25 some shift, above 0.25 significant shift.",
        "Computed over two non-overlapping windows with thresholds 0.10 "
        "warning and 0.25 drift.",
        "At a 30-day baseline against a 7-day current window: PSI 1.3348 on "
        "mean confidence and 1.1531 on predicted class distribution, over 142 "
        "and 152 inferences. Status: drift detected.",
    ),
    (
        "Baseline and current windows",
        "The two time periods PSI compares. They must not overlap, or the "
        "comparison is partly against itself.",
        "Selectable in the interface. The windows are built from the "
        "benchmark replay — Phase 12 held-out test set against Phase 13 "
        "locked final test set — and the panel states plainly that the "
        "inferences are real while the window timestamps are assigned rather "
        "than live traffic.",
        "A minimum of 30 samples per window is required before a verdict is "
        "treated as meaningful.",
    ),
    (
        "Retraining policy",
        "What a system does when drift is detected.",
        "This platform flags for human review and never retrains "
        "automatically. Drift is a symptom with many causes — a seasonal "
        "shift, a changed monitoring region, an upstream preprocessing bug "
        "— and retraining blindly bakes the cause into the weights.",
        "If asked why not automate it: because the correct response to drift "
        "depends on its cause, and the monitor cannot tell you the cause.",
    ),
    (
        "Model registry, and “not evaluated”",
        "A record of every model version with its metrics and deployment "
        "state.",
        "Five models registered, three evaluated. An unevaluated model "
        "reports null and renders as “Not evaluated” — never as zero, "
        "which would read as a measured failure.",
        "The optical YOLOv8 detector is a real object detector, but its test "
        "split was never committed, so its metrics are null and the page says "
        "so.",
    ),
    (
        "MARIDA",
        "The Marine Debris Archive (Kikaki et al., 2022): a labelled "
        "Sentinel-2 benchmark that separates marine debris from the things it "
        "is confused with — Sargassum, ships, foam, natural organic "
        "material.",
        "Not yet used. It is the named route to giving floating-material "
        "detections an absolute criterion, replacing the percentile with a "
        "trained classifier.",
        "This is the answer to “how would you fix the FDI problem?”",
    ),
]

SECTIONS = [
    ("Shailesh", "India Water Intelligence",
     "The in-situ half of the platform: national water-quality data, the "
     "freshness rules that govern what may be said about it, and the "
     "question-answering layer over it.", WATER),
    ("Santosh", "Marine Monitoring",
     "The remote-sensing half: radar and optical satellite data over India's "
     "exclusive economic zone, the indices computed from it, and the rules "
     "that turn an index value into a detection.", MARINE),
    ("Hemant", "Intelligence",
     "What the platform does with detections once it has them: scoring, "
     "forecasting, linking and reporting — all of it deterministic or "
     "explicitly labelled.", INTELLIGENCE),
    ("Shreya", "AI Research",
     "The machine-learning component: how the oil-slick classifier is "
     "measured, what its numbers mean, and how the platform watches it for "
     "decay.", AI_RESEARCH),
]
