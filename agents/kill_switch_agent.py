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
    5. Channel-level "Inauthentic Content" warning email from YouTube
    6. Daily API spend > 150% of 30-day average

Action on trigger:
    1. Write entry to kill_switch_events table
    2. Set pipeline_paused=True in data/system_state.json
    3. Send Telegram alert with diagnosis
    4. Pipeline resumes only via /resume command

# SCHEMA: Writes to kill_switch_events table.
#   CREATE TABLE kill_switch_events (
#     id INTEGER PRIMARY KEY,
#     trigger_type TEXT, severity TEXT,
#     metrics_snapshot TEXT,  -- JSON
#     resumed_at DATETIME,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#   );
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TriggerType(Enum):
    """Kill switch trigger types."""
    VIEW_CRASH = "view_crash"
    YPP_FLAG = "ypp_flag"
    SUB_LOSS = "sub_loss"
    AB_FAILURE = "ab_failure"
    INAUTHENTIC_WARNING = "inauthentic_warning"
    SPEND_SPIKE = "spend_spike"


@dataclass
class KillSwitchVerdict:
    """Result of a kill switch check.

    Attributes:
        triggered: Whether any kill switch condition fired.
        trigger_type: Which trigger fired (None if not triggered).
        severity: 'warning' or 'critical'.
        metrics_snapshot: Dict of relevant metrics at time of check.
        diagnosis: Human-readable explanation for Telegram alert.
    """
    triggered: bool = False
    trigger_type: TriggerType | None = None
    severity: str = "warning"
    metrics_snapshot: dict = field(default_factory=dict)
    diagnosis: str = ""


def check(config: dict | None = None) -> KillSwitchVerdict:
    """Run all 6 kill switch checks.

    Inputs:
        config: Pipeline config dict (optional, for Telegram alerting).

    Outputs:
        KillSwitchVerdict indicating whether the pipeline should be paused.

    Implementation plan:
        1. Check each of the 6 triggers
        2. If any fires: write to kill_switch_events, set pause flag,
           send Telegram alert
        3. Return verdict
    """
    # TODO: Check view crash (trigger 1)
    # TODO: Check YPP flag (trigger 2)
    # TODO: Check subscriber loss (trigger 3)
    # TODO: Check A/B failure (trigger 4)
    # TODO: Check inauthentic warning (trigger 5)
    # TODO: Check spend spike (trigger 6)
    # TODO: On trigger: write DB, set pause, alert
    raise NotImplementedError("kill_switch_agent.check() not yet implemented")


def is_paused() -> bool:
    """Check whether the pipeline is currently paused.

    Outputs:
        True if data/system_state.json has pipeline_paused=True.
    """
    # TODO: Read data/system_state.json
    raise NotImplementedError


def set_paused(paused: bool) -> None:
    """Set the pipeline pause state.

    Inputs:
        paused: True to pause, False to resume.
    """
    # TODO: Write to data/system_state.json
    raise NotImplementedError


def _check_view_crash() -> KillSwitchVerdict | None:
    """Trigger 1: Median views of last 5 < 30% of trailing 20 median."""
    # TODO: Query metrics table
    raise NotImplementedError


def _check_ypp_flag() -> KillSwitchVerdict | None:
    """Trigger 2: Any video with 'limited or no ads' flag."""
    # TODO: Check via YouTube API or manual flag in DB
    raise NotImplementedError


def _check_sub_loss() -> KillSwitchVerdict | None:
    """Trigger 3: Net subscriber loss over rolling 7 days."""
    # TODO: Query analytics data
    raise NotImplementedError


def _check_ab_failure() -> KillSwitchVerdict | None:
    """Trigger 4: Zero winning A/B variants in last 10 attempts."""
    # TODO: Query ab_variants table
    raise NotImplementedError


def _check_inauthentic_warning() -> KillSwitchVerdict | None:
    """Trigger 5: Channel-level 'Inauthentic Content' warning.

    This is a manual check — user sets a flag in config or system_state.
    """
    # TODO: Check manual flag
    raise NotImplementedError


def _check_spend_spike() -> KillSwitchVerdict | None:
    """Trigger 6: Daily API spend > 150% of 30-day average."""
    # TODO: Query api_costs table
    raise NotImplementedError
