"""Decide what a recruiting email is saying.

Two passes. A weighted phrase matcher handles the overwhelming majority of
recruiting mail — the wording is formulaic — at no API cost and with no network
round trip. Anything it can't call confidently (unusual phrasing, or a match
that's split between two roles at the same company) goes to Gemini in a single
batched request, along with the shortlist of open applications so the model can
pick the row as well as the category.

Gemini is optional: with no key configured, or when it's overloaded, the rule
verdict stands on its own and the caller's confidence floor decides whether it
is acted on.
"""

# Standard library
import re
from typing import Callable

# Local
import gemini_client
from email_model import (
    ACTIONABLE_CATEGORIES,
    POSITIVE_CATEGORIES,
    EmailAnalysis,
    EmailCategory,
    EmailMessage,
    EmailVerdict,
    compact_text,
)
from job_model import ApplicationRow

# A rule verdict at or above this confidence is taken as final; below it, the
# email is sent to Gemini for a second opinion.
RULES_CONFIDENCE_FLOOR = 0.7

# Phrase score at which a rule category counts as real evidence rather than a
# coincidence. One decisive phrase (3), or a strong one in the subject, clears
# it; a lone hint like "expires in" or "next steps" (1) — the stuff of every
# promo email — does not.
ACTIONABLE_SIGNAL_FLOOR = 3

# Why an email was sent to Gemini, shown in the run log.
REASON_UNCLEAR = "unclear category"
REASON_WHICH_ROW = "unsure which application"
REASON_DETAILS = "company/role for notification"

# Emails per Gemini request. Small enough that one bad batch costs little.
_GEMINI_BATCH_SIZE = 5

# Open applications offered to Gemini per email, best-scoring first.
_MAX_CANDIDATES_PER_EMAIL = 12

# (pattern, weight) per category. Weight 3 is a phrase that decides the category
# on its own, 2 is strong support, 1 is a hint. A hit in the subject line counts
# double — subjects are written to summarize the mail.
_PATTERNS: dict[EmailCategory, list[tuple[str, int]]] = {
    EmailCategory.REJECTION: [
        (r"mov(?:e|ing) forward with other (?:candidate|applicant)", 3),
        (r"other (?:candidates|applicants) whose", 3),
        (r"regret to inform", 3),
        (r"will not be (?:moving|proceeding|progressing|continuing)", 3),
        (r"not (?:be )?(?:moving|going) forward with your", 3),
        (r"decided not to (?:move|proceed|continue|pursue)", 3),
        (r"no longer under consideration", 3),
        (r"unable to (?:offer|move forward|proceed)", 3),
        (r"(?:was|were) not selected", 3),
        (r"(?:position|role) has been filled", 3),
        (r"pursu(?:e|ing) other (?:candidates|applicants)", 3),
        (r"application (?:was|has been) unsuccessful", 3),
        (r"not (?:be )?selected (?:to|for)", 3),
        (r"we have decided to move ahead with", 3),
        (r"unfortunately", 2),
        (r"difficult decision", 2),
        (r"(?:many|numerous) (?:highly )?qualified (?:applicants|candidates)", 2),
        (r"keep your (?:resume|application|profile) on file", 2),
        (r"not (?:a |an )?(?:good )?(?:match|fit)(?: for(?: us)?)?(?: at this time)?", 2),
        (r"wish you (?:the best|success|all the best)", 1),
        (r"at this time", 1),
    ],
    EmailCategory.ASSESSMENT: [
        (r"online assessment", 3),
        (r"(?:coding|technical|skills?|programming) (?:assessment|challenge|test|exercise)", 3),
        (r"take[\s-]?home (?:assignment|test|exercise|challenge|project)", 3),
        (r"hackerrank|codesignal|codility|coderpad|karat\b|woven\b|hackerearth|devskiller", 3),
        (r"assessment (?:invitation|link|invite)", 3),
        (r"complete (?:the|your|this) assessment", 3),
        (r"invit(?:e|ed|ation) to (?:take|complete)", 3),
        (r"\bassessment\b", 2),
        (r"complete (?:the|this) .{0,20}(?:test|exercise|challenge)", 2),
        (r"within \d+ (?:hours|days|business days)", 1),
        (r"expires? (?:in|on)", 1),
    ],
    EmailCategory.INTERVIEW: [
        (r"schedul(?:e|ing) (?:an?|your|the) interview", 3),
        (r"phone (?:screen|interview)", 3),
        (r"(?:technical|behavioral|panel|final|onsite|on[\s-]site|virtual onsite) interview", 3),
        (r"final round", 3),
        (r"interview (?:invitation|invite|request)", 3),
        (r"(?:invite|like) (?:you )?to (?:an )?interview", 3),
        (r"recruiter (?:screen|call|chat)", 3),
        (r"hiring manager (?:call|chat|conversation|screen)", 3),
        (r"set up (?:a|an) (?:call|chat|conversation|interview|time)", 3),
        (r"mov(?:e|ing) forward with your (?:application|candidacy)", 3),
        (r"next round", 3),
        (r"\binterview\b", 2),
        (r"your availability", 2),
        (r"(?:book|find|pick|choose) a time", 2),
        (r"calendly|goodtime|savvycal", 2),
        (r"schedule a call", 2),
        (r"(?:speak|chat|connect) with you", 2),
        (r"\d{2}[\s-]minute", 1),
        (r"next steps", 1),
    ],
    EmailCategory.OFFER: [
        (r"pleased to offer", 3),
        (r"offer of employment", 3),
        (r"(?:formal|written|official) offer", 3),
        (r"extend(?:ing)? (?:you )?an offer", 3),
        (r"offer letter", 3),
        (r"would like to offer you", 3),
        (r"welcome to the team", 3),
        (r"\bjob offer\b", 3),
        # Weak on purpose: nearly every "you advanced" email opens with it,
        # so it must not outweigh an assessment or interview invite.
        (r"congratulations", 1),
        (r"compensation package", 2),
        (r"(?:thrilled|excited) to have you", 2),
        (r"start date", 1),
        (r"onboarding", 1),
    ],
    EmailCategory.ACKNOWLEDGEMENT: [
        (r"(?:we(?:'ve| have)? )?received your application", 3),
        (r"thank(?:s| you) for applying", 3),
        (r"application (?:has been |was )?(?:received|submitted)", 3),
        (r"successfully submitted", 3),
        (r"application confirmation", 3),
        (r"(?:we are|we're) reviewing your application", 3),
        (r"(?:our team|the team|we) will review", 2),
        (r"will be in touch", 2),
        (r"reviewing applications", 2),
        (r"thank you for your interest", 1),
    ],
    EmailCategory.OTHER: [
        (r"job alert", 3),
        (r"jobs? (?:you may|we think you)", 3),
        (r"new jobs? (?:for|matching|that match)", 3),
        (r"recommended (?:jobs|for you)", 3),
        (r"top job picks", 3),
        (r"your job search", 2),
        (r"unsubscribe from (?:job )?alerts", 2),
        (r"newsletter", 2),
        (r"\d+ new jobs", 2),
    ],
}

_COMPILED: dict[EmailCategory, list[tuple[re.Pattern, int]]] = {
    category: [(re.compile(pattern, re.IGNORECASE), weight) for pattern, weight in rules]
    for category, rules in _PATTERNS.items()
}

_CATEGORY_BY_VALUE = {c.value: c for c in EmailCategory}

# "Thanks for applying" and job-alert boilerplate sit underneath whatever else
# an email says — nearly every rejection opens with the former, and a decision
# email can carry unsubscribe footers. As runners-up they only half count, so a
# decision that shares the page with pleasantries is still read confidently.
_SUBORDINATE_CATEGORIES = frozenset({EmailCategory.ACKNOWLEDGEMENT, EmailCategory.OTHER})
_SUBORDINATE_WEIGHT = 0.5


def score_categories(message: EmailMessage) -> dict[EmailCategory, int]:
    """Weighted phrase score per category for one email."""
    subject = message.subject or ""
    body = message.body or ""
    scores: dict[EmailCategory, int] = {}
    for category, rules in _COMPILED.items():
        total = 0
        for pattern, weight in rules:
            if pattern.search(subject):
                total += weight * 2
            if pattern.search(body):
                total += weight
        if total:
            scores[category] = total
    return scores


def _confidence(best: int, second: float) -> float:
    """Turn the winning margin into a confidence figure.

    A high score with nothing close behind it is a formulaic email we can read
    reliably; a narrow win usually means the mail mixes signals (a rejection
    that opens with "thank you for applying") and deserves a closer look.
    """
    if best <= 0:
        return 0.35
    ratio = second / best
    if best >= 6 and ratio <= 0.4:
        return 0.92
    if best >= 4 and ratio <= 0.5:
        return 0.8
    if best >= 3 and second == 0:
        return 0.75
    if best >= 3 and ratio <= 0.34:
        return 0.7
    return 0.45


def classify_by_rules(message: EmailMessage) -> EmailVerdict:
    """Phrase-matching verdict for one email. Never raises, never calls out."""
    scores = score_categories(message)
    if not scores:
        return EmailVerdict(category=EmailCategory.OTHER, confidence=0.35, summary=message.subject)

    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    (category, best) = ordered[0]
    second = max(
        (score * (_SUBORDINATE_WEIGHT if other in _SUBORDINATE_CATEGORIES else 1.0)
         for other, score in ordered[1:]),
        default=0.0,
    )
    return EmailVerdict(
        category=category,
        confidence=_confidence(best, second),
        summary=(message.subject or "").strip(),
        source="rules",
        rule_score=best,
    )


def _candidate_block(candidates: list[ApplicationRow]) -> str:
    if not candidates:
        return "  (no open applications look related to this email)"
    # Numbered rather than keyed by sheet row: the scraper writes one tab per
    # run, so row numbers repeat across tabs and can't identify an application.
    return "\n".join(
        f"  #{index}: {row.company or '(no company)'} — {row.role or '(no title)'}"
        f" [status: {row.status or 'blank'}]"
        for index, row in enumerate(candidates, 1)
    )


def _email_section(message: EmailMessage, candidates: list[ApplicationRow]) -> str:
    section = (
        f"EMAIL ID: {message.id}\n"
        f"- From: {message.sender}\n"
        f"- Subject: {message.subject}\n"
        f"- Body: {message.preview()}\n"
    )
    if message.thread_context:
        section += (f"- Earlier messages in the same thread (context only): "
                    f"{compact_text(message.thread_context, 3000)}\n")
    return section + f"- Open applications that might match:\n{_candidate_block(candidates)}"


def _build_prompt(items: list[tuple[EmailMessage, list[ApplicationRow]]]) -> str:
    sections = "\n\n".join(_email_section(message, candidates) for message, candidates in items)

    return f"""
You are triaging a job applicant's inbox. For each email below, decide what it says about
their application and which of their open applications it refers to.

{sections}

CATEGORIES — choose exactly one per email:
- "rejection": the application was declined, the role was filled, or they are not moving forward.
- "assessment": an invitation to take an online assessment, coding challenge, or take-home exercise.
- "interview": an invitation to interview, a request for availability, or scheduling for any round.
- "offer": an employment offer is being extended.
- "acknowledgement": confirmation that the application was received; no decision yet.
- "other": anything else — job alerts, newsletters, marketing, or mail unrelated to an application.

RULES:
- Judge by what the email actually says, not by how polite it is. A rejection that opens with
  "thank you for applying" is still a rejection.
- An assessment or interview invite that opens with "congratulations" is not an offer.
- Set application_index to the # of the one application the email is about. Use 0 if the email
  matches none of the listed applications, or if you cannot tell which one it is.
- Set company to the hiring company and role to the job title, exactly as the email states them.
  Fill these in even when application_index is 0. Leave either empty if neither the email nor
  its earlier thread messages say — never guess a title that isn't written down.
- Earlier thread messages are context only. They may supply the company and job title (a
  "just following up" reply rarely repeats them), but the category must describe the email
  itself, not what came before it.
- Set confidence to how certain you are of the category, from 0.0 to 1.0.
- Keep summary to one short sentence, under 120 characters.
- Return exactly one result per email, using the EMAIL ID given above.
""".strip()


def _classify_with_gemini(
    items: list[tuple[EmailMessage, list[ApplicationRow]]],
) -> dict[str, EmailVerdict]:
    """Ask Gemini about the emails the rules weren't sure of.

    Returns verdicts keyed by email id — emails the model didn't answer for are
    simply absent, leaving the caller's rule verdict in place.
    """
    verdicts: dict[str, EmailVerdict] = {}
    if not items:
        return verdicts
    if not gemini_client.is_configured():
        print("[classifier] no Gemini key configured — keeping rule verdicts")
        return verdicts

    shortlists = {message.id: candidates for message, candidates in items}
    total_batches = (len(items) + _GEMINI_BATCH_SIZE - 1) // _GEMINI_BATCH_SIZE

    for index in range(0, len(items), _GEMINI_BATCH_SIZE):
        batch = items[index:index + _GEMINI_BATCH_SIZE]
        batch_num = index // _GEMINI_BATCH_SIZE + 1
        print(f"[classifier] Gemini request {batch_num}/{total_batches} ({len(batch)} email(s))...")
        try:
            results = gemini_client.generate_json(
                system_instruction=_build_prompt(batch),
                contents="Classify the emails.",
                response_schema=list[EmailAnalysis],
            )
        except gemini_client.GeminiUnavailableError as e:
            print(f"[classifier] Gemini unavailable ({e}) — keeping rule verdicts for this batch")
            continue
        except Exception as e:  # noqa: BLE001 - a bad batch must not sink the run
            print(f"[classifier] Gemini request {batch_num} failed ({type(e).__name__}: {e}) — keeping rule verdicts")
            continue

        for result in results or []:
            category = _CATEGORY_BY_VALUE.get((result.category or "").strip().lower())
            if category is None or result.email_id not in shortlists:
                continue
            # Only trust an application the model was actually offered.
            shortlist = shortlists[result.email_id]
            index = result.application_index
            row = shortlist[index - 1] if 1 <= index <= len(shortlist) else None
            verdicts[result.email_id] = EmailVerdict(
                category=category,
                confidence=max(0.0, min(1.0, result.confidence)),
                summary=(result.summary or "").strip(),
                source="gemini",
                matched_row=row,
                company=(result.company or "").strip(),
                role=(result.role or "").strip(),
            )
    return verdicts


def _escalation_reason(
    message: EmailMessage,
    verdict: EmailVerdict,
    needs_review: set[str],
    related: set[str],
    unmatched: set[str],
) -> str:
    """Why this email deserves a Gemini call, or "" if the rules should stand.

    Every path needs real evidence the email is about a job — a genuine phrase
    signal or a company you applied to. Against a sheet of thousands of rows
    and an inbox full of promotions, anything weaker sends junk to Gemini.
    """
    confident = verdict.confidence >= RULES_CONFIDENCE_FLOOR
    signal = verdict.category in ACTIONABLE_CATEGORIES and verdict.rule_score >= ACTIONABLE_SIGNAL_FLOOR

    if not confident and (message.id in related or signal):
        return REASON_UNCLEAR
    if confident and verdict.category in ACTIONABLE_CATEGORIES and message.id in needs_review:
        return REASON_WHICH_ROW
    # Good news that can't be tied to a row still gets a notification; ask for
    # the company and role so it doesn't arrive as "Unknown company".
    if confident and verdict.category in POSITIVE_CATEGORIES and message.id in unmatched:
        return REASON_DETAILS
    return ""


def classify(
    messages: list[EmailMessage],
    candidates_for: dict[str, list[ApplicationRow]],
    needs_review: set[str] | None = None,
    related: set[str] | None = None,
    unmatched: set[str] | None = None,
    context_for: Callable[[EmailMessage], str] | None = None,
) -> dict[str, EmailVerdict]:
    """Classify every message, escalating only the unclear ones to Gemini.

    `candidates_for` maps email id to the shortlist of applications it might
    refer to; `needs_review` names emails whose row match was a coin flip;
    `related` names emails with real evidence of being about an application;
    `unmatched` names emails no row could be found for. Each verdict records in
    `escalation` why it went to Gemini, if it did. `context_for` fetches the
    rest of an email's thread; it's only called for emails sent to Gemini.
    """
    needs_review = needs_review or set()
    related = related or set()
    unmatched = unmatched or set()
    verdicts: dict[str, EmailVerdict] = {}
    escalated: list[tuple[EmailMessage, list[ApplicationRow]]] = []

    for message in messages:
        verdict = classify_by_rules(message)
        verdict.escalation = _escalation_reason(message, verdict, needs_review, related, unmatched)
        # A faint hint that isn't worth asking Gemini about isn't worth naming
        # either: "expires in" makes a promo score as an assessment, and a log
        # that says so reads like a false alarm. Its confidence is already below
        # anything that gets acted on, so this only changes the label.
        if (not verdict.escalation and verdict.category in ACTIONABLE_CATEGORIES
                and verdict.rule_score < ACTIONABLE_SIGNAL_FLOOR):
            verdict.category = EmailCategory.OTHER
        verdicts[message.id] = verdict
        if verdict.escalation:
            shortlist = candidates_for.get(message.id, [])[:_MAX_CANDIDATES_PER_EMAIL]
            escalated.append((message, shortlist))

    if escalated:
        print(f"[classifier] {len(messages) - len(escalated)} email(s) settled by rules, "
              f"{len(escalated)} sent to Gemini")
        if context_for:
            for message, _ in escalated:
                message.thread_context = context_for(message)
        for message_id, answer in _classify_with_gemini(escalated).items():
            # Keep the audit trail: why it was asked, and what the rules found.
            answer.escalation = verdicts[message_id].escalation
            answer.rule_score = verdicts[message_id].rule_score
            verdicts[message_id] = answer
    else:
        print(f"[classifier] all {len(messages)} email(s) settled by rules")

    return verdicts
