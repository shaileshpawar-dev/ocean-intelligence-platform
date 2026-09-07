# The agentic layer

## Control flow: a state machine, not a conversation

```
event_id
   ↓
Detection ──▶ Context ──▶ Research ──▶ Risk ──▶ Report ──▶ report_id
   │            │            │           │         │
   └────────────┴────────────┴───────────┴─────────┘
                    shared AgentContext
```

Five stages, linear, in dependency order. **Agents never call each other and
never loop.** The workflow therefore terminates in a bounded number of tool
calls by construction — asserted by
`test_terminates_in_a_bounded_number_of_tool_calls`.

This is a deliberate choice against free-form delegation. Letting agents
decide who to consult next makes cost and latency unpredictable, and it buys
nothing here: the dependency order between these five stages is known in
advance. Detection must load the event before Context can look up its
geography; Risk needs both before it can be interpreted.

A measured run:

```
workflow ea106dca77da498c | success | 83 ms | llm: none
  detection  [DETECTED]  oil like signature, confidence 0.72
  context    [OBSERVED]  ~198 km from coast; 8 observed days in 60
  research   [OBSERVED]  4 corpus passages retrieved
  risk       [INFERRED]  77.9/100 CRITICAL, driven by signature severity 20/20
  report     [INFERRED]  assembled with 4 sources

  6 tool calls, 74 ms total
```

## The two rules that shape everything

### 1. No agent produces a number

Every figure comes from a deterministic engine that already exists and is
already tested. The `calculate_risk` tool calls the same `RiskEngine` the REST
API calls; `get_forecast` calls the same forecaster. An agent's job is to
*read* those outputs and say what they mean.

`test_risk_in_the_report_comes_from_the_engine` reconstructs the score from
its contributions and asserts it matches — so if an agent ever started
inventing risk values, the test fails.

### 2. Every stage works with no LLM

`LLM_PROVIDER=none` is the default and the whole workflow runs on it. The
substance — measurements, risk arithmetic, retrieved passages — is computed by
tools. An LLM, when configured, writes the report *narrative* and nothing
else.

The template narrative is not a degraded fallback. It is the default, and it
states only values already computed:

> A oil like signature was detected in Gulf of Mexico NW at an uncalibrated
> confidence of 0.72 by sar-dark-formation:1.0.0. The deterministic risk
> engine scored it 77.9/100 (CRITICAL) from 5 evaluable factors, with 1
> factor unavailable. This is a detection, not a confirmed pollution incident.

## Tools

Each is a thin wrapper over an existing service. An agent layer whose tools
contain their own business logic is a second implementation that can drift
from the first; here an agent's answer and an API response cannot disagree.

| Tool | Delegates to |
|---|---|
| `get_pollution_event` | `pollution_service.get_event` |
| `get_satellite_observation` | the observation behind a detection |
| `get_geographic_context` | `GeographicDataProvider` (with precision notes) |
| `get_pollution_history` | `analytics_service.get_trends` |
| `get_forecast` | `forecast_service.forecast_region` |
| `calculate_risk` | `RiskEngine.assess` — the only path to a score |
| `search_research` | `rag.service.search` |
| `get_region` | region metadata |

Every call is timed and recorded:

```json
{"tool": "get_forecast", "duration_ms": 3.7, "success": true,
 "summary": "dict with 11 keys", "agent": "context"}
```

A failing tool is captured as data, not raised — one bad lookup must not abort
a workflow. Sessions are never written into the trace.

## What each stage contributes

**Detection** loads the event and judges how much it can support. It raises
concerns for uncalibrated confidence, confidence below 0.5, simulated data,
a bare `dark_formation` signature, and backscatter contrast under 3 dB.

**Context** gathers geography, history and forecast. A stage-2 sub-cell has
almost no history of its own, so it falls back to the parent screening cell
and *says* it did — reporting "0 observed days" for a refined detection would
understate the evidence that exists for that patch of ocean.

**Research** searches the corpus with terms drawn from the detection itself
(signature + parent region + "discharge regulation response").

**Risk** reads the stored assessment, ranks the contributions, and flags
missing factors. If no assessment exists it recomputes through the same
engine — never estimates.

**Report** assembles sections keyed by evidence level and derives
recommendations by rule.

## Reasoning is summarised, never traced

Chain-of-thought is never requested from a model, never stored and never
returned. What persists on an `AgentRun` is a concise `summary` per stage plus
the full tool trace — which is what actually makes a run auditable. You can
see which tools ran, how long they took, and what each stage concluded.

## The report

Sections are keyed by evidence level so a reader can see which parts are
measurements and which are inference:

```
OBSERVED   region, coordinates, acquisition time, backscatter, contrast,
           coastline and protected-area distance, observed days in window
DETECTED   signature, confidence (+ calibration flag), method, model version,
           estimated area (+ method), caveats
INFERRED   risk score, severity, engine version, per-factor contributions,
           missing factors
FORECAST   kind, model, beats_naive, 7-day bands, scope note
RETRIEVED  corpus sources with URLs and summary notices
```

Recommendations are rule-based, tied to thresholds a reader can check:

- HIGH/CRITICAL → task a higher-resolution acquisition before treating as an incident
- `oil_like_signature` → correlate with AIS; notify under OPRC if confirmed
- `dark_formation` → obtain wind data; below ~3 m/s it is not separable
- protected area within 200 km → notify the managing authority
- simulated event → **"NO OPERATIONAL ACTION"** inserted first

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/agents/analyze-event` | Run the workflow; returns findings, trace, report |
| `GET /api/v1/agents` | Workflow, stages, tool catalogue, LLM status |
| `GET /api/v1/agents/runs` | Recent runs with timing and tool counts |
| `POST /api/v1/reports/generate` | Run the workflow and return the report |
| `GET /api/v1/reports/{id}` | Stored report with provenance map |
| `GET /api/v1/reports/{id}/text` | Fixed-width briefing rendering |

## Limitations

- **Fixed pipeline.** The workflow cannot adapt its plan. That is the trade
  for bounded cost; a genuinely open-ended investigation would need dynamic
  planning and a budget.
- **Single event scope.** No cross-event correlation, no "is this the same
  slick as yesterday" reasoning.
- **Recommendations are rules, not judgement.** They encode thresholds, not
  an operational expert's assessment.
- **Tool errors degrade silently within a stage.** A failed lookup is
  recorded, and the stage continues with what it has.
- **The LLM path is untested against a live provider.** `LLM_PROVIDER=none`
  is exercised in CI; the Gemini/OpenAI/Anthropic adapters are written but
  have not been run against real credentials.
