import os
import random
from moviepy import (
    ImageClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, concatenate_audioclips,
)


def create_scene_clip(image_path: str, audio_path: str, narration_text: str,
                      config: dict) -> CompositeVideoClip:
    """Create a single scene clip with image, audio, and subtitles."""
    resolution = tuple(config["video"]["resolution"])

    # Load audio to get duration
    audio = AudioFileClip(audio_path)
    duration = audio.duration + 0.5  # small padding

    # Create image clip resized to target resolution
    img_clip = ImageClip(image_path, duration=duration).resized(resolution)

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
                text=subtitle_text,
                font_size=config["video"]["subtitle_font_size"],
                color=config["video"]["subtitle_color"],
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=2,
                method="caption",
                size=(resolution[0] - 200, None),
                duration=duration,
            )
            .with_position(("center", resolution[1] - 180))
        )
        video = CompositeVideoClip([img_clip, txt_clip], size=resolution)
    except Exception:
        # Fallback without subtitles if TextClip fails (ImageMagick not installed)
        print("    Warning: Subtitles skipped (install ImageMagick for subtitle support)")
        video = img_clip

    video = video.with_audio(audio)
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

    # Concatenate all scenes
    final = concatenate_videoclips(scene_clips, method="compose")

    # Add background music if available
    music_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "music")
    music_files = [f for f in os.listdir(music_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(music_dir) else []

    if music_files:
        bg_music_path = os.path.join(music_dir, random.choice(music_files))
        bg_music = AudioFileClip(bg_music_path).with_volume_scaled(config["video"]["bg_music_volume"])
        # Loop if needed
        if bg_music.duration < final.duration:
            loops = int(final.duration / bg_music.duration) + 1
            bg_music = concatenate_audioclips([bg_music] * loops)
        bg_music = bg_music.subclipped(0, final.duration)

        final = final.with_audio(CompositeAudioClip([final.audio, bg_music]))

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


def create_shorts_clip(image_path: str, audio_path: str, narration_text: str,
                       config: dict) -> CompositeVideoClip:
    """Create a single scene clip in vertical (9:16) format for Shorts."""
    shorts_res = (1080, 1920)

    audio = AudioFileClip(audio_path)
    duration = audio.duration + 0.3

    # Resize image to fill vertical frame (crop center)
    img_clip = ImageClip(image_path, duration=duration)
    # Scale to fill width, then crop height to 1920
    w, h = img_clip.size
    scale = shorts_res[0] / w
    new_h = int(h * scale)
    img_clip = img_clip.resized((shorts_res[0], new_h))
    # Center crop vertically
    if new_h > shorts_res[1]:
        y_offset = (new_h - shorts_res[1]) // 2
        img_clip = img_clip.cropped(y1=y_offset, y2=y_offset + shorts_res[1])
    elif new_h < shorts_res[1]:
        # If image is too short, just resize to exact resolution
        img_clip = img_clip.resized(shorts_res)

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
                text=subtitle_text,
                font_size=52,
                color="white",
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=3,
                method="caption",
                size=(shorts_res[0] - 100, None),
                duration=duration,
            )
            .with_position(("center", shorts_res[1] - 350))
        )
        video = CompositeVideoClip([img_clip, txt_clip], size=shorts_res)
    except Exception:
        video = img_clip

    video = video.with_audio(audio)
    return video


def assemble_shorts(config: dict, script_data: dict, assets: dict, output_dir: str) -> str:
    """Assemble a YouTube Shorts video (vertical, ≤60 seconds) from the best scenes."""
    scene_clips = []
    total_duration = 0.0
    max_duration = 59.0  # keep under 60s

    # Pick scenes that fit within 60 seconds
    for i in range(len(script_data["scenes"])):
        audio_path = assets["audio_files"][i]
        audio = AudioFileClip(audio_path)
        scene_dur = audio.duration + 0.3
        audio.close()

        if total_duration + scene_dur > max_duration:
            break

        image_path = assets["image_files"][i]
        narration = script_data["scenes"][i]["narration"]
        if i == 0:
            narration = script_data["intro_hook"] + " " + narration

        print(f"  Shorts: assembling scene {i+1}...")
        clip = create_shorts_clip(image_path, audio_path, narration, config)
        scene_clips.append(clip)
        total_duration += scene_dur

    if not scene_clips:
        raise Exception("No scenes fit within 60 seconds for Shorts")

    final = concatenate_videoclips(scene_clips, method="compose")

    # Trim to exactly 59 seconds if somehow over
    if final.duration > max_duration:
        final = final.subclipped(0, max_duration)

    # Add background music if available
    music_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "music")
    music_files = [f for f in os.listdir(music_dir) if f.endswith((".mp3", ".wav"))] if os.path.exists(music_dir) else []

    if music_files:
        bg_music_path = os.path.join(music_dir, random.choice(music_files))
        bg_music = AudioFileClip(bg_music_path).with_volume_scaled(config["video"]["bg_music_volume"])
        if bg_music.duration < final.duration:
            loops = int(final.duration / bg_music.duration) + 1
            bg_music = concatenate_audioclips([bg_music] * loops)
        bg_music = bg_music.subclipped(0, final.duration)
        final = final.with_audio(CompositeAudioClip([final.audio, bg_music]))

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
