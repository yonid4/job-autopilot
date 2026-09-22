"""Push the good news to Discord.

Posts through an incoming webhook, so no bot process and no gateway connection
— just a URL held in DISCORD_WEBHOOK_URL. With no URL configured the module
quietly no-ops, which keeps the rest of the pipeline usable before the channel
exists.
"""

# Standard library
import os
import time

# Third-party
from dotenv import load_dotenv
import requests

# Local
from email_model import EmailCategory, EmailMessage, EmailVerdict
from job_model import ApplicationRow

load_dotenv()

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

# Optional "<@123...>" or "@here" prepended to the message so it actually
# pushes to your phone instead of sitting silently in the channel.
MENTION = os.getenv("DISCORD_MENTION", "").strip()

_COLORS = {
    EmailCategory.ASSESSMENT: 0x5865F2,   # blurple
    EmailCategory.INTERVIEW: 0x57F287,    # green
    EmailCategory.OFFER: 0xFEE75C,        # gold
    EmailCategory.REJECTION: 0xED4245,    # red
}

_HEADLINES = {
    EmailCategory.ASSESSMENT: "Online assessment invite",
    EmailCategory.INTERVIEW: "Interview invite",
    EmailCategory.OFFER: "Offer",
    EmailCategory.REJECTION: "Rejection",
    EmailCategory.ACKNOWLEDGEMENT: "Application received",
}

_TIMEOUT = 15
_MAX_ATTEMPTS = 3
# Discord allows roughly 5 webhook posts per 2 seconds; stay well under it.
_SEND_SPACING_SECONDS = 0.5

_EMBED_DESCRIPTION_LIMIT = 4000
_FIELD_VALUE_LIMIT = 1024


def is_configured() -> bool:
    return bool(WEBHOOK_URL)


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_embed(message: EmailMessage, verdict: EmailVerdict, row: ApplicationRow | None) -> dict:
    """Discord embed describing one classified email."""
    headline = _HEADLINES.get(verdict.category, verdict.category.value.title())
    company = (row.company if row else "") or "Unknown company"
    role = (row.role if row else "") or "Unknown role"

    fields = [
        {"name": "Role", "value": _truncate(role, _FIELD_VALUE_LIMIT), "inline": True},
        {"name": "From", "value": _truncate(message.sender or "unknown sender", _FIELD_VALUE_LIMIT), "inline": True},
        {"name": "Subject", "value": _truncate(message.subject or "(no subject)", _FIELD_VALUE_LIMIT), "inline": False},
    ]
    if row:
        fields.append({
            "name": "Tracked at",
            "value": f"{row.tab} · row {row.row}",
            "inline": True,
        })
    else:
        fields.append({
            "name": "Tracked at",
            "value": "No matching row — update the sheet by hand",
            "inline": True,
        })

    embed = {
        "title": _truncate(f"{headline} — {company}", 256),
        "description": _truncate(verdict.summary or message.subject, _EMBED_DESCRIPTION_LIMIT),
        "color": _COLORS.get(verdict.category, 0x99AAB5),
        "fields": fields,
        "footer": {"text": f"job-autopilot · {verdict.source} · confidence {verdict.confidence:.0%}"},
    }
    if row and row.link:
        embed["url"] = row.link
    if message.received_at:
        embed["timestamp"] = message.received_at.isoformat()
    return embed


def _post(payload: dict) -> bool:
    """POST one webhook payload, honouring Discord's rate-limit backoff."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(WEBHOOK_URL, json=payload, timeout=_TIMEOUT)
        except requests.RequestException as e:
            print(f"[discord] request failed ({e}) — attempt {attempt}/{_MAX_ATTEMPTS}")
            time.sleep(2 ** attempt)
            continue

        if response.status_code == 429:
            retry_after = _TIMEOUT
            try:
                retry_after = float(response.json().get("retry_after", 1))
            except ValueError:
                pass
            print(f"[discord] rate limited — waiting {retry_after:.1f}s")
            time.sleep(min(retry_after, _TIMEOUT))
            continue

        if response.ok:
            return True

        print(f"[discord] webhook returned {response.status_code}: {response.text[:200]}")
        # 4xx other than 429 means a bad URL or payload; retrying won't help.
        if 400 <= response.status_code < 500:
            return False
        time.sleep(2 ** attempt)

    return False


def notify(items: list[tuple[EmailMessage, EmailVerdict, ApplicationRow | None]]) -> int:
    """Send one message per item. Returns how many made it through."""
    if not items:
        return 0
    if not is_configured():
        print(f"[discord] DISCORD_WEBHOOK_URL not set — skipping {len(items)} notification(s)")
        return 0

    sent = 0
    for index, (message, verdict, row) in enumerate(items):
        payload = {"embeds": [build_embed(message, verdict, row)]}
        if MENTION:
            payload["content"] = MENTION
            payload["allowed_mentions"] = {"parse": ["users", "everyone"]}
        if _post(payload):
            sent += 1
        if index < len(items) - 1:
            time.sleep(_SEND_SPACING_SECONDS)

    print(f"[discord] sent {sent}/{len(items)} notification(s)")
    return sent
