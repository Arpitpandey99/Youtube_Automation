# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Source of truth for v2 design:** [`REVAMP_PLAN.md`](REVAMP_PLAN.md)

## What this project is

Automated YouTube channel pipeline for **Hinglish "how things work" tech-explainer** videos. Faceless storytelling format covering Indian tech, science, and infrastructure deep-dives. Target: 2 long-form (8-12 min) + 3-4 shorts/week.

**This is NOT a kids channel.** Made-for-Kids is OFF. The v1 kids-content channel has been abandoned (archived on `v1-archive` branch).

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in API keys
cp config.example.yaml config.yaml

# Download background music (run once)
python main.py --generate-music
```

YouTube OAuth: place `client_secrets.json` in the project root. On first upload, `token.json` is generated via browser auth.

Telegram bot: create via BotFather, add `bot_token` and `chat_id` to `config.yaml` under `telegram:`.

## Running the pipeline

```bash
# Daily content production (produces ONE candidate, sends to Telegram for approval)
python main.py --content-loop
python main.py --content-loop --no-upload    # local test, skip queuing

# Telegram approval bot (long-running)
python main.py --approval-bot

# Publish approved candidates to YouTube
python main.py --publish-approved

# Feedback loop: analytics → learning → kill-switch (every 6h)
python main.py --feedback-loop

# Weekly strategy: trends + competitor + cluster + series
python main.py --strategy-loop

# One-shot analytics fetch
python main.py --analytics-sweep

# Maintenance
python main.py --cleanup-old --days 7 --dry-run
python main.py --cleanup-old --days 7
```

## Architecture

### Pipeline flow (v2)

Nothing publishes without a Telegram tap. The pipeline produces *candidates*, not uploads.

```
CONTENT LOOP (daily):
  topic_agent → research_agent → script_agent → quality_agent
       → asset_agent → animation_agent → video_agent
       → metadata_agent → approval_agent (Telegram queue)

PUBLISH LOOP (on approval):
  upload_agent → playlist_agent → notification_agent

FEEDBACK LOOP (every 6h):
  analytics_agent → learning_agent → kill_switch_agent

STRATEGY LOOP (weekly):
  competitor_agent → trend_service → cluster_service → series_service
```

### Agent inventory (23 agents)

| Agent | File | Purpose |
|---|---|---|
| `topic_agent` | `agents/topic_agent.py` | Topic selection with tech cluster weighting |
| `research_agent` | `agents/research_agent.py` | **NEW** — Web research → verified fact sheet with sources |
| `script_agent` | `agents/script_agent.py` | Hinglish tech-explainer scripts consuming fact sheets |
| `quality_agent` | `agents/quality_agent.py` | **NEW** — LLM-as-judge, 4-axis scoring, reject/flag/approve |
| `asset_agent` | `agents/asset_agent.py` | Image gen (Replicate FLUX / HuggingFace) + TTS (Sarvam Bulbul v3) |
| `animation_agent` | `agents/animation_agent.py` | Ken Burns effects only (AI video providers removed) |
| `video_agent` | `agents/video_agent.py` | MoviePy assembly: clips + audio + subtitles + bg music |
| `caption_agent` | `agents/caption_agent.py` | SRT subtitle generation |
| `metadata_agent` | `agents/metadata_agent.py` | YouTube title/description/tags + Pillow thumbnails |
| `approval_agent` | `agents/approval_agent.py` | **NEW** — Telegram bot with inline approval keyboard |
| `upload_agent` | `agents/upload_agent.py` | YouTube upload (queued mode, triggered by approval) |
| `analytics_agent` | `agents/analytics_agent.py` | YouTube Analytics API fetcher |
| `learning_agent` | `agents/learning_agent.py` | **NEW** — Analytics → strategy loop, cluster weight updates |
| `competitor_agent` | `agents/competitor_agent.py` | **NEW** — Weekly Hinglish tech channel intel |
| `kill_switch_agent` | `agents/kill_switch_agent.py` | **NEW** — 6-trigger watchdog, auto-pause pipeline |
| `ab_agent` | `agents/ab_agent.py` | A/B title/hook variant generation |
| `playlist_agent` | `agents/playlist_agent.py` | Auto-playlist management |
| `notification_agent` | `agents/notification_agent.py` | Email run summaries |
| `rate_limiter` | `agents/rate_limiter.py` | API quota throttling |
| `budget_guard` | `agents/budget_guard.py` | **NEW** — Cost ceiling enforcement decorator |
| `db` | `agents/db.py` | SQLite DB (21 tables) |

### Services (`services/`)

- `approval_queue_service` — Telegram approval queue state machine
- `analytics_service` — bulk analytics sweep, category weight computation
- `trend_service` — trending topic discovery
- `cluster_service` — GPT-powered topic clustering
- `series_service` — episodic series planning
- `thumbnail_ab_service` — thumbnail A/B testing
- `retention_service` — retention analysis
- `schedule_optimizer_service` — optimal upload time selection

### Cost ceiling and budget enforcement

Hard monthly caps enforced by `@budget_guard` decorator on every paid API call:

| Provider | Monthly cap (INR) |
|---|---|
| OpenAI (GPT-4o-mini) | 500 |
| Sarvam (TTS) | 400 |
| Replicate (FLUX images) | 700 |
| HuggingFace | 0 (free tier) |
| **Total ceiling** | **1500** |

Thresholds: 60% = log warning, 80% = Telegram alert, 100% = `BudgetExceededError`.

Caps defined in `config/budget.yaml`. Spend tracked in `api_costs` DB table.

### Approval gate

Every video candidate goes through Telegram approval:
- 30-second preview clip + 3 thumbnail variants + 3 title variants
- Inline keyboard: Publish | Regen Hook | New Thumbnail | Reject
- 24h timeout = auto-reject (never auto-publish)

### Data storage

- **SQLite** (`data/pipeline.db`) — 21 tables (v1 core + 6 new v2 tables)
- **`data/fact_sheets/`** — cached research fact sheets (90-day TTL)
- **`data/learning_log/`** — daily learning agent summaries
- **`data/system_state.json`** — kill-switch pause flag
- **`output/`** — per-run directories (gitignored)

### Configuration

All behaviour controlled by `config.yaml` (copy from `config.example.yaml`). Key sections:
- `tts.provider` — `sarvam` (default) | `google` | `elevenlabs` | `openai` | `edge-tts`
- `image_provider` — `replicate` (default for long-form) | `huggingface` (default for shorts) | `openai` | `pexels`
- `animation.provider` — `kenburns` (only option in v2)
- `telegram.bot_token` / `telegram.chat_id` — approval bot config
- `trends/clusters/series` — growth intelligence toggles

### Content language

All content is **Hinglish** (Hindi-English code-switching). `LANG_CODE = "hi"`, `LANG_NAME = "Hindi"` in `main.py`. `visual_description` fields in scripts are always English for AI image prompts.
