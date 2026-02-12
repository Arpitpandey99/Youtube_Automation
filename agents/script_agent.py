import json
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


def generate_script(config: dict, topic_data: dict, language: str = "English") -> dict:
    """Generate a scene-by-scene script for the video in the specified language."""
    client = OpenAI(api_key=config["openai"]["api_key"])
    num_scenes = config["content"]["scenes_per_video"]
    duration = config["content"]["video_duration_minutes"]
    target_age = topic_data["target_age"]

    lang_instruction = ""
    if language == "Hindi":
        lang_instruction = """
IMPORTANT LANGUAGE RULES — HINGLISH (mostly English with Hindi flavor):
- Write narration in HINGLISH — 60-70% English with 30-40% Hindi words mixed in naturally
- Keep ALL greetings and exclamations in ENGLISH: "Hey there little explorers!", "Oh my goodness!", "That's SO cool!"
- NEVER translate greetings to pure Hindi (NO "wahh", NO "chhote", NO formal Hindi intros)
- Hindi words to sprinkle in: "bacchon", "bahut", "chalo", "dekho", "pata hai", "kitna", "duniya", "sabse"
- GOOD: "Hey there little explorers! Aaj hum discover karenge some AMAZING facts!"
- GOOD: "Can you believe it?! Yeh toh bahut interesting hai!"
- GOOD: "Chalo guys, let's jump into today's super fun adventure!"
- BAD: "Hey wahh chhote explorers!" (awkward, unnatural)
- BAD: "Aaj hum janenge phalon ke baare mein" (too formal Hindi)
- Write the "title" in Hinglish too
- Keep "visual_description" in ENGLISH (it is used for image generation)
- Sound like a fun Indian YouTuber who naturally speaks English with Hindi mixed in"""
    elif language != "English":
        lang_instruction = f"""
IMPORTANT LANGUAGE RULES:
- Write ALL narration text (intro_hook, narration, outro) in {language} language.
- Write the "title" in {language} language.
- Keep "visual_description" in ENGLISH (it is used for image generation).
- Use simple {language} that kids can understand."""

    brand_voice = _get_brand_voice_instructions(config)

    prompt = f"""Write a YouTube video script for kids aged {target_age}.

Topic: {topic_data["topic"]}
Description: {topic_data["description"]}
Target duration: {duration} minutes
Number of scenes: {num_scenes}
{lang_instruction}
{brand_voice}
Rules:
- Use simple, fun, engaging language for kids
- Each scene narration should be 2-4 sentences
- Include fun facts or questions to keep kids engaged
- NO scary or inappropriate content
- Start with an exciting hook
- Write narration in a CONVERSATIONAL, ENTHUSIASTIC tone — like an excited friend telling a cool story
- Use exclamation marks, rhetorical questions ("Can you believe that?!", "Isn't that amazing?!"), and dramatic pauses ("And guess what...")
- Add emotional expressions: "Wow!", "Oh my goodness!", "That's SO cool!", "Whoa!"
- Vary sentence length — mix short punchy sentences with slightly longer ones for natural rhythm
- Avoid formal or robotic phrasing — write the way a fun, energetic storyteller would SPEAK, not write

Respond in this exact JSON format:
{{
    "title": "video title",
    "intro_hook": "an exciting 1-sentence opening hook",
    "scenes": [
        {{
            "scene_number": 1,
            "visual_description": "describe what should be shown visually IN ENGLISH (for image generation)",
            "narration": "the voiceover text for this scene"
        }}
    ],
    "outro": "a fun closing line encouraging kids to like and subscribe"
}}

Only return the JSON, nothing else."""

    system_msg = "You write engaging, educational scripts for kids' YouTube videos. Always respond with valid JSON only. Keep language simple and fun."
    if language == "Hindi":
        system_msg += " Write narration in Hinglish (casual Hindi-English mix, the way Indian kids actually speak). Keep visual_description in English."
    elif language != "English":
        system_msg += f" Write narration in {language}. Keep visual_description in English."

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=2000,
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

    prompt = f"""You are optimizing a kids' video script for YouTube Shorts (vertical, max 55 seconds).

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
2. Pick the 3 BEST scenes from the original (most visually interesting + engaging facts)
3. Make each scene narration shorter (1-2 sentences max, punchy and fast-paced)
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
