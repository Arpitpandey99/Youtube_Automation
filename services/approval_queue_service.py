"""
Approval Queue Service — State machine for the Telegram approval gate.

Manages the lifecycle of video candidates through the approval pipeline:
    pending → approved | rejected | timeout

Each candidate is enqueued after video assembly and dequeued either by
Telegram button press (approved/rejected) or by the hourly timeout check.

# SCHEMA: Uses approval_queue table.
#   CREATE TABLE approval_queue (
#     id INTEGER PRIMARY KEY,
#     run_id TEXT NOT NULL,
#     candidate_path TEXT,
#     quality_score INTEGER,
#     status TEXT DEFAULT 'pending',  -- pending|approved|rejected|timeout
#     telegram_message_id INTEGER,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
#     decided_at DATETIME,
#     decision_reason TEXT
#   );
"""

from __future__ import annotations

from datetime import datetime


def enqueue(
    run_id: str,
    candidate_path: str,
    quality_score: int,
    telegram_msg_id: int | None = None,
) -> int:
    """Add a new candidate to the approval queue.

    Inputs:
        run_id: Pipeline run identifier.
        candidate_path: Path to the assembled video file.
        quality_score: Total quality score (0-100) from quality_agent.
        telegram_msg_id: Telegram message ID (set after sending).

    Outputs:
        int row ID of the new queue entry.
    """
    # TODO: INSERT into approval_queue with status='pending'
    raise NotImplementedError


def mark_approved(run_id: str, reason: str = "user_approved") -> None:
    """Mark a candidate as approved.

    Inputs:
        run_id: Pipeline run identifier.
        reason: Approval reason string.
    """
    # TODO: UPDATE approval_queue SET status='approved', decided_at=now
    raise NotImplementedError


def mark_rejected(run_id: str, reason: str = "user_rejected") -> None:
    """Mark a candidate as rejected.

    Inputs:
        run_id: Pipeline run identifier.
        reason: Rejection reason string.
    """
    # TODO: UPDATE approval_queue SET status='rejected', decided_at=now
    raise NotImplementedError


def mark_timeout(run_id: str) -> None:
    """Mark a candidate as timed out (auto-reject).

    Inputs:
        run_id: Pipeline run identifier.
    """
    # TODO: UPDATE approval_queue SET status='timeout', decided_at=now
    raise NotImplementedError


def get_pending() -> list[dict]:
    """Get all pending candidates.

    Outputs:
        list of dicts with keys: id, run_id, candidate_path, quality_score,
        telegram_message_id, created_at.
    """
    # TODO: SELECT * FROM approval_queue WHERE status='pending'
    raise NotImplementedError


def get_approved() -> list[dict]:
    """Get all approved candidates not yet uploaded.

    Outputs:
        list of dicts with keys: id, run_id, candidate_path, quality_score,
        decided_at.
    """
    # TODO: SELECT * FROM approval_queue WHERE status='approved'
    raise NotImplementedError


def get_timed_out(hours: int = 24) -> list[dict]:
    """Get pending candidates that have exceeded the timeout window.

    Inputs:
        hours: Number of hours after which a pending entry times out.

    Outputs:
        list of dicts for candidates pending longer than `hours`.
    """
    # TODO: SELECT WHERE status='pending' AND created_at < now - hours
    raise NotImplementedError


def update_telegram_msg_id(run_id: str, telegram_msg_id: int) -> None:
    """Update the Telegram message ID for a queued candidate.

    Inputs:
        run_id: Pipeline run identifier.
        telegram_msg_id: Telegram message ID after sending.
    """
    # TODO: UPDATE approval_queue SET telegram_message_id
    raise NotImplementedError
