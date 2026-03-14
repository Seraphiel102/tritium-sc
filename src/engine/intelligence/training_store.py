# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RL training data collection store.

Logs every correlation decision, classification decision, and operator
feedback into a SQLite database for future model training. This is the
foundation for self-improving target correlation and classification.

The store captures:
- Correlation decisions: target pairs, features, scores, outcomes
- Classification decisions: device features, predicted types, confidence
- Operator feedback: confirmations/rejections of system decisions

All data is stored in SQLite for offline training pipeline consumption.
"""
from __future__ import annotations

import json
import sqlite3
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class TrainingStore:
    """SQLite-backed store for ML training data collection.

    Thread-safe. Stores correlation decisions, classification decisions,
    and operator feedback for reinforcement learning pipelines.
    """

    def __init__(self, db_path: str | Path = "data/training.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS correlation_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_a_id TEXT NOT NULL,
                        target_b_id TEXT NOT NULL,
                        features TEXT NOT NULL,  -- JSON
                        score REAL NOT NULL,
                        decision TEXT NOT NULL,
                        outcome TEXT,
                        source TEXT DEFAULT 'correlator',
                        timestamp REAL NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS classification_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_id TEXT NOT NULL,
                        features TEXT NOT NULL,  -- JSON
                        predicted_type TEXT NOT NULL,
                        predicted_alliance TEXT DEFAULT 'unknown',
                        confidence REAL NOT NULL,
                        correct_type TEXT,
                        correct_alliance TEXT,
                        source TEXT DEFAULT 'classifier',
                        timestamp REAL NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS operator_feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        target_id TEXT NOT NULL,
                        decision_type TEXT NOT NULL,
                        correct INTEGER NOT NULL,  -- 0 or 1
                        notes TEXT DEFAULT '',
                        operator TEXT DEFAULT '',
                        timestamp REAL NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_corr_targets
                        ON correlation_decisions(target_a_id, target_b_id);
                    CREATE INDEX IF NOT EXISTS idx_class_target
                        ON classification_decisions(target_id);
                    CREATE INDEX IF NOT EXISTS idx_feedback_target
                        ON operator_feedback(target_id);
                    CREATE INDEX IF NOT EXISTS idx_feedback_type
                        ON operator_feedback(decision_type);
                """)
                conn.commit()
            finally:
                conn.close()

    def log_correlation(
        self,
        target_a_id: str,
        target_b_id: str,
        features: dict[str, Any],
        score: float,
        decision: str = "unknown",
        outcome: Optional[str] = None,
        source: str = "correlator",
    ) -> int:
        """Log a correlation decision for training.

        Args:
            target_a_id: First target ID.
            target_b_id: Second target ID.
            features: Feature dict (proximity, timing, etc.).
            score: Correlation score (0-1).
            decision: System decision (merge/related/unrelated).
            outcome: Confirmed outcome (correct/incorrect/uncertain).
            source: Subsystem that produced this decision.

        Returns:
            Row ID of the inserted record.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.execute(
                    """INSERT INTO correlation_decisions
                       (target_a_id, target_b_id, features, score,
                        decision, outcome, source, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        target_a_id,
                        target_b_id,
                        json.dumps(features),
                        score,
                        decision,
                        outcome,
                        source,
                        time.time(),
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid or 0
                logger.debug(
                    f"Training: logged correlation {target_a_id}<->{target_b_id} "
                    f"score={score:.2f} decision={decision}"
                )
                return row_id
            finally:
                conn.close()

    def log_classification(
        self,
        target_id: str,
        features: dict[str, Any],
        predicted_type: str,
        confidence: float,
        predicted_alliance: str = "unknown",
        correct_type: Optional[str] = None,
        correct_alliance: Optional[str] = None,
        source: str = "classifier",
    ) -> int:
        """Log a classification decision for training.

        Args:
            target_id: Target being classified.
            features: Device features (RSSI, OUI, UUIDs, etc.).
            predicted_type: System's predicted device type.
            confidence: System confidence (0-1).
            predicted_alliance: System's predicted alliance.
            correct_type: Operator-corrected type (if available).
            correct_alliance: Operator-corrected alliance (if available).
            source: Subsystem that produced this classification.

        Returns:
            Row ID of the inserted record.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.execute(
                    """INSERT INTO classification_decisions
                       (target_id, features, predicted_type, predicted_alliance,
                        confidence, correct_type, correct_alliance, source, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        target_id,
                        json.dumps(features),
                        predicted_type,
                        predicted_alliance,
                        confidence,
                        correct_type,
                        correct_alliance,
                        source,
                        time.time(),
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid or 0
                logger.debug(
                    f"Training: logged classification {target_id} "
                    f"type={predicted_type} conf={confidence:.2f}"
                )
                return row_id
            finally:
                conn.close()

    def log_feedback(
        self,
        target_id: str,
        decision_type: str,
        correct: bool,
        notes: str = "",
        operator: str = "",
    ) -> int:
        """Log operator feedback on a system decision.

        Args:
            target_id: Target the feedback applies to.
            decision_type: Type of decision (correlation/classification/threat).
            correct: Whether the system's decision was correct.
            notes: Operator notes.
            operator: Operator identifier.

        Returns:
            Row ID of the inserted record.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.execute(
                    """INSERT INTO operator_feedback
                       (target_id, decision_type, correct, notes, operator, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        target_id,
                        decision_type,
                        1 if correct else 0,
                        notes,
                        operator,
                        time.time(),
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid or 0
                logger.debug(
                    f"Training: logged feedback for {target_id} "
                    f"type={decision_type} correct={correct}"
                )
                return row_id
            finally:
                conn.close()

    def get_correlation_data(
        self, limit: int = 1000, outcome_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve correlation training data.

        Args:
            limit: Maximum number of records to return.
            outcome_only: If True, only return records with confirmed outcomes.

        Returns:
            List of correlation decision dicts.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                if outcome_only:
                    rows = conn.execute(
                        """SELECT * FROM correlation_decisions
                           WHERE outcome IS NOT NULL
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM correlation_decisions
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                return [
                    {**dict(r), "features": json.loads(r["features"])}
                    for r in rows
                ]
            finally:
                conn.close()

    def get_classification_data(
        self, limit: int = 1000, corrected_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve classification training data.

        Args:
            limit: Maximum number of records to return.
            corrected_only: If True, only return records with corrections.

        Returns:
            List of classification decision dicts.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                if corrected_only:
                    rows = conn.execute(
                        """SELECT * FROM classification_decisions
                           WHERE correct_type IS NOT NULL
                              OR correct_alliance IS NOT NULL
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM classification_decisions
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                return [
                    {**dict(r), "features": json.loads(r["features"])}
                    for r in rows
                ]
            finally:
                conn.close()

    def get_feedback(
        self, decision_type: Optional[str] = None, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Retrieve operator feedback records.

        Args:
            decision_type: Filter by decision type (optional).
            limit: Maximum number of records to return.

        Returns:
            List of feedback dicts.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                if decision_type:
                    rows = conn.execute(
                        """SELECT * FROM operator_feedback
                           WHERE decision_type = ?
                           ORDER BY timestamp DESC LIMIT ?""",
                        (decision_type, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM operator_feedback
                           ORDER BY timestamp DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_stats(self) -> dict[str, Any]:
        """Get training data statistics.

        Returns:
            Dict with counts of each data type.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                corr_total = conn.execute(
                    "SELECT COUNT(*) FROM correlation_decisions"
                ).fetchone()[0]
                corr_confirmed = conn.execute(
                    "SELECT COUNT(*) FROM correlation_decisions WHERE outcome IS NOT NULL"
                ).fetchone()[0]
                class_total = conn.execute(
                    "SELECT COUNT(*) FROM classification_decisions"
                ).fetchone()[0]
                class_corrected = conn.execute(
                    """SELECT COUNT(*) FROM classification_decisions
                       WHERE correct_type IS NOT NULL OR correct_alliance IS NOT NULL"""
                ).fetchone()[0]
                feedback_total = conn.execute(
                    "SELECT COUNT(*) FROM operator_feedback"
                ).fetchone()[0]
                feedback_correct = conn.execute(
                    "SELECT COUNT(*) FROM operator_feedback WHERE correct = 1"
                ).fetchone()[0]

                return {
                    "correlation": {
                        "total": corr_total,
                        "confirmed": corr_confirmed,
                    },
                    "classification": {
                        "total": class_total,
                        "corrected": class_corrected,
                    },
                    "feedback": {
                        "total": feedback_total,
                        "correct": feedback_correct,
                        "accuracy": (
                            feedback_correct / feedback_total
                            if feedback_total > 0
                            else 0.0
                        ),
                    },
                }
            finally:
                conn.close()

    def update_correlation_outcome(
        self, row_id: int, outcome: str,
    ) -> bool:
        """Update the outcome of a correlation decision after operator review.

        Args:
            row_id: The database row ID.
            outcome: The confirmed outcome (correct/incorrect/uncertain).

        Returns:
            True if the row was updated.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.execute(
                    "UPDATE correlation_decisions SET outcome = ? WHERE id = ?",
                    (outcome, row_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def update_classification_correction(
        self,
        row_id: int,
        correct_type: Optional[str] = None,
        correct_alliance: Optional[str] = None,
    ) -> bool:
        """Update a classification with operator corrections.

        Args:
            row_id: The database row ID.
            correct_type: Operator-corrected device type.
            correct_alliance: Operator-corrected alliance.

        Returns:
            True if the row was updated.
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                updates = []
                params: list[Any] = []
                if correct_type is not None:
                    updates.append("correct_type = ?")
                    params.append(correct_type)
                if correct_alliance is not None:
                    updates.append("correct_alliance = ?")
                    params.append(correct_alliance)
                if not updates:
                    return False
                params.append(row_id)
                cursor = conn.execute(
                    f"UPDATE classification_decisions SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_store: Optional[TrainingStore] = None


def get_training_store(db_path: str | Path = "data/training.db") -> TrainingStore:
    """Get or create the singleton TrainingStore instance."""
    global _store
    if _store is None:
        _store = TrainingStore(db_path)
    return _store
