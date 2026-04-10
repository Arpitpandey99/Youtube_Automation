"""
Thumbnail A/B Testing Engine — generates multiple thumbnail variants,
evaluates performance, and auto-replaces underperformers.
"""

import os
import random
from datetime import datetime, timedelta

from agents.db import (
    get_connection, insert_thumbnail_variant, get_thumbnail_variants,
    activate_thumbnail_variant, get_latest_metrics,
)
from agents.metadata_agent import generate_youtube_thumbnail


# Variant strategies: different visual approaches for thumbnails
_VARIANT_STYLES = [
    {"font_scale": 1.0, "text_position": "center", "description": "Standard centered text"},
    {"font_scale": 1.2, "text_position": "top", "description": "Large text, top placement"},
    {"font_scale": 0.9, "text_position": "bottom", "description": "Compact text, bottom placement"},
]


def _generate_single_variant(config: dict, metadata: dict, image_path: str,
                              output_dir: str, content_type: str,
                              variant_index: int, style: dict) -> str:
    """Generate one thumbnail variant with modified styling.

    Uses the existing generate_youtube_thumbnail function as base,
    then applies variant-specific modifications.
    """
    from PIL import Image, ImageDraw
    from agents.metadata_agent import (
        _apply_gradient_overlay, _load_font, _draw_text_with_shadow,
        _draw_border_themed, _draw_corner_accents,
    )

    img = Image.open(image_path).resize((1280, 720), Image.LANCZOS)
    img = _apply_gradient_overlay(img, content_type)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()

    # Apply variant-specific font size
    base_size = 110
    font_size = int(base_size * style.get("font_scale", 1.0))
    font = _load_font(font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1280 - text_w) // 2

    # Apply variant-specific text position
    position = style.get("text_position", "center")
    if position == "top":
        y = int(720 * 0.25) - text_h // 2
    elif position == "bottom":
        y = int(720 * 0.75) - text_h // 2
    else:
        y = int(720 * 0.62) - text_h // 2

    _draw_text_with_shadow(draw, text, font, x, y)
    _draw_border_themed(draw, 1280, 720, content_type)
    _draw_corner_accents(draw, 1280, 720, content_type)

    variant_path = os.path.join(output_dir, f"thumbnail_variant_{variant_index}.png")
    img.save(variant_path, quality=95)
    return variant_path


def generate_thumbnail_variants(config: dict, metadata: dict, image_files: list,
                                output_dir: str, content_type: str = "video",
                                count: int = 3) -> list:
    """Generate multiple thumbnail PNG variants with different styles.

    Uses different background images (from scene images) and different text styling.
    Returns list of {"path": str, "variant_index": int, "description": str}
    """
    if not image_files:
        return []

    count = min(count, len(_VARIANT_STYLES), len(image_files) + 1)
    variants = []

    for i in range(count):
        style = _VARIANT_STYLES[i]
        # Use different scene images as backgrounds
        image_path = image_files[min(i, len(image_files) - 1)]

        try:
            variant_path = _generate_single_variant(
                config, metadata, image_path, output_dir,
                content_type, i, style
            )
            variants.append({
                "path": variant_path,
                "variant_index": i,
                "description": style["description"],
            })
        except Exception as e:
            print(f"  Warning: Thumbnail variant {i} generation failed: {e}")

    return variants


def store_thumbnail_variants(video_db_id: int, variants: list, primary_path: str = None):
    """Store thumbnail variants in the database.

    If primary_path is provided, it's stored as variant 0 (active).
    """
    if primary_path:
        insert_thumbnail_variant(
            video_db_id=video_db_id,
            variant_index=0,
            file_path=primary_path,
            description="Primary thumbnail",
            is_active=True,
        )

    for v in variants:
        insert_thumbnail_variant(
            video_db_id=video_db_id,
            variant_index=v["variant_index"] + 1,  # offset by 1 since primary is 0
            file_path=v["path"],
            description=v.get("description", ""),
            is_active=False,
        )


def replace_thumbnail(config: dict, video_id: str, thumbnail_path: str) -> bool:
    """Replace a live YouTube video's thumbnail.

    Uses the YouTube Data API thumbnails().set() endpoint.
    """
    from agents.upload_agent import get_authenticated_service
    from googleapiclient.http import MediaFileUpload

    try:
        youtube = get_authenticated_service(config)
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
        ).execute()
        print(f"  Thumbnail replaced for video {video_id}")
        return True
    except Exception as e:
        print(f"  Warning: Thumbnail replacement failed: {e}")
        return False


def evaluate_thumbnails(config: dict, video_db_id: int) -> dict:
    """Evaluate a video's thumbnail performance after 72+ hours.

    Compares video's CTR to channel average.
    Returns: {"current_ctr": float, "channel_avg_ctr": float,
              "should_replace": bool, "replacement_variant": dict or None}
    """
    conn = get_connection()

    # Get the video's video_id
    video = conn.execute(
        "SELECT video_id FROM videos WHERE id = ?", (video_db_id,)
    ).fetchone()

    if not video or not video["video_id"]:
        conn.close()
        return {"should_replace": False}

    # Get video's current metrics
    metrics = get_latest_metrics(video["video_id"])
    if not metrics:
        conn.close()
        return {"should_replace": False}

    current_ctr = metrics.get("ctr", 0)

    # Get channel average CTR
    avg_row = conn.execute(
        """SELECT AVG(ctr) as avg_ctr FROM metrics
           WHERE ctr > 0
           AND fetched_at = (
               SELECT MAX(m2.fetched_at) FROM metrics m2
               WHERE m2.video_id = metrics.video_id
           )"""
    ).fetchone()
    conn.close()

    channel_avg_ctr = avg_row["avg_ctr"] if avg_row and avg_row["avg_ctr"] else 0

    # Check threshold
    threshold = config.get("thumbnail_ab", {}).get("replace_if_ctr_below_pct", 0.8)
    min_impressions = config.get("thumbnail_ab", {}).get("min_impressions_before_replace", 100)

    should_replace = (
        channel_avg_ctr > 0
        and current_ctr < channel_avg_ctr * threshold
        and metrics.get("impressions", 0) >= min_impressions
    )

    result = {
        "current_ctr": current_ctr,
        "channel_avg_ctr": channel_avg_ctr,
        "should_replace": should_replace,
        "replacement_variant": None,
    }

    if should_replace:
        # Find the next unused variant
        variants = get_thumbnail_variants(video_db_id)
        for v in variants:
            if not v["is_active"] and os.path.exists(v["file_path"]):
                result["replacement_variant"] = v
                break

    return result


def run_thumbnail_optimization(config: dict):
    """Batch job: evaluate and replace underperforming thumbnails.

    Runs for all videos uploaded 3-7 days ago.
    Called from --optimize-thumbnails CLI.
    """
    print("\n[Thumbnail A/B] Evaluating thumbnail performance...")

    min_hours = config.get("thumbnail_ab", {}).get("min_hours_before_replace", 72)
    cutoff_start = (datetime.now() - timedelta(days=7)).isoformat()
    cutoff_end = (datetime.now() - timedelta(hours=min_hours)).isoformat()

    conn = get_connection()
    videos = conn.execute(
        """SELECT id, video_id, title FROM videos
           WHERE upload_date BETWEEN ? AND ?
           AND video_id IS NOT NULL""",
        (cutoff_start, cutoff_end)
    ).fetchall()
    conn.close()

    if not videos:
        print("  No videos in the evaluation window (3-7 days old).")
        return

    replaced = 0
    for video in videos:
        evaluation = evaluate_thumbnails(config, video["id"])

        if evaluation["should_replace"] and evaluation["replacement_variant"]:
            variant = evaluation["replacement_variant"]
            print(f"  Replacing thumbnail for '{video['title']}' "
                  f"(CTR: {evaluation['current_ctr']:.4f} < avg: {evaluation['channel_avg_ctr']:.4f})")

            success = replace_thumbnail(config, video["video_id"], variant["file_path"])
            if success:
                activate_thumbnail_variant(
                    variant["id"],
                    ctr_at_activation=evaluation["current_ctr"]
                )
                replaced += 1

    print(f"\n  Thumbnail optimization complete: {replaced}/{len(videos)} thumbnails replaced.")
