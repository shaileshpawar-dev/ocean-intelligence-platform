# Demo script — 25 November 2026

Ten to twelve minutes. Every number below was read off the running
application on **21 November after a clean restart**. If a figure on screen
does not match, say so rather than talking over it — the platform's whole
argument is that it reports what it has.

**Before you start**

```bash
docker compose up -d backend
```

Open `http://localhost:8000/app/india`. If anything looks wrong, run
`scripts/reset_demo.sh` — about a minute.

The caches the real-data pages read are inside the container's data volume
and survive a restart. To refresh them against the live services (optional,
and not needed for the demo):

```bash
python scripts/fetch_marine_conditions.py   # ~10 s
python scripts/fetch_gfw_activity.py        # ~3 min
python scripts/fetch_sentinel2_indices.py   # ~15 min
python scripts/fetch_cmems.py               # ~25 min
```

**The one-sentence framing, if you only get one:** *this platform separates
what was measured from what was inferred, and refuses to state anything it
cannot support — including when that makes it look worse.*

**What is real, in one list.** Worth having straight before you start, because
it is the first thing you will be asked:

| Layer | Source | Evidence | Status |
|---|---|---|---|
| India water quality | CPCB real-time analysers | OBSERVED | **Live** — 19 of 2,740 water bodies have a reading from the last 2 days |
| India water quality (historic) | CPCB / CWC via NWDP | OBSERVED | 2.7M readings to 2025; the two NWDP feeds are **down** (expired certificate) and say so |
| Water-quality indices | Sentinel-2 L2A via Copernicus | OBSERVED | **Live** — 253 readings, 35 of 40 regions, newest 20 Nov |
| Chlorophyll cross-check | Copernicus Marine ocean colour | OBSERVED | **Live** — all 35 regions |
| Sea conditions | Open-Meteo | INFERRED | **Live** — all 40 regions |
| Surface currents | Copernicus Marine physics | INFERRED | **Live** — all 40 regions, drives drift |
| Vessel activity | Global Fishing Watch | INFERRED | **Live** — 60,403 vessel-hours |
| SAR benchmark candidates | PANGAEA 980773 (CC BY 4.0) | MEASURED | 306 patches, real |
| Pollution events, vessel suspects | Demonstration data | SIMULATED | Labelled on every page |

---

## 1 · India Water Intelligence — the core (2 min)

### 1a. India Overview — `/app/india`

**On screen:** 2,740 water bodies · 4,951 monitoring stations ·
**4,601,509 observations** · Current data **19** · Recent data **7** ·
Historical only **2,714** · 35 states · 613 districts.

**Say this, it is new and it is the strongest line on the page:**

> "Nineteen water bodies have a reading from the last two days. Until
> yesterday that number was zero — CPCB's real-time analysers were being
> reported as unreachable, and that turned out to be a missing root
> certificate on this laptop rather than anything wrong at CPCB. One
> machine's trust gap had been recorded as a national outage. The newest
> reading in there now is from this morning."

> "This is real data — four and a half million parameter measurements from
> CPCB and CWC, covering 2,740 water bodies across all 35 states and union
> territories. The most important number is the one that looks worst:
> **zero** water bodies have data recent enough to describe them today."

> "That is not a bug. CPCB's hourly analysers on the Ganga were last ingested
> on 26 September; 26 water bodies are still within 90 days, and the other
> 2,714 come from manual programmes whose published extracts mostly stop in
> 2021. The platform refuses to describe present condition from a 2021
> sample, so it says so instead of showing you a green tick."

Point at the three cards summing to 2,740 — current + recent + historical.

### 1b. A water body — `/app/water/ganga-river`

**On screen:** 142 stations · 347,672 observations · latest 26 Sep 2026 ·
"Current condition: Cannot be established from this dataset" ·
"54 days ago. That is too old…" · Real-time data **No** · Historical **Yes,
3 sources** · Latest measured status **High concern**.

> "Three separate sources measure the Ganga and the platform keeps them apart
> — it never averages CPCB's manual programme with CWC's. It will tell you
> the last measured status was High concern, and in the same breath that this
> is a reading from 26 September, not a statement about today."

Scroll to **Why this status?** — the faecal coliform rule, the limit it
exceeded, and the standard it came from.

> "Every status is a stated rule over named parameters against a cited
> standard. Nothing here is a model's opinion."

### 1c. Ask about water — `/app/ai` *(optional, if time)*

Click **"What is the latest available status of Mithi River?"**

**On screen:** headline *"Mithi River: High concern as of 02 Dec 2021. Right
now: no recent data…"*, 5 citations, a limitations note.

> "This is retrieval over the stored observations, not a language model — five
> citations, every figure dated. It answers 'high concern in 2021' and
> refuses 'high concern now'."

---

## 2 · Candidate Review — the real marine data (1.5 min)

`/app/candidate-review` *(first item under Marine Monitoring)*

**On screen:** 306 evaluated samples · 207 eligible · 202 awaiting review ·
5 reviewed. Disposition: **136 + 70 + 0 + 1 + 99 = 306**.

> "Everything else in the marine module is simulated and labelled as such.
> This is not: 306 real Sentinel-1 patches from a peer-reviewed benchmark —
> PANGAEA 980773, CC BY 4.0 — each collocated with real ERA5 wind."

> "The triage funnel accounts for every sample exactly once: 136 under
> favourable wind, 70 ambiguous because the sea was too calm to trust,
> 1 with no wind data, and 99 where the detector found nothing. Low wind
> makes oil and calm water look alike on radar, so those are held for review
> rather than counted as detections."

---

## 2b · Real Satellite Observations — `/app/real-observations` (2 min)

**The strongest page in the marine half. Do not rush it.**

Open it. Point at the green **Real · Sentinel-2** badge and the **OBSERVED**
tile.

> "253 readings over 35 of our 40 regions. The newest was acquired on the
> 20th — yesterday. These are not a demonstration: Copernicus computed them
> from actual Sentinel-2 scenes, and only from pixels the scene
> classification layer marks as water, so a coastal cell reports on its sea
> rather than on the land in frame."

Point at a thumbnail.

> "That is the scene the numbers in that row came from. Not a stock image —
> the actual pass, on the actual date."

**Then the part that matters.** Scroll to a dimmed row — Bay of Bengal Z6,
Gulf of Khambhat, Lakshadweep Sea NE or Odisha Coast W.

> "Four rows have no numbers. The satellite did pass over, but the cell was
> almost entirely cloud — one of these was computed from a single water
> pixel. The arithmetic works fine; it describes nothing. One of them gave a
> floating-material index ten times every other cell, which is exactly the
> figure that would become a headline. Below a hundred water pixels the page
> prints a dash."

**If they ask about the FDI column — and they will:**

> "Floating Debris Index. It responds to anything floating that is brighter
> in the near-infrared than the water around it. The paper that defines it
> cannot separate plastic from seaweed, foam, timber or spume without
> further spectral analysis, and sun glint raises it too. So it says
> *possible floating material*. The word plastic appears on this page only
> where it is being ruled out."

**The Chl-a column:**

> "Chlorophyll twice, deliberately. NDCI is a two-band ratio we compute here
> from raw reflectance. The Chl-a column is Copernicus Marine's validated
> multi-sensor retrieval of the same quantity. Neither is adjusted to agree
> with the other — where they track together our cheap measure is worth
> something, and where they diverge, that is the useful part."

---

## 2c · Ocean Overview — live sea state and traffic (1.5 min)

`/app/overview`, scroll to **Sea conditions**.

> "Wind, waves and sea-surface temperature for all forty regions, from
> Open-Meteo. Labelled INFERRED, not OBSERVED — it is a weather model's
> analysis, not a measurement, and the platform does not promote one to the
> other just because it is accurate."

**The line to land:**

> "Eighteen of forty regions are below three metres per second right now.
> Below that the sea goes flat, and a flat sea in C-band radar looks exactly
> like oil. So any dark formation reported in those regions today is
> ambiguous on the physics, before any model is involved. That caveat has
> always been in the detector's documentation; this attaches it to today's
> weather."

Scroll to **Vessel activity**.

> "Global Fishing Watch — 60,403 vessel-hours across 25 of 40 regions.
> Arabian Sea Z4 is the busiest at 15,800 hours, mostly Chinese and Iranian
> flagged. Konkan and Goa at 11,000, all Indian."

**If asked why no vessel names — this is a good answer, use it:**

> "Deliberately absent. This platform has a table that marks a vessel as the
> source suspect for a detection at up to 0.97 confidence, and its
> detections are research benchmark patches — nobody spilled anything. A
> real ship's identity in that row names an identifiable vessel as the
> source of a spill that never happened, on a page built to be
> screenshotted. The caveat underneath does not survive a crop. So the
> suspect demo uses fictional vessels, and Global Fishing Watch answers the
> question it can answer honestly: how busy is this water."

---

## 3 · Model Performance — measured, not claimed (2 min)

`/app/models`

**On screen:** Registered models **5** · Evaluated **3** ·
Inference P95 **37.5 ms · 131 request(s) · sar-oil-slick-v2.2**.

> "Three models have been evaluated against held-out test splits. Two have
> not, and their metrics are null — the page says 'Not evaluated' rather than
> filling in a plausible number."

Scroll to **sar-oil-slick-v2.2**: Precision **0.677** · Recall **0.880** ·
F1 **0.765** · mAP@50 **Not evaluated**. Read the notes line aloud:

> "Against the rule-based baseline on the same leakage-free test split, F1
> **0.765 versus 0.222**. That is what the deep model buys. mAP is null
> because this is a scene classifier, not an object detector — that metric
> does not apply, so it stays empty."

### The live panel — "Measured against stored ground truth"

**On screen:** AUC **0.771** · matrix TP **136** / FN **18** / FP **71** /
TN **81** · Precision **65.7%** · Recall **88.3%** · F1 **0.753** ·
FPR **46.7%**.

> "This is not read from a file — it is computed from the database each time
> you move the slider, over all 306 candidates using their benchmark labels."

**Drag the threshold to 0.80.** Matrix becomes TP **28** / FP **9** /
TN **143** / FN **126**; precision rises to **75.7%**, recall falls to
**18.2%** — and **AUC stays 0.771**.

> "Precision and recall trade against each other as you move the cut. AUC
> does not move, because it is a property of the ranking, not of where you
> put the threshold. At 0.5 the false-positive rate is 47% — high, and the
> page says so. For a screening tool that hands candidates to a human
> analyst, missing a slick costs more than a false alarm."

---

## 4 · Drift Monitoring (1 min)

`/app/drift`

**On screen:** the provenance note, then **Overall status: Warning** ·
Mean confidence PSI **0.1100** (baseline 100 / current 105) ·
Predicted class distribution PSI **0.0322** — Stable.

> "This compares two independent held-out benchmarks — Phase 12 against
> Phase 13. The confidence distribution has shifted: PSI 0.11, just over the
> 0.10 warning line, while the class mix is stable at 0.03."

> "It says Warning, not 'no drift'. I did not tune that away. And read the
> grey note: the inferences are real, but the timestamps placing them in
> windows are assigned, because all 305 ran in about three seconds. It says
> '102 rows, 100 with confidence' because two old mock rows logged no
> confidence and the statistic could not use them."

> "Drift flags for a human. The platform never retrains on it — that is on
> the Retraining page, which says 'Not configured — by design'."

---

## 5 · Forecasts (1 min)

`/app/forecasts`

Select **Gulf of Kutch W**.

**On screen:** 55 observations · backtest MAE **5.59** vs naive **3.99** →
"did **NOT** beat the naive last-value baseline; treat the trend as weakly
supported."

Try one or two more. They all say the same thing.

> "Every forecast is backtested against last-value-carried-forward — predict
> today what you saw yesterday. Of forty regions, **not one beats it**. Each
> chart says so in its own words, and the model still runs and still shows
> its intervals, with the verdict attached."

**The line worth saying out loud:**

> "On the old region set this was one region out of thirty-eight. Re-cutting
> the regions to India's EEZ made it zero out of forty. The number moved the
> wrong way, and it is reported as it stands — I did not go looking for a
> window where it looked better."

> "That is the honest result for a damped-trend model on sparse detection
> counts. A dashboard that hid the comparison would look far cleverer."

---

## 6 · Risk Analysis (30 s)

`/app/risk`

> "A six-factor deterministic score — no language model produces or adjusts
> this number. Open any event and every contributing factor is listed with
> its weight, and the engine renormalises when a factor is missing rather
> than silently treating it as zero."

---

## 7 · Knowledge Graph (1.5 min)

`/app/knowledge-graph`

**On screen:** 40 Indian regions in the selector, default centre with
roughly **104 nodes / 125 edges** at 2 hops. Summary below: **4,131 nodes /
4,459 edges**, and **0 unresolved citations**.

> "Built entirely from foreign keys already in the schema — no new data, and
> nothing inferred from similarity. Rings are hop distance from the centre."

**Hover a node** → evidence level and attributes appear.
**Click a pollution event** → the graph re-centres on it.

Now centre on a region whose events carry reports (**Gulf of Kutch W** or
**Gulf of Mannar**), click through to an event, and point at the dashed
edges.

> "The dashed grey edges are different. Those are citations resolved from
> `reports.sources` — a JSON column, not a declared relationship. The ids do
> resolve to real documents, but nothing in the schema stops one dangling, so
> they are drawn differently and the legend says exactly what they are. Any
> that fail to resolve are counted, not hidden."

> "Two absences are deliberate. SAR candidates have no foreign key to a
> region, so they are a separate component — you cannot reach them from here,
> and that is the schema being reported accurately."

---

## 8 · Reports (30 s)

`/app/reports`

**On screen:** 10 reports across distinct regions, sectioned by evidence level.

> "Each report is organised by evidence ladder — observed, detected,
> inferred — so you can see which claims are measurements and which are
> reasoning. There is no language model writing prose here; `llm_provider` is
> `none`, and the structure is the output."

**Close on:**

> "Across the whole platform the pattern is the same: measured and inferred
> are kept apart, unevaluated things say 'not evaluated', and where the
> honest answer is zero it shows zero."

---

# Short version — 60 seconds

If time collapses, do these three and nothing else.

1. **`/app/india`** — "4.6 million real measurements across 2,740 water
   bodies. Zero are current enough to describe today, and the platform leads
   with that rather than hiding it."
2. **`/app/models`** — "Three evaluated models. v2.2 scores F1 0.765 against
   the rule-based baseline's 0.222 on the same leakage-free split. This panel
   recomputes from the database live — move the slider, precision and recall
   trade off, AUC stays 0.771."
3. **`/app/candidate-review`** — "306 real Sentinel-1 patches with ERA5 wind.
   The funnel accounts for all 306 exactly once: 136 + 70 + 0 + 1 + 99."

---

# Likely questions

**Is that plastic?** *(The FDI column. Expect this one.)*
No, and the platform will not say it is. The Floating Debris Index responds
to anything floating that is brighter in the near-infrared than the water
around it. Biermann's 2020 paper, which defines the index, separates floating
material into plastics, seaweed, sea-snot, foam, timber and spume — and needs
further spectral analysis to tell them apart. At ten metres a positive pixel
is roughly a tennis court of *something*. Sargassum, foam lines and sun glint
all raise it. So it is labelled "possible floating material", and there is no
threshold anywhere in the code above which it gets called plastic.

**How much of this is actually real?**
Point at the table at the top of this script. The India water data, the
Sentinel-2 indices, the chlorophyll, the sea state, the currents, the vessel
activity and the 306 benchmark SAR patches are real. The pollution events and
the vessel suspects are simulated and labelled SIMULATED on every page that
shows them. The honest summary is that the *measurement* layers are real and
the *incident* layer is a demonstration.

**Did your detector find any oil in the real Sentinel-1 imagery?**
It found nothing, and the more interesting part is that the result does not
count. Thirty tiles from three recent scenes — one acquired that morning —
went through the trained classifier and came back `no_anomaly` every time, at
confidence 1.000 on every single tile. That is not certainty, it is a
saturated softmax. On its own training patches the same model spreads from
0.005 to 0.83. A flat 1.000 means the input is unlike anything it was fitted
on: it was trained on pre-stretched quicklook JPEGs and these are calibrated
backscatter. So the pipeline works end to end and the model needs retraining
on this product before its output means anything. The script says so itself
at the end of every run.

**Why do two of the Indian water feeds say Unavailable?**
Because they are. Both NWDP endpoints sit behind a firewall appliance
presenting its factory certificate, which has expired. That is recorded
through the real ingestion pipeline with the exact error and the last
successful sync, not hand-edited. The third CPCB feed — the real-time
analysers — works, and is where the live readings come from. Worth adding:
it was *also* reported as down until yesterday, and that turned out to be a
missing root certificate on this Windows machine rather than anything wrong
at CPCB. One host's trust gap had been recorded as a national outage.

**Why does Gemini not write the report summaries?**
Google retired the model mid-build: the one we had integrated now answers 404
"no longer available to new users", and every current replacement answered
503 or timed out across a dozen attempts. The layer is built, tested and
cached — and the fallback is the thing worth showing, because the report
renders in full from computed values with nothing fabricated. There is also a
check that would discard any AI summary containing a number not present in
the evidence it was given.

**Why no vessel names on the detections?**
See section 2c. Short version: naming a real ship as the suspect for a spill
that did not happen is an accusation, and the caveat underneath does not
survive a screenshot crop.

**Why does drift say WARNING? Is something broken?**
No. It compares two independent held-out benchmarks and found the confidence
distribution shifted — PSI 0.11, just past the 0.10 line — while the predicted
class mix held at 0.03. That is drift monitoring doing its job: it raises a
flag for a human and never retrains on its own. I did not tune it away.

**You said the drift timestamps are assigned. Isn't that fabricated data?**
The measurements are real — the detector genuinely ran over all 305 patches
and the latency and confidence are what it produced. What is assigned is only
*which drift window* each row sits in, because all 305 ran within seconds and
drift compares time windows. Every row records `timestamp_is_synthetic: true`,
its true execution time, and a `BATCH` endpoint label, and the panel says so
in plain text. The split is meaningful: Phase 12 against Phase 13, with the
dev and validation sets deliberately outside both windows because comparing
against data the model was tuned on measures nothing.

**A 47% false-positive rate seems very high.**
It is, and the page states it rather than burying it. This is a screening
stage that hands candidates to a human analyst, so a miss costs more than a
false alarm — the threshold is set for recall (88%). Move the slider to 0.8
and precision rises to 76% while recall collapses to 18%. The scores are also
uncalibrated, so the threshold is a ranking cut, not a probability.

**The live panel says precision 65.7% but the card above says 0.677. Which is right?**
Both. The card reports the locked 100-sample leakage-free test split recorded
at evaluation time. The panel computes over all 306 stored candidates,
including the dev and validation sets. Different sample sets, and the page
says so underneath. That they agree to within two points is reassuring.

**Why is mAP "Not evaluated"?**
Because it does not apply. These are binary scene classifiers — they emit
P(oil) for a 224×224 patch, not bounding boxes. Filling in a number there
would be worse than leaving it empty. The optical YOLOv8 detector is a real
object detector, but its test split was never committed, so its metrics are
null too.

**How much of this is simulated?**
See the table at the top of this script. Real: 4.6M CPCB and CWC water
observations with 19 water bodies current today, 253 Sentinel-2 index
readings, Copernicus Marine chlorophyll and currents, Open-Meteo sea state,
60,403 vessel-hours from Global Fishing Watch, and 306 benchmark Sentinel-1
patches from PANGAEA 980773. Simulated: the 666 marine pollution events and
the vessel suspects, both tagged and labelled on every page that shows them.
Nothing is simulated without a label.

**The marine regions are Indian now — were they always?**
No, and it is worth being straight about it. The marine module was built
first against globally distributed demo regions, and the India work came
later and became the substantial part. They were re-cut to India's EEZ: 15
regions, 40 cells, from the Gulf of Kutch to the Andamans, with the risk
engine's coastal and protected-area factors now pointing at real Indian
receptors. The *regions* are real geography; the *events* in them are still
simulated, and every marine page says so. If anything that distinction
matters more now than it did — "Gulf of Mannar" is far easier to mistake for
a real incident than "Java Sea SE" ever was.

**Why can't I reach the SAR candidates from a region in the graph?**
Because no foreign key connects them. `sar_candidates` has no FKs at all, so
they are genuinely a separate component. Drawing an edge there would mean
inventing one, which is the thing this graph is built not to do.

**What are the dashed edges?**
Citations resolved from `reports.sources`, which is a JSON array of document
ids. They do resolve to real `research_documents` rows — all 40 of them — but
JSON is not a declared relationship and nothing stops one dangling, so they
are drawn dashed, labelled in the legend, and any that fail to resolve are
counted and reported.

**Where is the LLM?**
`llm_provider` is `none`. The agent workflow is a bounded sequence of tool
calls and the reports are structured rather than written. The water assistant
is retrieval and SQL over stored observations, which is why it can cite and
date every figure and cannot hallucinate one. Adding a narrative layer is
straightforward; grounding it is the part that is already done.

**Why hand-roll the graph instead of using a library?**
The API returns a subgraph defined by a centre and a hop count, and concentric
rings express that directly where a force simulation would scramble it. It is
also deterministic, so it does not rearrange itself between renders, and at
150 nodes there is no performance case for a simulation. It avoided a
200–400 KB dependency on top of an already large charts bundle. For free-form
exploration over thousands of nodes I would add a real library.

**What would you do next, with more time?**

The four answers I used to give here are now done — the marine regions are
Indian, Sentinel-1 and Sentinel-2 come through Copernicus, and the LLM
narrative layer exists with its grounding check. What that work produced was
a better list:

1. **Retrain the SAR classifier on calibrated backscatter.** The current
   model was fitted on pre-stretched quicklook JPEGs and saturates to 1.000
   on real Sentinel-1 product. Until that is fixed, live screening proves
   the pipeline and nothing about the ocean. This is the single highest-value
   item and everything else is secondary to it.
2. **Calibrate the confidence scores** so the 0.5 threshold is a probability
   rather than a ranking cut. The saturation above is the sharpest evidence
   yet that it currently is not.
3. **Finish the Gemini narratives** once Google's capacity recovers — one
   command, no code change.
4. **Pin the CPCB certificate chain** if the NWDP feeds are needed, or wait
   for CPCB to renew. Currently reported as unavailable, which is correct.

---

# Next steps — deliberately not done

Listed so nobody has to guess whether these were forgotten or declined.

- **Natural Earth coastline.** The risk engine measures distance to the
  nearest of 90 coastal reference points, not to a real coastline, and says
  so in every assessment. A real polygon would tighten the coastal factor.
- **WDPA protected-area boundaries.** Same shape of problem: 28 curated
  marine protected areas by centroid, which under-states proximity for large
  reserves. The platform states that limitation where it uses the number.
- **Legal corpus expansion.** The RAG corpus answers from what it holds and
  refuses otherwise; it simply holds less than it could.
- **MARIDA marine-debris classifier.** A second trained model. Not attempted
  — the existing one needs retraining first (item 1 above), and adding a
  second unvalidated model would be worse than having one.
- **Experiments page and optical YOLO evaluation.** Scaffolding exists; no
  measured results, which is why the page says so rather than showing
  placeholder metrics.
- **CPCB forecasting.** The forecaster runs on marine regions; pointing it at
  the water-quality series needs the daily-bucket work redone for a different
  cadence.
- **Real vessel identities on detections.** Declined on purpose, not pending.
  See section 2c.
