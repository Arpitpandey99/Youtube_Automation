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

# SCHEMA: Writes to api_costs table.
#   CREATE TABLE api_costs (
#     id INTEGER PRIMARY KEY,
#     provider TEXT, endpoint TEXT,
#     cost_inr REAL, run_id TEXT,
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#   );
"""

from __future__ import annotations

from typing import Any, Callable
from functools import wraps


class BudgetExceededError(Exception):
    """Raised when a provider's monthly budget cap is reached."""

    def __init__(self, provider: str, spent: float, cap: float) -> None:
        self.provider = provider
        self.spent = spent
        self.cap = cap
        super().__init__(
            f"Budget exceeded for {provider}: spent ₹{spent:.2f} / cap ₹{cap:.2f}"
        )


def budget_guard(provider: str, monthly_cap_inr: float | None = None) -> Callable:
    """Decorator factory that enforces per-provider monthly budget caps.

    Inputs:
        provider: Provider name (e.g., "openai", "sarvam", "replicate").
        monthly_cap_inr: Monthly cap in INR. If None, reads from
                         config/budget.yaml.

    Outputs:
        Decorator that wraps a function with budget checking and cost logging.

    Behavior:
        - Before call: check current month's spend vs cap
        - If >= 100%: raise BudgetExceededError
        - If >= 80%: log warning + send Telegram alert
        - If >= 60%: log warning
        - After call: log the cost to api_costs table
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # TODO: Load cap from config/budget.yaml if monthly_cap_inr is None
            # TODO: Query api_costs for current month's spend
            # TODO: Check thresholds (60%, 80%, 100%)
            # TODO: Execute wrapped function
            # TODO: Log cost to api_costs table
            raise NotImplementedError("budget_guard not yet implemented")
        return wrapper
    return decorator


def log_cost(provider: str, endpoint: str, cost_inr: float,
             run_id: str = "") -> None:
    """Log an API call cost to the api_costs table.

    Inputs:
        provider: Provider name (e.g., "openai").
        endpoint: Specific endpoint or operation name.
        cost_inr: Cost in INR for this call.
        run_id: Pipeline run identifier.
    """
    # TODO: Insert into api_costs table
    raise NotImplementedError


def get_monthly_spend(provider: str) -> float:
    """Get the current month's total spend for a provider.

    Inputs:
        provider: Provider name.

    Outputs:
        float total INR spent this month.
    """
    # TODO: Query api_costs for current month, sum cost_inr
    raise NotImplementedError


def get_all_monthly_spend() -> dict[str, float]:
    """Get current month's spend for all providers.

    Outputs:
        dict mapping provider name → total INR spent this month.
    """
    # TODO: Query api_costs grouped by provider
    raise NotImplementedError


def load_budget_config() -> dict[str, float]:
    """Load monthly caps from config/budget.yaml.

    Outputs:
        dict mapping provider name → monthly cap in INR.
    """
    # TODO: Parse config/budget.yaml
    raise NotImplementedError
