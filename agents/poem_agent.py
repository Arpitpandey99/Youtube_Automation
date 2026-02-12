"""
poem_agent.py — Hinglish rhyming poem script generation for kids (ages 3-8).

Generates structured poems with:
  - AABB / ABAB / ABCB rhyme schemes
  - 6 scenes (4 verses + 2 chorus repetitions)
  - lines[] field per scene for read-along text overlay
  - visual_description in English for image generation
  - narration as full verse text for TTS
"""
import json
import random
from openai import OpenAI

from agents.script_agent import POEM_TEMPLATES

RHYME_SCHEMES = ["AABB", "ABAB", "ABCB"]


def generate_poem_script(config: dict, topic_data: dict) -> dict:
    """Generate a Hinglish rhyming poem script (6 scenes) for kids.

    Returns the standard scenes[] dict compatible with all downstream agents
    (generate_images, animate_all_scenes, generate_voiceover_only, upload_video).
    Each scene also carries a 'lines[]' list for read-along text overlay in
    assemble_poem_video().
    """
    client = OpenAI(api_key=config["openai"]["api_key"])
    rhyme_scheme = random.choice(RHYME_SCHEMES)

    # Pick a template category closest to the topic category
    category = topic_data.get("category", "nature")
    template_list = POEM_TEMPLATES.get(category, POEM_TEMPLATES["nature"])
    poem_theme = random.choice(template_list)

    target_age = topic_data.get("target_age", "3-8")

    prompt = f"""Write a Hinglish children's poem for kids aged {target_age}.

Topic: {topic_data['topic']}
Description: {topic_data.get('description', '')}
Inspired theme: {poem_theme}
Rhyme scheme: {rhyme_scheme}

STRUCTURE (exactly 6 scenes):
  Scene 1: Verse 1 — introduce the topic/character
  Scene 2: Verse 2 — explore / build the story
  Scene 3: Chorus — catchy 4-line repeatable section
  Scene 4: Verse 3 — climax or surprising fact
  Scene 5: Verse 4 — resolution or happy ending
  Scene 6: Chorus — repeat chorus (same lines as Scene 3)

Each verse/chorus = exactly 4 lines, rhyming according to {rhyme_scheme}.

HINGLISH RULES (60% English + 40% Hindi naturally mixed):
- Exclamations/greetings in English: "Oh wow!", "Come let's see!", "Isn't that fun!"
- Hindi words to sprinkle: "chalo", "dekho", "sunlo", "bahut", "pyara", "duniya", "sona", "kitna"
- GOOD: "Little bee, little bee, kahan ja rahi ho? / Flying through flowers, khushiyan leke aao!"
- BAD: Pure formal Hindi or pure English — must feel like a fun Indian kids' rhyme
- Simple vocabulary, fun rhythm, kids aged {target_age}

IMAGE STYLE: "visual_description" should describe soft pastel, watercolor, cartoon imagery — no text in image.

Respond in this EXACT JSON format (6 scenes):
{{
    "title": "poem title in Hinglish",
    "poem_type": "animal_rhymes",
    "rhyme_scheme": "{rhyme_scheme}",
    "intro_hook": "one warm invitation line to start (e.g. 'Chalo bacchon, sun lo ek pyari si poem!')",
    "scenes": [
        {{
            "scene_number": 1,
            "verse_type": "verse",
            "visual_description": "describe scene image IN ENGLISH for AI image generation",
            "lines": ["Line 1", "Line 2", "Line 3", "Line 4"],
            "narration": "Line 1 Line 2 Line 3 Line 4"
        }}
    ],
    "outro": "one warm closing line"
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a children's Hinglish poet. Write musical, rhyming poems "
                    "with a natural Indian-English blend. Always respond with valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=2000,
    )

    poem_data = json.loads(response.choices[0].message.content.strip())

    # Ensure narration is always set (join lines if missing)
    for scene in poem_data.get("scenes", []):
        if not scene.get("narration") and scene.get("lines"):
            scene["narration"] = " ".join(scene["lines"])

    return poem_data
