"""The AI summary may describe the evidence. It may not add to it.

A language model writing prose over computed figures will, sooner or later,
write a figure of its own: a rounded area, a transposed digit, a total nobody
asked for. Next to a table of exact values that is not a stylistic problem --
it is a report that contradicts itself.

So every number in a generated summary is checked against the evidence the
model was given, and a summary that fails is discarded rather than shown with
a caveat. These tests pin that behaviour, and the fallbacks around it. No test
here calls a real model.
"""

from __future__ import annotations

import pytest
from app.llm.base import LLMResponse, LLMStatus
from app.llm.narrative import (
    build_evidence,
    check_numbers,
    evidence_fingerprint,
    generate_for_report,
)
from app.models.intelligence import Report

EVIDENCE = (
    "Title: Ocean Intelligence Report - Gulf of Kutch W (oil_like_signature)\n"
    "Deterministic summary: A oil like signature was detected in Gulf of "
    "Kutch W at an uncalibrated confidence of 0.73 by sar-dark-formation:"
    "1.0.0. The deterministic risk engine scored it 95.2/100 (CRITICAL) from "
    "5 evaluable factors, with 1 factor(s) unavailable.\n"
    "Estimated area: 4948.3 km2"
)


class TestTheNumberCheck:
    """What counts as a figure the model was not given."""

    def test_a_summary_that_only_repeats_given_figures_passes(self):
        narrative = (
            "A dark formation consistent with an oil-like signature was "
            "detected in Gulf of Kutch W at confidence 0.73. The risk engine "
            "scored it 95.2 out of 100."
        )
        assert check_numbers(narrative, EVIDENCE).passed

    def test_a_transposed_digit_is_caught(self):
        """95.3 for 95.2 -- the failure most likely to go unnoticed."""
        result = check_numbers("The engine scored it 95.3/100.", EVIDENCE)

        assert not result.passed
        assert "95.3" in result.unsupported

    def test_a_helpfully_rounded_area_is_caught(self):
        """Rounding is still a figure the platform did not compute."""
        result = check_numbers("The slick covers nearly 5000 km2.", EVIDENCE)

        assert not result.passed
        assert "5000" in result.unsupported

    def test_a_figure_from_nowhere_is_caught(self):
        result = check_numbers(
            "Roughly 12 vessels were in the area at the time.", EVIDENCE
        )

        assert not result.passed
        assert "12" in result.unsupported

    def test_thousands_separators_do_not_count_as_a_difference(self):
        """"4,948.3" and "4948.3" are the same number written two ways."""
        assert check_numbers("An area of 4,948.3 km2.", EVIDENCE).passed

    def test_a_trailing_zero_does_not_count_as_a_difference(self):
        assert check_numbers("Scored 95.20 out of 100.", EVIDENCE).passed is False
        assert check_numbers("Confidence of 0.73.", EVIDENCE).passed

    def test_small_counting_numbers_are_allowed_through(self):
        """"one paragraph", "the 5 factors" -- prose, not measurement."""
        assert check_numbers("There are 5 evaluable factors and 1 gap.", EVIDENCE).passed

    def test_the_check_reports_how_many_numbers_it_looked_at(self):
        result = check_numbers("Confidence 0.73, score 95.2.", EVIDENCE)

        assert result.checked == 2
        assert result.passed


class _StubLLM:
    """A model that says exactly what the test tells it to."""

    name = "gemini"
    model = "gemini-2.5-flash"

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.calls = 0

    @property
    def is_available(self) -> bool:
        return True

    def generate(self, messages, **kwargs) -> LLMResponse:
        self.calls += 1
        self._messages = messages
        return self._response


@pytest.fixture
def report(db):
    """A stored report with figures in it."""
    row = Report(
        report_id="rpt_test_narrative",
        title="Ocean Intelligence Report - Gulf of Kutch W",
        summary=(
            "Detected at an uncalibrated confidence of 0.73. The risk engine "
            "scored it 95.2/100 (CRITICAL)."
        ),
        sections={},
        generated_by="test",
        contains_simulated_data=True,
    )
    db.add(row)
    db.commit()
    return row


def _stub(monkeypatch, response: LLMResponse) -> _StubLLM:
    llm = _StubLLM(response)
    monkeypatch.setattr("app.llm.narrative.get_llm", lambda: llm)
    return llm


class TestGeneratingOne:
    """End to end, with the model stubbed."""

    def test_a_clean_summary_is_stored_and_reused(self, db, report, monkeypatch):
        llm = _stub(
            monkeypatch,
            LLMResponse(
                status=LLMStatus.OK,
                text="Detected at confidence 0.73 and scored 95.2 by the engine.",
                provider="gemini",
                model="gemini-2.5-flash",
            ),
        )

        first = generate_for_report(db, report, force=False)
        assert first.status == "generated"
        assert report.ai_narrative == first.text
        assert report.ai_model == "gemini-2.5-flash"
        assert (report.ai_check or {})["passed"] is True

        second = generate_for_report(db, report, force=False)
        assert second.status == "cached"
        assert llm.calls == 1, "a cached narrative must not call the model again"

    def test_a_summary_with_an_invented_figure_is_not_stored(
        self, db, report, monkeypatch
    ):
        """The point of the whole module: rejected means gone, not flagged."""
        _stub(
            monkeypatch,
            LLMResponse(
                status=LLMStatus.OK,
                text="Scored 97.4/100, affecting some 42 fishing vessels.",
                provider="gemini",
                model="gemini-2.5-flash",
            ),
        )

        result = generate_for_report(db, report, force=False)

        assert result.status == "rejected"
        assert result.text is None
        assert report.ai_narrative is None, "a rejected summary must not be persisted"
        assert "97.4" in result.check.unsupported

    def test_a_provider_failure_leaves_the_report_alone(self, db, report, monkeypatch):
        _stub(
            monkeypatch,
            LLMResponse(
                status=LLMStatus.ERROR, provider="gemini", detail="HTTP 503"
            ),
        )

        result = generate_for_report(db, report, force=False)

        assert not result.usable
        assert report.ai_narrative is None

    def test_no_provider_is_reported_not_disguised(self, db, report, monkeypatch):
        class _Absent:
            name = "none"
            is_available = False

        monkeypatch.setattr("app.llm.narrative.get_llm", lambda: _Absent())

        result = generate_for_report(db, report, force=False)

        assert result.status == "unavailable"
        assert result.text is None

    def test_the_prompt_carries_the_evidence_and_asks_for_nothing_else(
        self, db, report, monkeypatch
    ):
        llm = _stub(
            monkeypatch,
            LLMResponse(status=LLMStatus.OK, text="Confidence 0.73.", provider="gemini"),
        )

        generate_for_report(db, report, force=False)

        system = next(m.content for m in llm._messages if m.role == "system")
        user = next(m.content for m in llm._messages if m.role == "user")
        assert "ONLY the facts in the EVIDENCE block" in system
        assert "0.73" in user and "95.2" in user


class TestTheCacheKey:
    """A stored narrative must not outlive the figures it describes."""

    def test_changing_the_report_changes_the_fingerprint(self, report):
        before = evidence_fingerprint(build_evidence(report), "gemini-2.5-flash")
        report.summary = "Scored 12.0/100 (LOW)."
        after = evidence_fingerprint(build_evidence(report), "gemini-2.5-flash")

        assert before != after

    def test_changing_the_model_changes_the_fingerprint(self, report):
        evidence = build_evidence(report)

        assert evidence_fingerprint(evidence, "gemini-2.5-flash") != (
            evidence_fingerprint(evidence, "gemini-3.0-pro")
        )

    def test_a_stale_narrative_is_regenerated_not_served(
        self, db, report, monkeypatch
    ):
        _stub(
            monkeypatch,
            LLMResponse(status=LLMStatus.OK, text="Confidence 0.73.", provider="gemini"),
        )
        generate_for_report(db, report)
        assert report.ai_narrative

        report.summary = "Scored 12.0/100 (LOW), confidence 0.11."
        db.commit()
        llm = _stub(
            monkeypatch,
            LLMResponse(status=LLMStatus.OK, text="Confidence 0.11.", provider="gemini"),
        )

        result = generate_for_report(db, report)

        assert result.status == "generated", "a changed report must not reuse old prose"
        assert llm.calls == 1
