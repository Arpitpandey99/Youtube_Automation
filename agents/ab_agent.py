"""
A/B testing agent for titles, hooks, and thumbnails.
Generates multiple variants and tracks performance to optimize CTR.
"""

import json
import random
from openai import OpenAI

from agents.db import (
    insert_ab_variant, update_ab_variant_result, get_connection
)


def generate_ab_variants(config: dict, topic_data: dict, script_data: dict,
                         metadata: dict, language: str = "English") -> dict:
    """Generate A/B test variants for title, hook, and thumbnail text.

    Returns dict with 'variants' list, each containing:
    - title, hook, thumbnail_text
    """
    client = OpenAI(api_key=config["openai"]["api_key"])
    variants_count = config.get("ab_testing", {}).get("variants_count", 3)

    prompt = f"""You are a YouTube SEO expert. Generate {variants_count} different variants
for a kids' YouTube video to A/B test for maximum click-through rate (CTR).

Original video info:
- Topic: {topic_data["topic"]}
- Category: {topic_data["category"]}
- Current title: {metadata["title"]}
- Current hook: {script_data["intro_hook"]}
- Current thumbnail text: {metadata.get("thumbnail_text", "")}
- Language: {language}

For each variant, create a DIFFERENT approach:
- Variant 1: Curiosity-driven (question-based title)
- Variant 2: Excitement-driven (emoji-heavy, exclamation)
- Variant 3: Educational/value-driven (what kids will learn)

{"Write titles and hooks in " + language + "." if language != "English" else ""}

Respond in this exact JSON format:
{{
    "variants": [
        {{
            "title": "variant title (max 70 chars)",
            "hook": "variant intro hook (1 sentence)",
            "thumbnail_text": "SHORT TEXT (max 4 words)"
        }}
    ]
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You are a YouTube A/B testing expert for kids' content. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=800,
    )

    result = json.loads(response.choices[0].message.content.strip())
    return result


def pick_variant(config: dict, variants: dict, video_db_id: int) -> dict:
    """Pick the best variant based on historical data, or random if insufficient data.

    Stores the chosen variant in the database and returns it.
    """
    min_data = config.get("ab_testing", {}).get("min_data_points", 10)

    # Check if we have enough historical data
    conn = get_connection()
    total_videos = conn.execute("SELECT COUNT(*) FROM ab_variants WHERE ctr > 0").fetchone()[0]
    conn.close()

    variant_list = variants.get("variants", [])
    if not variant_list:
        return {}

    if total_videos >= min_data:
        # Use historical data to bias selection toward higher-performing styles
        conn = get_connection()
        rows = conn.execute(
            """SELECT variant_data, AVG(ctr) as avg_ctr
               FROM ab_variants WHERE ctr > 0
               GROUP BY variant_type
               ORDER BY avg_ctr DESC"""
        ).fetchall()
        conn.close()

        if rows:
            # Bias toward first variant (curiosity) if it historically performs best
            # But still allow exploration with 30% random chance
            if random.random() < 0.3:
                chosen = random.choice(variant_list)
            else:
                chosen = variant_list[0]  # Best-performing style
        else:
            chosen = random.choice(variant_list)
    else:
        # Not enough data, pick randomly
        chosen = random.choice(variant_list)

    # Store in database
    variant_id = insert_ab_variant(
        video_db_id=video_db_id,
        variant_type="title_hook_thumbnail",
        variant_data=chosen,
    )
    chosen["variant_id"] = variant_id

    return chosen


def record_variant_result(variant_id: int, ctr: float, is_winner: bool = False):
    """Record the performance result for an A/B variant."""
    update_ab_variant_result(variant_id, ctr, is_winner)


def apply_variant_to_metadata(metadata: dict, variant: dict) -> dict:
    """Apply the chosen A/B variant to the metadata."""
    if not variant:
        return metadata

    updated = metadata.copy()
    if "title" in variant:
        updated["title"] = variant["title"]
    if "thumbnail_text" in variant:
        updated["thumbnail_text"] = variant["thumbnail_text"]
    return updated
