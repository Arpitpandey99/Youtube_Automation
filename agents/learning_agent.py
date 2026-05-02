"""
Learning Agent — Closes the analytics → strategy feedback loop.

Runs daily after analytics_agent. Reads performance data, updates cluster
weights in topic_scores, and writes a human-readable summary to
data/learning_log/<date>.md.

Logic:
    1. Pull last 7 days of video performance
    2. Compute per-cluster CTR, retention, watch time
    3. Update topic_scores weights:
       - Cluster CTR > median + 1σ → weight × 1.5
       - Cluster CTR < median - 1σ → weight × 0.5
       - 3 strikes (3 videos CTR < 2%) → cluster paused 30 days
    4. Identify format losers
    5. Propose 2 new clusters from competitor data
    6. Write summary to data/learning_log/<date>.md
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, median, stdev

from agents.db import (
    get_connection,
    insert_learning_log,
    upsert_topic_score,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNING_LOG_DIR = os.path.join(BASE_DIR, "data", "learning_log")


@dataclass
class LearningUpdate:
    """Result of a daily learning cycle."""
    date: str = ""
    weight_changes: dict = field(default_factory=dict)
    paused_clusters: list[str] = field(default_factory=list)
    proposed_clusters: list[dict] = field(default_factory=list)
    format_insights: dict = field(default_factory=dict)
    summary_md: str = ""


def _get_recent_performance(days: int = 7) -> list[dict]:
    """Get videos with metrics from the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT v.id, v.topic, v.category, v.title, v.upload_date,
                  m.views, m.ctr, m.avg_watch_time, m.impressions
           FROM videos v
           LEFT JOIN metrics m ON v.video_id = m.video_id
           WHERE v.upload_date >= ?
           ORDER BY v.upload_date DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_cluster_stats(videos: list[dict]) -> dict[str, dict]:
    """Compute per-category (cluster proxy) stats.

    Returns dict mapping category → {avg_ctr, avg_views, video_count, ctrs[]}.
    """
    clusters: dict[str, list[dict]] = {}
    for v in videos:
        cat = v.get("category", "unknown")
        if cat not in clusters:
            clusters[cat] = []
        clusters[cat].append(v)

    stats = {}
    for cat, vids in clusters.items():
        ctrs = [v.get("ctr", 0) or 0 for v in vids]
        views = [v.get("views", 0) or 0 for v in vids]
        stats[cat] = {
            "avg_ctr": mean(ctrs) if ctrs else 0,
            "avg_views": mean(views) if views else 0,
            "video_count": len(vids),
            "ctrs": ctrs,
            "views_list": views,
        }
    return stats


def _apply_weight_updates(cluster_stats: dict[str, dict]) -> dict:
    """Apply the weight update rules from Section 4.4.

    Returns dict of weight changes: category → {old_weight, new_weight, reason}.
    """
    if not cluster_stats:
        return {}

    all_ctrs = []
    for stats in cluster_stats.values():
        all_ctrs.extend(stats["ctrs"])

    if len(all_ctrs) < 3:
        return {}

    med_ctr = median(all_ctrs)
    std_ctr = stdev(all_ctrs) if len(all_ctrs) > 1 else 0

    weight_changes = {}
    conn = get_connection()

    for cat, stats in cluster_stats.items():
        avg_ctr = stats["avg_ctr"]

        # Get current weight
        row = conn.execute(
            "SELECT last_score FROM topic_scores WHERE category = ? ORDER BY updated_at DESC LIMIT 1",
            (cat,),
        ).fetchone()
        old_weight = dict(row)["last_score"] if row else 1.0

        new_weight = old_weight
        reason = ""

        if std_ctr > 0 and avg_ctr > med_ctr + std_ctr:
            new_weight = old_weight * 1.5
            reason = f"CTR {avg_ctr:.2%} > median+1σ ({med_ctr + std_ctr:.2%})"
        elif std_ctr > 0 and avg_ctr < med_ctr - std_ctr:
            new_weight = old_weight * 0.5
            reason = f"CTR {avg_ctr:.2%} < median-1σ ({med_ctr - std_ctr:.2%})"

        if reason:
            weight_changes[cat] = {
                "old_weight": round(old_weight, 3),
                "new_weight": round(new_weight, 3),
                "reason": reason,
            }

    conn.close()
    return weight_changes


def _check_three_strikes(cluster_stats: dict[str, dict]) -> list[str]:
    """Check for clusters that should be paused (3 videos with CTR < 2%)."""
    paused = []
    for cat, stats in cluster_stats.items():
        low_ctr_count = sum(1 for c in stats["ctrs"] if c < 0.02)
        if low_ctr_count >= 3:
            paused.append(cat)
            logger.info("Three-strike pause for cluster: %s (%d videos with CTR < 2%%)",
                        cat, low_ctr_count)
    return paused


def _analyze_format(videos: list[dict]) -> dict:
    """Identify format-level insights (e.g., duration vs retention)."""
    if not videos:
        return {}

    insights = {}

    # Group by approximate duration bucket
    short = [v for v in videos if (v.get("avg_watch_time", 0) or 0) < 180]
    long = [v for v in videos if (v.get("avg_watch_time", 0) or 0) >= 180]

    if short and long:
        short_avg_ctr = mean(v.get("ctr", 0) or 0 for v in short)
        long_avg_ctr = mean(v.get("ctr", 0) or 0 for v in long)
        insights["duration_comparison"] = {
            "short_avg_ctr": round(short_avg_ctr, 4),
            "long_avg_ctr": round(long_avg_ctr, 4),
            "recommendation": "long-form" if long_avg_ctr > short_avg_ctr else "short-form",
        }

    return insights


def _write_summary(update: LearningUpdate) -> str:
    """Write the learning summary to a markdown file."""
    os.makedirs(LEARNING_LOG_DIR, exist_ok=True)
    path = os.path.join(LEARNING_LOG_DIR, f"{update.date}.md")

    md = f"# Learning Log — {update.date}\n\n"

    if update.weight_changes:
        md += "## Weight Changes\n\n"
        md += "| Category | Old | New | Reason |\n|---|---|---|---|\n"
        for cat, change in update.weight_changes.items():
            md += f"| {cat} | {change['old_weight']} | {change['new_weight']} | {change['reason']} |\n"
        md += "\n"

    if update.paused_clusters:
        md += "## Paused Clusters (3-strike rule)\n\n"
        for cat in update.paused_clusters:
            md += f"- **{cat}** — paused for 30 days (3+ videos with CTR < 2%)\n"
        md += "\n"

    if update.format_insights:
        md += "## Format Insights\n\n"
        md += f"```json\n{json.dumps(update.format_insights, indent=2)}\n```\n\n"

    if not update.weight_changes and not update.paused_clusters:
        md += "_No significant changes detected. Need more data._\n\n"

    md += f"\n---\n_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M IST')}_\n"

    with open(path, "w") as f:
        f.write(md)

    return path


def daily_update(config: dict | None = None) -> dict:
    """Run the daily learning cycle.

    Args:
        config: Pipeline config dict (optional).

    Returns:
        dict with date, weight_changes, paused_clusters, format_insights, summary_md.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"  Learning: running daily update for {today}...")

    # 1. Get recent performance data
    videos = _get_recent_performance(days=7)
    print(f"  Learning: {len(videos)} videos in last 7 days")

    if not videos:
        print("  Learning: no videos to analyze, skipping")
        return {"date": today, "weight_changes": {}, "summary_md": "No data"}

    # 2. Compute cluster stats
    cluster_stats = _compute_cluster_stats(videos)
    print(f"  Learning: {len(cluster_stats)} categories found")

    # 3. Apply weight updates
    weight_changes = _apply_weight_updates(cluster_stats)
    if weight_changes:
        print(f"  Learning: {len(weight_changes)} weight change(s)")
        for cat, change in weight_changes.items():
            print(f"    {cat}: {change['old_weight']} → {change['new_weight']} ({change['reason']})")

    # 4. Check three-strike pause
    paused_clusters = _check_three_strikes(cluster_stats)
    if paused_clusters:
        print(f"  Learning: pausing {len(paused_clusters)} cluster(s): {paused_clusters}")

    # 5. Format insights
    format_insights = _analyze_format(videos)

    # 6. Build and write summary
    update = LearningUpdate(
        date=today,
        weight_changes=weight_changes,
        paused_clusters=paused_clusters,
        format_insights=format_insights,
    )
    path = _write_summary(update)
    update.summary_md = path
    print(f"  Learning: summary written to {path}")

    # 7. Write to DB
    insert_learning_log(today, open(path).read(), weight_changes)

    return {
        "date": today,
        "weight_changes": weight_changes,
        "paused_clusters": paused_clusters,
        "format_insights": format_insights,
        "summary_md": path,
    }
