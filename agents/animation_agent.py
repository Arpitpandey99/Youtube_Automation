"""Animation agent — converts static images into animated video clips.

Three provider modes:
  - "kenburns" (default, free): Pan/zoom effects via MoviePy
  - "ai" (paid): AI image-to-video (Veo 2, Kling 3.0, or Replicate)
  - "ai_with_fallback": Try AI, fall back to Ken Burns on failure
"""

import base64
import copy
import math
import os
import random
import time

import numpy as np
import requests
from PIL import Image, ImageFilter, ImageEnhance

# Pillow 10+ removed Image.ANTIALIAS; MoviePy 1.x still references it
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, VideoClip, VideoFileClip,
    concatenate_videoclips, CompositeVideoClip, vfx,
)

from agents.rate_limiter import get_limiter


# ── Ken Burns effects ────────────────────────────────────────────────

EFFECTS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "combined"]


def _load_image_oversized(image_path: str, target_w: int, target_h: int,
                          margin: float = 1.35) -> Image.Image:
    """Load and resize image larger than target so there's room to pan/zoom."""
    img = Image.open(image_path).convert("RGB")
    new_w = int(target_w * margin)
    new_h = int(target_h * margin)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _apply_zoom_in(image_path: str, duration: float, resolution: tuple,
                   zoom_ratio: float = 0.04, fps: int = 24) -> VideoClip:
    """Progressive zoom into center of image."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th)
    iw, ih = img.size
    frame_base = np.array(img)

    def make_frame(t):
        scale = 1.0 + (zoom_ratio * t)
        cw = int(tw / scale)
        ch = int(th / scale)
        x = (iw - cw) // 2
        y = (ih - ch) // 2
        crop = Image.fromarray(frame_base).crop((x, y, x + cw, y + ch))
        return np.array(crop.resize((tw, th), Image.LANCZOS))

    return VideoClip(make_frame, duration=duration).set_fps(fps)


def _apply_zoom_out(image_path: str, duration: float, resolution: tuple,
                    zoom_ratio: float = 0.04, fps: int = 24) -> VideoClip:
    """Start zoomed in, slowly pull out."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th)
    iw, ih = img.size
    frame_base = np.array(img)
    max_zoom = 1.0 + (zoom_ratio * duration)

    def make_frame(t):
        scale = max_zoom - (zoom_ratio * t)
        scale = max(scale, 1.0)
        cw = int(tw / scale)
        ch = int(th / scale)
        x = (iw - cw) // 2
        y = (ih - ch) // 2
        crop = Image.fromarray(frame_base).crop((x, y, x + cw, y + ch))
        return np.array(crop.resize((tw, th), Image.LANCZOS))

    return VideoClip(make_frame, duration=duration).set_fps(fps)


def _apply_pan_left(image_path: str, duration: float, resolution: tuple,
                    fps: int = 24) -> VideoClip:
    """Horizontal pan from right to left across the image."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th, margin=1.4)
    iw, ih = img.size
    frame_base = np.array(img)
    max_offset = iw - tw

    def make_frame(t):
        progress = t / duration
        x = int(max_offset * (1 - progress))
        y = (ih - th) // 2
        crop = Image.fromarray(frame_base).crop((x, y, x + tw, y + th))
        return np.array(crop)

    return VideoClip(make_frame, duration=duration).set_fps(fps)


def _apply_pan_right(image_path: str, duration: float, resolution: tuple,
                     fps: int = 24) -> VideoClip:
    """Horizontal pan from left to right across the image."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th, margin=1.4)
    iw, ih = img.size
    frame_base = np.array(img)
    max_offset = iw - tw

    def make_frame(t):
        progress = t / duration
        x = int(max_offset * progress)
        y = (ih - th) // 2
        crop = Image.fromarray(frame_base).crop((x, y, x + tw, y + th))
        return np.array(crop)

    return VideoClip(make_frame, duration=duration).set_fps(fps)


def _apply_pan_up(image_path: str, duration: float, resolution: tuple,
                  fps: int = 24) -> VideoClip:
    """Vertical pan from bottom to top."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th, margin=1.4)
    iw, ih = img.size
    frame_base = np.array(img)
    max_offset = ih - th

    def make_frame(t):
        progress = t / duration
        x = (iw - tw) // 2
        y = int(max_offset * (1 - progress))
        crop = Image.fromarray(frame_base).crop((x, y, x + tw, y + th))
        return np.array(crop)

    return VideoClip(make_frame, duration=duration).set_fps(fps)


def _apply_combined(image_path: str, duration: float, resolution: tuple,
                    zoom_ratio: float = 0.03, fps: int = 24) -> VideoClip:
    """Combined slow zoom + gentle horizontal pan."""
    tw, th = resolution
    img = _load_image_oversized(image_path, tw, th, margin=1.5)
    iw, ih = img.size
    frame_base = np.array(img)
    max_pan = int((iw - tw) * 0.4)
    # Random direction
    pan_dir = random.choice([-1, 1])

    def make_frame(t):
        progress = t / duration
        scale = 1.0 + (zoom_ratio * t)
        cw = int(tw / scale)
        ch = int(th / scale)
        cx = (iw // 2) + int(pan_dir * max_pan * progress)
        cy = ih // 2
        x = cx - cw // 2
        y = cy - ch // 2
        # Clamp
        x = max(0, min(x, iw - cw))
        y = max(0, min(y, ih - ch))
        crop = Image.fromarray(frame_base).crop((x, y, x + cw, y + ch))
        return np.array(crop.resize((tw, th), Image.LANCZOS))

    return VideoClip(make_frame, duration=duration).set_fps(fps)


KENBURNS_EFFECTS = {
    "zoom_in": _apply_zoom_in,
    "zoom_out": _apply_zoom_out,
    "pan_left": _apply_pan_left,
    "pan_right": _apply_pan_right,
    "pan_up": _apply_pan_up,
    "combined": _apply_combined,
}


def _animate_kenburns(config: dict, image_path: str, duration: float,
                      output_path: str) -> str:
    """Create an animated clip using Ken Burns effects (free)."""
    resolution = tuple(config["video"]["resolution"])
    fps = config["video"]["fps"]
    anim_config = config.get("animation", {}).get("kenburns", {})
    zoom_ratio = anim_config.get("zoom_ratio", 0.04)
    available = anim_config.get("effects", EFFECTS)

    effect_name = random.choice(available)
    effect_fn = KENBURNS_EFFECTS[effect_name]
    print(f"    Effect: {effect_name}")

    kwargs = {"image_path": image_path, "duration": duration,
              "resolution": resolution, "fps": fps}
    if effect_name in ("zoom_in", "zoom_out", "combined"):
        kwargs["zoom_ratio"] = zoom_ratio

    clip = effect_fn(**kwargs)
    clip.write_videofile(output_path, fps=fps, codec="libx264",
                         audio=False, threads=2, logger=None)
    clip.close()
    return output_path


# ── AI animation helpers ─────────────────────────────────────────────

def _get_motion_prompt(scene_description: str) -> str:
    """Build an animation-specific prompt from scene description."""
    motion_hints = [
        "gentle swaying motion, soft breeze effect",
        "subtle floating particles, dreamy atmosphere",
        "slow camera drift, peaceful movement",
        "gentle character movement, soft animation",
        "subtle environmental motion, leaves rustling",
    ]
    hint = random.choice(motion_hints)
    return f"Gentle cartoon animation: {scene_description}. {hint}. " \
           f"Smooth kid-friendly style, no sudden movements, no scary elements."


def _extract_url(output) -> str:
    """Extract video URL from various Replicate output formats."""
    video_url = output
    if isinstance(output, list):
        video_url = output[0]
    if hasattr(video_url, 'url'):
        video_url = video_url.url
    return str(video_url)


def _extend_clip_to_duration(clip_path: str, target_duration: float,
                             image_path: str, config: dict,
                             output_path: str) -> str:
    """Extend a short AI clip to match audio duration.

    Strategy:
      1. Slow the AI clip to speed_factor (default 0.5x) → doubles duration
      2. If still shorter, append Ken Burns on the original image
      3. Crossfade between AI portion and Ken Burns extension
    """
    ai_config = config.get("animation", {}).get("ai", {})
    speed_factor = ai_config.get("speed_factor", 0.5)
    extend_with_kb = ai_config.get("extend_with_kenburns", True)
    fps = config["video"]["fps"]

    clip = VideoFileClip(clip_path)
    clip_dur = clip.duration

    # Step 1: Slow down the AI clip
    slowed = clip.fx(vfx.speedx, speed_factor)
    slowed_dur = slowed.duration

    if slowed_dur >= target_duration:
        # AI clip (slowed) is long enough — just trim
        final = slowed.subclip(0, target_duration)
        final.write_videofile(output_path, fps=fps, codec="libx264",
                              audio=False, threads=2, logger=None)
        final.close()
        slowed.close()
        clip.close()
        return output_path

    if not extend_with_kb:
        # Loop the slowed clip to fill duration
        loops = math.ceil(target_duration / slowed_dur)
        looped = slowed.fx(vfx.loop, n=loops).subclip(0, target_duration)
        looped.write_videofile(output_path, fps=fps, codec="libx264",
                               audio=False, threads=2, logger=None)
        looped.close()
        slowed.close()
        clip.close()
        return output_path

    # Step 2: Create Ken Burns extension for remaining duration
    remaining = target_duration - slowed_dur + 0.5  # 0.5s overlap for crossfade
    kb_temp = output_path.replace(".mp4", "_kb_ext.mp4")
    _animate_kenburns(config, image_path, remaining, kb_temp)
    kb_clip = VideoFileClip(kb_temp)

    # Step 3: Crossfade — fade out AI, fade in Ken Burns
    crossfade_dur = min(0.5, slowed_dur * 0.3)
    ai_part = slowed.set_start(0)
    kb_part = kb_clip.set_start(slowed_dur - crossfade_dur)
    kb_part = kb_part.crossfadein(crossfade_dur)

    final = CompositeVideoClip([ai_part, kb_part],
                               size=ai_part.size)
    final = final.subclip(0, target_duration)
    final.write_videofile(output_path, fps=fps, codec="libx264",
                          audio=False, threads=2, logger=None)

    final.close()
    kb_clip.close()
    slowed.close()
    clip.close()

    # Cleanup temp
    if os.path.exists(kb_temp):
        os.remove(kb_temp)

    return output_path


# ── AI Providers ──────────────────────────────────────────────────────

def _animate_with_veo(config: dict, image_path: str,
                      scene_description: str, output_path: str) -> str:
    """Generate animated clip using Google Veo 2 via Vertex AI.

    Uses GCP credits (₹26K free). Cost: ~$0.50/sec × 5 sec = $2.50/clip.
    Retries up to 3 times with simplified prompts if Veo returns no output
    (common when content safety filters reject the generation).
    """
    from google import genai
    from google.genai import types

    veo_config = config.get("animation", {}).get("ai", {}).get("veo", {})
    project_id = veo_config.get("project_id")
    location = veo_config.get("location", "us-central1")
    model = veo_config.get("model", "veo-2.0-generate-001")
    # Auto-detect aspect ratio from video resolution (landscape=16:9, portrait=9:16)
    res = config.get("video", {}).get("resolution", [1280, 720])
    aspect_ratio = "9:16" if res[1] > res[0] else veo_config.get("aspect_ratio", "16:9")

    # Set GCP credentials from config if GOOGLE_APPLICATION_CREDENTIALS not already set
    creds_path = config.get("tts", {}).get("google_tts_credentials", "")
    if creds_path and os.path.isfile(creds_path) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

    # Initialize client with Vertex AI
    client = genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
    )

    # Read local image
    image = types.Image.from_file(location=image_path)

    # Retry with progressively simpler prompts (Veo rejects some prompts silently)
    prompts = [
        _get_motion_prompt(scene_description),
        f"Gentle animation of a colorful kids illustration. Soft camera movement, peaceful scene.",
        f"Slow subtle zoom on a cartoon illustration. Calm, smooth, kid-friendly.",
    ]

    for attempt, prompt in enumerate(prompts):
        get_limiter("vertex_ai_video").acquire()
        attempt_label = f" (attempt {attempt+1}/3)" if attempt > 0 else ""
        print(f"    Veo 2: Generating clip{attempt_label} (polling, may take 1-3 min)...")

        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            image=image,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                number_of_videos=1,
            ),
        )

        # Poll until complete (Veo is async)
        poll_count = 0
        while not operation.done:
            time.sleep(15)
            operation = client.operations.get(operation)
            poll_count += 1
            if poll_count > 20:  # 5 min timeout
                break

        # Check if we got a result
        if (operation.done and operation.response
                and operation.result
                and operation.result.generated_videos):
            break
        else:
            if attempt < len(prompts) - 1:
                print(f"    Veo 2: No output (likely content filter), retrying with simpler prompt...")
            else:
                raise RuntimeError("Veo 2 returned no video after 3 attempts (content filter)")

    # Download video bytes
    video = operation.result.generated_videos[0].video
    if hasattr(video, 'video_bytes') and video.video_bytes:
        with open(output_path, "wb") as f:
            f.write(video.video_bytes)
    elif hasattr(video, 'uri') and video.uri:
        # Download from GCS URI
        video_data = requests.get(video.uri, timeout=120).content
        with open(output_path, "wb") as f:
            f.write(video_data)
    else:
        raise RuntimeError("Veo 2 returned no downloadable video")

    print(f"    Veo 2: Clip generated successfully")
    return output_path


def _animate_with_kling(config: dict, image_path: str,
                        scene_description: str, output_path: str) -> str:
    """Generate animated clip using Kling 3.0 via fal.ai API.

    Cheapest option: ~$0.029/sec × 5 sec = $0.145/clip.
    """
    import fal_client

    kling_config = config.get("animation", {}).get("ai", {}).get("kling", {})
    api_key = kling_config.get("api_key")
    model = kling_config.get("model", "fal-ai/kling-video/v3/pro/image-to-video")
    duration = kling_config.get("duration", 5)

    # Auto-detect aspect ratio from video resolution (landscape=16:9, portrait=9:16)
    res = config.get("video", {}).get("resolution", [1280, 720])
    aspect_ratio = "9:16" if res[1] > res[0] else "16:9"

    # fal.ai needs an image URL, not a local file — upload via data URI
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    img_b64 = base64.b64encode(image_bytes).decode()
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    image_data_uri = f"data:{mime};base64,{img_b64}"

    prompt = _get_motion_prompt(scene_description)

    # Set API key
    os.environ["FAL_KEY"] = api_key

    get_limiter("fal_ai").acquire()
    print(f"    Kling 3.0: Generating clip via fal.ai ({aspect_ratio})...")

    for attempt in range(3):
        try:
            result = fal_client.subscribe(
                model,
                arguments={
                    "prompt": prompt,
                    "image_url": image_data_uri,
                    "duration": str(duration),
                    "aspect_ratio": aspect_ratio,
                },
            )
            break
        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                print(f"    Retry {attempt+1}/2 ({type(e).__name__}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

    # Download generated video
    video_url = result.get("video", {}).get("url")
    if not video_url:
        raise RuntimeError(f"Kling returned no video URL: {result}")

    video_data = requests.get(video_url, timeout=120).content
    with open(output_path, "wb") as f:
        f.write(video_data)

    print(f"    Kling 3.0: Clip generated successfully")
    return output_path


def _animate_with_replicate(config: dict, image_path: str,
                            scene_description: str, output_path: str) -> str:
    """Generate animated clip using Replicate image-to-video model."""
    import replicate

    client = replicate.Client(api_token=config["replicate"]["api_token"])
    ai_config = config.get("animation", {}).get("ai", {})
    rep_config = ai_config.get("replicate", {})
    model = rep_config.get("model", "wan-ai/wan2.1-i2v-480p")
    clip_duration = rep_config.get("duration", 5)
    clip_resolution = rep_config.get("resolution", "480p")

    prompt = _get_motion_prompt(scene_description)

    for attempt in range(3):
        try:
            get_limiter("replicate_video").acquire()
            output = client.run(
                model,
                input={
                    "image": open(image_path, "rb"),
                    "prompt": prompt,
                    "duration": clip_duration,
                    "resolution": clip_resolution,
                }
            )
            break
        except Exception as e:
            if attempt < 2:
                wait = 15 * (attempt + 1)
                print(f"    Retry {attempt+1}/2 ({type(e).__name__}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

    video_url = _extract_url(output)
    video_data = requests.get(video_url, timeout=120).content
    with open(output_path, "wb") as f:
        f.write(video_data)

    print(f"    Replicate: Clip generated successfully")
    return output_path


# ── Public API ───────────────────────────────────────────────────────

def animate_scene(config: dict, image_path: str, duration: float,
                  scene_description: str, output_path: str) -> str:
    """Animate a single scene image into a video clip.

    For AI providers: generates a short clip (5s), then extends to full
    duration using speed reduction + Ken Burns hybrid approach.

    Args:
        config: Full pipeline config
        image_path: Path to the scene image
        duration: Target duration in seconds (matches audio)
        scene_description: Visual description (used by AI provider)
        output_path: Where to save the animated clip

    Returns:
        Path to the animated video clip (.mp4)
    """
    provider = config.get("animation", {}).get("provider", "kenburns")
    ai_provider = config.get("animation", {}).get("ai", {}).get("provider", "replicate")
    fallback = config.get("animation", {}).get("ai", {}).get("fallback_to_kenburns", True)

    if provider in ("ai", "ai_with_fallback"):
        try:
            # Generate short AI clip (5 seconds)
            temp_clip = output_path.replace(".mp4", "_ai_raw.mp4")

            if ai_provider == "veo":
                _animate_with_veo(config, image_path, scene_description, temp_clip)
            elif ai_provider == "kling":
                _animate_with_kling(config, image_path, scene_description, temp_clip)
            else:
                _animate_with_replicate(config, image_path, scene_description, temp_clip)

            # Extend to full duration using speed reduction + Ken Burns
            _extend_clip_to_duration(temp_clip, duration, image_path, config, output_path)

            # Cleanup raw AI clip
            if os.path.exists(temp_clip):
                os.remove(temp_clip)

            return output_path

        except Exception as e:
            if provider == "ai_with_fallback" or fallback:
                print(f"    AI animation failed ({e}), falling back to Ken Burns...")
                return _animate_kenburns(config, image_path, duration, output_path)
            raise
    else:
        return _animate_kenburns(config, image_path, duration, output_path)


def animate_all_scenes(config: dict, image_files: list, audio_files: list,
                       script_data: dict, output_dir: str) -> list:
    """Animate all scene images, matching each to its audio duration.

    For AI providers, estimates cost upfront and auto-falls back to
    Ken Burns if the projected cost exceeds the configured limit.

    Returns list of animated clip paths.
    """
    from moviepy.editor import AudioFileClip

    clips_dir = os.path.join(output_dir, "animated_clips")
    os.makedirs(clips_dir, exist_ok=True)

    provider = config.get("animation", {}).get("provider", "kenburns")
    ai_config = config.get("animation", {}).get("ai", {})

    # Cost estimation for AI providers
    if provider in ("ai", "ai_with_fallback"):
        ai_provider = ai_config.get("provider", "replicate")
        clip_dur = ai_config.get("clip_duration", 5)
        cost_map = ai_config.get("cost_per_second", {})
        cost_per_sec = cost_map.get(ai_provider, 0.04)
        num_scenes = len(image_files)
        est_cost = num_scenes * clip_dur * cost_per_sec
        cost_limit = ai_config.get("cost_limit_per_video", 5.0)

        print(f"  AI animation ({ai_provider}): ~${est_cost:.2f} for {num_scenes} scenes")

        if est_cost > cost_limit:
            print(f"  WARNING: Exceeds cost limit (${cost_limit:.2f}). Falling back to Ken Burns.")
            config = copy.deepcopy(config)
            config["animation"]["provider"] = "kenburns"

    animated_clips = []
    for i, (img_path, audio_path) in enumerate(zip(image_files, audio_files)):
        audio = AudioFileClip(audio_path)
        duration = audio.duration + 0.5  # small padding
        audio.close()

        scene_desc = script_data["scenes"][i].get("visual_description", "")
        clip_path = os.path.join(clips_dir, f"scene_{i+1}.mp4")

        print(f"  Animating scene {i+1}/{len(image_files)}...")
        animate_scene(config, img_path, duration, scene_desc, clip_path)
        animated_clips.append(clip_path)

    return animated_clips
