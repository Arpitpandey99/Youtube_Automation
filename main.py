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
from agents.script_agent import generate_script, generate_shorts_script, translate_script
from agents.asset_agent import generate_assets, generate_voiceover_only, pick_voice, generate_images
from agents.video_agent import (
    assemble_video, assemble_shorts,
    assemble_animated_video, assemble_animated_shorts,
)
from agents.animation_agent import animate_all_scenes
from agents.metadata_agent import (
    generate_metadata, generate_youtube_thumbnail, generate_instagram_thumbnail,
    generate_shorts_thumbnail, generate_shorts_metadata, generate_instagram_metadata,
)
from agents.upload_agent import upload_video, upload_captions
from agents.instagram_agent import build_reel_caption
from agents.caption_agent import generate_srt
from agents.db import init_db, insert_video, update_video_shorts, update_video_ig
from agents.ab_agent import generate_ab_variants, pick_variant, apply_variant_to_metadata
from agents.playlist_agent import get_or_create_playlist, add_to_playlist
from agents.analytics_agent import fetch_and_store_metrics, get_pending_analytics_videos


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
    # Initialize database
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(BASE_DIR, "output", timestamp)
    os.makedirs(run_dir, exist_ok=True)

    languages = config.get("languages", [{"code": "en", "name": "English", "voices": ["en-US-AnaNeural"]}])

    print(f"\n{'='*60}")
    print(f"  YouTube Video Pipeline - {timestamp}")
    print(f"  Languages: {', '.join(l['name'] for l in languages)}")
    print(f"{'='*60}\n")

    try:
        # Fetch pending analytics from previous runs
        analytics_enabled = config.get("analytics", {}).get("enabled", False)
        if analytics_enabled:
            print("[0] Fetching analytics for previous videos...")
            pending = get_pending_analytics_videos(config)
            for v in pending[:5]:
                try:
                    fetch_and_store_metrics(config, v["video_id"], v["platform"])
                except Exception as e:
                    print(f"  Analytics fetch failed for {v['video_id']}: {e}")

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
                print(f"  {lang_prefix} Translating script from English...")
                script_data = translate_script(config, en_script, language=lang_name)
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

            # Generate captions/SRT
            print(f"  {lang_prefix} Generating captions...")
            srt_path = generate_srt(script_data, audio_files, lang_dir, language=lang_code)
            log_run(run_dir, f"captions_{lang_code}", "success", {"path": srt_path})

            # Assemble full video
            print(f"  {lang_prefix} Assembling video...")
            video_path = assemble_video(config, script_data, assets, lang_dir)
            print(f"  {lang_prefix} Video saved: {video_path}")
            log_run(run_dir, f"video_{lang_code}", "success", {"path": video_path})

            # Generate metadata
            print(f"  {lang_prefix} Generating metadata...")
            metadata = generate_metadata(config, topic_data, script_data, language=lang_name)

            # A/B testing
            ab_enabled = config.get("ab_testing", {}).get("enabled", False)
            chosen_variant = None
            if ab_enabled:
                print(f"  {lang_prefix} Generating A/B variants...")
                try:
                    variants = generate_ab_variants(config, topic_data, script_data, metadata, lang_name)
                    # We'll pick the variant after we have a db_id for the video
                except Exception as e:
                    print(f"  {lang_prefix} A/B variant generation failed: {e}")
                    variants = None

            # Generate thumbnails (platform-specific)
            print(f"  {lang_prefix} Generating thumbnails...")
            yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
            ig_thumb = generate_instagram_thumbnail(config, metadata, image_files[0], lang_dir)
            shorts_thumb = generate_shorts_thumbnail(config, metadata, image_files[0], lang_dir)

            print(f"  {lang_prefix} Title: {metadata['title']}")
            log_run(run_dir, f"metadata_{lang_code}", "success", metadata)

            with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Upload full video
            video_id = None
            db_id = None
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading video...")

                    # Apply A/B variant if available
                    upload_metadata = metadata
                    if ab_enabled and variants:
                        # Create a temporary db_id=0, update after insert
                        chosen_variant = pick_variant(config, variants, 0)
                        upload_metadata = apply_variant_to_metadata(metadata, chosen_variant)

                    video_url, video_id = upload_video(config, video_path, upload_metadata, yt_thumb)
                    log_run(run_dir, f"upload_{lang_code}", "success", {"url": video_url})
                    print(f"  {lang_prefix} Video live at: {video_url}")

                    # Upload captions
                    if video_id and srt_path:
                        upload_captions(config, video_id, srt_path, language=lang_code)

                    # Store in database
                    db_id = insert_video(
                        video_id=video_id, platform="youtube", language=lang_code,
                        topic=topic_data["topic"], category=topic_data["category"],
                        title=upload_metadata["title"], run_dir=run_dir,
                    )

                    # Playlist automation
                    playlists_enabled = config.get("playlists", {}).get("enabled", False)
                    if playlists_enabled:
                        try:
                            playlist_id = get_or_create_playlist(config, topic_data["category"], lang_name)
                            if playlist_id:
                                add_to_playlist(config, video_id, playlist_id)
                        except Exception as e:
                            print(f"  {lang_prefix} Playlist failed: {e}")

                except Exception as e:
                    print(f"  {lang_prefix} Upload failed: {e}")
                    log_run(run_dir, f"upload_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Upload skipped (--no-upload mode)")
                log_run(run_dir, f"upload_{lang_code}", "skipped")

            # Generate re-hooked Shorts script
            print(f"  {lang_prefix} Creating YouTube Shorts...")
            shorts_script = None
            shorts_audio = None
            try:
                shorts_script = generate_shorts_script(config, topic_data, script_data, lang_name)
                print(f"  {lang_prefix} Re-hooked shorts script generated")
                shorts_audio = generate_voiceover_only(config, shorts_script, lang_dir, voice=voice)
            except Exception as e:
                print(f"  {lang_prefix} Shorts script/audio fallback to original: {e}")

            shorts_path = assemble_shorts(
                config, script_data, assets, lang_dir,
                shorts_script=shorts_script, shorts_audio_files=shorts_audio,
            )
            shorts_metadata = generate_shorts_metadata(metadata)
            log_run(run_dir, f"shorts_{lang_code}", "success", {"path": shorts_path})

            # Upload Shorts
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading Shorts...")
                    shorts_url, shorts_vid = upload_video(config, shorts_path, shorts_metadata, shorts_thumb)
                    log_run(run_dir, f"shorts_upload_{lang_code}", "success", {"url": shorts_url})
                    print(f"  {lang_prefix} Shorts live at: {shorts_url}")

                    if db_id and shorts_vid:
                        update_video_shorts(db_id, shorts_vid)
                except Exception as e:
                    print(f"  {lang_prefix} Shorts upload failed: {e}")
                    log_run(run_dir, f"shorts_upload_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Shorts upload skipped")
                log_run(run_dir, f"shorts_upload_{lang_code}", "skipped")

            # Save Instagram Reel assets to a folder (manual upload)
            ig_enabled = config.get("instagram", {}).get("enabled", False)
            if ig_enabled:
                try:
                    print(f"  {lang_prefix} Preparing Instagram assets...")
                    ig_dir = os.path.join(lang_dir, "instagram")
                    os.makedirs(ig_dir, exist_ok=True)

                    ig_metadata = generate_instagram_metadata(config, topic_data, script_data, lang_name)
                    reel_caption = build_reel_caption(metadata, language=lang_name, ig_metadata=ig_metadata)

                    # Copy reel video
                    ig_video_path = os.path.join(ig_dir, "reel.mp4")
                    shutil.copy2(shorts_path, ig_video_path)

                    # Copy thumbnail
                    if ig_thumb and os.path.exists(ig_thumb):
                        shutil.copy2(ig_thumb, os.path.join(ig_dir, "thumbnail.png"))

                    # Save caption
                    with open(os.path.join(ig_dir, "caption.txt"), "w", encoding="utf-8") as f:
                        f.write(reel_caption)

                    # Save full IG metadata
                    with open(os.path.join(ig_dir, "metadata.json"), "w", encoding="utf-8") as f:
                        json.dump(ig_metadata, f, indent=2, ensure_ascii=False)

                    log_run(run_dir, f"instagram_{lang_code}", "saved", {"path": ig_dir})
                    print(f"  {lang_prefix} Instagram assets saved to: {ig_dir}")
                except Exception as e:
                    print(f"  {lang_prefix} Instagram asset prep failed: {e}")
                    log_run(run_dir, f"instagram_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Instagram skipped (disabled in config)")

            # Cleanup language-specific large files after upload
            if upload:
                print(f"  {lang_prefix} Cleaning up...")
                audio_folder = os.path.join(lang_dir, "audio")
                if os.path.exists(audio_folder):
                    shutil.rmtree(audio_folder)
                for f in ["final_video.mp4", "shorts_video.mp4", "thumbnail.png",
                           "thumbnail_ig.png", "thumbnail_shorts.png"]:
                    fpath = os.path.join(lang_dir, f)
                    if os.path.exists(fpath):
                        os.remove(fpath)

        # Cleanup shared images (including _vertical.png temp files) after all languages
        if upload:
            print("\n  Cleaning up shared images...")
            if os.path.exists(image_dir):
                shutil.rmtree(image_dir)
            print("  Cleanup done. Kept: run_log.json, scripts, metadata, captions")

        print(f"\n{'='*60}")
        print(f"  Pipeline completed successfully!")
        print(f"  Languages: {len(languages)} | Videos: {len(languages) * 2} (full + shorts)")
        print(f"  Output: {run_dir}")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


def run_animated_pipeline(config: dict, upload: bool = True) -> dict:
    """Execute the animated cartoon video pipeline for all configured languages."""
    from agents.notification_agent import send_run_summary
    import copy
    config = copy.deepcopy(config)

    # Override image style for cartoon look
    anim_config = config.get("animation", {})
    config["content"]["image_style"] = anim_config.get(
        "image_style",
        "colorful cartoon illustration, animated style, vibrant colors, "
        "kid-friendly, Pixar-like, clean lines, no text"
    )

    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(BASE_DIR, "output", f"animated_{timestamp}")
    os.makedirs(run_dir, exist_ok=True)

    languages = config.get("languages", [{"code": "en", "name": "English", "voices": ["en-US-AnaNeural"]}])
    provider = anim_config.get("provider", "kenburns")
    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "videos": []}

    print(f"\n{'='*60}")
    print(f"  Animated Video Pipeline - {timestamp}")
    print(f"  Animation: {provider}")
    print(f"  Languages: {', '.join(l['name'] for l in languages)}")
    print(f"{'='*60}\n")

    try:
        # Step 1: Topic
        print("[1] Generating topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # Step 2: English script
        print("[2] Writing English script...")
        en_script = generate_script(config, topic_data, language="English")
        print(f"  Title: {en_script['title']}")
        print(f"  Scenes: {len(en_script['scenes'])}")
        log_run(run_dir, "script_en", "success", en_script)

        with open(os.path.join(run_dir, "script_en.json"), "w") as f:
            json.dump(en_script, f, indent=2)

        # Step 3: Generate cartoon-style images
        print("[3] Generating cartoon images...")
        image_dir = os.path.join(run_dir, "images")
        os.makedirs(image_dir, exist_ok=True)
        image_files = generate_images(config, en_script, image_dir)
        log_run(run_dir, "images", "success", {"image_count": len(image_files)})

        # Process each language
        for lang in languages:
            lang_code = lang["code"]
            lang_name = lang["name"]
            lang_prefix = f"[{lang_name}]"

            print(f"\n{'─'*60}")
            print(f"  Processing: {lang_name} ({lang_code})")
            print(f"{'─'*60}")

            lang_dir = os.path.join(run_dir, lang_code)
            os.makedirs(lang_dir, exist_ok=True)

            lang_result = {"language": lang_name, "language_code": lang_code,
                           "video_url": None, "shorts_url": None}

            # Script
            if lang_code == "en":
                script_data = en_script
            else:
                print(f"  {lang_prefix} Translating script...")
                script_data = translate_script(config, en_script, language=lang_name)
                print(f"  {lang_prefix} Title: {script_data['title']}")
                log_run(run_dir, f"script_{lang_code}", "success", script_data)
                with open(os.path.join(run_dir, f"script_{lang_code}.json"), "w") as f:
                    json.dump(script_data, f, indent=2, ensure_ascii=False)

            # Voice + Voiceover
            voice = pick_voice(config, lang_code)
            print(f"  {lang_prefix} Generating voiceover...")
            audio_files = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
            log_run(run_dir, f"voiceover_{lang_code}", "success", {"voice": voice})

            # Step 4: Animate images → video clips
            print(f"  {lang_prefix} Animating scenes ({provider})...")
            animated_clips = animate_all_scenes(
                config, image_files, audio_files, script_data, lang_dir
            )
            log_run(run_dir, f"animation_{lang_code}", "success",
                    {"clip_count": len(animated_clips), "provider": provider})

            # Captions
            print(f"  {lang_prefix} Generating captions...")
            srt_path = generate_srt(script_data, audio_files, lang_dir, language=lang_code)

            # Step 5: Assemble animated full video
            print(f"  {lang_prefix} Assembling animated video...")
            video_path = assemble_animated_video(
                config, script_data, animated_clips, audio_files, lang_dir
            )
            print(f"  {lang_prefix} Video saved: {video_path}")
            log_run(run_dir, f"video_{lang_code}", "success", {"path": video_path})

            # Metadata + thumbnails
            print(f"  {lang_prefix} Generating metadata...")
            metadata = generate_metadata(config, topic_data, script_data, language=lang_name)
            yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
            ig_thumb = generate_instagram_thumbnail(config, metadata, image_files[0], lang_dir)
            shorts_thumb = generate_shorts_thumbnail(config, metadata, image_files[0], lang_dir)

            print(f"  {lang_prefix} Title: {metadata['title']}")
            log_run(run_dir, f"metadata_{lang_code}", "success", metadata)
            with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Upload full video
            video_id = None
            db_id = None
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading video...")
                    video_url, video_id = upload_video(config, video_path, metadata, yt_thumb)
                    lang_result["video_url"] = video_url
                    log_run(run_dir, f"upload_{lang_code}", "success", {"url": video_url})
                    print(f"  {lang_prefix} Video live at: {video_url}")

                    if video_id and srt_path:
                        upload_captions(config, video_id, srt_path, language=lang_code)

                    db_id = insert_video(
                        video_id=video_id, platform="youtube", language=lang_code,
                        topic=topic_data["topic"], category=topic_data["category"],
                        title=metadata["title"], run_dir=run_dir,
                    )
                except Exception as e:
                    print(f"  {lang_prefix} Upload failed: {e}")
                    log_run(run_dir, f"upload_{lang_code}", "failed", {"error": str(e)})
            else:
                print(f"  {lang_prefix} Upload skipped (--no-upload mode)")

            # Shorts (animated)
            print(f"  {lang_prefix} Creating animated Shorts...")
            shorts_script = None
            shorts_audio = None
            try:
                shorts_script = generate_shorts_script(config, topic_data, script_data, lang_name)
                shorts_audio = generate_voiceover_only(config, shorts_script, lang_dir, voice=voice)
            except Exception as e:
                print(f"  {lang_prefix} Shorts script fallback: {e}")

            shorts_path = assemble_animated_shorts(
                config, script_data, animated_clips, audio_files, lang_dir,
                shorts_script=shorts_script, shorts_audio=shorts_audio,
            )
            shorts_metadata = generate_shorts_metadata(metadata)
            log_run(run_dir, f"shorts_{lang_code}", "success", {"path": shorts_path})

            # Upload Shorts
            if upload:
                try:
                    print(f"  {lang_prefix} Uploading Shorts...")
                    shorts_url, shorts_vid = upload_video(config, shorts_path, shorts_metadata, shorts_thumb)
                    lang_result["shorts_url"] = shorts_url
                    log_run(run_dir, f"shorts_upload_{lang_code}", "success", {"url": shorts_url})
                    print(f"  {lang_prefix} Shorts live at: {shorts_url}")
                    if db_id and shorts_vid:
                        update_video_shorts(db_id, shorts_vid)
                except Exception as e:
                    print(f"  {lang_prefix} Shorts upload failed: {e}")
            else:
                print(f"  {lang_prefix} Shorts upload skipped")

            # Save Instagram assets
            ig_enabled = config.get("instagram", {}).get("enabled", False)
            if ig_enabled:
                try:
                    print(f"  {lang_prefix} Preparing Instagram assets...")
                    ig_dir = os.path.join(lang_dir, "instagram")
                    os.makedirs(ig_dir, exist_ok=True)

                    ig_metadata = generate_instagram_metadata(config, topic_data, script_data, lang_name)
                    reel_caption = build_reel_caption(metadata, language=lang_name, ig_metadata=ig_metadata)

                    shutil.copy2(shorts_path, os.path.join(ig_dir, "reel.mp4"))
                    if ig_thumb and os.path.exists(ig_thumb):
                        shutil.copy2(ig_thumb, os.path.join(ig_dir, "thumbnail.png"))
                    with open(os.path.join(ig_dir, "caption.txt"), "w", encoding="utf-8") as f:
                        f.write(reel_caption)
                    with open(os.path.join(ig_dir, "metadata.json"), "w", encoding="utf-8") as f:
                        json.dump(ig_metadata, f, indent=2, ensure_ascii=False)

                    log_run(run_dir, f"instagram_{lang_code}", "saved", {"path": ig_dir})
                    print(f"  {lang_prefix} Instagram assets saved to: {ig_dir}")
                except Exception as e:
                    print(f"  {lang_prefix} Instagram asset prep failed: {e}")

            # Cleanup large files after upload
            if upload:
                print(f"  {lang_prefix} Cleaning up...")
                for folder in ["audio", "animated_clips"]:
                    folder_path = os.path.join(lang_dir, folder)
                    if os.path.exists(folder_path):
                        shutil.rmtree(folder_path)
                for f in ["final_video.mp4", "shorts_video.mp4", "thumbnail.png",
                           "thumbnail_ig.png", "thumbnail_shorts.png"]:
                    fpath = os.path.join(lang_dir, f)
                    if os.path.exists(fpath):
                        os.remove(fpath)

            run_summary["videos"].append(lang_result)

        # Cleanup shared images
        if upload and os.path.exists(image_dir):
            shutil.rmtree(image_dir)

        print(f"\n{'='*60}")
        print(f"  Animated Pipeline completed!")
        print(f"  Languages: {len(languages)} | Videos: {len(languages) * 2} (full + shorts)")
        print(f"  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        log_run(run_dir, "error", "failed", {"error": str(e)})
        raise


def start_scheduler(config: dict, animated: bool = False):
    """Start the automated scheduler."""
    upload_days = config["schedule"]["upload_days"]
    upload_time = config["schedule"]["upload_time"]
    pipeline_fn = run_animated_pipeline if animated else run_pipeline
    pipeline_label = "animated" if animated else "regular"

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
        day_map[day].at(upload_time).do(pipeline_fn, config=config)
        print(f"  Scheduled ({pipeline_label}): {day} at {upload_time}")

    print(f"\nScheduler running. Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    config = load_config()

    args = sys.argv[1:]
    upload = "--no-upload" not in args
    use_prefect = "--prefect" in args
    use_animated = "--animated" in args

    if "--help" in args:
        print("Usage:")
        print("  python main.py                       # Run once with upload")
        print("  python main.py --no-upload            # Run once without upload (test)")
        print("  python main.py --animated             # Animated cartoon pipeline")
        print("  python main.py --animated --no-upload # Animated without upload")
        print("  python main.py --schedule             # Start automated scheduler (regular)")
        print("  python main.py --schedule --animated  # Start scheduler (animated pipeline)")
        print("  python main.py --prefect              # Run with Prefect orchestration")
        print("  python main.py --prefect --no-upload  # Prefect without upload")
        print("  python main.py --prefect --animated   # Prefect + animated pipeline")
    elif "--schedule" in args:
        start_scheduler(config, animated=use_animated)
    elif use_prefect:
        try:
            from prefect_flow import pipeline_flow, animated_pipeline_flow
        except ImportError:
            print("Error: Prefect is not installed.")
            print("Install it with: pip install prefect>=3.0.0")
            sys.exit(1)
        if use_animated:
            animated_pipeline_flow(config, upload=upload)
        else:
            pipeline_flow(config, upload=upload)
    elif use_animated:
        run_animated_pipeline(config, upload=upload)
    else:
        run_pipeline(config, upload=upload)
