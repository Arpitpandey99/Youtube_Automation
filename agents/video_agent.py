import os
import random
from PIL import Image, ImageFilter, ImageEnhance

# Pillow 10+ removed Image.ANTIALIAS; MoviePy 1.x still references it
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, AudioFileClip, VideoFileClip, CompositeVideoClip,
    CompositeAudioClip, TextClip, concatenate_videoclips,
    concatenate_audioclips,
)


TRANSITION_DURATION = 0.6  # seconds of crossfade between scenes
LULLABY_TRANSITION = 1.0  # gentler crossfade for lullaby videos


def create_scene_clip(image_path: str, audio_path: str, narration_text: str,
                      config: dict) -> CompositeVideoClip:
    """Create a single scene clip with image, audio, and subtitles."""
    resolution = tuple(config["video"]["resolution"])

    # Load audio to get duration
    audio = AudioFileClip(audio_path)
    duration = audio.duration + 0.5  # small padding

    # Create image clip resized to target resolution
    img_clip = ImageClip(image_path, duration=duration).resize(resolution)

    # Create subtitle - split long text into lines
    words = narration_text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 50:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    subtitle_text = "\n".join(lines)

    try:
        txt_clip = (
            TextClip(
                subtitle_text,
                fontsize=config["video"]["subtitle_font_size"],
                color=config["video"]["subtitle_color"],
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=2,
                method="caption",
                size=(resolution[0] - 200, None),
            )
            .set_duration(duration)
            .set_position(("center", resolution[1] - 180))
        )
        video = CompositeVideoClip([img_clip, txt_clip], size=resolution)
    except Exception:
        # Fallback without subtitles if TextClip fails (ImageMagick not installed)
        print("    Warning: Subtitles skipped (install ImageMagick for subtitle support)")
        video = img_clip

    video = video.set_audio(audio)
    return video


def assemble_video(config: dict, script_data: dict, assets: dict, output_dir: str) -> str:
    """Assemble the final video from all scenes."""
    resolution = tuple(config["video"]["resolution"])
    scene_clips = []

    for i in range(len(script_data["scenes"])):
        image_path = assets["image_files"][i]
        audio_path = assets["audio_files"][i]
        narration = script_data["scenes"][i]["narration"]

        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]

        print(f"  Assembling scene {i+1}...")
        clip = create_scene_clip(image_path, audio_path, narration, config)
        scene_clips.append(clip)

    # Apply crossfade transitions between scenes
    t = TRANSITION_DURATION
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    # Concatenate with overlap (negative padding = crossfade overlap)
    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)

    # Add background music if available
    music_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "music")
    music_files = [f for f in os.listdir(music_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(music_dir) else []

    if music_files:
        bg_music_path = os.path.join(music_dir, random.choice(music_files))
        bg_music = AudioFileClip(bg_music_path).volumex(config["video"]["bg_music_volume"])
        # Loop if needed
        if bg_music.duration < final.duration:
            loops = int(final.duration / bg_music.duration) + 1
            bg_music = concatenate_audioclips([bg_music] * loops)
        bg_music = bg_music.subclip(0, final.duration)

        final = final.set_audio(CompositeAudioClip([final.audio, bg_music]))

    # Export
    output_path = os.path.join(output_dir, "final_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    # Clean up
    for clip in scene_clips:
        clip.close()
    final.close()

    return output_path


def _prepare_vertical_image(image_path: str, target_w: int = 1080, target_h: int = 1920) -> str:
    """Prepare a landscape image for vertical format with blurred background.

    Instead of stretching/compressing the image, this:
    1. Creates a blurred, darkened copy scaled to fill the full vertical frame
    2. Places the original image (scaled to fit width) centered on top
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Create blurred background — stretch to fill entire vertical frame
    bg = img.copy()
    bg = bg.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)

    # Scale foreground to fit width, maintaining aspect ratio
    scale = target_w / w
    new_h = int(h * scale)
    fg = img.resize((target_w, new_h), Image.LANCZOS)

    # Center the foreground vertically on the blurred background
    y_offset = (target_h - new_h) // 2
    bg.paste(fg, (0, y_offset))

    # Save the prepared vertical image
    temp_path = image_path.rsplit(".", 1)[0] + "_vertical.png"
    bg.save(temp_path, quality=95)
    return temp_path


def create_shorts_clip(image_path: str, audio_path: str, narration_text: str,
                       config: dict) -> CompositeVideoClip:
    """Create a single scene clip in vertical (9:16) format for Shorts."""
    shorts_res = (1080, 1920)

    audio = AudioFileClip(audio_path)
    duration = audio.duration + 0.3

    # Prepare vertical image with blurred background (no stretching)
    vertical_path = _prepare_vertical_image(image_path, shorts_res[0], shorts_res[1])
    img_clip = ImageClip(vertical_path, duration=duration).resize(shorts_res)

    # Subtitles with larger font for vertical format
    words = narration_text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 25:  # shorter lines for vertical
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    subtitle_text = "\n".join(lines)

    try:
        txt_clip = (
            TextClip(
                subtitle_text,
                fontsize=52,
                color="white",
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=3,
                method="caption",
                size=(shorts_res[0] - 100, None),
            )
            .set_duration(duration)
            .set_position(("center", shorts_res[1] - 350))
        )
        video = CompositeVideoClip([img_clip, txt_clip], size=shorts_res)
    except Exception:
        video = img_clip

    video = video.set_audio(audio)
    return video


def assemble_shorts(config: dict, script_data: dict, assets: dict, output_dir: str,
                    shorts_script: dict = None, shorts_audio_files: list = None) -> str:
    """Assemble a YouTube Shorts video (vertical, <=60 seconds).

    If shorts_script and shorts_audio_files are provided, uses the re-hooked
    shorts-specific script. Otherwise falls back to truncating the full video scenes.
    """
    scene_clips = []
    total_duration = 0.0
    max_duration = 59.0

    use_script = shorts_script or script_data
    use_audio = shorts_audio_files or assets["audio_files"]

    for i in range(len(use_script["scenes"])):
        if i >= len(use_audio):
            break

        audio_path = use_audio[i]
        audio = AudioFileClip(audio_path)
        padding = 0.2 if shorts_script else 0.3
        scene_dur = audio.duration + padding
        audio.close()

        if total_duration + scene_dur > max_duration:
            break

        # Map to correct original image using scene_number from shorts script
        scene = use_script["scenes"][i]
        scene_num = scene.get("scene_number", i + 1)
        img_idx = scene_num - 1  # scene_number is 1-indexed
        if img_idx < 0 or img_idx >= len(assets["image_files"]):
            img_idx = min(i, len(assets["image_files"]) - 1)
        image_path = assets["image_files"][img_idx]

        narration = scene["narration"]
        if i == 0:
            narration = use_script["intro_hook"] + " " + narration

        print(f"  Shorts: assembling scene {i+1}...")
        clip = create_shorts_clip(image_path, audio_path, narration, config)
        scene_clips.append(clip)
        total_duration += scene_dur

    if not scene_clips:
        raise Exception("No scenes fit within 60 seconds for Shorts")

    # Apply crossfade transitions (shorter for shorts)
    t = TRANSITION_DURATION * 0.6  # ~0.36s for fast-paced shorts
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)

    if final.duration > max_duration:
        final = final.subclip(0, max_duration)

    # Add background music if available
    music_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "music")
    music_files = [f for f in os.listdir(music_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(music_dir) else []

    if music_files:
        bg_music_path = os.path.join(music_dir, random.choice(music_files))
        bg_music = AudioFileClip(bg_music_path).volumex(config["video"]["bg_music_volume"])
        if bg_music.duration < final.duration:
            loops = int(final.duration / bg_music.duration) + 1
            bg_music = concatenate_audioclips([bg_music] * loops)
        bg_music = bg_music.subclip(0, final.duration)
        final = final.set_audio(CompositeAudioClip([final.audio, bg_music]))

    output_path = os.path.join(output_dir, "shorts_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    for clip in scene_clips:
        clip.close()
    final.close()

    print(f"  Shorts video: {total_duration:.1f}s, {len(scene_clips)} scenes")
    return output_path


# ── Animated video assembly ──────────────────────────────────────────

def _add_subtitles_to_clip(clip, narration_text: str, config: dict,
                           resolution: tuple, vertical: bool = False):
    """Add subtitle overlay to a video clip. Returns CompositeVideoClip."""
    max_chars = 25 if vertical else 50
    font_size = 52 if vertical else config["video"]["subtitle_font_size"]
    color = "white" if vertical else config["video"]["subtitle_color"]
    y_pos = resolution[1] - 350 if vertical else resolution[1] - 180

    words = narration_text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > max_chars:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    subtitle_text = "\n".join(lines)

    try:
        txt_clip = (
            TextClip(
                subtitle_text,
                fontsize=font_size,
                color=color,
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=2 if not vertical else 3,
                method="caption",
                size=(resolution[0] - (100 if vertical else 200), None),
            )
            .set_duration(clip.duration)
            .set_position(("center", y_pos))
        )
        return CompositeVideoClip([clip, txt_clip], size=resolution)
    except Exception:
        print("    Warning: Subtitles skipped (install ImageMagick for subtitle support)")
        return clip


def _add_bg_music(final_clip, config: dict, lang_dir: str = None, music_subdir: str = None):
    """Add background music to a clip. Uses AI-generated music if configured, else local files.

    music_subdir: if set (e.g. "lullaby"), look in data/music/{music_subdir}/ first,
                  then fall back to data/music/.
    """
    bg_music_path = None
    bg_cfg = config.get("bg_music", {})

    # Try AI-generated music first
    if bg_cfg.get("provider") == "replicate" and lang_dir:
        cached = os.path.join(lang_dir, "bg_music.mp3")
        if os.path.exists(cached):
            bg_music_path = cached
        else:
            from agents.asset_agent import generate_bg_music_ai
            bg_music_path = generate_bg_music_ai(config, cached)

    # Fall back to local music files
    if not bg_music_path:
        base_music_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "music")
        # If a subdir is requested (e.g. "lullaby"), try it first
        if music_subdir:
            sub_dir = os.path.join(base_music_dir, music_subdir)
            sub_files = [f for f in os.listdir(sub_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(sub_dir) else []
            if sub_files:
                bg_music_path = os.path.join(sub_dir, random.choice(sub_files))
        # Fall back to main music dir
        if not bg_music_path:
            music_dir = base_music_dir
            music_files = [f for f in os.listdir(music_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(music_dir) else []
            if music_files:
                bg_music_path = os.path.join(music_dir, random.choice(music_files))

    if bg_music_path:
        bg_music = AudioFileClip(bg_music_path).volumex(config["video"]["bg_music_volume"])
        if bg_music.duration < final_clip.duration:
            loops = int(final_clip.duration / bg_music.duration) + 1
            bg_music = concatenate_audioclips([bg_music] * loops)
        bg_music = bg_music.subclip(0, final_clip.duration)
        return final_clip.set_audio(CompositeAudioClip([final_clip.audio, bg_music]))

    return final_clip


def assemble_animated_video(config: dict, script_data: dict,
                            animated_clips: list, audio_files: list,
                            output_dir: str) -> str:
    """Assemble final video from pre-animated clips + audio files."""
    resolution = tuple(config["video"]["resolution"])
    scene_clips = []

    for i in range(len(script_data["scenes"])):
        if i >= len(animated_clips) or i >= len(audio_files):
            break

        clip_path = animated_clips[i]
        audio_path = audio_files[i]
        narration = script_data["scenes"][i]["narration"]

        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]

        print(f"  Assembling animated scene {i+1}...")
        video_clip = VideoFileClip(clip_path).resize(resolution)
        audio = AudioFileClip(audio_path)

        # Match clip duration to audio
        target_dur = audio.duration + 0.5
        if video_clip.duration < target_dur:
            # Loop the clip to fill the audio duration
            from moviepy.editor import vfx
            loops = int(target_dur / video_clip.duration) + 1
            video_clip = video_clip.fx(vfx.loop, n=loops)
        video_clip = video_clip.subclip(0, target_dur)

        # Add subtitles
        video_clip = _add_subtitles_to_clip(video_clip, narration, config, resolution)
        video_clip = video_clip.set_audio(audio)
        scene_clips.append(video_clip)

    # Apply crossfade transitions
    t = TRANSITION_DURATION
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)
    final = _add_bg_music(final, config, lang_dir=output_dir)

    output_path = os.path.join(output_dir, "final_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    for clip in scene_clips:
        clip.close()
    final.close()

    return output_path


def _prepare_vertical_clip(clip, target_w: int = 1080, target_h: int = 1920):
    """Convert a landscape video clip to vertical with blurred background."""
    import numpy as np

    cw, ch = clip.size

    def vertical_frame(get_frame, t):
        frame = Image.fromarray(get_frame(t))

        # Blurred background
        bg = frame.copy().resize((target_w, target_h), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
        bg = ImageEnhance.Brightness(bg).enhance(0.35)

        # Scale foreground to fit width
        scale = target_w / frame.size[0]
        new_h = int(frame.size[1] * scale)
        fg = frame.resize((target_w, new_h), Image.LANCZOS)

        # Center
        y_offset = (target_h - new_h) // 2
        bg.paste(fg, (0, y_offset))
        return np.array(bg)

    return clip.fl(vertical_frame).resize((target_w, target_h))


def assemble_animated_shorts(config: dict, script_data: dict,
                             animated_clips: list, audio_files: list,
                             output_dir: str,
                             shorts_script: dict = None,
                             shorts_audio: list = None) -> str:
    """Assemble animated Shorts video (vertical, <=60s)."""
    shorts_res = (1080, 1920)
    scene_clips = []
    total_duration = 0.0
    max_duration = 59.0

    use_script = shorts_script or script_data
    use_audio = shorts_audio or audio_files

    for i in range(len(use_script["scenes"])):
        if i >= len(use_audio):
            break

        audio_path = use_audio[i]
        audio = AudioFileClip(audio_path)
        padding = 0.2 if shorts_script else 0.3
        scene_dur = audio.duration + padding
        audio.close()

        if total_duration + scene_dur > max_duration:
            break

        # Map to correct animated clip using scene_number
        scene = use_script["scenes"][i]
        scene_num = scene.get("scene_number", i + 1)
        clip_idx = scene_num - 1
        if clip_idx < 0 or clip_idx >= len(animated_clips):
            clip_idx = min(i, len(animated_clips) - 1)

        clip_path = animated_clips[clip_idx]
        narration = scene["narration"]
        if i == 0:
            narration = use_script["intro_hook"] + " " + narration

        print(f"  Animated Shorts: scene {i+1}...")
        video_clip = VideoFileClip(clip_path)

        # Match duration to audio
        audio = AudioFileClip(audio_path)
        target_dur = audio.duration + padding
        if video_clip.duration < target_dur:
            from moviepy.editor import vfx
            loops = int(target_dur / video_clip.duration) + 1
            video_clip = video_clip.fx(vfx.loop, n=loops)
        video_clip = video_clip.subclip(0, target_dur)

        # Convert to vertical with blurred background
        video_clip = _prepare_vertical_clip(video_clip, shorts_res[0], shorts_res[1])

        # Add subtitles
        video_clip = _add_subtitles_to_clip(video_clip, narration, config,
                                            shorts_res, vertical=True)
        video_clip = video_clip.set_audio(audio)
        scene_clips.append(video_clip)
        total_duration += scene_dur

    if not scene_clips:
        raise Exception("No animated scenes fit within 60 seconds for Shorts")

    t = TRANSITION_DURATION * 0.6
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)
    if final.duration > max_duration:
        final = final.subclip(0, max_duration)

    final = _add_bg_music(final, config, lang_dir=output_dir)

    output_path = os.path.join(output_dir, "shorts_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    for clip in scene_clips:
        clip.close()
    final.close()

    print(f"  Animated Shorts: {total_duration:.1f}s, {len(scene_clips)} scenes")
    return output_path


# ── Poem & Lullaby assembly (new — does not touch existing functions) ──

def _make_poem_lines_clip(lines: list, duration: float, resolution: tuple):
    """Show 4 poem lines as read-along text at the top of the frame."""
    if not lines:
        return None
    text = "\n".join(lines)
    try:
        return (
            TextClip(
                text,
                fontsize=36,
                color="white",
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=1,
                method="caption",
                size=(resolution[0] - 100, None),
            )
            .set_duration(duration)
            .set_position(("center", 40))
        )
    except Exception:
        return None


def assemble_poem_video(config: dict, script_data: dict,
                        animated_clips: list, audio_files: list,
                        output_dir: str) -> str:
    """Assemble poem video with read-along text overlay at top of each scene.
    New function — does not touch assemble_animated_video().
    """
    resolution = tuple(config["video"]["resolution"])
    scene_clips = []

    for i, scene in enumerate(script_data["scenes"]):
        if i >= len(animated_clips) or i >= len(audio_files):
            break

        clip_path = animated_clips[i]
        audio_path = audio_files[i]
        narration = scene["narration"]

        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]

        print(f"  Poem scene {i+1}...")
        video_clip = VideoFileClip(clip_path).resize(resolution)
        audio = AudioFileClip(audio_path)

        target_dur = audio.duration + 0.5
        if video_clip.duration < target_dur:
            from moviepy.editor import vfx
            loops = int(target_dur / video_clip.duration) + 1
            video_clip = video_clip.fx(vfx.loop, n=loops)
        video_clip = video_clip.subclip(0, target_dur)

        # Bottom subtitle (narration)
        video_clip = _add_subtitles_to_clip(video_clip, narration, config, resolution)

        # Top read-along poem lines overlay
        poem_lines = scene.get("lines", [])
        lines_clip = _make_poem_lines_clip(poem_lines, target_dur, resolution)
        if lines_clip:
            video_clip = CompositeVideoClip([video_clip, lines_clip], size=resolution)

        video_clip = video_clip.set_audio(audio)
        scene_clips.append(video_clip)

    t = TRANSITION_DURATION
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)
    final = _add_bg_music(final, config, lang_dir=output_dir)

    output_path = os.path.join(output_dir, "poem_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    for clip in scene_clips:
        clip.close()
    final.close()
    return output_path


def assemble_lullaby_video(config: dict, script_data: dict,
                           animated_clips: list, audio_files: list,
                           output_dir: str) -> str:
    """Assemble lullaby video with 1.0s gentle transitions and lullaby music.
    New function — does not touch assemble_animated_video().
    """
    resolution = tuple(config["video"]["resolution"])
    scene_clips = []

    for i, scene in enumerate(script_data["scenes"]):
        if i >= len(animated_clips) or i >= len(audio_files):
            break

        clip_path = animated_clips[i]
        audio_path = audio_files[i]
        narration = scene["narration"]

        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]

        print(f"  Lullaby scene {i+1}...")
        video_clip = VideoFileClip(clip_path).resize(resolution)
        audio = AudioFileClip(audio_path)

        target_dur = audio.duration + 0.8  # extra padding for calm feel
        if video_clip.duration < target_dur:
            from moviepy.editor import vfx
            loops = int(target_dur / video_clip.duration) + 1
            video_clip = video_clip.fx(vfx.loop, n=loops)
        video_clip = video_clip.subclip(0, target_dur)

        video_clip = _add_subtitles_to_clip(video_clip, narration, config, resolution)
        video_clip = video_clip.set_audio(audio)
        scene_clips.append(video_clip)

    t = LULLABY_TRANSITION  # 1.0s instead of 0.6s
    for i in range(len(scene_clips)):
        if i > 0:
            scene_clips[i] = scene_clips[i].crossfadein(t)
        if i < len(scene_clips) - 1:
            scene_clips[i] = scene_clips[i].crossfadeout(t)

    final = concatenate_videoclips(scene_clips, method="compose", padding=-t)
    # Try lullaby-specific music first, fall back to main music dir
    final = _add_bg_music(final, config, lang_dir=output_dir, music_subdir="lullaby")

    output_path = os.path.join(output_dir, "lullaby_video.mp4")
    final.write_videofile(
        output_path,
        fps=config["video"]["fps"],
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    for clip in scene_clips:
        clip.close()
    final.close()
    return output_path
