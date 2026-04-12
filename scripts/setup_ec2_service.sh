#!/bin/bash
# Setup script for EC2 — installs youtube-bot as a systemd service
# Run once on EC2: bash ~/youtube_automation/scripts/setup_ec2_service.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== YouTube Bot: systemd service setup ==="
echo "Project dir: $PROJECT_DIR"

# 1. Set timezone to IST (scheduler times are IST-based)
echo ""
echo "[1/5] Setting timezone to Asia/Kolkata (IST)..."
sudo timedatectl set-timezone Asia/Kolkata
echo "  Timezone: $(timedatectl show -p Timezone --value)"

# 2. Kill any old tmux-based scheduler
echo ""
echo "[2/5] Stopping any old scheduler processes..."
pkill -f "python main.py --schedule" 2>/dev/null && echo "  Killed old scheduler process" || echo "  No old scheduler running"
tmux kill-session -t yt 2>/dev/null && echo "  Killed old tmux session 'yt'" || echo "  No tmux session 'yt' found"

# 3. Initialize DB (creates v2 tables if they don't exist)
echo ""
echo "[3/5] Initializing database (creating any new tables)..."
cd "$PROJECT_DIR"
source venv/bin/activate
python -c "from agents.db import init_db; init_db(); print('  DB initialized successfully')"

# 4. Install systemd service
echo ""
echo "[4/5] Installing systemd service..."
sudo cp "$SCRIPT_DIR/youtube-bot.service" /etc/systemd/system/youtube-bot.service
sudo systemctl daemon-reload
sudo systemctl enable youtube-bot
echo "  Service installed and enabled (will auto-start on boot)"

# 5. Start the service
echo ""
echo "[5/5] Starting youtube-bot service..."
sudo systemctl start youtube-bot
sleep 2

# Verify
if sudo systemctl is-active --quiet youtube-bot; then
    echo ""
    echo "=== SUCCESS ==="
    echo "youtube-bot is running!"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status youtube-bot     # check status"
    echo "  journalctl -u youtube-bot -f           # live logs"
    echo "  journalctl -u youtube-bot --since today # today's logs"
    echo "  sudo systemctl restart youtube-bot     # manual restart"
    echo "  sudo systemctl stop youtube-bot        # stop"
else
    echo ""
    echo "=== FAILED ==="
    echo "Service did not start. Check logs:"
    echo "  journalctl -u youtube-bot -n 30"
    exit 1
fi

# 6. Allow ubuntu user to restart the service without sudo password (needed by deploy.yml)
SUDOERS_LINE="ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart youtube-bot, /bin/systemctl stop youtube-bot, /bin/systemctl start youtube-bot, /bin/systemctl status youtube-bot"
SUDOERS_FILE="/etc/sudoers.d/youtube-bot"
if [ ! -f "$SUDOERS_FILE" ]; then
    echo ""
    echo "[Bonus] Adding passwordless sudo for systemctl youtube-bot commands..."
    echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 0440 "$SUDOERS_FILE"
    echo "  Done — deploy workflow can now restart the service without password"
fi
