# YouTube Kids Video Automation - Architecture

## System Overview

Fully automated pipeline that generates and uploads kid-friendly YouTube videos and Instagram Reels in multiple languages using AI.

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCHEDULER                                │
│              (cron / Python schedule library)                    │
│           Triggers pipeline on Mon / Wed / Fri                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR (main.py)                        │
│                                                                 │
│  ┌───────────┐   ┌──────────┐   ┌──────────────────────────┐   │
│  │  Step 1   │──▶│  Step 2  │──▶│        Step 3            │   │
│  │  Topic    │   │  Script  │   │   Image Generation       │   │
│  │  (shared) │   │   (EN)   │   │       (shared)           │   │
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
│  │                                        │                │   │
│  │  ┌──────────┐  ┌───────────┐  ┌───────▼────────────┐    │   │
│  │  │ Metadata │  │ Thumbnail │  │     UPLOAD         │    │   │
│  │  │ + SEO    │─▶│ (Pillow)  │─▶│ YT + Shorts + IG  │    │   │
│  │  └──────────┘  └───────────┘  └────────────────────┘    │   │
│  │                                        │                │   │
│  │                                   ┌────▼─────┐          │   │
│  │                                   │ Cleanup  │          │   │
│  │                                   └──────────┘          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Steps

### Step 1: Topic Generation
**Agent:** `agents/topic_agent.py`
**Tool:** GPT-4o-mini

```
topics_history.json ──▶ GPT-4o-mini ──▶ topic_data
                        (avoids repeats)
```

- Reads last 50 topics from `data/topics_history.json` to prevent duplicates
- Generates a unique kid-friendly topic with category and target age
- Appends new topic to history file
- **Output:** `{ topic, category, target_age, description }`

### Step 2: Script Writing
**Agent:** `agents/script_agent.py`
**Tool:** GPT-4o-mini

```
topic_data + language ──▶ GPT-4o-mini ──▶ script_data (JSON)
```

- Generates scene-by-scene script for specified language
- For non-English: narration in target language, `visual_description` stays in English (for image generation)
- Each scene has: `visual_description` (EN) + `narration` (target language)
- **Output:** `{ title, intro_hook, scenes[], outro }`

### Step 3: Image Generation (Shared)
**Agent:** `agents/asset_agent.py`
**Tool:** Replicate (Flux Schnell) / DALL-E 3 / HuggingFace / Pexels

```
visual_descriptions (EN) ──▶ Image API ──▶ scene_1.png ... scene_N.png
```

- Uses English visual descriptions from Step 2
- Images are generated once and shared across all languages
- Provider is configurable: `replicate`, `openai`, `huggingface`, `pexels`
- Retry with exponential backoff (15s, 30s, 45s, 60s) for rate limits
- 12-second delay between requests (Replicate rate limit: 6 req/min)
- **Output:** `[ scene_1.png, scene_2.png, ... ]`

### Step 4: Voice Selection + Voiceover (Per Language)
**Agent:** `agents/asset_agent.py`
**Tool:** edge-tts (Microsoft Edge TTS - free)

```
script narration + random voice ──▶ edge-tts ──▶ scene_1.mp3 ... scene_N.mp3
```

- Randomly picks a voice from the configured pool for each language
- English voices: AnaNeural, AriaNeural, JennyNeural, MichelleNeural, GuyNeural, SoniaNeural
- Hindi voices: SwaraNeural, MadhurNeural
- Sanitizes smart quotes, em dashes, ellipsis that break edge-tts
- Combines intro_hook with scene 1, outro with last scene
- **Output:** `[ scene_1.mp3, scene_2.mp3, ... ]`

### Step 5: Video Assembly (Per Language)
**Agent:** `agents/video_agent.py`
**Tool:** MoviePy 2.x

#### Full Video (Landscape 1920x1080)
```
images + audio + subtitles ──▶ MoviePy ──▶ final_video.mp4
```

- Each scene: image (resized to 1080p) + audio clip + subtitle overlay
- Subtitles: word-wrapped, yellow text, black stroke (requires ImageMagick)
- Background music from `data/music/` (if available), looped and mixed at 8% volume
- Concatenated with H.264 codec, AAC audio, 24fps
- **Output:** `final_video.mp4` (~3 min)

#### YouTube Shorts (Vertical 1080x1920)
```
images + audio ──▶ MoviePy ──▶ shorts_video.mp4 (≤59s)
```

- Takes scenes sequentially until 59-second limit is reached
- Images: scaled to fill 1080px width, center-cropped vertically to 1920px
- Larger subtitles (52px) and shorter line wrapping for mobile
- Same background music mixing
- **Output:** `shorts_video.mp4` (~50-59s, 3-4 scenes)

### Step 6: Metadata & Thumbnail (Per Language)
**Agent:** `agents/metadata_agent.py`
**Tools:** GPT-4o-mini + Pillow

```
topic + script ──▶ GPT-4o-mini ──▶ { title, description, tags, thumbnail_text }
                                         │
first scene image + thumbnail_text ──▶ Pillow ──▶ thumbnail.png
```

- GPT generates SEO-optimized title (70 chars + emoji), description with hashtags, 30 tags
- For Hindi: title/description in Hindi, mixed Hindi+English tags
- Shorts metadata: appends `#Shorts` to title, `#Shorts #YouTubeShorts` to description
- Thumbnail: first scene image → 1280x720 → bold text overlay → red background box → yellow/red border
- **Output:** `metadata.json` + `thumbnail.png`

### Step 7: YouTube Upload (Per Language)
**Agent:** `agents/upload_agent.py`
**Tool:** YouTube Data API v3

```
video.mp4 + metadata + thumbnail ──▶ YouTube API ──▶ video URL
```

- OAuth 2.0 authentication (token refresh handled automatically)
- Resumable upload with progress reporting
- Tags sanitized: special chars removed, max 10 tags, Unicode allowed
- Title/description: Unicode preserved (Hindi supported), only `<>` stripped
- `selfDeclaredMadeForKids: true` for COPPA compliance
- Custom thumbnail upload (requires channel verification)
- Graceful error handling: upload failures don't crash the pipeline
- **Output:** `https://www.youtube.com/watch?v=...`

### Step 8: Instagram Reels Upload (Per Language)
**Agent:** `agents/instagram_agent.py`
**Tool:** instagrapi

```
shorts_video.mp4 + caption ──▶ Instagram API ──▶ reel URL
```

- Reuses the same vertical shorts video (already 1080x1920, ≤60s)
- Caption built from: title + description + hashtags from tags (max 2200 chars)
- Session-based login: saves session to `instagram_session.json` to avoid repeated logins
- Configurable: `instagram.enabled: true/false`
- **Output:** `https://www.instagram.com/reel/...`

### Step 9: Cleanup
```
After all uploads complete:
  ├── DELETE: audio/, images/, final_video.mp4, shorts_video.mp4, thumbnail.png
  └── KEEP:  run_log.json, script_en.json, script_hi.json, metadata.json
```

---

## Output Per Pipeline Run

Each run produces **6 uploads** (2 languages x 3 platforms):

| # | Type | Language | Platform | Format |
|---|------|----------|----------|--------|
| 1 | Full Video | English | YouTube | 1920x1080, ~3 min |
| 2 | Shorts | English | YouTube | 1080x1920, ≤60s |
| 3 | Reel | English | Instagram | 1080x1920, ≤60s |
| 4 | Full Video | Hindi | YouTube | 1920x1080, ~3 min |
| 5 | Shorts | Hindi | YouTube | 1080x1920, ≤60s |
| 6 | Reel | Hindi | Instagram | 1080x1920, ≤60s |

---

## Project Structure

```
Youtube_Automation/
├── main.py                     # Orchestrator - runs full pipeline
├── config.yaml                 # API keys + settings (gitignored)
├── config.example.yaml         # Template config (committed)
├── requirements.txt            # Python dependencies
├── test_upload.py              # Test upload script (private video)
├── .gitignore
│
├── agents/
│   ├── __init__.py
│   ├── topic_agent.py          # GPT topic generation
│   ├── script_agent.py         # GPT script writing (multilingual)
│   ├── asset_agent.py          # TTS voiceover + image generation
│   ├── video_agent.py          # MoviePy video assembly (full + shorts)
│   ├── metadata_agent.py       # GPT metadata + Pillow thumbnails
│   ├── upload_agent.py         # YouTube Data API upload
│   └── instagram_agent.py      # Instagram Reels upload
│
├── data/
│   ├── topics_history.json     # Track used topics (avoid repeats)
│   └── music/                  # Royalty-free background tracks (optional)
│
├── output/                     # Generated files per run (gitignored)
│   └── YYYYMMDD_HHMMSS/
│       ├── images/             # Shared scene images
│       ├── en/                 # English outputs
│       │   ├── audio/
│       │   ├── final_video.mp4
│       │   ├── shorts_video.mp4
│       │   ├── thumbnail.png
│       │   └── metadata.json
│       ├── hi/                 # Hindi outputs
│       │   └── (same structure)
│       ├── script_en.json
│       ├── script_hi.json
│       └── run_log.json        # Step-by-step execution log
│
├── client_secrets.json         # Google OAuth credentials (gitignored)
├── token.json                  # Google OAuth token (gitignored)
└── instagram_session.json      # Instagram session (gitignored)
```

---

## Tech Stack

| Component | Tool | Cost |
|-----------|------|------|
| Text Generation (topic, script, metadata) | GPT-4o-mini | ~$0.01/video |
| Image Generation | Replicate Flux Schnell | ~$0.02/video (6 images) |
| Text-to-Speech | edge-tts (Microsoft) | Free |
| Video Assembly | MoviePy 2.x | Free (local) |
| Thumbnails | Pillow | Free (local) |
| YouTube Upload | YouTube Data API v3 | Free (10K units/day) |
| Instagram Upload | instagrapi | Free |
| Scheduling | Python schedule | Free |
| **Total per run (2 languages)** | | **~$0.04** |

---

## Configuration

All settings in `config.yaml`:

| Section | Key Settings |
|---------|-------------|
| `openai` | API key, model (gpt-4o-mini) |
| `image_provider` | replicate / openai / huggingface / pexels |
| `replicate` | API token, model (flux-schnell) |
| `tts` | Provider (edge-tts / openai) |
| `languages[]` | Code, name, voice pool per language |
| `youtube` | OAuth files, category, privacy, made_for_kids |
| `instagram` | Enabled flag, username, password, session file |
| `content` | Niche, target age, duration, scenes, image style |
| `schedule` | Upload days, time |
| `video` | Resolution, FPS, music volume, subtitle style |

---

## Data Flow Diagram

```
                    ┌──────────────┐
                    │  GPT-4o-mini │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌─────────┐  ┌──────────┐
         │ Topic  │  │ Script  │  │ Metadata │
         │  JSON  │  │  JSON   │  │   JSON   │
         └───┬────┘  └────┬────┘  └────┬─────┘
             │            │            │
             │     ┌──────┴──────┐     │
             │     ▼             ▼     │
             │ ┌────────┐  ┌────────┐  │
             │ │ visual │  │narrate │  │
             │ │ desc   │  │  text  │  │
             │ │  (EN)  │  │ (lang) │  │
             │ └───┬────┘  └───┬────┘  │
             │     │           │       │
             │     ▼           ▼       │
             │ ┌────────┐  ┌────────┐  │
             │ │Replicate│  │edge-tts│  │
             │ │ Images │  │ Audio  │  │
             │ └───┬────┘  └───┬────┘  │
             │     │           │       │
             │     └─────┬─────┘       │
             │           ▼             │
             │     ┌───────────┐       │
             │     │  MoviePy  │       │
             │     │  Video    │       │
             │     │ Assembly  │       │
             │     └─────┬─────┘       │
             │           │             │
             │     ┌─────┴─────┐       │
             │     ▼           ▼       │
             │ ┌───────┐ ┌─────────┐   │
             │ │ Full  │ │ Shorts  │   │
             │ │1080p  │ │ 9:16    │   │
             │ └───┬───┘ └────┬────┘   │
             │     │          │        │
             │     ▼          ▼        ▼
             │ ┌───────────────────────────┐
             │ │         UPLOAD            │
             │ │  ┌─────────┐ ┌─────────┐ │
             │ │  │ YouTube │ │Instagram│ │
             │ │  │ API v3  │ │  Reels  │ │
             │ │  └─────────┘ └─────────┘ │
             │ └───────────────────────────┘
             │
             ▼
        ┌──────────┐
        │ Cleanup  │
        │ & Log    │
        └──────────┘
```

---

## Error Handling

| Error | Handling |
|-------|----------|
| API rate limits (Replicate 429) | Retry with 15s * attempt backoff, max 5 attempts |
| edge-tts Unicode errors | `_sanitize_tts_text()` replaces smart quotes/dashes |
| YouTube invalid tags | Sanitize: remove special chars, max 10 tags, 30 char limit |
| YouTube upload limit | Graceful catch, log error, continue pipeline |
| Instagram login challenge | instagrapi handles 2FA/challenge resolution |
| ImageMagick not installed | Subtitle rendering falls back to no-subtitle mode |
| Network timeouts | Catch all exceptions in retry loops |

---

## CLI Usage

```bash
python main.py                # Full run: generate + upload all
python main.py --no-upload    # Generate only (test mode, no uploads)
python main.py --schedule     # Start automated scheduler (Mon/Wed/Fri)
python main.py --help         # Show usage
```

---

## Setup Requirements

1. **Python 3.10+** with virtual environment
2. **API Keys:** OpenAI, Replicate (or alternative image provider)
3. **Google Cloud:** OAuth 2.0 credentials for YouTube Data API v3
4. **Instagram:** Account credentials (optional, for Reels)
5. **ImageMagick:** Optional, for subtitle rendering on videos
6. **ffmpeg:** Required by MoviePy for video encoding
