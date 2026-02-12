import asyncio
import os
import random
import requests
import time

import edge_tts

from agents.rate_limiter import get_limiter


def _sanitize_tts_text(text: str) -> str:
    """Remove/replace characters that break edge-tts SSML."""
    replacements = {
        "\u2019": "'", "\u2018": "'",  # smart quotes
        "\u201c": '"', "\u201d": '"',  # smart double quotes
        "\u2013": "-", "\u2014": "-",  # en/em dashes
        "\u2026": "...",               # ellipsis
        "&": " and ",                  # SSML special char — breaks XML
        "<": "",                       # SSML tag start — breaks XML
        ">": "",                       # SSML tag end — breaks XML
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Collapse any double spaces created by replacements
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def pick_voice(config: dict, lang_code: str) -> str:
    """Randomly pick a voice from the configured pool for the given language."""
    for lang in config["languages"]:
        if lang["code"] == lang_code:
            voice = random.choice(lang["voices"])
            print(f"  Selected voice: {voice}")
            return voice
    raise ValueError(f"No voices configured for language: {lang_code}")


def _build_scene_texts(script_data: dict) -> list[str]:
    """Build narration texts for each scene, combining intro/outro."""
    texts = []
    for i, scene in enumerate(script_data["scenes"]):
        if i == 0:
            text = script_data["intro_hook"] + " " + scene["narration"]
        elif i == len(script_data["scenes"]) - 1:
            text = scene["narration"] + " " + script_data["outro"]
        else:
            text = scene["narration"]
        texts.append(_sanitize_tts_text(text))
    return texts


def _generate_voiceover_edge_tts(texts: list[str], output_dir: str,
                                  voice: str, lang_code: str = "en") -> list[str]:
    """Generate voiceover using edge-tts (free) with natural prosody."""
    audio_files = []

    # Keep prosody subtle — aggressive rate/pitch makes it sound MORE robotic
    # Let the natural voice shine through; the script itself has enthusiasm
    rate = "+3%"
    pitch = "+0Hz"

    async def _generate_single(text: str, filepath: str, use_prosody: bool = True):
        if use_prosody:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        else:
            communicate = edge_tts.Communicate(text, voice)
        await asyncio.wait_for(communicate.save(filepath), timeout=60)

    for i, text in enumerate(texts):
        filepath = os.path.join(output_dir, f"scene_{i+1}.mp3")
        print(f"    Scene {i+1}: {len(text)} chars — \"{text[:60]}...\"" if len(text) > 60 else f"    Scene {i+1}: {len(text)} chars")
        for attempt in range(4):
            try:
                # Last attempt: drop prosody in case it's confusing the SSML parser
                use_prosody = attempt < 3
                asyncio.run(_generate_single(text, filepath, use_prosody=use_prosody))
                break
            except Exception as e:
                if attempt < 3:
                    wait = 10 * (attempt + 1)
                    print(f"    TTS retry {attempt+1}/3 ({type(e).__name__}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        audio_files.append(filepath)
        time.sleep(0.5)  # brief pause between scenes to avoid rate limiting

    return audio_files


def _generate_voiceover_openai_tts(config: dict, texts: list[str],
                                    output_dir: str, voice: str = None) -> list[str]:
    """Generate voiceover using OpenAI TTS API."""
    from openai import OpenAI

    client = OpenAI(api_key=config["openai"]["api_key"])
    # Always use the configured OpenAI voice — the `voice` param is an edge-tts voice name
    tts_voice = config.get("tts", {}).get("openai_voice", "nova")
    audio_files = []

    for i, text in enumerate(texts):
        get_limiter("openai_tts").acquire()
        response = client.audio.speech.create(
            model="tts-1",
            voice=tts_voice,
            input=text,
        )
        filepath = os.path.join(output_dir, f"scene_{i+1}.mp3")
        response.stream_to_file(filepath)
        audio_files.append(filepath)

    return audio_files


def _generate_voiceover_elevenlabs(config: dict, texts: list[str],
                                    output_dir: str) -> list[str]:
    """Generate voiceover using ElevenLabs API."""
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise ImportError("Install elevenlabs package: pip install elevenlabs")

    api_key = config.get("tts", {}).get("elevenlabs_api_key", "")
    voice_id = config.get("tts", {}).get("elevenlabs_voice_id", "")

    client = ElevenLabs(api_key=api_key)
    audio_files = []

    for i, text in enumerate(texts):
        get_limiter("elevenlabs").acquire()
        audio = client.generate(
            text=text,
            voice=voice_id,
            model="eleven_multilingual_v2",
        )
        filepath = os.path.join(output_dir, f"scene_{i+1}.mp3")
        with open(filepath, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        audio_files.append(filepath)

    return audio_files


def _generate_lullaby_voiceover_edge_tts(texts: list[str], output_dir: str,
                                          voice: str) -> list[str]:
    """Generate lullaby voiceover with slower rate (-10%) for a calming bedtime feel."""
    audio_files = []

    async def _generate_single(text: str, filepath: str):
        communicate = edge_tts.Communicate(text, voice, rate="-10%", pitch="+0Hz")
        await asyncio.wait_for(communicate.save(filepath), timeout=60)

    for i, text in enumerate(texts):
        filepath = os.path.join(output_dir, f"scene_{i+1}.mp3")
        print(f"    Scene {i+1}: {len(text)} chars")
        for attempt in range(4):
            try:
                asyncio.run(_generate_single(text, filepath))
                break
            except Exception as e:
                if attempt < 3:
                    wait = 10 * (attempt + 1)
                    print(f"    TTS retry {attempt+1}/3 ({type(e).__name__}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        audio_files.append(filepath)
        time.sleep(0.5)

    return audio_files


def generate_lullaby_voiceover(config: dict, script_data: dict, output_dir: str,
                               voice: str = None) -> list[str]:
    """Generate lullaby voiceover at -10% speech rate (slower, calming). edge-tts only."""
    if voice is None:
        voice = pick_voice(config, "hi")

    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    texts = _build_scene_texts(script_data)
    print("  Generating lullaby voiceover (slow pace, rate=-10%)...")
    return _generate_lullaby_voiceover_edge_tts(texts, audio_dir, voice)


def generate_voiceover(config: dict, script_data: dict, output_dir: str,
                       voice: str = None) -> list[str]:
    """Generate voiceover using the configured TTS provider."""
    if voice is None:
        voice = pick_voice(config, "en")

    texts = _build_scene_texts(script_data)
    provider = config.get("tts", {}).get("provider", "edge-tts")

    if provider == "openai":
        return _generate_voiceover_openai_tts(config, texts, output_dir, voice=voice)
    elif provider == "elevenlabs":
        return _generate_voiceover_elevenlabs(config, texts, output_dir)
    else:
        return _generate_voiceover_edge_tts(texts, output_dir, voice)


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

        get_limiter("replicate").acquire()

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
            get_limiter("huggingface").acquire()
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

        get_limiter("openai").acquire()
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

        get_limiter("pexels").acquire()
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


def generate_bg_music_ai(config: dict, output_path: str) -> str | None:
    """Generate background music via Replicate musicgen. Returns local path or None on failure."""
    import replicate

    bg_cfg = config.get("bg_music", {})
    if bg_cfg.get("provider") != "replicate":
        return None

    prompt   = bg_cfg.get("prompt", "gentle playful kids background music, soft happy melody, no lyrics")
    duration = bg_cfg.get("duration", 30)
    model    = bg_cfg.get("replicate_model", "meta/musicgen")

    # Set Replicate API token from config
    os.environ["REPLICATE_API_TOKEN"] = config.get("replicate", {}).get("api_token", "")

    print(f"  Generating AI background music ({duration}s)...")
    try:
        output = replicate.run(
            model,
            input={
                "prompt": prompt,
                "duration": duration,
                "model_version": "stereo-large",
                "output_format": "mp3",
                "normalization_strategy": "peak",
            },
        )
        # output is a URL string or file-like; download it
        url = output if isinstance(output, str) else output[0]
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"  AI music saved: {output_path}")
        return output_path
    except Exception as e:
        print(f"  Warning: AI music generation failed ({e}), falling back to local music")
        return None
