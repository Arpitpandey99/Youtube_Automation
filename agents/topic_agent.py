"""
Topic Agent — v2 tech-explainer topic selection with weighted clusters.

Priority chain: Series episode → Cluster topic → Trending topic → GPT random.
Category weights are read from topic_scores table (updated by learning_agent).
"""

import json
import os
import random
from openai import OpenAI

from agents.analytics_agent import get_performance_hints


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "topics_history.json")

# v2: Tech explainer categories (replaces kids categories)
TECH_CATEGORIES = [
    "digital_payments",      # UPI, FASTag, RuPay, digital wallets
    "identity_systems",      # Aadhaar, DigiLocker, e-KYC
    "telecom_networks",      # 5G, Wi-Fi, satellite internet, AMI
    "transport_tech",        # Indian Railways, metro systems, GPS/ISRO
    "internet_infra",        # undersea cables, CDNs, DNS, how internet works
    "security_crypto",       # encryption, WhatsApp E2E, blockchain basics
    "government_tech",       # GSTIN, CoWIN, IRCTC backend, NIC systems
    "ai_ml_explained",       # how ChatGPT works, recommendation systems
    "hardware_chips",        # chip manufacturing, ARM vs x86, Indian fabs
    "everyday_tech",         # QR codes, barcodes, NFC, how apps work
]

# v2: Seed topics from REVAMP_PLAN.md Section 2
SEED_TOPICS = [
    {"topic": "WhatsApp ka encryption actually kaise kaam karta hai?", "category": "security_crypto"},
    {"topic": "UPI banaya kaise gaya? Pure backend ki kahani", "category": "digital_payments"},
    {"topic": "Aadhaar ka system inside out", "category": "identity_systems"},
    {"topic": "Why Indian ATMs are different from rest of the world", "category": "digital_payments"},
    {"topic": "5G in India — vo sab jo kisi ne nahi bataya", "category": "telecom_networks"},
    {"topic": "Smart meters aur AMI networks — your electricity bill ka future", "category": "telecom_networks"},
    {"topic": "DigiLocker kaise kaam karta hai", "category": "identity_systems"},
    {"topic": "FASTag system architecture", "category": "transport_tech"},
    {"topic": "IRCTC ka backend kyu crash hota hai", "category": "government_tech"},
]


def get_seed_topics() -> list[dict]:
    """Return the initial cluster seed topics from the revamp plan."""
    return SEED_TOPICS


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def _get_category_weights() -> dict[str, float]:
    """Read category weights from topic_scores table (populated by learning_agent)."""
    try:
        from agents.db import get_top_categories
        top = get_top_categories(limit=20)
        if top:
            return {r["category"]: r["avg_score"] for r in top if r.get("avg_score", 0) > 0}
    except Exception:
        pass
    return {}


def _weighted_category_pick() -> str:
    """Pick a category weighted by performance, or random from TECH_CATEGORIES."""
    weights = _get_category_weights()
    if weights:
        cats = list(weights.keys())
        wts = list(weights.values())
        return random.choices(cats, weights=wts, k=1)[0]
    return random.choice(TECH_CATEGORIES)


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

            print(f"  [Topic] Using trend topic: {trend['topic']}")
            return {
                "topic": trend["topic"],
                "category": trend.get("category", "everyday_tech"),
                "description": f"Trending topic (score: {trend.get('trend_score', 0):.2f})",
            }
    except Exception as e:
        print(f"  [Topic] Trend lookup failed: {e}")

    return None


def generate_topic(config: dict) -> dict:
    """Generate a tech-explainer video topic using the priority chain.

    Priority: Series episode → Cluster topic → Trending topic → GPT random.
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
        if topic_data["topic"].lower() not in {t.lower() for t in past_topics}:
            history.append(topic_data)
            save_history(history)
            return topic_data
        else:
            print(f"  [Topic] '{topic_data['topic']}' already used, falling back to GPT")

    # Fallback: GPT random generation — tech explainer
    print("  [Topic] Using GPT random generation")
    client = OpenAI(api_key=config["openai"]["api_key"])

    # Pick a weighted category
    category_hint = _weighted_category_pick()

    # Get performance hints if analytics is enabled
    perf_hints = get_performance_hints(config)
    perf_section = f"\n\nPERFORMANCE DATA:\n{perf_hints}\nUse these insights to pick a topic likely to perform well." if perf_hints else ""

    prompt = f"""Generate 1 unique YouTube video topic for a Hinglish tech-explainer channel.

Channel concept: "How things actually work" — Indian tech, science, and infrastructure deep-dives.
Target audience: curious Indian adults and students interested in technology.
Language: Hinglish (Hindi-English code-switching, the way educated urban Indians talk about tech).

Suggested category (but you can pick a different one if you have a better idea): {category_hint}

Available categories: {json.dumps(TECH_CATEGORIES)}

The topic must NOT be any of these previously used topics:
{json.dumps(past_topics[-30:], indent=2) if past_topics else "None yet"}
{perf_section}
Requirements:
- Topic should explain "how something works" or "why something is the way it is"
- Prefer Indian tech/infrastructure (UPI, Aadhaar, IRCTC, Indian Railways, 5G India, etc.)
- Topic should be specific enough to research deeply, not a vague overview
- Title should be in Hinglish, curiosity-inducing

Respond in this exact JSON format:
{{
    "topic": "the video topic title in Hinglish",
    "category": "one of the categories listed above",
    "description": "one line description of what the video will explain"
}}

Only return the JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You create engaging Hinglish tech-explainer video topics for an Indian audience. Respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=200,
    )

    topic_data = json.loads(response.choices[0].message.content.strip())

    history.append(topic_data)
    save_history(history)

    return topic_data
