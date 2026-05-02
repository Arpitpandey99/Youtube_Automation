# YouTube Automation v2 — Architecture

## System Overview

Queue-based content pipeline for a Hinglish tech-explainer YouTube channel. Produces video candidates daily, gates every upload through a Telegram approval bot, and closes the analytics-to-strategy feedback loop automatically.

- **Long-form**: 8-12 min landscape (1280x720), 2/week
- **Shorts**: ~1 min vertical (1080x1920), 3-4/week
- **Content**: Hinglish "how things work" — Indian tech, science, infrastructure deep-dives
- **Made-for-Kids**: OFF (permanently)

**Source of truth for v2 design decisions:** [`REVAMP_PLAN.md`](REVAMP_PLAN.md)

---

## Four-Loop Architecture

```
┌─ STRATEGY LOOP (weekly + on-demand) ─────────────────────────────┐
│  analytics_agent → trend_service → competitor_agent              │
│       ↓                                                           │
│  cluster_service → series_service → learning_agent               │
└───────────────────────────────────────────────────────────────────┘
                              ↓ (informs)
┌─ CONTENT LOOP (daily, produces ONE candidate) ───────────────────┐
│  topic_agent → research_agent → script_agent                     │
│       ↓                                                           │
│  quality_agent → asset_agent → animation_agent                   │
│       ↓                                                           │
│  caption_agent → video_agent → metadata_agent                    │
│       ↓                                                           │
│  approval_agent (Telegram bot) → [QUEUE]                         │
└───────────────────────────────────────────────────────────────────┘
                              ↓ (on tap-approve)
┌─ PUBLISH LOOP (triggered by approval) ───────────────────────────┐
│  upload_agent → playlist_agent → notification_agent              │
└───────────────────────────────────────────────────────────────────┘
                              ↓
┌─ FEEDBACK LOOP (every 6h) ───────────────────────────────────────┐
│  analytics_agent → learning_agent → thumbnail_ab_service         │
│       ↓                                                           │
│  kill_switch_agent → [pause if red]                              │
└───────────────────────────────────────────────────────────────────┘
```

### Key structural difference from v1

v1 was fully automatic: generate → upload → done. v2 produces *candidates*, not uploads. Nothing publishes without a Telegram tap. 24h no-response = auto-reject (pipeline pauses, never auto-publishes).

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEVELOPER (Mac)                             │
│   git push → GitHub (v2-tech branch)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ deploys to
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              AWS Lightsail (Ubuntu, IST timezone)               │
│                                                                 │
│  systemd:                                                       │
│    v2-approval-bot.service  (long-running Telegram bot)         │
│                                                                 │
│  cron:                                                          │
│    06:00 daily    → --content-loop                              │
│    */6h           → --feedback-loop                             │
│    06:00 Sunday   → --strategy-loop                             │
│    */15min        → --publish-approved                          │
│                                                                 │
│  Telegram Bot API (free) ←→ Arpit's phone                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ uploads to
                           ▼
              YouTube (scheduled to 19:00-20:30 IST)
```

---

## Agent Reference

### Content Generation

| Agent | File | Tool | Purpose |
|---|---|---|---|
| `topic_agent` | `agents/topic_agent.py` | GPT-4o-mini | Topic selection with tech cluster weighting from learning_agent |
| `research_agent` | `agents/research_agent.py` | Web search + GPT-4o-mini | Produces verified fact sheet with sources per topic |
| `script_agent` | `agents/script_agent.py` | GPT-4o-mini | Scene-by-scene Hinglish scripts consuming research fact sheets |
| `quality_agent` | `agents/quality_agent.py` | GPT-4o-mini | LLM-as-judge: 4-axis rubric (hook/narrative/specificity/hinglish), gate before asset gen |

### Asset Generation

| Agent | File | Tool | Purpose |
|---|---|---|---|
| `asset_agent` | `agents/asset_agent.py` | Sarvam TTS + Replicate/HF | TTS voiceover (Sarvam Bulbul v3) + image generation |
| `animation_agent` | `agents/animation_agent.py` | MoviePy + NumPy | Ken Burns pan/zoom effects per scene |
| `caption_agent` | `agents/caption_agent.py` | — | SRT subtitle generation timed to audio |

### Assembly & Output

| Agent | File | Tool | Purpose |
|---|---|---|---|
| `video_agent` | `agents/video_agent.py` | MoviePy | Final video: animated clips + audio + subtitles + bg music |
| `metadata_agent` | `agents/metadata_agent.py` | GPT-4o-mini + Pillow | YouTube title/description/tags + thumbnail generation |
| `approval_agent` | `agents/approval_agent.py` | python-telegram-bot | Telegram bot: preview + thumbnails + inline keyboard |
| `upload_agent` | `agents/upload_agent.py` | YouTube Data API v3 | Queued upload triggered by Telegram approval |
| `playlist_agent` | `agents/playlist_agent.py` | YouTube Data API v3 | Auto-playlist management |

### Analytics & Feedback

| Agent | File | Tool | Purpose |
|---|---|---|---|
| `analytics_agent` | `agents/analytics_agent.py` | YouTube Analytics API | Fetch views, CTR, retention, impressions |
| `learning_agent` | `agents/learning_agent.py` | GPT-4o-mini | Close analytics→strategy loop, update cluster weights |
| `competitor_agent` | `agents/competitor_agent.py` | YouTube Data API v3 | Weekly Hinglish tech channel intel, pattern extraction |
| `kill_switch_agent` | `agents/kill_switch_agent.py` | — | 6-trigger watchdog, auto-pause + Telegram alert |

### Infrastructure

| Agent | File | Purpose |
|---|---|---|
| `notification_agent` | `agents/notification_agent.py` | Email run summaries (Gmail SMTP / Resend) |
| `rate_limiter` | `agents/rate_limiter.py` | Token-bucket rate limiting per API provider |
| `budget_guard` | `agents/budget_guard.py` | `@budget_guard` decorator enforcing per-provider monthly caps |
| `ab_agent` | `agents/ab_agent.py` | A/B title/hook variant generation |
| `db` | `agents/db.py` | SQLite DB (21 tables, WAL mode) |

---

## Services

| Service | File | Purpose |
|---|---|---|
| `approval_queue_service` | `services/approval_queue_service.py` | Queue state machine: pending → approved/rejected/timeout |
| `analytics_service` | `services/analytics_service.py` | Bulk analytics sweep, category weight computation |
| `trend_service` | `services/trend_service.py` | Trending topic discovery (YouTube search/autocomplete/competitor) |
| `cluster_service` | `services/cluster_service.py` | GPT-powered topic clustering for topical authority |
| `series_service` | `services/series_service.py` | Episodic series planning and management |
| `thumbnail_ab_service` | `services/thumbnail_ab_service.py` | Thumbnail variant generation and auto-replacement |
| `retention_service` | `services/retention_service.py` | Retention analysis and script structure prompts |
| `schedule_optimizer_service` | `services/schedule_optimizer_service.py` | Optimal upload time selection from historical data |

---

## Database Schema (SQLite — `data/pipeline.db`)

### Core tables (v1)

| Table | Purpose |
|---|---|
| `videos` | All uploaded videos |
| `metrics` | YouTube stats per video |
| `ab_variants` | Title/hook/thumbnail A/B variants |
| `topic_scores` | Topic performance scores |
| `playlists` | Auto-created playlists |
| `quota_usage` | API quota tracking |
| `category_weights` | Performance weights per category |
| `trend_topics` | Discovered trending topics |
| `competitor_channels` | Competitor channel tracking |
| `topic_clusters` | Thematic topic groups |
| `series` | Episodic content series |
| `series_episodes` | Individual episodes within series |
| `thumbnail_variants` | Thumbnail A/B variants |
| `upload_time_slots` | Upload timing data |

### New tables (v2)

| Table | Purpose |
|---|---|
| `approval_queue` | Candidate queue: pending/approved/rejected/timeout |
| `quality_scores` | LLM-as-judge scores per script (hook/narrative/specificity/hinglish) |
| `competitor_videos` | Individual competitor video data (views, duration, view/sub ratio) |
| `kill_switch_events` | Kill switch trigger log with metrics snapshots |
| `api_costs` | Per-provider API spend tracking for budget_guard |
| `learning_log` | Daily learning agent summaries and weight changes |

---

## Cost Model

### Per-video cost

| Component | Long-form (8-12 min) | Shorts (~1 min) |
|---|---|---|
| Research | INR 6-8 | INR 2 (cached) |
| Script | INR 3 | INR 1 |
| Quality scoring | INR 1 | INR 0.5 |
| TTS (Sarvam) | INR 6-8 | INR 0.75 |
| Images | INR 20-30 (Replicate) | INR 0 (HuggingFace free) |
| Thumbnail | INR 2 | INR 0 |
| **Total** | **INR 40-55** | **INR 4-7** |

### Monthly total

| Line item | Cost (INR) |
|---|---|
| 10 long-form x INR 50 | 500 |
| 14 shorts x INR 6 | 84 |
| AWS Lightsail | 425 |
| Buffer | 200 |
| **Steady-state** | **~1259** |

Hard ceiling: INR 1500/month (kill switch fires above).

---

## Configuration (`config.yaml`)

| Section | Key Settings |
|---|---|
| `openai` | `api_key`, `model` (gpt-4o-mini) |
| `image_provider` | `replicate` (long-form) / `huggingface` (shorts) |
| `tts.provider` | `sarvam` (default, Bulbul v3) |
| `animation.provider` | `kenburns` (only option) |
| `telegram` | `bot_token`, `chat_id` |
| `youtube` | `client_secrets_file`, `token_file`, `privacy_status`, `made_for_kids: false` |
| `content` | `niche: "how things work tech explainer"` |
| `budget` | See `config/budget.yaml` |
| `quality` | See `config/quality_rubric.yaml` |

---

## CLI Reference

```bash
# Core pipeline
python main.py --content-loop              # daily candidate production
python main.py --content-loop --no-upload  # local test
python main.py --approval-bot              # long-running Telegram bot
python main.py --publish-approved          # upload approved candidates

# Feedback & strategy
python main.py --feedback-loop             # analytics → learning → kill-switch
python main.py --strategy-loop             # trends + competitor + cluster + series
python main.py --analytics-sweep           # one-shot bulk analytics fetch

# Maintenance
python main.py --cleanup-old --days 7 --dry-run
python main.py --cleanup-old --days 7
python main.py --generate-music
```

---

## Project Structure

```
Youtube_Automation/
├── main.py                     # Orchestrator — 4-loop pipeline
├── config.yaml                 # API keys + settings (gitignored)
├── config.example.yaml         # Template config
├── requirements.txt
├── REVAMP_PLAN.md              # v2 design source of truth
├── ARCHITECTURE.md             # This file
├── CLAUDE.md                   # Claude Code guidance
├── README.md
│
├── agents/
│   ├── topic_agent.py          # Topic selection (tech clusters)
│   ├── research_agent.py       # Web research → fact sheets
│   ├── script_agent.py         # Hinglish tech-explainer scripts
│   ├── quality_agent.py        # LLM-as-judge quality gate
│   ├── asset_agent.py          # Sarvam TTS + Replicate/HF images
│   ├── animation_agent.py      # Ken Burns effects
│   ├── video_agent.py          # MoviePy video assembly
│   ├── caption_agent.py        # SRT generation
│   ├── metadata_agent.py       # YouTube metadata + thumbnails
│   ├── approval_agent.py       # Telegram approval bot
│   ├── upload_agent.py         # YouTube upload (queued)
│   ├── analytics_agent.py      # YouTube Analytics fetcher
│   ├── learning_agent.py       # Analytics → strategy feedback
│   ├── competitor_agent.py     # Competitor channel intel
│   ├── kill_switch_agent.py    # Pipeline safety watchdog
│   ├── ab_agent.py             # A/B testing
│   ├── playlist_agent.py       # Auto-playlist management
│   ├── notification_agent.py   # Email summaries
│   ├── rate_limiter.py         # API rate limiting
│   ├── budget_guard.py         # Cost ceiling decorator
│   └── db.py                   # SQLite database
│
├── services/
│   ├── approval_queue_service.py
│   ├── analytics_service.py
│   ├── trend_service.py
│   ├── cluster_service.py
│   ├── series_service.py
│   ├── thumbnail_ab_service.py
│   ├── retention_service.py
│   └── schedule_optimizer_service.py
│
├── config/
│   ├── quality_rubric.yaml     # LLM-as-judge scoring rubric
│   ├── budget.yaml             # Monthly per-provider caps
│   └── competitors.yaml        # Seed competitor channels
│
├── data/
│   ├── pipeline.db             # SQLite (21 tables, gitignored)
│   ├── fact_sheets/            # Cached research (90-day TTL)
│   ├── learning_log/           # Daily learning summaries
│   ├── system_state.json       # Kill-switch pause flag
│   └── topics_history.json     # Topic deduplication
│
└── output/                     # Per-run directories (gitignored)
```
