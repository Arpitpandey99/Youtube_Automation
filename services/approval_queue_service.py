"""
Approval Queue Service — State machine for the Telegram approval gate.

Manages the lifecycle of video candidates through the approval pipeline:
    pending → approved | rejected | timeout

Each candidate is enqueued after video assembly and dequeued either by
Telegram button press (approved/rejected) or by the hourly timeout check.
"""

from __future__ import annotations

from agents.db import (
    insert_approval_queue,
    update_approval_status,
    update_approval_telegram_id,
    get_pending_approvals,
    get_approved_candidates,
    get_timed_out_approvals,
)


def enqueue(
    run_id: str,
    candidate_path: str,
    quality_score: int,
    telegram_msg_id: int | None = None,
) -> int:
    """Add a new candidate to the approval queue.

    Args:
        run_id: Pipeline run identifier.
        candidate_path: Path to the assembled video file.
        quality_score: Total quality score (0-100) from quality_agent.
        telegram_msg_id: Telegram message ID (set after sending).

    Returns:
        int row ID of the new queue entry.
    """
    return insert_approval_queue(
        run_id=run_id,
        candidate_path=candidate_path,
        quality_score=quality_score,
        telegram_message_id=telegram_msg_id,
    )


def mark_approved(run_id: str, reason: str = "user_approved") -> None:
    """Mark a candidate as approved.

    Args:
        run_id: Pipeline run identifier.
        reason: Approval reason string.
    """
    update_approval_status(run_id, "approved", reason)


def mark_rejected(run_id: str, reason: str = "user_rejected") -> None:
    """Mark a candidate as rejected.

    Args:
        run_id: Pipeline run identifier.
        reason: Rejection reason string.
    """
    update_approval_status(run_id, "rejected", reason)


def mark_timeout(run_id: str) -> None:
    """Mark a candidate as timed out (auto-reject).

    Args:
        run_id: Pipeline run identifier.
    """
    update_approval_status(run_id, "timeout", "auto-rejected: 24h timeout")


def get_pending() -> list[dict]:
    """Get all pending candidates.

    Returns:
        list of dicts with approval_queue row data.
    """
    return get_pending_approvals()


def get_approved() -> list[dict]:
    """Get all approved candidates not yet uploaded.

    Returns:
        list of dicts with approval_queue row data.
    """
    return get_approved_candidates()


def get_timed_out(hours: int = 24) -> list[dict]:
    """Get pending candidates that have exceeded the timeout window.

    Args:
        hours: Number of hours after which a pending entry times out.

    Returns:
        list of dicts for candidates pending longer than `hours`.
    """
    return get_timed_out_approvals(hours)


def update_telegram_msg_id(run_id: str, telegram_msg_id: int) -> None:
    """Update the Telegram message ID for a queued candidate.

    Args:
        run_id: Pipeline run identifier.
        telegram_msg_id: Telegram message ID after sending.
    """
    update_approval_telegram_id(run_id, telegram_msg_id)


def process_timeouts(hours: int = 24) -> int:
    """Find and auto-reject all timed-out candidates.

    Args:
        hours: Timeout window in hours.

    Returns:
        Number of candidates timed out.
    """
    timed_out = get_timed_out(hours)
    for entry in timed_out:
        mark_timeout(entry["run_id"])
    return len(timed_out)
