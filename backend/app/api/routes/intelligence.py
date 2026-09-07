"""Research, agent-workflow and report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tools import ToolRegistry
from app.agents.workflow import describe_workflow, run_event_analysis
from app.core.database import get_db
from app.llm.providers import get_llm
from app.models import AgentRun, PollutionEvent, Report
from app.rag.service import answer_question, corpus_stats, search

router = APIRouter(tags=["intelligence"])


@router.post("/research", summary="Ask the grounded research assistant")
def research(
    question: str = Body(..., embed=True, min_length=3, max_length=500),
    limit: int = Body(5, embed=True, ge=1, le=12),
    region: str | None = Body(None, embed=True),
    doc_type: str | None = Body(None, embed=True, description="regulation | reference"),
    db: Session = Depends(get_db),
) -> dict:
    """Answer a question strictly from the retrieved corpus.

    Three outcomes, always labelled by ``status``:

    * ``grounded`` -- passages retrieved and synthesised, every claim cited
    * ``retrieval_only`` -- passages returned verbatim; no LLM configured
    * ``no_evidence`` -- nothing relevant found, and the assistant declines

    The assistant never answers from a model's own knowledge. If the corpus
    is silent, so is the assistant.
    """
    return answer_question(
        db, question, limit=limit, region=region, doc_type=doc_type
    ).to_dict()


@router.get("/research/search", summary="Retrieve passages without synthesis")
def research_search(
    q: str = Query(..., min_length=2, max_length=300),
    limit: int = Query(6, ge=1, le=20),
    doc_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Raw retrieval, exposing BM25 scores and which terms matched."""
    hits = search(db, q, limit=limit, doc_type=doc_type)
    return {
        "query": q,
        "count": len(hits),
        "results": [hit.to_dict() for hit in hits],
    }


@router.get("/research/corpus", summary="Corpus size and composition")
def research_corpus(db: Session = Depends(get_db)) -> dict:
    """What is actually in the retrievable corpus, and what is not."""
    return corpus_stats(db)


@router.post("/agents/analyze-event", summary="Run the multi-agent workflow on an event")
def analyze_event(
    event_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
) -> dict:
    """Execute Detection → Context → Research → Risk → Report.

    A linear state machine: agents never call each other and never loop, so
    the run terminates in a bounded number of tool calls. Every stage works
    without an LLM; a configured model writes only the report narrative.

    Returns the per-agent findings, the full tool-call trace and the
    assembled report.
    """
    exists = db.scalar(
        select(PollutionEvent.id).where(PollutionEvent.event_id == event_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail=f"No event {event_id!r}")
    return run_event_analysis(db, event_id)


@router.get("/agents", summary="Workflow and agent catalogue")
def agents_catalogue(db: Session = Depends(get_db)) -> dict:
    """Describe the workflow, its stages, the tools and the LLM status."""
    llm = get_llm()
    return {
        **describe_workflow(),
        "tools": ToolRegistry(db=db).describe(),
        "llm": llm.describe(),
    }


@router.get("/agents/runs", summary="Recent agent workflow runs")
def agent_runs(
    limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> dict:
    """List recent runs with their timing and tool counts."""
    rows = db.scalars(
        select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "items": [
            {
                "workflow_id": run.workflow_id,
                "workflow_name": run.workflow_name,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "duration_ms": round(run.duration_ms, 2) if run.duration_ms else None,
                "llm_provider": run.llm_provider,
                "tool_calls": len(run.steps or []),
                "error": run.error,
            }
            for run in rows
        ],
    }


@router.post("/reports/generate", summary="Generate an intelligence report")
def generate_report(
    event_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
) -> dict:
    """Run the workflow and return the persisted report.

    The report keeps OBSERVED, DETECTED, INFERRED, FORECAST and retrieved
    evidence in separate sections, each carrying its own evidence level, so a
    reader can see which parts are measurements and which are inference.
    """
    exists = db.scalar(
        select(PollutionEvent.id).where(PollutionEvent.event_id == event_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail=f"No event {event_id!r}")

    result = run_event_analysis(db, event_id)
    if "report_id" not in result:
        raise HTTPException(
            status_code=422,
            detail=f"Workflow did not produce a report: {result.get('status')}",
        )
    return get_report(result["report_id"], db)


@router.get("/reports", summary="List generated reports")
def list_reports(
    limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> dict:
    """Recent reports, newest first."""
    rows = db.scalars(
        select(Report).order_by(Report.created_at.desc()).limit(limit)
    ).all()
    return {
        "count": len(rows),
        "items": [
            {
                "report_id": r.report_id,
                "title": r.title,
                "workflow_id": r.workflow_id,
                "created_at": r.created_at.isoformat(),
                "contains_simulated_data": r.contains_simulated_data,
                "source_count": len(r.sources or []),
            }
            for r in rows
        ],
    }


@router.get("/reports/{report_id}", summary="Fetch one report")
def get_report(report_id: str, db: Session = Depends(get_db)) -> dict:
    """Return a stored report with its provenance map."""
    report = db.scalar(select(Report).where(Report.report_id == report_id))
    if report is None:
        raise HTTPException(status_code=404, detail=f"No report {report_id!r}")
    return {
        "report_id": report.report_id,
        "title": report.title,
        "summary": report.summary,
        "sections": report.sections,
        "provenance": report.provenance,
        "sources": report.sources,
        "generated_by": report.generated_by,
        "workflow_id": report.workflow_id,
        "created_at": report.created_at.isoformat(),
        "contains_simulated_data": report.contains_simulated_data,
    }


@router.get("/reports/{report_id}/text", summary="Report as plain text")
def report_text(report_id: str, db: Session = Depends(get_db)) -> dict:
    """Render a report in the fixed-width form used for briefings."""
    report = db.scalar(select(Report).where(Report.report_id == report_id))
    if report is None:
        raise HTTPException(status_code=404, detail=f"No report {report_id!r}")
    return {"report_id": report.report_id, "text": _render(report)}


def _render(report: Report) -> str:
    """Format a report as fixed-width text with explicit evidence labels.

    The renderer's own chrome -- headings, labels, separators -- is ASCII so
    it never mangles in a Windows console or a cp1252 pipe. Content drawn
    from the corpus may contain Unicode: real instrument titles use
    em-dashes, and rewriting a source's name would be worse than the
    encoding risk.
    """
    sections = report.sections or {}
    observed = sections.get("observed", {})
    detected = sections.get("detected", {})
    inferred = sections.get("inferred", {})
    forecast = sections.get("forecast", {})
    evidence = sections.get("retrieved_evidence", {})

    line = "=" * 66
    out: list[str] = [line, "OCEAN INTELLIGENCE REPORT", line]
    if report.contains_simulated_data:
        out += [
            "",
            "*** SIMULATED DATA - this report describes demo-mode records ***",
            "*** and no real satellite acquisition.                       ***",
        ]
    out += [
        "",
        f"Report      {report.report_id}",
        f"Generated   {report.created_at.isoformat()}",
        f"Workflow    {report.workflow_id}",
        f"Produced by {report.generated_by}",
        "",
        "-" * 66,
        "OBSERVED - measured from sensor data",
        "-" * 66,
        f"Region              {observed.get('region')}",
        f"Coordinates         {observed.get('coordinates')}",
        f"Acquired            {observed.get('acquired_at')}",
        f"Platform            {observed.get('platform')}",
        f"Mean backscatter    {observed.get('mean_backscatter_db')} dB",
        f"Contrast p90-p10    {observed.get('contrast_db')} dB",
        f"Distance to coast   ~{observed.get('distance_to_coast_km')} km",
        f"Nearest protected   {observed.get('nearest_protected_area')}",
        f"Observed days/60    {observed.get('observed_days_in_window')}",
        "",
        "-" * 66,
        "DETECTED - detector output, carries uncertainty",
        "-" * 66,
        f"Signature           {detected.get('signature')}",
        f"Confidence          {detected.get('confidence')} "
        f"(calibrated: {detected.get('confidence_is_calibrated')})",
        f"Method              {detected.get('detection_method')}",
        f"Model               {detected.get('model_version')}",
        f"Estimated area      {detected.get('estimated_area_km2')} km2 "
        f"via {detected.get('area_method')}",
        "",
        "Caveats:",
    ]
    out += [f"  - {c}" for c in detected.get("caveats", [])] or ["  (none)"]

    out += [
        "",
        "-" * 66,
        "INFERRED - derived by the deterministic risk engine",
        "-" * 66,
        f"Risk score          {inferred.get('risk_score')}/100 "
        f"({inferred.get('severity')})",
        f"Engine              {inferred.get('engine_version')}",
        "",
        "Contributions:",
    ]
    for contribution in inferred.get("contributions", []):
        out.append(
            f"  {contribution['factor']:<26} "
            f"{contribution['points']:>6.1f} / {contribution['max_points']:<5.0f}"
        )
    if inferred.get("missing_factors"):
        out += [
            "",
            f"  Not evaluated: {', '.join(inferred['missing_factors'])}",
            "  Score renormalised over the remaining factors - a PARTIAL",
            "  assessment, not a low one.",
        ]

    out += [
        "",
        "-" * 66,
        "FORECAST - projection, not observation",
        "-" * 66,
        f"Kind                {forecast.get('kind')}",
        f"Model               {forecast.get('model')}",
        f"Beats naive         {forecast.get('beats_naive')}",
    ]
    for band in forecast.get("bands", []):
        out.append(
            f"  +{band['horizon_days']:<3}d {band['date']}  "
            f"{band['risk']:>5} {band['severity']:<9} "
            f"[{band['lower']} .. {band['upper']}]"
        )
    out += ["", f"  {forecast.get('scope_note')}"]

    out += ["", "-" * 66, "RETRIEVED EVIDENCE - corpus sources", "-" * 66]
    for index, source in enumerate(evidence.get("sources", []), 1):
        out += [
            f"[{index}] {source['title']}",
            f"    {source['doc_type']} | {source.get('source_url')}",
        ]
    if not evidence.get("sources"):
        out.append("  (no corpus passage matched)")

    out += ["", "-" * 66, "SUMMARY", "-" * 66, report.summary or "(none)", "", line]
    return "\n".join(out)
