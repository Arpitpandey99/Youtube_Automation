"""
Performance feedback loop: fetches YouTube/Instagram analytics,
stores metrics, and provides recommendations for future content.
"""

import json
from datetime import datetime, timedelta

from agents.db import (
    get_connection, insert_metrics, get_top_categories,
    upsert_topic_score, get_latest_metrics
)


def fetch_youtube_analytics(config: dict, video_id: str) -> dict:
    """Fetch analytics for a YouTube video using the YouTube Data API.

    Uses the videos.list endpoint (statistics part) which is available
    with the standard youtube scope (no separate Analytics API needed).
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    token_file = config["youtube"]["token_file"]
    creds = Credentials.from_authorized_user_file(token_file)

    youtube = build("youtube", "v3", credentials=creds)

    response = youtube.videos().list(
        part="statistics",
        id=video_id,
    ).execute()

    if not response.get("items"):
        return {}

    stats = response["items"][0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
    }


def fetch_and_store_metrics(config: dict, video_id: str, platform: str = "youtube"):
    """Fetch metrics for a video and store them in the database."""
    if platform == "youtube":
        metrics = fetch_youtube_analytics(config, video_id)
    else:
        metrics = {}

    if metrics:
        insert_metrics(video_id, platform, metrics)
        print(f"  Analytics stored for {video_id}: {metrics.get('views', 0)} views")

    return metrics


def update_topic_scores(config: dict):
    """Update topic scores based on latest video performance data."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT v.topic, v.category, m.views, m.ctr
           FROM videos v
           JOIN metrics m ON v.video_id = m.video_id
           WHERE m.fetched_at = (
               SELECT MAX(m2.fetched_at)
               FROM metrics m2 WHERE m2.video_id = m.video_id
           )"""
    ).fetchall()
    conn.close()

    for row in rows:
        upsert_topic_score(
            topic=row["topic"],
            category=row["category"],
            views=row["views"] or 0,
            ctr=row["ctr"] or 0,
        )


def analyze_performance(config: dict) -> dict:
    """Analyze historical performance and return recommendations.

    Returns dict with:
    - top_categories: best-performing content categories
    - avg_views: average views across all videos
    - recommendations: list of actionable insights
    """
    conn = get_connection()

    # Get top categories
    top_cats = get_top_categories(limit=5)

    # Get overall averages
    avg_row = conn.execute(
        """SELECT AVG(views) as avg_views, AVG(ctr) as avg_ctr, COUNT(*) as total
           FROM metrics
           WHERE fetched_at = (
               SELECT MAX(m2.fetched_at)
               FROM metrics m2 WHERE m2.video_id = metrics.video_id
           )"""
    ).fetchone()

    # Get best performing videos
    best_videos = conn.execute(
        """SELECT v.title, v.category, v.language, m.views, m.ctr
           FROM videos v
           JOIN metrics m ON v.video_id = m.video_id
           ORDER BY m.views DESC LIMIT 5"""
    ).fetchall()

    conn.close()

    recommendations = []
    if top_cats:
        best_cat = top_cats[0]["category"]
        recommendations.append(f"Focus on '{best_cat}' content - your top category")

    if avg_row and avg_row["total"] > 0:
        avg_views = avg_row["avg_views"] or 0
        if avg_views < 100:
            recommendations.append("Views are low - try more trending/seasonal topics")
        recommendations.append(f"Average views per video: {int(avg_views)}")

    return {
        "top_categories": top_cats,
        "avg_views": avg_row["avg_views"] if avg_row else 0,
        "avg_ctr": avg_row["avg_ctr"] if avg_row else 0,
        "total_videos": avg_row["total"] if avg_row else 0,
        "best_videos": [dict(r) for r in best_videos] if best_videos else [],
        "recommendations": recommendations,
    }


def get_performance_hints(config: dict) -> str:
    """Get a string of performance hints to inject into topic generation prompts."""
    analytics_enabled = config.get("analytics", {}).get("enabled", False)
    if not analytics_enabled:
        return ""

    try:
        analysis = analyze_performance(config)
    except Exception:
        return ""

    if not analysis["top_categories"]:
        return ""

    hints = ["Based on past performance, these categories work best:"]
    for cat in analysis["top_categories"][:3]:
        hints.append(f"  - {cat['category']} (score: {cat['avg_score']:.1f})")

    if analysis["recommendations"]:
        hints.append("Recommendations:")
        for rec in analysis["recommendations"][:2]:
            hints.append(f"  - {rec}")

    return "\n".join(hints)


def get_pending_analytics_videos(config: dict) -> list:
    """Get videos that need analytics fetched (uploaded > N hours ago, no recent metrics)."""
    delay_hours = config.get("analytics", {}).get("fetch_delay_hours", 48)
    cutoff = (datetime.now() - timedelta(hours=delay_hours)).isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT v.id, v.video_id, v.platform, v.title
           FROM videos v
           WHERE v.upload_date < ?
             AND v.video_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM metrics m
                 WHERE m.video_id = v.video_id
                   AND m.fetched_at > ?
             )""",
        (cutoff, cutoff)
    ).fetchall()
    conn.close()

    return [dict(r) for r in rows]
