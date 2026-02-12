# YouTube Kids Video Automation

Fully automated pipeline that generates and uploads kid-friendly YouTube videos (and Instagram Reels) in multiple languages using AI. Runs on AWS EC2 with twice-daily cron scheduling, GitHub Actions CI/CD, and Gmail email notifications after every run.

> Deployed on AWS EC2 t4g.small (ARM64) — auto-deploys on every push to `main`.

---

## Features

| Feature | Description |
|---------|-------------|
| AI topic selection | GPT-4o-mini picks fresh, age-appropriate topics; avoids duplicates via history tracking |
| Script generation | 6-scene narrated scripts in English + Hindi |
| AI image generation | Replicate (Flux Schnell) or OpenAI DALL-E per scene |
| Ken Burns animation | Smooth zoom/pan effects on each image — no paid animation API needed |
| TTS voice-over | OpenAI TTS (`nova` voice) or edge-tts; auto-synced to video |
| Auto subtitles | Burned-in yellow captions using MoviePy |
| Background music | Fades in/out from `data/music/` folder |
| YouTube upload | Full 16:9 video + vertical 9:16 Shorts; sets title, description, tags, thumbnail |
| Instagram Reels | Optional — posts Shorts clip via Meta Graph API |
| Email summary | Gmail SMTP notification with YouTube links sent after each run |
| Scheduler | Built-in cron via `schedule` library or external Linux crontab |
| CI/CD | GitHub Actions auto-deploys to EC2 on every push to `main` |
| A/B testing | Optional title/hook variant testing (see `agents/ab_agent.py`) |
| Analytics | Optional YouTube Analytics feedback loop (see `agents/analytics_agent.py`) |
| Playlists | Optional auto-playlist creation (see `agents/playlist_agent.py`) |

---

## Quick Start (Local)

### Prerequisites

```bash
# macOS
brew install ffmpeg

# Ubuntu/EC2
sudo apt install ffmpeg -y

pip install -r requirements.txt
```

### Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml — fill in your API keys (see Configuration section below)
```

### Run

```bash
# Animated pipeline (Ken Burns effects) — recommended
python main.py --animated

# Regular pipeline (static images)
python main.py

# Test without uploading to YouTube
python main.py --animated --no-upload

# Run the scheduler (twice-daily based on config.yaml schedule)
python main.py --schedule --animated
```

---

## Project Structure

```
Youtube_Automation/
├── main.py                        # Entry point — CLI flags, orchestrator
├── config.yaml                    # Your config (API keys) — NOT committed
├── config.example.yaml            # Template with placeholders — committed
├── requirements.txt
├── ARCHITECTURE.md                # Full architecture + deployment guide
│
├── agents/
│   ├── topic_agent.py             # AI topic selection + deduplication
│   ├── script_agent.py            # GPT script generation (6 scenes)
│   ├── asset_agent.py             # Image generation (Replicate/OpenAI/Pexels)
│   ├── animation_agent.py         # Ken Burns zoom/pan effects (MoviePy)
│   ├── video_agent.py             # Video assembly (MoviePy) — regular + animated
│   ├── metadata_agent.py          # Title, description, tags generation
│   ├── upload_agent.py            # YouTube Data API v3 upload
│   ├── caption_agent.py           # Auto-subtitle generation
│   ├── instagram_agent.py         # Instagram Reels via Meta Graph API
│   ├── notification_agent.py      # Gmail / Resend email summary
│   ├── ab_agent.py                # A/B testing (optional)
│   ├── analytics_agent.py         # YouTube Analytics (optional)
│   ├── playlist_agent.py          # Auto-playlist creation (optional)
│   ├── rate_limiter.py            # API rate limiting
│   └── db.py                      # SQLite pipeline state tracking
│
├── data/
│   ├── topics_history.json        # Used topics (prevents repeats)
│   └── music/                     # Background music files (not committed)
│
├── output/                        # Generated videos (not committed)
│   └── run_YYYYMMDD_HHMMSS/
│       ├── en/                    # English video files
│       └── hi/                    # Hindi video files
│
├── logs/                          # Pipeline run logs (EC2)
└── .github/
    └── workflows/
        └── deploy.yml             # GitHub Actions → EC2 auto-deploy
```

---

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your keys:

```yaml
openai:
  api_key: "sk-..."          # Required: OpenAI API key
  model: "gpt-4o-mini"

image_provider: "replicate"  # Options: replicate, openai, pexels

replicate:
  api_token: "r8_..."        # Required if using Replicate

tts:
  provider: "openai"         # Options: openai, edge-tts, elevenlabs
  openai_voice: "nova"

youtube:
  client_secrets_file: "client_secrets.json"
  token_file: "token.json"
  privacy_status: "public"
  made_for_kids: true

notifications:
  email:
    enabled: true
    provider: "gmail"
    sender_email: "you@gmail.com"
    sender_password: "xxxx xxxx xxxx xxxx"   # Gmail App Password (16 chars)
    recipient_email: "you@gmail.com"

schedule:
  videos_per_week: 14
  upload_days: [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
  upload_time: "21:00"        # Server timezone = Asia/Kolkata
```

**Gmail App Password**: Google Account → Security → 2-Step Verification → App Passwords → Generate.

**YouTube OAuth**: Download `client_secrets.json` from Google Cloud Console (YouTube Data API v3 enabled). Run once locally to generate `token.json`.

---

## Animated Pipeline (Recommended)

The `--animated` flag activates the Ken Burns pipeline:

1. Topics → Scripts → AI images (same as regular)
2. Each image gets a random Ken Burns effect: `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `combined`
3. TTS audio is generated and timed to each scene
4. Subtitles are burned in
5. Background music fades in/out
6. Full 16:9 video + vertical 9:16 Shorts assembled
7. Uploaded to YouTube
8. Email summary sent with video links

Typical run time: 30–90 minutes depending on image provider and video length.

---

## Deployment on AWS EC2

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full deployment guide including:

- EC2 instance setup (t4g.small ARM64, Ubuntu 24.04, ~$5/month)
- Linux cron for twice-daily runs (9 AM + 9 PM IST)
- GitHub Actions CI/CD (auto-deploy on `git push`)
- SSH key setup for GitHub Actions
- Secret file upload via `scp`

### Quick EC2 Setup

```bash
# 1. Install dependencies
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg git
sudo timedatectl set-timezone Asia/Kolkata

# 2. Clone and install
git clone https://github.com/Arpitpandey99/Youtube_Automation.git ~/youtube_automation
cd ~/youtube_automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p logs

# 3. Upload secrets from your Mac (run locally, not on EC2)
scp -i ~/Downloads/youtube-automation.pem config.yaml ubuntu@YOUR_EC2_IP:~/youtube_automation/
scp -i ~/Downloads/youtube-automation.pem client_secrets.json ubuntu@YOUR_EC2_IP:~/youtube_automation/
scp -i ~/Downloads/youtube-automation.pem token.json ubuntu@YOUR_EC2_IP:~/youtube_automation/

# 4. Add cron jobs
crontab -e
# Add:
# 0  9 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --animated >> logs/run.log 2>&1
# 0 21 * * * cd $HOME/youtube_automation && ./venv/bin/python main.py --animated >> logs/run.log 2>&1

# 5. Test
python main.py --animated --no-upload
```

---

## CI/CD (GitHub Actions)

Every push to `main` automatically deploys to EC2.

**Required GitHub Secrets** (repo → Settings → Secrets → Actions):

| Secret | Value |
|--------|-------|
| `EC2_HOST` | Your EC2 Elastic IP |
| `EC2_SSH_KEY` | Private key from EC2 deploy key (`~/.ssh/github_deploy`) |

**Generate EC2 deploy key:**
```bash
# On EC2:
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy    # paste this as EC2_SSH_KEY in GitHub
```

---

## Cost Estimate

| Item | Cost/month |
|------|-----------|
| t4g.small Spot Instance | ~$3–4 |
| 20GB gp3 EBS volume | $1.60 |
| Data transfer | ~$0.50 |
| **Total** | **~$5–6** |

---

## Tech Stack

- **AI**: OpenAI GPT-4o-mini (scripts/metadata), OpenAI TTS (voice-over), Replicate Flux Schnell (images)
- **Video**: MoviePy, FFmpeg
- **Upload**: YouTube Data API v3, Meta Graph API (Instagram)
- **Scheduler**: Python `schedule` library / Linux cron
- **Database**: SQLite (pipeline state)
- **Infra**: AWS EC2 t4g.small (ARM64 Graviton2), GitHub Actions

---

## License

MIT
