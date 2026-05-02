import json
import os
import random as _random
from openai import OpenAI


# ── Template libraries (imported by poem_agent and lullaby_agent) ─────────────

POEM_TEMPLATES = {
    "animal_rhymes":   ["The Dancing Bear", "Elephant's Big Adventure", "Bunny's Garden Day", "The Clever Fox"],
    "nature":          ["Seasons Change", "Rainbow After Rain", "The Busy Bee", "Little Raindrop"],
    "counting_rhymes": ["Ten Little Fireflies", "Five Colorful Balloons", "One to Twenty Adventure"],
    "alphabet_poems":  ["A is for Apple", "Letters All Around Us", "ABC Journey"],
    "bedtime_verse":   ["Goodnight Moon and Stars", "The Sleepy Forest Friends", "Dreams of Tomorrow"],
    "science":         ["The Tiny Seed", "Why the Sky is Blue", "Planets in a Row"],
    "food":            ["The Fruit Rainbow", "Vegetables All Around", "Yummy in My Tummy"],
}

LULLABY_TEMPLATES = {
    "goodnight_themes":      ["Goodnight Little One", "Sleep Sweet Child", "Tomorrow's New Day"],
    "star_and_moon_themes":  ["Moonlight Lullaby", "Stars Watch Over You", "Twinkle Twinkle Little Star"],
    "gentle_animal_friends": ["The Sleepy Kitten", "Owl's Nighttime Song", "Bear's Cozy Cave"],
    "dreamland_journeys":    ["Sailing to Dreamland", "The Dream Train", "Cloud Castle Dreams"],
}


def _load_character(config: dict) -> dict | None:
    """Load a character reference sheet based on config.content.character.

    Returns the character dict, or None if use_characters is disabled or the
    character file is missing. If character is "random", picks one at random.
    """
    content_cfg = config.get("content", {})
    if not content_cfg.get("use_characters", False):
        return None
    character_id = content_cfg.get("character", "")
    if not character_id:
        return None

    # Support "random" — pick any character from data/characters/
    if character_id == "random":
        chars_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "characters")
        try:
            candidates = [
                d for d in os.listdir(chars_dir)
                if os.path.isdir(os.path.join(chars_dir, d))
            ]
            if not candidates:
                return None
            character_id = _random.choice(candidates)
        except FileNotFoundError:
            return None

    ref_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "characters", character_id, "reference_sheet.json"
    )
    try:
        with open(ref_path) as f:
            char = json.load(f)
        char["id"] = character_id
        return char
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _get_brand_voice_instructions(config: dict) -> str:
    """Build brand voice instructions from config if enabled."""
    brand = config.get("brand_voice", {})
    if not brand.get("enabled", False):
        return ""

    parts = ["\nBRAND VOICE GUIDELINES:"]
    if brand.get("tone"):
        parts.append(f"- Tone: {brand['tone']}")
    if brand.get("catchphrases"):
        phrases = ", ".join(f'"{p}"' for p in brand["catchphrases"])
        parts.append(f"- Naturally incorporate catchphrases like: {phrases}")
    if brand.get("vocabulary_level"):
        parts.append(f"- Vocabulary level: {brand['vocabulary_level']}")
    return "\n".join(parts)


def generate_script(config: dict, topic_data: dict, language: str = "English",
                    fact_sheet: dict | None = None,
                    rewrite_suggestions: list[str] | None = None) -> dict:
    """Generate a scene-by-scene script for a tech-explainer video.

    Args:
        config: Pipeline config dict.
        topic_data: Topic dict from topic_agent.
        language: Language name ("Hindi" triggers Hinglish mode).
        fact_sheet: Optional research fact sheet from research_agent.
        rewrite_suggestions: Optional list of suggestions from quality_agent retry.
    """
    client = OpenAI(api_key=config["openai"]["api_key"])
    num_scenes = config["content"]["scenes_per_video"]
    duration = config["content"]["video_duration_minutes"]

    lang_instruction = ""
    if language == "Hindi":
        lang_instruction = """
IMPORTANT LANGUAGE RULES — HINGLISH (tech-explainer tone):
- Write narration in HINGLISH — 60-70% English with 30-40% Hindi words mixed in naturally
- Sound like an educated urban Indian explaining tech to a friend over chai
- Hindi words to use naturally: "samjho", "matlab", "aur sabse interesting baat", "dekho", "pata hai", "basically"
- GOOD: "Toh samjho, jab aap UPI se paise bhejte ho, toh pehle ek encrypted request jaati hai NPCI ke server ko."
- GOOD: "Aur sabse interesting baat? Ye sab real-time hota hai — matlab T+0 settlement!"
- BAD: "Aaj hum jaanenge UPI ke baare mein" (too formal, sounds like a textbook)
- BAD: Pure English with zero Hindi (this is a Hinglish channel)
- Write the "title" in Hinglish too
- Keep "visual_description" in ENGLISH (used for AI image generation)
- Tone: curious, informed, slightly amazed — NOT childish, NOT lecturing"""

    brand_voice = _get_brand_voice_instructions(config)

    # Fact sheet integration — the key v2 differentiator
    fact_sheet_section = ""
    if fact_sheet:
        key_facts = json.dumps(fact_sheet.get("key_facts", [])[:8], indent=2, ensure_ascii=False)
        narrative_arc = json.dumps(fact_sheet.get("narrative_arc", {}), indent=2, ensure_ascii=False)
        terms = json.dumps(fact_sheet.get("technical_terms", [])[:5], indent=2, ensure_ascii=False)
        misconceptions = json.dumps(fact_sheet.get("common_misconceptions", []), indent=2, ensure_ascii=False)
        credibility = ", ".join(fact_sheet.get("credibility_signals", []))

        fact_sheet_section = f"""
RESEARCH FACT SHEET (use these verified facts in the script):

KEY FACTS:
{key_facts}

NARRATIVE ARC (follow this structure):
{narrative_arc}

TECHNICAL TERMS (explain these naturally in the narration):
{terms}

COMMON MISCONCEPTIONS (address at least one):
{misconceptions}

CREDIBILITY SIGNALS (mention naturally): {credibility}

IMPORTANT: Every factual claim in your script MUST come from the fact sheet above.
Do NOT make up statistics or facts not in the research."""

    # Rewrite suggestions from quality_agent retry
    rewrite_section = ""
    if rewrite_suggestions:
        suggestions_text = "\n".join(f"  - {s}" for s in rewrite_suggestions)
        rewrite_section = f"""
REWRITE INSTRUCTIONS (this is a retry — fix these issues from the previous attempt):
{suggestions_text}
"""

    # Retention optimization
    retention_prompt = ""
    try:
        from services.retention_service import get_retention_structure_prompt
        retention_prompt = get_retention_structure_prompt("video", duration * 60)
    except Exception:
        pass

    # Series continuity context
    series_context = ""
    if topic_data.get("series_name"):
        ep_num = topic_data.get("episode_number", 1)
        series_name = topic_data["series_name"]
        continuity = topic_data.get("continuity_notes", "")
        series_context = f"""
SERIES CONTEXT:
This is Episode {ep_num} of the series "{series_name}".
{f'Series description: {topic_data.get("series_description", "")}' if topic_data.get("series_description") else ""}
{f'Continuity notes: {continuity}' if continuity else ""}
- Mention the series name and episode number naturally in the intro
- If this is Episode 2+, briefly reference what was covered before
- End with a teaser for the next episode in the series
"""

    prompt = f"""Write a YouTube tech-explainer video script in Hinglish.

Topic: {topic_data["topic"]}
Description: {topic_data.get("description", "")}
Target duration: {duration} minutes
Number of scenes: {num_scenes}
{lang_instruction}
{brand_voice}
{fact_sheet_section}
{rewrite_section}
{series_context}
{retention_prompt}
STRUCTURE REQUIREMENTS:
- HOOK (first 8 seconds): Open with a surprising fact, counterintuitive claim, or question that creates an information gap. Must be topic-specific, NOT generic.
- NARRATIVE ARC: Follow problem → mechanism → resolution. Each scene builds on the previous one.
- SPECIFICITY: Use concrete numbers, names, dates from the fact sheet. No vague filler like "bahut important hai."
- Each scene narration should be 3-5 sentences for long-form depth
- End with a satisfying "aha moment" or resolution, not a generic sign-off
- visual_description should describe diagrams, system flows, or abstract tech concepts — NOT cartoon characters

Respond in this exact JSON format:
{{
    "title": "Hinglish video title",
    "intro_hook": "8-second hook with specific fact/question",
    "scenes": [
        {{
            "scene_number": 1,
            "visual_description": "describe diagram/infographic/system flow IN ENGLISH",
            "narration": "the Hinglish voiceover text for this scene"
        }}
    ],
    "outro": "closing line with a thought-provoking takeaway"
}}

Only return the JSON, nothing else."""

    system_msg = (
        "You write engaging Hinglish tech-explainer scripts for YouTube. "
        "Tone: curious, informed, slightly amazed — like a smart friend explaining how something works. "
        "Always respond with valid JSON only. Keep visual_description in English."
    )

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=3000,
    )

    script_data = json.loads(response.choices[0].message.content.strip())
    return script_data


def translate_script(config: dict, en_script: dict, language: str) -> dict:
    """Translate an English script to another language, keeping scene order and visuals intact.

    This ensures the translated narration matches the same images (generated from English
    visual_description) scene-by-scene, preventing audio-image desync.
    """
    client = OpenAI(api_key=config["openai"]["api_key"])
    brand_voice = _get_brand_voice_instructions(config)

    scenes_json = json.dumps(en_script["scenes"], indent=2, ensure_ascii=False)

    lang_instruction = ""
    if language == "Hindi":
        lang_instruction = """TARGET LANGUAGE: HINGLISH (casual Hindi-English mix, mostly English with Hindi flavor)

CRITICAL HINGLISH RULES:
- Keep ALL greetings, intros, and exclamations in ENGLISH: "Hey there little explorers!", "Oh my goodness!", "That's SO cool!", "Can you believe it?!"
- NEVER translate greetings into pure Hindi (NO "wahh", NO "chhote", NO "namaste bacchon")
- Use 60-70% ENGLISH words with 30-40% Hindi words sprinkled in naturally
- Hindi words to use: "bacchon" (kids), "bahut" (very), "chalo" (let's go), "dekho" (look), "pata hai" (you know), "kitna" (how much), "duniya" (world), "sabse" (most)
- GOOD examples:
  - "Hey there little explorers! Aaj hum discover karenge some AMAZING fruit facts!"
  - "Can you believe it?! Strawberries mein actually 200 seeds hote hain! That's SO cool, right?"
  - "Wow friends! Yeh toh bahut interesting hai! Let's find out more!"
  - "Chalo guys, let's jump into today's super fun adventure!"
- BAD examples (DO NOT write like this):
  - "Hey wahh chhote explorers!" (sounds awkward and unnatural)
  - "Aaj hum phal ke tathyon ke baare mein jaanenge" (too formal Hindi)
- Keep it sounding like a fun Indian YouTuber who naturally speaks English with Hindi mixed in"""
    else:
        lang_instruction = f"TARGET LANGUAGE: {language}\nUse simple {language} that kids can understand."

    prompt = f"""Translate this kids' YouTube video script.

{lang_instruction}
{brand_voice}

ORIGINAL ENGLISH SCRIPT:
Title: {en_script["title"]}
Intro hook: {en_script["intro_hook"]}
Scenes: {scenes_json}
Outro: {en_script["outro"]}

RULES:
- Translate the "title", "intro_hook", each scene's "narration", and "outro"
- Keep EVERY "visual_description" EXACTLY the same in English (do NOT translate these — they are used for image generation)
- Keep the EXACT SAME number of scenes in the EXACT SAME order
- Keep the same scene_number values
- Make the translation feel natural, not word-for-word — adapt jokes and expressions
- Keep the same enthusiastic, fun energy as the original
- Write narration in a CONVERSATIONAL tone — like a fun storyteller SPEAKING, not reading
- For Hinglish: keep greetings and exclamations in English, only mix Hindi for connecting words and some nouns

Respond in this exact JSON format:
{{
    "title": "translated title",
    "intro_hook": "translated hook",
    "scenes": [
        {{
            "scene_number": 1,
            "visual_description": "KEEP ORIGINAL ENGLISH visual_description UNCHANGED",
            "narration": "translated narration"
        }}
    ],
    "outro": "translated outro"
}}

Only return JSON, nothing else."""

    system_msg = "You translate kids' video scripts while keeping them fun and engaging. Always respond with valid JSON only."
    if language == "Hindi":
        system_msg += " Translate to Hinglish (casual Hindi-English mix). Keep visual_description in English unchanged."
    else:
        system_msg += f" Translate to {language}. Keep visual_description in English unchanged."

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=2000,
    )

    translated = json.loads(response.choices[0].message.content.strip())

    # Safety: ensure visual_descriptions are preserved from original
    for i, scene in enumerate(translated.get("scenes", [])):
        if i < len(en_script["scenes"]):
            scene["visual_description"] = en_script["scenes"][i]["visual_description"]

    # Preserve character_id so image generation stays consistent across languages
    if "character_id" in en_script:
        translated["character_id"] = en_script["character_id"]

    return translated


def generate_shorts_script(config: dict, topic_data: dict, script_data: dict,
                           language: str = "English") -> dict:
    """Generate a re-hooked, punchier script optimized for YouTube Shorts."""
    client = OpenAI(api_key=config["openai"]["api_key"])

    scenes_json = json.dumps(script_data["scenes"], indent=2, ensure_ascii=False)
    brand_voice = _get_brand_voice_instructions(config)

    lang_instruction = ""
    if language == "Hindi":
        lang_instruction = """
Write the intro_hook, narration, and outro in HINGLISH (casual Hindi-English mix).
Use the same fun, energetic Hinglish tone as the original script.
Keep visual_description in English."""
    elif language != "English":
        lang_instruction = f"""
Write the intro_hook, narration, and outro in {language}.
Keep visual_description in English."""

    # Get configurable shorts settings
    target_scenes = config.get("shorts", {}).get("target_scenes", 3)
    max_duration = config.get("shorts", {}).get("max_duration", 59)

    # Retention optimization for shorts
    shorts_retention = ""
    try:
        from services.retention_service import get_retention_structure_prompt
        shorts_retention = get_retention_structure_prompt("shorts", max_duration)
    except Exception:
        pass

    prompt = f"""You are optimizing a kids' video script for YouTube Shorts (vertical, max {max_duration} seconds).
{shorts_retention}
ORIGINAL FULL SCRIPT:
Title: {script_data["title"]}
Hook: {script_data["intro_hook"]}
Scenes: {scenes_json}
Outro: {script_data["outro"]}
{lang_instruction}
{brand_voice}
YOUR TASK:
1. Write a NEW, punchier intro_hook (max 10 words) that grabs attention in 2 seconds
   - Use a surprising question, bold claim, or "Did you know..." format
2. Pick the {target_scenes} BEST scenes from the original (most visually interesting + engaging facts)
3. Make each scene narration appropriate length (1-3 sentences)
   - Target ~{max_duration // target_scenes} seconds per scene for total ~{max_duration}s
4. Write a short outro (1 sentence, call to action)

Respond in this exact JSON format:
{{
    "title": "{script_data["title"]}",
    "intro_hook": "NEW punchy hook",
    "scenes": [
        {{
            "scene_number": 1,
            "visual_description": "keep original visual_description IN ENGLISH",
            "narration": "shorter, punchier narration"
        }}
    ],
    "outro": "short CTA"
}}

Only return JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You optimize video scripts for short-form content. Maximum engagement in minimum time. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=1000,
    )

    shorts_script = json.loads(response.choices[0].message.content.strip())
    return shorts_script
