"""
Approval Agent — Telegram bot for daily candidate approval.

Delivers video candidates to Arpit's phone with one-tap actions.
Every video MUST pass through this gate before publishing.

Workflow:
    1. After video assembly, send Telegram message with:
       - 30-second preview clip (lower res)
       - 3 thumbnail variants (inline image grid)
       - 3 title variants
       - Quality score breakdown
       - Inline keyboard: Publish | Regen Hook | New Thumbnail | Reject
    2. Listen for callback via long-polling
    3. On approve → write to approval_queue, trigger upload
    4. On reject → log reason, mark topic for cooldown
    5. 24h timeout = auto-reject (never auto-publish)

Commands:
    /resume  — clear pipeline_paused flag (used by kill_switch)
    /status  — print today's pipeline state
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from services.approval_queue_service import (
    enqueue,
    get_approved,
    get_pending,
    mark_approved,
    mark_rejected,
    process_timeouts,
    update_telegram_msg_id,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_STATE_PATH = os.path.join(BASE_DIR, "data", "system_state.json")

# Callback data prefixes
CB_PUBLISH = "approve:"
CB_REGEN_HOOK = "regen_hook:"
CB_NEW_THUMB = "new_thumb:"
CB_REJECT = "reject:"


def _read_system_state() -> dict:
    """Read the system state file."""
    if not os.path.exists(SYSTEM_STATE_PATH):
        return {"pipeline_paused": False}
    with open(SYSTEM_STATE_PATH) as f:
        return json.load(f)


def _write_system_state(state: dict) -> None:
    """Write the system state file."""
    os.makedirs(os.path.dirname(SYSTEM_STATE_PATH), exist_ok=True)
    with open(SYSTEM_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _trim_preview(video_path: str, max_seconds: int = 30) -> str:
    """Trim a video to a 30-second preview clip using ffmpeg.

    Returns the path to the trimmed file (or original if already short enough
    or ffmpeg fails).
    """
    try:
        # Get video duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip())
        if duration <= max_seconds:
            return video_path

        # Trim to max_seconds with lower quality for bandwidth
        preview_path = os.path.join(
            tempfile.gettempdir(),
            f"preview_{os.path.basename(video_path)}"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-t", str(max_seconds),
             "-vf", "scale=640:-2",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
             "-c:a", "aac", "-b:a", "64k",
             preview_path],
            capture_output=True, timeout=60,
        )
        if os.path.exists(preview_path) and os.path.getsize(preview_path) > 0:
            return preview_path
    except Exception as e:
        logger.warning("Preview trim failed: %s, using original", e)

    return video_path


def _format_quality_text(quality_score: dict) -> str:
    """Format quality score into a readable Telegram message."""
    total = quality_score.get("total", 0)
    verdict = quality_score.get("verdict", "unknown")
    verdict_emoji = {"approve": "✅", "flag_for_review": "⚠️", "reject": "❌"}.get(verdict, "❓")

    text = (
        f"📊 *Quality Score: {total}/100* {verdict_emoji}\n"
        f"  Hook: {quality_score.get('hook', 0)}/25\n"
        f"  Narrative: {quality_score.get('narrative', 0)}/25\n"
        f"  Specificity: {quality_score.get('specificity', 0)}/25\n"
        f"  Hinglish: {quality_score.get('hinglish', 0)}/25\n"
    )

    flags = quality_score.get("flags", [])
    if flags:
        text += f"\n⚠️ *Flags:* {', '.join(flags)}"

    return text


class ApprovalBot:
    """Telegram bot wrapper for the approval gate."""

    def __init__(self, config: dict) -> None:
        """Initialize the approval bot from config."""
        self.config = config
        tg = config.get("telegram", {})
        self.bot_token: str = tg.get("bot_token", "")
        self.chat_id: str = str(tg.get("chat_id", ""))

        if not self.bot_token:
            raise ValueError("telegram.bot_token not set in config.yaml")
        if not self.chat_id:
            raise ValueError("telegram.chat_id not set in config.yaml")

        self.app: Application | None = None

    async def send_candidate(
        self,
        run_id: str,
        video_path: str,
        thumbnails: list[str],
        titles: list[str],
        quality_score: dict,
    ) -> int | None:
        """Send a video candidate to Telegram for approval.

        Returns the Telegram message_id of the keyboard message.
        """
        bot = Bot(token=self.bot_token)

        # 1. Send preview clip
        preview_path = _trim_preview(video_path)
        try:
            with open(preview_path, "rb") as vf:
                await bot.send_video(
                    chat_id=self.chat_id,
                    video=vf,
                    caption=f"🎬 *New candidate:* `{run_id}`",
                    parse_mode="Markdown",
                    read_timeout=120,
                    write_timeout=120,
                )
        except Exception as e:
            logger.warning("Failed to send video preview: %s", e)
            await bot.send_message(
                chat_id=self.chat_id,
                text=f"🎬 *New candidate:* `{run_id}`\n_(video preview failed: {e})_",
                parse_mode="Markdown",
            )

        # 2. Send thumbnails as media group (up to 3)
        valid_thumbs = [t for t in thumbnails if os.path.exists(t)]
        if valid_thumbs:
            media = []
            for i, thumb_path in enumerate(valid_thumbs[:3]):
                with open(thumb_path, "rb") as _:
                    pass  # Validate file exists and is readable
                caption = f"Thumbnail {i + 1}" if i == 0 else ""
                media.append(InputMediaPhoto(
                    media=open(thumb_path, "rb"),
                    caption=caption,
                ))
            try:
                await bot.send_media_group(chat_id=self.chat_id, media=media)
            except Exception as e:
                logger.warning("Failed to send thumbnails: %s", e)
            finally:
                for m in media:
                    try:
                        m.media.close()
                    except Exception:
                        pass

        # 3. Build title options + quality score text
        titles_text = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(titles[:3]))
        quality_text = _format_quality_text(quality_score)

        message_text = (
            f"📋 *Title options:*\n{titles_text}\n\n"
            f"{quality_text}\n\n"
            f"_Run ID: `{run_id}`_"
        )

        # 4. Inline keyboard
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Publish", callback_data=f"{CB_PUBLISH}{run_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"{CB_REJECT}{run_id}"),
            ],
            [
                InlineKeyboardButton("🔄 Regen Hook", callback_data=f"{CB_REGEN_HOOK}{run_id}"),
                InlineKeyboardButton("🎨 New Thumbnail", callback_data=f"{CB_NEW_THUMB}{run_id}"),
            ],
        ])

        msg = await bot.send_message(
            chat_id=self.chat_id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        # Update the queue entry with the telegram message ID
        update_telegram_msg_id(run_id, msg.message_id)

        return msg.message_id

    def _build_app(self) -> Application:
        """Build the telegram.ext.Application with handlers."""
        app = Application.builder().token(self.bot_token).build()

        # Callback handler for inline keyboard buttons
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Command handlers
        app.add_handler(CommandHandler("resume", self._handle_resume))
        app.add_handler(CommandHandler("status", self._handle_status))
        app.add_handler(CommandHandler("start", self._handle_start))

        return app

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button press."""
        query = update.callback_query
        await query.answer()

        data = query.data or ""

        if data.startswith(CB_PUBLISH):
            run_id = data[len(CB_PUBLISH):]
            mark_approved(run_id, "user_approved_via_telegram")
            await query.edit_message_text(
                text=f"✅ *APPROVED:* `{run_id}`\n\n"
                     f"Will be uploaded in the next publish cycle (19:00-20:30 IST).",
                parse_mode="Markdown",
            )
            logger.info("Approved: %s", run_id)

        elif data.startswith(CB_REJECT):
            run_id = data[len(CB_REJECT):]
            mark_rejected(run_id, "user_rejected_via_telegram")
            await query.edit_message_text(
                text=f"❌ *REJECTED:* `{run_id}`\n\nTopic cooled down. Pipeline continues tomorrow.",
                parse_mode="Markdown",
            )
            logger.info("Rejected: %s", run_id)

        elif data.startswith(CB_REGEN_HOOK):
            run_id = data[len(CB_REGEN_HOOK):]
            # Mark as rejected with regen reason — content-loop will pick this up
            mark_rejected(run_id, "regen_hook_requested")
            await query.edit_message_text(
                text=f"🔄 *REGEN HOOK:* `{run_id}`\n\n"
                     f"Marked for hook regeneration. Run `--content-loop` again to retry.",
                parse_mode="Markdown",
            )
            logger.info("Regen hook requested: %s", run_id)

        elif data.startswith(CB_NEW_THUMB):
            run_id = data[len(CB_NEW_THUMB):]
            mark_rejected(run_id, "new_thumbnail_requested")
            await query.edit_message_text(
                text=f"🎨 *NEW THUMBNAIL:* `{run_id}`\n\n"
                     f"Marked for thumbnail regeneration. Run `--content-loop` again to retry.",
                parse_mode="Markdown",
            )
            logger.info("New thumbnail requested: %s", run_id)

    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resume command — clear pipeline_paused flag."""
        state = _read_system_state()
        was_paused = state.get("pipeline_paused", False)
        state["pipeline_paused"] = False
        state["resumed_at"] = datetime.now().isoformat()
        _write_system_state(state)

        if was_paused:
            await update.message.reply_text(
                "▶️ Pipeline *resumed*. Content loop will run at next scheduled time.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "ℹ️ Pipeline was not paused. All systems normal.",
                parse_mode="Markdown",
            )

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command — print today's pipeline state."""
        state = _read_system_state()
        paused = state.get("pipeline_paused", False)
        paused_text = "⏸️ PAUSED" if paused else "▶️ Running"

        pending = get_pending()
        approved = get_approved()

        # Get today's budget spend
        try:
            from agents.budget_guard import get_all_monthly_spend
            spend = get_all_monthly_spend()
            spend_lines = "\n".join(f"  {p}: ₹{v:.2f}" for p, v in spend.items()) or "  No spend this month"
        except Exception:
            spend_lines = "  (unavailable)"

        text = (
            f"📊 *Pipeline Status*\n\n"
            f"State: {paused_text}\n"
            f"Pending approvals: {len(pending)}\n"
            f"Approved (awaiting upload): {len(approved)}\n\n"
            f"💰 *Monthly spend:*\n{spend_lines}\n\n"
            f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M IST')}_"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            "🤖 *YouTube Automation v2 — Approval Bot*\n\n"
            "Commands:\n"
            "  /status — pipeline state, pending count, budget\n"
            "  /resume — resume paused pipeline\n\n"
            "Candidates will appear here with approval buttons.",
            parse_mode="Markdown",
        )

    async def _timeout_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Periodic job: auto-reject timed-out candidates (>24h pending)."""
        count = process_timeouts(hours=24)
        if count > 0:
            try:
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"⏰ *Auto-rejected {count} candidate(s)* (24h timeout, no response).",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning("Failed to send timeout notification: %s", e)
            logger.info("Auto-rejected %d timed-out candidates", count)

    def run(self) -> None:
        """Start the bot in long-polling mode. Blocks forever."""
        self.app = self._build_app()

        # Schedule hourly timeout checks
        job_queue = self.app.job_queue
        if job_queue:
            job_queue.run_repeating(
                self._timeout_job,
                interval=3600,  # every hour
                first=60,       # first check after 1 minute
            )

        print(f"Approval bot started. Listening on chat_id={self.chat_id}")
        print("Commands: /status, /resume")
        print("Press Ctrl+C to stop.\n")

        self.app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["callback_query", "message"],
        )


# --- Standalone helper for sending candidates from the pipeline ---

async def send_candidate_standalone(
    config: dict,
    run_id: str,
    video_path: str,
    thumbnails: list[str],
    titles: list[str],
    quality_score: dict,
) -> int | None:
    """One-shot: send a candidate to Telegram without starting the full bot loop.

    Used by the content-loop pipeline to send a candidate after video assembly.
    Returns the Telegram message_id.
    """
    bot = ApprovalBot(config)
    return await bot.send_candidate(run_id, video_path, thumbnails, titles, quality_score)


def send_candidate_sync(
    config: dict,
    run_id: str,
    video_path: str,
    thumbnails: list[str],
    titles: list[str],
    quality_score: dict,
) -> int | None:
    """Synchronous wrapper for send_candidate_standalone.

    Safe to call from non-async pipeline code.
    """
    return asyncio.run(
        send_candidate_standalone(config, run_id, video_path, thumbnails, titles, quality_score)
    )
