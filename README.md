# YouTube Automation v2 — Hinglish Tech Explainers

Automated pipeline for a faceless Hinglish "how things work" YouTube channel. Generates one video candidate per day, gates every upload through a Telegram approval bot, and closes the analytics-to-strategy feedback loop automatically.

> **5-10 min/day** — get a Telegram notification, watch a 30s preview, tap Publish or Reject. That's it.

---

## What it does

1. **Picks a topic** from weighted tech clusters (UPI, Aadhaar, IRCTC, 5G, FASTag, etc.)
2. **Researches it** with web search + GPT synthesis → verified fact sheet
3. **Writes a Hinglish script** with narrative arc (hook → mechanism → resolution)
4. **Quality-gates the script** via LLM-as-judge (rejects below threshold, retries up to 3x)
5. **Generates assets** — Sarvam Bulbul v3 voiceover + Replicate FLUX images
6. **Assembles the video** — Ken Burns animation + subtitles + background music
7. **Sends to Telegram** — preview clip, 3 thumbnails, 3 titles, one-tap approval
8. **Uploads on approval** — scheduled to 19:00-20:30 IST peak window
9. **Learns from analytics** — updates cluster weights, kills failing patterns, proposes new topics

Nothing publishes without a human tap. 24h no-response = auto-reject.

---

## Quick Start

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # fill in API keys

# Download background music (once)
python main.py --generate-music

# Run the daily pipeline (produces a candidate, sends to Telegram)
python main.py --content-loop

# Start the Telegram approval bot
python main.py --approval-bot

# Publish approved candidates
python main.py --publish-approved
```

---

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for full details. See [`REVAMP_PLAN.md`](REVAMP_PLAN.md) for design decisions.

**Four loops:**

| Loop | Schedule | What it does |
|---|---|---|
| Content | Daily 06:00 | topic → research → script → quality → assets → video → Telegram queue |
| Publish | Every 15 min | Check queue, upload approved candidates |
| Feedback | Every 6h | analytics → learning → kill-switch check |
| Strategy | Weekly Sunday | competitor → trends → clusters → series |

**23 agents** orchestrated through `main.py`. Key additions over v1:

- `research_agent` — web research for factual accuracy
- `quality_agent` — LLM-as-judge script scoring (rejects AI slop)
- `approval_agent` — Telegram bot with one-tap publish/reject
- `learning_agent` — analytics → strategy feedback loop
- `competitor_agent` — weekly Hinglish tech channel intel
- `kill_switch_agent` — auto-pause on 6 red-flag triggers

---

## Cost

~INR 1259/month steady-state. Hard ceiling: INR 1500/month enforced by `budget_guard.py`.

| Provider | Cap (INR/month) |
|---|---|
| OpenAI (GPT-4o-mini) | 500 |
| Sarvam (TTS) | 400 |
| Replicate (images) | 700 |
| HuggingFace | 0 (free) |
| AWS Lightsail | 425 |

---

## Production (Lightsail)

```bash
# Cron schedule
0 6 * * *    --content-loop
0 */6 * * *  --feedback-loop
0 6 * * 0    --strategy-loop
*/15 * * * * --publish-approved

# Systemd service
v2-approval-bot.service  # long-running Telegram bot
```

---

## v1 Archive

The v1 kids-content channel (Funzooon, 206 videos, 14 subs) is archived on the `v1-archive` branch. See `docs/v1_DOCUMENTATION.md` and `docs/v1_FEATURES_AND_STATUS.md` for historical reference.

---

## License

MIT
