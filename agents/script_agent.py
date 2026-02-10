import json
from openai import OpenAI


def generate_script(config: dict, topic_data: dict, language: str = "English") -> dict:
    """Generate a scene-by-scene script for the video in the specified language."""
    client = OpenAI(api_key=config["openai"]["api_key"])
    num_scenes = config["content"]["scenes_per_video"]
    duration = config["content"]["video_duration_minutes"]
    target_age = topic_data["target_age"]

    lang_instruction = ""
    if language != "English":
        lang_instruction = f"""
IMPORTANT LANGUAGE RULES:
- Write ALL narration text (intro_hook, narration, outro) in {language} language.
- Write the "title" in {language} language.
- Keep "visual_description" in ENGLISH (it is used for image generation).
- Use simple {language} that kids can understand."""

    prompt = f"""Write a YouTube video script for kids aged {target_age}.

Topic: {topic_data["topic"]}
Description: {topic_data["description"]}
Target duration: {duration} minutes
Number of scenes: {num_scenes}
{lang_instruction}
Rules:
- Use simple, fun, engaging language for kids
- Each scene narration should be 2-4 sentences
- Include fun facts or questions to keep kids engaged
- NO scary or inappropriate content
- Start with an exciting hook

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

    system_msg = f"You write engaging, educational scripts for kids' YouTube videos. Always respond with valid JSON only. Keep language simple and fun."
    if language != "English":
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
