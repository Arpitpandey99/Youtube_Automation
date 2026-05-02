# YouTube Kids Automation Pipeline — Technical Documentation

## Overview

A fully automated Python pipeline that generates, assembles, and uploads educational kids' YouTube videos in **Hinglish** (casual Hindi-English mix). The system runs on an AWS EC2 instance, producing content for the **@kidlearningadventure** (Funzooon) YouTube channel targeting ages 3-8.

**Channel:** https://www.youtube.com/@kidlearningadventure

---

## Table of Contents

1. [Architecture](#architecture)
2. [Content Pipelines](#content-pipelines)
3. [Agent System](#agent-system)
4. [AI Services Used](#ai-services-used)
5. [Voice System (TTS)](#voice-system-tts)
6. [Image Generation](#image-generation)
7. [Animation System](#animation-system)
8. [Video Assembly](#video-assembly)
9. [Character System](#character-system)
10. [Format Variation (Anti-Detection)](#format-variation-anti-detection)
11. [Voice Rotation](#voice-rotation)
12. [YouTube Upload & Metadata](#youtube-upload--metadata)
13. [Thumbnail Generation](#thumbnail-generation)
14. [Database & Tracking](#database--tracking)
15. [Scheduler](#scheduler)
16. [Configuration](#configuration)
17. [Deployment (EC2)](#deployment-ec2)
18. [CLI Reference](#cli-reference)
19. [File Structure](#file-structure)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (Orchestrator)                   │
│  Pipelines: --video | --shorts | --poem | --lullaby | --schedule│
└───────┬─────────┬──────────┬──────────┬──────────┬──────────────┘
        │         │          │          │          │
   ┌────▼────┐ ┌──▼──┐ ┌────▼────┐ ┌───▼───┐ ┌───▼────┐
   │ Topic   │ │Script│ │ Asset   │ │ Video │ │Upload  │
   │ Agent   │ │Agent │ │ Agent   │ │ Agent │ │Agent   │
   └────┬────┘ └──┬──┘ └────┬────┘ └───┬───┘ └───┬────┘
        │         │     ┌───┴───┐      │         │
        │         │     │       │      │         │
      GPT-4o   GPT-4o  TTS   Images  MoviePy  YouTube
      mini     mini    ┌┴──┐  ┌┴──┐            API v3
                       │   │  │   │
                    Google Replicate
                    Neural2 Flux
```

**Flow for each video:**
1. **Topic Agent** → GPT generates a unique topic (avoids past topics)
2. **Script Agent** → GPT writes scene-by-scene Hinglish script
3. **Asset Agent** → TTS voiceover + AI image generation (parallel)
4. **Animation Agent** → Ken Burns pan/zoom effects on images
5. **Video Agent** → MoviePy assembles scenes + subtitles + background music
6. **Metadata Agent** → GPT generates title, description, tags + themed thumbnail
7. **Caption Agent** → Generates SRT subtitle file for YouTube
8. **Upload Agent** → OAuth 2.0 upload to YouTube + thumbnail + captions
9. **Notification Agent** → Email summary with video links
10. **DB Agent** → Records video in SQLite for tracking

---

## Content Pipelines

### 1. Video Pipeline (`--video`)
- **Duration:** 2-3 minutes, landscape (1280x720)
- **Scenes:** 6 (configurable via `content.scenes_per_video`)
- **Steps:** Topic → Script → Images → Voiceover → Animation → Captions → Assembly → Metadata + Thumbnail → Upload
- **Output:** `output/video_YYYYMMDD_HHMMSS/`

### 2. Shorts Pipeline (`--shorts`)
- **Duration:** ~60 seconds max, vertical (1080x1920)
- **Scenes:** 3 (best scenes picked from a full 6-scene script)
- **Steps:** Topic → Full Script → Images → Shorts Re-hook Script (punchier) → Voiceover → Animation → Assembly (vertical with blurred background) → Metadata → Upload
- **Output:** `output/shorts_YYYYMMDD_HHMMSS/`

### 3. Poem Pipeline (`--poem`)
- **Duration:** 2-3 minutes, landscape
- **Format:** Structured rhyming poem (verse + chorus), read-along text overlay at top
- **TTS:** 95% speaking rate for rhythmic delivery
- **Output:** `output/poem_YYYYMMDD_HHMMSS/`

### 4. Lullaby Pipeline (`--lullaby`)
- **Duration:** 2-3 minutes, landscape
- **Format:** Soothing bedtime content with dreamy pastel visuals
- **TTS:** 80% speaking rate, -2 semitone pitch for calm delivery
- **Transitions:** 1.0s gentle crossfades (vs. 0.6s for regular videos)
- **Music:** Dedicated lullaby music from `data/music/lullaby/`
- **Output:** `output/lullaby_YYYYMMDD_HHMMSS/`

---

## Agent System

Each agent is a standalone Python module in `agents/`. They are orchestrated by `main.py`.

| Agent | File | Purpose |
|-------|------|---------|
| Topic Agent | `agents/topic_agent.py` | GPT-generated unique topics, avoids repeats via `data/topics_history.json` |
| Script Agent | `agents/script_agent.py` | Scene-by-scene Hinglish scripts with hook templates (A/B/C format) |
| Poem Agent | `agents/poem_agent.py` | Structured rhyming poem scripts with verse/chorus/lines |
| Lullaby Agent | `agents/lullaby_agent.py` | Soothing bedtime lullaby scripts |
| Asset Agent | `agents/asset_agent.py` | TTS voiceover (5 providers) + image generation (4 providers) |
| Animation Agent | `agents/animation_agent.py` | Ken Burns effects or AI video-to-video animation |
| Video Agent | `agents/video_agent.py` | MoviePy assembly: scenes + subtitles + transitions + background music |
| Metadata Agent | `agents/metadata_agent.py` | GPT-generated title/description/tags + themed thumbnails |
| Caption Agent | `agents/caption_agent.py` | SRT subtitle file generation from script + audio timings |
| Upload Agent | `agents/upload_agent.py` | YouTube OAuth 2.0 upload with resumable uploads |
| DB Agent | `agents/db.py` | SQLite tracking: videos, metrics, A/B variants, playlists, quotas |
| A/B Agent | `agents/ab_agent.py` | A/B testing for titles/hooks/thumbnails (optional) |
| Analytics Agent | `agents/analytics_agent.py` | YouTube Analytics API data fetching + performance hints |
| Playlist Agent | `agents/playlist_agent.py` | Auto-organize videos into category playlists |
| Instagram Agent | `agents/instagram_agent.py` | Instagram Reels upload via Graph API |
| Notification Agent | `agents/notification_agent.py` | Email summary after each run (Gmail SMTP or Resend) |
| Rate Limiter | `agents/rate_limiter.py` | Token bucket rate limiting for all API calls |

---

## AI Services Used

| Service | What It Does | Cost |
|---------|-------------|------|
| **OpenAI GPT-4o-mini** | Topic generation, script writing, metadata, A/B variants | ~$0.01/video |
| **Google Cloud TTS Neural2** | Hinglish voiceover (Indian English accent) | GCP credits ($300 free tier) |
| **Replicate Flux Schnell** | AI image generation (soft watercolor/cartoon style) | ~$0.003/image |
| **YouTube Data API v3** | Video upload, thumbnail, captions | Free (quota-based) |
| **FesliyanStudios** | Background music (pre-downloaded, royalty-free) | Free |

### Optional/Alternative Services
| Service | What It Does | Cost |
|---------|-------------|------|
| ElevenLabs | Voice cloning, multilingual TTS | $5/mo (Starter) |
| Sarvam AI | Hinglish-native Indian TTS | Free ₹1000 trial |
| OpenAI TTS | Human-sounding tts-1-hd | Pay-per-use |
| edge-tts | Free Microsoft TTS (robotic) | Free |
| DALL-E 3 | OpenAI image generation | ~$0.04/image |
| HuggingFace | Free SDXL image generation | Free (rate-limited) |
| Pexels | Stock photo search | Free |
| Replicate MusicGen | AI background music generation | ~$0.05/track |

---

## Voice System (TTS)

Configured via `config.yaml → tts.provider`. Current provider: **Google Cloud TTS**.

### Google Cloud TTS (Recommended)
- **Voices:** Neural2 en-IN series (Indian English accent — perfect for Hinglish)
- **Auth:** Service account JSON key (`tts.google_tts_credentials`)
- **SSML:** Full support for `<prosody>`, `<break>`, `<emphasis>`
- **Voice variants by content type:**
  - Stories/Videos: `en-IN-Neural2-D` (warm female)
  - Lullabies: `en-IN-Neural2-D` at 80% rate, -2 semitone pitch
  - Poems: `en-IN-Neural2-A` at 95% rate (clear rhythmic delivery)

### Voice Rotation (NEW — $0 cost)
Each video randomly picks from a pool of 4 female Neural2 voices:
- `en-IN-Neural2-A` — clear female, good for educational
- `en-IN-Neural2-D` — warm female, good for stories
- `en-IN-Neural2-F` — soft female, gentle delivery
- `en-IN-Neural2-E` — expressive female, engaging tone

**Config:** `voice_rotation.enabled: true`

This prevents YouTube from detecting "same voice every video" pattern.

### ElevenLabs Voice Clone (NEW — disabled by default)
Supports custom cloned voices for a unique channel identity.
- **Config:** `tts.elevenlabs_use_clone: true` + `tts.elevenlabs_voice_clone_id: "YOUR_ID"`
- **Cost:** Requires Starter plan ($5/mo)
- **How to set up:**
  1. Sign up at https://elevenlabs.io
  2. Go to Voice Cloning → upload 1-5 min of your voice
  3. Copy the voice ID → set in config.yaml

### Hinglish Language Rules (Script Agent)
The script agent enforces specific Hinglish rules:
- **60-70% English** with **30-40% Hindi words** sprinkled in naturally
- Greetings/exclamations stay in English: "Hey there!", "Oh my goodness!", "That's SO cool!"
- Hindi words used: "bacchon", "bahut", "chalo", "dekho", "pata hai", "kitna", "duniya"
- Visual descriptions always in English (used for image generation prompts)
- Example: "Can you believe it?! Yeh toh bahut interesting hai!"

---

## Image Generation

Configured via `config.yaml → image_provider`. Current provider: **Replicate (Flux Schnell)**.

### Image Style
```yaml
image_style: "soft watercolor illustration, smooth edges, pastel colors,
              gentle dreamy look, kid-friendly, no sharp lines, no text, no words"
```

For animation mode, uses a softer cartoon style:
```yaml
animation.image_style: "soft cartoon illustration, smooth gentle colors, dreamy pastel tones,
                        kid-friendly, soft edges, Pixar-like warmth, no text, no words"
```

### Per-Scene Prompts
Each scene's `visual_description` (always in English) is combined with the style prefix and character prefix (if enabled) to create the image prompt:
```
{style}, {visual_description}, high quality, no text, no words {character_prefix}
```

---

## Animation System

Configured via `config.yaml → animation.provider`.

### Ken Burns (Default — Free)
Applies pan/zoom effects to static images using MoviePy:
- **Effects:** `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `combined`
- **Zoom ratio:** 0.04 per second (randomized 0.025-0.06 with format variation)
- Images are loaded at 1.35x target resolution for pan room

### AI Animation (Paid — ~$0.20/scene)
Uses Replicate's image-to-video models (Wan 2.5 i2v):
- Generates 5-second animated clips from each static image
- Falls back to Ken Burns if AI generation fails (`ai_with_fallback` mode)

---

## Video Assembly

Handled by `agents/video_agent.py` using MoviePy.

### Landscape Video (1280x720)
1. Each scene: image clip + audio clip + subtitle overlay
2. Crossfade transitions between scenes (0.3-0.8s, randomized)
3. Background music layer (auto-looped, 8% volume)
4. Export: H.264 MP4, AAC audio, 24fps

### Shorts Video (1080x1920 vertical)
1. Landscape images converted to vertical with **blurred background fill**
2. Shorter padding, faster transitions
3. Max 59 seconds total duration
4. Same subtitle + music treatment

### Subtitle System
- Word-wrapped at 50 chars (landscape) or 25 chars (vertical)
- Bottom-positioned with black stroke outline
- Font, color, size, and position all randomized per video (format variation)

---

## Character System

Recurring characters appear in every scene for brand consistency.

### Available Characters
| ID | Name | Description |
|----|------|-------------|
| `teddy_bear_friend` | Teddy | Golden-brown teddy bear with red bow tie, curious personality |
| `bunny_dreamer` | — | Dreamy bunny character |
| `owl_storyteller` | — | Wise owl narrator |

### How It Works
1. `config.yaml → content.character: "teddy_bear_friend"` (or `"random"`)
2. Script Agent loads `data/characters/<id>/reference_sheet.json`
3. Character name is injected into every scene's `visual_description`
4. Character's `image_prompt_prefix` is appended to every image generation prompt
5. Result: Same character appears consistently across all scenes

---

## Format Variation (Anti-Detection)

**NEW — $0 cost. Enabled by default.**

YouTube's AI slop detector flags channels with identical video formatting. Format variation randomizes visual parameters per video so no two look the same.

### What Gets Randomized

| Parameter | Range | Purpose |
|-----------|-------|---------|
| Transition duration | 0.3 – 0.8s | Different scene change pacing |
| Subtitle font size | 42 – 54px | Visual variety |
| Subtitle color | yellow, white, cyan, gold, green, salmon | Different look per video |
| Subtitle font | Arial-Bold, Helvetica-Bold, Impact, Verdana-Bold | Font variety |
| Subtitle stroke width | 2 – 3px | Outline thickness |
| Subtitle Y position | 140 – 200px from bottom | Vertical placement |
| Shorts subtitle size | 48 – 56px | Vertical format variety |
| Ken Burns zoom ratio | 0.025 – 0.06 | Animation speed variety |

### Config
```yaml
format_variation:
  enabled: true   # set to false to use fixed defaults
```

Each pipeline run logs the chosen parameters:
```
Format variation: transition=0.52s, font=Impact, color=#00FFFF, size=50, zoom=0.038
```

---

## Voice Rotation

**NEW — $0 cost. Enabled by default.**

Instead of using one fixed Google TTS voice for every video, each video randomly picks from a pool of 4 female voices.

### Config
```yaml
voice_rotation:
  enabled: true
  google_voice_pool:
    - "en-IN-Neural2-A"   # clear female
    - "en-IN-Neural2-D"   # warm female
    - "en-IN-Neural2-F"   # soft female
    - "en-IN-Neural2-E"   # expressive female
```

Each pipeline run logs the chosen voice:
```
Voice rotation: selected en-IN-Neural2-F
```

---

## YouTube Upload & Metadata

### OAuth 2.0 Authentication
- **Scopes:** `youtube.upload`, `youtube`, `youtube.force-ssl`
- **Files:** `client_secrets.json` (OAuth app) + `token.json` (cached token)
- First run triggers browser-based OAuth flow
- Token auto-refreshes on expiry

### Metadata Generation (GPT)
The metadata agent generates:
- **Title:** SEO-optimized, Hinglish, max 100 chars
- **Description:** Engaging description with hashtags and emojis
- **Tags:** 10 relevant tags, cleaned for YouTube's character restrictions
- **Category:** 24 (Entertainment)
- **Privacy:** Public, `made_for_kids: true` (COPPA compliant)

### Upload Process
1. Resumable upload via `MediaFileUpload` (handles large files)
2. Progress tracking printed during upload
3. Thumbnail uploaded separately after video
4. SRT captions uploaded as auto-generated track
5. Video ID stored in SQLite database

---

## Thumbnail Generation

Themed thumbnails generated per content type using Pillow (PIL):

| Content Type | Theme | Colors |
|-------------|-------|--------|
| Video | Energetic gradient | Orange → Yellow |
| Shorts | Bold vertical | Red → Magenta |
| Poem | Soft artistic | Purple → Lavender |
| Lullaby | Dreamy calm | Navy → Midnight Blue |

### Thumbnail Elements
1. Scene image as background (resized to 1280x720)
2. Gradient overlay (bottom 40% of image)
3. Large title text with drop shadow
4. Corner accent decorations (stars, sparkles, etc.)
5. Colored border (4px, themed)

---

## Database & Tracking

SQLite database at `data/pipeline.db` with WAL mode for concurrent access.

### Tables
| Table | Purpose |
|-------|---------|
| `videos` | Video records: ID, platform, topic, category, title, upload date, run dir |
| `metrics` | Performance metrics: views, likes, CTR, watch time, impressions |
| `ab_variants` | A/B test variants: title/hook/thumbnail alternatives |
| `topic_scores` | Topic performance scores for topic selection optimization |
| `playlists` | Playlist records for auto-organization |
| `quota_usage` | API quota tracking per provider per day |

### Topic History
`data/topics_history.json` — JSON array of all generated topics. The topic agent checks this to avoid repeating topics. Grows over time as more videos are produced.

---

## Scheduler

```python
python main.py --schedule
```

Runs two pipelines daily on configured days:
- **09:00 IST** → Video pipeline (2-3 min landscape)
- **21:00 IST** → Shorts pipeline (~1 min vertical)

With `--animate` flag, shorts use AI animation instead of Ken Burns.

### Config
```yaml
schedule:
  videos_per_week: 14
  upload_days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
  upload_time: "21:00"
```

---

## Configuration

All configuration in `config.yaml` (gitignored — contains API keys).
Template: `config.example.yaml` (committed).

### Key Config Sections

| Section | What It Controls |
|---------|-----------------|
| `openai` | GPT API key and model (gpt-4o-mini) |
| `replicate` | Image generation API token and model |
| `tts` | Voice provider, credentials, voice IDs |
| `youtube` | OAuth files, category, privacy, made_for_kids |
| `instagram` | Instagram Graph API (optional) |
| `content` | Niche, target age, scenes count, image style, character |
| `video` | Resolution, FPS, subtitle style, music volume |
| `animation` | Provider (kenburns/ai), zoom settings |
| `bg_music` | Music provider (local/replicate), prompt |
| `voice_rotation` | Voice pool for per-video rotation |
| `format_variation` | Enable/disable visual randomization |
| `schedule` | Upload frequency, days, time |
| `notifications` | Email alerts after each run |
| `ab_testing` | A/B testing (optional) |
| `analytics` | YouTube Analytics feedback loop (optional) |
| `playlists` | Auto-playlist organization (optional) |

---

## Deployment (EC2)

### Server
- **Instance:** AWS EC2 (Ubuntu)
- **Access:** `ssh ubuntu@54.160.189.94`
- **Path:** `/home/ubuntu/youtube_automation/`

### Deployment Flow
```bash
# Local: push changes
git push origin main

# EC2: pull and update
ssh ubuntu@54.160.189.94
cd /home/ubuntu/youtube_automation
git pull origin main
pip install -r requirements.txt
```

### Running on EC2
```bash
# One-off video
python main.py --video

# One-off shorts
python main.py --shorts

# Scheduler (background with tmux)
tmux new -s yt
python main.py --schedule
# Ctrl+B, D to detach
```

### Required Files on EC2 (not in git)
- `config.yaml` — API keys and settings
- `client_secrets.json` — Google OAuth app credentials
- `token.json` — Cached OAuth token
- GCP service account JSON — for Google TTS

---

## CLI Reference

```
python main.py --video                    # 2-3 min Hinglish video + upload
python main.py --shorts                   # ~1 min Hinglish Short + upload
python main.py --poem                     # Hinglish rhyming poem + upload
python main.py --lullaby                  # Hinglish bedtime lullaby + upload
python main.py --video --no-upload        # Generate video, skip upload
python main.py --shorts --no-upload       # Generate shorts, skip upload
python main.py --video --animate          # Use AI animation instead of Ken Burns
python main.py --shorts --animate         # AI animated Short
python main.py --schedule                 # Scheduler: video 9AM, shorts 9PM daily
python main.py --schedule --animate       # Scheduler with AI animated shorts
python main.py --generate-music           # Download 10 kids background music tracks
python main.py --generate-lullaby-music   # Download lullaby-specific music tracks
python main.py --cleanup-old [--days 7] [--dry-run]   # Clean old output files
```

---

## File Structure

```
Youtube_Automation/
├── main.py                          # Entry point — orchestrates all pipelines
├── config.yaml                      # Active config (gitignored — has API keys)
├── config.example.yaml              # Config template (committed)
├── requirements.txt                 # Python dependencies
├── client_secrets.json              # Google OAuth credentials (gitignored)
├── token.json                       # Cached OAuth token (gitignored)
├── analyze_channel.py               # Standalone channel analytics script
├── DOCUMENTATION.md                 # This file
│
├── agents/                          # All pipeline agents
│   ├── topic_agent.py               # GPT topic generation
│   ├── script_agent.py              # GPT script writing (Hinglish)
│   ├── poem_agent.py                # Poem-specific script generator
│   ├── lullaby_agent.py             # Lullaby-specific script generator
│   ├── asset_agent.py               # TTS voiceover + image generation
│   ├── animation_agent.py           # Ken Burns / AI animation
│   ├── video_agent.py               # MoviePy video assembly + format variation
│   ├── metadata_agent.py            # YouTube metadata + thumbnails
│   ├── caption_agent.py             # SRT subtitle generation
│   ├── upload_agent.py              # YouTube OAuth upload
│   ├── db.py                        # SQLite database CRUD
│   ├── ab_agent.py                  # A/B testing for titles/hooks
│   ├── analytics_agent.py           # YouTube Analytics API
│   ├── playlist_agent.py            # Auto-playlist management
│   ├── instagram_agent.py           # Instagram Reels upload
│   ├── notification_agent.py        # Email notifications
│   └── rate_limiter.py              # Token bucket rate limiter
│
├── data/
│   ├── topics_history.json          # All generated topics (avoids repeats)
│   ├── pipeline.db                  # SQLite database
│   ├── music/                       # Background music tracks (.mp3)
│   │   └── lullaby/                 # Lullaby-specific calm tracks
│   └── characters/                  # Character reference sheets
│       ├── teddy_bear_friend/
│       │   └── reference_sheet.json
│       ├── bunny_dreamer/
│       │   └── reference_sheet.json
│       └── owl_storyteller/
│           └── reference_sheet.json
│
├── output/                          # Generated video outputs (gitignored)
│   ├── video_YYYYMMDD_HHMMSS/       # One directory per run
│   │   ├── script.json              # Generated script
│   │   ├── run_log.json             # Step-by-step execution log
│   │   └── hi/                      # Language-specific outputs
│   │       ├── final_video.mp4
│   │       ├── metadata.json
│   │       └── captions_hi.srt
│   ├── shorts_YYYYMMDD_HHMMSS/
│   ├── poem_YYYYMMDD_HHMMSS/
│   └── lullaby_YYYYMMDD_HHMMSS/
│
└── templates/                       # (Reserved for future use)
```

---

## Pipeline Step-by-Step (Video Example)

Here's exactly what happens when you run `python main.py --video`:

```
[1] Generating topic...
    → GPT-4o-mini generates a unique educational topic
    → Checks topics_history.json to avoid repeats
    → Saves new topic to history

[2] Writing Hinglish script...
    → GPT writes 6 scenes with visual descriptions + Hinglish narration
    → Hook template (A/B/C) ensures topic-specific opener
    → Character injected into every scene if enabled
    → Script saved to output/video_*/script.json

[3] Generating images...
    → Replicate Flux Schnell generates 6 scene images
    → Prompt: "{style} + {visual_description} + {character_prefix}"
    → 16:9 aspect ratio, PNG output
    → Retries up to 5 times on failure

[4] Generating Hinglish voiceover...
    → Voice rotation picks from 4 female Neural2 voices
    → Google TTS generates MP3 for each scene
    → SSML wrapping for natural prosody
    → Intro hook prepended to scene 1, outro appended to last scene

[5] Animating scenes (Ken Burns)...
    → Random effect per scene: zoom_in, pan_left, combined, etc.
    → Zoom ratio randomized (format variation)
    → Images loaded at 1.35x resolution for pan room

[6] Generating captions...
    → SRT file built from script narration + audio durations
    → Words chunked into 10-word subtitle blocks
    → Timed to audio playback

[7] Assembling video...
    → Format variation: randomizes subtitle style, transitions, etc.
    → Each scene: animated clip + audio + subtitle overlay
    → Crossfade transitions between scenes
    → Background music layer (random track, 8% volume, looped)
    → Export: 1280x720, H.264, AAC, 24fps

[8] Generating metadata...
    → GPT generates SEO title, description, tags (Hinglish)
    → Themed thumbnail: gradient overlay, title text, corner accents
    → Metadata saved to metadata.json

[9] Uploading to YouTube...
    → OAuth 2.0 authentication (cached token)
    → Resumable upload with progress tracking
    → Thumbnail uploaded separately
    → SRT captions uploaded
    → Video ID stored in SQLite database

[10] Cleanup + notification
    → Intermediate files deleted (audio, images, animated clips)
    → Email sent with video URL
    → Run summary logged
```

---

## Cost Per Video

| Component | Cost |
|-----------|------|
| GPT-4o-mini (topic + script + metadata) | ~$0.01 |
| Google TTS Neural2 (6 scenes) | ~$0.02 (GCP credits) |
| Replicate Flux Schnell (6 images) | ~$0.02 |
| YouTube API upload | Free |
| Background music | Free (pre-downloaded) |
| **Total per video** | **~$0.05** |
| **Total per month (5/week)** | **~$1.00** |

---

## Recent Changes (March 2026)

1. **Format Variation** — Randomizes subtitle styles, transition durations, and Ken Burns zoom per video to avoid YouTube's AI slop detection ($0 cost)
2. **Voice Rotation** — Rotates between 4 female Google Neural2 voices per video ($0 cost)
3. **ElevenLabs Voice Clone** — Support for custom cloned voices (disabled by default, $5/mo)
4. **Channel Analytics** — `analyze_channel.py` fetches full YouTube Analytics + Data API metrics and generates a comprehensive report
