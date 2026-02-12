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
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype("arial.ttf", size)
        except (OSError, IOError):
            return ImageFont.load_default()


def _draw_thumbnail_text(draw: ImageDraw.Draw, text: str, font, img_width: int, img_height: int):
    """Draw centered text with background and outline on a thumbnail."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (img_width - text_width) // 2
    y = (img_height - text_height) // 2

    # Draw background rectangle
    padding = 20
    draw.rectangle(
        [x - padding, y - padding, x + text_width + padding, y + text_height + padding],
        fill=(255, 50, 50, 200),
    )

    # Draw text with outline
    for dx in [-3, 0, 3]:
        for dy in [-3, 0, 3]:
            draw.text((x + dx, y + dy), text, font=font, fill="black")
    draw.text((x, y), text, font=font, fill="white")


def _draw_border(draw: ImageDraw.Draw, width: int, height: int, border_width: int = 8):
    """Draw alternating yellow/red border."""
    for i in range(border_width):
        color = (255, 255, 0) if i % 2 == 0 else (255, 50, 50)
        draw.rectangle([i, i, width - 1 - i, height - 1 - i], outline=color)


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


def generate_thumbnail(config: dict, metadata: dict, first_image_path: str, output_dir: str) -> str:
    """Generate a YouTube thumbnail (1280x720) from the first scene image."""
    return generate_youtube_thumbnail(config, metadata, first_image_path, output_dir)


def generate_youtube_thumbnail(config: dict, metadata: dict, first_image_path: str,
                               output_dir: str) -> str:
    """Generate a horizontal YouTube thumbnail (1280x720)."""
    img = Image.open(first_image_path).resize((1280, 720), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(90)

    _draw_thumbnail_text(draw, text, font, 1280, 720)
    _draw_border(draw, 1280, 720)

    thumbnail_path = os.path.join(output_dir, "thumbnail.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path


def generate_instagram_thumbnail(config: dict, metadata: dict, first_image_path: str,
                                 output_dir: str) -> str:
    """Generate a vertical Instagram thumbnail (1080x1920) with blurred background."""
    img = _prepare_vertical_thumbnail(first_image_path, 1080, 1920)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(72)

    _draw_thumbnail_text(draw, text, font, 1080, 1920)
    _draw_border(draw, 1080, 1920)

    thumbnail_path = os.path.join(output_dir, "thumbnail_ig.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path


def generate_shorts_thumbnail(config: dict, metadata: dict, first_image_path: str,
                              output_dir: str) -> str:
    """Generate a vertical Shorts thumbnail (1080x1920) with blurred background."""
    img = _prepare_vertical_thumbnail(first_image_path, 1080, 1920)

    draw = ImageDraw.Draw(img)
    text = metadata["thumbnail_text"].upper()
    font = _load_font(80)

    _draw_thumbnail_text(draw, text, font, 1080, 1920)
    _draw_border(draw, 1080, 1920, border_width=6)

    thumbnail_path = os.path.join(output_dir, "thumbnail_shorts.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path
