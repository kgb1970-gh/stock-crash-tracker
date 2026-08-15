"""Emails a summary of today's new short/sell signals. No-op if the NOTIFY_*
env vars aren't set, so this stays silent for local runs and only activates in
CI once the secrets are configured.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.environ.get("NOTIFY_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("NOTIFY_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("NOTIFY_SMTP_USER")
SMTP_PASSWORD = os.environ.get("NOTIFY_SMTP_PASSWORD")
EMAIL_TO = os.environ.get("NOTIFY_EMAIL_TO")


def send(short_signal: list[str], sold: list[str]) -> None:
    if not (SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        return  # not configured -- silent no-op, keeps local runs working unchanged
    if not short_signal and not sold:
        return  # nothing new today, don't email

    lines = []
    if short_signal:
        lines.append("SHORT: " + ", ".join(short_signal))
    if sold:
        lines.append("SELL: " + ", ".join(sold))
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = "Stock tracker: new signals today"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        print(f"[notify] emailed: {body!r}")
