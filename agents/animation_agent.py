"""Animation agent — converts static images into animated video clips.

Two providers:
  - "kenburns" (default, free): Pan/zoom effects via MoviePy
  - "ai" (optional, paid): Replicate image-to-video models
"""

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

from moviepy.editor import ImageClip, VideoClip, VideoFileClip, vfx

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


# ── AI animation (Replicate) ────────────────────────────────────────

def _animate_with_replicate(config: dict, image_path: str,
                            scene_description: str, duration: float,
                            output_path: str) -> str:
    """Animate an image using a Replicate image-to-video model."""
    import replicate

    client = replicate.Client(api_token=config["replicate"]["api_token"])
    ai_config = config.get("animation", {}).get("ai", {})
    model = ai_config.get("model", "wan-video/wan-2.5-i2v-fast")
    clip_duration = ai_config.get("duration", 5)
    clip_resolution = ai_config.get("resolution", "720p")

    prompt = f"Gentle animation of: {scene_description}. Smooth subtle movement, kid-friendly cartoon style."

    for attempt in range(3):
        try:
            get_limiter("replicate").acquire()
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

    # Download the video
    video_url = output
    if isinstance(output, list):
        video_url = output[0]
    if hasattr(video_url, 'url'):
        video_url = video_url.url

    video_data = requests.get(str(video_url), timeout=120).content
    with open(output_path, "wb") as f:
        f.write(video_data)

    # If clip is shorter than needed, loop it
    clip = VideoFileClip(output_path)
    if clip.duration < duration:
        loops = math.ceil(duration / clip.duration)
        looped = clip.fx(vfx.loop, n=loops).subclip(0, duration)
        temp_path = output_path.replace(".mp4", "_looped.mp4")
        looped.write_videofile(temp_path, fps=clip.fps, codec="libx264",
                               audio=False, threads=2, logger=None)
        looped.close()
        clip.close()
        os.replace(temp_path, output_path)
    else:
        clip.close()

    return output_path


# ── Public API ───────────────────────────────────────────────────────

def animate_scene(config: dict, image_path: str, duration: float,
                  scene_description: str, output_path: str) -> str:
    """Animate a single scene image into a video clip.

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

    if provider == "ai":
        return _animate_with_replicate(config, image_path, scene_description,
                                       duration, output_path)
    else:
        return _animate_kenburns(config, image_path, duration, output_path)


def animate_all_scenes(config: dict, image_files: list, audio_files: list,
                       script_data: dict, output_dir: str) -> list:
    """Animate all scene images, matching each to its audio duration.

    Returns list of animated clip paths.
    """
    from moviepy.editor import AudioFileClip

    clips_dir = os.path.join(output_dir, "animated_clips")
    os.makedirs(clips_dir, exist_ok=True)

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
