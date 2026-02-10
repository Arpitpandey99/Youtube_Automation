import asyncio
import os
import random
import requests
import time

import edge_tts


def _sanitize_tts_text(text: str) -> str:
    """Remove/replace characters that break edge-tts."""
    replacements = {
        "\u2019": "'", "\u2018": "'",  # smart quotes
        "\u201c": '"', "\u201d": '"',  # smart double quotes
        "\u2013": "-", "\u2014": "-",  # en/em dashes
        "\u2026": "...",               # ellipsis
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def pick_voice(config: dict, lang_code: str) -> str:
    """Randomly pick a voice from the configured pool for the given language."""
    for lang in config["languages"]:
        if lang["code"] == lang_code:
            voice = random.choice(lang["voices"])
            print(f"  Selected voice: {voice}")
            return voice
    raise ValueError(f"No voices configured for language: {lang_code}")


def generate_voiceover(config: dict, script_data: dict, output_dir: str,
                       voice: str = None) -> list[str]:
    """Generate voiceover audio files for each scene using edge-tts."""
    if voice is None:
        voice = pick_voice(config, "en")
    audio_files = []

    # Combine intro hook with first scene, and outro with last scene
    texts = []
    for i, scene in enumerate(script_data["scenes"]):
        text = ""
        if i == 0:
            text = script_data["intro_hook"] + " " + scene["narration"]
        elif i == len(script_data["scenes"]) - 1:
            text = scene["narration"] + " " + script_data["outro"]
        else:
            text = scene["narration"]
        texts.append(_sanitize_tts_text(text))

    async def _generate_single(text: str, filepath: str):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    for i, text in enumerate(texts):
        filepath = os.path.join(output_dir, f"scene_{i+1}.mp3")
        asyncio.run(_generate_single(text, filepath))
        audio_files.append(filepath)

    return audio_files


def generate_images_replicate(config: dict, script_data: dict, output_dir: str) -> list[str]:
    """Generate scene images using Replicate API (Flux Schnell - fast & cheap)."""
    import replicate

    client = replicate.Client(api_token=config["replicate"]["api_token"])
    style = config["content"]["image_style"]
    model = config["replicate"]["model"]
    image_files = []

    for i, scene in enumerate(script_data["scenes"]):
        prompt = f"{style}, {scene['visual_description']}, high quality, no text, no words, no letters"

        for attempt in range(5):
            try:
                output = client.run(
                    model,
                    input={
                        "prompt": prompt,
                        "aspect_ratio": "16:9",
                        "num_outputs": 1,
                        "output_format": "png",
                    }
                )
                break
            except Exception as e:
                if attempt < 4:
                    wait = 15 * (attempt + 1)
                    print(f"    Retry {attempt+1}/4 ({type(e).__name__}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        # Download the image
        img_url = output[0] if isinstance(output, list) else output
        if hasattr(img_url, 'url'):
            img_url = img_url.url
        img_data = requests.get(str(img_url)).content
        filepath = os.path.join(output_dir, f"scene_{i+1}.png")
        with open(filepath, "wb") as f:
            f.write(img_data)
        image_files.append(filepath)
        print(f"    Scene {i+1}/{len(script_data['scenes'])} done")

        time.sleep(12)  # stay under 6 req/min limit

    return image_files


def generate_images_huggingface(config: dict, script_data: dict, output_dir: str) -> list[str]:
    """Generate scene images using Hugging Face Inference API (free, rate-limited)."""
    api_token = config["huggingface"]["api_token"]
    model = config["huggingface"]["model"]
    style = config["content"]["image_style"]
    image_files = []

    headers = {"Authorization": f"Bearer {api_token}"}
    api_url = f"https://api-inference.huggingface.co/models/{model}"

    for i, scene in enumerate(script_data["scenes"]):
        prompt = f"{style}, {scene['visual_description']}, high quality, no text, no words"

        for attempt in range(3):
            response = requests.post(api_url, headers=headers, json={"inputs": prompt})
            if response.status_code == 200:
                filepath = os.path.join(output_dir, f"scene_{i+1}.png")
                with open(filepath, "wb") as f:
                    f.write(response.content)
                image_files.append(filepath)
                break
            elif response.status_code == 503:
                # Model loading, wait
                time.sleep(20)
            else:
                raise Exception(f"HuggingFace API error: {response.status_code} - {response.text}")

        time.sleep(2)

    return image_files


def generate_images_openai(config: dict, script_data: dict, output_dir: str) -> list[str]:
    """Generate scene images using OpenAI DALL-E API."""
    from openai import OpenAI

    client = OpenAI(api_key=config["openai"]["api_key"])
    style = config["content"]["image_style"]
    image_files = []

    for i, scene in enumerate(script_data["scenes"]):
        prompt = f"{style}, {scene['visual_description']}, no text, no words"

        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt[:4000],
            n=1,
            size="1792x1024",
            quality="standard",
        )

        img_url = response.data[0].url
        img_data = requests.get(img_url).content
        filepath = os.path.join(output_dir, f"scene_{i+1}.png")
        with open(filepath, "wb") as f:
            f.write(img_data)
        image_files.append(filepath)

        time.sleep(1)

    return image_files


def generate_images_pexels(config: dict, script_data: dict, output_dir: str) -> list[str]:
    """Download stock images from Pexels API (free)."""
    api_key = config["pexels"]["api_key"]
    image_files = []

    headers = {"Authorization": api_key}

    for i, scene in enumerate(script_data["scenes"]):
        query = scene["visual_description"][:80]  # Pexels search query
        url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape"

        response = requests.get(url, headers=headers)
        data = response.json()

        if data.get("photos"):
            img_url = data["photos"][0]["src"]["large2x"]
            img_data = requests.get(img_url).content
            filepath = os.path.join(output_dir, f"scene_{i+1}.png")
            with open(filepath, "wb") as f:
                f.write(img_data)
            image_files.append(filepath)
        else:
            raise Exception(f"No Pexels results for: {query}")

        time.sleep(0.5)

    return image_files


def generate_images(config: dict, script_data: dict, output_dir: str) -> list[str]:
    """Route to the configured image provider."""
    provider = config["image_provider"]
    if provider == "openai":
        return generate_images_openai(config, script_data, output_dir)
    elif provider == "replicate":
        return generate_images_replicate(config, script_data, output_dir)
    elif provider == "huggingface":
        return generate_images_huggingface(config, script_data, output_dir)
    elif provider == "pexels":
        return generate_images_pexels(config, script_data, output_dir)
    else:
        raise ValueError(f"Unknown image provider: {provider}")


def generate_assets(config: dict, script_data: dict, output_dir: str,
                    voice: str = None) -> dict:
    """Generate all assets (voiceover + images) for the video."""
    audio_dir = os.path.join(output_dir, "audio")
    image_dir = os.path.join(output_dir, "images")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    print("  Generating voiceover...")
    audio_files = generate_voiceover(config, script_data, audio_dir, voice=voice)

    print("  Generating images...")
    image_files = generate_images(config, script_data, image_dir)

    return {
        "audio_files": audio_files,
        "image_files": image_files,
    }


def generate_voiceover_only(config: dict, script_data: dict, output_dir: str,
                            voice: str = None) -> list[str]:
    """Generate only voiceover files (reuses existing images from another language)."""
    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    print("  Generating voiceover...")
    return generate_voiceover(config, script_data, audio_dir, voice=voice)
