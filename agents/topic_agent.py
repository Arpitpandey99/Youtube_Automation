import json
import os
import random
from openai import OpenAI

from agents.analytics_agent import get_performance_hints


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "topics_history.json")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def _try_series_topic(config: dict) -> dict | None:
    """Try to get a topic from an active series episode."""
    series_cfg = config.get("series", {})
    if not series_cfg.get("enabled", False):
        return None

    priority = series_cfg.get("series_topic_priority", 0.6)
    if random.random() > priority:
        return None

    try:
        from services.series_service import get_next_episode
        episode = get_next_episode(config)
        if episode:
            print(f"  [Topic] Using series episode: {episode['series_name']} Ep.{episode['episode_number']}")
            return episode
    except Exception as e:
        print(f"  [Topic] Series lookup failed: {e}")

    return None


def _try_cluster_topic(config: dict) -> dict | None:
    """Try to get a topic from a topic cluster."""
    cluster_cfg = config.get("clusters", {})
    if not cluster_cfg.get("enabled", False) or not cluster_cfg.get("use_cluster_topics", True):
        return None

    try:
        from services.cluster_service import get_next_cluster_topic
        topic = get_next_cluster_topic(config)
        if topic:
            print(f"  [Topic] Using cluster topic: {topic['cluster_name']}")
            return topic
    except Exception as e:
        print(f"  [Topic] Cluster lookup failed: {e}")

    return None


def _try_trend_topic(config: dict) -> dict | None:
    """Try to get a topic from trending data."""
    trend_cfg = config.get("trends", {})
    if not trend_cfg.get("enabled", False):
        return None

    weight = trend_cfg.get("trend_weight_in_topic_gen", 0.4)
    if random.random() > weight:
        return None

    try:
        from services.trend_service import get_trend_topics
        from agents.db import mark_trend_topic_used
        trends = get_trend_topics(config, limit=10)
        if trends:
            trend = trends[0]
            if trend.get("id"):
                mark_trend_topic_used(trend["id"])

            target_age = config.get("content", {}).get("target_age", "3-8")
            print(f"  [Topic] Using trend topic: {trend['topic']}")
            return {
                "topic": trend["topic"],
                "category": trend.get("category", "general"),
                "target_age": target_age,
                "description": f"Trending topic (score: {trend.get('trend_score', 0):.2f})",
            }
    except Exception as e:
        print(f"  [Topic] Trend lookup failed: {e}")

    return None


def generate_topic(config: dict) -> dict:
    """Generate a unique kid-friendly video topic using priority chain.

    Priority: Series episode → Cluster topic → Trending topic → GPT random
    """
    history = load_history()
    past_topics = [h["topic"] for h in history[-50:] if isinstance(h, dict)]

    # Priority chain: try each source in order
    topic_data = _try_series_topic(config)
    if not topic_data:
        topic_data = _try_cluster_topic(config)
    if not topic_data:
        topic_data = _try_trend_topic(config)

    if topic_data:
        # Check for duplicates
        if topic_data["topic"].lower() not in {t.lower() for t in past_topics}:
            history.append(topic_data)
            save_history(history)
            return topic_data
        else:
            print(f"  [Topic] '{topic_data['topic']}' already used, falling back to GPT")

    # Fallback: GPT random generation (original behavior)
    print("  [Topic] Using GPT random generation")
    client = OpenAI(api_key=config["openai"]["api_key"])

    niche = config["content"]["niche"]
    target_age = config["content"]["target_age"]

    # Get performance hints if analytics is enabled
    perf_hints = get_performance_hints(config)
    perf_section = f"\n\nPERFORMANCE DATA:\n{perf_hints}\nUse these insights to pick a topic likely to perform well." if perf_hints else ""

    prompt = f"""Generate 1 unique YouTube video topic for kids aged {target_age}.
Niche: {niche}

The topic must NOT be any of these previously used topics:
{json.dumps(past_topics, indent=2) if past_topics else "None yet"}
{perf_section}
Respond in this exact JSON format:
{{
    "topic": "the video topic title",
    "category": "e.g. animals, science, space, nature, history, alphabet, numbers",
    "target_age": "{target_age}",
    "description": "one line description of what the video will cover"
}}

Only return the JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You create engaging, educational, kid-friendly YouTube video topics. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=200,
    )

    topic_data = json.loads(response.choices[0].message.content.strip())

    # Save to history
    history.append(topic_data)
    save_history(history)

    return topic_data
