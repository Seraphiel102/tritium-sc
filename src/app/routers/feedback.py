# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Operator feedback endpoint for reinforcement learning.

Operators confirm or reject system decisions (correlation, classification,
threat assessment). Feedback is stored as training data for self-improving
models. Every feedback event also updates the relevant training store
records so the supervised learning pipeline has ground-truth labels.

Endpoints:
    POST /api/feedback       — Submit operator feedback on a decision
    GET  /api/feedback/stats — Get training data statistics
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from loguru import logger

router = APIRouter(prefix="/api", tags=["feedback"])

VALID_DECISION_TYPES = {"correlation", "classification", "threat"}


class FeedbackRequest(BaseModel):
    """Operator feedback on a system decision."""
    target_id: str = Field(..., min_length=1, description="Target the feedback applies to")
    decision_type: str = Field(..., description="Type: correlation, classification, or threat")
    correct: bool = Field(..., description="Whether the system's decision was correct")
    notes: str = Field("", description="Operator notes")
    operator: str = Field("", description="Operator identifier")


@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest):
    """Submit operator feedback on a system decision.

    The feedback is stored in the training store for RL/ML pipelines.
    This allows the system to self-improve over time based on operator
    corrections.
    """
    # Validate decision_type
    if feedback.decision_type not in VALID_DECISION_TYPES:
        raise HTTPException(
            400,
            f"Invalid decision_type: {feedback.decision_type}. "
            f"Must be one of: {sorted(VALID_DECISION_TYPES)}",
        )

    # Store in training store
    try:
        from engine.intelligence.training_store import get_training_store
        store = get_training_store()
        row_id = store.log_feedback(
            target_id=feedback.target_id,
            decision_type=feedback.decision_type,
            correct=feedback.correct,
            notes=feedback.notes,
            operator=feedback.operator,
        )
    except Exception as e:
        logger.error(f"Failed to store feedback: {e}")
        raise HTTPException(500, f"Failed to store feedback: {e}")

    logger.info(
        f"Operator feedback: {feedback.operator or 'anonymous'} "
        f"{'confirmed' if feedback.correct else 'rejected'} "
        f"{feedback.decision_type} for {feedback.target_id}"
    )

    return {
        "status": "ok",
        "feedback_id": row_id,
        "target_id": feedback.target_id,
        "decision_type": feedback.decision_type,
        "correct": feedback.correct,
    }


@router.get("/feedback/stats")
async def get_feedback_stats():
    """Get training data statistics.

    Returns counts of correlation decisions, classification decisions,
    and operator feedback, including accuracy metrics.
    """
    try:
        from engine.intelligence.training_store import get_training_store
        store = get_training_store()
        return store.get_stats()
    except Exception as e:
        logger.error(f"Failed to get training stats: {e}")
        return {
            "correlation": {"total": 0, "confirmed": 0},
            "classification": {"total": 0, "corrected": 0},
            "feedback": {"total": 0, "correct": 0, "accuracy": 0.0},
        }
