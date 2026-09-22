"""Work out which tracking-sheet row an inbox message is about.

Recruiting mail rarely names the job cleanly: it arrives from an applicant
tracking system rather than the company's own domain, the subject may be a bare
"Update on your application", and you may have several rows open at the same
company. So instead of parsing a company out of the email, this scores every
populated row against the message and takes the clear winner — and reports back
when there isn't one, so the caller can send the tie to Gemini.
"""

# Standard library
import re

# Third-party
from pydantic import BaseModel

# Local
from email_model import EmailMessage
from job_model import ApplicationRow

# Sender domains that belong to an applicant tracking system, a scheduling tool
# or a bulk-mail relay rather than the hiring company. Matched as substrings, so
# "us.greenhouse-mail.io" and "mail.greenhouse.io" both resolve.
_ATS_DOMAIN_TOKENS = (
    "greenhouse", "lever.co", "ashbyhq", "myworkday", "workday", "icims", "taleo",
    "successfactors", "smartrecruiters", "workable", "jobvite", "breezy.hr",
    "bamboohr", "recruitee", "teamtailor", "applytojob", "jazzhr", "rippling",
    "avature", "dayforcehcm", "ultipro", "brassring", "eightfold", "paradox.ai",
    "hiringthing", "phenompeople", "oraclecloud", "gem.com", "goodtime.io",
    "calendly", "hirevue", "karat.io", "codesignal", "hackerrank", "codility",
    "coderpad", "woven.teams", "indeed.com", "linkedin.com", "ziprecruiter",
    "glassdoor", "monster.com", "dice.com", "handshake", "simplify.jobs",
    "wellfound", "angel.co", "otta.com", "sendgrid", "mailgun", "amazonses",
    "mandrillapp", "sparkpostmail", "mcsv.net", "mailchimp", "hubspot",
    "salesforce.com", "notifications.google.com",
)

# Trailing noise on company names — dropped before comparing.
_LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "gmbh", "sa", "ag", "nv", "bv", "ab", "oy", "as",
    "pte", "pty", "srl", "spa", "kk", "labs", "technologies", "technology",
})

# Words that say nothing about which role this is.
_ROLE_STOPWORDS = frozenset({
    "senior", "junior", "staff", "principal", "lead", "entry", "level", "new",
    "grad", "graduate", "intern", "internship", "i", "ii", "iii", "iv", "1", "2",
    "3", "full", "time", "fulltime", "part", "contract", "remote", "hybrid",
    "onsite", "us", "usa", "and", "or", "of", "the", "a", "an", "to", "at",
    "in", "for", "with",
})

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# A row needs this much evidence before we'll write to it. Calibrated so a bare
# mention of the company in the body (2) is never enough on its own, while a
# matching sender domain (5) or a display name plus subject (4 + 3) is.
MATCH_THRESHOLD = 5


class MatchResult(BaseModel):
    """Outcome of scoring one email against the sheet."""

    row: ApplicationRow | None = None
    score: int = 0
    runner_up_score: int = 0
    ambiguous: bool = False   # a close second — worth a second opinion from Gemini

    @property
    def matched(self) -> bool:
        return self.row is not None


def _normalize(text: str) -> str:
    """Lowercase, and reduce every run of punctuation to a single space."""
    return _NON_ALNUM_RE.sub(" ", (text or "").lower()).strip()


def _squash(text: str) -> str:
    """Normalized text with the spaces removed — 'Acme Robotics' -> 'acmerobotics'."""
    return _normalize(text).replace(" ", "")


def company_key(company: str) -> str:
    """Company name reduced to its distinctive words ('Stripe, Inc.' -> 'stripe')."""
    words = [w for w in _normalize(company).split() if w and w not in _LEGAL_SUFFIXES]
    # Everything was a suffix (e.g. a row literally named "The Company") — keep
    # the original words rather than returning nothing to match on.
    return " ".join(words) if words else _normalize(company)


def _is_ats_domain(domain: str) -> bool:
    return any(token in domain for token in _ATS_DOMAIN_TOKENS)


def domain_root(domain: str) -> str:
    """The company-ish label of a domain: 'careers.stripe.com' -> 'stripe'.

    Returns '' for applicant tracking systems and bulk senders, whose domain
    says nothing about who is hiring.
    """
    domain = (domain or "").lower().strip()
    if not domain or _is_ats_domain(domain):
        return ""
    labels = [label for label in domain.split(".") if label]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu"}:
        labels = labels[:-2]          # acme.co.uk -> acme
    elif len(labels) >= 2:
        labels = labels[:-1]          # careers.stripe.com -> careers.stripe
    return labels[-1] if labels else ""


def _company_pattern(key: str) -> re.Pattern:
    """Whole-word matcher for a company key, tolerant of how the words are
    separated ('acme robotics' also matches 'acme-robotics')."""
    return re.compile(r"\b" + r"\s+".join(re.escape(w) for w in key.split()) + r"\b")


def _role_words(role: str) -> list[str]:
    return [w for w in _normalize(role).split() if w and w not in _ROLE_STOPWORDS]


def _domains_align(root: str, squashed_company: str) -> bool:
    """Whether a sender domain root and a company name refer to the same thing.

    Requires 4+ characters before accepting a containment match, so 'ai' or 'hr'
    inside an unrelated domain doesn't count.
    """
    if not root or not squashed_company:
        return False
    if root == squashed_company:
        return True
    shorter = min(root, squashed_company, key=len)
    return len(shorter) >= 4 and (root in squashed_company or squashed_company in root)


def score_row(message: EmailMessage, row: ApplicationRow) -> int:
    """How strongly this email points at this row. Higher is better; 0 is no signal."""
    subject = _normalize(message.subject)
    body = _normalize(message.body)
    sender_name = _normalize(message.sender_name)

    score = 0

    # The job link pasted into the email is as direct as evidence gets.
    if row.link and row.link.strip() and row.link.strip() in (message.body or ""):
        score += 6

    key = company_key(row.company)
    if key:
        squashed = key.replace(" ", "")
        root = "" if message.is_personal_domain else domain_root(message.sender_domain)
        if _domains_align(root, squashed):
            score += 5
        # One- and two-character names ("X", "HP") are too collision-prone to
        # trust in free text — they only count via the domain or the job link.
        if len(squashed) > 2:
            pattern = _company_pattern(key)
            if pattern.search(sender_name):
                score += 4
            if pattern.search(subject):
                score += 3
            if pattern.search(body):
                score += 2

    # Role wording separates several open applications at the same company.
    words = _role_words(row.role)
    if words:
        if sum(1 for w in words if w in subject) / len(words) >= 0.5:
            score += 2
        if sum(1 for w in words if w in body) / len(words) >= 0.6:
            score += 1

    return score


def rank_candidates(message: EmailMessage, rows: list[ApplicationRow]) -> list[tuple[int, ApplicationRow]]:
    """Every row with any signal at all, best first."""
    scored = [(score_row(message, row), row) for row in rows]
    return sorted([s for s in scored if s[0] > 0], key=lambda s: (-s[0], s[1].row))


def best_match(message: EmailMessage, rows: list[ApplicationRow]) -> MatchResult:
    """Pick the row this email is about.

    A result is `ambiguous` when the runner-up scores within a point of the
    winner — typically two open roles at the same company, where the email
    itself has to be read to tell them apart.
    """
    ranked = rank_candidates(message, rows)
    if not ranked:
        return MatchResult()

    top_score, top_row = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0

    if top_score < MATCH_THRESHOLD:
        # Not enough to write on, but the caller may still hand the near-misses
        # to Gemini, so report what the best guess would have been.
        return MatchResult(score=top_score, runner_up_score=runner_up, ambiguous=True)

    return MatchResult(
        row=top_row,
        score=top_score,
        runner_up_score=runner_up,
        ambiguous=runner_up >= top_score - 1,
    )
