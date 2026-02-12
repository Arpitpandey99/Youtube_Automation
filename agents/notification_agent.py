"""Notification agent — sends email summary after each pipeline run.

Two providers supported:
  - "gmail"  : Gmail SMTP with App Password (requires 2-Step Verification)
  - "resend" : Resend.com API (free, no 2FA needed — sign up at resend.com)
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _build_body(run_summary: dict) -> tuple:
    """Build subject and body text from run summary."""
    timestamp = run_summary.get("timestamp", "")
    subject = f"[YouTube Bot] Run Complete — {timestamp}"

    lines = [f"Pipeline run completed: {timestamp}", ""]
    for v in run_summary.get("videos", []):
        lang = v.get("language", "Unknown")
        lines.append(f"── {lang} " + "─" * (40 - len(lang)))
        video_url  = v.get("video_url")
        shorts_url = v.get("shorts_url")
        lines.append(f"  Full video : {video_url  if video_url  else 'FAILED / skipped'}")
        lines.append(f"  Shorts     : {shorts_url if shorts_url else 'FAILED / skipped'}")
        lines.append("")
    lines.append(f"Output dir : {run_summary.get('run_dir', 'N/A')}")
    return subject, "\n".join(lines)


def _send_via_gmail(email_cfg: dict, subject: str, body: str):
    """Send via Gmail SMTP (requires App Password — needs 2-Step Verification enabled)."""
    sender    = email_cfg["sender_email"]
    password  = email_cfg["sender_password"]
    recipient = email_cfg["recipient_email"]

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    print(f"  Email sent to {recipient} (via Gmail)")


def _send_via_resend(email_cfg: dict, subject: str, body: str):
    """Send via Resend.com API (free, no 2FA needed).

    Sign up at resend.com → get API key → add a verified sender domain or use
    the default onboarding@resend.dev as sender for testing.
    """
    import urllib.request
    import urllib.error
    import json

    api_key   = email_cfg["resend_api_key"]
    sender    = email_cfg.get("sender_email", "onboarding@resend.dev")
    recipient = email_cfg["recipient_email"]

    payload = json.dumps({
        "from": sender,
        "to": [recipient],
        "subject": subject,
        "text": body,
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    print(f"  Email sent to {recipient} (via Resend, id={result.get('id')})")


def send_run_summary(config: dict, run_summary: dict):
    """Send email summary with video links after a pipeline run."""
    email_cfg = config.get("notifications", {}).get("email", {})
    if not email_cfg.get("enabled", False):
        return

    provider = email_cfg.get("provider", "gmail")
    subject, body = _build_body(run_summary)

    try:
        if provider == "resend":
            _send_via_resend(email_cfg, subject, body)
        else:
            _send_via_gmail(email_cfg, subject, body)
    except Exception as e:
        print(f"  Warning: Email notification failed: {e}")
