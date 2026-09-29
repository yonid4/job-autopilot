# Standard library
import re
from datetime import datetime
from enum import Enum
from typing import Optional

# Third-party
from pydantic import BaseModel, Field

# Local
from job_model import ApplicationRow

_URL_RE = re.compile(r"https?://\S+")
_ADDRESS_RE = re.compile(r"^\s*(?:\"?(?P<name>[^\"<]*?)\"?\s*)?<?(?P<email>[^<>\s]+@[^<>\s]+)>?\s*$")
_PUBLIC_MAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "aol.com", "proton.me", "protonmail.com"})


def compact_text(text: str, limit: int) -> str:
    """Text squeezed for a prompt: links become "[link]" and whitespace collapses.

    Plain-text recruiting mail spells out every link as a long tracking URL;
    left in, a handful of them crowd out the sentences that name the job.
    """
    text = _URL_RE.sub("[link]", text or "")
    return " ".join(text.split())[:limit]


class EmailCategory(str, Enum):
    """What a recruiting email is telling us about an application."""

    REJECTION = "rejection"
    ASSESSMENT = "assessment"       # online assessment / coding challenge invite
    INTERVIEW = "interview"         # phone screen, technical round, scheduling
    OFFER = "offer"                 # offer extended, "congratulations"
    ACKNOWLEDGEMENT = "acknowledgement"  # "we received your application"
    OTHER = "other"                 # newsletters, job alerts, anything unrelated


# Good news — these are the ones worth a Discord ping.
POSITIVE_CATEGORIES = frozenset({
    EmailCategory.ASSESSMENT,
    EmailCategory.INTERVIEW,
    EmailCategory.OFFER,
})

# Categories that say something concrete about an application's state and are
# therefore worth writing back to the sheet.
ACTIONABLE_CATEGORIES = POSITIVE_CATEGORIES | {
    EmailCategory.REJECTION,
    EmailCategory.ACKNOWLEDGEMENT,
}


class EmailMessage(BaseModel):
    """A single message pulled from the inbox, flattened to what we classify on."""

    id: str
    thread_id: str = ""
    subject: str = ""
    sender: str = ""              # raw From header, e.g. 'Stripe Careers <no-reply@stripe.com>'
    body: str = ""                # plain-text body, truncated
    received_at: Optional[datetime] = None
    web_link: str = ""            # opens this message in Gmail on the web
    # Earlier messages in the same thread, fetched only for emails sent to
    # Gemini. A "just following up" reply often doesn't quote the invite it
    # follows, so the job title lives only in the message before it.
    thread_context: str = ""

    @property
    def sender_name(self) -> str:
        """Display name from the From header ('Stripe Careers'), or '' if bare."""
        match = _ADDRESS_RE.match(self.sender or "")
        return (match.group("name") or "").strip() if match else ""

    @property
    def sender_email(self) -> str:
        match = _ADDRESS_RE.match(self.sender or "")
        return (match.group("email") or "").strip().lower() if match else ""

    @property
    def sender_domain(self) -> str:
        """Full domain of the sender, e.g. 'careers.stripe.com'."""
        email = self.sender_email
        return email.rsplit("@", 1)[1] if "@" in email else ""

    @property
    def is_personal_domain(self) -> bool:
        """True when the sender is on a consumer mail host, so the domain says
        nothing about which company they work for."""
        return self.sender_domain in _PUBLIC_MAIL_DOMAINS

    def received_date(self) -> str:
        """Date stamp written into the sheet, e.g. '2026-09-22'."""
        return self.received_at.strftime("%Y-%m-%d") if self.received_at else ""

    def preview(self, limit: int = 4000) -> str:
        """Body squeezed for a prompt — see compact_text."""
        return compact_text(self.body, limit)


class EmailVerdict(BaseModel):
    """The classifier's reading of one email."""

    category: EmailCategory = EmailCategory.OTHER
    confidence: float = 0.0
    summary: str = ""
    source: str = "rules"                 # "rules" or "gemini"
    # Set only when Gemini picked an application out of the shortlist; the
    # rule-based matcher's own choice is tracked separately by the caller.
    matched_row: Optional[ApplicationRow] = None
    # Weighted phrase score behind a rule verdict — how much evidence it rests on.
    rule_score: int = 0
    # Why the email was sent to Gemini; "" when the rules settled it alone.
    escalation: str = ""
    # Company and job title as the email itself states them (Gemini only). Used
    # when the email can't be tied to a row in the sheet.
    company: str = ""
    role: str = ""

    @property
    def is_positive(self) -> bool:
        return self.category in POSITIVE_CATEGORIES

    @property
    def is_actionable(self) -> bool:
        return self.category in ACTIONABLE_CATEGORIES


class EmailAnalysis(BaseModel):
    """Gemini's structured response for one ambiguous email (response_schema)."""

    email_id: str = Field(description="Copy the EMAIL ID exactly as provided")
    category: str = Field(description="One of: rejection, assessment, interview, offer, acknowledgement, other")
    application_index: int = Field(description="The # of the matching application from the candidate list, or 0 if none match")
    confidence: float = Field(description="Confidence in the category, 0.0 to 1.0")
    summary: str = Field(description="One short sentence describing what the email says")
    company: str = Field(description="Hiring company named in the email, or empty if none is stated")
    role: str = Field(description="Job title named in the email, or empty if none is stated")
