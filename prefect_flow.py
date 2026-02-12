"""
Prefect-based orchestration for the YouTube Kids Video Pipeline.
Provides retries, observability, and parallel language processing.

Usage:
  python main.py --prefect              # Run once with Prefect
  python main.py --prefect --no-upload  # Run without uploading
"""

import os
import json
import shutil
from datetime import datetime

from prefect import flow, task, get_run_logger

from agents.topic_agent import generate_topic
from agents.script_agent import generate_script, generate_shorts_script, translate_script
from agents.asset_agent import generate_voiceover_only, pick_voice, generate_images
from agents.video_agent import (
    assemble_video, assemble_shorts,
    assemble_animated_video, assemble_animated_shorts,
)
from agents.animation_agent import animate_all_scenes
from agents.metadata_agent import (
    generate_metadata, generate_youtube_thumbnail, generate_instagram_thumbnail,
    generate_shorts_thumbnail, generate_shorts_metadata,
)
from agents.upload_agent import upload_video, upload_captions
from agents.instagram_agent import build_reel_caption
from agents.caption_agent import generate_srt
from agents.db import init_db, insert_video, update_video_shorts, update_video_ig
from agents.ab_agent import generate_ab_variants, pick_variant, apply_variant_to_metadata
from agents.playlist_agent import get_or_create_playlist, add_to_playlist
from agents.analytics_agent import fetch_and_store_metrics, get_pending_analytics_videos


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _log_run(run_dir: str, step: str, status: str, data: dict = None):
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


@task(retries=2, retry_delay_seconds=30, name="generate-topic")
def task_generate_topic(config: dict) -> dict:
    logger = get_run_logger()
    topic_data = generate_topic(config)
    logger.info(f"Topic: {topic_data['topic']}")
    return topic_data


@task(retries=2, retry_delay_seconds=30, name="generate-script")
def task_generate_script(config: dict, topic_data: dict, language: str) -> dict:
    logger = get_run_logger()
    script = generate_script(config, topic_data, language=language)
    logger.info(f"Script ({language}): {script['title']} - {len(script['scenes'])} scenes")
    return script


@task(retries=2, retry_delay_seconds=30, name="translate-script")
def task_translate_script(config: dict, en_script: dict, language: str) -> dict:
    logger = get_run_logger()
    script = translate_script(config, en_script, language=language)
    logger.info(f"Translated ({language}): {script['title']} - {len(script['scenes'])} scenes")
    return script


@task(retries=3, retry_delay_seconds=60, name="generate-images")
def task_generate_images(config: dict, script_data: dict, image_dir: str) -> list:
    logger = get_run_logger()
    os.makedirs(image_dir, exist_ok=True)
    images = generate_images(config, script_data, image_dir)
    logger.info(f"Generated {len(images)} images")
    return images


@task(retries=2, retry_delay_seconds=15, name="generate-voiceover")
def task_generate_voiceover(config: dict, script_data: dict, lang_dir: str, voice: str) -> list:
    return generate_voiceover_only(config, script_data, lang_dir, voice=voice)


@task(name="assemble-video")
def task_assemble_video(config: dict, script_data: dict, assets: dict, lang_dir: str) -> str:
    return assemble_video(config, script_data, assets, lang_dir)


@task(name="assemble-shorts")
def task_assemble_shorts(config: dict, script_data: dict, assets: dict, lang_dir: str,
                         shorts_script: dict = None, shorts_audio: list = None) -> str:
    return assemble_shorts(config, script_data, assets, lang_dir,
                          shorts_script=shorts_script, shorts_audio_files=shorts_audio)


@task(name="generate-metadata")
def task_generate_metadata(config: dict, topic_data: dict, script_data: dict,
                           language: str) -> dict:
    return generate_metadata(config, topic_data, script_data, language=language)


@task(retries=2, retry_delay_seconds=120, name="upload-video")
def task_upload_video(config: dict, video_path: str, metadata: dict,
                      thumbnail_path: str = None) -> tuple:
    return upload_video(config, video_path, metadata, thumbnail_path)



@flow(name="youtube-kids-pipeline", log_prints=True)
def pipeline_flow(config: dict, upload: bool = True):
    """Full pipeline flow with Prefect orchestration."""
    logger = get_run_logger()
    init_db()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(BASE_DIR, "output", timestamp)
    os.makedirs(run_dir, exist_ok=True)

    languages = config.get("languages", [{"code": "en", "name": "English", "voices": ["en-US-AnaNeural"]}])

    logger.info(f"Pipeline started: {timestamp}")
    logger.info(f"Languages: {', '.join(l['name'] for l in languages)}")

    # Fetch pending analytics from previous runs
    analytics_enabled = config.get("analytics", {}).get("enabled", False)
    if analytics_enabled:
        pending = get_pending_analytics_videos(config)
        for v in pending[:5]:
            try:
                fetch_and_store_metrics(config, v["video_id"], v["platform"])
            except Exception as e:
                logger.warning(f"Analytics fetch failed for {v['video_id']}: {e}")

    # Step 1: Topic
    topic_data = task_generate_topic(config)
    _log_run(run_dir, "topic", "success", topic_data)

    # Step 2: English script (for images)
    en_script = task_generate_script(config, topic_data, "English")
    _log_run(run_dir, "script_en", "success", en_script)
    with open(os.path.join(run_dir, "script_en.json"), "w") as f:
        json.dump(en_script, f, indent=2)

    # Step 3: Images (shared)
    image_dir = os.path.join(run_dir, "images")
    image_files = task_generate_images(config, en_script, image_dir)
    _log_run(run_dir, "images", "success", {"image_count": len(image_files)})

    # Process each language
    for lang in languages:
        lang_code = lang["code"]
        lang_name = lang["name"]
        lang_dir = os.path.join(run_dir, lang_code)
        os.makedirs(lang_dir, exist_ok=True)

        logger.info(f"Processing: {lang_name}")

        # Script (translate from English to keep scene order in sync with images)
        if lang_code == "en":
            script_data = en_script
        else:
            script_data = task_translate_script(config, en_script, lang_name)
            _log_run(run_dir, f"script_{lang_code}", "success", script_data)
            with open(os.path.join(run_dir, f"script_{lang_code}.json"), "w") as f:
                json.dump(script_data, f, indent=2, ensure_ascii=False)

        # Voice + Voiceover
        voice = pick_voice(config, lang_code)
        audio_files = task_generate_voiceover(config, script_data, lang_dir, voice)
        _log_run(run_dir, f"voiceover_{lang_code}", "success", {"voice": voice})

        assets = {"audio_files": audio_files, "image_files": image_files}

        # Full video
        video_path = task_assemble_video(config, script_data, assets, lang_dir)
        _log_run(run_dir, f"video_{lang_code}", "success", {"path": video_path})

        # Captions
        srt_path = generate_srt(script_data, audio_files, lang_dir, language=lang_code)
        _log_run(run_dir, f"captions_{lang_code}", "success", {"path": srt_path})

        # Metadata
        metadata = task_generate_metadata(config, topic_data, script_data, lang_name)

        # A/B testing
        ab_enabled = config.get("ab_testing", {}).get("enabled", False)
        if ab_enabled:
            variants = generate_ab_variants(config, topic_data, script_data, metadata, lang_name)
            # video_db_id placeholder for variant tracking
            chosen = pick_variant(config, variants, 0)
            metadata = apply_variant_to_metadata(metadata, chosen)

        # Thumbnails
        yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
        ig_thumb = generate_instagram_thumbnail(config, metadata, image_files[0], lang_dir)
        shorts_thumb = generate_shorts_thumbnail(config, metadata, image_files[0], lang_dir)

        _log_run(run_dir, f"metadata_{lang_code}", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Upload full video
        video_url = None
        video_id = None
        if upload:
            try:
                video_url, video_id = task_upload_video(config, video_path, metadata, yt_thumb)
                _log_run(run_dir, f"upload_{lang_code}", "success", {"url": video_url})

                # Upload captions
                if video_id and srt_path:
                    upload_captions(config, video_id, srt_path, language=lang_code)

                # Store in DB
                db_id = insert_video(
                    video_id=video_id, platform="youtube", language=lang_code,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=metadata["title"], run_dir=run_dir,
                )

                # Playlist
                playlists_enabled = config.get("playlists", {}).get("enabled", False)
                if playlists_enabled:
                    try:
                        playlist_id = get_or_create_playlist(config, topic_data["category"], lang_name)
                        if playlist_id:
                            add_to_playlist(config, video_id, playlist_id)
                    except Exception as e:
                        logger.warning(f"Playlist failed: {e}")

            except Exception as e:
                logger.error(f"Upload failed ({lang_name}): {e}")
                _log_run(run_dir, f"upload_{lang_code}", "failed", {"error": str(e)})

        # Shorts
        shorts_script = None
        shorts_audio = None
        try:
            shorts_script = generate_shorts_script(config, topic_data, script_data, lang_name)
            shorts_audio = generate_voiceover_only(config, shorts_script, lang_dir, voice=voice)
        except Exception:
            pass

        shorts_path = task_assemble_shorts(
            config, script_data, assets, lang_dir,
            shorts_script=shorts_script, shorts_audio=shorts_audio,
        )
        shorts_metadata = generate_shorts_metadata(metadata)

        if upload:
            try:
                shorts_url, shorts_vid = task_upload_video(config, shorts_path, shorts_metadata, shorts_thumb)
                _log_run(run_dir, f"shorts_upload_{lang_code}", "success", {"url": shorts_url})
            except Exception as e:
                logger.error(f"Shorts upload failed ({lang_name}): {e}")

        # Instagram — save assets for manual upload
        ig_enabled = config.get("instagram", {}).get("enabled", False)
        if ig_enabled:
            try:
                ig_dir = os.path.join(lang_dir, "instagram")
                os.makedirs(ig_dir, exist_ok=True)

                reel_caption = build_reel_caption(metadata, language=lang_name)

                shutil.copy2(shorts_path, os.path.join(ig_dir, "reel.mp4"))
                if ig_thumb and os.path.exists(ig_thumb):
                    shutil.copy2(ig_thumb, os.path.join(ig_dir, "thumbnail.png"))
                with open(os.path.join(ig_dir, "caption.txt"), "w", encoding="utf-8") as f:
                    f.write(reel_caption)

                _log_run(run_dir, f"instagram_{lang_code}", "saved", {"path": ig_dir})
                logger.info(f"Instagram assets saved: {ig_dir}")
            except Exception as e:
                logger.error(f"Instagram asset prep failed ({lang_name}): {e}")

        # Cleanup
        if upload:
            audio_folder = os.path.join(lang_dir, "audio")
            if os.path.exists(audio_folder):
                shutil.rmtree(audio_folder)
            for f in ["final_video.mp4", "shorts_video.mp4", "thumbnail.png",
                       "thumbnail_ig.png", "thumbnail_shorts.png"]:
                fpath = os.path.join(lang_dir, f)
                if os.path.exists(fpath):
                    os.remove(fpath)

    # Cleanup shared images
    if upload and os.path.exists(image_dir):
        shutil.rmtree(image_dir)

    logger.info(f"Pipeline completed! Output: {run_dir}")


# ── Animated pipeline tasks ──────────────────────────────────────────

@task(retries=1, retry_delay_seconds=30, name="animate-scenes")
def task_animate_scenes(config: dict, image_files: list, audio_files: list,
                        script_data: dict, output_dir: str) -> list:
    return animate_all_scenes(config, image_files, audio_files, script_data, output_dir)


@task(name="assemble-animated-video")
def task_assemble_animated_video(config: dict, script_data: dict,
                                 animated_clips: list, audio_files: list,
                                 lang_dir: str) -> str:
    return assemble_animated_video(config, script_data, animated_clips, audio_files, lang_dir)


@task(name="assemble-animated-shorts")
def task_assemble_animated_shorts(config: dict, script_data: dict,
                                  animated_clips: list, audio_files: list,
                                  lang_dir: str, shorts_script: dict = None,
                                  shorts_audio: list = None) -> str:
    return assemble_animated_shorts(config, script_data, animated_clips, audio_files,
                                    lang_dir, shorts_script=shorts_script,
                                    shorts_audio=shorts_audio)


@flow(name="animated-kids-pipeline", log_prints=True)
def animated_pipeline_flow(config: dict, upload: bool = True):
    """Animated cartoon pipeline with Prefect orchestration."""
    import copy
    config = copy.deepcopy(config)

    logger = get_run_logger()
    init_db()

    # Override image style for cartoon
    anim_config = config.get("animation", {})
    config["content"]["image_style"] = anim_config.get(
        "image_style",
        "colorful cartoon illustration, animated style, vibrant colors, "
        "kid-friendly, Pixar-like, clean lines, no text"
    )
    provider = anim_config.get("provider", "kenburns")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(BASE_DIR, "output", f"animated_{timestamp}")
    os.makedirs(run_dir, exist_ok=True)

    languages = config.get("languages", [{"code": "en", "name": "English", "voices": ["en-US-AnaNeural"]}])

    logger.info(f"Animated pipeline started: {timestamp} (provider: {provider})")
    logger.info(f"Languages: {', '.join(l['name'] for l in languages)}")

    # Topic
    topic_data = task_generate_topic(config)
    _log_run(run_dir, "topic", "success", topic_data)

    # English script
    en_script = task_generate_script(config, topic_data, "English")
    _log_run(run_dir, "script_en", "success", en_script)
    with open(os.path.join(run_dir, "script_en.json"), "w") as f:
        json.dump(en_script, f, indent=2)

    # Cartoon images
    image_dir = os.path.join(run_dir, "images")
    image_files = task_generate_images(config, en_script, image_dir)
    _log_run(run_dir, "images", "success", {"image_count": len(image_files)})

    for lang in languages:
        lang_code = lang["code"]
        lang_name = lang["name"]
        lang_dir = os.path.join(run_dir, lang_code)
        os.makedirs(lang_dir, exist_ok=True)

        logger.info(f"Processing: {lang_name}")

        # Script
        if lang_code == "en":
            script_data = en_script
        else:
            script_data = task_translate_script(config, en_script, lang_name)
            _log_run(run_dir, f"script_{lang_code}", "success", script_data)
            with open(os.path.join(run_dir, f"script_{lang_code}.json"), "w") as f:
                json.dump(script_data, f, indent=2, ensure_ascii=False)

        # Voice + Voiceover
        voice = pick_voice(config, lang_code)
        audio_files = task_generate_voiceover(config, script_data, lang_dir, voice)
        _log_run(run_dir, f"voiceover_{lang_code}", "success", {"voice": voice})

        # Animate scenes
        animated_clips = task_animate_scenes(config, image_files, audio_files,
                                             script_data, lang_dir)
        _log_run(run_dir, f"animation_{lang_code}", "success",
                 {"clip_count": len(animated_clips), "provider": provider})

        # Captions
        srt_path = generate_srt(script_data, audio_files, lang_dir, language=lang_code)

        # Assemble animated video
        video_path = task_assemble_animated_video(config, script_data, animated_clips,
                                                  audio_files, lang_dir)
        _log_run(run_dir, f"video_{lang_code}", "success", {"path": video_path})

        # Metadata + thumbnails
        metadata = task_generate_metadata(config, topic_data, script_data, lang_name)
        yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir)
        ig_thumb = generate_instagram_thumbnail(config, metadata, image_files[0], lang_dir)
        shorts_thumb = generate_shorts_thumbnail(config, metadata, image_files[0], lang_dir)

        _log_run(run_dir, f"metadata_{lang_code}", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Upload full video
        if upload:
            try:
                video_url, video_id = task_upload_video(config, video_path, metadata, yt_thumb)
                _log_run(run_dir, f"upload_{lang_code}", "success", {"url": video_url})
                if video_id and srt_path:
                    upload_captions(config, video_id, srt_path, language=lang_code)
                insert_video(
                    video_id=video_id, platform="youtube", language=lang_code,
                    topic=topic_data["topic"], category=topic_data["category"],
                    title=metadata["title"], run_dir=run_dir,
                )
            except Exception as e:
                logger.error(f"Upload failed ({lang_name}): {e}")

        # Animated Shorts
        shorts_script = None
        shorts_audio = None
        try:
            shorts_script = generate_shorts_script(config, topic_data, script_data, lang_name)
            shorts_audio = generate_voiceover_only(config, shorts_script, lang_dir, voice=voice)
        except Exception:
            pass

        shorts_path = task_assemble_animated_shorts(
            config, script_data, animated_clips, audio_files, lang_dir,
            shorts_script=shorts_script, shorts_audio=shorts_audio,
        )
        shorts_metadata = generate_shorts_metadata(metadata)

        if upload:
            try:
                shorts_url, shorts_vid = task_upload_video(config, shorts_path,
                                                           shorts_metadata, shorts_thumb)
                _log_run(run_dir, f"shorts_upload_{lang_code}", "success", {"url": shorts_url})
            except Exception as e:
                logger.error(f"Shorts upload failed ({lang_name}): {e}")

        # Instagram assets
        ig_enabled = config.get("instagram", {}).get("enabled", False)
        if ig_enabled:
            try:
                ig_dir = os.path.join(lang_dir, "instagram")
                os.makedirs(ig_dir, exist_ok=True)
                reel_caption = build_reel_caption(metadata, language=lang_name)
                shutil.copy2(shorts_path, os.path.join(ig_dir, "reel.mp4"))
                if ig_thumb and os.path.exists(ig_thumb):
                    shutil.copy2(ig_thumb, os.path.join(ig_dir, "thumbnail.png"))
                with open(os.path.join(ig_dir, "caption.txt"), "w", encoding="utf-8") as f:
                    f.write(reel_caption)
                _log_run(run_dir, f"instagram_{lang_code}", "saved", {"path": ig_dir})
            except Exception as e:
                logger.error(f"Instagram asset prep failed ({lang_name}): {e}")

        # Cleanup
        if upload:
            for folder in ["audio", "animated_clips"]:
                folder_path = os.path.join(lang_dir, folder)
                if os.path.exists(folder_path):
                    shutil.rmtree(folder_path)
            for f in ["final_video.mp4", "shorts_video.mp4", "thumbnail.png",
                       "thumbnail_ig.png", "thumbnail_shorts.png"]:
                fpath = os.path.join(lang_dir, f)
                if os.path.exists(fpath):
                    os.remove(fpath)

    if upload and os.path.exists(image_dir):
        shutil.rmtree(image_dir)

    logger.info(f"Animated pipeline completed! Output: {run_dir}")
