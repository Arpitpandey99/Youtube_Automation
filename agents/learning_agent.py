"""
Learning Agent — Closes the analytics → strategy feedback loop.

Runs daily after analytics_agent. Reads performance data, updates cluster
weights in topic_scores, and writes a human-readable summary to
data/learning_log/<date>.md.

This is the reason v1 had analytics but no growth — data was collected but
never fed back into topic selection decisions.

Logic:
    1. Pull last 7 days of video performance from analytics_agent outputs
    2. Compute per-cluster CTR, retention, watch time
    3. Update topic_scores table:
       - Cluster CTR > median + 1σ → weight × 1.5
       - Cluster CTR < median - 1σ → weight × 0.5
       - 3 strikes (3 videos with CTR < 2%) → cluster auto-paused 30 days
    4. Identify format losers (e.g., 5-min vs 10-min retention comparison)
    5. Propose 2 new clusters/week based on competitor_agent top performers
    6. Write summary to data/learning_log/<date>.md

# SCHEMA: Writes to learning_log table.
#   CREATE TABLE learning_log (
#     id INTEGER PRIMARY KEY,
#     log_date DATE, summary_md TEXT,
#     weight_changes TEXT,  -- JSON
#     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
#   );
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LearningUpdate:
    """Result of a daily learning cycle.

    Attributes:
        date: ISO date string for this update.
        weight_changes: Dict mapping cluster_name → {old_weight, new_weight, reason}.
        paused_clusters: List of cluster names auto-paused (3-strike rule).
        proposed_clusters: List of new cluster suggestions from competitor data.
        format_insights: Dict with format-level findings (e.g., optimal duration).
        summary_md: Markdown summary for human review.
    """
    date: str = ""
    weight_changes: dict = field(default_factory=dict)
    paused_clusters: list[str] = field(default_factory=list)
    proposed_clusters: list[dict] = field(default_factory=list)
    format_insights: dict = field(default_factory=dict)
    summary_md: str = ""


def daily_update(config: dict | None = None) -> dict:
    """Run the daily learning cycle.

    Inputs:
        config: Pipeline config dict (optional, for API access).

    Outputs:
        dict with keys: date, weight_changes, paused_clusters,
        proposed_clusters, format_insights, summary_md.

    Implementation plan:
        1. Read last 7 days of metrics from DB
        2. Compute per-cluster statistics
        3. Apply weight update rules
        4. Check 3-strike pause conditions
        5. Read competitor_agent data for new cluster proposals
        6. Write summary to data/learning_log/<date>.md
        7. Write to learning_log DB table
    """
    # TODO: Read analytics data from metrics table
    # TODO: Compute cluster-level stats
    # TODO: Apply weight update rules to topic_scores
    # TODO: Check 3-strike cluster pause
    # TODO: Generate cluster proposals from competitor data
    # TODO: Write markdown summary
    # TODO: Write to learning_log table
    raise NotImplementedError("learning_agent.daily_update() not yet implemented")


def _compute_cluster_stats(days: int = 7) -> dict:
    """Compute per-cluster CTR, retention, and watch time stats.

    Inputs:
        days: Number of days to look back (default 7).

    Outputs:
        dict mapping cluster_name → {avg_ctr, avg_retention, avg_watch_time,
        video_count, median_ctr, std_ctr}.
    """
    # TODO: Query metrics joined with videos on cluster
    raise NotImplementedError


def _write_learning_log(date: str, summary_md: str, weight_changes: dict) -> None:
    """Write a learning log entry to both filesystem and DB.

    Inputs:
        date: ISO date string.
        summary_md: Markdown summary content.
        weight_changes: Dict of weight changes for JSON storage.
    """
    # TODO: Write to data/learning_log/<date>.md
    # TODO: Insert into learning_log table
    raise NotImplementedError
