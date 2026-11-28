"""Content for the OceanAI page-by-page guide.

Written for a team member who has not seen the project before. Every page
in the application's navigation gets the same treatment: what it is for,
what is on the screen, how it actually works, every term that appears on
it, and the questions it tends to attract.

All figures were read from the running application on 24 November 2026.
"""

from __future__ import annotations

# ===========================================================================
# PART 0 - the primer
# ===========================================================================

WHAT_IT_IS = [
    "OceanAI is a monitoring website. It answers two questions: how clean "
    "is India's fresh water, and what is happening on the sea around "
    "India's coast. It answers them from data that other organisations "
    "already publish — pollution boards, water commissions, European "
    "satellites — rather than from any sensor of our own.",

    "The data all lands in one database. A set of background programs, "
    "called the ingestion jobs, fetch it, check it and write it there. The "
    "website itself only reads from that database. It never goes out to "
    "the internet when you click something. This is why the demonstration "
    "cannot be broken by a satellite service being down, and why the whole "
    "thing can be restored from a single backup file.",

    "There are 21 pages. They are grouped into five sections in the "
    "left-hand menu, and this guide walks through all of them in that "
    "order.",
]

THE_ONE_IDEA = [
    "Almost every design decision in this project comes from one "
    "observation: most environmental dashboards show you a number without "
    "telling you what kind of number it is.",

    "A laboratory technician measuring oxygen in a river with an "
    "instrument produces one kind of number. A satellite index calculated "
    "from the colour of the sea produces a second kind. A model guessing "
    "next week's value produces a third. On most dashboards all three "
    "render as the same coloured badge, so a reader cannot tell them "
    "apart — and therefore learns to trust none of them.",

    "OceanAI stores what kind of number each value is, as a property of "
    "the value itself, and shows it. It also stores when the value was "
    "measured, and refuses to describe present conditions from a reading "
    "that is too old. When it cannot answer, it says it cannot answer.",

    "If you only remember one sentence for the presentation, make it this "
    "one: this platform separates what was measured from what was "
    "inferred, dates every figure, and refuses to describe conditions it "
    "cannot support — including when that makes it look worse.",
]

VOCABULARY = [
    ("Evidence level",
     "A tag on every stored value saying what kind of knowledge it is. "
     "You will see these words in capitals all over the site. OBSERVED "
     "means an instrument reported it. MEASURED means we computed it "
     "directly from an instrument's raw output, such as satellite pixels. "
     "DETECTED means a rule or a model raised it from measurements. "
     "INFERRED means a model produced it from other inputs — a weather "
     "forecast is inferred. FORECAST means a projection into the future. "
     "RETRIEVED means it was pulled out of a document."),

    ("Provenance",
     "Where a number came from: which organisation, which instrument, "
     "which station or satellite scene, and at what moment. Every row in "
     "the database carries this."),

    ("Cadence",
     "How often a source is supposed to report. An automatic analyser in "
     "a river reports every hour. A satellite passes over the same place "
     "every five or six days. Some manual sampling programmes publish once "
     "a year."),

    ("The refusal horizon",
     "The rule that follows from cadence: if the newest reading for "
     "something is older than its source's own cadence allows, the "
     "platform will tell you when it was measured, but will not tell you "
     "what the water is like now. This is the single most distinctive "
     "behaviour in the application and the thing examiners notice first."),

    ("In-situ",
     "Latin for “in position”. It means measured on the spot — "
     "someone went to the river with an instrument or a sample bottle. The "
     "opposite of remote sensing."),

    ("Remote sensing",
     "Measuring something from a distance, here from a satellite, without "
     "touching it."),

    ("Index",
     "A single number calculated from several satellite measurements to "
     "stand for a physical property. For example, comparing how much red "
     "light and how much red-edge light the sea reflects gives a number "
     "that tracks how much algae is in it."),

    ("Detection, and why it is not an incident",
     "In this platform a detection means one thing only: a reading that is "
     "unusual for that place compared with its own past year, and that "
     "also passes a level taken from published research. It does not mean "
     "anyone has confirmed that pollution occurred. Every page that shows "
     "a detection says so."),

    ("Risk score",
     "A number from 0 to 100 meaning “how bad would this be if it "
     "turned out to be real” — built from how large the affected area "
     "is, how close it is to a coast or a protected area, and how "
     "trustworthy the detection is. It is not a probability that anything "
     "happened."),

    ("Simulated data",
     "Invented records, used by some projects to make a demonstration look "
     "full. This project has none in its database. One panel on one page "
     "shows the output of a drift model rather than a measurement, and "
     "that panel says so on itself."),

    ("The database",
     "PostgreSQL with an add-on called PostGIS that lets it store shapes "
     "and positions on the Earth, so the application can ask questions "
     "like “which water bodies fall inside this state”."),

    ("API",
     "The part of the backend the website talks to. Every page you see is "
     "the browser asking the API a question and drawing the answer. If "
     "someone asks whether the data is “real-time”, the honest answer "
     "is that the pages read a database, and the database is filled by "
     "jobs that are run separately."),
]

HOW_BUILT = [
    ("1. The ingestion jobs",
     "Separate programs that fetch from each outside source, check the "
     "values, and write them to the database. They also save a copy of "
     "every raw response to disk, so any figure can be traced back to the "
     "exact bytes a provider sent. These are run by hand today."),
    ("2. The database",
     "One PostgreSQL database holding everything: water observations, "
     "satellite index readings, detections, regions and their shapes, "
     "model records, and the audit trail of analyst decisions."),
    ("3. The analysis layer",
     "Code that turns stored measurements into conclusions: computing "
     "satellite indices, screening radar tiles with the classifier, "
     "applying the two detection criteria, scoring risk, producing "
     "forecasts."),
    ("4. The API and the website",
     "A FastAPI service exposes everything over HTTP, and a React website "
     "draws it. The website is served from the same address as the API, so "
     "there is no separate server to configure."),
]

READING_NOTE = [
    "Each page below is covered in five parts. **What it is for** is one "
    "sentence you could say to anyone. **What you are looking at** walks "
    "the screen top to bottom. **How it works** is the mechanism behind "
    "the numbers. **Terms on this page** defines every piece of jargon "
    "that appears there. **If you are asked** gives the questions that "
    "page tends to attract, with answers.",

    "You do not need to memorise any of it. Read the section you are "
    "presenting closely, skim the rest, and keep this open during "
    "questions.",
]


# ===========================================================================
# The pages
# ===========================================================================

INDIA_OVERVIEW = {
    "name": "India Overview",
    "path": "/app/india",
    "purpose": "The front page of the freshwater half of the platform: how "
               "much is known about India's rivers, lakes and ponds, and "
               "how current that knowledge actually is.",
    "see": [
        ("Six cards across the top",
         "Water bodies (2,740), monitoring stations (4,951), observations "
         "(4,601,509), then three freshness cards: current data, recent "
         "data, historical only. The last three always add up to the first "
         "card."),
        ("“How current is this?” panel",
         "A paragraph explaining, in plain English, why the current-data "
         "number is what it is. On 24 November it read 0, and the panel "
         "explained that CPCB's hourly analysers last reported on "
         "21 November."),
        ("“Status when last measured” bars",
         "A breakdown of what the most recent sample at each water body "
         "showed — no applicable reference, within reference, elevated, "
         "high concern, insufficient data — each with a count and a "
         "percentage."),
        ("Coverage panel",
         "Geography actually present in the data: 35 states and union "
         "territories, 613 districts, and a per-state list of water bodies "
         "and stations."),
    ],
    "working": [
        "Every figure on this page is a count from the database. Nothing "
        "is estimated.",
        "The three freshness cards come from comparing each water body's "
        "newest observation date against today. Inside two days is "
        "current; inside ninety days is recent; anything older is "
        "historical only. Because every water body falls into exactly one "
        "bucket, the three numbers must sum to the total — which is a "
        "quick way to show that nothing is being hidden.",
        "The status bars use the reference standard that applies to each "
        "water body, which is chosen by the rules on the Reference "
        "Standards page. Where no standard applies, the platform says “no "
        "applicable reference” rather than inventing a comparison.",
    ],
    "terms": [
        ("Water body", "A named river, lake, pond, drain or coastal "
                       "stretch that is monitored."),
        ("Monitoring station", "A physical place on a water body where "
                               "samples are taken or an instrument sits. "
                               "One water body can have many."),
        ("Observation", "One parameter measured at one station at one "
                        "time. 4.6 million of these is the bulk of the "
                        "platform's data."),
        ("CPCB", "Central Pollution Control Board — India's national "
                 "pollution regulator. Runs both manual sampling and a "
                 "smaller set of automatic analysers that report hourly."),
        ("CWC", "Central Water Commission — the central water-resources "
                "agency, with its own gauging and sampling stations on the "
                "major rivers."),
        ("Current / recent / historical only",
         "The three freshness buckets: a reading inside two days, inside "
         "ninety days, or older."),
        ("Within reference / elevated / high concern",
         "How the last measured value compared with the standard that "
         "applies. These describe that measurement on its date, not the "
         "water today."),
    ],
    "asked": [
        ("Why does it say zero? Is it broken?",
         "No — and this is the best moment on the page. Zero means no "
         "water body has a reading fresh enough to describe it today. The "
         "automatic analysers last reported on 21 November. A dashboard "
         "that showed a green tick here would be describing the river from "
         "a sample that is days or years old."),
        ("Is this live data?",
         "The data is real and was really fetched from CPCB and CWC. It is "
         "not streaming: background jobs fetch it and the website reads "
         "the database. The page tells you the date of the newest reading "
         "rather than implying it is live."),
    ],
}

WATER_MAP = {
    "name": "Water Map",
    "path": "/app/map",
    "purpose": "The same freshwater data placed on a map of India, so you "
               "can see where the monitored water bodies actually are.",
    "see": [
        ("The map itself",
         "An OpenStreetMap base layer with state and district boundaries "
         "drawn over it, and the monitored water bodies on top. Zoom and "
         "pan to load an area."),
        ("Filters panel", "Narrow what is drawn — by state, by category "
                          "of water body, by freshness."),
        ("Layers panel", "Turn boundary layers and water-body layers on "
                         "and off."),
        ("A count in the corner",
         "How many water bodies are in the current view. It reads zero "
         "until you zoom to an area that has them, because the map only "
         "requests what is on screen."),
    ],
    "working": [
        "The map asks the API for water bodies inside the rectangle you "
        "are currently looking at, rather than downloading all 2,740 at "
        "once. That is why the count changes as you move.",
        "Where a water body could be matched to a real shape, it is drawn "
        "as that shape. The shapes come from an OpenStreetMap extract "
        "matched offline by name and position. Where no shape could be "
        "matched, the water body still exists in the data but has no "
        "outline to draw — the detail page for it says so plainly.",
        "Administrative boundaries come from geoBoundaries, used under "
        "CC BY 2.5 IN, and the attribution is printed on the map.",
    ],
    "terms": [
        ("Base layer", "The background map everything else is drawn on "
                       "top of."),
        ("Bounding box", "The rectangle of latitude and longitude you are "
                         "currently looking at. The map sends it to the "
                         "API as a filter."),
        ("Geometry", "The actual outline of a river or lake, as opposed to "
                     "a single point marking roughly where it is."),
        ("OpenStreetMap", "A free, openly licensed map of the world built "
                          "by volunteers. The source of our water-body "
                          "shapes."),
        ("geoBoundaries", "An open dataset of administrative boundaries. "
                          "The source of the state and district outlines."),
        ("PostGIS", "The add-on to the database that understands shapes "
                    "and positions, so the API can answer “what is inside "
                    "this rectangle” quickly."),
    ],
    "asked": [
        ("Why is the map empty when it loads?",
         "It only fetches what is in view, and at full-country zoom the "
         "request is deliberately limited. Zoom into a state and the water "
         "bodies appear."),
        ("Why do some water bodies have shapes and others do not?",
         "Because a shape could only be attached where the name and "
         "position matched an OpenStreetMap feature confidently. We did "
         "not force a match, and the detail page reports whether the shape "
         "was found."),
    ],
}

ASK_WATER = {
    "name": "Ask about water",
    "path": "/app/ai",
    "purpose": "Ask a plain-English question about India's water and get an "
               "answer assembled from the stored measurements, with every "
               "figure cited and dated.",
    "see": [
        ("A question box", "Type a question, or click one of the suggested "
                           "ones below it."),
        ("Suggested questions",
         "Examples that are known to work well, such as “What is the "
         "latest available status of Mithi River?” or “Show polluted "
         "rivers near Mumbai”."),
        ("The answer",
         "A headline sentence, the supporting figures, a list of "
         "citations, and a limitations note saying what the answer does "
         "not cover."),
    ],
    "working": [
        "This is retrieval, not generation. The system works out what the "
        "question is asking for, queries the stored observations, and "
        "assembles a sentence from what it found. No language model writes "
        "the answer, which is why the figures in it cannot be invented.",
        "Every number in the answer carries a citation back to the "
        "observations it came from, and a date.",
        "If the stored data cannot support an answer, the system says so "
        "instead of producing something plausible. Asking about a water "
        "body with no recent data gets you the last measured status with "
        "its date, and an explicit statement that present condition cannot "
        "be established.",
    ],
    "terms": [
        ("Retrieval", "Finding and returning records that already exist. "
                      "The opposite of generating new text."),
        ("Generation", "A language model writing new sentences. Useful, "
                       "but it can state things that are not in the data — "
                       "which is why it is not used to answer here."),
        ("Citation", "A pointer from a figure in the answer back to the "
                     "stored observation that produced it."),
        ("Limitations note", "The sentence under the answer saying what it "
                             "does not cover, for example that it "
                             "describes a past measurement rather than "
                             "present condition."),
        ("Refusal", "The system declining to answer because the data "
                    "cannot support one. A feature, not a failure."),
    ],
    "asked": [
        ("Is this ChatGPT?",
         "No. There is no language model in this answer path at all. It "
         "queries the database and assembles a sentence from the rows it "
         "finds, which is why every figure has a citation."),
        ("What happens if I ask something it does not know?",
         "It tells you it cannot answer from the available data. Try it — "
         "that is a better demonstration than a question that works."),
    ],
}

REFERENCE_STANDARDS = {
    "name": "Reference Standards",
    "path": "/app/standards",
    "purpose": "The published rules the platform compares measurements "
               "against, where each one comes from, and how it decides "
               "which rule applies to which water body.",
    "see": [
        ("“How a standard is chosen”",
         "A list of five rules in priority order: a standard you selected, "
         "a designated use recorded for that water body, a station "
         "classification from the source, the national assessment "
         "category, and finally “no applicable reference”."),
        ("The national assessment reference for rivers",
         "The Primary Water Quality Criteria for Bathing Water, with its "
         "four parameters and their limits, and a link to the source "
         "document."),
        ("CPCB designated best use classes",
         "Classes A to E, each with its own parameter limits, applied only "
         "when a designated use is actually recorded for a water body."),
    ],
    "working": [
        "The page opens with the reason it exists: “Is this water "
        "polluted?” has no answer until somebody says polluted for what. "
        "Water fit for irrigation is not fit for drinking, and judging a "
        "river by the wrong standard produces a confident wrong answer.",
        "So no standard is applied by default. The five rules are tried in "
        "order and the first that applies wins. If none applies, the "
        "platform shows the measurements and prints “Reference comparison "
        "unavailable” rather than borrowing a standard from elsewhere.",
        "Each standard carries its source. The bathing-water criteria cite "
        "the Environment (Protection) Rules 1986, Schedule item 93, and "
        "the page records that the values were read from the CPCB-hosted "
        "PDF on 21 September 2026.",
    ],
    "terms": [
        ("Reference standard", "A published set of limits that a "
                               "measurement can be judged against."),
        ("Designated best use",
         "CPCB's principle that of all the uses a water body serves, the "
         "one needing the highest quality decides which class it is judged "
         "by. Class A is a drinking source needing only disinfection; "
         "B is organised outdoor bathing; C is a drinking source after "
         "treatment; D is wildlife and fisheries; E is irrigation and "
         "industrial cooling."),
        ("Primary Water Quality Criteria",
         "The actual numeric limits attached to each class."),
        ("Faecal coliform",
         "Gut bacteria from warm-blooded animals, counted as MPN per "
         "100 mL. Their presence means sewage contamination. The bathing "
         "standard allows at most 2,500, with 500 desirable."),
        ("MPN", "Most Probable Number — the statistical way bacteria "
                "counts are expressed, because you cannot count every "
                "organism directly."),
        ("pH", "How acidic or alkaline water is. 7 is neutral. The bathing "
               "standard allows 6.5 to 8.5."),
        ("Dissolved oxygen (DO)",
         "Oxygen dissolved in the water, in mg/L. Fish need it; organic "
         "pollution consumes it. Higher is better. The bathing standard "
         "requires at least 5 mg/L."),
        ("Biochemical oxygen demand (BOD)",
         "How much oxygen micro-organisms use up breaking down organic "
         "matter in a sample — an indirect measure of sewage and organic "
         "load. Lower is better. The bathing standard allows at most "
         "3 mg/L, measured over 3 days at 27 °C."),
        ("Environment (Protection) Rules, 1986",
         "The Indian regulation whose schedule contains these criteria."),
    ],
    "asked": [
        ("Why not just use one standard for everything?",
         "Because the answer would be wrong. A value that fails a drinking "
         "standard may be perfectly fine for irrigation. Saying “this "
         "river is polluted” without naming the use is not a claim you "
         "can defend."),
        ("Where did these numbers come from?",
         "The Environment (Protection) Rules 1986 schedule, read from the "
         "CPCB-hosted PDF. The page prints the source and the date it was "
         "read."),
    ],
}

DATA_SOURCES = {
    "name": "Data Sources",
    "path": "/app/data-quality",
    "purpose": "Where every number in the platform comes from, whether "
               "each source is reachable, and what its last fetch actually "
               "produced.",
    "see": [
        ("One card per external service",
         "Nine in total. Each card shows the provider, what it supplies, "
         "its expected cadence, the last successful sync, how many records "
         "are held, the evidence level the data is stored at, and the "
         "licence attribution."),
        ("A status badge on each card",
         "Live, stale, sync paused, or unavailable — derived from what "
         "that source last actually produced, not from a setting."),
        ("A technical details toggle",
         "Expands to the underlying endpoint and error detail for the "
         "sources that are not currently fetching."),
    ],
    "working": [
        "The status is computed, not configured. A source is Live if its "
        "last successful fetch is inside its expected cadence, and the "
        "page degrades it from there.",
        "Two sources read “Sync paused”: the CPCB and CWC feeds that "
        "come through the National Water Data Portal. The server answers, "
        "but a firewall in front of it returns HTTP 403 to automated "
        "clients. That is deliberately not called an outage — the source "
        "is up and refusing us, which is a different fact.",
        "Licence attribution is shown because the data is free but not "
        "unconditional. Copernicus requires “Contains modified Copernicus "
        "Sentinel data”, Global Fishing Watch requires “Powered by "
        "Global Fishing Watch”, and so on.",
    ],
    "terms": [
        ("Sync", "One run of a fetch job against a source."),
        ("Cadence", "How often that source is expected to produce "
                    "something new."),
        ("HTTP 403", "The web status code for “I understood you and I am "
                     "refusing”. Different from a timeout or a 404."),
        ("NWDP", "National Water Data Portal — the government portal "
                 "through which CPCB and CWC publish their extracts."),
        ("Attribution", "The credit line a licence requires you to print "
                        "wherever the data appears."),
        ("Copernicus", "The European Union's Earth-observation programme. "
                       "Sentinel-1 and Sentinel-2 are its satellites, and "
                       "its data is free."),
        ("Open-Meteo", "A free weather and marine forecast service. Our "
                       "source of wind, wave and sea-temperature data."),
        ("Global Fishing Watch",
         "An organisation that publishes vessel activity derived from "
         "ships' AIS transponder broadcasts."),
        ("PANGAEA", "An open scientific data archive. Dataset 980773 is "
                    "the radar oil-slick benchmark this project uses."),
    ],
    "asked": [
        ("Two sources say sync paused — is the project broken?",
         "No. Those two are blocked by a firewall at the data provider's "
         "end, which refuses automated clients. The 4.6 million records we "
         "already fetched are in the database and are what the water pages "
         "use. We report the refusal rather than hiding it or calling it "
         "an outage."),
        ("Is any of this paid data?",
         "None of it. Every source is public: government portals, "
         "Copernicus, Open-Meteo, Global Fishing Watch, and an open "
         "research archive."),
    ],
}

REAL_OBSERVATIONS = {
    "name": "Real Observations",
    "path": "/app/real-observations",
    "purpose": "The satellite measurements behind the marine half of the "
               "platform — and the test where the detector was pointed at "
               "a real oil spill.",
    "see": [
        ("Three cards",
         "Readings stored (3,006), regions with data (36 of 40), and the "
         "evidence level the readings carry (OBSERVED)."),
        ("A note about what these are",
         "“These are measurements” — values from Sentinel-2 "
         "acquisitions on the dates shown, with only water pixels "
         "included, and nothing substituted where there was no clear "
         "acquisition."),
        ("The historical incident replay",
         "The MSC ELSA 3 section: the ship, the sinking, a radar patch "
         "image, and a table of four satellite passes with how many days "
         "after the sinking each was, how many tiles were screened, the "
         "highest oil score reached, and the wind speed."),
    ],
    "working": [
        "For each monitored region, a job asks Copernicus for Sentinel-2 "
        "imagery, keeps only the pixels the satellite's own classification "
        "layer marks as water, and computes three indices from the "
        "reflectance values. Four of the 40 regions have no readings "
        "because no acquisition cleared the cloud limit — and the page "
        "says that rather than filling the gap.",
        "The incident replay is the project's own test of its radar "
        "detector. MSC ELSA 3 sank off Kochi on 25 May 2025 carrying 367 "
        "tonnes of heavy fuel oil. Four Sentinel-1 passes over the wreck "
        "were screened. The detector flagged nothing on any of them.",
        "That negative result is published together with the reasons it is "
        "weak evidence: the first pass was three days later into a 9.3 m/s "
        "wind, which roughens the sea enough to hide a slick; dispersant "
        "had been applied; oil weathers within days; and the model is "
        "operating outside the sea it was trained on. It does not prove no "
        "slick was there.",
    ],
    "terms": [
        ("Sentinel-2", "A European optical satellite pair — it "
                       "photographs in many colour bands. Used for the "
                       "water-quality indices."),
        ("Sentinel-1", "A European radar satellite pair. Radar supplies "
                       "its own illumination, so it works at night and "
                       "through cloud. Used for oil screening."),
        ("Acquisition", "One pass of a satellite recording one scene."),
        ("Scene classification layer",
         "A per-pixel map that ships with Sentinel-2 imagery saying what "
         "each pixel is — water, cloud, cloud shadow, land. We keep only "
         "the water pixels."),
        ("Reflectance", "How much light a surface sends back, per "
                        "wavelength band. The raw material of every "
                        "optical index."),
        ("Tile", "A small square cut out of a large satellite scene. The "
                 "classifier scores one tile at a time."),
        ("p(oil)", "The classifier's score for a tile, between 0 and 1. "
                   "Higher means more oil-like. It is a ranking, not a "
                   "calibrated probability."),
        ("Dispersant", "Chemicals sprayed on a spill to break it into "
                       "droplets. It makes the slick much harder to see "
                       "from a satellite."),
        ("Weathering", "The natural process by which spilled oil spreads, "
                       "evaporates and emulsifies over days, changing how "
                       "it looks to a sensor."),
        ("SITREP", "Situation report — the official document an "
                   "authority issues during an incident. The MSC ELSA 3 "
                   "details come from the Kerala State Disaster Management "
                   "Authority's SITREP-3."),
    ],
    "asked": [
        ("Your detector failed. Why show it?",
         "Because a detector that always answered “no oil” would score "
         "exactly the same on open water as a working one. This replay was "
         "the test that could tell them apart, so the result belongs on "
         "the screen whichever way it came out. A system that published "
         "only its successes would be less informative."),
        ("Does this mean there was no oil?",
         "No, and the page says so. It means our detector did not flag it "
         "on those passes, under those conditions, with a model trained on "
         "a different sea."),
    ],
}

CANDIDATE_REVIEW = {
    "name": "Candidate Review",
    "path": "/app/candidate-review",
    "purpose": "An analyst's workbench over 306 real radar patches from a "
               "published research benchmark — each one scored by the "
               "classifier and presented with its supporting evidence.",
    "see": [
        ("Workflow cards",
         "Total evaluated samples (306), eligible candidates (207), "
         "awaiting review (202), reviewed."),
        ("Sample disposition",
         "Five mutually exclusive buckets that add to 306: 136 under "
         "favourable wind, 70 low-wind ambiguous, 0 high-wind, 1 missing "
         "wind data, 99 where the detector found nothing."),
        ("The candidate list and filters",
         "Every candidate, searchable, with its screening state and review "
         "status."),
        ("The inspection drawer",
         "Opens on the right when you pick a candidate: the radar patch "
         "image, the detection and model scores, the ERA5 wind context, "
         "the Sentinel-2 optical panel, vessel activity nearby, a drift "
         "projection, and the review form."),
    ],
    "working": [
        "The 306 patches come from PANGAEA dataset 980773, a published "
        "Sentinel-1 benchmark of oil slicks in the Eastern Mediterranean, "
        "released under CC BY 4.0. Each is a real 256×256 radar image.",
        "Each patch is matched to ERA5 reanalysis wind for its time and "
        "place. This matters because below about 3 m/s the sea goes flat "
        "by itself and looks exactly like an oil film on radar. Those "
        "candidates are held as ambiguous rather than counted as "
        "detections — which is why the disposition has five buckets "
        "instead of two.",
        "The optical panel beside each candidate is real: six Sentinel-2 "
        "bands plus the scene classification layer, fetched from "
        "Copernicus for that candidate's own position and date, within "
        "five days of the radar pass. Where no cloud-free scene exists in "
        "that window, the panel shows nothing and says why. There is no "
        "generated fallback.",
        "Review decisions are append-only: a decision is added to the "
        "audit trail and never overwrites an earlier one.",
    ],
    "terms": [
        ("Candidate", "One radar patch that has been scored and is waiting "
                      "for a human verdict."),
        ("Benchmark dataset", "A published, labelled dataset that "
                              "researchers use so different methods can be "
                              "compared on the same data."),
        ("CC BY 4.0", "An open licence: you may reuse the data if you "
                      "credit the author."),
        ("Dark formation", "A patch of sea that reflects less radar energy "
                           "than its surroundings. Oil causes this — but "
                           "so do several other things."),
        ("Look-alike", "Anything that makes a dark formation without being "
                       "oil: algae films, rain cells, wind shadows, and "
                       "above all calm water."),
        ("ERA5", "A European reanalysis — a physically consistent "
                 "reconstruction of past weather, used here for wind at "
                 "the moment each patch was taken."),
        ("Collocation", "Matching a weather value to an observation in "
                        "both space and time."),
        ("VV polarisation", "The radar channel that transmits and receives "
                            "vertically. It is the one most sensitive to "
                            "the small surface ripples oil suppresses."),
        ("Triage", "Sorting candidates into groups by how much the "
                   "evidence can support, before any human looks."),
        ("Append-only audit", "A record that is only ever added to. You "
                              "can see what an analyst decided and when, "
                              "and nobody can quietly change it."),
    ],
    "asked": [
        ("Why Mediterranean data in an India project?",
         "Because that is where a published, labelled benchmark exists. "
         "There is no equivalent labelled Sentinel-1 oil set for Indian "
         "waters. We use it to measure the model honestly, and we state "
         "everywhere that its accuracy does not transfer — which is "
         "exactly why retraining on Indian data is the top item of future "
         "work."),
        ("Why is no vessel named?",
         "Deliberately. These are benchmark patches, not confirmed spills. "
         "Naming a real ship as the source of something never established "
         "would be an accusation. The panel shows how busy the water was "
         "— hours and flag states from Global Fishing Watch — and no "
         "identity at all."),
    ],
}

OCEAN_OVERVIEW = {
    "name": "Ocean Overview",
    "path": "/app/overview",
    "purpose": "The command-centre page for the marine half: detections, "
               "sea conditions and vessel traffic across India's exclusive "
               "economic zone, on one screen.",
    "see": [
        ("A scope note at the top",
         "States that the module monitors 15 regions, that every detection "
         "is derived from a measured Sentinel-2 acquisition, and that a "
         "detection means the reading is in the top 1% of that region's "
         "own last 12 months — not a confirmed incident."),
        ("Sea conditions table",
         "Per region: wind speed, gust, wave height, wave period, sea "
         "surface temperature, and a SAR legibility column reading either "
         "“within range” or “low wind — ambiguous”. It shows the "
         "four windiest and four calmest of the 40 regions."),
        ("Vessel activity",
         "Aggregate hours and vessel counts from Global Fishing Watch."),
        ("Model panels",
         "The detector behind the marine numbers and its measured "
         "performance."),
    ],
    "working": [
        "The sea-state figures come from Open-Meteo, fetched per region "
        "and stored. They are labelled INFERRED because a weather model "
        "produced them — nobody measured the wind at that spot.",
        "The SAR legibility column is the physics made visible. Below "
        "3 m/s the sea surface flattens and returns little radar energy, "
        "so a dark patch there carries almost no information. On "
        "24 November, 18 of 40 regions were below that line, and the page "
        "says plainly that any dark formation reported in those regions "
        "today is ambiguous before any model is involved.",
        "Vessel activity is aggregate only — hours and counts by flag "
        "state, never an individual ship.",
    ],
    "terms": [
        ("EEZ", "Exclusive Economic Zone — the belt of sea out to 200 "
                "nautical miles where a coastal state has rights over "
                "resources."),
        ("Region and cell", "A named stretch of the EEZ, subdivided into "
                            "cells with their own bounding boxes. 15 "
                            "regions, 40 cells."),
        ("Gust", "The short peak wind speed, higher than the sustained "
                 "wind."),
        ("Wave period", "Seconds between wave crests. Long periods mean "
                        "swell from far away; short periods mean local "
                        "wind-driven chop."),
        ("SST", "Sea surface temperature."),
        ("SAR legibility", "Our own term for whether the sea state makes "
                           "radar interpretable at all."),
        ("C-band", "The radar wavelength Sentinel-1 uses. It responds to "
                   "centimetre-scale ripples, which is why wind matters so "
                   "much."),
        ("Flag state", "The country a ship is registered in. Vessel "
                       "activity is grouped by this, not by ship."),
    ],
    "asked": [
        ("Why report wind at all on a pollution dashboard?",
         "Because without it a radar detection is uninterpretable. Calm "
         "water and an oil film look the same to the satellite. Showing "
         "the wind is how the page lets you discount a detection that the "
         "physics cannot support."),
    ],
}

LIVE_MONITORING = {
    "name": "Live Monitoring",
    "path": "/app/live",
    "purpose": "The operations view: is the system healthy, what has it "
               "detected most recently, and what state is the pipeline in.",
    "see": [
        ("Four status cards",
         "Service status, stored satellite observations (3,006), the "
         "active detector and its version, and requests logged with the "
         "median response time."),
        ("Recent detections feed",
         "Newest first, as the API returns them: time, signature, region, "
         "confidence, evidence level, severity and risk score."),
        ("Pipeline controls",
         "Run ingestion, Stage-2 refine, Refresh — and a pipeline panel "
         "showing the last health check, whether demo mode is on, and "
         "which environment this is."),
    ],
    "working": [
        "The status cards are read live from the API each time the page "
        "loads. The response-time figure is a true median over logged "
        "requests, not an estimate.",
        "“Demo mode: disabled” is worth pointing at during the "
        "presentation. It is the switch that would let the platform serve "
        "invented records, and it is off.",
        "The pipeline buttons trigger the background jobs. In a "
        "demonstration you would normally not press them, because the "
        "database is already populated and a fetch takes minutes.",
    ],
    "terms": [
        ("Active detector", "Which model version is currently scoring "
                            "tiles. Here sar-oil-slick-v2.2."),
        ("p50", "The median — half of requests were faster than this. "
                "Medians are used instead of averages because a few slow "
                "calls would drag an average."),
        ("Signature", "What kind of thing a detection looks like: algal "
                      "bloom, floating material, turbidity plume."),
        ("Confidence", "The detector's own score for that detection. "
                       "Uncalibrated — a ranking, not a probability."),
        ("Severity", "The band the risk score falls into: LOW, MEDIUM, "
                     "HIGH or CRITICAL."),
        ("Stage-2 refine", "A second pass that narrows a detection to "
                           "sub-cells within a region."),
        ("Environment", "Which deployment this is — development here, "
                        "as opposed to a production server."),
    ],
    "asked": [
        ("What does “demo mode disabled” mean?",
         "That the platform is not allowed to serve invented records. Some "
         "projects keep a demo switch to make the screens look busy. Ours "
         "is off, and the database has zero simulated rows."),
    ],
}

POLLUTION_EVENTS = {
    "name": "Pollution Events",
    "path": "/app/events",
    "purpose": "The full list of detections the platform has raised, "
               "ranked by risk, with the evidence behind each one.",
    "see": [
        ("A scope banner",
         "Repeats that these are statistical anomalies against each "
         "region's own 12-month baseline, not confirmed incidents."),
        ("Filters", "By region, severity and signature."),
        ("The table",
         "One row per detection: signature and region, evidence level, "
         "confidence, affected area in km², risk score, severity band, "
         "and the date detected. 108 rows."),
    ],
    "working": [
        "A detection is raised only when two independent conditions both "
        "hold. First, the reading must be in the top 1% of that region's "
        "own distribution over the preceding twelve months. Second, it "
        "must also exceed an absolute level taken from published research.",
        "Computing the first condition per region, rather than once "
        "globally, is what stops naturally turbid coastal water from being "
        "permanently flagged while a genuine anomaly elsewhere is missed.",
        "Where the research literature publishes no absolute level, the "
        "platform does not invent one. Floating-material detections "
        "therefore rest on the statistical condition alone and are "
        "labelled “relative anomaly only”.",
        "Adding the second condition changed the counts from 41/41/41 to "
        "41 floating material, 35 algal bloom and 32 turbidity. The first "
        "set was describing the method, not the sea.",
    ],
    "terms": [
        ("Baseline", "The distribution of past readings a new reading is "
                     "compared against. Here, twelve months for that "
                     "region."),
        ("Top 1% / p99", "The level that only the highest one per cent of "
                         "a region's own readings exceed."),
        ("Absolute floor", "A fixed level from published research that a "
                           "reading must also clear, regardless of how "
                           "unusual it is locally."),
        ("Algal bloom", "A rapid growth of algae, which discolours water "
                        "and can starve it of oxygen."),
        ("Turbidity plume", "A spreading cloud of suspended sediment, "
                            "often from a river mouth or dredging."),
        ("Floating material", "Material on the surface detected by its "
                              "infrared signature. Never call it plastic — "
                              "the index cannot support that."),
        ("Affected area", "The estimated area of the anomaly in square "
                          "kilometres."),
        ("Relative anomaly only", "The label for a detection that passed "
                                  "the statistical test but had no "
                                  "citable absolute level to clear."),
    ],
    "asked": [
        ("Is that 108 real pollution incidents?",
         "No, and the banner says so. They are 108 readings that were both "
         "unusual for their own region and past a level from published "
         "research. Nobody has gone out and confirmed any of them."),
        ("Why can you not call floating material plastic?",
         "Because the paper that defines the index publishes no threshold "
         "for it, and classifies using a trained model over two indices "
         "rather than a cut-off. We checked the paper. Saying plastic "
         "would be a claim the method cannot support."),
    ],
}

OCEAN_MAP = {
    "name": "Ocean Map",
    "path": "/app/ocean-map",
    "purpose": "Everything the marine module knows, drawn on one map of "
               "India's exclusive economic zone.",
    "see": [
        ("A header line",
         "36 monitored cells, 34 with an active detection, 60,403 "
         "vessel-hours, 100 Sentinel-1 tiles screened, 40 current sea-state "
         "fields."),
        ("Two notes",
         "One repeating the statistical-anomaly scope, one stating that "
         "every layer on this map is real and naming the source of each."),
        ("The map and its layer switcher",
         "Toggles for observed cells, stage-2 refined sub-cells, vessel "
         "activity, surface currents, chlorophyll, the historical incident "
         "replay, the benchmark dataset, and the screened Sentinel-1 "
         "tiles."),
        ("A scene selector and severity filter",
         "Pick one real radar acquisition, or show all; filter by minimum "
         "severity."),
    ],
    "working": [
        "The rectangles are the tiles the classifier actually ran on, at "
        "their real footprints, coloured by whether the detector flagged "
        "them. None are flagged, so none are red.",
        "The circles are detections from measured Sentinel-2 readings, "
        "sized and coloured by severity.",
        "Currents and chlorophyll come from Copernicus Marine; vessel "
        "activity from Global Fishing Watch. The benchmark layer, off by "
        "default, is the Mediterranean PANGAEA set — kept separate so it "
        "is never mistaken for Indian data.",
    ],
    "terms": [
        ("Layer", "One switchable set of things drawn on the map."),
        ("Footprint", "The real ground area a satellite tile covers, drawn "
                      "at its true position."),
        ("Surface current", "Modelled water movement at the surface, from "
                            "Copernicus Marine. Used to drive the drift "
                            "projection."),
        ("Chlorophyll-a", "The green pigment in algae. An independent "
                          "Copernicus Marine product used to cross-check "
                          "our own algal index."),
        ("Stage-2 refined sub-cell", "A narrower area inside a region, "
                                     "produced by a second analysis pass."),
        ("Scene", "One satellite acquisition. The selector lets you look "
                  "at the tiles from a single pass."),
    ],
    "asked": [
        ("Which parts of this map are made up?",
         "None. The note at the top names the source of every layer. The "
         "demonstration overlay that used to be here was replaced by the "
         "100 tiles that were really screened."),
    ],
}

FORECASTS = {
    "name": "Forecasts",
    "path": "/app/forecasts",
    "purpose": "Short-horizon projections of detection activity or a "
               "measured satellite index, with an honest comparison "
               "against the simplest possible alternative.",
    "see": [
        ("Selectors", "Region, forecasting method, what to forecast, and "
                      "the horizon — 1, 10, 14 or 21 days."),
        ("The chart", "Observed history to the left of the divider, "
                      "projection to the right, with an 80% prediction "
                      "interval shaded."),
        ("A verdict line",
         "States the method, how many observations it was fitted on, the "
         "backtest error against the naive baseline, and in plain words "
         "whether it beat it."),
        ("A table of projected values",
         "Per day: the value, its severity band, and the interval."),
    ],
    "working": [
        "The method is Holt linear damped: it models a level and a trend "
        "and damps the trend as the horizon lengthens, so it does not "
        "extrapolate a straight line forever.",
        "Every forecast is backtested against the naive baseline — the "
        "prediction that tomorrow equals today. On Odisha Coast W the "
        "forecaster's error is 0.176 against the baseline's 0.176, and the "
        "page prints “does NOT beat the naive baseline” in those words.",
        "Across all 40 regions it beats the baseline in none of them, and "
        "every chart says so. The page also states what is being forecast: "
        "the platform's own detection activity, not the physical movement "
        "of a pollutant.",
    ],
    "terms": [
        ("Horizon", "How far ahead the forecast goes."),
        ("Holt linear damped", "A standard forecasting method with a level "
                               "term, a trend term, and a damping factor "
                               "that flattens the trend over time."),
        ("Naive baseline", "The simplest possible forecast: tomorrow will "
                           "be the same as today. A method that cannot "
                           "beat this has not earned its complexity."),
        ("Backtest", "Running the method over history you already have, so "
                     "you can measure how wrong it would have been."),
        ("MAE", "Mean absolute error — the average size of the mistakes, "
                "in the same units as the thing forecast. Lower is "
                "better."),
        ("Prediction interval", "The shaded band expected to contain the "
                                "true value 80% of the time. It widens "
                                "with the horizon."),
    ],
    "asked": [
        ("Your forecaster loses to “tomorrow equals today”. Why keep it?",
         "Because the comparison is the finding. Most dashboards show a "
         "forecast line with no baseline at all, so you cannot tell "
         "whether it is doing anything. Ours tells you, on every chart, "
         "that it is not — which is more useful than a confident line "
         "nobody checked."),
    ],
}

RISK_ANALYSIS = {
    "name": "Risk Analysis",
    "path": "/app/risk",
    "purpose": "How a detection turns into a 0-100 risk score, broken "
               "down so that every point can be traced back to a rule.",
    "see": [
        ("A selector", "Pick any detection."),
        ("The score dial", "The number out of 100, its severity band, its "
                           "evidence level, the region, and the engine "
                           "version."),
        ("A partial-assessment warning",
         "Shown when a factor could not be evaluated, stating that the "
         "score was renormalised over the factors that could be."),
        ("Contribution breakdown",
         "A stacked bar and a list: each factor, the points it earned out "
         "of its maximum, and a sentence explaining why."),
    ],
    "working": [
        "The engine distributes 100 points across six factors: signature "
        "severity 20, affected area 20, detection confidence 15, coastal "
        "proximity 15, protected-area proximity 15, historical trend 15.",
        "It is deterministic — a fixed formula, no model involved — so "
        "the same inputs always give the same score and every point is "
        "reconstructible. The weights are a documented product judgement, "
        "and the code says so rather than pretending they are physical "
        "constants.",
        "If a factor cannot be evaluated, the score is computed over the "
        "rest and rescaled, with the page saying it is partial. The "
        "alternative — scoring the unknown as zero — would make an "
        "unmeasured event look safe, which is the failure this behaviour "
        "exists to prevent.",
    ],
    "terms": [
        ("Deterministic", "Produced by a fixed formula, so the same inputs "
                          "always give the same output."),
        ("Factor", "One of the six things the score is built from."),
        ("Weight", "The maximum points a factor can contribute."),
        ("Renormalisation", "Rescaling a score computed over fewer factors "
                            "so it is still out of 100."),
        ("Receptor", "Something that would be harmed if pollution reached "
                     "it — a fishery, a mangrove, a protected reserve."),
        ("Protected-area proximity", "How close the detection is to a "
                                     "protected area. Currently measured "
                                     "to 28 curated points rather than "
                                     "true boundaries, which the page "
                                     "states."),
        ("Historical trend", "Whether risk in that region has been rising "
                             "or falling, in risk points per day."),
    ],
    "asked": [
        ("Why not use a model to score risk?",
         "Because then nobody could ask why. With a fixed formula an "
         "examiner can point at any factor and we can show the "
         "arithmetic."),
        ("What does “partial assessment” mean?",
         "That one of the six factors had no data, so the score was "
         "computed over the others and rescaled. We show it rather than "
         "silently scoring the missing factor as zero, which would make "
         "the event look safer than we know it to be."),
    ],
}

KNOWLEDGE_GRAPH = {
    "name": "Knowledge Graph",
    "path": "/app/knowledge-graph",
    "purpose": "The platform's own records drawn as a network, so you can "
               "see what is genuinely connected to what.",
    "see": [
        ("Controls", "Centre the graph on a region, and choose how many "
                     "hops out to draw."),
        ("The graph", "Nodes coloured by type — region, pollution event, "
                      "risk assessment — with the centre node in the "
                      "middle."),
        ("A legend", "Counts per node type, and a note on what the edges "
                     "mean."),
    ],
    "working": [
        "Only relationships the database actually declares are drawn. "
        "Solid edges are foreign keys; dashed edges are citations resolved "
        "from report sources. Nothing is inferred from names being similar "
        "or things being near each other.",
        "That restraint produces a visible gap: the SAR candidates are not "
        "connected to the regions, because the candidates table declares "
        "no foreign key to them. Drawing an edge there would mean "
        "inventing one, which is the single thing this graph exists not to "
        "do.",
        "The legend reports unresolved citations, which is currently zero "
        "— every citation in every report points at something that "
        "actually exists.",
    ],
    "terms": [
        ("Node", "One record — a region, an event, an assessment."),
        ("Edge", "A link between two records."),
        ("Hop", "One step along an edge. Two hops means neighbours and "
                "their neighbours."),
        ("Foreign key", "A database link: a column in one table that "
                        "points at a row in another. The only kind of "
                        "relationship this graph will draw as solid."),
        ("Unresolved citation", "A citation in a report that points at "
                                "something that cannot be found. Zero of "
                                "these."),
    ],
    "asked": [
        ("Why are the radar candidates not connected to anything?",
         "Because in the database they genuinely are not. They have no "
         "foreign key to a region. We could have drawn a line based on "
         "position, but that would be inventing a relationship — and this "
         "graph is built to show only what is declared."),
    ],
}

RAG_RESEARCH = {
    "name": "RAG Research",
    "path": "/app/research",
    "purpose": "A question-answering assistant over marine-pollution "
               "regulations and this platform's own methodology notes, "
               "which answers only from documents it retrieved.",
    "see": [
        ("A question box with a source filter",
         "All sources, Regulations, Methodology or Research."),
        ("Suggested questions",
         "Such as “What rules govern oil discharge from ships?” or "
         "“What are the look-alikes for oil in SAR imagery?”"),
        ("Knowledge corpus panel",
         "What the assistant can draw on: 22 documents, 31 retrievable "
         "passages, 16 regulation and 6 reference, plus the retriever and "
         "reranker it uses."),
    ],
    "working": [
        "RAG means retrieval-augmented generation: find relevant passages "
        "first, then answer only from them. The alternative is letting a "
        "model answer from memory, which is where invented citations come "
        "from.",
        "The retriever is BM25, a long-established lexical ranking method "
        "that scores passages by term overlap with the question. The "
        "reranker then reorders candidates using features such as title "
        "overlap, exact phrase matches, region and document type.",
        "The corpus panel is deliberately blunt about its own limits: "
        "regulation documents carry factual metadata with "
        "platform-authored scope summaries rather than verbatim legal "
        "text, reference documents are our own methodology notes, and the "
        "corpus contains no journal literature — none is invented to fill "
        "the gap.",
    ],
    "terms": [
        ("RAG", "Retrieval-augmented generation. Retrieve first, answer "
                "only from what was retrieved."),
        ("Corpus", "The body of documents the assistant can search."),
        ("Passage", "A chunk of a document, small enough to retrieve and "
                    "cite precisely."),
        ("Retriever", "The component that finds candidate passages."),
        ("BM25", "A classic ranking formula that scores a passage by how "
                 "many of the question's words it contains, weighted so "
                 "common words count for less."),
        ("Lexical", "Based on the words themselves, rather than on learned "
                    "meaning. Transparent and cheap."),
        ("Reranker", "A second pass that reorders the retriever's "
                     "candidates using extra features."),
        ("Grounded", "Said of an answer that can be traced to retrieved "
                     "text."),
        ("MARPOL", "The international convention for the prevention of "
                   "pollution from ships. Annex I covers oil; Annex V "
                   "covers garbage including plastics."),
    ],
    "asked": [
        ("Is this corpus big enough to be useful?",
         "It is a seed set of 22 documents, and the page says so on "
         "itself. The point of the page is the mechanism — retrieve, "
         "rerank, answer only from sources, refuse otherwise — and that "
         "the corpus does not quietly pretend to contain research "
         "literature it does not have."),
    ],
}

AGENT_ANALYSIS = {
    "name": "Agent Analysis",
    "path": "/app/agents",
    "purpose": "Run an automated analysis over one detection: gather its "
               "evidence, assess it, and produce a structured report.",
    "see": [
        ("A list of detections", "Each shown as signature, region and risk "
                                 "score. Pick one to analyse."),
        ("The workflow", "Five stages, which run in order and then stop."),
        ("The result", "The evidence gathered, the assessment, and a link "
                       "to the report it produced."),
    ],
    "working": [
        "The workflow is bounded: five stages, a fixed maximum number of "
        "tool calls, and agents that never call each other. That is a "
        "deliberate design limit — an agent that can call other agents "
        "can loop indefinitely and run up a bill with nothing to show.",
        "Each stage reads from the database rather than from the open "
        "internet, so a run is reproducible: the same detection produces "
        "the same evidence.",
        "The output is a report sectioned by evidence level, so what was "
        "observed stays separate from what was detected and what was "
        "inferred.",
    ],
    "terms": [
        ("Agent", "A program that carries out a multi-step task by "
                  "choosing which tools to call."),
        ("Tool call", "One action an agent takes — querying the "
                      "database, computing a score."),
        ("Bounded", "Limited in advance. Here: a fixed number of stages "
                    "and tool calls."),
        ("Workflow", "The fixed sequence of stages a run goes through."),
        ("Reproducible", "Running it again on the same input gives the "
                         "same result."),
    ],
    "asked": [
        ("Is this an AI agent like the ones in the news?",
         "It is the same idea, deliberately constrained. It has five "
         "stages, a hard cap on tool calls, and it cannot spawn other "
         "agents. It reads our database rather than the open web, so its "
         "output is reproducible."),
    ],
}

REPORTS = {
    "name": "Reports",
    "path": "/app/reports",
    "purpose": "The written outputs: one report per detection, organised "
               "so that the strength of each claim is visible.",
    "see": [
        ("A list of reports", "One per detection, labelled by signature "
                              "and region."),
        ("The report body",
         "Sections by evidence level: what was observed, what was "
         "detected, what was inferred — kept apart rather than blended "
         "into a narrative."),
        ("An AI-generated summary",
         "A short prose paragraph, labelled as such, with the model name "
         "shown."),
    ],
    "working": [
        "The structure is the output. No language model decides what goes "
        "in which section — that comes from the evidence level stored on "
        "each value.",
        "The prose summary is generated once by Gemini, checked against "
        "the stored evidence figure by figure before being saved, and "
        "cached in the database. It is never generated when you open the "
        "page, so the numbers in it cannot drift from the data.",
        "Nothing in the platform depends on that prose. Delete it and "
        "every conclusion still stands.",
    ],
    "terms": [
        ("Evidence-level sectioning", "Organising a document by how "
                                      "strongly each claim is supported, "
                                      "rather than by topic."),
        ("Gemini", "Google's large language model, used here only to write "
                   "the summary paragraph."),
        ("Cached", "Computed once and stored, rather than recomputed on "
                   "every view."),
        ("Number-checked", "Each figure in the generated prose was "
                           "compared against the stored evidence before "
                           "the text was saved."),
    ],
    "asked": [
        ("Is the AI making things up?",
         "The prose is labelled as AI-generated and names the model. Every "
         "figure in it was verified against the stored evidence before it "
         "was saved, and no decision in the platform depends on it. The "
         "report's actual content is the evidence-level sections, which no "
         "model writes."),
    ],
}

MODEL_PERFORMANCE = {
    "name": "Model Performance",
    "path": "/app/models",
    "purpose": "How well the oil-slick classifier actually performs, "
               "measured rather than claimed, and recomputed in front of "
               "you.",
    "see": [
        ("Three cards", "Registered models (5), evaluated models (3), "
                        "median inference time (49.41 ms)."),
        ("Confusion matrix",
         "Four counts at the current threshold: 136 true positive, 18 "
         "missed slick, 71 false alarm, 81 true negative."),
        ("Metric list", "Precision 65.7%, recall 88.3%, F1 0.753, "
                        "false-positive rate 46.7%."),
        ("ROC curve", "With AUC 0.771 and a dashed diagonal marking "
                      "chance."),
        ("A threshold slider", "Move it and the matrix and metrics "
                               "recompute."),
        ("The model registry below", "Each registered model, its version, "
                                     "and its metrics or a null."),
    ],
    "working": [
        "The matrix and metrics are computed live from the 306 stored "
        "benchmark candidates, not read from a saved result.",
        "Because they cover all 306, they differ slightly from the "
        "registry card, which reports a 100-sample test split. The page "
        "explains that rather than hiding it — neither is wrong, they "
        "are different samples.",
        "An unevaluated model reports null and renders as “Not "
        "evaluated”. It never renders as zero, which a reader would "
        "mistake for a measured failure.",
    ],
    "terms": [
        ("Classifier", "A model that sorts inputs into categories — here, "
                       "oil-like or not."),
        ("True positive", "Oil, and the model said oil."),
        ("False positive / false alarm", "Clean sea, and the model said "
                                         "oil."),
        ("True negative", "Clean sea, and the model said clean."),
        ("False negative / missed slick", "Oil, and the model missed it."),
        ("Precision", "Of everything called oil, how much really was oil. "
                      "Answers: can I trust an alarm?"),
        ("Recall", "Of all the real oil, how much was found. Answers: how "
                   "much do I miss?"),
        ("F1", "A single number balancing precision and recall. It "
               "punishes a model that is good at one and bad at the "
               "other."),
        ("False-positive rate", "Of all the clean sea, how much was "
                                "wrongly flagged."),
        ("Threshold", "The score above which an output counts as "
                      "positive. Choosing it is a decision about which "
                      "error is worse."),
        ("ROC curve", "A plot of recall against false-positive rate as the "
                      "threshold sweeps across its whole range."),
        ("AUC", "Area under that curve. 1.0 is perfect, 0.5 is chance. It "
                "summarises ranking ability independently of any one "
                "threshold."),
        ("Uncalibrated", "The model's scores rank well but do not mean "
                         "probabilities. A 0.9 does not mean 90%."),
        ("Inference", "One run of the model on one input."),
    ],
    "asked": [
        ("A 46.7% false-positive rate sounds bad. Why show it?",
         "Because it is true. Nearly half of clean sea gets flagged at "
         "this threshold, which is the clearest single argument for why "
         "the model must be retrained on Indian data before anyone relies "
         "on it. Hiding it would make the project less useful, not more "
         "impressive."),
        ("Why do the numbers here differ from the model card?",
         "Different samples. This page computes over all 306 candidates; "
         "the card reports the 100-sample held-out test split. The page "
         "says so underneath."),
    ],
}

DRIFT_MONITORING = {
    "name": "Drift Monitoring",
    "path": "/app/drift",
    "purpose": "Watching whether the data the model sees today still looks "
               "like the data it was measured on — because if not, its "
               "measured accuracy stops meaning anything.",
    "see": [
        ("Window selectors", "A baseline window and a current window, here "
                             "30 days against 7 days."),
        ("Three cards", "Overall status, minimum samples per window (30), "
                        "and the thresholds (0.1 warning, 0.25 drift)."),
        ("The checks table",
         "One row per metric watched — mean confidence and predicted "
         "class distribution — with its PSI value, the sample count in "
         "each window, and a verdict."),
        ("A retraining-policy note",
         "Stating that drift flags for human review and never triggers "
         "retraining automatically."),
    ],
    "working": [
        "PSI, the Population Stability Index, measures how far one "
        "distribution has moved from another. Both are divided into bins, "
        "and the differences are summed. Conventionally below 0.1 is "
        "stable, 0.1 to 0.25 is some shift, above 0.25 is significant.",
        "On 24 November, with a 30-day baseline against a 7-day current "
        "window, PSI was 1.33 on mean confidence and 1.15 on predicted "
        "class distribution — well past the drift line. The verdict reads "
        "“drift detected”.",
        "The windows must not overlap, or the comparison is partly against "
        "itself. A minimum of 30 samples per window is required before a "
        "verdict means anything.",
        "The panel states plainly that the inferences are real but the "
        "window timestamps are assigned rather than live traffic, because "
        "all the inferences ran within seconds of each other and drift "
        "compares time windows.",
    ],
    "terms": [
        ("Drift", "When the data a model sees stops resembling the data it "
                  "was trained and measured on."),
        ("PSI", "Population Stability Index — the number measuring that "
                "shift."),
        ("Baseline window", "The earlier period, treated as the reference."),
        ("Current window", "The recent period being compared against it."),
        ("Bin", "One slice of the value range. PSI compares how much of "
                "each distribution falls in each slice."),
        ("Predicted class distribution", "The mix of outputs the model is "
                                         "producing — how often it says "
                                         "oil versus clean."),
        ("Mean confidence", "The average score the model is producing. A "
                            "shift here means it has become systematically "
                            "more or less certain."),
    ],
    "asked": [
        ("Your monitor says drift detected. Is the model broken?",
         "It means the inputs have shifted far enough that the measured "
         "accuracy is no longer a safe guide. That is the monitor working. "
         "We did not tune it away — a green light here would have been "
         "easy to arrange and worth nothing."),
        ("Why not retrain automatically?",
         "Because drift is a symptom with several possible causes: a "
         "seasonal change in sea state, a change to which regions we "
         "monitor, or a bug in preprocessing. Retraining automatically on "
         "the last of those bakes the bug into the weights. So it flags "
         "for a human."),
    ],
}

EXPERIMENTS = {
    "name": "Experiments",
    "path": "/app/experiments",
    "purpose": "Where training-run tracking would live. It is empty, and "
               "the page explains why rather than showing a placeholder.",
    "see": [
        ("An explanatory panel",
         "“Experiment tracking — not available”, stating that this "
         "deployment exposes no experiment-tracking endpoint, that the "
         "backend records model versions and their evaluated metrics but "
         "does not yet track training runs, hyperparameter sweeps or run "
         "comparisons."),
        ("The planned next step",
         "MLflow integration, with a note that the model_versions table is "
         "deliberately shaped to map onto it."),
        ("A link", "To Model Performance, where the registered models and "
                   "their measured metrics actually are."),
    ],
    "working": [
        "There is nothing to compute here. The page exists because the "
        "navigation promises it, and an empty page that explains itself is "
        "more honest than a chart of invented runs.",
        "This is worth presenting rather than skipping. An examiner who "
        "clicks it will find a clear statement of a known gap and the "
        "intended fix, which is a better answer than a page that quietly "
        "shows nothing.",
    ],
    "terms": [
        ("Experiment tracking", "Recording each training run with its "
                                "settings and results, so runs can be "
                                "compared."),
        ("Hyperparameter", "A setting chosen before training — learning "
                           "rate, batch size — as opposed to a weight the "
                           "model learns."),
        ("Sweep", "Training many times across a range of hyperparameters "
                  "to find a good combination."),
        ("MLflow", "A widely used open-source tool for experiment tracking "
                   "and model registry."),
        ("Endpoint", "One address in the API that answers a particular "
                     "kind of request."),
    ],
    "asked": [
        ("Why ship a page that does not work?",
         "It does work — it reports accurately that the capability is not "
         "built, names what is missing, and says what would fill it. The "
         "alternative is a page showing fabricated training runs, which "
         "would be worse than an empty one."),
    ],
}

RETRAINING = {
    "name": "Retraining",
    "path": "/app/retraining",
    "purpose": "The policy for what happens when drift is detected, and "
               "the current state of the trigger.",
    "see": [
        ("A policy panel",
         "“Not configured — by design”, explaining that drift raises a "
         "flag for human review and never triggers retraining on its own."),
        ("Current model",
         "Name and version, deployment status, dataset version, and "
         "whether it has been evaluated. Here: sar-dark-formation 1.0.0, "
         "Production, never evaluated."),
        ("Trigger state", "The current drift verdict and the policy that "
                          "applies to it."),
    ],
    "working": [
        "The reasoning is printed on the page: drift is a symptom with "
        "several causes — a seasonal shift in sea state, a change to the "
        "monitored regions, or an upstream preprocessing bug. Retraining "
        "automatically on the last of those bakes the bug into the "
        "weights.",
        "A retraining candidate is raised only after a sustained drift "
        "signal has been reviewed and the input pipeline verified. Then it "
        "is run deliberately, against a new dataset version.",
        "Note that the model shown here as Production is "
        "sar-dark-formation 1.0.0 and is recorded as never evaluated, "
        "while the experimental sar-oil-slick-v2.2 is the one with "
        "measured metrics. The platform reports both states accurately "
        "rather than promoting the experimental model to look better.",
    ],
    "terms": [
        ("Retraining", "Training a model again, usually on newer or "
                       "corrected data."),
        ("Trigger", "The condition that would start a retraining run."),
        ("Dataset version", "A specific frozen snapshot of training data, "
                            "so a model can be tied to exactly what it "
                            "learned from."),
        ("Production", "The deployment state meaning this is the model in "
                       "real use, as opposed to experimental."),
        ("Human in the loop", "A design where a person must approve a "
                              "consequential step."),
        ("Input pipeline", "The chain of code that prepares data before "
                           "the model sees it. A bug here looks exactly "
                           "like drift."),
    ],
    "asked": [
        ("Why is the production model never evaluated?",
         "Because it never was, and the page says so rather than showing a "
         "zero or borrowing another model's numbers. The model with "
         "measured metrics is the experimental v2.2, and the registry "
         "keeps those facts separate."),
    ],
}

GROUPS = [
    ("India Water Intelligence",
     "The freshwater half of the platform. Five pages covering what is "
     "known about India's rivers and lakes, where it is, how it is judged, "
     "how to ask questions of it, and where it all came from.",
     [INDIA_OVERVIEW, WATER_MAP, ASK_WATER, REFERENCE_STANDARDS,
      DATA_SOURCES]),

    ("Marine Monitoring",
     "The sea half. Six pages covering satellite measurements over India's "
     "exclusive economic zone, the detections derived from them, the radar "
     "benchmark, and the map that ties it together.",
     [REAL_OBSERVATIONS, CANDIDATE_REVIEW, OCEAN_OVERVIEW, LIVE_MONITORING,
      POLLUTION_EVENTS, OCEAN_MAP]),

    ("Intelligence",
     "What the platform does with a detection once it has one: project it "
     "forward, score it, and link it to everything else it knows.",
     [FORECASTS, RISK_ANALYSIS, KNOWLEDGE_GRAPH]),

    ("AI Research",
     "The language and automation layer: grounded question answering over "
     "documents, a bounded analysis workflow, and the written reports it "
     "produces.",
     [RAG_RESEARCH, AGENT_ANALYSIS, REPORTS]),

    ("Machine Learning",
     "The model itself: how it is measured, how it is watched for decay, "
     "and two pages that honestly report capabilities that are not built.",
     [MODEL_PERFORMANCE, DRIFT_MONITORING, EXPERIMENTS, RETRAINING]),
]

# ===========================================================================
# Closing material
# ===========================================================================

NUMBERS = [
    ("4,601,509", "water-quality measurements (CPCB and CWC)"),
    ("2,740 / 4,951", "water bodies / monitoring stations"),
    ("35 / 613", "states and union territories / districts"),
    ("3,006", "Sentinel-2 index readings, 36 of 40 regions, 12 months"),
    ("108", "detections — 41 floating material, 35 algal bloom, "
            "32 turbidity"),
    ("25", "of those detections in the CRITICAL band"),
    ("306", "benchmark Sentinel-1 radar patches (PANGAEA 980773)"),
    ("100", "Sentinel-1 tiles screened live, 0 oil detections"),
    ("60,403", "vessel-hours from Global Fishing Watch, 25 of 40 regions"),
    ("15 / 40", "marine regions / monitoring cells across India's EEZ"),
    ("0.771", "ROC AUC of the classifier, computed live"),
    ("65.7% / 88.3%", "precision / recall at threshold 0.50"),
    ("46.7%", "false-positive rate — reported, not hidden"),
    ("1.33", "PSI on mean confidence — drift detected"),
    ("0 of 40", "regions where the forecaster beats the naive baseline"),
    ("0", "simulated rows in the database"),
    ("868", "automated tests passing"),
]

NEVER_SAY = [
    ("Never say a detection is a confirmed pollution incident.",
     "Say it is a statistical anomaly against that region's own 12-month "
     "baseline that also cleared a level from published research."),
    ("Never call floating material plastic.",
     "The index that detects it has no published threshold and the paper "
     "classifies with a trained model, not a cut-off. Say “floating "
     "material”."),
    ("Never name a vessel as the source of anything.",
     "Our detections are benchmark patches and anomalies. Say the platform "
     "shows aggregate vessel activity — hours and flag states — and no "
     "identities at all."),
    ("Never say the model is accurate for Indian waters.",
     "It was measured on a Mediterranean benchmark. Say its measured "
     "accuracy does not transfer, and that retraining on Indian data is "
     "the top item of future work."),
    ("Never say the sync-paused sources are down.",
     "The server answers and a firewall refuses automated clients with "
     "HTTP 403. Say we are being refused, not that the source is out."),
    ("Never say a figure is live if it came from the database.",
     "Say the data is real and was really fetched, that background jobs "
     "write it, and that the page reads the database."),
]

THREE_ANSWERS = [
    ("The detector found nothing over a real wreck.",
     "Four Sentinel-1 passes over the MSC ELSA 3 sinking, nothing flagged. "
     "It is published with the reasons it is weak evidence — 9.3 m/s "
     "wind on the first pass, dispersant applied, oil weathering, model "
     "off-distribution. The point: a detector that always said no would "
     "have scored identically, so this was the test that could tell them "
     "apart."),
    ("The forecaster beats the naive baseline in none of 40 regions.",
     "And every chart says so in those words. Most dashboards show a "
     "forecast line with no baseline at all, so nobody can tell whether it "
     "is doing anything. Ours tells you."),
    ("The drift monitor is reporting drift.",
     "PSI 1.33 against a threshold of 0.25. That is the monitor working. "
     "It flags for a human and never retrains on its own, because drift "
     "can be caused by a preprocessing bug and retraining would bake the "
     "bug in."),
]
