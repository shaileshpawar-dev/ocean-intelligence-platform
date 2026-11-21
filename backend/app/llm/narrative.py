"""AI-written summaries of reports, constrained to the evidence they are given.

The platform computes every number it shows. Risk scores come from the risk
engine, confidences from the detector, areas from the area method, freshness
from the observation timestamps. None of that needs a language model, and
none of it is delegated to one -- see ``app.llm.base``, rule 2.

What a model can add is prose: an analyst-readable paragraph over figures that
are otherwise rendered as a table. That is this module's entire job.

Two rules make it safe enough to show:

**The prompt carries the evidence and nothing else.** The model is given a
block of computed facts and told to write about those facts only. It has no
tools, no retrieval, and no access to the database.

**Every number in the reply is checked against that evidence.** A model asked
to summarise "risk 95.2" will occasionally write "risk 95.3", or round 4948.3
km² to "nearly 5,000 km²", or introduce a figure from nowhere. So the reply is
parsed for numbers and each one must appear in the evidence it was given.
A reply that fails is **discarded**, not displayed with a warning -- a summary
whose numbers disagree with the table beside it is worse than no summary.

The deterministic template remains the default and the fallback. If Gemini is
unconfigured, slow, erroring or caught inventing a figure, the report renders
exactly as it does today. Nothing here is load-bearing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.llm.base import LLMMessage
from app.llm.providers import get_llm
from app.models.intelligence import Report

logger = get_logger(__name__)

#: Shown wherever a generated narrative appears. The platform's own prose is
#: template-rendered from computed values; this is not, and says so.
AI_LABEL = "AI-generated summary"

SYSTEM_PROMPT = """You are writing one short paragraph for a marine pollution \
monitoring report, for an analyst who can already see the figures.

Rules, all of them absolute:
- Use ONLY the facts in the EVIDENCE block. You have no other knowledge of \
this event.
- Every number you write must appear in the EVIDENCE block, copied exactly. \
Do not round, convert units, recompute, average, or total anything.
- Do not state a cause, a responsible party, or a vessel. The detection does \
not identify one.
- Do not call this a confirmed spill, incident, or pollution event. It is a \
detection.
- If the evidence is thin, say so plainly instead of padding.
- 60 to 110 words. One paragraph. No heading, no bullet points, no preamble \
such as "Here is a summary".
"""

#: Numbers that carry no claim: a model writing "one paragraph" or "the 5
#: factors" is not inventing a measurement. Years are allowed through for the
#: same reason -- they are already in the evidence as part of a timestamp.
_TRIVIAL = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers_in(text: str) -> list[str]:
    """Every numeric token in ``text``, normalised for comparison.

    Thousands separators are stripped so "4,948.3" and "4948.3" compare equal;
    a trailing ".0" is dropped so "95" and "95.0" do. Nothing else is
    normalised -- in particular 95.2 and 95.3 stay different, which is the
    whole point.
    """
    found = []
    for raw in _NUMBER.findall(text):
        token = raw.replace(",", "")
        if token.endswith(".0"):
            token = token[:-2]
        found.append(token.rstrip("."))
    return found


@dataclass(slots=True)
class NumberCheck:
    """Result of comparing a generated narrative against its evidence."""

    passed: bool
    unsupported: list[str] = field(default_factory=list)
    checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage beside the narrative."""
        return {
            "passed": self.passed,
            "unsupported": self.unsupported,
            "checked": self.checked,
        }


def check_numbers(narrative: str, evidence: str) -> NumberCheck:
    """Verify that every figure in ``narrative`` occurs in ``evidence``.

    This is deliberately strict and deliberately dumb. It does not understand
    the sentence; it asks only whether each number was given. A false positive
    costs a fallback to the template, which is cheap. A false negative puts a
    wrong figure in front of someone, which is not.
    """
    allowed = set(_numbers_in(evidence)) | _TRIVIAL
    unsupported = [n for n in _numbers_in(narrative) if n not in allowed]
    # Duplicates say nothing extra, and a repeated bad figure is one mistake.
    unique = sorted(set(unsupported))
    return NumberCheck(
        passed=not unique,
        unsupported=unique,
        checked=len(_numbers_in(narrative)),
    )


def build_evidence(report: Report) -> str:
    """Flatten a report's computed content into the EVIDENCE block.

    Only what the platform already computed and stored. Nothing is fetched,
    derived or reformatted into a new figure here, because a number that first
    appears in this function is a number the check cannot vouch for.
    """
    lines = [f"Title: {report.title}"]
    if report.summary:
        lines.append(f"Deterministic summary: {report.summary}")

    for section in report.sections or []:
        if not isinstance(section, dict):
            continue
        heading = section.get("heading") or section.get("title") or "Section"
        body = section.get("body") or section.get("text") or ""
        if isinstance(body, list):
            body = "\n".join(str(item) for item in body)
        if body:
            lines.append(f"{heading}: {body}")

    if report.contains_simulated_data:
        lines.append(
            "Data origin: SIMULATED. This detection comes from demonstration "
            "data, not from a live satellite acquisition."
        )
    sources = report.sources or []
    if sources:
        lines.append(f"Cited sources: {len(sources)}")
    return "\n".join(lines)


def evidence_fingerprint(evidence: str, model: str) -> str:
    """Stable key for the cache.

    Keyed on the evidence *and* the model, so a regenerated report or a model
    change produces a new narrative while an unchanged report reuses the
    stored one. The demo therefore makes no live call at all.
    """
    digest = hashlib.sha256(f"{model}|{evidence}".encode()).hexdigest()
    return digest[:32]


@dataclass(slots=True)
class NarrativeResult:
    """What happened when a narrative was requested."""

    status: str  # "generated" | "cached" | "unavailable" | "rejected" | "error"
    text: str | None = None
    model: str | None = None
    detail: str | None = None
    check: NumberCheck | None = None

    @property
    def usable(self) -> bool:
        """True when there is a narrative worth showing."""
        return self.status in {"generated", "cached"} and bool(self.text)


def generate_for_report(
    db: Session, report: Report, *, force: bool = False
) -> NarrativeResult:
    """Produce, verify and cache an AI summary for one report.

    Returns a :class:`NarrativeResult` describing the outcome. The caller
    renders the deterministic template whenever ``usable`` is false, which is
    every path except a fresh or cached narrative that passed its check.
    """
    evidence = build_evidence(report)
    llm = get_llm()

    if not llm.is_available:
        return NarrativeResult(
            status="unavailable",
            detail=(
                "No LLM provider is configured. The report below is rendered "
                "from computed values, as it always is."
            ),
        )

    model = getattr(llm, "model", None) or llm.name
    fingerprint = evidence_fingerprint(evidence, model)

    if not force and report.ai_narrative and report.ai_fingerprint == fingerprint:
        return NarrativeResult(
            status="cached", text=report.ai_narrative, model=report.ai_model
        )

    response = llm.generate(
        [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(role="user", content=f"EVIDENCE:\n{evidence}"),
        ],
        max_tokens=400,
        temperature=0.2,
    )

    if not response.ok:
        logger.info(
            "narrative_unavailable",
            extra={"report": report.report_id, "status": str(response.status)},
        )
        return NarrativeResult(
            status="error" if response.status == "error" else "unavailable",
            detail=response.detail,
            model=model,
        )

    check = check_numbers(response.text, evidence)
    if not check.passed:
        # Kept out of the database entirely. A rejected narrative has no use
        # except as evidence of the rejection, which the log holds.
        logger.warning(
            "narrative_rejected_unsupported_numbers",
            extra={
                "report": report.report_id,
                "unsupported": check.unsupported[:5],
            },
        )
        return NarrativeResult(
            status="rejected",
            model=model,
            check=check,
            detail=(
                "The generated summary contained "
                f"{len(check.unsupported)} figure(s) not present in the "
                "evidence, so it was discarded."
            ),
        )

    report.ai_narrative = response.text
    report.ai_model = model
    report.ai_fingerprint = fingerprint
    report.ai_generated_at = datetime.now(UTC)
    report.ai_check = check.to_dict()
    db.add(report)
    db.commit()

    logger.info(
        "narrative_generated",
        extra={
            "report": report.report_id,
            "model": model,
            "numbers_checked": check.checked,
            "latency_ms": response.latency_ms,
        },
    )
    return NarrativeResult(
        status="generated", text=response.text, model=model, check=check
    )
