"""
Competitor Agent — Weekly intel on what's working in the Hinglish tech niche.

Scans seed competitor channels via YouTube Data API v3, ranks their recent
videos by view-to-subscriber ratio, and extracts structural patterns.

Runs: Weekly (Sunday 06:00 IST) via --strategy-loop.
Seed channels configured in config/competitors.yaml.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, median

import yaml

from agents.db import insert_competitor_video, upsert_competitor_channel
from agents.rate_limiter import get_limiter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPETITORS_PATH = os.path.join(BASE_DIR, "config", "competitors.yaml")


@dataclass
class CompetitorPattern:
    """Extracted pattern from top-performing competitor videos."""
    title_structures: list[str] = field(default_factory=list)
    avg_duration_seconds: int = 0
    best_upload_day: str = ""
    best_upload_hour: int = 0
    common_topics: list[str] = field(default_factory=list)
    top_videos: list[dict] = field(default_factory=list)


def _load_seed_channels() -> list[dict]:
    """Load seed competitor channels from config/competitors.yaml."""
    if not os.path.exists(COMPETITORS_PATH):
        logger.warning("competitors.yaml not found, returning empty list")
        return []
    with open(COMPETITORS_PATH) as f:
        data = yaml.safe_load(f)
    channels = data.get("seed_channels", [])
    return [c for c in channels if c.get("channel_id")]


def _get_youtube_service(config: dict):
    """Build YouTube Data API v3 service."""
    from googleapiclient.discovery import build
    api_key = config.get("youtube", {}).get("api_key", "")
    if not api_key:
        api_key = config.get("openai", {}).get("api_key", "")  # fallback
    if not api_key:
        raise ValueError("No YouTube Data API key found in config")
    return build("youtube", "v3", developerKey=api_key)


def _get_channel_stats(youtube, channel_id: str) -> dict:
    """Get subscriber count for a channel."""
    limiter = get_limiter("youtube")
    limiter.acquire()
    resp = youtube.channels().list(
        part="statistics", id=channel_id
    ).execute()
    items = resp.get("items", [])
    if not items:
        return {"subscribers": 0}
    stats = items[0].get("statistics", {})
    return {"subscribers": int(stats.get("subscriberCount", 0))}


def _search_channel_videos(youtube, channel_id: str, days: int = 30) -> list[dict]:
    """Search for recent videos from a channel."""
    limiter = get_limiter("youtube")
    after = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    limiter.acquire()
    search_resp = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        publishedAfter=after,
        type="video",
        order="date",
        maxResults=50,
    ).execute()

    video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])
                 if item.get("id", {}).get("videoId")]

    if not video_ids:
        return []

    # Fetch video details in batches of 50
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        limiter.acquire()
        details_resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()
        videos.extend(details_resp.get("items", []))

    return videos


def _parse_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _extract_patterns(top_videos: list[dict]) -> CompetitorPattern:
    """Extract structural patterns from top-performing videos."""
    pattern = CompetitorPattern()

    if not top_videos:
        return pattern

    pattern.top_videos = top_videos[:10]

    # Title structure analysis
    title_formats = []
    for v in top_videos:
        title = v.get("title", "")
        if "?" in title:
            title_formats.append("question")
        elif title.lower().startswith(("how", "kaise", "why", "kyu")):
            title_formats.append("how/why")
        elif any(w in title.lower() for w in ["explained", "samjho", "jaano"]):
            title_formats.append("explained")
        else:
            title_formats.append("statement")
    pattern.title_structures = title_formats

    # Duration
    durations = [v.get("duration_seconds", 0) for v in top_videos if v.get("duration_seconds", 0) > 0]
    if durations:
        pattern.avg_duration_seconds = int(mean(durations))

    # Upload timing
    days = []
    hours = []
    for v in top_videos:
        pub = v.get("published_at", "")
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                days.append(dt.strftime("%A"))
                hours.append(dt.hour)
            except ValueError:
                pass
    if days:
        pattern.best_upload_day = max(set(days), key=days.count)
    if hours:
        pattern.best_upload_hour = max(set(hours), key=hours.count)

    return pattern


def weekly_intel(config: dict) -> list[dict]:
    """Run weekly competitor analysis and return top patterns.

    Args:
        config: Pipeline config dict (needs YouTube API key).

    Returns:
        list of top 10 video dicts sorted by view_to_sub_ratio.
    """
    seed_channels = _load_seed_channels()
    if not seed_channels:
        print("  Competitor: no seed channels configured in config/competitors.yaml")
        return []

    # Load analysis settings
    with open(COMPETITORS_PATH) as f:
        comp_config = yaml.safe_load(f)
    analysis = comp_config.get("analysis", {})
    lookback_days = analysis.get("lookback_days", 30)
    top_n = analysis.get("top_n", 10)

    try:
        youtube = _get_youtube_service(config)
    except Exception as e:
        print(f"  Competitor: failed to init YouTube API: {e}")
        return []

    all_videos = []

    for channel in seed_channels:
        ch_id = channel["channel_id"]
        ch_name = channel.get("channel_name", ch_id)
        print(f"  Competitor: scanning {ch_name}...")

        try:
            # Get subscriber count
            ch_stats = _get_channel_stats(youtube, ch_id)
            subs = ch_stats.get("subscribers", 0)
            upsert_competitor_channel(ch_id, ch_name, avg_views=0)

            # Get recent videos
            videos = _search_channel_videos(youtube, ch_id, days=lookback_days)
            print(f"    Found {len(videos)} videos in last {lookback_days} days")

            for vid in videos:
                stats = vid.get("statistics", {})
                snippet = vid.get("snippet", {})
                views = int(stats.get("viewCount", 0))
                duration = _parse_duration(vid.get("contentDetails", {}).get("duration", ""))
                ratio = views / subs if subs > 0 else 0

                video_data = {
                    "channel_id": ch_id,
                    "channel_name": ch_name,
                    "video_id": vid["id"],
                    "title": snippet.get("title", ""),
                    "view_count": views,
                    "view_to_sub_ratio": round(ratio, 4),
                    "duration_seconds": duration,
                    "published_at": snippet.get("publishedAt", ""),
                }

                # Write to DB
                insert_competitor_video(**video_data)
                all_videos.append(video_data)

        except Exception as e:
            print(f"    Error scanning {ch_name}: {e}")
            logger.exception("Competitor scan failed for %s", ch_name)

    # Sort by view-to-subscriber ratio and take top N
    all_videos.sort(key=lambda v: v["view_to_sub_ratio"], reverse=True)
    top_videos = all_videos[:top_n]

    # Extract patterns
    patterns = _extract_patterns(top_videos)
    print(f"\n  Competitor: top {len(top_videos)} videos analyzed")
    if patterns.avg_duration_seconds:
        print(f"    Avg duration: {patterns.avg_duration_seconds // 60}m {patterns.avg_duration_seconds % 60}s")
    if patterns.best_upload_day:
        print(f"    Best upload day: {patterns.best_upload_day}")

    return top_videos
