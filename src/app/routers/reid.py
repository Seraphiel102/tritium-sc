# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ReID (Re-Identification) API endpoints.

Provides cross-camera person/vehicle re-identification matches,
embedding stats, and match history for the ReID Matches panel.

Endpoints:
    GET  /api/reid/matches   — recent cross-camera ReID matches
    GET  /api/reid/stats     — ReID store statistics
"""

from fastapi import APIRouter

from engine.intelligence.reid_store import get_reid_store

router = APIRouter(prefix="/api/reid", tags=["reid"])


@router.get("/matches")
async def get_matches(count: int = 50, camera_id: str | None = None):
    """Get recent cross-camera ReID matches from the store.

    Returns matches with similarity scores, camera sources,
    timestamps, and dossier links.
    """
    store = get_reid_store()
    # The store tracks matches internally but doesn't persist a match log.
    # We return the embeddings paired with their metadata so the frontend
    # can display cross-camera sightings.
    entries = store._entries[-count * 2:]  # Get recent entries

    # Build match pairs: find entries from different cameras with same class
    from engine.intelligence.reid_store import _cosine_similarity

    matches = []
    seen = set()
    threshold = store._threshold

    for i in range(len(entries) - 1, -1, -1):
        if len(matches) >= count:
            break
        a = entries[i]
        for j in range(i - 1, max(-1, i - 20), -1):
            b = entries[j]
            if a.camera_id == b.camera_id:
                continue
            if a.class_name != b.class_name:
                continue
            pair_key = tuple(sorted([a.target_id, b.target_id]))
            if pair_key in seen:
                continue
            sim = _cosine_similarity(a.embedding, b.embedding)
            if sim >= threshold:
                seen.add(pair_key)
                matches.append({
                    "target_a": a.target_id,
                    "target_b": b.target_id,
                    "camera_a": a.camera_id,
                    "camera_b": b.camera_id,
                    "class_name": a.class_name,
                    "similarity": round(sim, 4),
                    "timestamp_a": a.timestamp,
                    "timestamp_b": b.timestamp,
                    "dossier_id": a.dossier_id or b.dossier_id,
                    "confidence_a": a.confidence,
                    "confidence_b": b.confidence,
                })
                if len(matches) >= count:
                    break

    if camera_id:
        matches = [
            m for m in matches
            if m["camera_a"] == camera_id or m["camera_b"] == camera_id
        ]

    return matches


@router.get("/stats")
async def get_stats():
    """Get ReID store statistics."""
    store = get_reid_store()
    return store.get_stats()
