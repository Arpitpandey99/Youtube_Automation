import json
import os
from openai import OpenAI

from agents.analytics_agent import get_performance_hints


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "topics_history.json")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def generate_topic(config: dict) -> dict:
    """Generate a unique kid-friendly video topic, informed by past performance."""
    client = OpenAI(api_key=config["openai"]["api_key"])
    history = load_history()
    past_topics = [h["topic"] for h in history[-50:]]

    niche = config["content"]["niche"]
    target_age = config["content"]["target_age"]

    # Get performance hints if analytics is enabled
    perf_hints = get_performance_hints(config)
    perf_section = f"\n\nPERFORMANCE DATA:\n{perf_hints}\nUse these insights to pick a topic likely to perform well." if perf_hints else ""

    prompt = f"""Generate 1 unique YouTube video topic for kids aged {target_age}.
Niche: {niche}

The topic must NOT be any of these previously used topics:
{json.dumps(past_topics, indent=2) if past_topics else "None yet"}
{perf_section}
Respond in this exact JSON format:
{{
    "topic": "the video topic title",
    "category": "e.g. animals, science, space, nature, history, alphabet, numbers",
    "target_age": "{target_age}",
    "description": "one line description of what the video will cover"
}}

Only return the JSON, nothing else."""

    response = client.chat.completions.create(
        model=config["openai"]["model"],
        messages=[
            {"role": "system", "content": "You create engaging, educational, kid-friendly YouTube video topics. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=200,
    )

    topic_data = json.loads(response.choices[0].message.content.strip())

    # Save to history
    history.append(topic_data)
    save_history(history)

    return topic_data
