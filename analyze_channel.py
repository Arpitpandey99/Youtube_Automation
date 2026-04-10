#!/usr/bin/env python3
"""
YouTube Channel Analysis Script
Fetches comprehensive analytics via YouTube Data API + Analytics API,
cross-references with local pipeline database, and generates a detailed
markdown report with market-research-backed recommendations.
"""

import os
import sys
import json
import re
import sqlite3
import shutil
from datetime import datetime, timedelta
from collections import defaultdict
from statistics import mean, median, stdev

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CLIENT_SECRETS = os.path.join(BASE_DIR, "client_secrets.json")
EC2_DB_PATH = os.path.join(BASE_DIR, "data", "ec2_pipeline.db")
EC2_TOPICS_PATH = os.path.join(BASE_DIR, "data", "ec2_topics_history.json")
REPORT_PATH = os.path.join(BASE_DIR, "data", "channel_analysis_report.md")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def authenticate():
    """Authenticate with YouTube API. Backs up existing token if scopes differ."""
    creds = None
    token_backup = TOKEN_FILE + ".bak"

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            # Back up existing token before re-auth
            if os.path.exists(TOKEN_FILE):
                shutil.copy2(TOKEN_FILE, token_backup)
                print(f"  Backed up existing token to {token_backup}")

            if not os.path.exists(CLIENT_SECRETS):
                print(f"ERROR: Missing {CLIENT_SECRETS}")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            print("  New token saved.")

    youtube = build("youtube", "v3", credentials=creds)
    youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
    return youtube, youtube_analytics


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------
def fetch_channel_stats(youtube):
    """Fetch channel-level statistics."""
    resp = youtube.channels().list(
        part="statistics,snippet,contentDetails",
        mine=True,
    ).execute()

    if not resp.get("items"):
        print("ERROR: No channel found for this account.")
        sys.exit(1)

    ch = resp["items"][0]
    return {
        "channel_id": ch["id"],
        "title": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", ""),
        "created_at": ch["snippet"]["publishedAt"],
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "total_views": int(ch["statistics"].get("viewCount", 0)),
        "total_videos": int(ch["statistics"].get("videoCount", 0)),
    }


def fetch_all_video_ids(youtube, uploads_playlist):
    """Paginate through uploads playlist to get all video IDs."""
    video_ids = []
    next_page = None

    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page,
        ).execute()

        for item in resp.get("items", []):
            video_ids.append({
                "video_id": item["contentDetails"]["videoId"],
                "published_at": item["snippet"]["publishedAt"],
            })

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    print(f"  Found {len(video_ids)} videos in uploads playlist.")
    return video_ids


def fetch_video_details_batch(youtube, video_ids):
    """Batch fetch video details (50 per request)."""
    all_details = []

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        ids_str = ",".join(v["video_id"] for v in batch)

        resp = youtube.videos().list(
            part="statistics,snippet,contentDetails",
            id=ids_str,
        ).execute()

        for item in resp.get("items", []):
            stats = item["statistics"]
            snippet = item["snippet"]
            content = item["contentDetails"]

            # Parse duration (ISO 8601 → seconds)
            duration_str = content.get("duration", "PT0S")
            duration_secs = _parse_duration(duration_str)

            all_details.append({
                "video_id": item["id"],
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "tags": snippet.get("tags", []),
                "published_at": snippet["publishedAt"],
                "category_id": snippet.get("categoryId", ""),
                "duration_seconds": duration_secs,
                "definition": content.get("definition", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "is_short": duration_secs <= 62 or "#Shorts" in snippet["title"] or "#shorts" in snippet["title"],
            })

    print(f"  Fetched details for {len(all_details)} videos.")
    return all_details


def fetch_analytics_data(youtube_analytics, channel_id, start_date, end_date):
    """Fetch YouTube Analytics API data for deep metrics."""
    analytics = {}

    # 1. Per-video metrics
    try:
        resp = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares",
            dimensions="video",
            sort="-views",
            maxResults=200,
        ).execute()
        analytics["per_video"] = {}
        for row in resp.get("rows", []):
            analytics["per_video"][row[0]] = {
                "views": row[1],
                "est_minutes_watched": row[2],
                "avg_view_duration": row[3],
                "avg_view_percentage": row[4],
                "likes": row[5],
                "shares": row[6],
            }
    except Exception as e:
        print(f"  Warning: Per-video analytics failed: {e}")
        analytics["per_video"] = {}

    # 2. Traffic sources
    try:
        resp = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            sort="-views",
        ).execute()
        analytics["traffic_sources"] = {}
        for row in resp.get("rows", []):
            analytics["traffic_sources"][row[0]] = {
                "views": row[1],
                "est_minutes_watched": row[2],
            }
    except Exception as e:
        print(f"  Warning: Traffic sources analytics failed: {e}")
        analytics["traffic_sources"] = {}

    # 3. Device types
    try:
        resp = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="deviceType",
            sort="-views",
        ).execute()
        analytics["devices"] = {}
        for row in resp.get("rows", []):
            analytics["devices"][row[0]] = {
                "views": row[1],
                "est_minutes_watched": row[2],
            }
    except Exception as e:
        print(f"  Warning: Device analytics failed: {e}")
        analytics["devices"] = {}

    # 4. Geography
    try:
        resp = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            sort="-views",
            maxResults=20,
        ).execute()
        analytics["geography"] = {}
        for row in resp.get("rows", []):
            analytics["geography"][row[0]] = {
                "views": row[1],
                "est_minutes_watched": row[2],
            }
    except Exception as e:
        print(f"  Warning: Geography analytics failed: {e}")
        analytics["geography"] = {}

    # 5. Daily views trend
    try:
        resp = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost",
            dimensions="day",
            sort="day",
        ).execute()
        analytics["daily"] = []
        for row in resp.get("rows", []):
            analytics["daily"].append({
                "date": row[0],
                "views": row[1],
                "est_minutes_watched": row[2],
                "subs_gained": row[3],
                "subs_lost": row[4],
            })
    except Exception as e:
        print(f"  Warning: Daily trend analytics failed: {e}")
        analytics["daily"] = []

    return analytics


def enrich_with_local_data(videos, db_path):
    """Cross-reference videos with local pipeline database."""
    if not os.path.exists(db_path):
        print(f"  Warning: {db_path} not found, skipping enrichment.")
        return videos

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    db_videos = {}
    for row in conn.execute("SELECT video_id, topic, category FROM videos WHERE video_id IS NOT NULL"):
        db_videos[row["video_id"]] = {"topic": row["topic"], "category": row["category"]}
    conn.close()

    enriched = 0
    for v in videos:
        if v["video_id"] in db_videos:
            v["topic"] = db_videos[v["video_id"]]["topic"]
            v["category"] = db_videos[v["video_id"]]["category"]
            enriched += 1
        else:
            # Try to infer category from title
            v["topic"] = v["title"]
            v["category"] = _infer_category(v["title"])

    print(f"  Enriched {enriched}/{len(videos)} videos from local DB.")
    return videos


# ---------------------------------------------------------------------------
# Analysis Functions
# ---------------------------------------------------------------------------
def analyze_topic_performance(videos):
    """Group by category, compute avg views/likes, best/worst performers."""
    by_category = defaultdict(list)
    for v in videos:
        cat = v.get("category", "unknown")
        by_category[cat].append(v)

    results = []
    for cat, vids in sorted(by_category.items()):
        views = [v["views"] for v in vids]
        likes = [v["likes"] for v in vids]
        best = max(vids, key=lambda x: x["views"])
        worst = min(vids, key=lambda x: x["views"])
        results.append({
            "category": cat,
            "count": len(vids),
            "avg_views": mean(views),
            "avg_likes": mean(likes),
            "total_views": sum(views),
            "best_video": {"title": best["title"], "views": best["views"]},
            "worst_video": {"title": worst["title"], "views": worst["views"]},
        })

    results.sort(key=lambda x: x["avg_views"], reverse=True)
    return results


def analyze_content_types(videos):
    """Compare regular videos vs shorts."""
    types = {"shorts": [], "regular": []}
    for v in videos:
        if v["is_short"]:
            types["shorts"].append(v)
        else:
            types["regular"].append(v)

    results = {}
    for content_type, vids in types.items():
        if not vids:
            results[content_type] = {"count": 0, "avg_views": 0, "avg_likes": 0}
            continue

        views = [v["views"] for v in vids]
        likes = [v["likes"] for v in vids]

        # View velocity = views / days since publish
        velocities = []
        for v in vids:
            days = (datetime.now() - _parse_iso_date(v["published_at"])).days
            if days > 0:
                velocities.append(v["views"] / days)

        results[content_type] = {
            "count": len(vids),
            "avg_views": mean(views),
            "median_views": median(views),
            "avg_likes": mean(likes),
            "total_views": sum(views),
            "avg_velocity": mean(velocities) if velocities else 0,
        }

    return results


def analyze_publishing_patterns(videos):
    """Analyze day-of-week, time-of-day performance."""
    by_day = defaultdict(list)
    by_hour = defaultdict(list)
    weekly_uploads = defaultdict(int)

    for v in videos:
        dt = _parse_iso_date(v["published_at"])
        day_name = dt.strftime("%A")
        hour = dt.hour
        week_key = dt.strftime("%Y-W%W")

        by_day[day_name].append(v["views"])
        by_hour[hour].append(v["views"])
        weekly_uploads[week_key] += 1

    day_perf = {day: {"avg_views": mean(views), "count": len(views)}
                for day, views in by_day.items()}
    hour_perf = {h: {"avg_views": mean(views), "count": len(views)}
                 for h, views in by_hour.items()}

    # Upload consistency
    weeks = list(weekly_uploads.values())
    consistency = {
        "total_weeks": len(weeks),
        "avg_uploads_per_week": mean(weeks) if weeks else 0,
        "min_uploads_week": min(weeks) if weeks else 0,
        "max_uploads_week": max(weeks) if weeks else 0,
    }

    return {"by_day": day_perf, "by_hour": hour_perf, "consistency": consistency}


def analyze_metadata_quality(videos):
    """Analyze title length, emoji usage, tag patterns."""
    results = {
        "title_length_vs_views": [],
        "emoji_vs_no_emoji": {"with_emoji": [], "without_emoji": []},
        "tag_count_vs_views": [],
        "hinglish_vs_english": {"hinglish": [], "english": []},
    }

    for v in videos:
        title = v["title"]
        title_len = len(title)
        has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF]', title))
        tag_count = len(v.get("tags", []))
        is_hinglish = bool(re.search(r'[A-Za-z].*(?:ke|ki|ka|mein|hai|aur|se|ko)', title, re.IGNORECASE))

        results["title_length_vs_views"].append((title_len, v["views"]))

        if has_emoji:
            results["emoji_vs_no_emoji"]["with_emoji"].append(v["views"])
        else:
            results["emoji_vs_no_emoji"]["without_emoji"].append(v["views"])

        results["tag_count_vs_views"].append((tag_count, v["views"]))

        if is_hinglish:
            results["hinglish_vs_english"]["hinglish"].append(v["views"])
        else:
            results["hinglish_vs_english"]["english"].append(v["views"])

    # Compute summaries
    with_emoji = results["emoji_vs_no_emoji"]["with_emoji"]
    without_emoji = results["emoji_vs_no_emoji"]["without_emoji"]
    results["emoji_impact"] = {
        "with_emoji_avg": mean(with_emoji) if with_emoji else 0,
        "without_emoji_avg": mean(without_emoji) if without_emoji else 0,
    }

    hinglish = results["hinglish_vs_english"]["hinglish"]
    english = results["hinglish_vs_english"]["english"]
    results["hinglish_impact"] = {
        "hinglish_avg": mean(hinglish) if hinglish else 0,
        "english_avg": mean(english) if english else 0,
    }

    return results


def analyze_growth_trajectory(videos):
    """Sort by publish date, show views trend, detect growth/stagnation."""
    sorted_vids = sorted(videos, key=lambda x: x["published_at"])

    # Group by week
    weekly = defaultdict(list)
    for v in sorted_vids:
        dt = _parse_iso_date(v["published_at"])
        week = dt.strftime("%Y-W%W")
        weekly[week].append(v["views"])

    weekly_avg = [(week, mean(views)) for week, views in sorted(weekly.items())]

    # Trend: compare first half vs second half
    if len(weekly_avg) >= 4:
        mid = len(weekly_avg) // 2
        first_half = mean([v for _, v in weekly_avg[:mid]])
        second_half = mean([v for _, v in weekly_avg[mid:]])
        trend = "growing" if second_half > first_half * 1.1 else (
            "declining" if second_half < first_half * 0.9 else "stagnant"
        )
        trend_pct = ((second_half - first_half) / first_half * 100) if first_half > 0 else 0
    else:
        trend = "insufficient_data"
        trend_pct = 0

    return {
        "weekly_averages": weekly_avg,
        "trend": trend,
        "trend_pct": trend_pct,
        "total_videos": len(sorted_vids),
        "first_upload": sorted_vids[0]["published_at"] if sorted_vids else None,
        "latest_upload": sorted_vids[-1]["published_at"] if sorted_vids else None,
    }


def analyze_traffic_sources(analytics):
    """Break down views by traffic source."""
    sources = analytics.get("traffic_sources", {})
    total = sum(s["views"] for s in sources.values())
    results = []
    for source, data in sorted(sources.items(), key=lambda x: x[1]["views"], reverse=True):
        pct = (data["views"] / total * 100) if total > 0 else 0
        results.append({
            "source": source,
            "views": data["views"],
            "pct": pct,
            "minutes_watched": data["est_minutes_watched"],
        })
    return {"sources": results, "total_views": total}


def analyze_audience_retention(videos, analytics):
    """Analyze watch duration and completion rates."""
    per_video = analytics.get("per_video", {})

    durations = []
    percentages = []
    for v in videos:
        vid_data = per_video.get(v["video_id"], {})
        if vid_data:
            avg_dur = vid_data.get("avg_view_duration", 0)
            avg_pct = vid_data.get("avg_view_percentage", 0)
            durations.append(avg_dur)
            percentages.append(avg_pct)
            v["avg_view_duration"] = avg_dur
            v["avg_view_percentage"] = avg_pct

    return {
        "avg_view_duration": mean(durations) if durations else 0,
        "avg_view_percentage": mean(percentages) if percentages else 0,
        "videos_with_data": len(durations),
    }


def analyze_impressions_ctr(analytics):
    """Analyze impressions and CTR from Analytics API (channel-level only for MFK content)."""
    # Note: For Made-for-Kids content, per-video impression data may be limited
    per_video = analytics.get("per_video", {})
    return {
        "videos_with_data": len(per_video),
        "note": "Impression/CTR data may be limited for Made-for-Kids content due to COPPA restrictions.",
    }


def ai_content_risk_assessment(videos, growth):
    """Assess risk of YouTube AI slop detection based on content patterns."""
    risks = []
    score = 0  # 0-100, higher = more risky

    # 1. Upload frequency
    if growth["total_videos"] > 0 and growth["first_upload"]:
        first = _parse_iso_date(growth["first_upload"])
        days_active = (datetime.now() - first).days or 1
        uploads_per_day = growth["total_videos"] / days_active
        if uploads_per_day >= 2:
            risks.append("CRITICAL: Uploading 2+ videos/day matches mass-production pattern YouTube flags")
            score += 30
        elif uploads_per_day >= 1:
            risks.append("WARNING: Daily uploads may trigger repetitive content detection")
            score += 15

    # 2. Title similarity
    titles = [v["title"] for v in videos]
    if len(titles) >= 5:
        # Check for repeating patterns
        title_words = defaultdict(int)
        for t in titles:
            for word in t.lower().split():
                if len(word) > 3:
                    title_words[word] += 1
        most_common = sorted(title_words.items(), key=lambda x: x[1], reverse=True)[:5]
        repetition_rate = most_common[0][1] / len(titles) if most_common else 0
        if repetition_rate > 0.5:
            risks.append(f"WARNING: High title repetition - '{most_common[0][0]}' appears in {most_common[0][1]}/{len(titles)} titles")
            score += 15

    # 3. Duration uniformity
    durations = [v["duration_seconds"] for v in videos if not v["is_short"]]
    if len(durations) >= 5:
        dur_std = stdev(durations) if len(durations) > 1 else 0
        avg_dur = mean(durations)
        cv = dur_std / avg_dur if avg_dur > 0 else 0
        if cv < 0.15:
            risks.append("WARNING: Very uniform video durations suggest automated production")
            score += 10

    # 4. All content is AI-generated (known from pipeline)
    risks.append("CRITICAL: All images are AI-generated (Flux/DALL-E) with TTS voiceover — matches YouTube's AI slop detection signals")
    score += 25

    # 5. Ken Burns animation = minimal editing
    risks.append("WARNING: Ken Burns zoom/pan on static images = 'minimal editing' signal in YouTube's detection")
    score += 10

    # 6. View trend declining
    if growth["trend"] == "declining":
        risks.append("CRITICAL: Views are declining over time — possible algorithmic suppression already happening")
        score += 10

    return {"risk_score": min(score, 100), "risks": risks}


def analyze_devices(analytics):
    """Break down by device type."""
    devices = analytics.get("devices", {})
    total = sum(d["views"] for d in devices.values())
    results = []
    for device, data in sorted(devices.items(), key=lambda x: x[1]["views"], reverse=True):
        pct = (data["views"] / total * 100) if total > 0 else 0
        results.append({"device": device, "views": data["views"], "pct": pct})
    return results


def analyze_geography(analytics):
    """Break down by country."""
    geo = analytics.get("geography", {})
    total = sum(g["views"] for g in geo.values())
    results = []
    for country, data in sorted(geo.items(), key=lambda x: x[1]["views"], reverse=True):
        pct = (data["views"] / total * 100) if total > 0 else 0
        results.append({"country": country, "views": data["views"], "pct": pct})
    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def generate_report(channel, videos, analytics_data, topic_perf, content_types,
                    publishing, metadata, growth, traffic, retention,
                    impressions, risk, devices, geography):
    """Generate comprehensive markdown analysis report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Sort for top/bottom
    sorted_by_views = sorted(videos, key=lambda x: x["views"], reverse=True)
    all_views = [v["views"] for v in videos]

    report = []
    report.append(f"# YouTube Channel Analysis Report")
    report.append(f"**Channel:** {channel['title']} (@kidlearningadventure)")
    report.append(f"**Analysis Date:** {now}")
    report.append(f"**Total Videos Analyzed:** {len(videos)}")
    report.append("")

    # ── Executive Summary ──
    report.append("## 1. Executive Summary")
    report.append("")

    health_score = _calculate_health_score(channel, videos, growth, risk, retention)
    emoji = "🟢" if health_score >= 70 else ("🟡" if health_score >= 40 else "🔴")
    report.append(f"**Channel Health Score: {health_score}/100** {emoji}")
    report.append("")

    # Top risks
    report.append("### Top Risks")
    critical_risks = [r for r in risk["risks"] if r.startswith("CRITICAL")]
    for r in critical_risks[:3]:
        report.append(f"- {r}")
    report.append("")

    # Top opportunities
    report.append("### Top Opportunities")
    if content_types.get("shorts", {}).get("avg_views", 0) > content_types.get("regular", {}).get("avg_views", 0):
        report.append("- Shorts outperform regular videos — increase shorts ratio")
    if topic_perf:
        best_cat = topic_perf[0]
        report.append(f"- Best category: **{best_cat['category']}** ({best_cat['avg_views']:.0f} avg views) — double down")
    report.append("- Add replay-friendly content (songs, counting loops, alphabet)")
    report.append("")

    # ── Channel Overview ──
    report.append("## 2. Channel Overview")
    report.append("")
    report.append(f"| Metric | Value |")
    report.append(f"|--------|-------|")
    report.append(f"| Subscribers | {channel['subscribers']:,} |")
    report.append(f"| Total Views | {channel['total_views']:,} |")
    report.append(f"| Total Videos | {channel['total_videos']} |")
    report.append(f"| Channel Created | {channel['created_at'][:10]} |")
    report.append(f"| Average Views/Video | {mean(all_views):.0f} |")
    report.append(f"| Median Views/Video | {median(all_views):.0f} |")
    report.append(f"| Like-to-View Ratio | {_safe_ratio(sum(v['likes'] for v in videos), sum(all_views))*100:.1f}% |")
    report.append(f"| Days Active | {(datetime.now() - _parse_iso_date(channel['created_at'])).days} |")
    report.append(f"| Avg Uploads/Week | {publishing['consistency']['avg_uploads_per_week']:.1f} |")
    report.append("")

    # ── Content Performance by Category ──
    report.append("## 3. Content Performance by Category")
    report.append("")
    report.append("| Category | Videos | Avg Views | Avg Likes | Total Views | Best Video |")
    report.append("|----------|--------|-----------|-----------|-------------|------------|")
    for tp in topic_perf:
        best = tp["best_video"]
        report.append(f"| {tp['category']} | {tp['count']} | {tp['avg_views']:.0f} | {tp['avg_likes']:.0f} | {tp['total_views']:,} | {best['title'][:40]}... ({best['views']} views) |")
    report.append("")

    # ── Content Type Comparison ──
    report.append("## 4. Content Type Comparison (Shorts vs Regular)")
    report.append("")
    report.append("| Type | Count | Avg Views | Median Views | Total Views | Avg View Velocity (views/day) |")
    report.append("|------|-------|-----------|--------------|-------------|-------------------------------|")
    for ct_name, ct_data in content_types.items():
        if ct_data["count"] > 0:
            report.append(f"| {ct_name.title()} | {ct_data['count']} | {ct_data['avg_views']:.0f} | {ct_data['median_views']:.0f} | {ct_data['total_views']:,} | {ct_data['avg_velocity']:.1f} |")
    report.append("")

    shorts_avg = content_types.get("shorts", {}).get("avg_views", 0)
    regular_avg = content_types.get("regular", {}).get("avg_views", 0)
    if shorts_avg > 0 and regular_avg > 0:
        ratio = shorts_avg / regular_avg
        report.append(f"**Shorts vs Regular ratio:** Shorts get {ratio:.1f}x {'more' if ratio > 1 else 'fewer'} views on average.")
    report.append("")

    # ── Publishing Patterns ──
    report.append("## 5. Publishing Patterns")
    report.append("")
    report.append("### By Day of Week")
    report.append("| Day | Videos | Avg Views |")
    report.append("|-----|--------|-----------|")
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        if day in publishing["by_day"]:
            d = publishing["by_day"][day]
            report.append(f"| {day} | {d['count']} | {d['avg_views']:.0f} |")
    report.append("")

    report.append("### Upload Consistency")
    c = publishing["consistency"]
    report.append(f"- Total active weeks: {c['total_weeks']}")
    report.append(f"- Avg uploads/week: {c['avg_uploads_per_week']:.1f}")
    report.append(f"- Range: {c['min_uploads_week']}–{c['max_uploads_week']} uploads/week")
    report.append("")

    # ── Traffic Sources ──
    report.append("## 6. Traffic & Discovery Sources")
    report.append("")
    if traffic["sources"]:
        report.append("| Source | Views | % of Total | Minutes Watched |")
        report.append("|--------|-------|-----------|-----------------|")
        for s in traffic["sources"]:
            report.append(f"| {s['source']} | {s['views']:,} | {s['pct']:.1f}% | {s['minutes_watched']:.0f} |")
        report.append("")

        # COPPA impact analysis
        suggested = next((s for s in traffic["sources"] if "SUGGESTED" in s["source"].upper()), None)
        browse = next((s for s in traffic["sources"] if "BROWSE" in s["source"].upper()), None)
        search = next((s for s in traffic["sources"] if "SEARCH" in s["source"].upper() and "EXT" not in s["source"].upper()), None)

        report.append("### COPPA Discovery Impact")
        if suggested:
            report.append(f"- Suggested videos: {suggested['pct']:.1f}% of views — COPPA disables personalized suggestions, so this is lower than non-kids channels (~50-60%)")
        if browse:
            report.append(f"- Browse features: {browse['pct']:.1f}% — homepage recommendations, limited by COPPA")
        if search:
            report.append(f"- YouTube Search: {search['pct']:.1f}% — your primary controllable growth lever under COPPA")
        report.append("")
    else:
        report.append("*Traffic source data not available.*")
        report.append("")

    # ── Audience Retention ──
    report.append("## 7. Audience Retention")
    report.append("")
    if retention["videos_with_data"] > 0:
        report.append(f"- Average view duration: {retention['avg_view_duration']:.0f} seconds")
        report.append(f"- Average view percentage: {retention['avg_view_percentage']:.1f}%")
        report.append(f"- Videos with data: {retention['videos_with_data']}")
        report.append("")
        if retention["avg_view_percentage"] < 30:
            report.append("**WARNING:** Avg view percentage below 30% — viewers are leaving early. This signals content quality/engagement issues to the algorithm.")
        elif retention["avg_view_percentage"] < 50:
            report.append("**NOTE:** Avg view percentage is moderate. Target >50% for kids content (kids tend to watch full videos when engaged).")
        else:
            report.append("**GOOD:** Retention above 50% — content is engaging once discovered.")
    else:
        report.append("*Retention data not available from Analytics API.*")
    report.append("")

    # ── Devices ──
    report.append("## 8. Device Breakdown")
    report.append("")
    if devices:
        report.append("| Device | Views | % |")
        report.append("|--------|-------|---|")
        for d in devices:
            report.append(f"| {d['device']} | {d['views']:,} | {d['pct']:.1f}% |")
        report.append("")
        mobile = next((d for d in devices if "MOBILE" in d["device"].upper()), None)
        tv = next((d for d in devices if "TV" in d["device"].upper() or "GAME" in d["device"].upper()), None)
        if mobile and mobile["pct"] > 60:
            report.append("**Insight:** Majority views from mobile — optimize thumbnails for small screens.")
        if tv and tv["pct"] > 15:
            report.append("**Insight:** Significant TV viewership — kids watching on family devices. Good sign for longer content.")
    else:
        report.append("*Device data not available.*")
    report.append("")

    # ── Geography ──
    report.append("## 9. Geographic Distribution")
    report.append("")
    if geography:
        report.append("| Country | Views | % |")
        report.append("|---------|-------|---|")
        for g in geography[:10]:
            report.append(f"| {g['country']} | {g['views']:,} | {g['pct']:.1f}% |")
        report.append("")
        india = next((g for g in geography if g["country"] == "IN"), None)
        if india and india["pct"] < 40:
            report.append("**Insight:** India is less than 40% of views — Hinglish content should target Indian audience more strongly. Consider SEO in Hindi keywords.")
        elif india and india["pct"] > 60:
            report.append("**Insight:** Heavily India-focused. Consider expanding to other South Asian markets (Bangladesh, Pakistan, Sri Lanka) or adding pure English content for global reach.")
    else:
        report.append("*Geography data not available.*")
    report.append("")

    # ── Metadata Quality ──
    report.append("## 10. Metadata Quality Analysis")
    report.append("")
    report.append(f"### Emoji Impact")
    ei = metadata["emoji_impact"]
    report.append(f"- With emoji: {ei['with_emoji_avg']:.0f} avg views")
    report.append(f"- Without emoji: {ei['without_emoji_avg']:.0f} avg views")
    if ei["with_emoji_avg"] > 0 and ei["without_emoji_avg"] > 0:
        better = "with" if ei["with_emoji_avg"] > ei["without_emoji_avg"] else "without"
        report.append(f"- **Titles {better} emoji perform better**")
    report.append("")

    report.append(f"### Hinglish vs English Titles")
    hi = metadata["hinglish_impact"]
    report.append(f"- Hinglish titles: {hi['hinglish_avg']:.0f} avg views ({len(metadata['hinglish_vs_english']['hinglish'])} videos)")
    report.append(f"- English titles: {hi['english_avg']:.0f} avg views ({len(metadata['hinglish_vs_english']['english'])} videos)")
    report.append("")

    # ── Top & Bottom Videos ──
    report.append("## 11. Top 10 Videos")
    report.append("")
    report.append("| # | Title | Views | Likes | Duration | Type | Published |")
    report.append("|---|-------|-------|-------|----------|------|-----------|")
    for i, v in enumerate(sorted_by_views[:10], 1):
        vtype = "Short" if v["is_short"] else "Regular"
        dur = _format_duration(v["duration_seconds"])
        report.append(f"| {i} | {v['title'][:50]}{'...' if len(v['title']) > 50 else ''} | {v['views']:,} | {v['likes']} | {dur} | {vtype} | {v['published_at'][:10]} |")
    report.append("")

    report.append("## 12. Bottom 10 Videos")
    report.append("")
    report.append("| # | Title | Views | Likes | Duration | Type | Published |")
    report.append("|---|-------|-------|-------|----------|------|-----------|")
    for i, v in enumerate(sorted_by_views[-10:], 1):
        vtype = "Short" if v["is_short"] else "Regular"
        dur = _format_duration(v["duration_seconds"])
        report.append(f"| {i} | {v['title'][:50]}{'...' if len(v['title']) > 50 else ''} | {v['views']:,} | {v['likes']} | {dur} | {vtype} | {v['published_at'][:10]} |")
    report.append("")

    # ── Growth Trajectory ──
    report.append("## 13. Growth Trajectory")
    report.append("")
    report.append(f"- **Trend:** {growth['trend'].upper()} ({growth['trend_pct']:+.1f}% second half vs first half)")
    report.append(f"- First upload: {growth['first_upload'][:10] if growth['first_upload'] else 'N/A'}")
    report.append(f"- Latest upload: {growth['latest_upload'][:10] if growth['latest_upload'] else 'N/A'}")
    report.append("")

    # Weekly trend chart
    if growth["weekly_averages"]:
        report.append("### Weekly Average Views Trend")
        report.append("```")
        max_val = max(v for _, v in growth["weekly_averages"]) or 1
        for week, avg in growth["weekly_averages"][-16:]:  # last 16 weeks
            bar_len = int(avg / max_val * 40)
            report.append(f"{week} | {'█' * bar_len} {avg:.0f}")
        report.append("```")
    report.append("")

    # ── AI Content Risk Assessment ──
    report.append("## 14. AI Content Risk Assessment")
    report.append("")
    risk_emoji = "🔴" if risk["risk_score"] >= 60 else ("🟡" if risk["risk_score"] >= 30 else "🟢")
    report.append(f"**AI Slop Risk Score: {risk['risk_score']}/100** {risk_emoji}")
    report.append("")
    for r in risk["risks"]:
        report.append(f"- {r}")
    report.append("")

    report.append("""### Why This Matters
YouTube CEO Neal Mohan explicitly called out "AI slop" in kids content in his January 2026 letter.
Since July 2025, YouTube penalizes "inauthentic content": mass-produced, repetitive videos with no
original value. Channels built on AI scripts, slideshows, synthetic voices, or copy-paste formats
are the first to fall — especially when every upload looks, sounds, and moves the same.

YouTube's detection looks for:
- Upload frequency patterns (automated uploads)
- Format similarity across videos
- Synthetic voice detection
- Lack of human presence/commentary
- Minimal editing (same Ken Burns effect every video)

**Your pipeline hits ALL of these signals.**
""")

    # ── Market Analysis ──
    report.append("## 15. Market Analysis & Competitive Intelligence")
    report.append("")
    report.append("""### What Top Kids Channels Do (That This Channel Doesn't)

| Channel | Subs | What They Do | What This Channel Does Instead |
|---------|------|-------------|-------------------------------|
| ChuChu TV | 96M | Custom animated music, 10-15 videos/month, 12 languages | AI images + TTS, 14 videos/week, 1 language |
| Cocomelon | 199M | 3D animation, songs as household routines, replay value | Ken Burns on static images, fact narration |
| Kids Diana Show | 100M+ | Live-action, real kids, family dynamics | No human presence at all |
| Blippi | 21M | Live-action presenter, educational with personality | Synthetic TTS voice, no personality |
| Ryan's World | 37M | Unboxing, experiments, brand empire | Pure narration format |

### Key Insight
**Every successful kids channel has either:**
1. High-quality custom animation with original music, OR
2. Real humans/kids on camera

**No successful kids channel relies on AI-generated images with TTS voiceover.**

### Viral Kids Content Formats (2025-2026)
The channel's format (fact narration over AI images) doesn't match any of the 13 viral kids formats:
1. Sneaky educational content (lessons hidden in songs/entertainment)
2. Toy unboxing and reviews
3. Funny animations/shorts (quirky characters, slapstick)
4. Superhero playtime
5. DIY craft videos
6. Nursery rhymes (catchy melodies + animation)
7. Character-centric series (recurring characters with development)
8. Mindfulness/yoga for kids
9. Storytime adventures (animated fairy tales)
10. STEM experiments (hands-on, kitchen science)
11. Language/culture learning
12. Cooking with kids
13. Animal/wildlife adventures

The closest match is #1 (sneaky educational) and #10 (STEM), but those succeed through
interactive/hands-on elements — not static narration over AI images.
""")

    # ── Actionable Recommendations ──
    report.append("## 16. Actionable Recommendations")
    report.append("")

    report.append("""### TIER 1: Existential (Do This Week Or Views Will Keep Declining)

**1. Reduce upload frequency from 14/week to 4-5/week**
- Current 2/day schedule matches YouTube's mass-production detection pattern
- ChuChu TV does 10-15/month with 96M subscribers
- Fewer, higher-quality videos > daily AI-generated content
- Expected impact: Reduces AI slop risk score, stops algorithmic suppression

**2. Add human element to break AI slop detection**
- Option A: Record your own voiceover instead of TTS (even basic phone recording > TTS)
- Option B: Add brief face-cam intro/outro (even 5 seconds of a human face signals "real creator")
- Option C: Use a premium voice clone (ElevenLabs voice clone) with varied delivery styles
- Why: YouTube's detection specifically targets "synthetic voices" + "no human presence"

**3. Vary your video format/structure**
- Current: Every video = same 6-scene structure + Ken Burns + TTS + AI image
- YouTube detects "every upload looks, sounds, and moves the same"
- Mix in: different scene counts, different animation styles, different music, occasional live footage
- Even small variations signal "human creative decisions" vs "automated pipeline"

### TIER 2: Strategic (This Month)

**4. Pivot to replay-friendly content**
- Current content: one-time educational facts (watch once, no reason to rewatch)
- Top kids channels succeed because kids REWATCH: songs, counting, alphabet
- Create: Hinglish counting songs (1-20), alphabet adventures, color songs
- These formats generate 10-100x more views because kids loop them

**5. Create compilation/mix videos**
- Take existing shorts and compile into 15-30 minute "super compilations"
- Parents put these on for screen time → massive watch time accumulation
- Watch time is the #1 metric for YouTube algorithm
- Zero additional content creation cost — just re-editing existing content

**6. Optimize for parent discovery (not kid discovery)**
- COPPA disables kid-side engagement (no notifications, no personalized recs)
- Parents find content via YouTube Search and Browse
- Title strategy: Include parent-appealing keywords ("Educational", "Learning", "Safe for Kids")
- Thumbnail strategy: Clean, educational look (not flashy/colorful — parents trust professional-looking content)

**7. Add music/songs to your pipeline**
- Nursery rhymes = the single most successful kids content format on YouTube
- Use AI music generation (Suno, Udio) + your existing animation pipeline
- Even simple educational songs with Hinglish lyrics + animated characters would outperform fact narration
- Catchy 60-90 second songs designed for replay

### TIER 3: Growth Accelerators (Ongoing)

**8. Regional language expansion**
- Tamil, Telugu, Bengali kids content is massively underserved
- ChuChu TV has 12 language channels — most small creators ignore this
- Your pipeline already supports translation (translate_script in script_agent.py)
- Start with Telugu or Tamil (large YouTube audiences, less competition)

**9. Cross-platform seeding**
- Post short teasers on Instagram Reels, TikTok, Facebook
- External traffic signals help YouTube's algorithm
- Critical because COPPA disables the normal discovery mechanisms
- Your pipeline already has Instagram integration (just needs enabling)

**10. YouTube Kids app optimization**
- The YouTube Kids app has a SEPARATE recommendation algorithm
- It rewards: high engagement, replays, watch time, likes
- Most small creators don't know this or optimize for it
- Focus on content that kids replay (songs, counting) to rank in Kids app

**11. Enable analytics feedback loop**
- Set `analytics.enabled: true` in config.yaml
- Let the pipeline learn from performance data
- Auto-adjust topic selection toward what actually gets views
""")

    # ── 30-Day Action Plan ──
    report.append("## 17. 30-Day Action Plan")
    report.append("")
    report.append("""### Week 1: Stop the Bleeding
- [ ] Reduce uploads to 1/day (down from 2/day)
- [ ] Record your own voiceover for 2-3 videos (test TTS vs human voice performance)
- [ ] Create 1 compilation video from existing shorts (15-20 min)
- [ ] Enable analytics feedback loop in config.yaml

### Week 2: Format Diversification
- [ ] Create 2 counting/alphabet song videos (use AI music generation)
- [ ] Vary video structure (try 4 scenes instead of 6, different transitions)
- [ ] A/B test thumbnails: current gradient style vs clean educational style
- [ ] Reduce to 5 videos/week total

### Week 3: Discovery Optimization
- [ ] Audit all titles for parent-friendly keywords
- [ ] Create first Telugu or Tamil language video
- [ ] Enable Instagram cross-posting
- [ ] Create 1 more compilation video

### Week 4: Measure & Iterate
- [ ] Run this analysis script again to compare metrics
- [ ] Identify which changes had the most impact
- [ ] Double down on what works
- [ ] Plan next month's content strategy based on data
""")

    # ── Made-for-Kids Strategy ──
    report.append("## 18. Made-for-Kids: Can You Change It?")
    report.append("")
    report.append("""**Short answer: No, and here's why.**

Your content is animated educational content specifically targeting ages 3-8. This IS "made for kids"
by YouTube's definition. Setting `made_for_kids: false` would be:

1. **A COPPA violation** — FTC fines up to $50,120 per violation
2. **Auto-detected by YouTube** — YouTube's AI in 2025-2026 auto-reclassifies based on audience
   composition. Animated kids educational content WILL be flagged regardless of your setting.
3. **Risky for channel termination** — YouTube may terminate channels that repeatedly mislabel content

**Alternative strategy: Create a SECOND channel for "family-friendly" content**
- Not targeted at kids specifically, but enjoyable by all ages
- Examples: "Amazing Science Facts Everyone Should Know" (not "for kids")
- Same pipeline, different framing — targets families, not children
- Keeps comments, notifications, personalized recommendations
- Higher CPM, better discovery

This is how successful creators navigate COPPA: they run TWO channels — one Made-for-Kids
(COPPA compliant) and one family-friendly (full features).
""")

    report.append("---")
    report.append(f"*Report generated on {now} by analyze_channel.py*")
    report.append(f"*Sources: YouTube Data API v3, YouTube Analytics API v2, EC2 pipeline database*")

    return "\n".join(report)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_duration(iso_duration):
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _parse_iso_date(iso_str):
    """Parse ISO 8601 date string to datetime."""
    # Handle both 'Z' and '+00:00' formats
    iso_str = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_str.replace("+00:00", ""))
    except ValueError:
        return datetime.strptime(iso_str[:19], "%Y-%m-%dT%H:%M:%S")


def _format_duration(seconds):
    """Format seconds to M:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _safe_ratio(numerator, denominator):
    """Safe division returning 0 if denominator is 0."""
    return numerator / denominator if denominator > 0 else 0


def _infer_category(title):
    """Infer category from video title keywords."""
    title_lower = title.lower()
    categories = {
        "science": ["science", "experiment", "magnet", "weather", "bubble", "fossil", "crystal", "light", "geology", "pattern", "texture", "tornado"],
        "animals": ["animal", "creatures", "whale", "starfish", "snake", "bug", "insect", "mammal", "jellyfish", "footprint", "wildlife"],
        "nature": ["nature", "ocean", "mountain", "cloud", "coral", "plant", "tree", "garden", "biome", "fungi", "mushroom", "jungle"],
        "space": ["space", "planet", "galaxy", "comet", "star", "moon", "solar"],
        "food": ["food", "fruit", "veggie", "vegetable", "cooking", "yummy"],
        "math": ["math", "shape", "geometry", "counting", "number"],
        "history": ["history", "invention", "fairy tale"],
        "poem": ["poem", "rhyme", "rhyming"],
        "lullaby": ["lullaby", "sleep", "dream", "goodnight"],
    }
    for cat, keywords in categories.items():
        if any(kw in title_lower for kw in keywords):
            return cat
    return "other"


def _calculate_health_score(channel, videos, growth, risk, retention):
    """Calculate channel health score 0-100."""
    score = 50  # Start neutral

    # Views performance
    avg_views = mean([v["views"] for v in videos]) if videos else 0
    if avg_views >= 500:
        score += 15
    elif avg_views >= 100:
        score += 5
    elif avg_views < 50:
        score -= 10

    # Growth trend
    if growth["trend"] == "growing":
        score += 15
    elif growth["trend"] == "declining":
        score -= 15

    # AI risk
    score -= risk["risk_score"] * 0.3

    # Retention
    if retention.get("avg_view_percentage", 0) > 50:
        score += 10
    elif retention.get("avg_view_percentage", 0) < 30:
        score -= 10

    # Subscriber ratio
    if channel["subscribers"] > 0:
        views_per_sub = channel["total_views"] / channel["subscribers"]
        if views_per_sub > 100:
            score += 5

    return max(0, min(100, int(score)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("YouTube Channel Analysis")
    print("=" * 60)
    print()

    # 1. Authenticate
    print("[1/7] Authenticating with YouTube API...")
    youtube, youtube_analytics = authenticate()
    print("  Authentication successful.")

    # 2. Fetch channel stats
    print("[2/7] Fetching channel statistics...")
    channel = fetch_channel_stats(youtube)
    print(f"  Channel: {channel['title']}")
    print(f"  Subscribers: {channel['subscribers']:,}")
    print(f"  Total Views: {channel['total_views']:,}")
    print(f"  Total Videos: {channel['total_videos']}")

    # 3. Fetch all videos
    print("[3/7] Fetching all video details...")
    video_ids = fetch_all_video_ids(youtube, channel["uploads_playlist"])
    videos = fetch_video_details_batch(youtube, video_ids)

    # 4. Enrich with local data
    print("[4/7] Enriching with local database...")
    videos = enrich_with_local_data(videos, EC2_DB_PATH)

    # 5. Fetch analytics
    print("[5/7] Fetching YouTube Analytics data...")
    start_date = channel["created_at"][:10]
    end_date = datetime.now().strftime("%Y-%m-%d")
    analytics_data = fetch_analytics_data(youtube_analytics, channel["channel_id"], start_date, end_date)
    print(f"  Per-video analytics: {len(analytics_data.get('per_video', {}))} videos")
    print(f"  Traffic sources: {len(analytics_data.get('traffic_sources', {}))} sources")
    print(f"  Daily data points: {len(analytics_data.get('daily', []))}")

    # 6. Run analysis
    print("[6/7] Running analysis...")
    topic_perf = analyze_topic_performance(videos)
    content_types = analyze_content_types(videos)
    publishing = analyze_publishing_patterns(videos)
    metadata_quality = analyze_metadata_quality(videos)
    growth = analyze_growth_trajectory(videos)
    traffic = analyze_traffic_sources(analytics_data)
    retention = analyze_audience_retention(videos, analytics_data)
    impressions = analyze_impressions_ctr(analytics_data)
    risk = ai_content_risk_assessment(videos, growth)
    devices = analyze_devices(analytics_data)
    geography = analyze_geography(analytics_data)

    print(f"  Growth trend: {growth['trend']} ({growth['trend_pct']:+.1f}%)")
    print(f"  AI risk score: {risk['risk_score']}/100")

    # 7. Generate report
    print("[7/7] Generating report...")
    report = generate_report(
        channel, videos, analytics_data, topic_perf, content_types,
        publishing, metadata_quality, growth, traffic, retention,
        impressions, risk, devices, geography,
    )

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"\n{'=' * 60}")
    print(f"Report saved to: {REPORT_PATH}")
    print(f"{'=' * 60}")

    # Quick summary
    print(f"\n--- Quick Summary ---")
    print(f"Channel Health Score: {_calculate_health_score(channel, videos, growth, risk, retention)}/100")
    print(f"AI Slop Risk Score: {risk['risk_score']}/100")
    print(f"Avg Views/Video: {mean([v['views'] for v in videos]):.0f}")
    print(f"Growth Trend: {growth['trend']}")
    print(f"Top Category: {topic_perf[0]['category'] if topic_perf else 'N/A'} ({topic_perf[0]['avg_views']:.0f} avg views)")
    print(f"\nTop 3 Risks:")
    for r in risk["risks"][:3]:
        print(f"  - {r}")


if __name__ == "__main__":
    main()
