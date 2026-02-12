"""
YouTube Kids Video Automation - Main Orchestrator
Hinglish content pipeline: --video (2-3 min) or --shorts (~1 min)
"""

import os
import sys
import json
import copy
import shutil
import yaml
import schedule
import time
from datetime import datetime

from agents.topic_agent import generate_topic
from agents.script_agent import generate_script, generate_shorts_script
from agents.asset_agent import (
    generate_images, generate_voiceover_only, generate_lullaby_voiceover, pick_voice,
)
from agents.video_agent import (
    assemble_animated_video, assemble_animated_shorts,
    assemble_poem_video, assemble_lullaby_video,
)
from agents.poem_agent import generate_poem_script
from agents.lullaby_agent import generate_lullaby_script
from agents.animation_agent import animate_all_scenes
from agents.metadata_agent import (
    generate_metadata, generate_youtube_thumbnail,
    generate_shorts_thumbnail, generate_shorts_metadata,
)
from agents.upload_agent import upload_video, upload_captions
from agents.caption_agent import generate_srt
from agents.db import init_db, insert_video, update_video_shorts
from agents.notification_agent import send_run_summary


BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
LANG_CODE = "hi"
LANG_NAME = "Hindi"   # triggers Hinglish mode in script_agent


def load_config():
    config_path = os.path.join(BASE_DIR, "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def log_run(run_dir: str, step: str, status: str, data: dict = None):
    log_file = os.path.join(run_dir, "run_log.json")
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            log = json.load(f)
    else:
        log = {"started_at": datetime.now().isoformat(), "steps": {}}
    log["steps"][step] = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }
    with open(log_file, "w") as f:
        json.dump(log, f, indent=2)


def _prepare_config(config: dict) -> dict:
    """Deep-copy config and apply soft animation image style override."""
    cfg = copy.deepcopy(config)
    anim_style = cfg.get("animation", {}).get(
        "image_style",
        "soft cartoon illustration, smooth gentle colors, dreamy pastel tones, "
        "kid-friendly, soft edges, Pixar-like warmth, no text, no words",
    )
    cfg["content"]["image_style"] = anim_style
    return cfg


def _cleanup(lang_dir: str, image_dir: str):
    """Remove large intermediate files after a successful upload."""
    for folder in ["audio", "animated_clips"]:
        p = os.path.join(lang_dir, folder)
        if os.path.exists(p):
            shutil.rmtree(p)
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)


# ── Video pipeline (2–3 min landscape) ───────────────────────────────────────

def run_video_pipeline(config: dict, upload: bool = True) -> dict:
    """Generate a 2–3 min animated Hinglish video and upload to YouTube."""
    config = _prepare_config(config)
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(BASE_DIR, "output", f"video_{timestamp}")
    lang_dir  = os.path.join(run_dir, LANG_CODE)
    image_dir = os.path.join(run_dir, "images")
    os.makedirs(lang_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "videos": []}
    result      = {"language": LANG_NAME, "language_code": LANG_CODE,
                   "video_url": None, "shorts_url": None}

    print(f"\n{'='*60}")
    print(f"  Video Pipeline (Hinglish) — {timestamp}")
    print(f"{'='*60}\n")

    try:
        # 1. Topic
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # 2. Hinglish script (visual_description stays in English for AI image prompts)
        print("[2] Writing Hinglish script...")
        script_data = generate_script(config, topic_data, language=LANG_NAME)
        print(f"  Title: {script_data['title']}")
        print(f"  Scenes: {len(script_data['scenes'])}")
        log_run(run_dir, "script", "success", script_data)
        with open(os.path.join(run_dir, "script.json"), "w") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # 3. Generate soft/dreamy images
        print("[3] Generating images...")
        image_files = generate_images(config, script_data, image_dir)
        log_run(run_dir, "images", "success", {"count": len(image_files)})

        # 4. Indian accent voiceover
        voice = pick_voice(config, LANG_CODE)
        print("[4] Generating Hinglish voiceover...")
        audio_files = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
        log_run(run_dir, "voiceover", "success", {"voice": voice})

        # 5. Ken Burns animation
        print("[5] Animating scenes (Ken Burns)...")
        animated_clips = animate_all_scenes(
            config, image_files, audio_files, script_data, lang_dir
        )
        log_run(run_dir, "animation", "success", {"clips": len(animated_clips)})

        # 6. Captions / SRT
        print("[6] Generating captions...")
        srt_path = generate_srt(script_data, audio_files, lang_dir, language=LANG_CODE)

        # 7. Assemble animated video (landscape 1280×720) + AI background music
        print("[7] Assembling video...")
        video_path = assemble_animated_video(
            config, script_data, animated_clips, audio_files, lang_dir
        )
        print(f"  Saved: {video_path}")
        log_run(run_dir, "video", "success", {"path": video_path})

        # 8. Metadata + thumbnail
        print("[8] Generating metadata...")
        metadata = generate_metadata(config, topic_data, script_data, language=LANG_NAME)
        yt_thumb  = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
        print(f"  Title: {metadata['title']}")
        log_run(run_dir, "metadata", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 9. Upload
        if upload:
            try:
                print("[9] Uploading to YouTube...")
                video_url, video_id = upload_video(config, video_path, metadata, yt_thumb)
                result["video_url"] = video_url
                log_run(run_dir, "upload", "success", {"url": video_url})
                print(f"  Live: {video_url}")
                if video_id and srt_path:
                    upload_captions(config, video_id, srt_path, language=LANG_CODE)
                insert_video(
                    video_id=video_id, platform="youtube", language=LANG_CODE,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=metadata["title"], run_dir=run_dir,
                )
            except Exception as e:
                print(f"  Upload failed: {e}")
                log_run(run_dir, "upload", "failed", {"error": str(e)})
        else:
            print("[9] Upload skipped (--no-upload mode)")

        if upload:
            _cleanup(lang_dir, image_dir)

        run_summary["videos"].append(result)

        print(f"\n{'='*60}")
        print(f"  Video Pipeline complete!  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


# ── Shorts pipeline (~1 min vertical) ────────────────────────────────────────

def run_shorts_pipeline(config: dict, upload: bool = True) -> dict:
    """Generate a ~1 min animated Hinglish Short and upload to YouTube."""
    config = _prepare_config(config)
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(BASE_DIR, "output", f"shorts_{timestamp}")
    lang_dir  = os.path.join(run_dir, LANG_CODE)
    image_dir = os.path.join(run_dir, "images")
    os.makedirs(lang_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "videos": []}
    result      = {"language": LANG_NAME, "language_code": LANG_CODE,
                   "video_url": None, "shorts_url": None}

    print(f"\n{'='*60}")
    print(f"  Shorts Pipeline (Hinglish) — {timestamp}")
    print(f"{'='*60}\n")

    try:
        # 1. Topic
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # 2. Full Hinglish script (for image visual descriptions)
        print("[2] Writing base Hinglish script...")
        base_script = generate_script(config, topic_data, language=LANG_NAME)
        print(f"  Base title: {base_script['title']}")
        log_run(run_dir, "script_base", "success", base_script)

        # 3. Soft/dreamy images
        print("[3] Generating images...")
        image_files = generate_images(config, base_script, image_dir)
        log_run(run_dir, "images", "success", {"count": len(image_files)})

        # 4. Shorts-optimised script (punchy, 3 scenes, ~1 min)
        print("[4] Writing Shorts script (punchy, ~1 min)...")
        script_data = generate_shorts_script(config, topic_data, base_script, LANG_NAME)
        print(f"  Shorts title: {script_data['title']}")
        print(f"  Scenes: {len(script_data['scenes'])}")
        log_run(run_dir, "script_shorts", "success", script_data)
        with open(os.path.join(run_dir, "script.json"), "w") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # 5. Indian accent voiceover for shorts script
        voice = pick_voice(config, LANG_CODE)
        print("[5] Generating Hinglish voiceover...")
        shorts_audio = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
        log_run(run_dir, "voiceover", "success", {"voice": voice})

        # 6. Ken Burns animation (using base_script for scene-image mapping)
        print("[6] Animating scenes (Ken Burns)...")
        animated_clips = animate_all_scenes(
            config, image_files, shorts_audio, base_script, lang_dir
        )
        log_run(run_dir, "animation", "success", {"clips": len(animated_clips)})

        # 7. Assemble vertical Shorts (1080×1920) + AI background music
        print("[7] Assembling Shorts video (vertical)...")
        shorts_path = assemble_animated_shorts(
            config, base_script, animated_clips, shorts_audio, lang_dir,
            shorts_script=script_data, shorts_audio=shorts_audio,
        )
        print(f"  Saved: {shorts_path}")
        log_run(run_dir, "shorts_video", "success", {"path": shorts_path})

        # 8. Metadata + thumbnail
        print("[8] Generating metadata...")
        metadata        = generate_metadata(config, topic_data, script_data, language=LANG_NAME)
        shorts_metadata = generate_shorts_metadata(metadata)
        thumb           = generate_shorts_thumbnail(config, metadata, image_files[0], lang_dir)
        print(f"  Title: {shorts_metadata['title']}")
        log_run(run_dir, "metadata", "success", shorts_metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(shorts_metadata, f, indent=2, ensure_ascii=False)

        # 9. Upload
        if upload:
            try:
                print("[9] Uploading to YouTube Shorts...")
                shorts_url, shorts_vid = upload_video(
                    config, shorts_path, shorts_metadata, thumb
                )
                result["shorts_url"] = shorts_url
                log_run(run_dir, "upload", "success", {"url": shorts_url})
                print(f"  Live: {shorts_url}")
                insert_video(
                    video_id=shorts_vid, platform="youtube", language=LANG_CODE,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=shorts_metadata["title"], run_dir=run_dir,
                )
            except Exception as e:
                print(f"  Upload failed: {e}")
                log_run(run_dir, "upload", "failed", {"error": str(e)})
        else:
            print("[9] Upload skipped (--no-upload mode)")

        if upload:
            _cleanup(lang_dir, image_dir)

        run_summary["videos"].append(result)

        print(f"\n{'='*60}")
        print(f"  Shorts Pipeline complete!  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


# ── Poem pipeline (structured rhyming poem with read-along overlay) ───────────

def run_poem_pipeline(config: dict, upload: bool = True) -> dict:
    """Generate a Hinglish rhyming poem video with read-along text overlay."""
    config = _prepare_config(config)
    config["content"]["niche"] = "children's rhyming poem"
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(BASE_DIR, "output", f"poem_{timestamp}")
    lang_dir  = os.path.join(run_dir, LANG_CODE)
    image_dir = os.path.join(run_dir, "images")
    os.makedirs(lang_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "videos": []}
    result      = {"language": LANG_NAME, "language_code": LANG_CODE,
                   "video_url": None, "shorts_url": None}

    print(f"\n{'='*60}")
    print(f"  Poem Pipeline (Hinglish) — {timestamp}")
    print(f"{'='*60}\n")

    try:
        # 1. Topic
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # 2. Poem script (verse + chorus structure, lines[] for read-along)
        print("[2] Writing Hinglish poem script...")
        script_data = generate_poem_script(config, topic_data)
        print(f"  Title: {script_data['title']}")
        print(f"  Scenes: {len(script_data['scenes'])}")
        log_run(run_dir, "script", "success", script_data)
        with open(os.path.join(run_dir, "script.json"), "w") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # 3. Generate images
        print("[3] Generating images...")
        image_files = generate_images(config, script_data, image_dir)
        log_run(run_dir, "images", "success", {"count": len(image_files)})

        # 4. Voiceover (regular rate — poem pace is natural)
        voice = pick_voice(config, LANG_CODE)
        print("[4] Generating Hinglish voiceover...")
        audio_files = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
        log_run(run_dir, "voiceover", "success", {"voice": voice})

        # 5. Ken Burns animation
        print("[5] Animating scenes (Ken Burns)...")
        animated_clips = animate_all_scenes(
            config, image_files, audio_files, script_data, lang_dir
        )
        log_run(run_dir, "animation", "success", {"clips": len(animated_clips)})

        # 6. Assemble poem video with read-along text overlay
        print("[6] Assembling poem video...")
        video_path = assemble_poem_video(
            config, script_data, animated_clips, audio_files, lang_dir
        )
        print(f"  Saved: {video_path}")
        log_run(run_dir, "video", "success", {"path": video_path})

        # 7. Metadata + thumbnail
        print("[7] Generating metadata...")
        metadata = generate_metadata(config, topic_data, script_data, language=LANG_NAME)
        yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
        print(f"  Title: {metadata['title']}")
        log_run(run_dir, "metadata", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 8. Upload
        if upload:
            try:
                print("[8] Uploading to YouTube...")
                video_url, video_id = upload_video(config, video_path, metadata, yt_thumb)
                result["video_url"] = video_url
                log_run(run_dir, "upload", "success", {"url": video_url})
                print(f"  Live: {video_url}")
                insert_video(
                    video_id=video_id, platform="youtube", language=LANG_CODE,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=metadata["title"], run_dir=run_dir,
                )
            except Exception as e:
                print(f"  Upload failed: {e}")
                log_run(run_dir, "upload", "failed", {"error": str(e)})
        else:
            print("[8] Upload skipped (--no-upload mode)")

        if upload:
            _cleanup(lang_dir, image_dir)

        run_summary["videos"].append(result)

        print(f"\n{'='*60}")
        print(f"  Poem Pipeline complete!  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


# ── Lullaby pipeline (soothing bedtime lullaby, slower TTS) ───────────────────

def run_lullaby_pipeline(config: dict, upload: bool = True) -> dict:
    """Generate a soothing Hinglish lullaby video with slower TTS and gentle transitions."""
    config = _prepare_config(config)
    config["content"]["niche"] = "bedtime lullaby for kids"
    # Soft pastel image style for lullaby visuals
    config["content"]["image_style"] = (
        "soft dreamy watercolor illustration, pastel lavender and blue tones, "
        "sleepy animals, moonlit night sky, gentle stars, cozy warm bedroom, "
        "soft glowing light, no text, no words, no sharp edges"
    )
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(BASE_DIR, "output", f"lullaby_{timestamp}")
    lang_dir  = os.path.join(run_dir, LANG_CODE)
    image_dir = os.path.join(run_dir, "images")
    os.makedirs(lang_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "videos": []}
    result      = {"language": LANG_NAME, "language_code": LANG_CODE,
                   "video_url": None, "shorts_url": None}

    print(f"\n{'='*60}")
    print(f"  Lullaby Pipeline (Hinglish) — {timestamp}")
    print(f"{'='*60}\n")

    try:
        # 1. Topic
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # 2. Lullaby script (4 scenes, verse-chorus structure)
        print("[2] Writing Hinglish lullaby script...")
        script_data = generate_lullaby_script(config, topic_data)
        print(f"  Title: {script_data['title']}")
        print(f"  Scenes: {len(script_data['scenes'])}")
        log_run(run_dir, "script", "success", script_data)
        with open(os.path.join(run_dir, "script.json"), "w") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # 3. Generate soft pastel images
        print("[3] Generating images...")
        image_files = generate_images(config, script_data, image_dir)
        log_run(run_dir, "images", "success", {"count": len(image_files)})

        # 4. Lullaby voiceover at -10% rate (slower, calming pace)
        voice = pick_voice(config, LANG_CODE)
        print("[4] Generating lullaby voiceover (rate=-10%)...")
        audio_files = generate_lullaby_voiceover(config, script_data, lang_dir, voice=voice)
        log_run(run_dir, "voiceover", "success", {"voice": voice})

        # 5. Ken Burns animation
        print("[5] Animating scenes (Ken Burns)...")
        animated_clips = animate_all_scenes(
            config, image_files, audio_files, script_data, lang_dir
        )
        log_run(run_dir, "animation", "success", {"clips": len(animated_clips)})

        # 6. Assemble lullaby video (1.0s gentle transitions + lullaby music)
        print("[6] Assembling lullaby video...")
        video_path = assemble_lullaby_video(
            config, script_data, animated_clips, audio_files, lang_dir
        )
        print(f"  Saved: {video_path}")
        log_run(run_dir, "video", "success", {"path": video_path})

        # 7. Metadata + thumbnail
        print("[7] Generating metadata...")
        metadata = generate_metadata(config, topic_data, script_data, language=LANG_NAME)
        yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
        print(f"  Title: {metadata['title']}")
        log_run(run_dir, "metadata", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 8. Upload
        if upload:
            try:
                print("[8] Uploading to YouTube...")
                video_url, video_id = upload_video(config, video_path, metadata, yt_thumb)
                result["video_url"] = video_url
                log_run(run_dir, "upload", "success", {"url": video_url})
                print(f"  Live: {video_url}")
                insert_video(
                    video_id=video_id, platform="youtube", language=LANG_CODE,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=metadata["title"], run_dir=run_dir,
                )
            except Exception as e:
                print(f"  Upload failed: {e}")
                log_run(run_dir, "upload", "failed", {"error": str(e)})
        else:
            print("[8] Upload skipped (--no-upload mode)")

        if upload:
            _cleanup(lang_dir, image_dir)

        run_summary["videos"].append(result)

        print(f"\n{'='*60}")
        print(f"  Lullaby Pipeline complete!  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler(config: dict):
    """Run video at 09:00 IST and shorts at 21:00 IST, every configured day."""
    upload_days = config["schedule"].get(
        "upload_days",
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    )
    day_map = {
        "Monday":    schedule.every().monday,
        "Tuesday":   schedule.every().tuesday,
        "Wednesday": schedule.every().wednesday,
        "Thursday":  schedule.every().thursday,
        "Friday":    schedule.every().friday,
        "Saturday":  schedule.every().saturday,
        "Sunday":    schedule.every().sunday,
    }

    for day in upload_days:
        day_map[day].at("09:00").do(run_video_pipeline,  config=config)
        day_map[day].at("21:00").do(run_shorts_pipeline, config=config)
        print(f"  Scheduled: {day}  09:00 → video   21:00 → shorts")

    print("\nScheduler running. Press Ctrl+C to stop.\n")
    while True:
        schedule.run_pending()
        time.sleep(60)


# ── Music pre-generation ──────────────────────────────────────────────────────

def generate_music_library(config: dict, count: int = 10):
    """Download 10 free royalty-free kids background music tracks to data/music/.
    Run once: python main.py --generate-music
    Source: FesliyanStudios.com — free for YouTube/commercial use, attribution appreciated
    """
    music_dir = os.path.join(BASE_DIR, "data", "music")
    os.makedirs(music_dir, exist_ok=True)

    BASE = "https://www.fesliyanstudios.com/musicfiles/"
    # Kids-friendly, instrumental tracks — FesliyanStudios.com (David Renda)
    # License: free for YouTube / commercial use; credit appreciated in description
    tracks = [
        (BASE + "2020-05-29_-_Curious_Kiddo_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Curious_Kiddo_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_curious_kiddo.mp3"),
        (BASE + "2020-05-22_-_Joyful_Lullaby_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-22_-_Joyful_Lullaby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_joyful_lullaby.mp3"),
        (BASE + "2020-05-22_-_Gentle_Lullaby_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-22_-_Gentle_Lullaby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_gentle_lullaby.mp3"),
        (BASE + "2021-12-06_-_Dancing_Silly_-_www.FesliyanStudios.com/"
               + "2021-12-06_-_Dancing_Silly_-_www.FesliyanStudios.com.mp3",
         "kids_dancing_silly.mp3"),
        (BASE + "2020-05-29_-_Play_Date_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Play_Date_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_play_date.mp3"),
        (BASE + "2020-06-05_-_Duck_Duck_Goose_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-06-05_-_Duck_Duck_Goose_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_duck_duck_goose.mp3"),
        (BASE + "2020-05-22_-_Dancing_Baby_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-22_-_Dancing_Baby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_dancing_baby.mp3"),
        (BASE + "2020-05-29_-_Clap_And_Sing_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Clap_And_Sing_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_clap_and_sing.mp3"),
        (BASE + "2021-12-15_-_Pig_In_The_Mud_-_www.FesliyanStudios.com/"
               + "2021-12-15_-_Pig_In_The_Mud_-_www.FesliyanStudios.com.mp3",
         "kids_pig_in_the_mud.mp3"),
        (BASE + "2020-05-19_-_GooGoo_GaGa_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-19_-_GooGoo_GaGa_-_www.FesliyanStudios.com_David_Renda.mp3",
         "kids_googoo_gaga.mp3"),
    ]

    import requests as req

    print(f"\nDownloading {count} kids background music tracks → data/music/\n")
    print("  Source: FesliyanStudios.com (David Renda) — free for commercial use")
    print("  Optional credit in description: 'Music by David Renda (FesliyanStudios.com)'\n")

    success = 0
    for i, (url, filename) in enumerate(tracks[:count]):
        out_path = os.path.join(music_dir, filename)
        if os.path.exists(out_path):
            print(f"  [{i+1}/{count}] Already exists: {filename}")
            success += 1
            continue
        try:
            print(f"  [{i+1}/{count}] Downloading {filename}...")
            r = req.get(url, timeout=60, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.fesliyanstudios.com/",
            })
            r.raise_for_status()
            if len(r.content) < 10_000:
                raise ValueError(f"Response too small ({len(r.content)} bytes) — likely an error page")
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"           Saved ({len(r.content)//1024} KB)")
            success += 1
        except Exception as e:
            print(f"           Failed: {e}")
        time.sleep(1)

    print(f"\nDone! {success}/{count} tracks in data/music/")
    if success < count:
        print("\n  Tip: Manually download kids music from https://www.fesliyanstudios.com/")
        print("  or https://pixabay.com/music/ and save .mp3 files to data/music/")


# ── Lullaby music pre-generation ──────────────────────────────────────────────

def generate_lullaby_music_library(config: dict, count: int = 6):
    """Seed data/music/lullaby/ with calm bedtime music tracks.

    Copies existing lullaby tracks from data/music/ as seeds, then downloads
    additional calm/sleep tracks from FesliyanStudios.com.
    Run once: python main.py --generate-lullaby-music
    """
    music_dir   = os.path.join(BASE_DIR, "data", "music")
    lullaby_dir = os.path.join(BASE_DIR, "data", "music", "lullaby")
    os.makedirs(lullaby_dir, exist_ok=True)

    # Seed: copy any existing lullaby-named tracks from the main music dir
    seeded = 0
    if os.path.exists(music_dir):
        for fname in os.listdir(music_dir):
            if "lullaby" in fname.lower() and fname.endswith((".mp3", ".wav")):
                src = os.path.join(music_dir, fname)
                dst = os.path.join(lullaby_dir, fname)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    print(f"  Seeded from data/music/: {fname}")
                seeded += 1

    BASE = "https://www.fesliyanstudios.com/musicfiles/"
    # Calm/gentle tracks suitable for lullaby/bedtime content
    tracks = [
        (BASE + "2020-05-22_-_Joyful_Lullaby_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-22_-_Joyful_Lullaby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "lullaby_joyful.mp3"),
        (BASE + "2020-05-22_-_Gentle_Lullaby_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-22_-_Gentle_Lullaby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "lullaby_gentle.mp3"),
        (BASE + "2020-09-18_-_Goodnight_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-09-18_-_Goodnight_-_www.FesliyanStudios.com_David_Renda.mp3",
         "lullaby_goodnight.mp3"),
        (BASE + "2019-04-04_-_A_Soft_Piano_Lullaby_-_www.FesliyanStudios.com_David_Renda/"
               + "2019-04-04_-_A_Soft_Piano_Lullaby_-_www.FesliyanStudios.com_David_Renda.mp3",
         "lullaby_soft_piano.mp3"),
        (BASE + "2021-03-05_-_Dreamy_-_www.FesliyanStudios.com/"
               + "2021-03-05_-_Dreamy_-_www.FesliyanStudios.com.mp3",
         "lullaby_dreamy.mp3"),
        (BASE + "2020-06-26_-_Sweet_Dreams_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-06-26_-_Sweet_Dreams_-_www.FesliyanStudios.com_David_Renda.mp3",
         "lullaby_sweet_dreams.mp3"),
    ]

    import requests as req

    print(f"\nDownloading up to {count} lullaby music tracks → data/music/lullaby/\n")
    print("  Source: FesliyanStudios.com (David Renda) — free for commercial use\n")

    downloaded = 0
    for i, (url, filename) in enumerate(tracks[:count]):
        out_path = os.path.join(lullaby_dir, filename)
        if os.path.exists(out_path):
            print(f"  [{i+1}/{count}] Already exists: {filename}")
            downloaded += 1
            continue
        try:
            print(f"  [{i+1}/{count}] Downloading {filename}...")
            r = req.get(url, timeout=60, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.fesliyanstudios.com/",
            })
            r.raise_for_status()
            if len(r.content) < 10_000:
                raise ValueError(f"Response too small ({len(r.content)} bytes) — likely error page")
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"           Saved ({len(r.content)//1024} KB)")
            downloaded += 1
        except Exception as e:
            print(f"           Failed: {e}")
        time.sleep(1)

    total = len([f for f in os.listdir(lullaby_dir) if f.endswith((".mp3", ".wav"))])
    print(f"\nDone! {total} lullaby track(s) in data/music/lullaby/")
    if total == 0:
        print("  Warning: No tracks downloaded. Lullaby videos will fall back to data/music/ tracks.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config = load_config()
    args   = sys.argv[1:]
    upload = "--no-upload" not in args

    if "--help" in args:
        print("Usage:")
        print("  python main.py --video                    # 2-3 min Hinglish video + upload")
        print("  python main.py --shorts                   # ~1 min Hinglish Short + upload")
        print("  python main.py --poem                     # Hinglish rhyming poem + upload")
        print("  python main.py --lullaby                  # Hinglish bedtime lullaby + upload")
        print("  python main.py --video --no-upload        # test video, skip upload")
        print("  python main.py --shorts --no-upload       # test shorts, skip upload")
        print("  python main.py --poem --no-upload         # test poem, skip upload")
        print("  python main.py --lullaby --no-upload      # test lullaby, skip upload")
        print("  python main.py --schedule                 # scheduler: video 9AM, shorts 9PM")
        print("  python main.py --generate-music           # download 10 kids music tracks")
        print("  python main.py --generate-lullaby-music   # download lullaby music tracks")
    elif "--generate-lullaby-music" in args:
        generate_lullaby_music_library(config)
    elif "--generate-music" in args:
        generate_music_library(config)
    elif "--schedule" in args:
        start_scheduler(config)
    elif "--lullaby" in args:
        run_lullaby_pipeline(config, upload=upload)
    elif "--poem" in args:
        run_poem_pipeline(config, upload=upload)
    elif "--shorts" in args:
        run_shorts_pipeline(config, upload=upload)
    elif "--video" in args:
        run_video_pipeline(config, upload=upload)
    else:
        print("Usage: python main.py --video | --shorts | --poem | --lullaby | --schedule [--no-upload]")
        print("Run with --help for more details.")
        sys.exit(1)
