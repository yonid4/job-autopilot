"""Read the inbox, mark the tracking sheet, and ping Discord about good news.

Run it alongside the scraper (see .github/workflows/check_email.yml):

    python check_email.py

The pass is idempotent. Every message it looks at gets a Gmail label, and the
fetch excludes that label, so re-running never double-writes a row or sends the
same notification twice. Set EMAIL_DRY_RUN=1 to print the plan and touch
nothing — worth doing on the first run.
"""

# Standard library
import os

# Local
import application_matcher as matcher
import application_status as status_policy
import discord_notifier
import gmail_service
import sheets
from config import Config as config
from email_classifier import classify
from email_model import POSITIVE_CATEGORIES, EmailCategory, EmailMessage, EmailVerdict
from job_model import ApplicationRow, StatusUpdate

# How far back to look. The processed label — not this window — is what stops
# repeat work, so a generous window just means nothing gets missed when a run
# is skipped.
LOOKBACK_HOURS = int(os.getenv("EMAIL_LOOKBACK_HOURS") or getattr(config, "EMAIL_LOOKBACK_HOURS", 48))
MAX_MESSAGES = int(os.getenv("EMAIL_MAX_RESULTS") or getattr(config, "EMAIL_MAX_RESULTS", 150))
PROCESSED_LABEL = os.getenv("EMAIL_PROCESSED_LABEL") or getattr(config, "EMAIL_PROCESSED_LABEL", "Job Autopilot/Processed")

# Below this, a verdict is reported but nothing is written or sent.
MIN_CONFIDENCE = float(os.getenv("EMAIL_MIN_CONFIDENCE") or getattr(config, "EMAIL_MIN_CONFIDENCE", 0.6))

DRY_RUN = (os.getenv("EMAIL_DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}

# Google Sheets rejects cell values beyond 50k characters.
_CELL_LIMIT = 45000

_NOTE_LABELS = {
    EmailCategory.REJECTION: "Rejected",
    EmailCategory.ASSESSMENT: "Online assessment",
    EmailCategory.INTERVIEW: "Interview",
    EmailCategory.OFFER: "Offer",
    EmailCategory.ACKNOWLEDGEMENT: "Application received",
}


def _notify_categories() -> set[EmailCategory]:
    """Categories worth a Discord ping — the positive ones unless configured otherwise."""
    configured = getattr(config, "DISCORD_NOTIFY_CATEGORIES", None)
    if not configured:
        return set(POSITIVE_CATEGORIES)
    by_value = {c.value: c for c in EmailCategory}
    return {by_value[name] for name in (str(c).strip().lower() for c in configured) if name in by_value}


def _detail(message: EmailMessage, verdict: EmailVerdict) -> str:
    """One-line description of what the email said."""
    subject = (message.subject or "").strip()
    summary = (verdict.summary or "").strip()
    if summary and subject and summary.lower() != subject.lower():
        return f"{subject} — {summary}"
    return summary or subject or "(no subject)"


def _note_text(row: ApplicationRow, message: EmailMessage, verdict: EmailVerdict) -> tuple[str, str]:
    """The cell to write and its new contents.

    Rejections go to Rejection Reason (column G), which holds a placeholder
    "N/A" until there is a real reason. Everything else is prepended to Notes
    (column F), keeping the Gemini fit analysis already in there underneath.
    """
    label = _NOTE_LABELS.get(verdict.category, verdict.category.value)
    line = f"[{message.received_date()}] {label}: {_detail(message, verdict)}".strip()

    if verdict.category == EmailCategory.REJECTION:
        existing = row.rejection_reason.strip()
        if existing and existing.upper() != "N/A":
            return "G", f"{line}\n{existing}"[:_CELL_LIMIT]
        return "G", line[:_CELL_LIMIT]

    existing = row.notes.strip()
    return "F", (f"{line}\n\n{existing}" if existing else line)[:_CELL_LIMIT]


def plan_updates(
    messages: list[EmailMessage],
    verdicts: dict[str, EmailVerdict],
    matches: dict[str, matcher.MatchResult],
) -> tuple[list[StatusUpdate], list[tuple[EmailMessage, EmailVerdict, ApplicationRow | None]]]:
    """Turn verdicts into sheet writes and Discord notifications.

    Returns (updates, notifications). A positive email still earns a
    notification when no row matched — the news matters even if the tracker
    can't place it.
    """
    notify_categories = _notify_categories()
    updates: list[StatusUpdate] = []
    notifications: list[tuple[EmailMessage, EmailVerdict, ApplicationRow | None]] = []
    claimed: set[tuple[str, int]] = set()

    actionable: list[tuple[EmailMessage, EmailVerdict, ApplicationRow | None]] = []
    for message in messages:
        verdict = verdicts.get(message.id) or EmailVerdict()
        if not verdict.is_actionable:
            print(f"  · {verdict.category.value:16} {message.subject[:60]!r} — ignored")
            continue
        if verdict.confidence < MIN_CONFIDENCE:
            print(f"  ? {verdict.category.value:16} {message.subject[:60]!r} — "
                  f"confidence {verdict.confidence:.0%} below {MIN_CONFIDENCE:.0%}, skipped")
            continue
        # Gemini's pick wins when it made one; it read the email body, while the
        # matcher only sees name and domain overlap.
        row = verdict.matched_row or matches.get(message.id, matcher.MatchResult()).row
        actionable.append((message, verdict, row))

    # A batch can hold several emails about one application — an auto-reply and
    # the interview invite that followed it. Sort so the furthest-along news
    # claims the row, and fall back to the most recent when two rank equally.
    actionable.sort(key=lambda item: (
        -status_policy.rank(status_policy.status_for(item[1].category) or ""),
        -(item[0].received_at.timestamp() if item[0].received_at else 0),
    ))

    for message, verdict, row in actionable:
        if row is None:
            print(f"  ! {verdict.category.value:16} {message.subject[:60]!r} — no matching application")
        elif (row.tab, row.row) in claimed:
            print(f"  ! {verdict.category.value:16} {message.subject[:60]!r} — "
                  f"{row.company} ({row.tab} row {row.row}) already updated this run")
        else:
            new_status = status_policy.status_for(verdict.category)
            if new_status and status_policy.is_upgrade(row.status, new_status):
                column, text = _note_text(row, message, verdict)
                updates.append(StatusUpdate(tab=row.tab, row=row.row, status=new_status,
                                            note_column=column, note_text=text))
                claimed.add((row.tab, row.row))
                print(f"  > {verdict.category.value:16} {row.company} — {row.role} "
                      f"({row.tab} row {row.row}): {row.status or 'blank'} -> {new_status}")
            else:
                print(f"  = {verdict.category.value:16} {row.company} — {row.role} "
                      f"({row.tab} row {row.row}): already {row.status}, left alone")

        if verdict.category in notify_categories:
            notifications.append((message, verdict, row))

    return updates, notifications


def main() -> None:
    print(f"[check_email] scanning the last {LOOKBACK_HOURS}h"
          + (" (dry run — nothing will be written)" if DRY_RUN else ""))

    rows = sheets.get_application_rows()
    if not rows:
        print("[check_email] no applications in the sheet yet — nothing to match against")
        return

    messages = gmail_service.fetch_messages(
        lookback_hours=LOOKBACK_HOURS,
        processed_label=PROCESSED_LABEL,
        max_results=MAX_MESSAGES,
    )
    if not messages:
        return

    # Score every email against the sheet first: the shortlist tells the
    # classifier which applications an ambiguous email might be about, and a
    # coin-flip between two rows is itself a reason to ask Gemini.
    matches: dict[str, matcher.MatchResult] = {}
    candidates_for: dict[str, list[ApplicationRow]] = {}
    needs_review: set[str] = set()
    for message in messages:
        result = matcher.best_match(message, rows)
        matches[message.id] = result
        candidates_for[message.id] = [row for _, row in matcher.rank_candidates(message, rows)]
        if result.ambiguous:
            needs_review.add(message.id)

    verdicts = classify(messages, candidates_for, needs_review)

    print(f"\n[check_email] {len(messages)} message(s) triaged:")
    updates, notifications = plan_updates(messages, verdicts, matches)

    if DRY_RUN:
        print(f"\n[check_email] dry run — would write {len(updates)} row(s) "
              f"and send {len(notifications)} notification(s)")
        return

    # Label only after the sheet write lands, so a failure here leaves the mail
    # unprocessed and the next run picks it up again.
    sheets.apply_status_updates(updates)
    discord_notifier.notify(notifications)
    gmail_service.mark_processed([m.id for m in messages], PROCESSED_LABEL)

    print(f"\n[check_email] done: {len(updates)} row(s) updated, "
          f"{len(notifications)} notification(s) sent, {len(messages)} message(s) processed.")


if __name__ == "__main__":
    main()
