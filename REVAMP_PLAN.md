# YouTube Automation v2 — Revamp Plan

**Status:** Active plan. Source of truth for v2 implementation.
**Owner:** Arpit
**Branch:** `v2-tech`
**Last revised:** May 2026

---

## 0. TL;DR

The current channel is in YouTube's 2026 AI-slop kill zone in the worst possible niche (kids content). We are abandoning it cleanly, keeping the codebase, and pivoting to a Hinglish "how things work" tech-explainer channel where Arpit's actual technical depth (IIT Jodhpur M.Tech AI, Wi-Fi HaLow research, full-stack SaaS builder) becomes the unfair advantage that AI slop can't replicate.

The v2 system keeps the existing 17-agent architecture but adds 6 new agents that close the loop: **research → quality gate → approval (Telegram) → upload → learning → kill-switch**. Pure automation is replaced with **5-10 minutes/day of Telegram-based approval**, which is the only realistic path to a monetizable faceless channel in 2026 YouTube.

Steady-state cost: **₹1300-1800/month**, with quality not compromised. AWS Lightsail kept as the host. Sarvam AI Bulbul v3 for TTS. Replicate FLUX for images on long-form, HuggingFace free tier for shorts.

---

## 1. The brutal reality (one-page recap)

### Why the current channel is dead

- **Niche death zone.** In April 2026, 200+ child advocacy groups (Fairplay, AFT, Jonathan Haidt) demanded YouTube ban AI-generated content from kids platforms entirely. YouTube confirmed it's developing dedicated AI labels for YouTube Kids. The regulatory direction is one-way.
- **Algorithmic death zone.** YouTube's "Inauthentic Content Policy" (renamed July 2025) now evaluates entire channels for AI patterns. January 2026 enforcement wave terminated 16 major channels (35M subs, 4.7B lifetime views, $10M annual revenue). Upload frequency, format similarity, lack of commentary, minimal editing all stack as risk signals.
- **Channel signature is textbook AI slop.** 5 shorts/day, Ken Burns + TTS, 89% in 3 categories, no commentary, no editing judgment. Self-assessed AI slop risk: 85/100.
- **Made-for-Kids structural tax.** No comments, no notifications, no end screens, no personalized ads (~25-35% of normal CPM), no community tab.
- **Numbers.** 206 videos, 1,007 total views, 14 subscribers, ~5 views/video average. Channel is already algorithmically classified.

### Why the codebase is salvageable

17 agents + 7 services + 15-table SQLite + scheduler + multi-provider abstractions + A/B harness. Genuinely strong agentic content system. Wrong battlefield, right machinery. We redirect, not rebuild.

### Why pure automation cannot win on 2026 YouTube

YouTube's 2026 enforcement standard requires "visible human creativity / judgment per upload." A fully automated faceless pipeline cannot pass this bar at scale and grow. We accept a 5-10 min/day human checkpoint as a hard architectural decision.

---

## 2. The new channel

### Concept

**"How things actually work" — Indian tech, science, and infrastructure deep-dives in Hinglish, faceless storytelling format.**

### Why this niche, specifically

| Factor | Why it works |
|---|---|
| Real moat | Arpit's M.Tech AI + Wi-Fi HaLow research + SaaS-builder background can fact-check at the 5-min approval step in ways no other automated channel can |
| Healthy CPM | Tech audience in India: $1.50-3.50 RPM vs $0.20-0.80 for kids/general entertainment |
| Long watch time | "How X works" content averages 50-65% retention on 8-12 min videos |
| AI-friendly visuals | Diagrams, system flows, abstract concepts — generated visuals are appropriate and not uncanny |
| Counter-signal to slop detection | Narrative arc (problem → mechanism → resolution) is structurally different from templated listicles |
| Series-friendly | Existing `series_agent` shines. "UPI in 5 parts", "Indian Railways tech in 4 parts" → binge-watching, subscriber loyalty |

### Content examples (initial cluster seeds)

- *WhatsApp ka encryption actually kaise kaam karta hai?*
- *UPI banaya kaise gaya? Pure backend ki kahani*
- *Aadhaar ka system inside out*
- *Why Indian ATMs are different from rest of the world*
- *5G in India — vo sab jo kisi ne nahi bataya*
- *Smart meters aur AMI networks — your electricity bill ka future* (Arpit's literal research domain)
- *DigiLocker kaise kaam karta hai*
- *FASTag system architecture*
- *IRCTC ka backend kyu crash hota hai*

### Format mix

- 2 long-form/week (8-12 min) — primary growth + monetization driver
- 3-4 shorts/week — discovery feeders that link to long-form
- **Total: 5-6 uploads/week (NOT 35/week like v1)**

### Made-For-Kids toggle: **OFF**. Permanently.

---

## 3. Architecture v2 — overview

### Three structural changes from v1

1. **Approval gate is now the most important component.** Pipeline produces *candidates*, not uploads. Nothing publishes without a Telegram tap.
2. **Quality agent runs LLM-as-judge before assets are generated.** Bad scripts get rejected before wasting image API budget.
3. **Learning agent closes the analytics → strategy loop.** Performance data automatically updates topic weights, kills failing patterns, proposes new clusters.

### High-level agent map

```
┌─ STRATEGY LOOP (weekly + on-demand) ─────────────────────────────┐
│  analytics_agent → trend_agent → competitor_agent (NEW)          │
│       ↓                                                           │
│  cluster_agent → series_agent → learning_agent (NEW)             │
└───────────────────────────────────────────────────────────────────┘
                              ↓ (informs)
┌─ CONTENT LOOP (daily, produces ONE candidate) ───────────────────┐
│  topic_agent → research_agent (NEW) → script_agent               │
│       ↓                                                           │
│  quality_agent (NEW) → asset_agent → animation_agent             │
│       ↓                                                           │
│  caption_agent → video_agent → metadata_agent                    │
│       ↓                                                           │
│  approval_agent (NEW, Telegram bot) → [QUEUE]                    │
└───────────────────────────────────────────────────────────────────┘
                              ↓ (on tap-approve)
┌─ PUBLISH LOOP (triggered by approval) ───────────────────────────┐
│  upload_agent → playlist_agent → notification_agent              │
└───────────────────────────────────────────────────────────────────┘
                              ↓
┌─ FEEDBACK LOOP (every 6h) ───────────────────────────────────────┐
│  analytics_agent → learning_agent → thumbnail_ab_service         │
│       ↓                                                           │
│  kill_switch_agent (NEW) → [pause if red]                        │
└───────────────────────────────────────────────────────────────────┘
```

### Agent disposition

| Status | Agents |
|---|---|
| **NEW (6)** | `research_agent`, `quality_agent`, `approval_agent`, `learning_agent`, `competitor_agent`, `kill_switch_agent` |
| **KEEP as-is** | `caption_agent`, `metadata_agent`, `video_agent`, `analytics_agent`, `playlist_agent`, `ab_agent`, `notification_agent`, `rate_limiter`, `db.py` |
| **REFACTOR** | `topic_agent` (new clusters), `script_agent` (consume research_agent), `asset_agent` (Sarvam + FLUX/HF default), `animation_agent` (Ken Burns only), `upload_agent` (queued mode), `main.py` (new orchestration), all `services/*` (turn ON, retarget to tech) |
| **DELETE** | `poem_agent`, `lullaby_agent`, AI video providers in `animation_agent` (Kling, Veo), `instagram_agent` (defer until YouTube works), `prefect_flow.py` |

### New file additions

```
agents/
├── research_agent.py          # NEW
├── quality_agent.py           # NEW
├── approval_agent.py          # NEW (Telegram bot)
├── learning_agent.py          # NEW
├── competitor_agent.py        # NEW
├── kill_switch_agent.py       # NEW
└── budget_guard.py            # NEW (cost ceiling enforcement)

services/
└── approval_queue_service.py  # NEW

config/
└── quality_rubric.yaml        # NEW (LLM-as-judge rubric)
```

---

## 4. The 6 new agents — full specs

### 4.1 `research_agent.py`

**Purpose.** Bridge between `topic_agent` and `script_agent`. Takes a topic, produces a verified fact sheet with sources. This is the single biggest difference between "AI slop about UPI" and "actually-correct video about UPI."

**Inputs:** `topic` (str), `cluster_context` (dict, optional)
**Outputs:** `fact_sheet.json` with structured fields:
```json
{
  "topic": "How UPI works",
  "key_facts": [
    {"fact": "...", "source_url": "...", "confidence": 0.9}
  ],
  "narrative_arc": {
    "hook_angle": "...",
    "problem": "...",
    "mechanism": "...",
    "resolution": "..."
  },
  "technical_terms": [{"term": "VPA", "explanation": "..."}],
  "common_misconceptions": ["..."],
  "credibility_signals": ["RBI report 2024", "NPCI documentation"]
}
```

**Implementation:**
- 5-8 web searches per topic (use existing rate_limiter)
- GPT-4o-mini for synthesis with strict JSON schema
- Cache fact sheets in `data/fact_sheets/<topic_slug>.json` for 90 days
- Cost cap: ₹10/call (enforced by budget_guard)

### 4.2 `quality_agent.py`

**Purpose.** LLM-as-judge that rejects below-threshold scripts before they consume image budget. The AI slop firewall.

**Inputs:** `script.json`
**Outputs:** `quality_score.json`:
```json
{
  "total": 84,
  "breakdown": {
    "hook": 22,        // 0-25, does first 8 sec stop scrolling
    "narrative": 21,   // 0-25, problem→mechanism→resolution
    "specificity": 20, // 0-25, concrete numbers/names/dates
    "hinglish": 21     // 0-25, natural Hinglish, not robotic
  },
  "verdict": "approve",  // approve | flag_for_review | reject
  "flags": [],
  "rewrite_suggestions": []
}
```

**Thresholds:**
- ≥ 80: auto-approve, proceed to asset generation
- 70-79: flag for human review in Telegram with reasons
- < 70: auto-reject, regenerate with rewrite_suggestions injected into prompt
- Max 3 regenerations before topic is shelved for a week

**Rubric stored in `config/quality_rubric.yaml`** so it can be tuned over time without code changes.

**Cost:** ~₹1/call

### 4.3 `approval_agent.py`

**Purpose.** Telegram bot that delivers the daily candidate to Arpit's phone with one-tap actions.

**Tech:** `python-telegram-bot` library, free Telegram Bot API.

**Workflow:**
1. After video assembly, send Telegram message with:
   - 30-second preview clip (lower res to save bandwidth)
   - 3 thumbnail variants (inline image grid)
   - 3 title variants
   - Quality score breakdown
   - Inline keyboard: ✅ Publish | 🔄 Regen Hook | 🎨 New Thumbnail | ❌ Reject
2. Listen for callback in a long-running loop / webhook
3. On approve → write to `approval_queue` table, trigger `upload_agent`
4. On reject → log reason, mark topic for cooldown
5. On regen → re-trigger relevant sub-agent only (not full pipeline)
6. **24h timeout = auto-reject** (safer than auto-publish)

**State:** Stored in `approval_queue` table with `pending | approved | rejected | timeout` states.

### 4.4 `learning_agent.py`

**Purpose.** Closes the analytics → strategy loop. The reason your v1 had analytics but no growth — it never fed back into decisions.

**Runs:** Daily at 02:00 IST after `analytics_agent` completes.

**Logic:**
1. Pull last 7 days of video performance from `analytics_agent` outputs
2. Compute per-cluster CTR, retention, watch time
3. Update `topic_scores` table:
   - Cluster CTR > median + 1σ → weight × 1.5
   - Cluster CTR < median - 1σ → weight × 0.5
   - 3 strikes (3 videos with CTR < 2%) → cluster auto-paused for 30 days
4. Identify "format losers" (e.g., if 5-min videos retain 25% but 10-min retain 55%, reduce weight on 5-min target duration)
5. Propose 2 new clusters/week to `cluster_agent` based on competitor_agent's top performers
6. Write summary to `data/learning_log/<date>.md` for human review

### 4.5 `competitor_agent.py`

**Purpose.** Weekly intel on what's working in the niche.

**Runs:** Sunday 06:00 IST.

**Logic:**
1. Search YouTube Data API for top 20 channels in tech/Hinglish space (configurable seed list + keyword search)
2. Pull their last 30 days of uploads
3. Sort by views/subscriber ratio (relative performance, not absolute)
4. For top 10 videos: extract title structure, thumbnail style, video length, upload time
5. Store in `competitor_videos` table (NEW table)
6. Feed structural patterns to `topic_agent` and `cluster_agent`
7. **Never copy titles directly.** Extract patterns: e.g., "How X works" beats "X explained" 2:1 in CTR for tech-Hinglish.

**Seed channels (initial list, edit in `config/competitors.yaml`):**
- Be A Engineer (Hindi tech)
- Tech Burner
- Geeky Ranjit
- Technical Guruji
- (add 6-8 more after first run, including Hinglish education channels)

### 4.6 `kill_switch_agent.py`

**Purpose.** Prevent slow disasters. Auto-pause the pipeline if red flags trip.

**Runs:** Every 6 hours.

**Triggers (any one fires the kill switch):**
- Median view count of last 5 uploads < 30% of trailing 20-upload median
- Any video gets a "limited or no ads" YPP flag
- Subscriber loss > subscriber gain over rolling 7 days
- A/B thumbnail tests show 0 winning variants in last 10 attempts (content fundamentally not landing)
- Channel-level "Inauthentic Content" warning email from YouTube
- Daily API spend > 150% of 30-day average

**Action on trigger:**
1. Write entry to `kill_switch_events` table
2. Set system flag `pipeline_paused=True` in `data/system_state.json`
3. `main.py` content loop checks this flag at every run, exits early if paused
4. Telegram alert with diagnosis: which trigger fired, recent metrics, recommended action
5. Pipeline only resumes when Arpit sends `/resume` to the Telegram bot

### 4.7 `budget_guard.py` (utility, not agent)

**Purpose.** Hard cost ceiling enforced in code. Wraps every paid API call.

**Logic:**
```python
@budget_guard(provider="sarvam", monthly_cap_inr=400)
def synthesize_audio(text): ...
```
- Tracks per-provider spend in `api_costs` table (NEW)
- 60% of cap → log warning
- 80% of cap → log warning + Telegram alert
- 100% of cap → raise BudgetExceededError, agent fails gracefully
- Resets monthly on the 1st

---

## 5. Cost model — locked

### Per-video cost (verified pricing)

**Long-form (8-12 min, ~2000 chars script, 8-10 images):**

| Component | Provider | Cost (₹) |
|---|---|---|
| Research (5-8 searches + GPT synthesis) | GPT-4o-mini + web | 6-8 |
| Script generation | GPT-4o-mini | 3 |
| Quality scoring | GPT-4o-mini | 1 |
| TTS (~2000 chars) | Sarvam Bulbul v3 | 6-8 |
| Images (8-10) | Replicate FLUX schnell ($0.003/img) | 20-30 |
| Thumbnail | Pillow + GPT-4o-mini | 2 |
| **Per long-form** | | **40-55** |

**Shorts (~1 min, ~250 chars script, 3-4 images):**

| Component | Provider | Cost (₹) |
|---|---|---|
| Research | cached + GPT | 2 |
| Script | GPT-4o-mini | 1 |
| Quality | GPT-4o-mini | 0.5 |
| TTS (~250 chars) | Sarvam Bulbul v3 | 0.75 |
| Images (3-4) | HuggingFace FLUX free tier | 0 |
| Thumbnail | Pillow | 0 |
| **Per short** | | **4-7** |

### Monthly volume

10 long-form + 14 shorts = 24 videos.

### Monthly total

| Line item | Cost (₹) |
|---|---|
| 10 long-form × ₹50 | 500 |
| 14 shorts × ₹6 | 84 |
| AWS Lightsail $5/mo (₹85/USD) | 425 |
| Backblaze B2 backup (~5 GB) | 50 |
| Telegram bot | 0 |
| Buffer (regenerations, A/B variants, kill switch retries) | 200 |
| **Steady-state monthly** | **~₹1259** |

That sits comfortably in the ₹1500-2500 target band, with ~₹700-1200/month of headroom for:
- ElevenLabs voice cloning (₹2000/mo) once monetized
- Higher-quality FLUX dev model on shorts
- Premium Sarvam plan if rate limits hit
- Second channel A/B test in month 4-6

### Hard caps in `config/budget.yaml`

```yaml
monthly_caps_inr:
  openai: 500       # GPT-4o-mini total
  sarvam: 400       # TTS
  replicate: 700    # FLUX images
  huggingface: 0    # free tier
  total: 1500       # absolute ceiling, kill switch fires above
```

---

## 6. Daily workflow & approval gate design

### Pipeline schedule

| Time (IST) | Job | Description |
|---|---|---|
| 02:00 | Feedback loop | analytics_agent → learning_agent → kill_switch check |
| 06:00 (Sun) | Strategy loop | competitor_agent → cluster_agent → series_agent |
| 06:00 (daily) | Content loop | topic → research → script → quality → assets → video → Telegram |
| Any time | Approval | Arpit taps in Telegram |
| 19:00-20:30 | Upload | Triggered by approval, scheduled to peak Indian tech-audience window |

### What Arpit's day looks like

Arpit gets a Telegram notification any time during the day, opens it:

1. **30 sec** — watch the preview clip
2. **30 sec** — pick title + thumbnail (or "use defaults")
3. **1 min** — skim quality_agent's score breakdown if anything was flagged
4. **1 tap** — Publish | Regen Hook | New Thumbnail | Reject

**Total daily commitment: 5-10 min, any time of day, no fixed window.**

If no response in 24h, candidate is auto-rejected (channel pauses for the day, doesn't auto-publish unreviewed content).

### Weekend session (1-2h, optional)

- Review week's analytics in `data/learning_log/<week>.md`
- Tune `quality_rubric.yaml` if you noticed approve/reject decisions you'd have made differently
- Adjust cluster weights if learning_agent missed a trend
- Skim competitor_agent's report for new ideas

---

## 7. 90-day roadmap with honest milestones

**No promises of YPP in 90 days.** Realistic faceless-channel monetization in 2026 is 6-9 months. Here's what 90 days actually look like.

### Days 1-7 — Triage and foundation

- [ ] Pause current channel (don't delete)
- [ ] Run `python main.py --analytics-sweep` once on existing 206 videos for autopsy data
- [ ] Free EC2 disk, fix ImageMagick dependency, fix silent video pipeline failure
- [ ] Pick channel name (30 min, no more)
- [ ] Create new YouTube channel under new Google account (clean separation from v1's algorithmic baggage). MFK toggle OFF.
- [ ] Branch repo `v2-tech`, push

### Days 8-21 — Build the new system

- [ ] Implement 6 new agents (one per day with Claude Code)
- [ ] Set up Telegram bot via BotFather, save token
- [ ] Wire up `budget_guard.py` with hard caps
- [ ] Integration test: produce 3 candidate videos end-to-end without uploading
- [ ] **Goal: pipeline working, ZERO published videos yet**

### Days 22-30 — Soft launch

- [ ] Publish first 5 videos via approval gate (manually approve everything)
- [ ] Establish baseline metrics
- [ ] **Goal: 0-50 subscribers, learning what the algorithm shows**

### Days 31-60 — Find what works

- [ ] 2 long-form/week + 3 shorts/week consistent cadence
- [ ] learning_agent kicks in, tunes topic weights
- [ ] A/B thumbnails on every video
- [ ] Test 3 different series formats, see which builds binge-watching
- [ ] **Goal: First video crosses 1000 views, 200-500 subs total, identify your "winning sub-niche" within tech**

### Days 61-90 — Compound

- [ ] Lock in winning sub-niche from day 60 analysis
- [ ] Increase to 3 long-form/week
- [ ] Two parallel series running
- [ ] **Goal: 800-2000 subs, 1500-3000 watch hours, ONE breakthrough video at 10K+ views**

### Days 91-180 — Honest monetization window

- [ ] Hit 1000 subs + 4000 public watch hours = YPP eligibility
- [ ] Apply for monetization
- [ ] Realistic first-month ad revenue: ₹1500-5000

### Pivot gates (kill criteria)

- **Day 30: < 50 subs total** → format wrong, swap target duration
- **Day 60: < 200 subs** → sub-niche wrong, pivot inside tech (e.g., from infrastructure to AI explainers)
- **Day 90: < 800 subs** → niche wrong, evaluate finance/tax niche pivot using same code

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| YouTube AI policy tightens further | Medium | Channel-ending | quality_agent enforces commentary/structure floor; AI disclosure honestly toggled; Made-for-Kids OFF |
| Niche wrong, no traction by day 60 | Medium | 60 days lost | learning_agent flags by day 30; pivot sub-niche by day 45 |
| Cost overrun (rogue API loop) | Low | ₹5K+ surprise bill | budget_guard.py kills agents at 80% cap, alerts at 60% |
| Burnout on daily Telegram approvals | Medium | Channel dies | Bot is brain-dead simple; auto-reject on missed days (channel pauses, doesn't slop) |
| 2-week exam/research crunch | High | Pipeline pauses | Auto-pause is fine. Don't try to "make up" missed days. |
| Lightsail crashes / data loss | Low | Days of uptime lost | Daily SQLite + media backup to Backblaze B2 (₹50/mo); pipeline restartable from any clone |
| Competitor channels copy playbook | Medium | Erosion | Moat = Arpit's actual technical depth + Wi-Fi HaLow / SaaS-builder backstory. Lean into rare topics. |
| Channel termination (bad-faith strike) | Low | Channel-ending | YouTube Audio Library only, never claim others' work, AI disclosure ON |
| Telegram bot token leaks | Low | Spam to bot, no channel impact | Token in env var, rotate quarterly, no destructive commands without `/confirm` |

---

## 9. Cleanup plan

### Local cleanup (run on dev laptop)

```bash
# Inside project root
cd /path/to/youtube_automation

# 1. Branch v1 to archive
git checkout -b v1-archive
git push origin v1-archive
git checkout main
git checkout -b v2-tech

# 2. Old run directories (41 local runs)
rm -rf output/video_*
rm -rf output/shorts_*
rm -rf output/poem_*
rm -rf output/lullaby_*

# 3. Kid-content artifacts
rm -rf data/characters/teddy_bear_friend
rm -rf data/characters/bunny_dreamer
rm -rf data/characters/owl_storyteller
rm -rf data/music/lullaby
# Move kids music to archive (don't delete yet, they're 11 MP3s)
mkdir -p data/music_archive
mv data/music/kids_*.mp3 data/music_archive/

# 4. Stale EC2 copy artifacts
rm data/ec2_pipeline.db
rm data/ec2_topics_history.json

# 5. Token backups
rm token.json.bak

# 6. Empty / unused
rm prefect_flow.py            # never used
# Keep templates/ dirs but populate them in v2

# 7. Old documentation that's now misleading
mv DOCUMENTATION.md docs/v1_DOCUMENTATION.md
mv FEATURES_AND_STATUS.md docs/v1_FEATURES_AND_STATUS.md
# CLAUDE.md will be replaced (Phase 2)
# ARCHITECTURE.md will be replaced (Phase 2)
# README.md will be replaced (Phase 2)

# 8. Remove deleted agents
rm agents/poem_agent.py
rm agents/lullaby_agent.py
rm agents/instagram_agent.py
```

### EC2 cleanup (run on Lightsail instance)

```bash
# SSH into Lightsail, run as the bot user

# 1. Stop the bot first
sudo systemctl stop youtube-bot
sudo systemctl disable youtube-bot

# 2. Inventory what's there before deleting
df -h
du -sh ~/youtube_automation/output/* | sort -h | tail -20
du -sh ~/youtube_automation/data/* | sort -h | tail -10

# 3. Delete the 206 old run directories
cd ~/youtube_automation
rm -rf output/video_*
rm -rf output/shorts_*
rm -rf output/poem_*
rm -rf output/lullaby_*

# 4. Old logs
sudo journalctl --vacuum-time=7d
rm -rf ~/youtube_automation/logs/*.log.* 2>/dev/null
rm -rf /tmp/* 2>/dev/null

# 5. Pip + apt caches
pip cache purge
sudo apt-get clean
sudo apt-get autoremove -y

# 6. Old Python __pycache__
find ~/youtube_automation -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 7. Truncate SQLite DB (after archiving)
cp ~/youtube_automation/data/pipeline.db ~/pipeline_v1_archive_$(date +%Y%m%d).db
# DO NOT delete pipeline.db — it has the schema we'll reuse. Just archive a copy.

# 8. Verify free space
df -h
# Should now have plenty of headroom (target: < 60% used)

# 9. Install missing system deps for v2
sudo apt-get update
sudo apt-get install -y imagemagick ffmpeg
# Edit ImageMagick policy.xml to allow text rendering
sudo sed -i 's|<policy domain="path" rights="none" pattern="@\*"/>|<!-- &-->|' /etc/ImageMagick-6/policy.xml

# 10. Don't restart bot yet — wait until v2 code is deployed
```

### Database migration (preserve schema, archive data)

```bash
# Local
cd data
sqlite3 pipeline.db ".schema" > v1_schema_backup.sql
mv pipeline.db pipeline_v1_archive.db
# v2 will create a fresh pipeline.db with extended schema (new tables: approval_queue,
# quality_scores, competitor_videos, kill_switch_events, api_costs, learning_log)
```

---

## 10. MCPs & Connectors — what to add

Arpit already has Notion connector. Here's what else is worth adding for this project specifically.

### High-value additions

| MCP / Connector | Why | Setup effort |
|---|---|---|
| **GitHub MCP** | Direct repo operations from Claude Code (issue tracking for pivots, branch management) | 5 min |
| **Google Drive** | Backup approved-video archive, store weekly learning_log reports for cross-device access | 0 min (already available) |
| **Notion** (already have) | Topic backlog, competitor intel dashboard, idea inbox during 1-2h weekend sessions | Already done |
| **Filesystem MCP** (local + EC2) | Claude Code can directly inspect/edit Lightsail without manual SSH for routine tasks | 10 min |

### Skip these (not needed for this project)

- Slack — Telegram already covers notifications, don't double up
- Calendar — automation doesn't need scheduling beyond cron
- Gmail — existing notification_agent handles this
- Canva MCP — your `metadata_agent` Pillow thumbnails are fine; Canva is overkill for daily volume

### External APIs (not MCPs, but used directly)

| API | Library | Purpose |
|---|---|---|
| Telegram Bot | `python-telegram-bot` | approval_agent |
| YouTube Data v3 | existing | uploads, analytics, competitor intel |
| Sarvam Bulbul v3 | requests | TTS |
| Replicate FLUX schnell | `replicate` | image gen |
| HuggingFace Inference | requests | image gen (free tier) |
| OpenAI | `openai` | GPT-4o-mini for research/script/quality |

---

## 11. Success metrics — what to track

### Channel-level (in `data/learning_log/`)

- Subscribers (daily delta)
- Total watch hours (toward 4000 YPP requirement)
- Median CTR per cluster
- Median average view duration per format (long vs short)
- New vs returning viewer ratio (binge signal)

### Pipeline-level (in `api_costs` + `kill_switch_events`)

- Daily API spend (vs budget)
- Quality_agent approve/flag/reject ratio (target: 70/20/10)
- Approval gate human-rejection ratio (target: < 15% — if higher, quality_agent rubric needs tuning)
- Time from generation to approval (median target: < 4h)
- Days with no upload (target: < 2/month)

### Leading indicators (week-over-week)

- Average first-24h CTR trending up?
- Average retention curve flattening (less drop-off at 30s)?
- Subscriber-from-video ratio improving?

If any of these stagnate for 3 weeks, learning_agent should be flagging it. If it's not, the rubric needs adjustment.

---

## 12. What this plan does NOT promise

- ❌ "1M subscribers in 6 months"
- ❌ "₹50K/month from YouTube ads"
- ❌ "Fully autonomous, no human ever"
- ❌ "AI slop will work if you just diversify topics"

What it promises:
- ✅ A real shot at YPP in 6-9 months (35-45% probability with disciplined execution)
- ✅ A reusable agentic content system that can pivot to a 2nd/3rd channel if this one stalls
- ✅ Cost-bounded, restart-safe, kill-switched operations
- ✅ ~5-10 min/day of actual time commitment, weekend deep-dive optional
- ✅ A genuine moat from Arpit's domain depth that no other automated channel can copy

---

## 13. Decision log (living section)

| Date | Decision | Reasoning |
|---|---|---|
| 2026-05 | Abandon v1 channel, new niche | AI slop classification + kids niche regulatory pressure |
| 2026-05 | Sarvam Bulbul v3 over edge-tts | Pricing confirmed (₹30/10K chars = ~₹6-8/long-form), quality justifies it |
| 2026-05 | Replicate FLUX over HuggingFace for long-form | Quality differentiator on monetization-driving content; HF free tier still used for shorts |
| 2026-05 | AWS Lightsail kept | User preference; cost (~₹425/mo) acceptable within budget |
| 2026-05 | Telegram approval gate over web UI | Mobile-first, free, brain-dead simple, no UI to maintain |
| 2026-05 | Daily cadence (not weekly) | User preference; spreads the cognitive load to 5-10 min instead of 35-70 min weekly batch |

---

## Appendix A: File-level migration map

### v1 → v2 file changes

```
KEEP UNCHANGED:
  agents/caption_agent.py
  agents/metadata_agent.py
  agents/video_agent.py
  agents/analytics_agent.py
  agents/playlist_agent.py
  agents/ab_agent.py
  agents/notification_agent.py
  agents/rate_limiter.py
  agents/db.py (extend schema, don't recreate)
  services/trend_service.py
  services/cluster_service.py
  services/series_service.py
  services/analytics_service.py
  services/thumbnail_ab_service.py
  services/schedule_optimizer_service.py
  services/retention_service.py

REFACTOR:
  agents/topic_agent.py              # new clusters, weights from learning_agent
  agents/script_agent.py             # input is now research_agent output
  agents/asset_agent.py              # default Sarvam + Replicate FLUX, drop kids defaults
  agents/animation_agent.py          # Ken Burns only, drop Kling/Veo
  agents/upload_agent.py             # queued mode, triggered by approval not cron
  main.py                            # new orchestration: candidate → queue, no auto-upload

ADD:
  agents/research_agent.py
  agents/quality_agent.py
  agents/approval_agent.py
  agents/learning_agent.py
  agents/competitor_agent.py
  agents/kill_switch_agent.py
  agents/budget_guard.py
  services/approval_queue_service.py
  config/quality_rubric.yaml
  config/budget.yaml
  config/competitors.yaml

DELETE:
  agents/poem_agent.py
  agents/lullaby_agent.py
  agents/instagram_agent.py
  prefect_flow.py
```

### New SQLite tables (extend existing schema)

```sql
CREATE TABLE approval_queue (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  candidate_path TEXT,
  quality_score INTEGER,
  status TEXT DEFAULT 'pending',  -- pending|approved|rejected|timeout
  telegram_message_id INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  decided_at DATETIME,
  decision_reason TEXT
);

CREATE TABLE quality_scores (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  total INTEGER, hook INTEGER, narrative INTEGER,
  specificity INTEGER, hinglish INTEGER,
  verdict TEXT, flags TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE competitor_videos (
  id INTEGER PRIMARY KEY,
  channel_id TEXT, channel_name TEXT,
  video_id TEXT UNIQUE, title TEXT, view_count INTEGER,
  view_to_sub_ratio REAL, duration_seconds INTEGER,
  published_at DATETIME, observed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE kill_switch_events (
  id INTEGER PRIMARY KEY,
  trigger_type TEXT, severity TEXT,
  metrics_snapshot TEXT,  -- JSON
  resumed_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE api_costs (
  id INTEGER PRIMARY KEY,
  provider TEXT, endpoint TEXT,
  cost_inr REAL, run_id TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE learning_log (
  id INTEGER PRIMARY KEY,
  log_date DATE, summary_md TEXT,
  weight_changes TEXT,  -- JSON
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

*End of plan. This document is the source of truth — when in doubt, refer here.*
