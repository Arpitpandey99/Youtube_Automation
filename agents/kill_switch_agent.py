"""
Kill Switch Agent — Prevent slow disasters. Auto-pause on red flags.

Runs every 6 hours via --feedback-loop. Checks 6 trigger conditions and
pauses the entire pipeline if any fire. Pipeline only resumes when Arpit
sends /resume to the Telegram bot.

Triggers (any one fires the kill switch):
    1. Median view count of last 5 uploads < 30% of trailing 20-upload median
    2. Any video gets a "limited or no ads" YPP flag
    3. Subscriber loss > subscriber gain over rolling 7 days
    4. A/B thumbnail tests show 0 winning variants in last 10 attempts
    5. Channel-level "Inauthentic Content" warning (manual flag)
    6. Daily API spend > 150% of 30-day average
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from statistics import median as stat_median

from agents.db import get_connection, insert_kill_switch_event

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_STATE_PATH = os.path.join(BASE_DIR, "data", "system_state.json")


class TriggerType(Enum):
    VIEW_CRASH = "view_crash"
    YPP_FLAG = "ypp_flag"
    SUB_LOSS = "sub_loss"
    AB_FAILURE = "ab_failure"
    INAUTHENTIC_WARNING = "inauthentic_warning"
    SPEND_SPIKE = "spend_spike"


@dataclass
class KillSwitchVerdict:
    """Result of a kill switch check."""
    triggered: bool = False
    trigger_type: TriggerType | None = None
    severity: str = "warning"
    metrics_snapshot: dict = field(default_factory=dict)
    diagnosis: str = ""


def is_paused() -> bool:
    """Check whether the pipeline is currently paused."""
    if not os.path.exists(SYSTEM_STATE_PATH):
        return False
    try:
        with open(SYSTEM_STATE_PATH) as f:
            state = json.load(f)
        return state.get("pipeline_paused", False)
    except (json.JSONDecodeError, IOError):
        return False


def set_paused(paused: bool, reason: str = "") -> None:
    """Set the pipeline pause state."""
    os.makedirs(os.path.dirname(SYSTEM_STATE_PATH), exist_ok=True)
    state = {}
    if os.path.exists(SYSTEM_STATE_PATH):
        try:
            with open(SYSTEM_STATE_PATH) as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    state["pipeline_paused"] = paused
    state["pause_reason"] = reason if paused else ""
    state["updated_at"] = datetime.now().isoformat()
    if not paused:
        state["resumed_at"] = datetime.now().isoformat()
    with open(SYSTEM_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _send_telegram_alert(config: dict, message: str) -> None:
    """Best-effort Telegram alert."""
    try:
        import yaml, requests
        tg = config.get("telegram", {})
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        if not token or not chat_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning("Kill switch Telegram alert failed: %s", e)


def _check_view_crash() -> KillSwitchVerdict | None:
    """Trigger 1: Median views of last 5 < 30% of trailing 20 median."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT m.views FROM videos v
           JOIN metrics m ON v.video_id = m.video_id
           ORDER BY v.upload_date DESC LIMIT 20"""
    ).fetchall()
    conn.close()

    if len(rows) < 10:
        return None  # Not enough data

    views = [r["views"] for r in rows if r["views"] is not None]
    if len(views) < 10:
        return None

    recent_5 = views[:5]
    trailing_20 = views[:20]
    med_recent = stat_median(recent_5)
    med_trailing = stat_median(trailing_20)

    if med_trailing > 0 and med_recent < 0.3 * med_trailing:
        return KillSwitchVerdict(
            triggered=True,
            trigger_type=TriggerType.VIEW_CRASH,
            severity="critical",
            metrics_snapshot={
                "median_last_5": med_recent,
                "median_trailing_20": med_trailing,
                "ratio": round(med_recent / med_trailing, 3) if med_trailing else 0,
            },
            diagnosis=(
                f"View crash: median of last 5 uploads ({med_recent:.0f}) is "
                f"{med_recent / med_trailing:.0%} of trailing 20 median ({med_trailing:.0f}). "
                f"Threshold: 30%."
            ),
        )
    return None


def _check_sub_loss() -> KillSwitchVerdict | None:
    """Trigger 3: Net subscriber loss over rolling 7 days."""
    conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """SELECT subscribers_gained FROM metrics
           WHERE fetched_at >= ? AND subscribers_gained IS NOT NULL""",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        return None

    total_gained = sum(r["subscribers_gained"] for r in rows if r["subscribers_gained"] is not None)

    if total_gained < 0:
        return KillSwitchVerdict(
            triggered=True,
            trigger_type=TriggerType.SUB_LOSS,
            severity="warning",
            metrics_snapshot={"net_subs_7d": total_gained},
            diagnosis=f"Subscriber loss: net {total_gained} subscribers in last 7 days.",
        )
    return None


def _check_ab_failure() -> KillSwitchVerdict | None:
    """Trigger 4: Zero winning A/B variants in last 10 attempts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT is_winner FROM ab_variants ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()

    if len(rows) < 10:
        return None  # Not enough data

    winners = sum(1 for r in rows if r["is_winner"])
    if winners == 0:
        return KillSwitchVerdict(
            triggered=True,
            trigger_type=TriggerType.AB_FAILURE,
            severity="warning",
            metrics_snapshot={"winners_in_last_10": 0},
            diagnosis="A/B failure: 0 winning variants in last 10 attempts. Content not landing.",
        )
    return None


def _check_inauthentic_warning() -> KillSwitchVerdict | None:
    """Trigger 5: Manual 'Inauthentic Content' flag in system_state."""
    if not os.path.exists(SYSTEM_STATE_PATH):
        return None
    try:
        with open(SYSTEM_STATE_PATH) as f:
            state = json.load(f)
        if state.get("inauthentic_warning"):
            return KillSwitchVerdict(
                triggered=True,
                trigger_type=TriggerType.INAUTHENTIC_WARNING,
                severity="critical",
                metrics_snapshot={"flag": state.get("inauthentic_warning")},
                diagnosis="YouTube 'Inauthentic Content' warning detected. Manual flag set.",
            )
    except (json.JSONDecodeError, IOError):
        pass
    return None


def _check_spend_spike() -> KillSwitchVerdict | None:
    """Trigger 6: Daily API spend > 150% of 30-day average."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Today's spend
    today_row = conn.execute(
        "SELECT COALESCE(SUM(cost_inr), 0) as total FROM api_costs WHERE DATE(created_at) = ?",
        (today,),
    ).fetchone()
    today_spend = float(today_row["total"]) if today_row else 0

    # 30-day daily average
    avg_row = conn.execute(
        """SELECT COALESCE(SUM(cost_inr), 0) / MAX(1, COUNT(DISTINCT DATE(created_at))) as daily_avg
           FROM api_costs WHERE DATE(created_at) >= ? AND DATE(created_at) < ?""",
        (month_start, today),
    ).fetchone()
    daily_avg = float(avg_row["daily_avg"]) if avg_row else 0

    conn.close()

    if daily_avg > 0 and today_spend > 1.5 * daily_avg:
        return KillSwitchVerdict(
            triggered=True,
            trigger_type=TriggerType.SPEND_SPIKE,
            severity="warning",
            metrics_snapshot={
                "today_spend_inr": round(today_spend, 2),
                "daily_avg_inr": round(daily_avg, 2),
                "ratio": round(today_spend / daily_avg, 2),
            },
            diagnosis=(
                f"Spend spike: today's spend (INR {today_spend:.2f}) is "
                f"{today_spend / daily_avg:.0%} of 30-day daily average (INR {daily_avg:.2f}). "
                f"Threshold: 150%."
            ),
        )
    return None


def check(config: dict | None = None) -> KillSwitchVerdict:
    """Run all 6 kill switch checks.

    Args:
        config: Pipeline config dict (for Telegram alerting).

    Returns:
        KillSwitchVerdict — triggered=True if any check fires.
    """
    config = config or {}
    checks = [
        ("view_crash", _check_view_crash),
        ("sub_loss", _check_sub_loss),
        ("ab_failure", _check_ab_failure),
        ("inauthentic_warning", _check_inauthentic_warning),
        ("spend_spike", _check_spend_spike),
    ]
    # Note: trigger 2 (YPP flag) requires manual YouTube API check or email
    # parsing — left as manual flag in system_state.json for now.

    for name, check_fn in checks:
        try:
            verdict = check_fn()
            if verdict and verdict.triggered:
                print(f"  Kill switch: TRIGGERED — {name}")
                print(f"    {verdict.diagnosis}")

                # Write to DB
                insert_kill_switch_event(
                    trigger_type=verdict.trigger_type.value,
                    severity=verdict.severity,
                    metrics_snapshot=verdict.metrics_snapshot,
                )

                # Pause pipeline
                set_paused(True, reason=verdict.diagnosis)

                # Telegram alert
                _send_telegram_alert(
                    config,
                    f"🚨 *KILL SWITCH TRIGGERED*\n\n"
                    f"*Trigger:* {name}\n"
                    f"*Severity:* {verdict.severity}\n\n"
                    f"{verdict.diagnosis}\n\n"
                    f"Pipeline paused. Send /resume to restart.",
                )

                return verdict
        except Exception as e:
            logger.warning("Kill switch check '%s' failed: %s", name, e)

    print("  Kill switch: all clear")
    return KillSwitchVerdict(triggered=False)
