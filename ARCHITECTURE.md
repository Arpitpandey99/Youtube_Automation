# YouTube Kids Video Automation - Architecture

## System Overview

Fully automated pipeline that generates and uploads **Hinglish** kid-friendly YouTube videos and Shorts using AI. Runs on AWS EC2 t4g.small (ARM64) with twice-daily cron, GitHub Actions CI/CD, and Gmail email notifications after each run.

- **`--video`** → 2–3 min animated landscape video (1280×720), uploaded to YouTube
- **`--shorts`** → ~1 min animated vertical Short (1080×1920), uploaded as YouTube Short
- All content is **Hinglish** (60–70% English + 30–40% Hindi), narrated by Indian female voices

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
│   dawidd6/action-send-mail → Gmail deploy notification          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ deploys to
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              AWS EC2 t4g.small (ARM64 Graviton2)                 │
│              Ubuntu 24.04 LTS — Asia/Kolkata (IST)              │
│              2 GB RAM + 2 GB swap — 20 GB gp3 EBS               │
│                                                                 │
│  crontab:                                                       │
│    0  9 * * *  python main.py --video  >> logs/run.log          │
│    0 21 * * *  python main.py --shorts >> logs/run.log          │
│                         │                                       │
│                         ▼                                       │
│              run_video_pipeline()  /  run_shorts_pipeline()     │
│                         │                                       │
│                         ▼                                       │
│              Email summary sent (Gmail SMTP)                    │
│              → arpitpandey6599@gmail.com                        │
│              → prachipandey2024@gmail.com                       │
└─────────────────────────────────────────────────────────────────┘
                           │ uploads to
                           ▼
             YouTube (full video at 9 AM + Short at 9 PM)
```

### EC2 Instance Details

| Spec | Value |
|------|-------|
| Instance type | t4g.small (ARM64 Graviton2) |
| vCPU | 2 |
| RAM | 2 GB + 2 GB swap |
| Storage | 20 GB gp3 EBS |
| OS | Ubuntu 24.04 LTS (ARM64) |
| Timezone | Asia/Kolkata (IST) |
| Pricing model | Spot (~$3-4/month) |
| Elastic IP | Yes (static, for GitHub Actions SSH) |

> **Note:** 2 GB swap added to prevent OOM kill during MoviePy video encoding at 1280×720.

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

### `--video` Pipeline (2–3 min landscape, 9 AM IST)

```
[1] Topic Generation (GPT-4o-mini)
         │  topic + category + target_age
         ▼
[2] Hinglish Script (GPT-4o-mini, language="Hindi")
         │  6 scenes, narration in Hinglish, visual_description in English
         ▼
[3] Image Generation (Replicate Flux Schnell)
         │  6 soft/dreamy cartoon scene images (shared)
         │  style: "soft watercolor illustration, pastel colors, dreamy..."
         ▼
[4] Indian Accent Voiceover (edge-tts)
         │  Random pick from: en-IN-NeerjaNeural | en-IN-NeerjaExpressiveNeural | hi-IN-SwaraNeural
         │  6 scene audio files (MP3)
         ▼
[5] Ken Burns Animation (MoviePy + NumPy)
         │  Each image → animated VideoClip
         │  Random effect per scene: zoom_in / zoom_out / pan_left / pan_right / pan_up / combined
         ▼
[6] Caption / SRT Generation
         │  Timed subtitles from narration + audio durations
         ▼
[7] Video Assembly (MoviePy) — 1280×720
         │  Animated clips + audio + crossfade transitions
         │  Background music: random track from data/music/ (looped, 8% volume)
         │  Output: final_video.mp4
         ▼
[8] Metadata + Thumbnail (GPT-4o-mini + Pillow)
         │  SEO title, Hinglish description, tags
         │  Thumbnail: 1280×720
         ▼
[9] YouTube Upload + Captions (YouTube Data API v3)
         │  Uploads video + thumbnail + .srt captions
         ▼
[10] Database (SQLite) + Cleanup
         │  Stores video_id; deletes audio/, animated_clips/, images/
         ▼
Email Summary (Gmail SMTP)
```

### `--shorts` Pipeline (~1 min vertical, 9 PM IST)

```
[1] Topic Generation (GPT-4o-mini)
         ▼
[2] Base Hinglish Script (GPT-4o-mini)
         │  6 scenes — visual_description used for image generation
         ▼
[3] Image Generation (Replicate Flux Schnell)
         │  6 soft/dreamy cartoon scene images (shared)
         ▼
[4] Shorts-Optimised Script (GPT-4o-mini)
         │  Re-hooked punchy version: 3 scenes, ~1 min, strong hook
         ▼
[5] Indian Accent Voiceover (edge-tts)
         │  3 scene audio files for the shorts script
         ▼
[6] Ken Burns Animation (MoviePy + NumPy)
         │  Animated clips from base images
         ▼
[7] Shorts Assembly (MoviePy) — 1080×1920 vertical
         │  Landscape clips → vertical via blurred background fill
         │    blurred + darkened bg fills full 1080×1920 frame
         │    original image centered on top (no stretching)
         │  Background music: random track from data/music/ (looped, 8% volume)
         │  Capped at 59 seconds
         │  Output: shorts_video.mp4
         ▼
[8] Metadata + Thumbnail (GPT-4o-mini + Pillow)
         │  Shorts-optimised title (≤100 chars + #Shorts)
         │  Thumbnail: 1080×1920
         ▼
[9] YouTube Upload (YouTube Data API v3)
         ▼
[10] Database (SQLite) + Cleanup
         ▼
Email Summary (Gmail SMTP)
```

---

## Agent Reference

### `agents/topic_agent.py`
**Tool:** GPT-4o-mini

- Reads last 50 topics from `data/topics_history.json` to prevent duplicates
- Generates kid-friendly topic with category and target age (3-8)
- **Output:** `{ topic, category, target_age, description }`

### `agents/script_agent.py`
**Tool:** GPT-4o-mini

- `generate_script(config, topic, language="Hindi")` → Hinglish mode
  - Narration: 60–70% English + 30–40% Hindi words mixed naturally
  - `visual_description` always stays in English (used as image prompts)
- `generate_shorts_script(config, topic, base_script, language)` → punchy 3-scene version
- **Output:** `{ title, intro_hook, scenes[], outro }`

### `agents/asset_agent.py`
**Tools:** Replicate (Flux Schnell), edge-tts / OpenAI TTS / ElevenLabs

**Image generation:**
- `generate_images()` — routes to configured `image_provider`
- Providers: `replicate` (default, Flux Schnell) / `openai` (DALL-E 3) / `huggingface` / `pexels`
- Retry with exponential backoff (15s × attempt, up to 5 attempts)

**Voiceover:**
- `pick_voice(config, "hi")` → random from 3 Indian female voices
- `generate_voiceover_only()` → edge-tts (default) with `+3%` rate, `+0Hz` pitch
- Fallbacks: OpenAI TTS (`nova`), ElevenLabs
- `_sanitize_tts_text()` strips SSML-breaking characters (`&`, `<`, `>`, smart quotes)

**Background music:**
- `generate_bg_music_ai()` → Replicate musicgen (future use when model is available)

### `agents/animation_agent.py`
**Tools:** MoviePy, NumPy, Pillow

Ken Burns effects applied per scene (random selection):

| Effect | Description |
|--------|-------------|
| `zoom_in` | Progressive zoom into center |
| `zoom_out` | Start zoomed, slowly pull out |
| `pan_left` | Horizontal pan right→left |
| `pan_right` | Horizontal pan left→right |
| `pan_up` | Vertical pan bottom→top |
| `combined` | Slow zoom + gentle horizontal drift |

- Images pre-scaled 20–50% larger than target to allow movement headroom
- Uses `VideoClip(make_frame, duration)` pattern (not `ImageClip`) for smooth frames

### `agents/video_agent.py`
**Tool:** MoviePy

- `assemble_animated_video()` → landscape 1280×720, `final_video.mp4`
- `assemble_animated_shorts()` → vertical 1080×1920, `shorts_video.mp4`
- `_add_bg_music(clip, config, lang_dir)` → picks random file from `data/music/`, loops to fill duration
- `_prepare_vertical_clip()` → converts landscape clip to vertical with blurred background
- `_add_subtitles_to_clip()` → text overlay (requires ImageMagick; degrades gracefully if missing)
- Crossfade transitions: 0.6s for video, 0.36s for shorts

### `agents/caption_agent.py`
- Builds SRT files timed to audio durations
- Splits narration into ~10-word subtitle chunks

### `agents/metadata_agent.py`
**Tool:** GPT-4o-mini + Pillow

- `generate_metadata()` → SEO title, Hinglish description, up to 30 tags
- `generate_shorts_metadata()` → adds `#Shorts`, trims title to ≤100 chars
- `generate_youtube_thumbnail()` → 1280×720 landscape thumbnail
- `generate_shorts_thumbnail()` → 1080×1920 vertical thumbnail

### `agents/upload_agent.py`
**Tool:** YouTube Data API v3 (OAuth 2.0)

- Uploads video + thumbnail to YouTube
- `upload_captions()` → attaches `.srt` to video
- Token-bucket rate-limited

### `agents/notification_agent.py`
**Tool:** Gmail SMTP (App Password)

- Sends run summary email after every pipeline completion
- Contains: timestamp, YouTube video links, output directory
- Supports comma-separated `recipient_email`

### `agents/caption_agent.py`, `agents/db.py`, `agents/rate_limiter.py`
Supporting agents — captions, SQLite storage, per-API token-bucket rate limiting.

---

## Background Music

Background music is pre-downloaded once via `python main.py --generate-music` and stored in `data/music/`. Each video run picks one track at random.

| Source | License | Tracks |
|--------|---------|--------|
| FesliyanStudios.com (David Renda) | Free for commercial use | 10 kids instrumental tracks |

Track list: `kids_curious_kiddo`, `kids_joyful_lullaby`, `kids_gentle_lullaby`, `kids_dancing_silly`, `kids_play_date`, `kids_duck_duck_goose`, `kids_dancing_baby`, `kids_clap_and_sing`, `kids_pig_in_the_mud`, `kids_googoo_gaga`

Music is looped to match video duration and mixed at 8% volume (`bg_music_volume: 0.08`).

---

## Voice Configuration

All voices are Indian female, free via edge-tts:

| Voice | Type | Description |
|-------|------|-------------|
| `en-IN-NeerjaNeural` | Indian English | Warm, natural Hinglish storyteller |
| `en-IN-NeerjaExpressiveNeural` | Indian English | Expressive, great for kids |
| `hi-IN-SwaraNeural` | Hindi female | Most natural for Hinglish narration |

Voice is picked randomly per run via `pick_voice(config, "hi")`.

---

## Project Structure

```
Youtube_Automation/
├── main.py                     # Orchestrator — video + shorts pipelines
├── config.yaml                 # API keys + settings (gitignored)
├── config.example.yaml         # Template config (committed)
├── requirements.txt            # Python dependencies
├── ARCHITECTURE.md             # This file
├── README.md                   # Quick-start guide
├── .gitignore
│
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD → AWS EC2 + deploy email
│
├── agents/
│   ├── topic_agent.py          # GPT topic generation
│   ├── script_agent.py         # GPT script writing (Hinglish + shorts variant)
│   ├── asset_agent.py          # TTS voiceover (edge-tts/openai/elevenlabs) + images
│   ├── animation_agent.py      # Ken Burns effects → animated VideoClip per scene
│   ├── video_agent.py          # MoviePy assembly (landscape video + vertical shorts)
│   ├── metadata_agent.py       # GPT metadata + platform-specific thumbnails
│   ├── upload_agent.py         # YouTube upload + caption upload (OAuth 2.0)
│   ├── instagram_agent.py      # Instagram Reels asset prep (optional)
│   ├── caption_agent.py        # SRT/caption generation
│   ├── notification_agent.py   # Email summary (Gmail SMTP)
│   ├── ab_agent.py             # A/B testing for titles/hooks (optional)
│   ├── analytics_agent.py      # YouTube analytics feedback loop (optional)
│   ├── playlist_agent.py       # Playlist auto-creation (optional)
│   ├── rate_limiter.py         # Token-bucket rate limiter per API provider
│   └── db.py                   # SQLite database (videos, metrics)
│
├── data/
│   ├── topics_history.json     # Track used topics (avoid repeats)
│   ├── pipeline.db             # SQLite database (gitignored)
│   └── music/                  # 10 pre-downloaded kids instrumental tracks
│       ├── kids_curious_kiddo.mp3
│       ├── kids_joyful_lullaby.mp3
│       └── ...
│
└── output/                     # Generated files per run (gitignored)
    ├── video_YYYYMMDD_HHMMSS/
    │   ├── images/             # Shared cartoon scene images (6 PNGs)
    │   ├── hi/
    │   │   ├── audio/          # Scene voiceover MP3s (deleted after upload)
    │   │   ├── animated_clips/ # Ken Burns MP4 clips (deleted after upload)
    │   │   ├── final_video.mp4 # 1280×720 landscape video
    │   │   ├── captions_hi.srt
    │   │   ├── thumbnail.png
    │   │   └── metadata.json
    │   ├── script.json
    │   └── run_log.json
    └── shorts_YYYYMMDD_HHMMSS/
        ├── images/
        ├── hi/
        │   ├── audio/
        │   ├── animated_clips/
        │   ├── shorts_video.mp4  # 1080×1920 vertical Short
        │   ├── thumbnail.png
        │   └── metadata.json
        ├── script.json
        └── run_log.json
```

---

## Tech Stack

| Component | Tool | Cost/run |
|-----------|------|----------|
| Text Generation | GPT-4o-mini | ~$0.02 |
| Image Generation | Replicate Flux Schnell | ~$0.02 (6 images) |
| Text-to-Speech | edge-tts (Indian female voices) | Free |
| Ken Burns Animation | MoviePy + NumPy | Free (CPU) |
| Video Assembly | MoviePy | Free (CPU) |
| Background Music | FesliyanStudios.com (pre-downloaded) | Free |
| Thumbnails | Pillow | Free |
| Captions/SRT | Built-in | Free |
| YouTube Upload | YouTube Data API v3 | Free (quota) |
| Email Notification | Gmail SMTP (App Password) | Free |
| Database | SQLite | Free |
| Scheduling | Linux cron (EC2) | Free |
| **Total per run** | | **~$0.04** |

| Infrastructure | Tool | Cost/month |
|----------------|------|------------|
| Compute | AWS EC2 t4g.small Spot | ~$3-4 |
| Storage | 20 GB gp3 EBS | $1.60 |
| Elastic IP | (while running) | $0.00 |
| Data transfer | Video uploads | ~$0.50 |
| **Total infra** | | **~$5-6** |

---

## CLI Reference

```bash
# Run pipelines
python main.py --video               # 2-3 min Hinglish video + upload
python main.py --shorts              # ~1 min Hinglish Short + upload
python main.py --video --no-upload   # Generate video only (no YouTube upload)
python main.py --shorts --no-upload  # Generate Short only (no upload)

# Scheduler (runs --video at 9 AM, --shorts at 9 PM)
python main.py --schedule

# One-time music download (run once after first EC2 setup)
python main.py --generate-music      # Downloads 10 tracks to data/music/

# Help
python main.py --help
```

---

## Configuration Reference

| Section | Key Settings |
|---------|-------------|
| `openai` | `api_key`, `model` (gpt-4o-mini) |
| `image_provider` | `replicate` / `openai` / `huggingface` / `pexels` |
| `replicate` | `api_token`, `model` (flux-schnell) |
| `tts` | `provider` (edge-tts/openai/elevenlabs), `openai_voice` |
| `languages[]` | `code: "hi"`, `name: "Hindi"`, `voices[]` (3 Indian female voices) |
| `youtube` | `client_secrets_file`, `token_file`, `category_id`, `privacy_status`, `made_for_kids` |
| `instagram` | `enabled`, `ig_user_id`, `access_token` |
| `content` | `niche`, `target_age`, `video_duration_minutes`, `scenes_per_video`, `image_style` |
| `schedule` | `upload_days`, `upload_time` |
| `video` | `resolution` ([1280, 720]), `fps`, `bg_music_volume` (0.08), `subtitle_font_size`, `subtitle_color` |
| `animation` | `provider` (kenburns), `image_style`, `kenburns.zoom_ratio`, `kenburns.effects` |
| `bg_music` | `provider` (local), `replicate_model`, `prompt`, `duration` |
| `notifications.email` | `enabled`, `provider` (gmail), `sender_email`, `sender_password`, `recipient_email` |
| `brand_voice` | `enabled`, `tone`, `catchphrases`, `vocabulary_level` |
| `ab_testing` | `enabled`, `variants_count`, `min_data_points` |
| `analytics` | `enabled`, `youtube_analytics`, `fetch_delay_hours` |
| `playlists` | `enabled`, `auto_create`, `min_videos_for_playlist`, `naming_template` |
| `orchestration` | `engine` (simple) |

---

## Database Schema (SQLite — `data/pipeline.db`)

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
| Replicate 429 / rate limit | Retry with 15s × attempt backoff, max 5 attempts |
| edge-tts SSML parse error | `_sanitize_tts_text()` strips `&`, `<`, `>`, smart quotes |
| edge-tts NoAudioReceived | Retry up to 4 times; last attempt drops prosody tags |
| YouTube `uploadLimitExceeded` | Verify channel at youtube.com/verify |
| YouTube invalid_scope | Delete `token.json`, re-run OAuth flow |
| OOM kill on EC2 | 2 GB swap + 1280×720 resolution (not 1080p) |
| MoviePy `Image.ANTIALIAS` missing | Monkey-patched: `Image.ANTIALIAS = Image.LANCZOS` |
| ImageMagick not installed | Subtitle rendering silently skipped |
| Email notification fails | Warning printed, pipeline continues |
| Playlist creation fails | Skipped, video uploads normally |

---

## EC2 Deployment Guide

### One-time Setup

```bash
# 1. SSH into EC2
ssh -i ~/.ssh/youtube-automation.pem -o ServerAliveInterval=60 ubuntu@YOUR_ELASTIC_IP

# 2. Install system dependencies
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg git imagemagick
sudo timedatectl set-timezone Asia/Kolkata
timedatectl   # verify: IST (UTC+0530)

# 3. Add swap (prevent OOM during video encoding)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 4. Clone repo and install Python dependencies
git clone https://github.com/YOUR_USERNAME/Youtube_Automation.git ~/youtube_automation
cd ~/youtube_automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p logs

# 5. Upload secret files (run from your Mac)
scp -i ~/.ssh/youtube-automation.pem config.yaml ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/
scp -i ~/.ssh/youtube-automation.pem client_secrets.json ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/
scp -i ~/.ssh/youtube-automation.pem token.json ubuntu@YOUR_ELASTIC_IP:~/youtube_automation/

# 6. Download background music library
cd ~/youtube_automation && ./venv/bin/python main.py --generate-music

# 7. Test pipeline manually
./venv/bin/python main.py --video --no-upload    # test without upload
./venv/bin/python main.py --shorts --no-upload   # test shorts without upload
./venv/bin/python main.py --video                # full test: generate + upload + email

# 8. Set up cron (video at 9 AM + shorts at 9 PM IST)
crontab -e
# Add these two lines:
0  9 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --video  >> logs/run.log 2>&1
0 21 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --shorts >> logs/run.log 2>&1

# 9. Create deploy key for GitHub Actions
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
| `GMAIL_SENDER` | Gmail address for deploy notifications |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password |

### Verify Everything Works

```bash
# Check cron is set
crontab -l

# Watch live logs
tail -f ~/youtube_automation/logs/run.log

# Check last git pull (CI/CD test)
git log -1 --oneline

# Test email notification
cd ~/youtube_automation && source venv/bin/activate
python3 -c "
import yaml; from agents.notification_agent import send_run_summary
c = yaml.safe_load(open('config.yaml'))
send_run_summary(c, {'timestamp':'test','run_dir':'/tmp','videos':[{'language':'Hindi','video_url':'https://youtu.be/test','shorts_url':None}]})
"

# Check music library
ls -lh data/music/   # should show 10+ .mp3 files
```

---

## Setup Requirements

1. **Python 3.10+** with virtual environment
2. **API Keys:** OpenAI (GPT-4o-mini), Replicate (Flux Schnell image generation)
3. **Google Cloud:** OAuth 2.0 credentials for YouTube Data API v3 (`client_secrets.json` + `token.json`)
4. **Gmail App Password:** 16-char app password (Google Account → Security → 2-Step Verification → App Passwords)
5. **AWS EC2:** t4g.small ARM64 instance with Elastic IP + 2 GB swap
6. **GitHub Secrets:** `EC2_HOST` + `EC2_SSH_KEY` + `GMAIL_SENDER` + `GMAIL_APP_PASSWORD`
7. **ffmpeg:** Required by MoviePy (`sudo apt install ffmpeg`)
8. **ImageMagick:** Optional, for subtitle text rendering (`sudo apt install imagemagick`)
9. **Background music:** Run `python main.py --generate-music` once after setup
10. **YouTube channel verification:** Required for upload quota — verify at youtube.com/verify
