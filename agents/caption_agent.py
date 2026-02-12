"""
Automated caption & SRT generation for videos.
Builds SRT subtitle files from script narration + audio durations for SEO and accessibility.
"""

import os
from moviepy.editor import AudioFileClip


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(script_data: dict, audio_files: list, output_dir: str,
                 language: str = "en") -> str:
    """Generate an SRT subtitle file from script narration and audio durations.

    Each scene becomes one or more subtitle blocks, timed to the audio.
    Returns path to the generated .srt file.
    """
    srt_blocks = []
    current_time = 0.0
    block_num = 1

    for i, scene in enumerate(script_data["scenes"]):
        # Get audio duration for this scene
        audio = AudioFileClip(audio_files[i])
        scene_duration = audio.duration
        audio.close()

        # Build narration text (same logic as voiceover generation)
        narration = scene["narration"]
        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]

        # Split long narrations into subtitle chunks (~10 words each)
        words = narration.split()
        chunks = []
        current_chunk = []
        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= 10:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Distribute time evenly across chunks within this scene
        chunk_duration = scene_duration / max(len(chunks), 1)

        for chunk in chunks:
            start = current_time
            end = current_time + chunk_duration
            srt_blocks.append(
                f"{block_num}\n"
                f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
                f"{chunk}\n"
            )
            block_num += 1
            current_time = end

        # Add padding between scenes
        current_time += 0.5

    # Write SRT file
    lang_suffix = language if language != "English" else "en"
    srt_path = os.path.join(output_dir, f"captions_{lang_suffix}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_blocks))

    return srt_path


def generate_shorts_srt(script_data: dict, audio_files: list, output_dir: str,
                        language: str = "en") -> str:
    """Generate SRT for shorts video (only scenes that fit in 59s)."""
    srt_blocks = []
    current_time = 0.0
    block_num = 1
    max_duration = 59.0

    for i, scene in enumerate(script_data["scenes"]):
        audio = AudioFileClip(audio_files[i])
        scene_duration = audio.duration
        audio.close()

        if current_time + scene_duration > max_duration:
            break

        narration = scene["narration"]
        if i == 0:
            narration = script_data["intro_hook"] + " " + narration

        words = narration.split()
        chunks = []
        current_chunk = []
        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= 8:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        chunk_duration = scene_duration / max(len(chunks), 1)

        for chunk in chunks:
            start = current_time
            end = current_time + chunk_duration
            srt_blocks.append(
                f"{block_num}\n"
                f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
                f"{chunk}\n"
            )
            block_num += 1
            current_time = end

        current_time += 0.3

    lang_suffix = language if language != "English" else "en"
    srt_path = os.path.join(output_dir, f"shorts_captions_{lang_suffix}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_blocks))

    return srt_path


def generate_caption_text(script_data: dict, language: str = "English") -> str:
    """Build a plain text transcript for SEO boost in video descriptions."""
    lines = []
    lines.append("--- Transcript ---")
    for i, scene in enumerate(script_data["scenes"]):
        narration = scene["narration"]
        if i == 0:
            narration = script_data["intro_hook"] + " " + narration
        elif i == len(script_data["scenes"]) - 1:
            narration = narration + " " + script_data["outro"]
        lines.append(narration)
    return "\n".join(lines)
