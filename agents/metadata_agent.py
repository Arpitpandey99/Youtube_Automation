import json
import os
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


def generate_metadata(config: dict, topic_data: dict, script_data: dict,
                      language: str = "English") -> dict:
    """Generate YouTube metadata (title, description, tags) using GPT."""
    client = OpenAI(api_key=config["openai"]["api_key"])

    lang_instruction = ""
    if language == "Hindi":
        lang_instruction = """
IMPORTANT: Write the title and description in HINGLISH (casual Hindi-English mix, how Indians actually speak).
Include both Hindi and English tags for better reach.
The thumbnail_text should be in Hinglish or English (whichever is catchier)."""
    elif language != "English":
        lang_instruction = f"""
IMPORTANT: Write the title and description in {language} language.
Include both {language} and English tags for better reach.
The thumbnail_text should be in {language}."""

    prompt = f"""Generate YouTube video metadata for a kids' video.

Topic: {topic_data["topic"]}
Category: {topic_data["category"]}
Target age: {topic_data["target_age"]}
Video title from script: {script_data["title"]}
{lang_instruction}
Generate:
1. An SEO-optimized, catchy title (max 70 chars, include emoji)
2. A description (include keywords, 3-4 sentences + hashtags)
3. Tags (30 relevant tags)
4. A short text to overlay on the thumbnail (max 4 words)

Respond in this exact JSON format:
{{
    "title": "the youtube title",
    "description": "the full description with hashtags",
    "tags": ["tag1", "tag2", "..."],
    "thumbnail_text": "SHORT TEXT"
}}

Only return JSON, nothing else."""

    system_msg = "You are a YouTube SEO expert for kids' channels. Always respond with valid JSON only."
    if language == "Hindi":
        system_msg += " Write title and description in Hinglish (casual Hindi-English mix)."
    elif language != "English":
        system_msg += f" Write title and description in {language}."

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=600,
    )

    metadata = json.loads(response.choices[0].message.content.strip())
    return metadata


def generate_instagram_metadata(config: dict, topic_data: dict, script_data: dict,
                                language: str = "English") -> dict:
    """Generate Instagram-specific metadata with trending hashtags and engaging caption."""
    client = OpenAI(api_key=config["openai"]["api_key"])

    lang_instruction = ""
    if language != "English":
        lang_instruction = f"Write the caption in {language} language but keep hashtags in English for maximum reach."

    prompt = f"""Generate Instagram Reel metadata for a kids' educational video.

Topic: {topic_data["topic"]}
Category: {topic_data["category"]}
Target age: {topic_data["target_age"]}
Video title: {script_data["title"]}
{lang_instruction}

Generate:
1. A short, catchy Instagram caption (2-3 lines, use emojis, include a call-to-action like "Follow for more!")
2. 25-30 trending and relevant Instagram hashtags (mix of popular and niche kids/education hashtags)

IMPORTANT hashtag rules:
- Include broad popular hashtags like #kidseducation #funfacts #learningisfun #kidsofinstagram
- Include niche hashtags related to the specific topic
- Include engagement hashtags like #explorepage #reels #viral #trending
- Include parenting hashtags like #momlife #parentingtips #kidsactivities
- All hashtags should be lowercase, no spaces

Respond in this exact JSON format:
{{
    "caption": "the engaging caption with emojis",
    "hashtags": ["hashtag1", "hashtag2", "..."]
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You are an Instagram growth expert for kids' educational content. Generate viral, engaging captions and trending hashtags. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=600,
    )

    ig_metadata = json.loads(response.choices[0].message.content.strip())
    return ig_metadata


def generate_shorts_metadata(metadata: dict) -> dict:
    """Generate metadata for the YouTube Shorts version of the video."""
    # Shorts title must include #Shorts for YouTube to recognize it
    title = metadata["title"]
    # Keep title under 100 chars with #Shorts appended
    max_title_len = 100 - len(" #Shorts")
    if len(title) > max_title_len:
        title = title[:max_title_len].rstrip()
    shorts_title = f"{title} #Shorts"

    shorts_desc = (
        f"{metadata['description']}\n\n"
        "#Shorts #YouTubeShorts"
    )

    return {
        "title": shorts_title,
        "description": shorts_desc,
        "tags": metadata.get("tags", []) + ["shorts", "youtube shorts"],
        "thumbnail_text": metadata.get("thumbnail_text", ""),
    }


def _load_font(size: int):
    """Try to load a bold font, fall back to default."""
    for path in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ── Content-type colour themes ─────────────────────────────────────────────
_THUMB_THEMES = {
    "lullaby": {
        "gradient": (70, 30, 130),
        "border1": (160, 120, 220),
        "border2": (200, 170, 255),
        "accent": (220, 200, 255),
    },
    "poem": {
        "gradient": (190, 50, 85),
        "border1": (255, 120, 160),
        "border2": (255, 200, 220),
        "accent": (255, 200, 220),
    },
    "video": {
        "gradient": (190, 90, 10),
        "border1": (255, 200, 0),
        "border2": (255, 140, 0),
        "accent": (255, 230, 100),
    },
}
_THUMB_THEMES["story"] = _THUMB_THEMES["video"]
_THUMB_THEMES["shorts"] = _THUMB_THEMES["video"]


def _apply_gradient_overlay(img: Image.Image, content_type: str) -> Image.Image:
    """Apply a semi-transparent gradient strip to the bottom 40% of the image."""
    theme = _THUMB_THEMES.get(content_type, _THUMB_THEMES["video"])
    base_color = theme["gradient"]
    w, h = img.size
    strip_h = int(h * 0.42)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(strip_h):
        alpha = int(195 * (y / strip_h))
        draw.line([(0, h - strip_h + y), (w, h - strip_h + y)], fill=(*base_color, alpha))

    img_rgba = img.convert("RGBA")
    result = Image.alpha_composite(img_rgba, overlay)
    return result.convert("RGB")


def _draw_text_with_shadow(draw: ImageDraw.Draw, text: str, font,
                            x: int, y: int, shadow_offset: int = 4):
    """Draw white text with a dark drop shadow for depth and readability."""
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(15, 15, 15))
    draw.text((x, y), text, font=font, fill="white")


def _draw_border_themed(draw: ImageDraw.Draw, width: int, height: int,
                         content_type: str, border_width: int = 8):
    """Draw a themed alternating-colour border based on content type."""
    theme = _THUMB_THEMES.get(content_type, _THUMB_THEMES["video"])
    for i in range(border_width):
        color = theme["border1"] if i % 2 == 0 else theme["border2"]
        draw.rectangle([i, i, width - 1 - i, height - 1 - i], outline=color)


def _draw_corner_accents(draw: ImageDraw.Draw, width: int, height: int,
                          content_type: str):
    """Draw small decorative accents in the four corners.

    - lullaby: filled circles (stars)
    - poem: diamond shapes (sparkles)
    - video/story: small square dots
    """
    theme = _THUMB_THEMES.get(content_type, _THUMB_THEMES["video"])
    color = theme["accent"]
    r, margin = 10, 22
    corners = [
        (margin, margin),
        (width - margin - r * 2, margin),
        (margin, height - margin - r * 2),
        (width - margin - r * 2, height - margin - r * 2),
    ]
    if content_type == "lullaby":
        for cx, cy in corners:
            draw.ellipse([cx, cy, cx + r * 2, cy + r * 2], fill=color)
    elif content_type == "poem":
        for cx, cy in corners:
            mid_x, mid_y = cx + r, cy + r
            draw.polygon(
                [(mid_x, cy), (cx + r * 2, mid_y), (mid_x, cy + r * 2), (cx, mid_y)],
                fill=color,
            )
    else:
        for cx, cy in corners:
            draw.rectangle([cx, cy, cx + r * 2, cy + r * 2], fill=color)


def _prepare_vertical_thumbnail(image_path: str, target_w: int = 1080, target_h: int = 1920) -> Image.Image:
    """Prepare a landscape image for vertical thumbnail with blurred background.

    Creates a blurred, darkened background and places the original image centered.
    No stretching or compression.
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Blurred background — stretched to fill (ok since it's blurred)
    bg = img.copy()
    bg = bg.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)

    # Foreground — fit to width, keep aspect ratio
    scale = target_w / w
    new_h = int(h * scale)
    fg = img.resize((target_w, new_h), Image.LANCZOS)

    # Center vertically
    y_offset = (target_h - new_h) // 2
    bg.paste(fg, (0, y_offset))

    return bg


def generate_thumbnail(config: dict, metadata: dict, first_image_path: str,
                       output_dir: str, content_type: str = "video") -> str:
    """Generate a YouTube thumbnail (1280x720) from the first scene image."""
    return generate_youtube_thumbnail(config, metadata, first_image_path, output_dir, content_type)


def generate_youtube_thumbnail(config: dict, metadata: dict, first_image_path: str,
                               output_dir: str, content_type: str = "video") -> str:
    """Generate a horizontal YouTube thumbnail (1280x720) with themed gradient overlay."""
    img = Image.open(first_image_path).resize((1280, 720), Image.LANCZOS)
    img = _apply_gradient_overlay(img, content_type)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(110)  # larger than before (was 90)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1280 - text_w) // 2
    y = int(720 * 0.62) - text_h // 2  # lower zone in the gradient strip

    _draw_text_with_shadow(draw, text, font, x, y)
    _draw_border_themed(draw, 1280, 720, content_type)
    _draw_corner_accents(draw, 1280, 720, content_type)

    thumbnail_path = os.path.join(output_dir, "thumbnail.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path


def generate_instagram_thumbnail(config: dict, metadata: dict, first_image_path: str,
                                 output_dir: str, content_type: str = "video") -> str:
    """Generate a vertical Instagram thumbnail (1080x1920) with themed gradient overlay."""
    img = _prepare_vertical_thumbnail(first_image_path, 1080, 1920)
    img = _apply_gradient_overlay(img, content_type)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(88)  # larger than before (was 72)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1080 - text_w) // 2
    y = int(1920 * 0.62) - text_h // 2

    _draw_text_with_shadow(draw, text, font, x, y)
    _draw_border_themed(draw, 1080, 1920, content_type)
    _draw_corner_accents(draw, 1080, 1920, content_type)

    thumbnail_path = os.path.join(output_dir, "thumbnail_ig.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path


def generate_shorts_thumbnail(config: dict, metadata: dict, first_image_path: str,
                              output_dir: str, content_type: str = "video") -> str:
    """Generate a vertical Shorts thumbnail (1080x1920) with themed gradient overlay."""
    img = _prepare_vertical_thumbnail(first_image_path, 1080, 1920)
    img = _apply_gradient_overlay(img, content_type)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(96)  # larger than before (was 80)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1080 - text_w) // 2
    y = int(1920 * 0.62) - text_h // 2

    _draw_text_with_shadow(draw, text, font, x, y)
    _draw_border_themed(draw, 1080, 1920, content_type, border_width=6)
    _draw_corner_accents(draw, 1080, 1920, content_type)

    thumbnail_path = os.path.join(output_dir, "thumbnail_shorts.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path
