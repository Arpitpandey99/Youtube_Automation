"""
Topic Cluster Engine — groups topics into thematic clusters for topical authority.
Uses GPT to intelligently group topics, then prioritizes based on performance + trends.
"""

import json
import os
from datetime import datetime, timedelta

from openai import OpenAI

from agents.db import (
    get_connection, insert_topic_cluster, get_active_clusters,
    increment_cluster_usage, clear_clusters, get_category_weights,
    get_unused_trend_topics,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CLUSTERS_FILE = os.path.join(DATA_DIR, "topic_clusters.json")
HISTORY_FILE = os.path.join(DATA_DIR, "topics_history.json")


def _load_all_topics() -> list:
    """Collect topics from trend_topics + topics_history for clustering."""
    topics = set()

    # From trend topics
    trend_topics = get_unused_trend_topics(limit=50)
    for t in trend_topics:
        topics.add(t["topic"])

    # From topics history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
        for h in history[-100:]:
            if isinstance(h, dict):
                topics.add(h.get("topic", ""))
            elif isinstance(h, str):
                topics.add(h)

    return [t for t in topics if t and len(t) > 5]


def generate_clusters(config: dict, topics: list = None) -> list:
    """Use GPT to group topics into thematic clusters.

    Returns list of {"cluster_name": str, "theme": str, "topics": list, "priority_score": float}
    """
    if topics is None:
        topics = _load_all_topics()

    if len(topics) < 5:
        print("  Not enough topics for clustering (need at least 5).")
        return []

    client = OpenAI(api_key=config["openai"]["api_key"])
    max_clusters = config.get("clusters", {}).get("max_clusters", 15)
    min_size = config.get("clusters", {}).get("min_cluster_size", 3)

    prompt = f"""I have {len(topics)} kids educational YouTube video topics. Group them into
{max_clusters} or fewer thematic clusters. Each cluster should be a coherent theme
that could become a YouTube playlist or video series.

Topics:
{json.dumps(topics[:80], indent=2)}

Rules:
- Each cluster needs at least {min_size} topics
- Create catchy, kid-friendly cluster names (e.g., "Amazing Animal Superpowers", "Space Secrets", "Tiny Science Lab")
- If some topics don't fit any cluster, group them into a "Mixed Fun Facts" cluster
- For each cluster, also suggest 3-5 NEW topics that would fit the theme (to expand the cluster)

Return JSON array:
[
    {{
        "cluster_name": "Amazing Animal Superpowers",
        "theme": "Animals with incredible abilities",
        "topics": ["existing topic 1", "existing topic 2", "new suggested topic 1", ...]
    }}
]

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You organize educational content into thematic clusters. Respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=3000,
    )

    clusters = json.loads(response.choices[0].message.content.strip())
    return clusters


def prioritize_clusters(config: dict, clusters: list) -> list:
    """Score clusters by trend overlap, category performance, and freshness.

    Score = trend_overlap * 0.4 + category_performance * 0.4 + freshness * 0.2
    """
    # Load used topics for freshness calculation
    used_topics = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
        for h in history:
            if isinstance(h, dict):
                used_topics.add(h.get("topic", "").lower())
            elif isinstance(h, str):
                used_topics.add(h.lower())

    # Load trend topics for overlap calculation
    trend_topics = get_unused_trend_topics(limit=100)
    trend_set = {t["topic"].lower() for t in trend_topics}

    # Load category weights for performance signal
    cat_weights = {w["category"]: w["weight"] for w in get_category_weights()}

    for cluster in clusters:
        topics = cluster.get("topics", [])
        if not topics:
            cluster["priority_score"] = 0
            continue

        # Trend overlap: what % of cluster topics are trending
        trend_overlap = sum(1 for t in topics if t.lower() in trend_set) / len(topics)

        # Category performance: check if cluster theme matches high-performing categories
        cat_score = 0
        theme_lower = cluster.get("theme", "").lower()
        for cat, weight in cat_weights.items():
            if cat.lower() in theme_lower or cat.lower() in cluster.get("cluster_name", "").lower():
                cat_score = max(cat_score, weight)

        # Freshness: what % of topics are NOT already used
        freshness = sum(1 for t in topics if t.lower() not in used_topics) / len(topics)

        cluster["priority_score"] = round(
            trend_overlap * 0.4 + cat_score * 0.4 + freshness * 0.2,
            3
        )

    clusters.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    return clusters


def save_clusters(clusters: list):
    """Save clusters to JSON file and database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CLUSTERS_FILE, "w") as f:
        json.dump(clusters, f, indent=2)
    print(f"  Saved {len(clusters)} clusters to {CLUSTERS_FILE}")

    # Save to DB (clear old ones first)
    clear_clusters()
    for cluster in clusters:
        insert_topic_cluster(
            cluster_name=cluster["cluster_name"],
            theme=cluster.get("theme", ""),
            topics=cluster.get("topics", []),
            priority_score=cluster.get("priority_score", 0.0),
        )


def get_next_cluster_topic(config: dict) -> dict:
    """Pick the next unused topic from the highest-priority cluster.

    Returns a topic_data dict compatible with the existing pipeline:
    {"topic": str, "category": str, "target_age": str, "description": str, "cluster_name": str}
    """
    clusters = get_active_clusters()
    if not clusters:
        return None

    # Load used topics
    used_topics = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
        for h in history:
            if isinstance(h, dict):
                used_topics.add(h.get("topic", "").lower())

    for cluster in clusters:
        topics = json.loads(cluster["topics_json"]) if isinstance(cluster["topics_json"], str) else cluster["topics_json"]
        used_count = cluster["topics_used"]

        # Find first unused topic in this cluster
        for topic in topics:
            if topic.lower() not in used_topics:
                increment_cluster_usage(cluster["id"])
                target_age = config.get("content", {}).get("target_age", "3-8")
                return {
                    "topic": topic,
                    "category": cluster.get("theme", "general").split()[0].lower(),
                    "target_age": target_age,
                    "description": f"Part of cluster: {cluster['cluster_name']}",
                    "cluster_name": cluster["cluster_name"],
                }

    return None


def refresh_clusters(config: dict) -> list:
    """Full cluster refresh: load topics, cluster them, prioritize, save.

    This is the main entry point called by CLI --generate-clusters.
    """
    print("\n[Topic Cluster Engine] Generating topic clusters...")

    # 1. Collect all topics
    topics = _load_all_topics()
    print(f"  Collected {len(topics)} topics for clustering")

    if len(topics) < 5:
        print("  Not enough topics. Run --refresh-trends first to gather more topics.")
        return []

    # 2. Generate clusters
    print("  Generating clusters via GPT...")
    clusters = generate_clusters(config, topics)
    print(f"  Created {len(clusters)} clusters")

    # 3. Prioritize
    print("  Computing priority scores...")
    clusters = prioritize_clusters(config, clusters)

    # 4. Save
    save_clusters(clusters)

    print("\n  Cluster refresh complete!")
    for c in clusters[:5]:
        print(f"    {c['cluster_name']} — {len(c.get('topics', []))} topics, score: {c.get('priority_score', 0):.3f}")

    return clusters
