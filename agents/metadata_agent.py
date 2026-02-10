import json
import os
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont


def generate_metadata(config: dict, topic_data: dict, script_data: dict,
                      language: str = "English") -> dict:
    """Generate YouTube metadata (title, description, tags) using GPT."""
    client = OpenAI(api_key=config["openai"]["api_key"])

    lang_instruction = ""
    if language != "English":
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
    if language != "English":
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


def generate_thumbnail(config: dict, metadata: dict, first_image_path: str, output_dir: str) -> str:
    """Generate a YouTube thumbnail from the first scene image."""
    img = Image.open(first_image_path).resize((1280, 720), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    text = metadata["thumbnail_text"].upper()

    # Try to use a bold font, fall back to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 90)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("arial.ttf", 90)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center text position
    x = (1280 - text_width) // 2
    y = (720 - text_height) // 2

    # Draw background rectangle
    padding = 20
    draw.rectangle(
        [x - padding, y - padding, x + text_width + padding, y + text_height + padding],
        fill=(255, 50, 50, 200),
    )

    # Draw text with outline
    outline_color = "black"
    for dx in [-3, 0, 3]:
        for dy in [-3, 0, 3]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill="white")

    # Add colorful border
    border_width = 8
    for i in range(border_width):
        color = (255, 255, 0) if i % 2 == 0 else (255, 50, 50)
        draw.rectangle([i, i, 1279 - i, 719 - i], outline=color)

    thumbnail_path = os.path.join(output_dir, "thumbnail.png")
    img.save(thumbnail_path, quality=95)
    return thumbnail_path
