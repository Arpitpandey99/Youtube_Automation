# YouTube Kids Video Automation - Architecture

## System Overview

Fully automated pipeline that generates and uploads kid-friendly YouTube videos and Instagram Reels in multiple languages using AI. Runs on AWS EC2 t4g.small (ARM64) with twice-daily cron, GitHub Actions CI/CD, and Gmail email notifications after each run.

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEVELOPER (Mac)                             │
│   git push → GitHub (main branch)                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ triggers
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              GITHUB ACTIONS (.github/workflows/deploy.yml)      │
│   appleboy/ssh-action → EC2: git pull + pip install             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ deploys to
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              AWS EC2 t4g.small (ARM64 Graviton2)                 │
│              Ubuntu 24.04 LTS — Asia/Kolkata (IST)              │
│                                                                 │
│  crontab:                                                       │
│    0  9 * * *  python main.py --animated >> logs/run.log        │
│    0 21 * * *  python main.py --animated >> logs/run.log        │
│                         │                                       │
│                         ▼                                       │
│              run_animated_pipeline()                            │
│                         │                                       │
│                         ▼                                       │
│              Email summary sent (Gmail SMTP)                    │
│              → arpitpandey6599@gmail.com                        │
│              → prachipandey2024@gmail.com                       │
└─────────────────────────────────────────────────────────────────┘
                           │ uploads to
                           ▼
             YouTube (full video + Shorts)
```

### EC2 Instance Details

| Spec | Value |
|------|-------|
| Instance type | t4g.small (ARM64 Graviton2) |
| vCPU | 2 |
| RAM | 2 GB |
| Storage | 20 GB gp3 EBS |
| OS | Ubuntu 24.04 LTS (ARM64) |
| Timezone | Asia/Kolkata (IST) |
| Pricing model | Spot (~$3-4/month) |
| Elastic IP | Yes (static, for GitHub Actions SSH) |

### Monthly Cost Estimate

| Item | Cost |
|------|------|
| t4g.small Spot Instance | ~$3-4 |
| 20 GB gp3 EBS volume | $1.60 |
| Elastic IP (running) | $0.00 |
| Data transfer | ~$0.50 |
| **Total** | **~$5-6/month** |

---

## Pipeline Architecture

### Regular Pipeline (`python main.py`)

```
┌─────────────────────────────────────────────────────────────────┐
│              SCHEDULER / PREFECT ORCHESTRATION                   │
│       (cron / Python schedule / Prefect with retries)            │
│           Triggers pipeline twice daily (9 AM + 9 PM IST)        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Analytics  │ (fetch metrics from previous runs)
                    │  Feedback   │
                    └──────┬──────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (main.py)                        │
│                                                                 │
│  ┌───────────┐   ┌──────────┐   ┌──────────────────────────┐   │
│  │  Step 1   │──▶│  Step 2  │──▶│        Step 3            │   │
│  │  Topic    │   │  Script  │   │   Image Generation       │   │
│  │(+analytics│   │(+brand   │   │    (rate-limited)        │   │
│  │  hints)   │   │  voice)  │   │       (shared)           │   │
│  └───────────┘   └──────────┘   └──────────────────────────┘   │
│                                              │                  │
│                    ┌─────────────────────────┐│                  │
│                    │   FOR EACH LANGUAGE     ││                  │
│                    │   (English, Hindi)      │▼                  │
│  ┌─────────────────┴────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  ┌──────────┐  ┌───────────┐  ┌────────────────────┐    │   │
│  │  │ Script   │  │ Voice     │  │  Video Assembly    │    │   │
│  │  │ (lang)   │─▶│ (random)  │─▶│  (full + shorts)  │    │   │
│  │  └──────────┘  └───────────┘  └────────────────────┘    │   │
│  │                      │                │                 │   │
│  │               ┌──────▼──────┐         │                 │   │
│  │               │  Captions   │         │                 │   │
│  │               │  (.srt)     │         │                 │   │
│  │               └─────────────┘         │                 │   │
│  │                                       │                 │   │
│  │  ┌──────────┐  ┌───────────┐  ┌──────▼─────────────┐   │   │
│  │  │ Metadata │  │ Thumbnails│  │     UPLOAD         │   │   │
│  │  │ + A/B    │─▶│ (YT + IG │─▶│ YT + Shorts + IG  │   │   │
│  │  │ Testing  │  │ + Shorts) │  │ + Captions         │   │   │
│  │  └──────────┘  └───────────┘  └────────────────────┘   │   │
│  │                                       │                 │   │
│  │                              ┌────────▼────────┐        │   │
│  │                              │ Playlist + DB   │        │   │
│  │                              │ + Cleanup       │        │   │
│  │                              └─────────────────┘        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Email     │ Gmail SMTP — run summary + video links
                    │  Summary    │ → notification_agent.py
                    └─────────────┘
```

### Animated Pipeline (`python main.py --animated`)

```
Topic → English Script → Cartoon Images (Replicate Flux Schnell)
                                │
                    FOR EACH LANGUAGE
                                │
                         Voiceover (OpenAI TTS)
                                │
                    Ken Burns Animation (animation_agent.py)
                    ┌────────────────────────┐
                    │  Each image → VideoClip │
                    │  Effects (random):      │
                    │   zoom_in / zoom_out    │
                    │   pan_left / pan_right  │
                    │   pan_up / combined     │
                    └────────────────────────┘
                                │
                    Assemble animated video (MoviePy)
                    ├── Full video (1920x1080, ~3 min)
                    └── Shorts (1080x1920 vertical, ≤59s)
                              + blurred background fill
                                │
                    Upload → YouTube + Shorts
                                │
                    Email summary → Gmail
```

---

## Pipeline Steps

### Step 0: Analytics Feedback (Optional)
**Agent:** `agents/analytics_agent.py`
**Tool:** YouTube Data API v3

- Fetches views/likes/CTR for videos uploaded 48+ hours ago
- Stores metrics in SQLite (`data/pipeline.db`)
- Updates topic scores by category
- Provides performance hints to topic generation
- **Config:** `analytics.enabled: true/false`

### Step 1: Topic Generation
**Agent:** `agents/topic_agent.py`
**Tool:** GPT-4o-mini

- Reads last 50 topics from `data/topics_history.json` to prevent duplicates
- When analytics enabled: injects top-performing categories as hints
- Generates a unique kid-friendly topic with category and target age
- **Output:** `{ topic, category, target_age, description }`

### Step 2: Script Writing
**Agent:** `agents/script_agent.py`
**Tool:** GPT-4o-mini

- Generates scene-by-scene script for specified language
- Brand voice: when enabled, injects tone, catchphrases, vocabulary level
- For non-English: narration in target language, `visual_description` stays in English
- Also generates `generate_shorts_script()` — re-hooked, punchier version for Shorts
- **Output:** `{ title, intro_hook, scenes[], outro }`

### Step 3: Image Generation (Shared)
**Agent:** `agents/asset_agent.py`
**Tool:** Replicate (Flux Schnell) / DALL-E 3 / HuggingFace / Pexels

- Token-bucket rate limiter prevents API bans
- Images generated once and shared across all languages
- For `--animated`: uses cartoon image style (Pixar-like, no text)
- **Output:** `[ scene_1.png, scene_2.png, ... ]`

### Step 4: Voice Selection + Voiceover (Per Language)
**Agent:** `agents/asset_agent.py`
**Tool:** OpenAI TTS / edge-tts / ElevenLabs

- **Default: OpenAI TTS** (nova voice, reliable, no 2FA needed)
- edge-tts: free but occasionally fails with `NoAudioReceived`
- ElevenLabs: premium quality
- **Output:** `[ scene_1.mp3, scene_2.mp3, ... ]`

### Step 5: Ken Burns Animation (Animated Pipeline Only)
**Agent:** `agents/animation_agent.py`
**Tool:** MoviePy + NumPy + Pillow

- Converts static images into animated video clips
- Six effects (randomly assigned per scene):
  - `zoom_in` — progressive zoom into center
  - `zoom_out` — start zoomed, slowly pull out
  - `pan_left` — horizontal pan right→left
  - `pan_right` — horizontal pan left→right
  - `pan_up` — vertical pan bottom→top
  - `combined` — slow zoom + gentle horizontal pan
- Each effect uses `VideoClip(make_frame, duration)` for smooth animation
- Images pre-scaled 20–50% larger than target to allow room for movement
- **Output:** `[ scene_1.mp4, scene_2.mp4, ... ]` (animated clips)

### Step 6: Caption & SRT Generation (Per Language)
**Agent:** `agents/caption_agent.py`

- Builds SRT subtitle files from script narration + audio durations
- Each scene split into ~10-word subtitle chunks, timed to audio
- **Output:** `captions_en.srt`

### Step 7: Video Assembly (Per Language)
**Agent:** `agents/video_agent.py`
**Tool:** MoviePy

#### Regular Full Video (Landscape 1920x1080)
- Each scene: image + audio + subtitle overlay + crossfade transitions
- Background music from `data/music/`, looped at 8% volume
- **Output:** `final_video.mp4` (~3 min)

#### Regular Shorts (Vertical 1080x1920)
- Re-hooked punchier script, best 3 scenes
- Falls back to original truncation if re-hook fails
- **Output:** `shorts_video.mp4` (≤59s)

#### Animated Full Video (Landscape 1920x1080)
- Uses pre-animated Ken Burns clips instead of static images
- Clips looped to match audio duration
- Crossfade transitions between scenes
- **Output:** `final_video.mp4` (~3 min)

#### Animated Shorts (Vertical 1080x1920)
- Animated clips converted to vertical with blurred background fill
- `_prepare_vertical_clip()`: blurs + darkens landscape frame as background, centers foreground
- **Output:** `shorts_video.mp4` (≤59s)

### Step 8: Metadata + Thumbnails (Per Language)
**Agent:** `agents/metadata_agent.py`, `agents/ab_agent.py`
**Tools:** GPT-4o-mini + Pillow

- GPT generates SEO-optimized metadata (title, description, tags)
- A/B Testing (optional): 3 title/hook/thumbnail variants
- **Platform thumbnails:**
  - YouTube: 1280×720 horizontal
  - Instagram: 1080×1920 vertical
  - Shorts: 1080×1920 vertical

### Step 9: YouTube Upload + Captions
**Agent:** `agents/upload_agent.py`
**Tool:** YouTube Data API v3 (OAuth 2.0)

- Uploads video + thumbnail + SRT captions
- Rate-limited via token bucket
- **Output:** video URL + video_id

### Step 10: Playlist Automation (Optional)
**Agent:** `agents/playlist_agent.py`

- Auto-creates playlists by category + language when 3+ videos exist
- **Config:** `playlists.enabled: true/false`

### Step 11: Instagram Assets (Optional)
**Agent:** `agents/instagram_agent.py`

- Saves reel video + caption + thumbnail to `instagram/` folder
- **Config:** `instagram.enabled: true/false`

### Step 12: Email Notification
**Agent:** `agents/notification_agent.py`
**Tool:** Gmail SMTP (App Password) or Resend API

- Sends run summary email after every pipeline completion
- Contains: timestamp, YouTube video links, Shorts links, output directory
- Supports multiple recipients (comma-separated)
- **Providers:** `gmail` (App Password required) or `resend` (free, no 2FA)
- **Config:** `notifications.email.enabled: true`

### Step 13: Database + Cleanup
- Stores video_id, shorts_id in SQLite (`data/pipeline.db`)
- Deletes: audio/, animated_clips/, images/, large video files
- Keeps: run_log.json, scripts (.json), metadata.json, captions (.srt)

---

## Features Summary

| Feature | Config Key | Default | Description |
|---------|-----------|---------|-------------|
| Animated Pipeline | `--animated` flag | Off | Ken Burns effects on cartoon images |
| Email Notifications | `notifications.email.enabled` | false | Gmail/Resend summary after each run |
| Twice-Daily Schedule | cron on EC2 | 9 AM + 9 PM IST | Runs pipeline automatically |
| GitHub Actions CI/CD | `.github/workflows/deploy.yml` | Active | Auto-deploy on push to main |
| Rate Limiting | (always on) | Enabled | Token-bucket per API provider |
| SQLite Database | (always on) | Enabled | Tracks videos, metrics, playlists |
| Brand Voice | `brand_voice.enabled` | false | Consistent tone/catchphrases |
| Multi-TTS | `tts.provider` | openai | OpenAI TTS (default) / edge-tts / ElevenLabs |
| Captions/SRT | (always on) | Enabled | Auto-generated subtitle files |
| Re-hooked Shorts | (always on) | Enabled | Punchier hooks for short-form |
| A/B Testing | `ab_testing.enabled` | false | Test title/hook/thumbnail variants |
| Analytics Loop | `analytics.enabled` | false | Learn from past video performance |
| Playlists | `playlists.enabled` | false | Auto-create & organize playlists |
| Prefect | `orchestration.engine` | simple | Event-driven orchestration with retries |

---

## Project Structure

```
Youtube_Automation/
├── main.py                     # Orchestrator — regular + animated pipeline
├── prefect_flow.py             # Prefect-based orchestration (optional)
├── config.yaml                 # API keys + settings (gitignored)
├── config.example.yaml         # Template config (committed)
├── requirements.txt            # Python dependencies
├── ARCHITECTURE.md             # This file
├── .gitignore
│
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD → AWS EC2
│
├── agents/
│   ├── topic_agent.py          # GPT topic generation (+analytics hints)
│   ├── script_agent.py         # GPT script writing (+brand voice, +shorts script)
│   ├── asset_agent.py          # TTS voiceover (openai/edge/elevenlabs) + images
│   ├── animation_agent.py      # Ken Burns effects → animated VideoClip per scene
│   ├── video_agent.py          # MoviePy assembly (regular + animated, full + shorts)
│   ├── metadata_agent.py       # GPT metadata + platform-specific thumbnails
│   ├── upload_agent.py         # YouTube upload + caption upload (OAuth 2.0)
│   ├── instagram_agent.py      # Instagram Reels asset prep
│   ├── caption_agent.py        # SRT/caption generation
│   ├── notification_agent.py   # Email summary (Gmail SMTP / Resend API)
│   ├── ab_agent.py             # A/B testing for titles/hooks/thumbnails
│   ├── analytics_agent.py      # YouTube analytics feedback loop
│   ├── playlist_agent.py       # Playlist auto-creation & management
│   ├── rate_limiter.py         # Token-bucket rate limiter
│   └── db.py                   # SQLite database (videos, metrics, playlists)
│
├── data/
│   ├── topics_history.json     # Track used topics (avoid repeats)
│   ├── pipeline.db             # SQLite database (gitignored)
│   └── music/                  # Royalty-free background tracks (optional)
│
└── output/                     # Generated files per run (gitignored)
    └── animated_YYYYMMDD_HHMMSS/
        ├── images/             # Shared cartoon scene images
        ├── en/
        │   ├── audio/
        │   ├── animated_clips/ # Ken Burns mp4 clips (deleted after upload)
        │   ├── final_video.mp4
        │   ├── shorts_video.mp4
        │   ├── captions_en.srt
        │   └── metadata.json
        ├── hi/                 # Hindi outputs (same structure)
        ├── script_en.json
        └── run_log.json
```

---

## Tech Stack

| Component | Tool | Cost/run (2 langs) |
|-----------|------|--------------------|
| Text Generation | GPT-4o-mini | ~$0.02 |
| Image Generation | Replicate Flux Schnell | ~$0.02 (6 images) |
| Text-to-Speech | OpenAI TTS (nova) | ~$0.01 |
| Ken Burns Animation | MoviePy + NumPy | Free (CPU) |
| Video Assembly | MoviePy | Free (CPU) |
| Thumbnails | Pillow | Free |
| Captions/SRT | Built-in | Free |
| YouTube Upload | YouTube Data API v3 | Free (quota) |
| Email Notification | Gmail SMTP (App Password) | Free |
| Database | SQLite | Free |
| Scheduling | Linux cron (EC2) | Free |
| **Total per run** | | **~$0.05** |

| Infrastructure | Tool | Cost/month |
|----------------|------|------------|
| Compute | AWS EC2 t4g.small Spot | ~$3-4 |
| Storage | 20 GB gp3 EBS | $1.60 |
| Elastic IP | (while running) | $0.00 |
| Data transfer | Video uploads | ~$0.50 |
| **Total infra** | | **~$5-6** |

---

## Configuration Reference

| Section | Key Settings |
|---------|-------------|
| `openai` | API key, model (gpt-4o-mini) |
| `image_provider` | replicate / openai / huggingface / pexels |
| `replicate` | API token, model (flux-schnell) |
| `tts` | provider (openai/edge-tts/elevenlabs), openai_voice |
| `languages[]` | code, name, voice pool per language |
| `youtube` | client_secrets_file, token_file, category, privacy, made_for_kids |
| `instagram` | enabled, ig_user_id, access_token |
| `content` | niche, target_age, video_duration_minutes, scenes_per_video, image_style |
| `schedule` | upload_days (all 7), upload_time ("21:00") |
| `video` | resolution, fps, bg_music_volume, subtitle_font_size, subtitle_color |
| `animation` | provider (kenburns/ai), image_style, kenburns.zoom_ratio, kenburns.effects |
| `notifications.email` | enabled, provider (gmail/resend), sender_email, sender_password, recipient_email |
| `brand_voice` | enabled, tone, catchphrases, vocabulary_level |
| `ab_testing` | enabled, variants_count, min_data_points |
| `analytics` | enabled, youtube_analytics, fetch_delay_hours |
| `playlists` | enabled, auto_create, min_videos_for_playlist, naming_template |
| `orchestration` | engine (simple/prefect) |

---

## Database Schema (SQLite)

```
videos       → id, video_id, platform, language, topic, category, title, upload_date
metrics      → id, video_id, platform, views, likes, ctr, avg_watch_time, fetched_at
ab_variants  → id, video_db_id, variant_type, variant_data (JSON), is_winner, ctr
topic_scores → id, topic, category, avg_views, avg_ctr, times_used, last_score
playlists    → id, playlist_id, platform, language, category, title, video_count
quota_usage  → id, provider, date, units_used
```

---

## Error Handling

| Error | Handling |
|-------|----------|
| API rate limits | Token-bucket rate limiter blocks until safe |
| Replicate 429 | Retry with 15s × attempt backoff, max 5 attempts |
| edge-tts NoAudioReceived | Switch to OpenAI TTS (`tts.provider: openai`) |
| YouTube invalid_scope | Delete token.json to force OAuth re-authorization |
| YouTube invalid tags | Sanitize: remove special chars, max 10 tags, 30-char limit |
| YouTube upload fails | Graceful catch, log error, continue pipeline |
| Email notification fails | Warning printed, pipeline continues |
| Ken Burns shape mismatch | Use `VideoClip(make_frame)` not `ImageClip(make_frame)` |
| Pillow ANTIALIAS removed | Monkey-patch: `Image.ANTIALIAS = Image.LANCZOS` |
| ImageMagick not installed | Subtitle rendering falls back to no-subtitle mode |
| Shorts script fails | Falls back to original truncation approach |
| A/B variant fails | Falls back to original metadata |
| Playlist creation fails | Skipped, video still uploads normally |

---

## CLI Usage

```bash
# Local development
python main.py                          # Regular pipeline: generate + upload
python main.py --no-upload              # Generate only (no YouTube upload)
python main.py --animated               # Animated cartoon pipeline + upload
python main.py --animated --no-upload   # Animated, no upload (test mode)
python main.py --schedule               # Scheduler: regular pipeline (all 7 days)
python main.py --schedule --animated    # Scheduler: animated pipeline (all 7 days)
python main.py --prefect                # Prefect orchestration
python main.py --prefect --animated     # Prefect + animated
python main.py --help                   # Show usage

# On EC2 (cron runs these automatically)
python main.py --animated               # 9 AM IST + 9 PM IST via crontab
```

---

## EC2 Deployment Guide

### One-time Setup

```bash
# 1. SSH into EC2
ssh -i ~/.ssh/youtube-automation.pem ubuntu@YOUR_ELASTIC_IP

# 2. Install system dependencies
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg git imagemagick
sudo timedatectl set-timezone Asia/Kolkata
timedatectl   # verify: IST (UTC+0530)

# 3. Clone repo and install Python dependencies
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git ~/youtube_automation
cd ~/youtube_automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p logs

# 4. Upload secret files (run from your Mac)
scp -i ~/.ssh/youtube-automation.pem config.yaml ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/
scp -i ~/.ssh/youtube-automation.pem client_secrets.json ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/
scp -i ~/.ssh/youtube-automation.pem token.json ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/

# 5. Test pipeline manually
source ~/youtube_automation/venv/bin/activate
cd ~/youtube_automation
python main.py --animated --no-upload   # test without upload first
python main.py --animated               # full test: generate + upload + email

# 6. Set up cron (twice daily at 9 AM + 9 PM IST)
crontab -e
# Add these two lines:
0  9 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --animated >> logs/run.log 2>&1
0 21 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --animated >> logs/run.log 2>&1

# 7. Create deploy key for GitHub Actions
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy   # copy this — paste as EC2_SSH_KEY GitHub Secret
```

### GitHub Secrets Required

Go to: GitHub repo → Settings → Secrets and variables → Actions → New repository secret

| Secret | Value |
|--------|-------|
| `EC2_HOST` | Your Elastic IP address |
| `EC2_SSH_KEY` | Contents of `~/.ssh/github_deploy` (private key) |

### Verify Everything Works

```bash
# Check cron is set
crontab -l

# Watch live logs
tail -f ~/youtube_automation/logs/run.log

# Check last git pull (CI/CD test)
git log -1 --oneline

# Test email
cd ~/youtube_automation && source venv/bin/activate
python3 -c "
import yaml; from agents.notification_agent import send_run_summary
c = yaml.safe_load(open('config.yaml'))
send_run_summary(c, {'timestamp':'test','run_dir':'/tmp','videos':[{'language':'English','video_url':'https://youtu.be/test','shorts_url':None}]})
"
```

---

## Setup Requirements

1. **Python 3.10+** with virtual environment
2. **API Keys:** OpenAI (TTS + GPT), Replicate (image generation)
3. **Google Cloud:** OAuth 2.0 credentials for YouTube Data API v3 (`client_secrets.json`)
4. **Gmail App Password:** 16-char app password (Google Account → Security → 2-Step Verification → App Passwords)
5. **AWS EC2:** t4g.small ARM64 instance with Elastic IP
6. **GitHub Secrets:** `EC2_HOST` + `EC2_SSH_KEY` for CI/CD
7. **ffmpeg:** Required by MoviePy (install via apt on EC2)
8. **ImageMagick:** Optional, for subtitle text rendering on videos
9. **ElevenLabs API Key:** Optional, only if `tts.provider: elevenlabs`
10. **Prefect:** Optional, `pip install prefect` only if using `--prefect` mode
