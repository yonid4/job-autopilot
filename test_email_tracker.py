"""Offline checks for the email -> sheet tracking logic.

Runs entirely on fixtures — no Gmail, no Sheets, no Gemini, no credentials:

    python test_email_tracker.py

Covers the parts that decide whether a row gets written: phrase classification,
the email-to-row matcher, and the status-precedence ladder.
"""

# Standard library
import os
from datetime import datetime

# check_email imports sheets, which reads its spreadsheet target at import time.
# Nothing here calls the API — these placeholders just let the module load.
os.environ.setdefault("GOOGLE_SHEET_ID", "offline-test")
os.environ.setdefault("GOOGLE_CREDENTIALS_PATH", "offline-test")

# Local
import application_matcher as matcher
import application_status as status
import check_email
import discord_notifier
import email_classifier
import gemini_client
from email_classifier import RULES_CONFIDENCE_FLOOR, classify_by_rules
from email_model import EmailAnalysis, EmailCategory, EmailMessage, EmailVerdict
from job_model import ApplicationRow

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")
        _failures.append(name)


def email(subject: str, body: str, sender: str = "Careers <no-reply@example.com>", id_: str = "m1") -> EmailMessage:
    return EmailMessage(
        id=id_,
        thread_id=id_,
        subject=subject,
        sender=sender,
        body=body,
        received_at=datetime(2026, 9, 22),
    )


def expect_category(name: str, message: EmailMessage, expected: EmailCategory, confident: bool = True) -> None:
    verdict = classify_by_rules(message)
    ok = verdict.category == expected
    if confident:
        ok = ok and verdict.confidence >= RULES_CONFIDENCE_FLOOR
    check(name, ok, f"got {verdict.category.value} @ {verdict.confidence:.2f}")


# --- Classification -------------------------------------------------------

def test_classification() -> None:
    print("\nclassification")

    expect_category(
        "plain rejection",
        email(
            "Your application to Acme Robotics",
            "Thank you for your interest in Acme Robotics. After careful review we have "
            "decided to move forward with other candidates whose experience more closely "
            "matches the role. We wish you the best in your search.",
        ),
        EmailCategory.REJECTION,
    )

    expect_category(
        "rejection that opens with thanks for applying",
        email(
            "Update on your application",
            "Thank you for applying to the Software Engineer role. Unfortunately, we will "
            "not be moving forward with your application at this time.",
        ),
        EmailCategory.REJECTION,
    )

    # The single most common shape in a job-search inbox: a rejection wrapped
    # in the pleasantries of an acknowledgement.
    expect_category(
        "short rejection behind a polite opener",
        email(
            "Your application to Acme Robotics",
            "Thank you for applying. Unfortunately we have decided to move forward "
            "with other candidates.",
        ),
        EmailCategory.REJECTION,
    )

    expect_category(
        "online assessment invite",
        email(
            "Next step: your online assessment",
            "Congratulations on advancing! Please complete the assessment on HackerRank "
            "within 5 days to continue with your application.",
        ),
        EmailCategory.ASSESSMENT,
    )

    expect_category(
        "take-home challenge",
        email(
            "Coding challenge for your application",
            "We'd like you to complete a take-home assignment. The link expires in 72 hours.",
        ),
        EmailCategory.ASSESSMENT,
    )

    expect_category(
        "interview invite",
        email(
            "Interview invitation — Backend Engineer",
            "We would like to invite you to a phone screen with our hiring manager. "
            "Please share your availability and book a time using the link below.",
        ),
        EmailCategory.INTERVIEW,
    )

    expect_category(
        "offer",
        email(
            "Your offer from Acme Robotics",
            "Congratulations! We are pleased to offer you the position of Software Engineer. "
            "Your offer letter is attached and outlines the compensation package.",
        ),
        EmailCategory.OFFER,
    )

    expect_category(
        "application acknowledgement",
        email(
            "We received your application",
            "Thanks for applying to Acme Robotics. Our team will review your application "
            "and be in touch.",
        ),
        EmailCategory.ACKNOWLEDGEMENT,
    )

    expect_category(
        "job alert is noise",
        email(
            "10 new jobs for you this week",
            "Here are jobs you may be interested in based on your job search. "
            "Unsubscribe from job alerts anytime.",
        ),
        EmailCategory.OTHER,
    )

    # "Congratulations" is the trap here — an assessment invite is not an offer.
    expect_category(
        "congratulations + assessment is not an offer",
        email(
            "Congratulations — next steps",
            "Congratulations on clearing the first round! The next step is an online "
            "assessment. Please complete the assessment within 3 days.",
        ),
        EmailCategory.ASSESSMENT,
    )

    verdict = classify_by_rules(email("Quick question", "Are you still interested in chatting?"))
    check(
        "vague email is left to Gemini",
        verdict.confidence < RULES_CONFIDENCE_FLOOR,
        f"confidence {verdict.confidence:.2f}",
    )


# --- Matching -------------------------------------------------------------

ROWS = [
    ApplicationRow(row=2, company="Acme Robotics", status="Applied",
                   role="Software Engineer", link="https://boards.example.com/acme/123"),
    ApplicationRow(row=3, company="Acme Robotics", status="Applied",
                   role="Data Engineer", link="https://boards.example.com/acme/456"),
    ApplicationRow(row=4, company="Stripe", status="Have Not Applied",
                   role="Backend Engineer", link="https://stripe.com/jobs/789"),
    ApplicationRow(row=5, company="Northwind Trading Co", status="Applied",
                   role="Platform Engineer", link="https://northwind.example/jobs/1"),
]


def test_matching() -> None:
    print("\nmatching")

    result = matcher.best_match(
        email("Update on your application", "We reviewed your application carefully.",
              sender="Stripe Recruiting <no-reply@stripe.com>"),
        ROWS,
    )
    check("sender domain picks the company", result.matched and result.row.row == 4,
          f"row {result.row.row if result.row else None} @ {result.score}")

    # Greenhouse sends the mail, so only the display name and subject identify it.
    result = matcher.best_match(
        email("Your application to Acme Robotics",
              "Thank you for applying to the Data Engineer position at Acme Robotics.",
              sender="Acme Robotics <no-reply@us.greenhouse-mail.io>"),
        ROWS,
    )
    check("ATS sender resolved by name + role", result.matched and result.row.row == 3,
          f"row {result.row.row if result.row else None} @ {result.score}")

    result = matcher.best_match(
        email("Interview", "Regarding https://boards.example.com/acme/123 — let's talk.",
              sender="Recruiter <someone@gmail.com>"),
        ROWS,
    )
    check("job link beats everything else", result.matched and result.row.row == 2,
          f"row {result.row.row if result.row else None} @ {result.score}")

    result = matcher.best_match(
        email("Your Amazon order has shipped", "Your package is on the way.",
              sender="Amazon <ship-confirm@amazon.com>"),
        ROWS,
    )
    check("unrelated mail matches nothing", not result.matched,
          f"row {result.row.row if result.row else None} @ {result.score}")

    # Same company, no role wording to separate the two rows -> Gemini's call.
    result = matcher.best_match(
        email("An update", "An update on your application at Acme Robotics.",
              sender="Acme Robotics <careers@acmerobotics.com>"),
        ROWS,
    )
    check("two roles at one company reads as ambiguous", result.ambiguous,
          f"row {result.row.row if result.row else None} score {result.score} vs {result.runner_up_score}")

    result = matcher.best_match(
        email("Northwind Trading", "Following up on your Platform Engineer application.",
              sender="Careers <talent@northwind.example>"),
        ROWS,
    )
    check("legal suffix in company name is ignored", result.matched and result.row.row == 5,
          f"row {result.row.row if result.row else None} @ {result.score}")

    body_only = matcher.best_match(
        email("Newsletter", "This week: Stripe raised a round, and other news.",
              sender="Tech Digest <hello@techdigest.example>"),
        ROWS,
    )
    check("a passing mention in the body is not a match", not body_only.matched,
          f"score {body_only.score}")


# --- Status precedence ----------------------------------------------------

def test_status_precedence() -> None:
    print("\nstatus precedence")

    check("acknowledgement promotes an untouched row",
          status.is_upgrade(status.STATUS_NOT_APPLIED, status.STATUS_APPLIED))
    check("assessment beats applied",
          status.is_upgrade(status.STATUS_APPLIED, status.STATUS_ASSESSMENT))
    check("a late auto-reply cannot undo an interview",
          not status.is_upgrade(status.STATUS_INTERVIEW, status.STATUS_APPLIED))
    check("rejection lands even on an offer",
          status.is_upgrade(status.STATUS_OFFER, status.STATUS_REJECTED))
    check("re-reading the same rejection is a no-op",
          not status.is_upgrade(status.STATUS_REJECTED, status.STATUS_REJECTED))
    check("unknown status is treated as the start of the funnel",
          status.is_upgrade("Waiting on referral", status.STATUS_INTERVIEW))
    check("category with no status implication returns None",
          status.status_for(EmailCategory.OTHER) is None)


# --- Planning -------------------------------------------------------------

def plan(entries: list[tuple[EmailMessage, EmailVerdict, ApplicationRow | None]]):
    """Run plan_updates over ready-made verdicts, bypassing Gmail and Gemini."""
    messages = [message for message, _, _ in entries]
    verdicts = {message.id: verdict for message, verdict, _ in entries}
    matches = {
        message.id: matcher.MatchResult(row=row, score=99 if row else 0)
        for message, _, row in entries
    }
    return check_email.plan_updates(messages, verdicts, matches)


def verdict(category: EmailCategory, confidence: float = 0.9, summary: str = "", source: str = "rules") -> EmailVerdict:
    return EmailVerdict(category=category, confidence=confidence, summary=summary, source=source)


def test_planning() -> None:
    print("\nplanning")

    applied = ApplicationRow(row=2, tab="Sep 20", company="Acme Robotics", status="Applied",
                             role="Software Engineer", link="https://x.example/1",
                             notes="Gemini: strong match on backend work.", rejection_reason="N/A")

    updates, notifications = plan([(
        email("Your application to Acme Robotics", "We are moving forward with other candidates."),
        verdict(EmailCategory.REJECTION, summary="Acme declined the application."),
        applied,
    )])
    ok = (len(updates) == 1 and updates[0].status == status.STATUS_REJECTED
          and updates[0].note_column == "G" and updates[0].tab == "Sep 20" and updates[0].row == 2)
    check("rejection writes status and the reason column", ok, str(updates))
    check("rejection replaces the N/A placeholder",
          updates and updates[0].note_text.startswith("[2026-09-22] Rejected:") and "N/A" not in updates[0].note_text,
          updates[0].note_text if updates else "")
    check("rejection is not a Discord ping", not notifications, str(notifications))

    updates, notifications = plan([(
        email("Online assessment", "Please complete the assessment on HackerRank."),
        verdict(EmailCategory.ASSESSMENT, summary="OA invite, due in 5 days."),
        applied,
    )])
    check("assessment moves the row forward",
          len(updates) == 1 and updates[0].status == status.STATUS_ASSESSMENT and updates[0].note_column == "F",
          str(updates))
    check("assessment keeps the existing notes underneath",
          updates and updates[0].note_text.endswith("Gemini: strong match on backend work."),
          updates[0].note_text if updates else "")
    check("assessment pings Discord", len(notifications) == 1, str(notifications))

    # Good news the matcher couldn't place still has to reach you.
    updates, notifications = plan([(
        email("Interview invitation", "Please share your availability."),
        verdict(EmailCategory.INTERVIEW),
        None,
    )])
    check("unmatched positive notifies with no row",
          not updates and len(notifications) == 1 and notifications[0][2] is None,
          f"{updates} {notifications}")

    updates, notifications = plan([(
        email("Something vague", "Circling back."),
        verdict(EmailCategory.INTERVIEW, confidence=0.4),
        applied,
    )])
    check("low confidence does nothing at all", not updates and not notifications,
          f"{updates} {notifications}")

    interviewing = applied.model_copy(update={"status": status.STATUS_INTERVIEW})
    updates, _ = plan([(
        email("We received your application", "Thanks for applying."),
        verdict(EmailCategory.ACKNOWLEDGEMENT),
        interviewing,
    )])
    check("a late auto-reply leaves an interviewing row alone", not updates, str(updates))

    # Two emails, one row: the interview invite must win over the auto-reply.
    ack = email("We received your application", "Thanks for applying.", id_="a")
    invite = email("Interview invitation", "Let's schedule a call.", id_="b")
    updates, _ = plan([
        (ack, verdict(EmailCategory.ACKNOWLEDGEMENT), applied),
        (invite, verdict(EmailCategory.INTERVIEW), applied),
    ])
    check("furthest-along news claims a contested row",
          len(updates) == 1 and updates[0].status == status.STATUS_INTERVIEW, str(updates))

    # Two pieces of good news for one row: written once, but both still reach you,
    # and both still name the job they're about.
    oa = email("Online assessment", "Complete the assessment on HackerRank.", id_="c")
    call = email("Interview invitation", "Let's schedule a call.", id_="d")
    updates, notifications = plan([
        (oa, verdict(EmailCategory.ASSESSMENT), applied),
        (call, verdict(EmailCategory.INTERVIEW), applied),
    ])
    check("a contested row is written once but notified twice",
          len(updates) == 1 and len(notifications) == 2, f"{updates} {notifications}")
    check("the second notification still names the job",
          all(n[2] is not None and n[2].company == "Acme Robotics" for n in notifications),
          str([n[2] for n in notifications]))

    long_notes = applied.model_copy(update={"notes": "x" * 60000})
    updates, _ = plan([(
        email("Online assessment", "Complete the assessment."),
        verdict(EmailCategory.ASSESSMENT),
        long_notes,
    )])
    check("note text stays inside the cell limit",
          updates and len(updates[0].note_text) <= 45000, str(len(updates[0].note_text)) if updates else "")


# --- Gemini gate ----------------------------------------------------------

def test_gemini_gate() -> None:
    print("\ngemini gate")

    # Regression: "ai" inside "claim"/"email" used to count as the role "AI
    # Engineer", so against a big sheet every promo email had a shortlist.
    promo = email("Claim it: 20% off 5 rides",
                  "Open the app and your discount is applied. Questions? Reply to this email.",
                  sender="Rides <promo@rides.example>", id_="promo")
    ai_row = ApplicationRow(row=2, tab="t", company="Acme", role="AI Engineer")
    check("short role words don't match inside other words",
          matcher.score_row(promo, ai_row) == 0, f"score {matcher.score_row(promo, ai_row)}")

    # Capture what would be sent to Gemini instead of calling it.
    sent: list[str] = []
    original = email_classifier._classify_with_gemini
    email_classifier._classify_with_gemini = lambda items: sent.extend(m.id for m, _ in items) or {}
    try:
        weak = ApplicationRow(row=3, tab="t", company="Globex", role="Data Engineer")
        vague_related = email("Quick question", "Are you still interested?",
                              sender="Globex Talent <talent@globex.com>", id_="related")
        vague_unrelated = email("Quick question", "Are you still interested?",
                                sender="Someone <someone@elsewhere.example>", id_="unrelated")
        email_classifier.classify(
            [promo, vague_related, vague_unrelated],
            candidates_for={"promo": [ai_row], "related": [weak], "unrelated": [weak]},
            related={"related"},
        )
    finally:
        email_classifier._classify_with_gemini = original

    check("unrelated junk stays away from Gemini even with a weak shortlist",
          "promo" not in sent and "unrelated" not in sent, str(sent))
    check("an unclear email from a company you applied to still goes to Gemini",
          "related" in sent, str(sent))

    result = matcher.best_match(vague_related, [weak])
    check("company in the sender's name counts as related",
          result.score >= matcher.RELATED_THRESHOLD, f"score {result.score}")


# --- Escalation reasons, extraction and notification details --------------

def reason_for(message: EmailMessage, **sets) -> str:
    verdict = classify_by_rules(message)
    return email_classifier._escalation_reason(
        message, verdict,
        sets.get("needs_review", set()), sets.get("related", set()), sets.get("unmatched", set()),
    )


def test_escalation_reasons() -> None:
    print("\nescalation reasons")

    # Straight from the first real run: faint category hints in promotions.
    promos = [
        email("LIMITED OFFER - Book Today & Get a $200 Gift Card!",
              "Congratulations! This offer expires in 3 days. Book now.", id_="p1"),
        email("Claim it: 20% off 5 rides", "Your promo expires on Sunday. Next steps: open the app.", id_="p2"),
        email("We're updating our Terms of Service", "These changes take effect at this time next month.", id_="p3"),
    ]
    leaked = [m.subject for m in promos if reason_for(m, needs_review={m.id}, unmatched={m.id})]
    check("promo emails with faint hints stay with the rules", not leaked, str(leaked))
    labels = email_classifier.classify(promos, {})
    check("and are logged as other, not as an assessment or rejection",
          all(v.category == EmailCategory.OTHER for v in labels.values()),
          str({v.summary[:20]: v.category.value for v in labels.values()}))

    amazon = email("RE: Amazon Opportunity - Virtual Interview Invitation- Yonatan Dayagi - 10382631",
                   "We'd like to schedule your virtual interview. Please share your availability.",
                   sender="SP EMEA Loops <sp-scheduling@amazon.jobs>", id_="amzn")
    check("unmatched good news goes to Gemini for company and role",
          reason_for(amazon, unmatched={"amzn"}) == email_classifier.REASON_DETAILS,
          reason_for(amazon, unmatched={"amzn"}))
    check("a coin-flip row match goes to Gemini to pick the row",
          reason_for(amazon, needs_review={"amzn"}) == email_classifier.REASON_WHICH_ROW,
          reason_for(amazon, needs_review={"amzn"}))
    check("a matched, confident email doesn't need Gemini", reason_for(amazon) == "", reason_for(amazon))

    rejection = email("Update", "Unfortunately we will not be moving forward.", id_="rej")
    check("a matched-less rejection isn't worth a details call",
          reason_for(rejection, unmatched={"rej"}) == "", reason_for(rejection, unmatched={"rej"}))


def test_gemini_extraction() -> None:
    print("\ngemini extraction")

    amazon = email("Virtual Interview Invitation", "Please share your availability.",
                   sender="SP EMEA Loops <sp-scheduling@amazon.jobs>", id_="amzn")
    row = ApplicationRow(row=5, tab="Sep 20", company="Acme", role="Backend Engineer")
    canned = [EmailAnalysis(email_id="amzn", category="interview", application_index=0,
                            confidence=0.97, summary="Amazon wants interview availability.",
                            company="Amazon", role="Software Development Engineer")]

    original = (gemini_client.is_configured, gemini_client.generate_json)
    gemini_client.is_configured = lambda: True
    gemini_client.generate_json = lambda **_: canned
    try:
        verdicts = email_classifier.classify([amazon], {"amzn": [row]}, unmatched={"amzn"})
    finally:
        gemini_client.is_configured, gemini_client.generate_json = original

    verdict = verdicts["amzn"]
    check("Gemini's reading replaces the rule verdict", verdict.source == "gemini", verdict.source)
    check("company and role are read out of the email",
          verdict.company == "Amazon" and verdict.role == "Software Development Engineer",
          f"{verdict.company!r} / {verdict.role!r}")
    check("the reason it was asked is kept for the log",
          verdict.escalation == email_classifier.REASON_DETAILS, verdict.escalation)
    check("index 0 means no row, not the first candidate", verdict.matched_row is None, str(verdict.matched_row))
    check("log tag names Gemini and the reason",
          check_email._via(verdict) == f"gemini: {email_classifier.REASON_DETAILS}", check_email._via(verdict))

    unanswered = classify_by_rules(amazon)
    unanswered.escalation = email_classifier.REASON_DETAILS
    check("log tag admits when Gemini was asked but didn't answer",
          "didn't answer" in check_email._via(unanswered), check_email._via(unanswered))
    check("log tag for a rules-only email", check_email._via(classify_by_rules(amazon)) == "rules")


def test_notification_details() -> None:
    print("\nnotification details")

    link = "https://mail.google.com/mail/?authuser=me%40gmail.com#all/abc123"
    message = email("Virtual Interview Invitation", "Share your availability.", id_="abc123")
    message = message.model_copy(update={"web_link": link})
    from_email = EmailVerdict(category=EmailCategory.INTERVIEW, confidence=1.0, source="gemini",
                              company="Amazon", role="Software Development Engineer")

    embed = discord_notifier.build_embed(message, from_email, None)
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    check("title uses the company the email names", embed["title"].endswith("— Amazon"), embed["title"])
    check("role uses the title the email names",
          fields.get("Role") == "Software Development Engineer", fields.get("Role"))
    check("title links to the email", embed.get("url") == link, embed.get("url"))
    check("links field opens the email", f"[Open email]({link})" in fields.get("Links", ""), fields.get("Links"))

    row = ApplicationRow(row=4, tab="Sep 20", company="Stripe", role="Backend Engineer",
                         link="https://stripe.com/jobs/1")
    embed = discord_notifier.build_embed(message, from_email, row)
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    check("the sheet row wins over what the email says",
          embed["title"].endswith("— Stripe") and fields["Role"] == "Backend Engineer",
          f"{embed['title']} / {fields['Role']}")
    check("job posting sits next to the email link",
          "[Job posting](https://stripe.com/jobs/1)" in fields.get("Links", ""), fields.get("Links"))

    bare = discord_notifier.build_embed(email("x", "y"), EmailVerdict(category=EmailCategory.OFFER), None)
    bare_fields = {f["name"]: f["value"] for f in bare["fields"]}
    check("nothing known still reads Unknown, with no dead link",
          bare["title"].endswith("Unknown company") and "Links" not in bare_fields and "url" not in bare,
          bare["title"])


def main() -> None:
    test_classification()
    test_matching()
    test_status_precedence()
    test_planning()
    test_gemini_gate()
    test_escalation_reasons()
    test_gemini_extraction()
    test_notification_details()
    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed:")
        for name in _failures:
            print(f"  - {name}")
        raise SystemExit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
