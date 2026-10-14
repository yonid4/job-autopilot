"""Push the good news to Discord.

Posts through an incoming webhook, so no bot process and no gateway connection
— just the #notifications channel's URL, held in DISCORD_WEBHOOK_URL.
With no URL configured the module quietly no-ops, which keeps the rest of the
pipeline usable before the channel exists.
"""

# Standard library
import os
import time

# Third-party
from dotenv import load_dotenv
import requests

# Local
from email_model import EmailCategory, EmailMessage, EmailVerdict
from job_model import ApplicationRow, Job

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
    """Discord embed describing one classified email.

    Company and role come from the sheet row when there is one; otherwise from
    what the email itself says (Gemini reads that out), and only then "Unknown".
    The title links to the email, since replying to it is usually the next step.
    """
    headline = _HEADLINES.get(verdict.category, verdict.category.value.title())
    company = (row.company if row else "") or verdict.company or "Unknown company"
    role = (row.role if row else "") or verdict.role or "Unknown role"

    fields = [
        {"name": "Role", "value": _truncate(role, _FIELD_VALUE_LIMIT), "inline": True},
        {"name": "From", "value": _truncate(message.sender or "unknown sender", _FIELD_VALUE_LIMIT), "inline": True},
        {"name": "Subject", "value": _truncate(message.subject or "(no subject)", _FIELD_VALUE_LIMIT), "inline": False},
    ]

    links = []
    if message.web_link:
        links.append(f"[Open email]({message.web_link})")
    if row and row.link:
        links.append(f"[Job posting]({row.link})")
    if links:
        fields.append({"name": "Links", "value": " · ".join(links), "inline": False})

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
    if message.web_link:
        embed["url"] = message.web_link
    elif row and row.link:
        embed["url"] = row.link
    if message.received_at:
        embed["timestamp"] = message.received_at.isoformat()
    return embed


def _post(payload: dict, url: str = "") -> bool:
    """POST one webhook payload, honouring Discord's rate-limit backoff.

    Posts to `url`, or to DISCORD_WEBHOOK_URL when none is given."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url or WEBHOOK_URL, json=payload, timeout=_TIMEOUT)
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


# --- Job digests --------------------------------------------------------------
# Ported from faang_scraper's jobtracker/sink.py: new matches go out as embeds,
# batched into as few messages as Discord allows, with a heartbeat when a run
# finds nothing so a silent channel still proves the scraper ran.

# Discord caps a message at 10 embeds AND 6000 characters across all of them;
# a batch of wordy matches hits the character limit first, and Discord rejects
# the whole message when it's exceeded. The margin absorbs anything Discord
# counts that we don't model.
_EMBEDS_PER_MESSAGE = 10
_MESSAGE_CHARS_BUDGET = 6000 - 200
_JOB_DESC_LIMIT = 4096
_STRONG_SCORE = 90                  # matches the sheet's green highlight
_STRONG_COLOR = 0x2ECC71            # green
_MATCH_COLOR = 0xF1C40F             # yellow

_HEARTBEAT_CONTENT = "✅ LinkedIn scrape ran — 0 new matches."


def _job_header(n: int) -> str:
    return f"🎯 {n} new match{'' if n == 1 else 'es'} — apply within 48h"


def _embed_chars(embed: dict) -> int:
    """Characters Discord counts toward the per-message embed budget."""
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    )


def build_job_embed(job: Job) -> dict:
    """One matched job: title links to the posting, Gemini's notes below.

    The description is capped so even a single wordy embed always fits in a
    message on its own."""
    score = job.score if job.score is not None else 0
    fields = [
        {"name": "Company", "value": _truncate(job.company or "Unknown", _FIELD_VALUE_LIMIT), "inline": True},
        {"name": "Track", "value": job.track or "—", "inline": True},
        {"name": "Score", "value": f"{score}/100", "inline": True},
    ]
    title = _truncate(job.role or "Untitled role", 256)
    overhead = len(title) + sum(len(f["name"]) + len(f["value"]) for f in fields)
    desc_limit = max(0, min(_JOB_DESC_LIMIT, _MESSAGE_CHARS_BUDGET - overhead))
    embed = {
        "title": title,
        "color": _STRONG_COLOR if score >= _STRONG_SCORE else _MATCH_COLOR,
        "description": _truncate(job.notes or "", desc_limit) if desc_limit else "",
        "fields": fields,
    }
    if job.link:
        embed["url"] = job.link
    return embed


def build_job_messages(jobs: list[Job], note: str = "") -> list[dict]:
    """Webhook payloads for a run: a heartbeat when empty, else embeds chunked
    by both of Discord's message limits, with a header (and any note) on the
    first message."""
    suffix = f"\n{note}" if note else ""
    if not jobs:
        return [{"content": _HEARTBEAT_CONTENT + suffix}]

    messages: list[dict] = []
    chunk: list[dict] = []
    chunk_chars = 0
    for job in jobs:
        embed = build_job_embed(job)
        chars = _embed_chars(embed)
        if chunk and (len(chunk) >= _EMBEDS_PER_MESSAGE
                      or chunk_chars + chars > _MESSAGE_CHARS_BUDGET):
            messages.append({"embeds": chunk})
            chunk, chunk_chars = [], 0
        chunk.append(embed)
        chunk_chars += chars
    if chunk:
        messages.append({"embeds": chunk})

    messages[0]["content"] = _job_header(len(jobs)) + suffix
    return messages


def notify_jobs(jobs: list[Job], *, webhook_url: str, note: str = "") -> int:
    """Post matched jobs to `webhook_url`; a heartbeat when there are none.

    Never raises: the sheet is the system of record and Discord is a
    convenience on top, so a failed post is logged and skipped. Returns how
    many jobs actually reached Discord."""
    if not webhook_url:
        print(f"[discord] no job webhook set — skipping {len(jobs)} job notification(s)")
        return 0

    messages = build_job_messages(jobs, note=note)
    if MENTION:
        messages[0]["content"] = f"{MENTION} {messages[0]['content']}"
        messages[0]["allowed_mentions"] = {"parse": ["users", "everyone"]}

    delivered = 0
    for index, payload in enumerate(messages):
        if index > 0:
            time.sleep(_SEND_SPACING_SECONDS)
        if _post(payload, webhook_url):
            delivered += len(payload.get("embeds", []))
        else:
            print(f"[discord] job message {index + 1}/{len(messages)} failed — skipped")

    # Report what actually landed, not what was attempted.
    print(f"[discord] {delivered}/{len(jobs)} job match(es) posted in {len(messages)} message(s)")
    return delivered
