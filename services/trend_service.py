"""
Trend Intelligence Engine — discovers trending kids educational topics.
Sources: YouTube Data API trending, YouTube Autocomplete, competitor channel analysis.
"""

import json
import os
import requests
from datetime import datetime, timedelta

from agents.db import (
    get_connection, insert_trend_topic, get_unused_trend_topics,
    clear_old_trend_topics, upsert_competitor_channel, get_competitor_channels,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TREND_TOPICS_FILE = os.path.join(DATA_DIR, "trend_topics.json")


def _get_youtube_service(config: dict):
    """Build a YouTube Data API v3 service."""
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    token_file = config["youtube"]["token_file"]
    creds = Credentials.from_authorized_user_file(token_file)
    return build("youtube", "v3", credentials=creds)


def scrape_youtube_trending(config: dict, niche_keywords: list = None) -> list:
    """Search YouTube for trending kids educational videos from the last 7 days.

    Returns list of {"topic": str, "channel": str, "views": int, "video_id": str}
    """
    youtube = _get_youtube_service(config)

    if not niche_keywords:
        niche_keywords = config.get("trends", {}).get("niche_keywords", [
            "kids fun facts", "kids science", "children educational",
            "kids animals facts", "bachche ke liye facts",
        ])

    published_after = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
    all_results = []
    seen_ids = set()

    for keyword in niche_keywords:
        try:
            response = youtube.search().list(
                part="snippet",
                q=keyword,
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                maxResults=10,
                relevanceLanguage="en",
                videoCategoryId="27",  # Education
            ).execute()

            video_ids = [item["id"]["videoId"] for item in response.get("items", [])]
            if not video_ids:
                continue

            # Get view counts
            stats_response = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(video_ids),
            ).execute()

            for item in stats_response.get("items", []):
                vid = item["id"]
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)

                views = int(item["statistics"].get("viewCount", 0))
                title = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]

                all_results.append({
                    "topic": title,
                    "channel": channel,
                    "views": views,
                    "video_id": vid,
                    "source": "youtube_trending",
                    "keyword": keyword,
                })

        except Exception as e:
            print(f"  Warning: YouTube search failed for '{keyword}': {e}")
            continue

    # Sort by views
    all_results.sort(key=lambda x: x["views"], reverse=True)
    return all_results[:50]


def scrape_youtube_autocomplete(query_prefix: str) -> list:
    """Hit YouTube's public autocomplete endpoint for topic suggestions.

    No API key needed — this is a public endpoint.
    Returns list of autocomplete suggestion strings.
    """
    url = "https://suggestqueries-clients6.youtube.com/complete/search"
    params = {
        "client": "youtube",
        "hl": "en",
        "gl": "IN",
        "q": query_prefix,
        "ds": "yt",
    }

    try:
        response = requests.get(url, params=params, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        response.raise_for_status()

        # Response is JSONP, extract the JSON array
        text = response.text
        # Format: window.google.ac.h([...])
        start = text.index("[")
        data = json.loads(text[start:text.rindex("]") + 1])

        suggestions = []
        if len(data) > 1 and isinstance(data[1], list):
            for item in data[1]:
                if isinstance(item, list) and len(item) > 0:
                    suggestions.append(item[0])

        return suggestions

    except Exception as e:
        print(f"  Warning: YouTube autocomplete failed for '{query_prefix}': {e}")
        return []


def get_autocomplete_topics(config: dict) -> list:
    """Get autocomplete suggestions for all configured niche keywords.

    Returns list of {"topic": str, "source": "autocomplete"}
    """
    keywords = config.get("trends", {}).get("niche_keywords", [
        "kids fun facts about", "kids science", "why do",
        "how does", "amazing facts for kids",
    ])

    all_suggestions = []
    seen = set()

    for keyword in keywords:
        suggestions = scrape_youtube_autocomplete(keyword)
        for s in suggestions:
            s_lower = s.lower().strip()
            if s_lower not in seen and len(s) > 10:
                seen.add(s_lower)
                all_suggestions.append({
                    "topic": s,
                    "source": "autocomplete",
                    "keyword": keyword,
                })

    return all_suggestions


def analyze_competitor_channels(config: dict) -> list:
    """Analyze competitor channels and find outperforming topics.

    Returns list of {"topic": str, "channel": str, "views": int, "outperformance_ratio": float}
    """
    channel_ids = config.get("trends", {}).get("competitor_channels", [])
    if not channel_ids:
        return []

    youtube = _get_youtube_service(config)
    results = []

    for channel_id in channel_ids:
        try:
            # Get channel info
            ch_response = youtube.channels().list(
                part="snippet,statistics",
                id=channel_id,
            ).execute()

            if not ch_response.get("items"):
                continue

            ch_item = ch_response["items"][0]
            channel_name = ch_item["snippet"]["title"]
            total_videos = int(ch_item["statistics"].get("videoCount", 1))
            total_views = int(ch_item["statistics"].get("viewCount", 0))
            avg_views = total_views / max(total_videos, 1)

            upsert_competitor_channel(channel_id, channel_name, avg_views)

            # Get recent videos
            search_response = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                type="video",
                order="date",
                maxResults=20,
            ).execute()

            video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
            if not video_ids:
                continue

            stats_response = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(video_ids),
            ).execute()

            for item in stats_response.get("items", []):
                views = int(item["statistics"].get("viewCount", 0))
                ratio = views / max(avg_views, 1)

                if ratio >= 2.0:  # Only topics that outperform 2x+
                    results.append({
                        "topic": item["snippet"]["title"],
                        "channel": channel_name,
                        "views": views,
                        "outperformance_ratio": round(ratio, 2),
                        "source": "competitor",
                        "video_id": item["id"],
                    })

        except Exception as e:
            print(f"  Warning: Competitor analysis failed for {channel_id}: {e}")
            continue

    results.sort(key=lambda x: x["outperformance_ratio"], reverse=True)
    return results


def compute_trend_scores(trending_data: list, autocomplete_data: list,
                         competitor_data: list) -> list:
    """Combine all trend signals into scored topics.

    Score = trending_weight * 0.4 + autocomplete_presence * 0.3 + competitor_outperformance * 0.3
    Returns sorted list of {"topic": str, "category": str, "trend_score": float, "sources": list}
    """
    from openai import OpenAI
    import yaml

    # Collect all raw topics
    all_topics = []
    for t in trending_data[:30]:
        all_topics.append({"raw": t["topic"], "source": "trending", "score_signal": min(t["views"] / 100000, 1.0)})
    for t in autocomplete_data[:30]:
        all_topics.append({"raw": t["topic"], "source": "autocomplete", "score_signal": 0.5})
    for t in competitor_data[:20]:
        all_topics.append({"raw": t["topic"], "source": "competitor", "score_signal": min(t["outperformance_ratio"] / 5.0, 1.0)})

    if not all_topics:
        return []

    # Use GPT to clean and categorize the raw topics into kid-friendly format
    config_path = os.path.join(os.path.dirname(DATA_DIR), "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    client = OpenAI(api_key=config["openai"]["api_key"])

    raw_list = [t["raw"] for t in all_topics]
    prompt = f"""I have these raw YouTube video titles/suggestions. Convert them into clean,
kid-friendly topic ideas for a children's educational YouTube channel.

Raw topics:
{json.dumps(raw_list[:40], indent=2)}

For each topic, provide:
1. A clean, concise topic title suitable for kids aged 3-8
2. A category (one of: animals, science, space, nature, history, food, body, ocean, dinosaurs, geography, weather, insects)

Remove duplicates and irrelevant topics. Keep only educational/fun fact topics.
Return a JSON array:
[{{"topic": "...", "category": "..."}}]

Only return JSON, nothing else."""

    try:
        response = client.chat.completions.create(
            model=config["openai"]["model"],
            messages=[
                {"role": "system", "content": "You clean and categorize YouTube video topics for kids. Respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=2000,
        )
        cleaned = json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        print(f"  Warning: GPT topic cleaning failed: {e}")
        cleaned = [{"topic": t["raw"], "category": "general"} for t in all_topics[:20]]

    # Assign trend scores
    scored_topics = []
    source_map = {}
    for t in all_topics:
        key = t["raw"].lower().strip()
        if key not in source_map:
            source_map[key] = {"sources": [], "max_signal": 0}
        source_map[key]["sources"].append(t["source"])
        source_map[key]["max_signal"] = max(source_map[key]["max_signal"], t["score_signal"])

    for item in cleaned:
        topic = item["topic"]
        category = item.get("category", "general")

        # Find best matching source signal
        best_signal = 0.5
        sources = ["cleaned"]
        topic_lower = topic.lower()
        for key, data in source_map.items():
            if any(word in key for word in topic_lower.split()[:3]):
                best_signal = max(best_signal, data["max_signal"])
                sources = data["sources"]
                break

        scored_topics.append({
            "topic": topic,
            "category": category,
            "trend_score": round(best_signal, 3),
            "sources": list(set(sources)),
        })

    scored_topics.sort(key=lambda x: x["trend_score"], reverse=True)
    return scored_topics


def save_trend_topics(trend_topics: list):
    """Save trend topics to JSON file and database."""
    # Save to JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TREND_TOPICS_FILE, "w") as f:
        json.dump(trend_topics, f, indent=2)
    print(f"  Saved {len(trend_topics)} trend topics to {TREND_TOPICS_FILE}")

    # Save to DB (clear old ones first)
    clear_old_trend_topics(days_old=7)
    for t in trend_topics:
        insert_trend_topic(
            topic=t["topic"],
            category=t.get("category", "general"),
            trend_score=t.get("trend_score", 0.0),
            source=",".join(t.get("sources", ["unknown"])),
        )


def get_trend_topics(config: dict, limit: int = 20) -> list:
    """Get cached trend topics, or recompute if stale.

    Checks if trend_topics.json exists and is fresh (< refresh_interval_hours).
    """
    refresh_hours = config.get("trends", {}).get("refresh_interval_hours", 24)

    # Check if cached file is fresh
    if os.path.exists(TREND_TOPICS_FILE):
        mtime = datetime.fromtimestamp(os.path.getmtime(TREND_TOPICS_FILE))
        if datetime.now() - mtime < timedelta(hours=refresh_hours):
            with open(TREND_TOPICS_FILE, "r") as f:
                topics = json.load(f)
            return topics[:limit]

    # Also check DB for unused topics
    db_topics = get_unused_trend_topics(limit)
    if db_topics:
        return db_topics

    return []


def refresh_trends(config: dict) -> list:
    """Full trend refresh: scrape all sources, score, and save.

    This is the main entry point called by CLI --refresh-trends.
    """
    print("\n[Trend Intelligence] Refreshing trend data...")

    # 1. YouTube trending search
    print("  Scraping YouTube trending videos...")
    trending = scrape_youtube_trending(config)
    print(f"    Found {len(trending)} trending videos")

    # 2. YouTube autocomplete
    print("  Fetching YouTube autocomplete suggestions...")
    autocomplete = get_autocomplete_topics(config)
    print(f"    Found {len(autocomplete)} autocomplete suggestions")

    # 3. Competitor analysis
    print("  Analyzing competitor channels...")
    competitor = analyze_competitor_channels(config)
    print(f"    Found {len(competitor)} outperforming competitor topics")

    # 4. Compute scores
    print("  Computing trend scores...")
    scored = compute_trend_scores(trending, autocomplete, competitor)
    print(f"    Scored {len(scored)} topics")

    # 5. Save
    save_trend_topics(scored)

    print(f"\n  Trend refresh complete! {len(scored)} topics available.")
    return scored
