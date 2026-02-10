"""
YouTube Kids Video Automation - Main Orchestrator
Generates and uploads kid-friendly YouTube videos automatically.
"""

import os
import sys
import json
import shutil
import yaml
import schedule
import time
from datetime import datetime

from agents.topic_agent import generate_topic
from agents.script_agent import generate_script
from agents.asset_agent import generate_assets, generate_voiceover_only, pick_voice, generate_images
from agents.video_agent import assemble_video, assemble_shorts
from agents.metadata_agent import generate_metadata, generate_thumbnail, generate_shorts_metadata
from agents.upload_agent import upload_video
from agents.instagram_agent import upload_reel, build_reel_caption


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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


def run_pipeline(config: dict, upload: bool = True):
    """Execute the full video generation pipeline for all configured languages."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(BASE_DIR, "output", timestamp)
    os.makedirs(run_dir, exist_ok=True)

    languages = config.get("languages", [{"code": "en", "name": "English", "voices": ["en-US-AnaNeural"]}])

    print(f"\n{'='*60}")
    print(f"  YouTube Video Pipeline - {timestamp}")
    print(f"  Languages: {', '.join(l['name'] for l in languages)}")
    print(f"{'='*60}\n")

    try:
        # Step 1: Generate Topic (shared across languages)
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # Step 2: Generate English script first (needed for image generation)
        print("[2] Writing English script (for image prompts)...")
        en_script = generate_script(config, topic_data, language="English")
        print(f"  Title: {en_script['title']}")
        print(f"  Scenes: {len(en_script['scenes'])}")
        log_run(run_dir, "script_en", "success", en_script)

        with open(os.path.join(run_dir, "script_en.json"), "w") as f:
            json.dump(en_script, f, indent=2)

        # Step 3: Generate images once (shared across all languages)
        print("[3] Generating images (shared across languages)...")
        image_dir = os.path.join(run_dir, "images")
        os.makedirs(image_dir, exist_ok=True)
        image_files = generate_images(config, en_script, image_dir)
        log_run(run_dir, "images", "success", {"image_count": len(image_files)})

        # Process each language
        for lang_idx, lang in enumerate(languages):
            lang_code = lang["code"]
            lang_name = lang["name"]
            lang_prefix = f"[{lang_name}]"

            print(f"\n{'─'*60}")
            print(f"  Processing: {lang_name} ({lang_code})")
            print(f"{'─'*60}")

            lang_dir = os.path.join(run_dir, lang_code)
            os.makedirs(lang_dir, exist_ok=True)

            # Generate script for this language (reuse English script if English)
            if lang_code == "en":
                script_data = en_script
            else:
                print(f"  {lang_prefix} Writing script...")
                script_data = generate_script(config, topic_data, language=lang_name)
                print(f"  {lang_prefix} Title: {script_data['title']}")
                log_run(run_dir, f"script_{lang_code}", "success", script_data)

                with open(os.path.join(run_dir, f"script_{lang_code}.json"), "w") as f:
                    json.dump(script_data, f, indent=2, ensure_ascii=False)

            # Pick a random voice for this language
            voice = pick_voice(config, lang_code)

            # Generate voiceover
            print(f"  {lang_prefix} Generating voiceover...")
            audio_dir = os.path.join(lang_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            audio_files = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
            log_run(run_dir, f"voiceover_{lang_code}", "success", {
                "voice": voice, "audio_count": len(audio_files),
            })

            assets = {"audio_files": audio_files, "image_files": image_files}

            # Assemble full video
            print(f"  {lang_prefix} Assembling video...")
            video_path = assemble_video(config, script_data, assets, lang_dir)
            print(f"  {lang_prefix} Video saved: {video_path}")
            log_run(run_dir, f"video_{lang_code}", "success", {"path": video_path})

            # Generate metadata
            print(f"  {lang_prefix} Generating metadata & thumbnail...")
            metadata = generate_metadata(config, topic_data, script_data, language=lang_name)
            thumbnail_path = generate_thumbnail(config, metadata, image_files[0], lang_dir)
            print(f"  {lang_prefix} Title: {metadata['title']}")
            log_run(run_dir, f"metadata_{lang_code}", "success", metadata)

            with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Upload full video
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading video...")
                    video_url = upload_video(config, video_path, metadata, thumbnail_path)
                    log_run(run_dir, f"upload_{lang_code}", "success", {"url": video_url})
                    print(f"  {lang_prefix} Video live at: {video_url}")
                except Exception as e:
                    print(f"  {lang_prefix} Upload failed: {e}")
                    log_run(run_dir, f"upload_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Upload skipped (--no-upload mode)")
                log_run(run_dir, f"upload_{lang_code}", "skipped")

            # Assemble Shorts
            print(f"  {lang_prefix} Creating YouTube Shorts...")
            shorts_path = assemble_shorts(config, script_data, assets, lang_dir)
            shorts_metadata = generate_shorts_metadata(metadata)
            log_run(run_dir, f"shorts_{lang_code}", "success", {"path": shorts_path})

            # Upload Shorts
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading Shorts...")
                    shorts_url = upload_video(config, shorts_path, shorts_metadata)
                    log_run(run_dir, f"shorts_upload_{lang_code}", "success", {"url": shorts_url})
                    print(f"  {lang_prefix} Shorts live at: {shorts_url}")
                except Exception as e:
                    print(f"  {lang_prefix} Shorts upload failed: {e}")
                    log_run(run_dir, f"shorts_upload_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Shorts upload skipped")
                log_run(run_dir, f"shorts_upload_{lang_code}", "skipped")

            # Upload to Instagram as Reel (reuse shorts video)
            ig_enabled = config.get("instagram", {}).get("enabled", False)
            if upload and ig_enabled:
                try:
                    print(f"  {lang_prefix} Uploading Instagram Reel...")
                    reel_caption = build_reel_caption(metadata, language=lang_name)
                    reel_url = upload_reel(config, shorts_path, reel_caption, thumbnail_path)
                    log_run(run_dir, f"instagram_{lang_code}", "success", {"url": reel_url})
                    print(f"  {lang_prefix} Reel live at: {reel_url}")
                except Exception as e:
                    print(f"  {lang_prefix} Instagram upload failed: {e}")
                    log_run(run_dir, f"instagram_{lang_code}", "failed", {"error": str(e)})
            elif not ig_enabled:
                print(f"  {lang_prefix} Instagram upload skipped (disabled in config)")
                log_run(run_dir, f"instagram_{lang_code}", "skipped")

            # Cleanup language-specific large files after upload
            if upload:
                print(f"  {lang_prefix} Cleaning up...")
                audio_folder = os.path.join(lang_dir, "audio")
                if os.path.exists(audio_folder):
                    shutil.rmtree(audio_folder)
                for f in ["final_video.mp4", "shorts_video.mp4", "thumbnail.png"]:
                    fpath = os.path.join(lang_dir, f)
                    if os.path.exists(fpath):
                        os.remove(fpath)

        # Cleanup shared images after all languages are done
        if upload:
            print("\n  Cleaning up shared images...")
            if os.path.exists(image_dir):
                shutil.rmtree(image_dir)
            print("  Cleanup done. Kept: run_log.json, scripts, metadata")

        print(f"\n{'='*60}")
        print(f"  Pipeline completed successfully!")
        print(f"  Languages: {len(languages)} | Videos: {len(languages) * 2} (full + shorts)")
        print(f"  Output: {run_dir}")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


def start_scheduler(config: dict):
    """Start the automated scheduler."""
    upload_days = config["schedule"]["upload_days"]
    upload_time = config["schedule"]["upload_time"]

    day_map = {
        "Monday": schedule.every().monday,
        "Tuesday": schedule.every().tuesday,
        "Wednesday": schedule.every().wednesday,
        "Thursday": schedule.every().thursday,
        "Friday": schedule.every().friday,
        "Saturday": schedule.every().saturday,
        "Sunday": schedule.every().sunday,
    }

    for day in upload_days:
        day_map[day].at(upload_time).do(run_pipeline, config=config)
        print(f"  Scheduled: {day} at {upload_time}")

    print(f"\nScheduler running. Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    config = load_config()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--schedule":
            start_scheduler(config)
        elif sys.argv[1] == "--no-upload":
            run_pipeline(config, upload=False)
        elif sys.argv[1] == "--help":
            print("Usage:")
            print("  python main.py              # Run once with upload")
            print("  python main.py --no-upload  # Run once without upload (test)")
            print("  python main.py --schedule   # Start automated scheduler")
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Use --help for usage info")
    else:
        run_pipeline(config)
