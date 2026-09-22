"""Read recruiting mail out of Gmail.

Authentication is user OAuth, not the service account used for Sheets: a service
account has no personal mailbox to read, and Google only lets one impersonate a
user through domain-wide delegation on a Workspace domain. So this runs the
installed-app consent flow once locally, then reuses the resulting refresh token
everywhere else (including CI, where it arrives as three env vars).

State lives in Gmail itself. Every message that has been classified gets a label
applied, and the fetch query excludes that label, so a rerun never re-notifies
you about mail it has already dealt with.

Run this module directly to do the one-time authorization:

    python gmail_service.py
"""

# Standard library
import base64
import html
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Third-party
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Local
from email_model import EmailMessage

load_dotenv()

# Read messages and change their labels. Does not permit sending or deleting.
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "gmail_token.json")
_CLIENT_SECRET_PATH = os.getenv("GMAIL_CLIENT_SECRET_PATH", "gmail_client_secret.json")

# Enough of the body to classify on. Recruiting mail says what it means up top,
# and trimming keeps Gemini prompts small.
_BODY_MAX_CHARS = 4000

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAK_RE = re.compile(r"<(?:br|/p|/div|/tr|/h[1-6])\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RE = re.compile(r"[ \t\r\f\v]+")
_NEWLINES_RE = re.compile(r"\n{3,}")

_service = None


def _credentials() -> Credentials:
    """Resolve OAuth credentials: env vars first (CI), then a saved token file,
    then an interactive consent flow (local, first run only)."""
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri=_TOKEN_URI,
            scopes=_SCOPES,
        )
        creds.refresh(Request())
        return creds

    if os.path.isfile(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(creds)
        return creds

    return authorize()


def _save_token(creds: Credentials) -> None:
    with open(_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def authorize() -> Credentials:
    """Run the one-time browser consent flow and save the token locally."""
    if not os.path.isfile(_CLIENT_SECRET_PATH):
        raise RuntimeError(
            f"Gmail OAuth is not set up. Either set GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / "
            f"GMAIL_REFRESH_TOKEN, or download an OAuth client ID (Desktop app) from Google "
            f"Cloud Console and save it as {_CLIENT_SECRET_PATH!r}. See the README."
        )

    # Imported here so the dependency is only needed for the one-time local
    # consent flow, never in CI.
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(_CLIENT_SECRET_PATH, _SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save_token(creds)
    print(f"[gmail] authorized — token saved to {_TOKEN_PATH}")
    return creds


def get_service():
    global _service
    if _service is None:
        _service = build("gmail", "v1", credentials=_credentials(), cache_discovery=False)
    return _service


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _html_to_text(markup: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", markup)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    # Non-breaking spaces survive unescaping and break phrase matching.
    return html.unescape(text).replace("\xa0", " ")


def _collect_parts(payload: dict, plain: list[str], markup: list[str]) -> None:
    """Walk the MIME tree, keeping text/plain and text/html bodies separately."""
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if data:
        if mime == "text/plain":
            plain.append(_decode(data))
        elif mime == "text/html":
            markup.append(_decode(data))
    for part in payload.get("parts") or []:
        _collect_parts(part, plain, markup)


def extract_body(payload: dict) -> str:
    """Readable body text for a message, preferring text/plain over HTML."""
    plain: list[str] = []
    markup: list[str] = []
    _collect_parts(payload, plain, markup)

    text = "\n".join(plain).strip() or _html_to_text("\n".join(markup))
    text = _BLANK_RE.sub(" ", text)
    text = _NEWLINES_RE.sub("\n\n", text)
    return text.strip()[:_BODY_MAX_CHARS]


def _received_at(message: dict, tz: str) -> datetime | None:
    """Delivery time in the configured timezone, from Gmail's own epoch stamp."""
    raw = message.get("internalDate")
    if not raw:
        return None
    try:
        utc = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
        return utc.astimezone(ZoneInfo(tz))
    except Exception:
        return None


def _to_message(message: dict, tz: str) -> EmailMessage:
    payload = message.get("payload") or {}
    return EmailMessage(
        id=message["id"],
        thread_id=message.get("threadId", ""),
        subject=_header(payload, "Subject").strip(),
        sender=_header(payload, "From").strip(),
        body=extract_body(payload),
        received_at=_received_at(message, tz),
    )


def ensure_label(name: str) -> str:
    """Return the id of the processed-marker label, creating it if needed."""
    service = get_service()
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in existing:
        if label.get("name") == name:
            return label["id"]

    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    print(f"[gmail] created label {name!r}")
    return created["id"]


def fetch_messages(
    lookback_hours: int,
    processed_label: str,
    max_results: int = 100,
    extra_query: str = "",
) -> list[EmailMessage]:
    """Recent inbox mail that hasn't been processed yet, newest first."""
    service = get_service()
    label_id = ensure_label(processed_label)

    after = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    query = f'after:{after} -in:chats -in:sent -in:drafts -from:me -label:"{processed_label}"'
    if extra_query:
        query = f"{query} {extra_query}"
    print(f"[gmail] searching: {query}")

    ids: list[str] = []
    page_token = None
    while len(ids) < max_results:
        response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(100, max_results - len(ids)),
            pageToken=page_token,
        ).execute()
        ids.extend(m["id"] for m in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    ids = ids[:max_results]

    if not ids:
        print("[gmail] no new messages in the window")
        return []

    tz = os.getenv("TIMEZONE", "America/Los_Angeles")
    messages: list[EmailMessage] = []
    for index, message_id in enumerate(ids, 1):
        raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        # The query should exclude these, but a label applied between the list
        # and get calls would slip through.
        if label_id in (raw.get("labelIds") or []):
            continue
        messages.append(_to_message(raw, tz))
        if index % 25 == 0:
            print(f"[gmail] fetched {index}/{len(ids)} messages...")

    print(f"[gmail] fetched {len(messages)} message(s)")
    return messages


def mark_processed(message_ids: list[str], processed_label: str) -> None:
    """Label messages so later runs skip them."""
    if not message_ids:
        return
    service = get_service()
    label_id = ensure_label(processed_label)
    # batchModify takes up to 1000 ids per call.
    for start in range(0, len(message_ids), 1000):
        service.users().messages().batchModify(
            userId="me",
            body={"ids": message_ids[start:start + 1000], "addLabelIds": [label_id]},
        ).execute()
    print(f"[gmail] labeled {len(message_ids)} message(s) as {processed_label!r}")


if __name__ == "__main__":
    credentials = authorize()
    print("\nAdd these to your GitHub Actions secrets to run this in CI:")
    print(f"  GMAIL_CLIENT_ID     = {credentials.client_id}")
    print(f"  GMAIL_CLIENT_SECRET = {credentials.client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN = {credentials.refresh_token}")
