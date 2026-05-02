# YouTube Kids Automation - Feature Documentation & Production Audit

> Last updated: 2026-05-02 | 206 videos uploaded | Channel: Funzooon (@kidlearningadventure)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Pipeline Types](#2-pipeline-types)
3. [Agent Inventory (17 modules)](#3-agent-inventory)
4. [v2 Growth Intelligence Services (7 services)](#4-v2-growth-intelligence-services)
5. [Provider Matrix](#5-provider-matrix)
6. [CLI Commands](#6-cli-commands)
7. [Database Schema (15 tables)](#7-database-schema)
8. [EC2 Production Status](#8-ec2-production-status)
9. [Channel Performance Snapshot](#9-channel-performance-snapshot)
10. [Current Problems & Red Flags](#10-current-problems--red-flags)

---

## 1. Project Overview

Automated YouTube Kids channel pipeline generating Hinglish (Hindi-English code-switched) educational content for ages 3-8.

| Property | Value |
|----------|-------|
| Channel | Funzooon (@kidlearningadventure) |
| Subscribers | ~14 (as of March 2026) |
| Total uploads | 206 |
| Content language | Hinglish (60-70% English + 30-40% Hindi) |
| Target audience | Kids aged 3-8 |
| Niche | Fun educational facts |
| Made for Kids | Yes (COPPA compliant) |
| Pipeline start | February 10, 2026 |

**Architecture**: Each pipeline follows 8-9 numbered steps:
Topic -> Script -> Images -> TTS Voiceover -> Animation -> Assembly -> Metadata + Thumbnail -> Upload -> DB Record

---

## 2. Pipeline Types

### 2.1 Video Pipeline (`--video`)
| Property | Value |
|----------|-------|
| Duration | 2-3 minutes |
| Orientation | Landscape (1280x720) |
| Scenes | 6 |
| Status in production | **FAILING SILENTLY** (no video output in recent weeks) |

### 2.2 Shorts Pipeline (`--shorts`)
| Property | Value |
|----------|-------|
| Duration | ~1 minute |
| Orientation | Vertical (1080x1920) |
| Scenes | 5 (retention-optimized) |
| Status in production | **ACTIVE** - 5 uploads/day |

Note: Shorts pipeline first generates a full 6-scene script for image generation, then condenses to 5 scenes for the actual short.

### 2.3 Poem Pipeline (`--poem`)
| Property | Value |
|----------|-------|
| Duration | ~2 minutes |
| Scenes | 6 (AABB/ABAB/ABCB rhyme schemes) |
| Special | Read-along text overlay, rhythmic delivery (95% speed) |
| Status in production | **NOT RUNNING** |

### 2.4 Lullaby Pipeline (`--lullaby`)
| Property | Value |
|----------|-------|
| Duration | ~2 minutes |
| Scenes | 4 (verse-chorus-verse-chorus) |
| Special | Slow TTS (-10% rate), pastel visuals, dedicated lullaby music |
| Status in production | **NOT RUNNING** |

---

## 3. Agent Inventory

### Content Generation

| Agent | File | What it does |
|-------|------|-------------|
| `topic_agent` | `agents/topic_agent.py` | Picks topics using series/cluster/trend/random weighted fallback. Deduplicates via `topics_history.json`. Supports category weighting from analytics |
| `script_agent` | `agents/script_agent.py` | Generates scene-by-scene Hinglish scripts via GPT-4o-mini. Each scene has `narration` (Hinglish) + `visual_description` (English, for image prompts). Also generates condensed shorts scripts. Supports character consistency and brand voice |
| `poem_agent` | `agents/poem_agent.py` | Generates rhyming verse scripts with `lines[]` array per scene for read-along text overlay |
| `lullaby_agent` | `agents/lullaby_agent.py` | Generates soothing bedtime scripts with Hindi words (sona, chanda, tara, neend, pyar) |

### Asset Generation

| Agent | File | What it does |
|-------|------|-------------|
| `asset_agent` | `agents/asset_agent.py` | Image generation (4 providers) + TTS voiceover (5 providers). Handles voice rotation, background music selection, audio rate/pitch adjustments per pipeline type |
| `animation_agent` | `agents/animation_agent.py` | Ken Burns pan/zoom effects (free) or AI video generation (Veo 2 / Kling 3.0 / Replicate). AI clips (5s) are extended to audio length via speed reduction + Ken Burns hybrid |
| `caption_agent` | `agents/caption_agent.py` | SRT subtitle generation timed to each scene's audio duration |

### Assembly & Output

| Agent | File | What it does |
|-------|------|-------------|
| `video_agent` | `agents/video_agent.py` | MoviePy assembly: animated clips + audio + subtitles + background music. Four assembly modes: `assemble_animated_video` (landscape), `assemble_animated_shorts` (vertical), `assemble_poem_video` (read-along overlay), `assemble_lullaby_video` (gentle 1.0s crossfades) |
| `metadata_agent` | `agents/metadata_agent.py` | GPT-4o-mini generates YouTube title/description/tags. Pillow generates thumbnails with text overlay, gradients, and borders. Supports landscape (1280x720), square (1200x1200), and Instagram metadata |
| `upload_agent` | `agents/upload_agent.py` | YouTube Data API v3 upload with OAuth 2.0. Handles video upload, thumbnail upload, privacy settings, made-for-kids flag, scheduled publishing |
| `instagram_agent` | `agents/instagram_agent.py` | Instagram Graph API Reels upload. Hosts video temporarily via tmpfiles.org |
| `playlist_agent` | `agents/playlist_agent.py` | Auto-creates YouTube playlists by category + language. Database-backed tracking |

### Analytics & Optimization

| Agent | File | What it does |
|-------|------|-------------|
| `analytics_agent` | `agents/analytics_agent.py` | Fetches YouTube stats (views, likes, CTR, avg watch time). Updates topic performance scores |
| `ab_agent` | `agents/ab_agent.py` | Generates 3+ title/hook/thumbnail_text variants per video. Tracks CTR per variant, detects winners |

### Infrastructure

| Agent | File | What it does |
|-------|------|-------------|
| `notification_agent` | `agents/notification_agent.py` | Email summaries after each pipeline run via Gmail SMTP or Resend API. Shows pipeline type, OK/FAILED status, error messages, video URLs |
| `rate_limiter` | `agents/rate_limiter.py` | Token-bucket rate limiting for 11 providers (Replicate, OpenAI, YouTube, Instagram, etc.) |
| `db` | `agents/db.py` | SQLite with WAL mode. 15 tables covering videos, metrics, A/B variants, topic scores, playlists, trends, clusters, series, thumbnails, upload time slots |

---

## 4. v2 Growth Intelligence Services

Higher-level strategic modules. **All built, all DISABLED in production.**

### 4.1 Trend Service (`services/trend_service.py`)
Discovers trending kids topics from 3 sources:
- YouTube Trending (last 7 days, education category, view-ranked)
- YouTube Autocomplete (free public endpoint, no API key needed)
- Competitor channel analysis (finds videos with 2x+ views vs channel average)

Scoring: 40% trending + 30% autocomplete + 30% competitor signals. GPT auto-categorizes into 12 categories. Auto-refreshes daily at 03:00 IST when enabled.

### 4.2 Cluster Service (`services/cluster_service.py`)
Groups unused trend topics + historical topics into thematic clusters via GPT. Builds topical authority (YouTube algorithm rewards depth in a topic). 3-15 clusters per refresh, refreshed every 7 days.

### 4.3 Series Service (`services/series_service.py`)
Transforms clusters into episodic series (10-15 episodes each). GPT generates series name, episode titles, character assignment, and continuity notes linking episodes. Max 3 active concurrent series. Prioritizes continuing existing series before starting new ones.

### 4.4 Analytics Service (`services/analytics_service.py`)
Bulk analytics sweep using YouTube Analytics API v2 (impressions, CTR, avg view duration, avg view percentage). Computes category performance weights to bias topic selection toward high-performing categories. Requires min 5 videos per category.

### 4.5 Thumbnail A/B Service (`services/thumbnail_ab_service.py`)
Generates 3 thumbnail variants per video (different text positions, font scales). Auto-replaces underperformers after 72h if CTR < 80% of channel average. Min 100 impressions threshold.

### 4.6 Schedule Optimizer Service (`services/schedule_optimizer_service.py`)
Correlates upload hour/day with 48h views + CTR. Returns optimal upload time with confidence score. Requires 20+ data points. Auto-adjusts scheduler when confidence > 0.5.

### 4.7 Retention Service (`services/retention_service.py`)
Generates retention structure prompts per content type (hook timing, curiosity building, mini-hooks every 10s, cliffhanger/CTA). Integrated into script generation.

### Topic Selection Flow (when all enabled)

```
Topic Request
  |
  +-- 60% chance --> Series episode (if active series exist)
  |                    \-- Picks next unproduced episode from active series
  |
  +-- 40% chance --> Standalone topic
                       |
                       +-- 40% --> Trending topic (from trend_topics table)
                       +-- 30% --> Cluster topic (unused topic from active cluster)
                       +-- 30% --> Random (GPT generates based on niche + category weights)
```

**Current state (all disabled)**: 100% random GPT topics with no performance feedback.

---

## 5. Provider Matrix

### Image Generation
| Provider | Model | Cost | Config value | Production |
|----------|-------|------|-------------|-----------|
| **Replicate** | Flux Schnell | ~$0.015/img | `replicate` | **ACTIVE** |
| OpenAI | DALL-E 3 | ~$0.08/img | `openai` | available |
| Hugging Face | SDXL | Free | `huggingface` | available |
| Pexels | Stock API | Free | `pexels` | available |

### Text-to-Speech
| Provider | Cost | Hinglish | Config value | Production |
|----------|------|----------|-------------|-----------|
| Google Cloud TTS | GCP credits | Native en-IN accent | `google` | available |
| ElevenLabs | $11-99/mo | Voice cloning | `elevenlabs` | available |
| **Sarvam AI** | ~Rs178/mo | Best (Indian-built, Bulbul v3) | `sarvam` | **ACTIVE** |
| OpenAI TTS | ~$15/1M chars | No Indian accent | `openai` | available |
| Edge-TTS | Free | Poor Hindi | `edge-tts` | available |

### Animation
| Provider | Cost | Config value | Production |
|----------|------|-------------|-----------|
| **Ken Burns** | Free | `kenburns` | **ACTIVE** (scheduler) |
| Ken Burns + AI fallback | Variable | `ai_with_fallback` | **ACTIVE** (cron shorts) |
| Google Veo 2 | ~$2.50/clip | `ai` (veo) | configured |
| Kling 3.0 | ~$0.145/clip | `ai` (kling) | not configured |
| Replicate | Variable | `ai` (replicate) | configured |

### Upload Targets
| Platform | Method | Production |
|----------|--------|-----------|
| **YouTube** | Data API v3 + OAuth 2.0 | **ACTIVE** |
| Instagram | Graph API + Reels | **DISABLED** |

### Rate Limits (all active)
| Provider | Limit |
|----------|-------|
| Replicate (images) | 5/min |
| Replicate (video) | 3/min |
| OpenAI | 20/min |
| Google TTS | 10/min |
| YouTube | 5/min |
| Instagram | 2/min |
| ElevenLabs | 3/min |
| Hugging Face | 5/min |
| Pexels | 10/min |
| fal.ai (Kling) | 5/min |
| Vertex AI (Veo) | 3/min |

---

## 6. CLI Commands

### Content Pipelines
```bash
python main.py --video                    # 2-3 min landscape video
python main.py --shorts                   # ~1 min vertical Short
python main.py --poem                     # Rhyming poem video
python main.py --lullaby                  # Bedtime lullaby video
python main.py --video --no-upload        # Local test (skip upload)
python main.py --shorts --animate         # AI animation instead of Ken Burns
```

### Scheduling
```bash
python main.py --schedule                 # video 9AM + shorts 9PM daily
python main.py --schedule --animate       # with AI-animated shorts
```

### v2 Growth Intelligence
```bash
python main.py --analytics-sweep          # Fetch YouTube analytics for uploaded videos
python main.py --recompute-weights        # Recompute category performance weights
python main.py --refresh-trends           # Discover trending kids topics
python main.py --generate-clusters        # Group topics into thematic clusters
python main.py --generate-series          # Create episodic series from clusters
python main.py --list-series              # Show active series with progress
python main.py --optimize-thumbnails      # Auto-replace underperforming thumbnails
```

### Maintenance
```bash
python main.py --generate-music           # Download 10 background music tracks
python main.py --generate-lullaby-music   # Download lullaby music tracks
python main.py --cleanup-old --days 7 --dry-run   # Preview what would be deleted
python main.py --cleanup-old --days 7              # Actually delete old files
```

---

## 7. Database Schema

**Location**: `data/pipeline.db` (SQLite, WAL mode) | **15 tables**

### Core Tables
| Table | Purpose | Key columns |
|-------|---------|-------------|
| `videos` | All uploaded videos (206 rows) | video_id, platform, language, topic, category, title, upload_date, run_dir |
| `metrics` | YouTube stats per video | video_id, views, likes, ctr, avg_watch_time, impressions, fetched_at |
| `ab_variants` | Title/hook/thumbnail A/B variants | video_db_id, variant_type, variant_data, is_winner, ctr |
| `topic_scores` | Topic performance scores | topic, category, avg_views, avg_ctr, times_used, last_score |
| `playlists` | Auto-created playlists | playlist_id, platform, language, category, title, video_count |
| `quota_usage` | API quota tracking | provider, date, units_used |

### v2 Intelligence Tables
| Table | Purpose | Key columns |
|-------|---------|-------------|
| `category_weights` | Performance weights per category | category, weight, total_videos, avg_ctr, avg_views |
| `trend_topics` | Discovered trending topics | topic, category, trend_score, source, used |
| `competitor_channels` | Competitor tracking | channel_id, channel_name, avg_views |
| `topic_clusters` | Thematic topic groups | cluster_name, theme, topics_json, priority_score, topics_used/total |
| `series` | Episodic content series | series_name, character_id, target_episodes, produced_episodes, status |
| `series_episodes` | Individual episodes | series_id, episode_number, topic, title, continuity_notes, status |
| `thumbnail_variants` | Thumbnail A/B variants | video_db_id, variant_index, file_path, is_active, ctr_at_activation |
| `upload_time_slots` | Upload timing data | video_db_id, upload_hour, day_of_week, views_48h, ctr_48h |

---

## 8. EC2 Production Status

### Infrastructure

| Property | Value |
|----------|-------|
| Instance ID | `i-0ea80d31c682f822b` |
| Type | `t4g.small` (2 vCPU ARM64, 2 GB RAM) |
| Region | `us-east-1` |
| IP | `54.160.189.94` |
| Disk | 6.8 GB total, **96% used (317 MB free)** |
| Memory | 1.8 GB total, 502 MB used, 2 GB swap |
| Peak memory | 1.4 GB + 354 MB swap |
| Uptime | Running since Apr 24 (8+ days) |

### What's Actually Running

#### 1. Systemd Service: `youtube-bot.service`
```
ExecStart: python main.py --schedule
Status: active (running) since Apr 24
```
Runs the built-in scheduler:
- `run_video_pipeline` at **09:00 IST** daily -- **FAILING SILENTLY**
- `run_shorts_pipeline` at **21:00 IST** daily -- working (Ken Burns animation)

#### 2. Crontab (3 active shorts jobs + 1 cleanup)

| Time (IST) | Command | Status |
|-------------|---------|--------|
| 18:00 daily | `--shorts --animate` | **ACTIVE** (AI animation) |
| 18:30 daily | `--shorts --animate` | **ACTIVE** (AI animation) |
| 19:30 daily | `--shorts --animate` | **ACTIVE** (AI animation) |
| 02:00 Sunday | `--cleanup-old --days 7` | **ACTIVE** |

#### 3. Net Daily Output

| Time | Source | Type | Animation |
|------|--------|------|-----------|
| 09:00 | systemd | video | Ken Burns -- **FAILING** |
| 18:00 | cron | shorts | AI with fallback |
| 18:30 | cron | shorts | AI with fallback |
| 19:30 | cron | shorts | AI with fallback |
| 21:00 | systemd | shorts | Ken Burns |

**Result: 5 shorts/day uploaded, 0 videos/day. Only shorts content being produced.**

### Production Config

| Setting | Value |
|---------|-------|
| TTS provider | Sarvam AI (Bulbul v3, speaker: priya, pace: 0.8) |
| Image provider | Replicate (Flux Schnell) |
| Animation | Ken Burns (scheduler) / AI with Veo fallback (cron) |
| Character | teddy_bear_friend (fixed, no rotation) |
| Voice rotation | Enabled (4 Google voices in pool, but TTS is Sarvam) |
| Format variation | Enabled |
| YouTube category | 24 (Entertainment) |
| Privacy | Public |
| Made for kids | True |
| **Trends** | **DISABLED** |
| **Clusters** | **DISABLED** |
| **Series** | **DISABLED** |
| **Analytics** | **DISABLED** |
| **Thumbnail A/B** | **DISABLED** |
| **A/B testing** | **DISABLED** |
| **Playlists** | **DISABLED** |
| **Instagram** | **DISABLED** |
| **Schedule optimizer** | **DISABLED** |
| Email notifications | Gmail (enabled) |

### Upload Stats (from DB)

| Metric | Value |
|--------|-------|
| Total videos in DB | 206 |
| Daily upload rate | 5/day (last 30 days) |
| Top category | animals (68 = 33%) |
| Second | science (59 = 29%) |
| Third | nature (57 = 28%) |
| Others | history (8), space (4), music (3), misc (7) = 10% |

---

## 9. Channel Performance Snapshot

> From channel analysis report dated March 9, 2026 (at 117 videos). Now at 206 videos.

| Metric | Value (at 117 videos) |
|--------|-------|
| Channel Health Score | **9/100** |
| AI Slop Risk Score | **85/100** |
| Subscribers | 14 |
| Total views | 1,007 |
| Average views/video | 9 |
| Median views/video | 1 |
| Avg watch duration | 36 seconds |
| Avg retention | 59.5% |
| Primary traffic source | YouTube Search (67.9%) |
| Primary device | Mobile (81.4%) |
| Geography | 100% India |
| Growth trend | **DECLINING** (-84.2% second half vs first half) |
| Shorts vs Regular | Shorts get 3.1x more views |
| Best performing | science category (21 avg views) |
| Top video | "Dazzling Dinosaurs" -- 455 views |

### Key Finding from Analysis

> "Every successful kids channel has either high-quality custom animation with original music, OR real humans/kids on camera. No successful kids channel relies on AI-generated images with TTS voiceover."

### Traffic Sources
| Source | % of views |
|--------|-----------|
| YouTube Search | 67.9% |
| Related Video | 12.7% |
| Channel Page | 6.5% |
| Playlist | 5.4% |
| Shorts Feed | 3.0% |
| Subscriber | 1.6% |

---

## 10. Current Problems & Red Flags

### CRITICAL

| # | Problem | Impact |
|---|---------|--------|
| 1 | **Disk 96% full** (317 MB free on 6.8 GB) | Pipeline will crash when disk runs out. Weekly cleanup not freeing enough. |
| 2 | **Video pipeline failing silently** | 0 full videos produced in recent weeks. `_safe_run` catches the crash, logs to journal, moves on. No notification email sent for crashes. |
| 3 | **No subtitles on any video** | ImageMagick not installed on EC2. All 206 videos have no subtitles. Hurts accessibility, SEO, watch time. |
| 4 | **Duplicate scheduling** | Systemd scheduler + crontab both running shorts. Unintentional 5 shorts/day instead of 2. |
| 5 | **5 uploads/day = AI slop signal** | YouTube's mass-production detection triggers at 2+/day. ChuChu TV (96M subs) does 10-15/month. |

### HIGH PRIORITY

| # | Problem | Impact |
|---|---------|--------|
| 6 | **All v2 intelligence disabled** | Trends, clusters, series, analytics, thumbnail A/B -- all built but not running. Channel operates as random topic dump with no strategy. |
| 7 | **Zero analytics feedback** | 206 videos, 0 analytics fetched. Topic scores empty. Category weights not computed. System is blind to what works. |
| 8 | **89% videos in 3 categories** | animals/science/nature dominate. No topic diversity. |
| 9 | **No content variety** | Only shorts. No videos, poems, or lullabies despite all being built. Single character. Same formula. |
| 10 | **Declining views** | -84.2% decline. Possible algorithmic suppression already happening. |

### MEDIUM

| # | Problem | Impact |
|---|---------|--------|
| 11 | **Google TTS credentials path wrong on EC2** | Points to `/Users/arpitpandey/...` (Mac path). Works because Sarvam is the active TTS provider, but switching to Google TTS would fail. |
| 12 | **Voice rotation config mismatch** | Voice rotation pool has Google voices, but TTS provider is Sarvam. Rotation has no effect. |
| 13 | **API keys in plain text in config** | Sarvam API key and Gmail app password exposed in config.yaml. |
| 14 | **No quality gates** | Videos uploaded without audio/image/script quality checks. |
| 15 | **Brand voice not enabled** | Video tone varies randomly per GPT generation. |
