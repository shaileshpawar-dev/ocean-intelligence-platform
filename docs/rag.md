# The research assistant

## The guarantee

Every answer is exactly one of three things, and the response says which:

| `status` | Meaning |
|---|---|
| `grounded` | Passages retrieved, synthesised by an LLM, every claim cited |
| `retrieval_only` | Passages retrieved and returned verbatim; no LLM configured |
| `no_evidence` | Nothing relevant retrieved — **the assistant declines to answer** |

The third row is the point of the module. An assistant that answers
marine-law questions out of a model's weights, with no retrieved source, is
exactly the failure this exists to prevent. Two mechanisms enforce it:

1. The system prompt forbids falling back on parametric knowledge.
2. The `no_evidence` path is taken *before* any model is consulted, so when
   the corpus is silent there is no generation step to go wrong.

`TestGroundedAnswering::test_declines_when_nothing_relevant_is_retrieved`
asks the assistant the airspeed of a swallow and asserts it refuses.

## What is in the corpus, and what is not

Fabricating a plausible bibliography would destroy the project's credibility
faster than any other single act, so the seed corpus contains only two kinds
of document and labels both.

**Regulations (14).** Real, named international instruments. Titles, adopting
bodies, adoption and entry-into-force years, and scope are factual:

| | |
|---|---|
| Global | MARPOL Annex I (oil), Annex V (garbage/plastics), OPRC 1990, UNCLOS Part XII, CLC 1992, Bunkers 2001, London Protocol |
| Regional | OSPAR, HELCOM, Barcelona/UNEP-MAP, Kuwait/ROPME, Abidjan, Nairobi |
| National/bloc | EU Directive 2005/35/EC |

The body text of each is a **platform-authored scope summary, not verbatim
treaty text**, and every record carries a notice saying so. `source_url`
points at the *organisation* that maintains the instrument rather than a deep
link, because a stale deep link is worse than none.

**References (5).** Platform-authored technical notes on this system's own
methodology: SAR dark-formation physics, look-alike discrimination, the risk
engine's renormalisation, the forecast scope boundary, and how operational
satellite monitoring works. Attributed to the platform, not to any external
author.

**There are no invented journal papers.** Adding real literature is an
ingestion task, not a seeding task — point `ingest_document()` at a real
corpus and it becomes retrievable alongside these.

## Retrieval

```
question
   ↓  tokenize   lowercase, drop stopwords, keep "MARPOL 73/78" intact
   ↓  BM25       k1=1.5, b=0.75, over-fetch 3×
   ↓  rerank     title overlap, exact phrase, region, doc type
   ↓  top-k with citations
```

### Why BM25 and not embeddings

The default deployment has no API key and no model download. BM25 runs in
pure Python over a few hundred chunks in microseconds and is **inspectable** —
every hit reports `matched_terms`, so you can see exactly why it ranked.

For a corpus of regulatory instruments this is not a compromise. The user's
vocabulary and the document vocabulary overlap almost exactly: someone asking
about "oil discharge in the Persian Gulf" uses the words the instruments use.
A live query demonstrates it:

```
"oil discharge from ships Persian Gulf special area"

  12.55  Kuwait Regional Convention (ROPME Sea Area)
         matched: area, discharge, gulf, oil, persian, special
   7.41  MARPOL 73/78 Annex I
         matched: discharge, oil, ships, special
```

The regional instrument outranks the global one, which is the correct answer.

Dense retrieval genuinely helps with paraphrase-heavy queries and slots in
behind the same interface when `sentence-transformers` is installed. It is
optional on purpose.

### Chunking

Sentence-aligned with overlap. Chunks end on sentence boundaries so a
retrieved passage reads correctly on its own — a passage starting mid-sentence
makes the system look like it is quoting carelessly. Overlap prevents losing a
fact that straddles a boundary.

### Reranking

Feature-based, multiplicative, and **deliberately modest**: it refines the
lexical ordering rather than overriding it.

| Signal | Boost |
|---|---|
| Query term in title | +0.16 each |
| Exact leading phrase in body | +0.30 |
| Region mentioned | +0.22 |
| Preferred doc type | +0.14 |

The tests assert these *raise a score*, not that they always flip a ranking —
asserting the latter would mean the boosts were drowning out BM25, which is
the bug this design avoids. A cross-encoder would rank better and needs a
model download; this is the version that runs everywhere.

### Zero-score hits are dropped

A chunk that matched no query term is not returned, even if that leaves fewer
than `limit` results. Padding the list with unrelated passages would put them
in front of the LLM and invite it to cite them.

## Grounding rules given to the model

```
1. Answer ONLY from the numbered passages. If they do not contain the
   answer, say so and stop. Never fall back on your own knowledge.
2. Cite the passage number in brackets after every factual sentence.
3. Never state that a detection proves pollution.
4. Where passages are scope summaries, do not quote them as legal text.
5. Be concise.
```

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/research` | Ask a question; returns answer + cited sources |
| `GET /api/v1/research/search` | Raw retrieval with BM25 scores and matched terms |
| `GET /api/v1/research/corpus` | Corpus size, composition, and what it excludes |

## Limitations

- **No journal literature.** Coverage is regulatory and methodological.
- **Scope summaries, not legal text.** Never rely on a retrieved passage for
  a compliance decision; consult the official instrument.
- **Lexical retrieval misses paraphrase.** A question worded entirely
  differently from the corpus may return nothing — which the assistant
  reports honestly rather than papering over.
- **Organisation-level URLs.** Deep links to specific articles are not
  provided because they go stale.
- **No freshness tracking.** Instruments are amended; the corpus records
  entry-into-force years but does not track amendments.
