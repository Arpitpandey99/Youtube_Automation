"""
lullaby_agent.py — Soothing Hinglish lullaby script generation for bedtime (ages 3-8).

Generates lullabies with:
  - 4 scenes (verse-chorus-verse-chorus)
  - Calming, repetitive phrases
  - Soft Hindi words: sona, chanda, tara, neend, pyar
  - Slow narration rate (used by generate_lullaby_voiceover in asset_agent)
  - Pastel, moonlit visual descriptions
"""
import json
import random
from openai import OpenAI

from agents.script_agent import LULLABY_TEMPLATES


def generate_lullaby_script(config: dict, topic_data: dict) -> dict:
    """Generate a soothing Hinglish lullaby script (4 scenes) for bedtime kids content.

    Returns the standard scenes[] dict compatible with all downstream agents.
    Designed to be used with generate_lullaby_voiceover() (rate=-10%) for a
    slow, calming narration pace.
    """
    client = OpenAI(api_key=config["openai"]["api_key"])

    theme_key = random.choice(list(LULLABY_TEMPLATES.keys()))
    theme_title = random.choice(LULLABY_TEMPLATES[theme_key])
    target_age = topic_data.get("target_age", "3-8")

    prompt = f"""Write a soothing Hinglish lullaby for bedtime, for kids aged {target_age}.

Inspired theme: {theme_title}
Topic hint: {topic_data['topic']}

STRUCTURE (exactly 4 scenes, gentle and repetitive):
  Scene 1: Opening verse — set the peaceful scene (stars, moon, cozy room)
  Scene 2: Chorus — 4 short, repetitive, soothing lines. This is the lullaby refrain.
  Scene 3: Second verse — a gentle story or reassurance (animals sleeping, dreams)
  Scene 4: Chorus — repeat same chorus lines as Scene 2

HINGLISH LULLABY RULES:
- Soft Hindi words: "sona" (sleep/gold), "chanda" (moon), "tara" (star), "neend" (sleep),
  "pyar" (love), "aa jao" (come), "so jao" (go to sleep), "mamma" (mother)
- English should be warm, reassuring: "Close your eyes", "Dream sweet dreams",
  "I am right here", "Sleep tight little one"
- GOOD: "Chanda mama aa gaye / Tum so jao pyare / Stars are twinkling up above / Wrapped in moonlight and love"
- Rhythm: slow, gentle, 3-4 words per line maximum. Not fast-paced.
- Each verse/chorus: exactly 4 lines, gentle rhyme (AABB or ABAB)
- End with warmth and love — feeling safe

VISUAL DESCRIPTIONS:
- Soft pastels only: lavender, soft blue, pale pink, gentle gold moonlight
- Scenes: moonlit bedroom, sleepy animals, twinkling stars, cozy blanket
- Always calm, no bright colors, no busy scenes

Respond in this EXACT JSON format (exactly 4 scenes):
{{
    "title": "lullaby title",
    "lullaby_theme": "{theme_key}",
    "intro_hook": "one soft, gentle opening line (e.g. 'Shh... it is time to sleep, little one.')",
    "scenes": [
        {{
            "scene_number": 1,
            "visual_description": "soft, dreamy visual IN ENGLISH — pastel colors, calm moonlit scene",
            "narration": "the 4 lullaby lines for this scene"
        }}
    ],
    "outro": "final gentle goodnight line (e.g. 'Goodnight, sweet dreams, we love you so.')"
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {
                "role": "system",
                "content": (
                    "You write soothing children's lullabies with a calm, loving Hinglish blend. "
                    "Slow rhythm, repetitive phrases, warm imagery. Always respond with valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
        max_tokens=1500,
    )

    return json.loads(response.choices[0].message.content.strip())
