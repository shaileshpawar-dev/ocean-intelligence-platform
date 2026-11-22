"""Knowledge-graph endpoints over the platform's own foreign keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.knowledge_graph.builder import (
    MAX_NODES,
    NODE_TYPES,
    build_graph,
    default_center,
    graph_summary,
)

router = APIRouter(tags=["knowledge-graph"])


# Declared before the graph route. Neither takes a path parameter today, so
# they cannot collide -- but /models/{name}/{version} swallowing
# /models/sar-candidates/evaluation was exactly this shape, and adding a
# parameterised path later would reintroduce it.
@router.get(
    "/knowledge-graph/summary",
    summary="Node and edge counts by type, straight from the tables",
)
def summary(db: Session = Depends(get_db)) -> dict:
    """Counts for the whole graph, not a sample of it."""
    return graph_summary(db)


@router.get(
    "/knowledge-graph",
    summary="A subgraph of linked records around one centre",
)
def knowledge_graph(
    center_type: str | None = Query(
        None,
        description=(
            "Node type to centre on. Defaults to the region with the most "
            f"events. One of: {', '.join(NODE_TYPES)}"
        ),
    ),
    center_id: str | None = Query(
        None,
        description=(
            "Primary key, or the human-facing identifier (region code, "
            "evt_... , cand_...)."
        ),
    ),
    depth: int = Query(1, ge=1, le=2, description="Hops from the centre."),
    limit: int = Query(
        MAX_NODES, ge=1, le=MAX_NODES, description="Maximum nodes returned."
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Walk declared foreign keys outward from one record.

    Every edge corresponds to a row holding another row's key. Nothing is
    inferred from proximity or similarity, so an absent edge means an absent
    relationship rather than a relationship this endpoint failed to guess.
    """
    if center_type is None or center_id is None:
        fallback = default_center(db)
        if fallback is None:
            return {
                "center": None,
                "center_type": None,
                "depth": depth,
                "limit": limit,
                "truncated": False,
                "nodes": [],
                "edges": [],
                "node_count": 0,
                "edge_count": 0,
                "notes": ["No records are stored, so there is nothing to link."],
            }
        center_type, center_id = fallback

    if center_type not in NODE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown centre type {center_type!r}. "
                f"Available: {', '.join(NODE_TYPES)}"
            ),
        )

    graph = build_graph(db, center_type, center_id, depth=depth, limit=limit)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {center_type} with identifier {center_id!r}",
        )
    return graph
