# Demo script — 22 November 2026

Eight to ten minutes. Every number below was read off the running application
on 20 November after a clean restart. If a figure on screen does not match,
say so rather than talking over it — the platform's whole argument is that it
reports what it has.

**Before you start**

```bash
docker compose up -d db
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/app/india`. If anything looks wrong, run
`scripts/reset_demo.sh` and restart the API — about a minute.

**The one-sentence framing, if you only get one:** *this platform separates
what was measured from what was inferred, and refuses to state anything it
cannot support — including when that makes it look worse.*

---

## 1 · India Water Intelligence — the core (2 min)

### 1a. India Overview — `/app/india`

**On screen:** 2,740 water bodies · 4,951 monitoring stations ·
**4,601,153 observations** · Current data **0** · Recent data **26** ·
Historical only **2,714** · 35 states · 613 districts.

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

## 3 · Model Performance — measured, not claimed (2 min)

`/app/models`

**On screen:** Registered models **5** · Evaluated **3** ·
Inference P95 **9.63 ms · 105 request(s) · sar-oil-slick-v2.2**.

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

Select **Java Sea SE**.

**On screen:** 23d observed · backtest MAE **0.785** vs naive **0.791** →
**beats** the naive baseline.

Now select **Arabian Sea NE**.

**On screen:** MAE **1.368** vs naive **0.572** → "does **NOT** beat the
naive baseline."

> "Every forecast is backtested against last-value-carried-forward. Of 38
> regions, exactly **one** beats it, and barely. The other 37 lose, and each
> one says so on its own chart."

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

**On screen:** 38 regions in the selector, default centre with roughly
**113 nodes / 137 edges** at 2 hops. Summary below: **4,378 nodes /
4,504 edges**.

> "Built entirely from foreign keys already in the schema — no new data, and
> nothing inferred from similarity. Rings are hop distance from the centre."

**Hover a node** → evidence level and attributes appear.
**Click a pollution event** → the graph re-centres on it.

Now centre on a region whose events carry reports (**Gulf of Mexico SE**),
click through to an event, and point at the dashed edges.

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
The India water data is real: 4.6 million CPCB and CWC observations. The 306
SAR candidates are real Sentinel-1 patches from PANGAEA 980773. The marine
pollution events — all 686 — are synthetic, tagged `SIMULATED` by the API,
and every page in that module says so. Nothing is simulated without a label.

**Why are the marine regions global when the rest is India?**
Honestly: the marine module was built first, against globally distributed
demo regions, and the India work came later and became the substantial part.
Rather than renaming regions to look coherent, every marine page states that
it is a global demonstration and points at Candidate Review for the real data.
Re-centring on Indian waters — the Gulf of Kutch, Gulf of Mannar — is the
first thing I would do next.

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
Four things, in order: live Sentinel-1 ingestion through the Copernicus API so
the marine side stops being a demonstration; re-centre the marine regions on
Indian waters so the platform is one project rather than two; calibrate the
SAR confidence scores so the threshold is a probability instead of a ranking
cut; and add an LLM narrative layer over the report structure that already
exists — generation last, because the grounding is what makes it safe.
