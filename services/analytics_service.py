"""
Enhanced analytics service using YouTube Analytics API.
Fetches CTR, impressions, avg view duration, subscribers gained.
Computes category weights for topic generation optimization.
"""

import json
from datetime import datetime, timedelta

from agents.db import (
    get_connection, insert_metrics, get_top_categories,
    upsert_topic_score, get_category_weights, upsert_category_weight,
)
from agents.analytics_agent import get_pending_analytics_videos


def _get_youtube_analytics_service(config: dict):
    """Build a YouTube Analytics API service using existing OAuth credentials."""
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_file = config["youtube"]["token_file"]
    creds = Credentials.from_authorized_user_file(token_file)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("youtubeAnalytics", "v2", credentials=creds)


def _get_channel_id(config: dict) -> str:
    """Get the authenticated user's YouTube channel ID."""
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    token_file = config["youtube"]["token_file"]
    creds = Credentials.from_authorized_user_file(token_file)
    youtube = build("youtube", "v3", credentials=creds)

    response = youtube.channels().list(part="id", mine=True).execute()
    if response.get("items"):
        return response["items"][0]["id"]
    raise ValueError("Could not determine channel ID from authenticated credentials")


def fetch_detailed_analytics(config: dict, video_id: str, days_after_upload: int = 7) -> dict:
    """Fetch detailed analytics for a video using YouTube Analytics API.

    Returns impressions, CTR, avg view duration, avg view percentage,
    views, likes, subscribers gained.
    """
    analytics = _get_youtube_analytics_service(config)

    # Query date range: from upload date to N days after
    conn = get_connection()
    row = conn.execute(
        "SELECT upload_date FROM videos WHERE video_id = ?", (video_id,)
    ).fetchone()
    conn.close()

    if not row:
        return {}

    upload_date = datetime.fromisoformat(row["upload_date"])
    start_date = upload_date.strftime("%Y-%m-%d")
    end_date = (upload_date + timedelta(days=days_after_upload)).strftime("%Y-%m-%d")

    try:
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,likes,subscribersGained,averageViewDuration,annotationClickThroughRate",
            dimensions="video",
            filters=f"video=={video_id}",
        ).execute()
    except Exception:
        # Fallback: try with simpler metrics if some aren't available
        try:
            response = analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,likes,subscribersGained,averageViewDuration",
                dimensions="video",
                filters=f"video=={video_id}",
            ).execute()
        except Exception as e:
            print(f"  Warning: YouTube Analytics API failed for {video_id}: {e}")
            return {}

    if not response.get("rows"):
        return {}

    row_data = response["rows"][0]
    headers = [col["name"] for col in response.get("columnHeaders", [])]

    metrics = {}
    for i, header in enumerate(headers):
        if header == "video":
            continue
        val = row_data[i] if i < len(row_data) else 0
        metrics[header] = val

    # Map to our schema
    return {
        "views": int(metrics.get("views", 0)),
        "likes": int(metrics.get("likes", 0)),
        "subscribers_gained": int(metrics.get("subscribersGained", 0)),
        "avg_watch_time": float(metrics.get("averageViewDuration", 0)),
        "ctr": float(metrics.get("annotationClickThroughRate", 0)),
        "impressions": 0,  # Not always available via Analytics API
    }


def run_analytics_sweep(config: dict) -> list:
    """Fetch analytics for all videos uploaded >48h ago that lack recent metrics.

    Returns list of updated video_ids.
    """
    pending = get_pending_analytics_videos(config)
    if not pending:
        print("  No videos pending analytics fetch.")
        return []

    updated = []
    use_detailed = config.get("analytics", {}).get("detailed_metrics", False)

    for video in pending:
        video_id = video["video_id"]
        print(f"  Fetching analytics for: {video.get('title', video_id)}")

        if use_detailed:
            metrics = fetch_detailed_analytics(config, video_id)
        else:
            from agents.analytics_agent import fetch_youtube_analytics
            metrics = fetch_youtube_analytics(config, video_id)

        if metrics:
            insert_metrics(video_id, video.get("platform", "youtube"), metrics)
            updated.append(video_id)
            print(f"    Stored: {metrics.get('views', 0)} views, CTR: {metrics.get('ctr', 0):.4f}")

    # Update topic scores with new data
    from agents.analytics_agent import update_topic_scores
    update_topic_scores(config)

    print(f"  Analytics sweep complete: {len(updated)}/{len(pending)} videos updated.")
    return updated


def compute_category_weights(config: dict) -> dict:
    """Compute probability weights per category based on historical performance.

    Categories that outperform the channel average get boosted proportionally.
    Returns dict like: {"science": 0.35, "animals": 0.25, "space": 0.20}
    """
    min_videos = config.get("analytics", {}).get("category_weight_min_videos", 5)

    conn = get_connection()

    # Get per-category averages
    categories = conn.execute(
        """SELECT category, AVG(last_score) as avg_score, SUM(times_used) as total_videos
           FROM topic_scores
           GROUP BY category
           HAVING total_videos >= ?
           ORDER BY avg_score DESC""",
        (min_videos,)
    ).fetchall()

    conn.close()

    if not categories:
        print("  Not enough data for category weights (need more videos per category).")
        return {}

    # Compute weights proportional to performance score
    total_score = sum(max(row["avg_score"], 0.1) for row in categories)
    if total_score <= 0:
        return {}

    weights = {}
    now = datetime.now().isoformat()

    for row in categories:
        category = row["category"]
        weight = max(row["avg_score"], 0.1) / total_score
        weights[category] = round(weight, 3)

        upsert_category_weight(
            category=category,
            weight=weight,
            total_videos=row["total_videos"],
            avg_ctr=0.0,  # Will be populated as more data comes in
            avg_views=row["avg_score"],
        )

    print("  Category weights computed:")
    for cat, w in sorted(weights.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {w*100:.1f}%")

    return weights
