# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ReID (Re-Identification) API endpoints.

Provides cross-camera person/vehicle re-identification matches,
embedding stats, match history, and person-grouped timeline data
for the ReID cross-camera tracking panel.

Endpoints:
    GET  /api/reid/matches   — recent cross-camera ReID matches
    GET  /api/reid/stats     — ReID store statistics
    GET  /api/reid/persons   — person-grouped sightings with timeline
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from engine.intelligence.reid_store import get_reid_store, _cosine_similarity

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


@router.get("/persons")
async def get_persons(max_persons: int = 20, threshold: float | None = None):
    """Get person-grouped sightings with cross-camera timeline.

    Clusters ReID entries by identity (using cosine similarity) and
    returns a list of persons, each with their camera appearances
    ordered by time. This powers the ReID cross-camera tracking panel.

    Returns a list of person groups, each containing:
    - person_id: cluster identifier
    - class_name: detection class
    - sightings: list of {target_id, camera_id, timestamp, confidence}
    - cameras: unique cameras this person appeared on
    - first_seen / last_seen: time range
    - match_confidence: average cross-camera similarity
    """
    store = get_reid_store()
    thresh = threshold if threshold is not None else store._threshold
    now = time.time()

    with store._lock:
        # Filter to non-expired entries
        entries = [
            e for e in store._entries
            if now - e.timestamp <= store._ttl
        ]

    if not entries:
        return []

    # Greedy clustering: assign each entry to the first cluster it matches
    clusters: list[list] = []
    cluster_centroids: list[list[float]] = []

    for entry in entries:
        assigned = False
        for idx, centroid in enumerate(cluster_centroids):
            sim = _cosine_similarity(entry.embedding, centroid)
            if sim >= thresh:
                clusters[idx].append(entry)
                assigned = True
                break
        if not assigned:
            clusters.append([entry])
            cluster_centroids.append(entry.embedding)

    # Build person response objects — only include multi-camera clusters
    # or all clusters if few exist
    persons = []
    for cluster_idx, cluster in enumerate(clusters):
        cameras = list(set(e.camera_id for e in cluster if e.camera_id))
        sightings = sorted(
            [
                {
                    "target_id": e.target_id,
                    "camera_id": e.camera_id,
                    "timestamp": e.timestamp,
                    "confidence": round(e.confidence, 3),
                    "dossier_id": e.dossier_id,
                }
                for e in cluster
            ],
            key=lambda s: s["timestamp"],
        )

        # Compute average cross-camera similarity
        cross_sims = []
        for i, a in enumerate(cluster):
            for b in cluster[i + 1:]:
                if a.camera_id != b.camera_id:
                    cross_sims.append(
                        _cosine_similarity(a.embedding, b.embedding)
                    )
        avg_sim = sum(cross_sims) / len(cross_sims) if cross_sims else 0.0

        persons.append({
            "person_id": f"reid_person_{cluster_idx}",
            "class_name": cluster[0].class_name,
            "sightings": sightings,
            "cameras": cameras,
            "first_seen": sightings[0]["timestamp"] if sightings else 0,
            "last_seen": sightings[-1]["timestamp"] if sightings else 0,
            "match_confidence": round(avg_sim, 4),
            "sighting_count": len(sightings),
            "cross_camera": len(cameras) > 1,
        })

    # Sort: cross-camera first, then by sighting count
    persons.sort(key=lambda p: (-int(p["cross_camera"]), -p["sighting_count"]))
    return persons[:max_persons]


@router.get("/stats")
async def get_stats():
    """Get ReID store statistics."""
    store = get_reid_store()
    return store.get_stats()
