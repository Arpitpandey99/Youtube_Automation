"""
YouTube Automation v2 — Main Orchestrator
Hinglish tech-explainer pipeline with Telegram approval gate.

CLI:
  --content-loop        daily: topic→research→script→quality→assets→video→queue
  --approval-bot        long-running Telegram approval bot
  --publish-approved    upload approved candidates from the queue
  --feedback-loop       analytics→learning→kill-switch (every 6h)
  --strategy-loop       weekly: trends + competitor + cluster + series
  --analytics-sweep     one-shot bulk analytics fetch
  --generate-music      download background music tracks
  --cleanup-old         clean old intermediate files
  --report              generate weekly report
"""

import os
import sys
import json
import copy
import shutil
import yaml
import time
from datetime import datetime

from agents.topic_agent import generate_topic
from agents.script_agent import generate_script, generate_shorts_script
from agents.asset_agent import (
    generate_images, generate_voiceover_only, pick_voice,
)
from agents.video_agent import (
    assemble_animated_video, assemble_animated_shorts,
)
from agents.animation_agent import animate_all_scenes
from agents.metadata_agent import (
    generate_metadata, generate_youtube_thumbnail,
    generate_shorts_thumbnail, generate_shorts_metadata,
)
from agents.upload_agent import upload_video, upload_captions, queue_for_approval
from agents.caption_agent import generate_srt
from agents.db import init_db, insert_video
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
    """Deep-copy config and apply image style override."""
    cfg = copy.deepcopy(config)
    anim_style = cfg.get("animation", {}).get(
        "image_style",
        "clean technical illustration, infographic style, modern flat design, "
        "vibrant colors, no text, no words, professional diagram aesthetic",
    )
    cfg["content"]["image_style"] = anim_style
    return cfg


def _cleanup(lang_dir: str, image_dir: str):
    """Remove large intermediate files after video assembly."""
    for folder in ["audio", "animated_clips"]:
        p = os.path.join(lang_dir, folder)
        if os.path.exists(p):
            shutil.rmtree(p)
    if os.path.exists(image_dir):
        preserved = []
        for f in os.listdir(image_dir):
            if f.startswith("thumbnail_variant_"):
                src = os.path.join(image_dir, f)
                dst = os.path.join(lang_dir, f)
                shutil.copy2(src, dst)
                preserved.append(f)
        shutil.rmtree(image_dir)
        if preserved:
            print(f"  Preserved {len(preserved)} thumbnail variants for A/B testing")


def cleanup_old_output_dirs(days_old: int = 7, dry_run: bool = True):
    """Remove media files from old output directories.
    KEEPS: script.json, metadata.json, run_log.json
    """
    output_base = os.path.join(BASE_DIR, "output")
    if not os.path.exists(output_base):
        return

    cutoff_time = time.time() - (days_old * 86400)
    cleaned_bytes = 0

    for run_dir in os.listdir(output_base):
        run_path = os.path.join(output_base, run_dir)
        if not os.path.isdir(run_path):
            continue
        mtime = os.path.getmtime(run_path)
        if mtime >= cutoff_time:
            continue

        for root, dirs, files in os.walk(run_path):
            for dir_name in ["audio", "animated_clips", "images"]:
                if dir_name in dirs:
                    target = os.path.join(root, dir_name)
                    size = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, dn, fn in os.walk(target)
                        for f in fn
                    )
                    if dry_run:
                        print(f"  Would delete: {target} ({size // 1024} KB)")
                    else:
                        shutil.rmtree(target)
                        print(f"  Deleted: {target} ({size // 1024} KB)")
                    cleaned_bytes += size

        for root, dirs, files in os.walk(run_path):
            for filename in files:
                if filename.endswith(".mp4") or \
                   filename.endswith(".png") and "thumbnail" in filename.lower() or \
                   filename.endswith(".srt"):
                    target = os.path.join(root, filename)
                    size = os.path.getsize(target)
                    if dry_run:
                        print(f"  Would delete: {target} ({size // 1024} KB)")
                    else:
                        os.remove(target)
                        print(f"  Deleted: {target} ({size // 1024} KB)")
                    cleaned_bytes += size

    print(f"\nTotal: {cleaned_bytes // (1024*1024)} MB {'would be' if dry_run else ''} freed")


# ── v2: Post-upload helper hooks ──────────────────────────────────────────────

def _generate_thumbnail_variants(config: dict, metadata: dict, image_files: list,
                                  output_dir: str, content_type: str):
    """Generate thumbnail A/B variants if enabled."""
    if not config.get("thumbnail_ab", {}).get("enabled", False):
        return
    try:
        from services.thumbnail_ab_service import generate_thumbnail_variants
        count = config.get("thumbnail_ab", {}).get("variants_count", 3)
        variants = generate_thumbnail_variants(
            config, metadata, image_files, output_dir, content_type, count=count
        )
        if variants:
            print(f"  Generated {len(variants)} thumbnail variants for A/B testing")
    except Exception as e:
        print(f"  Warning: Thumbnail variant generation failed: {e}")


def _post_upload_hooks(config: dict, video_db_id: int, topic_data: dict,
                       primary_thumb: str, output_dir: str):
    """Run v2 post-upload hooks."""
    if not video_db_id:
        return
    try:
        from services.schedule_optimizer_service import record_upload_time
        record_upload_time(video_db_id)
    except Exception:
        pass
    try:
        from services.thumbnail_ab_service import store_thumbnail_variants
        import glob as _glob
        variant_files = sorted(_glob.glob(os.path.join(output_dir, "thumbnail_variant_*.png")))
        if variant_files:
            variants = [{"path": p, "variant_index": i, "description": f"Variant {i}"}
                        for i, p in enumerate(variant_files)]
            store_thumbnail_variants(video_db_id, variants, primary_path=primary_thumb)
    except Exception:
        pass
    if topic_data.get("episode_id"):
        try:
            from services.series_service import mark_episode_produced
            mark_episode_produced(topic_data["episode_id"], video_db_id)
        except Exception:
            pass


# ── Content Loop (daily) ────────────────────────────────────────────────────

def run_content_loop(config: dict, upload: bool = True, dry_run: bool = False) -> dict:
    """v2 content loop: topic → research → script → quality → assets → video → queue.

    Produces ONE candidate and sends it to the Telegram approval queue.
    Does NOT upload directly.
    """
    config = _prepare_config(config)
    init_db()

    # Check kill switch
    from agents.kill_switch_agent import is_paused
    if is_paused():
        print("Pipeline is PAUSED (kill switch active). Send /resume to the Telegram bot.")
        return {"status": "paused"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(BASE_DIR, "output", f"video_{timestamp}")
    lang_dir  = os.path.join(run_dir, LANG_CODE)
    image_dir = os.path.join(run_dir, "images")
    os.makedirs(lang_dir, exist_ok=True)
    os.makedirs(image_dir, exist_ok=True)

    run_id = f"v2_{timestamp}"
    run_summary = {"run_dir": run_dir, "timestamp": timestamp, "run_id": run_id, "videos": []}
    result = {"language": LANG_NAME, "language_code": LANG_CODE,
              "video_url": None, "shorts_url": None}

    print(f"\n{'='*60}")
    print(f"  Content Loop (v2 Tech Explainer) — {timestamp}")
    print(f"{'='*60}\n")

    try:
        # 1. Topic
        print("[1] Selecting topic...")
        topic_data = generate_topic(config)
        print(f"  Topic: {topic_data['topic']}")
        log_run(run_dir, "topic", "success", topic_data)

        # 2. Research (NEW in v2)
        print("[2] Researching topic...")
        from agents.research_agent import research
        fact_sheet = research(topic_data["topic"], config)
        log_run(run_dir, "research", "success", {"topic": topic_data["topic"]})
        with open(os.path.join(run_dir, "fact_sheet.json"), "w") as f:
            json.dump(fact_sheet, f, indent=2, ensure_ascii=False)

        # 3. Script (now consumes fact_sheet)
        print("[3] Writing Hinglish tech-explainer script...")
        script_data = generate_script(config, topic_data, language=LANG_NAME, fact_sheet=fact_sheet)
        print(f"  Title: {script_data['title']}")
        print(f"  Scenes: {len(script_data['scenes'])}")
        log_run(run_dir, "script", "success", script_data)

        # 4. Quality gate (NEW in v2)
        print("[4] Quality scoring...")
        from agents.quality_agent import score as quality_score
        qs = quality_score(script_data, config, run_id=run_id)
        log_run(run_dir, "quality", qs.verdict, {
            "total": qs.total, "hook": qs.hook, "narrative": qs.narrative,
            "specificity": qs.specificity, "hinglish": qs.hinglish,
            "verdict": qs.verdict,
        })

        if qs.verdict == "reject":
            # Try once more with suggestions
            print("[4b] Rejected — retrying with suggestions...")
            script_data = generate_script(
                config, topic_data, language=LANG_NAME,
                fact_sheet=fact_sheet, rewrite_suggestions=qs.rewrite_suggestions,
            )
            qs = quality_score(script_data, config, run_id=f"{run_id}_retry")
            print(f"  Retry score: {qs.total}/100 → {qs.verdict}")
            if qs.verdict == "reject":
                print(f"  Still rejected. Shelving topic for today.")
                run_summary["pipeline_type"] = "content_loop"
                run_summary["shelved"] = True
                send_run_summary(config, run_summary)
                return run_summary

        with open(os.path.join(run_dir, "script.json"), "w") as f:
            json.dump(script_data, f, indent=2, ensure_ascii=False)

        # 5. Images
        print("[5] Generating images...")
        image_files = generate_images(config, script_data, image_dir)
        log_run(run_dir, "images", "success", {"count": len(image_files)})

        # 6. Voiceover
        voice = pick_voice(config, LANG_CODE)
        print("[6] Generating voiceover...")
        audio_files = generate_voiceover_only(config, script_data, lang_dir, voice=voice)
        log_run(run_dir, "voiceover", "success", {"voice": voice})

        # 7. Animation (Ken Burns)
        print("[7] Animating scenes (Ken Burns)...")
        animated_clips = animate_all_scenes(
            config, image_files, audio_files, script_data, lang_dir
        )
        log_run(run_dir, "animation", "success", {"clips": len(animated_clips)})

        # 8. Captions
        print("[8] Generating captions...")
        srt_path = generate_srt(script_data, audio_files, lang_dir, language=LANG_CODE)

        # 9. Assemble video
        print("[9] Assembling video...")
        video_path = assemble_animated_video(
            config, script_data, animated_clips, audio_files, lang_dir
        )
        print(f"  Saved: {video_path}")
        log_run(run_dir, "video", "success", {"path": video_path})

        # 10. Metadata + thumbnails
        print("[10] Generating metadata + thumbnails...")
        metadata = generate_metadata(config, topic_data, script_data, language=LANG_NAME)
        yt_thumb = generate_youtube_thumbnail(config, metadata, image_files[0], lang_dir, content_type="video")
        print(f"  Title: {metadata['title']}")
        log_run(run_dir, "metadata", "success", metadata)
        with open(os.path.join(lang_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        _generate_thumbnail_variants(config, metadata, image_files, lang_dir, "video")

        # 11. Queue for approval (NOT direct upload)
        print("[11] Queuing for Telegram approval...")
        queue_for_approval(run_id, video_path, qs.total, config)

        # Send to Telegram if bot config exists
        tg_config = config.get("telegram", {})
        if tg_config.get("bot_token") and tg_config.get("chat_id") and not dry_run:
            try:
                from agents.approval_agent import send_candidate_sync
                import glob as _glob
                thumb_variants = sorted(_glob.glob(os.path.join(lang_dir, "thumbnail_variant_*.png")))
                if not thumb_variants:
                    thumb_variants = [yt_thumb] if yt_thumb else []
                titles = [metadata.get("title", "Untitled")]
                # Generate 2 more title variants via ab_agent if available
                try:
                    from agents.ab_agent import generate_title_variants
                    extra_titles = generate_title_variants(config, metadata, count=2)
                    titles.extend(extra_titles)
                except Exception:
                    pass

                quality_dict = {
                    "total": qs.total, "hook": qs.hook, "narrative": qs.narrative,
                    "specificity": qs.specificity, "hinglish": qs.hinglish,
                    "verdict": qs.verdict, "flags": qs.flags,
                }
                send_candidate_sync(config, run_id, video_path, thumb_variants, titles, quality_dict)
                print("  Telegram notification sent.")
            except Exception as e:
                print(f"  Warning: Telegram send failed: {e}")
        else:
            print("  (Telegram not configured or dry-run, skipping notification)")

        # Cleanup intermediates
        _cleanup(lang_dir, image_dir)

        run_summary["videos"].append(result)
        run_summary["pipeline_type"] = "content_loop"

        print(f"\n{'='*60}")
        print(f"  Content Loop complete! Candidate queued: {run_id}")
        print(f"  Output: {run_dir}")
        print(f"{'='*60}\n")

        send_run_summary(config, run_summary)
        return run_summary

    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        log_run(run_dir, "error", "failed", {"error": str(e)})
        run_summary["videos"].append(result)
        run_summary["pipeline_type"] = "content_loop"
        run_summary["fatal_error"] = str(e)
        send_run_summary(config, run_summary)
        raise


# ── Feedback Loop (every 6h) ────────────────────────────────────────────────

def run_feedback_loop(config: dict) -> dict:
    """Analytics → learning → kill-switch check."""
    init_db()
    results = {}

    print(f"\n{'='*60}")
    print(f"  Feedback Loop — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Analytics sweep
    try:
        print("[1] Analytics sweep...")
        from services.analytics_service import run_analytics_sweep
        run_analytics_sweep(config)
        results["analytics"] = "ok"
    except Exception as e:
        print(f"  Analytics failed: {e}")
        results["analytics"] = str(e)

    # 2. Learning update
    try:
        print("[2] Learning update...")
        from agents.learning_agent import daily_update
        learning = daily_update(config)
        results["learning"] = learning
    except Exception as e:
        print(f"  Learning failed: {e}")
        results["learning"] = str(e)

    # 3. Kill switch check
    try:
        print("[3] Kill switch check...")
        from agents.kill_switch_agent import check
        verdict = check(config)
        results["kill_switch"] = {"triggered": verdict.triggered}
        if verdict.triggered:
            print(f"  KILL SWITCH TRIGGERED: {verdict.diagnosis}")
    except Exception as e:
        print(f"  Kill switch check failed: {e}")
        results["kill_switch"] = str(e)

    print(f"\n  Feedback loop complete.\n")
    return results


# ── Strategy Loop (weekly) ──────────────────────────────────────────────────

def run_strategy_loop(config: dict) -> dict:
    """Trends + competitor + cluster + series refresh."""
    init_db()
    results = {}

    print(f"\n{'='*60}")
    print(f"  Strategy Loop — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Competitor intel
    try:
        print("[1] Competitor analysis...")
        from agents.competitor_agent import weekly_intel
        intel = weekly_intel(config)
        results["competitor"] = f"{len(intel)} videos analyzed"
    except Exception as e:
        print(f"  Competitor analysis failed: {e}")
        results["competitor"] = str(e)

    # 2. Trend refresh
    if config.get("trends", {}).get("enabled", False):
        try:
            print("[2] Trend refresh...")
            from services.trend_service import refresh_trends
            refresh_trends(config)
            results["trends"] = "ok"
        except Exception as e:
            print(f"  Trend refresh failed: {e}")
            results["trends"] = str(e)

    # 3. Cluster refresh
    if config.get("clusters", {}).get("enabled", False):
        try:
            print("[3] Cluster refresh...")
            from services.cluster_service import refresh_clusters
            refresh_clusters(config)
            results["clusters"] = "ok"
        except Exception as e:
            print(f"  Cluster refresh failed: {e}")
            results["clusters"] = str(e)

    # 4. Series refresh
    if config.get("series", {}).get("enabled", False):
        try:
            print("[4] Series refresh...")
            from services.series_service import generate_series
            generate_series(config)
            results["series"] = "ok"
        except Exception as e:
            print(f"  Series refresh failed: {e}")
            results["series"] = str(e)

    print(f"\n  Strategy loop complete.\n")
    return results


# ── Publish approved candidates ─────────────────────────────────────────────

def run_publish_approved(config: dict, dry_run: bool = False) -> list:
    """Upload all approved candidates from the queue."""
    init_db()
    from agents.upload_agent import publish_from_queue
    return publish_from_queue(config, dry_run=dry_run)


# ── Music pre-generation ────────────────────────────────────────────────────

def generate_music_library(config: dict, count: int = 10):
    """Download royalty-free background music tracks to data/music/."""
    music_dir = os.path.join(BASE_DIR, "data", "music")
    os.makedirs(music_dir, exist_ok=True)

    import requests as req

    # Tech/explainer appropriate tracks — FesliyanStudios.com (David Renda)
    BASE = "https://www.fesliyanstudios.com/musicfiles/"
    tracks = [
        (BASE + "2020-05-29_-_Curious_Kiddo_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Curious_Kiddo_-_www.FesliyanStudios.com_David_Renda.mp3",
         "curious_upbeat.mp3"),
        (BASE + "2020-05-29_-_Play_Date_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Play_Date_-_www.FesliyanStudios.com_David_Renda.mp3",
         "playful_light.mp3"),
        (BASE + "2021-12-06_-_Dancing_Silly_-_www.FesliyanStudios.com/"
               + "2021-12-06_-_Dancing_Silly_-_www.FesliyanStudios.com.mp3",
         "energetic_bounce.mp3"),
        (BASE + "2020-06-05_-_Duck_Duck_Goose_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-06-05_-_Duck_Duck_Goose_-_www.FesliyanStudios.com_David_Renda.mp3",
         "upbeat_discovery.mp3"),
        (BASE + "2020-05-29_-_Clap_And_Sing_-_www.FesliyanStudios.com_David_Renda/"
               + "2020-05-29_-_Clap_And_Sing_-_www.FesliyanStudios.com_David_Renda.mp3",
         "bright_explainer.mp3"),
    ]

    print(f"\nDownloading {min(count, len(tracks))} background music tracks → data/music/\n")
    print("  Source: FesliyanStudios.com (David Renda) — free for commercial use\n")

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
                raise ValueError(f"Response too small ({len(r.content)} bytes)")
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"           Saved ({len(r.content)//1024} KB)")
            success += 1
        except Exception as e:
            print(f"           Failed: {e}")
        time.sleep(1)

    print(f"\nDone! {success}/{min(count, len(tracks))} tracks in data/music/")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config = load_config()
    args   = sys.argv[1:]
    upload = "--no-upload" not in args
    dry_run = "--dry-run" in args

    if "--help" in args:
        print("Usage:")
        print("  python main.py --content-loop              # daily candidate production")
        print("  python main.py --content-loop --no-upload   # local test")
        print("  python main.py --content-loop --dry-run     # skip Telegram + upload")
        print("  python main.py --approval-bot               # long-running Telegram bot")
        print("  python main.py --publish-approved            # upload approved candidates")
        print("  python main.py --publish-approved --dry-run  # show what would upload")
        print("  python main.py --feedback-loop               # analytics → learning → kill-switch")
        print("  python main.py --strategy-loop               # trends + competitor + cluster + series")
        print("  python main.py --analytics-sweep             # one-shot bulk analytics fetch")
        print("  python main.py --generate-music              # download background music")
        print("  python main.py --cleanup-old [--days 7] [--dry-run]")

    # --- v2 Core loops ---
    elif "--content-loop" in args:
        run_content_loop(config, upload=upload, dry_run=dry_run)

    elif "--approval-bot" in args:
        init_db()
        from agents.approval_agent import ApprovalBot
        bot = ApprovalBot(config)
        bot.run()

    elif "--publish-approved" in args:
        run_publish_approved(config, dry_run=dry_run)

    elif "--feedback-loop" in args:
        run_feedback_loop(config)

    elif "--strategy-loop" in args:
        run_strategy_loop(config)

    # --- Analytics + Intelligence ---
    elif "--analytics-sweep" in args:
        init_db()
        from services.analytics_service import run_analytics_sweep
        run_analytics_sweep(config)

    elif "--recompute-weights" in args:
        init_db()
        from services.analytics_service import compute_category_weights
        compute_category_weights(config)

    elif "--refresh-trends" in args:
        init_db()
        from services.trend_service import refresh_trends
        refresh_trends(config)

    elif "--generate-clusters" in args:
        init_db()
        from services.cluster_service import refresh_clusters
        refresh_clusters(config)

    elif "--generate-series" in args:
        init_db()
        from services.series_service import generate_series
        generate_series(config)

    elif "--list-series" in args:
        init_db()
        from services.series_service import list_series
        list_series(config)

    elif "--optimize-thumbnails" in args:
        init_db()
        from services.thumbnail_ab_service import run_thumbnail_optimization
        run_thumbnail_optimization(config)

    # --- Maintenance ---
    elif "--generate-music" in args:
        generate_music_library(config)
    elif "--cleanup-old" in args:
        days = 7
        if "--days" in args:
            idx = args.index("--days")
            days = int(args[idx + 1])
        cleanup_old_output_dirs(days_old=days, dry_run=dry_run)

    # --- Legacy (kept for backwards compat during transition) ---
    elif "--video" in args:
        run_content_loop(config, upload=upload, dry_run=dry_run)
    elif "--shorts" in args:
        run_content_loop(config, upload=upload, dry_run=dry_run)

    else:
        print("Usage: python main.py --content-loop | --approval-bot | --publish-approved | --feedback-loop | --strategy-loop")
        print("Run with --help for more details.")
        sys.exit(1)
