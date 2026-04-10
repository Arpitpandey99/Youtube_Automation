"""
Series Generator — transforms topic clusters into episodic content series.
Maintains theme continuity, assigns characters, and tracks episode production.
"""

import json
import os
from datetime import datetime

from openai import OpenAI

from agents.db import (
    get_active_clusters, get_active_series, get_series_by_name,
    insert_series, insert_series_episode, get_next_planned_episode,
    mark_episode_produced as db_mark_episode_produced,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SERIES_FILE = os.path.join(DATA_DIR, "series_plan.json")
HISTORY_FILE = os.path.join(DATA_DIR, "topics_history.json")


def _get_available_characters() -> list:
    """List available character IDs from data/characters/."""
    chars_dir = os.path.join(DATA_DIR, "characters")
    if not os.path.exists(chars_dir):
        return []
    return [d for d in os.listdir(chars_dir)
            if os.path.isdir(os.path.join(chars_dir, d))]


def generate_series_plan(config: dict, cluster: dict) -> dict:
    """Use GPT to transform a topic cluster into an episodic series plan.

    Returns: {
        "series_name": str,
        "series_description": str,
        "character_id": str,
        "episodes": [{"episode_number": int, "topic": str, "title": str,
                       "description": str, "continuity_notes": str}]
    }
    """
    client = OpenAI(api_key=config["openai"]["api_key"])
    target_episodes = config.get("series", {}).get("episodes_per_series", 15)
    characters = _get_available_characters()

    cluster_name = cluster.get("cluster_name", "Unknown")
    cluster_topics = cluster.get("topics", [])
    if isinstance(cluster_topics, str):
        cluster_topics = json.loads(cluster_topics)

    char_instruction = ""
    if characters:
        char_instruction = f"""
Available characters (pick ONE to be the host of this series): {json.dumps(characters)}
If none fit well, leave character_id as null."""

    prompt = f"""Create an episodic kids' YouTube series plan based on this topic cluster.

Cluster: {cluster_name}
Theme: {cluster.get("theme", "")}
Available topics: {json.dumps(cluster_topics, indent=2)}
Target episodes: {target_episodes}
{char_instruction}

Rules:
- Create a catchy series name that kids will remember
- Each episode should cover one topic from the cluster (or a closely related new topic)
- Add "continuity_notes" for each episode explaining how it connects to the previous one
  (e.g., "Reference the dinosaur size comparison from Episode 2")
- Episodes should build on each other — start with simpler concepts, get more detailed
- Include episode titles that follow a pattern (e.g., all start with the series name)
- If you need more topics to reach {target_episodes} episodes, create new related ones

Return JSON:
{{
    "series_name": "catchy series name",
    "series_description": "what this series is about (1 sentence)",
    "character_id": "one of the available characters or null",
    "episodes": [
        {{
            "episode_number": 1,
            "topic": "the specific topic",
            "title": "Episode Title",
            "description": "what this episode covers (1 sentence)",
            "continuity_notes": "how it connects to the series narrative"
        }}
    ]
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You create episodic content series for kids' YouTube channels. Respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=3000,
    )

    plan = json.loads(response.choices[0].message.content.strip())
    return plan


def save_series_to_db(plan: dict, cluster_id: int = None) -> int:
    """Save a series plan to the database.

    Returns the series DB id.
    """
    series_id = insert_series(
        series_name=plan["series_name"],
        series_description=plan.get("series_description", ""),
        character_id=plan.get("character_id"),
        cluster_id=cluster_id,
        target_episodes=len(plan.get("episodes", [])),
    )

    for ep in plan.get("episodes", []):
        insert_series_episode(
            series_id=series_id,
            episode_number=ep["episode_number"],
            topic=ep["topic"],
            title=ep.get("title"),
            description=ep.get("description"),
            continuity_notes=ep.get("continuity_notes"),
        )

    return series_id


def get_next_episode(config: dict, series_name: str = None) -> dict:
    """Get the next unproduced episode from a series.

    If series_name is None, picks from the active series with most produced episodes
    (to maintain momentum on existing series before starting new ones).

    Returns a topic_data-compatible dict:
    {"topic": str, "category": str, "target_age": str, "description": str,
     "series_name": str, "episode_number": int, "episode_id": int,
     "continuity_notes": str}
    """
    if series_name:
        series = get_series_by_name(series_name)
        if not series:
            print(f"  Series '{series_name}' not found.")
            return None
        active = [series]
    else:
        active = get_active_series()

    if not active:
        return None

    # Sort by produced_episodes descending (continue existing series first)
    active.sort(key=lambda s: s["produced_episodes"], reverse=True)

    target_age = config.get("content", {}).get("target_age", "3-8")

    for series in active:
        episode = get_next_planned_episode(series["id"])
        if episode:
            return {
                "topic": episode["topic"],
                "category": series.get("series_description", "general").split()[0].lower(),
                "target_age": target_age,
                "description": episode.get("description", ""),
                "series_name": series["series_name"],
                "series_description": series.get("series_description", ""),
                "episode_number": episode["episode_number"],
                "episode_id": episode["id"],
                "continuity_notes": episode.get("continuity_notes", ""),
                "character_id": series.get("character_id"),
            }

    return None


def mark_episode_produced(episode_id: int, video_db_id: int):
    """Mark a series episode as produced and link to video record."""
    db_mark_episode_produced(episode_id, video_db_id)
    print(f"  Series episode {episode_id} marked as produced (video #{video_db_id})")


def list_series(config: dict) -> list:
    """List all active series with progress."""
    series_list = get_active_series()
    if not series_list:
        print("  No active series. Run --generate-series to create some.")
        return []

    print(f"\n  Active Series ({len(series_list)}):")
    for s in series_list:
        progress = f"{s['produced_episodes']}/{s['target_episodes']}"
        char = f" [{s['character_id']}]" if s.get("character_id") else ""
        print(f"    {s['series_name']}{char} — {progress} episodes produced")

    return series_list


def generate_series(config: dict) -> list:
    """Generate series plans from top clusters.

    This is the main entry point called by CLI --generate-series.
    """
    print("\n[Series Generator] Creating episodic series from clusters...")

    max_series = config.get("series", {}).get("max_active_series", 3)

    # Check existing series
    existing = get_active_series()
    if len(existing) >= max_series:
        print(f"  Already have {len(existing)} active series (max: {max_series}).")
        print("  Complete or pause existing series before creating new ones.")
        list_series(config)
        return existing

    slots = max_series - len(existing)

    # Get top clusters
    clusters = get_active_clusters()
    if not clusters:
        print("  No topic clusters available. Run --generate-clusters first.")
        return []

    plans = []
    for cluster in clusters[:slots]:
        print(f"\n  Generating series for cluster: {cluster['cluster_name']}...")
        topics = json.loads(cluster["topics_json"]) if isinstance(cluster["topics_json"], str) else cluster["topics_json"]
        cluster_dict = {
            "cluster_name": cluster["cluster_name"],
            "theme": cluster.get("theme", ""),
            "topics": topics,
        }

        plan = generate_series_plan(config, cluster_dict)
        series_id = save_series_to_db(plan, cluster_id=cluster["id"])
        plan["series_id"] = series_id
        plans.append(plan)

        print(f"    Created: {plan['series_name']} — {len(plan.get('episodes', []))} episodes")

    # Save to JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SERIES_FILE, "w") as f:
        json.dump(plans, f, indent=2)

    print(f"\n  Series generation complete! {len(plans)} new series created.")
    list_series(config)
    return plans
