"""
Budget Guard — Hard cost ceiling enforced in code.

Decorator-based utility (not an agent) that wraps every paid API call.
Tracks per-provider spend in the api_costs DB table and enforces monthly
caps defined in config/budget.yaml.

Usage:
    @budget_guard(provider="sarvam", monthly_cap_inr=400)
    def synthesize_audio(text): ...

Thresholds:
    60% of cap → log warning
    80% of cap → log warning + Telegram alert
   100% of cap → raise BudgetExceededError

Resets monthly on the 1st.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Any, Callable
from functools import wraps

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET_CONFIG_PATH = os.path.join(BASE_DIR, "config", "budget.yaml")


class BudgetExceededError(Exception):
    """Raised when a provider's monthly budget cap is reached."""

    def __init__(self, provider: str, spent: float, cap: float) -> None:
        self.provider = provider
        self.spent = spent
        self.cap = cap
        super().__init__(
            f"Budget exceeded for {provider}: spent INR {spent:.2f} / cap INR {cap:.2f}"
        )


def load_budget_config() -> dict:
    """Load monthly caps and thresholds from config/budget.yaml.

    Returns:
        dict with 'monthly_caps_inr' and 'alert_thresholds' keys.
    """
    if not os.path.exists(BUDGET_CONFIG_PATH):
        logger.warning("Budget config not found at %s, using defaults", BUDGET_CONFIG_PATH)
        return {
            "monthly_caps_inr": {"openai": 500, "sarvam": 400, "replicate": 700,
                                 "huggingface": 0, "web_search": 100, "total": 1500},
            "alert_thresholds": {"warning": 0.6, "alert": 0.8, "kill": 1.0},
        }
    with open(BUDGET_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def log_cost(provider: str, endpoint: str, cost_inr: float, run_id: str = "") -> None:
    """Log an API call cost to the api_costs table.

    Args:
        provider: Provider name (e.g., "openai").
        endpoint: Specific endpoint or operation name.
        cost_inr: Cost in INR for this call.
        run_id: Pipeline run identifier.
    """
    from agents.db import get_connection
    conn = get_connection()
    conn.execute(
        """INSERT INTO api_costs (provider, endpoint, cost_inr, run_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (provider, endpoint, cost_inr, run_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_monthly_spend(provider: str) -> float:
    """Get the current month's total spend for a provider.

    Args:
        provider: Provider name.

    Returns:
        Total INR spent this calendar month.
    """
    from agents.db import get_connection
    month_start = datetime.now().strftime("%Y-%m-01")
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_inr), 0) as total FROM api_costs "
        "WHERE provider = ? AND created_at >= ?",
        (provider, month_start),
    ).fetchone()
    conn.close()
    return float(row["total"]) if row else 0.0


def get_all_monthly_spend() -> dict[str, float]:
    """Get current month's spend for all providers.

    Returns:
        dict mapping provider name → total INR spent this month.
    """
    from agents.db import get_connection
    month_start = datetime.now().strftime("%Y-%m-01")
    conn = get_connection()
    rows = conn.execute(
        "SELECT provider, COALESCE(SUM(cost_inr), 0) as total FROM api_costs "
        "WHERE created_at >= ? GROUP BY provider",
        (month_start,),
    ).fetchall()
    conn.close()
    return {row["provider"]: float(row["total"]) for row in rows}


def _send_telegram_alert(message: str) -> None:
    """Best-effort Telegram alert for budget warnings."""
    try:
        config_path = os.path.join(BASE_DIR, "config.yaml")
        if not os.path.exists(config_path):
            return
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        tg = cfg.get("telegram", {})
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        if not token or not chat_id:
            return
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning("Telegram budget alert failed: %s", e)


def _check_budget(provider: str, cap: float) -> None:
    """Check current spend against cap and warn/alert/kill as needed.

    Args:
        provider: Provider name.
        cap: Monthly cap in INR.

    Raises:
        BudgetExceededError: If spend >= 100% of cap.
    """
    if cap <= 0:
        return

    spent = get_monthly_spend(provider)
    ratio = spent / cap
    budget_cfg = load_budget_config()
    thresholds = budget_cfg.get("alert_thresholds", {})

    if ratio >= thresholds.get("kill", 1.0):
        msg = (f"BUDGET KILL: {provider} at INR {spent:.2f}/{cap:.2f} "
               f"({ratio:.0%}). Blocking further calls.")
        logger.error(msg)
        _send_telegram_alert(f"🚨 {msg}")
        raise BudgetExceededError(provider, spent, cap)

    if ratio >= thresholds.get("alert", 0.8):
        msg = (f"BUDGET ALERT: {provider} at INR {spent:.2f}/{cap:.2f} "
               f"({ratio:.0%}). Approaching limit.")
        logger.warning(msg)
        _send_telegram_alert(f"⚠️ {msg}")

    elif ratio >= thresholds.get("warning", 0.6):
        logger.warning(
            "BUDGET WARNING: %s at INR %.2f/%.2f (%.0f%%)",
            provider, spent, cap, ratio * 100,
        )


def budget_guard(provider: str, monthly_cap_inr: float | None = None) -> Callable:
    """Decorator factory that enforces per-provider monthly budget caps.

    Args:
        provider: Provider name (e.g., "openai", "sarvam", "replicate").
        monthly_cap_inr: Monthly cap in INR. If None, reads from
                         config/budget.yaml.

    Returns:
        Decorator that wraps a function with budget checking and cost logging.

    The decorated function can optionally return a tuple of (result, cost_inr)
    to log the actual cost. If it returns a plain value, no cost is logged
    automatically — use log_cost() manually in that case.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Resolve cap
            cap = monthly_cap_inr
            if cap is None:
                cfg = load_budget_config()
                caps = cfg.get("monthly_caps_inr", {})
                cap = caps.get(provider, 0)

            # Pre-call budget check
            _check_budget(provider, cap)

            # Execute the wrapped function
            result = func(*args, **kwargs)

            # If the function returns (result, cost), log the cost
            if isinstance(result, tuple) and len(result) == 2:
                actual_result, cost = result
                if isinstance(cost, (int, float)) and cost > 0:
                    log_cost(provider, func.__name__, float(cost))
                return actual_result

            return result
        return wrapper
    return decorator
