# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in API keys
cp config.example.yaml config.yaml
```

YouTube OAuth: place `client_secrets.json` in the project root. On first upload, `token.json` is generated via browser auth. GCP credentials path goes in `config.yaml` under `tts.google_tts_credentials`.

Background music (run once before the first pipeline run):
```bash
python main.py --generate-music
python main.py --generate-lullaby-music   # for lullaby pipeline
```

## Running the pipeline

```bash
# Production runs (generates + uploads to YouTube)
python main.py --video         # 2–3 min landscape video
python main.py --shorts        # ~1 min vertical Short
python main.py --poem          # rhyming poem video
python main.py --lullaby       # bedtime lullaby video

# Skip upload (local test)
python main.py --video --no-upload

# AI animation instead of Ken Burns
python main.py --video --animate

# Scheduler (video at 09:00 IST, shorts at 21:00 IST, daily)
python main.py --schedule
python main.py --schedule --animate   # AI-animated shorts

# Maintenance
python main.py --cleanup-old --days 7 --dry-run
python main.py --cleanup-old --days 7     # actually deletes

# v2 Growth Intelligence
python main.py --analytics-sweep          # fetch YouTube analytics for uploaded videos
python main.py --recompute-weights        # recompute category performance weights
python main.py --refresh-trends           # discover trending kids topics
python main.py --generate-clusters        # group topics into thematic clusters
python main.py --generate-series          # create episodic series from clusters
python main.py --list-series              # show active series with progress
python main.py --optimize-thumbnails      # auto-replace underperforming thumbnails
```

## Architecture

### Content type → pipeline flow

Each pipeline in `main.py` follows the same numbered steps:
1. **Topic** (`topic_agent`) — picks topic from clusters/series/trends/random based on config weights
2. **Script** (`script_agent` / `poem_agent` / `lullaby_agent`) — generates Hinglish script with per-scene `visual_description` (English, for AI image prompts) and `narration` (Hinglish)
3. **Images** (`asset_agent.generate_images`) — calls image provider (Replicate/OpenAI/HuggingFace/Pexels)
4. **Voiceover** (`asset_agent`) — calls TTS provider (Google Cloud TTS / ElevenLabs / edge-tts / OpenAI)
5. **Animation** (`animation_agent`) — Ken Burns effect or AI video (Kling via fal.ai, Veo 2 via google-genai)
6. **Assembly** (`video_agent`) — MoviePy combines animated clips + audio + subtitles + bg music into final MP4
7. **Metadata + Thumbnail** (`metadata_agent`) — GPT-4o-mini generates YouTube title/description/tags; Pillow generates thumbnail
8. **Upload** (`upload_agent`) — YouTube Data API v3 upload + captions; optionally Instagram Graph API
9. **DB record** (`agents/db.py`) — SQLite at `data/pipeline.db`

### Agent responsibilities

| Agent | File | Purpose |
|---|---|---|
| `topic_agent` | `agents/topic_agent.py` | Topic selection with category weighting, trend/cluster/series integration |
| `script_agent` | `agents/script_agent.py` | Full video and Shorts scripts (Hinglish) |
| `poem_agent` | `agents/poem_agent.py` | Rhyming verse scripts |
| `lullaby_agent` | `agents/lullaby_agent.py` | Verse-chorus lullaby scripts |
| `asset_agent` | `agents/asset_agent.py` | Image generation + TTS voiceover (multi-provider) |
| `animation_agent` | `agents/animation_agent.py` | Ken Burns / AI video per scene |
| `video_agent` | `agents/video_agent.py` | Final video assembly via MoviePy |
| `metadata_agent` | `agents/metadata_agent.py` | YouTube/Instagram metadata + thumbnails |
| `upload_agent` | `agents/upload_agent.py` | YouTube + caption upload |
| `caption_agent` | `agents/caption_agent.py` | SRT subtitle generation |
| `analytics_agent` | `agents/analytics_agent.py` | YouTube Analytics API fetcher |
| `ab_agent` | `agents/ab_agent.py` | A/B variant title/hook generation |
| `playlist_agent` | `agents/playlist_agent.py` | Auto-playlist management |
| `instagram_agent` | `agents/instagram_agent.py` | Instagram Reels upload |
| `notification_agent` | `agents/notification_agent.py` | Email run summaries |
| `rate_limiter` | `agents/rate_limiter.py` | API quota throttling |

### v2 Services (`services/`)

Higher-level intelligence modules that wrap multiple agents/DB calls:

- `analytics_service` — bulk analytics sweep, category weight computation
- `trend_service` — trending topic discovery (YouTube search/autocomplete/competitor analysis)
- `cluster_service` — GPT-powered topic clustering for topical authority
- `series_service` — episodic series planning and management
- `thumbnail_ab_service` — thumbnail variant generation and auto-replacement
- `retention_service` — retention analysis
- `schedule_optimizer_service` — optimal upload time selection from historical data

### Data storage

- **SQLite** (`data/pipeline.db`) — all structured data: videos, metrics, A/B variants, playlists, topic scores, trend topics, clusters, series, thumbnail variants, upload time slots
- **`data/topics_history.json`** — flat topic deduplication history
- **`output/`** — per-run directories (`video_YYYYMMDD_HHMMSS/`, `shorts_*`, etc.). Each run directory contains `script.json`, `metadata.json`, `run_log.json`; intermediate files (audio, images, animated_clips) are deleted after assembly
- **`data/music/`** — pre-generated background music MP3s; `data/music/lullaby/` for lullaby-specific tracks

### Configuration

All behaviour is controlled by `config.yaml` (copy from `config.example.yaml`). Key sections:
- `tts.provider` — `google` | `elevenlabs` | `sarvam` | `openai` | `edge-tts`
- `image_provider` — `replicate` | `openai` | `huggingface` | `pexels`
- `animation.provider` — `kenburns` (free) | `ai` (Replicate ~$0.20/scene) | `ai_with_fallback`
- `voice_rotation.enabled` — rotates Google TTS voices per video to avoid repetition detection
- `format_variation.enabled` — randomizes subtitle styles and Ken Burns zoom per video
- `trends/clusters/series` — v2 growth intelligence, each independently toggleable

### Content language

All content is **Hinglish** (Hindi-English code-switching). `LANG_CODE = "hi"`, `LANG_NAME = "Hindi"` in `main.py` triggers Hinglish mode in the script agents. `visual_description` fields in scripts are always kept in English for AI image generation prompts.
