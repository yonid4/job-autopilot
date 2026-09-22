"""Which sheet status an email implies, and whether it's allowed to overwrite
what's already in the Application Status column.

The status strings must match the dropdown in your sheet exactly — override them
in config.py if your tracker uses different wording.
"""

# Local
from config import Config as config
from email_model import EmailCategory

# Status strings written into column B. Sourced from config so they can be lined
# up with the sheet's data-validation dropdown without touching this file.
STATUS_NOT_APPLIED = getattr(config, "STATUS_ON_SCRAPE", "Have Not Applied")
STATUS_APPLIED = getattr(config, "STATUS_APPLIED", "Applied")
STATUS_ASSESSMENT = getattr(config, "STATUS_ASSESSMENT", "Online Assessment")
STATUS_INTERVIEW = getattr(config, "STATUS_INTERVIEW", "Interviewing")
STATUS_OFFER = getattr(config, "STATUS_OFFER", "Offer")
STATUS_REJECTED = getattr(config, "STATUS_REJECTED", "Rejected")

_CATEGORY_TO_STATUS = {
    EmailCategory.ACKNOWLEDGEMENT: STATUS_APPLIED,
    EmailCategory.ASSESSMENT: STATUS_ASSESSMENT,
    EmailCategory.INTERVIEW: STATUS_INTERVIEW,
    EmailCategory.OFFER: STATUS_OFFER,
    EmailCategory.REJECTION: STATUS_REJECTED,
}

# How far along the funnel each status sits. A row only ever moves up this
# ladder, so a late "thanks for applying" auto-reply can't knock a row back down
# from Interviewing. Rejection ranks highest because it's terminal news: it
# lands whatever the row currently says.
_RANK = {
    STATUS_NOT_APPLIED.lower(): 0,
    STATUS_APPLIED.lower(): 1,
    STATUS_ASSESSMENT.lower(): 2,
    STATUS_INTERVIEW.lower(): 3,
    STATUS_OFFER.lower(): 4,
    STATUS_REJECTED.lower(): 5,
}

# Wording used by other trackers / the sheet template, folded onto the ranks
# above so an unfamiliar status still compares sensibly.
_RANK_ALIASES = {
    "have not applied": 0,
    "not applied": 0,
    "to apply": 0,
    "applied": 1,
    "in progress": 1,
    "submitted": 1,
    "oa": 2,
    "online assessment": 2,
    "assessment": 2,
    "take home": 2,
    "interviewing": 3,
    "interview": 3,
    "phone screen": 3,
    "onsite": 3,
    "final round": 3,
    "offer": 4,
    "accepted": 4,
    "rejected": 5,
    "declined": 5,
    "closed": 5,
    "no longer under consideration": 5,
}


def status_for(category: EmailCategory) -> str | None:
    """The sheet status an email of this category implies, or None if it
    shouldn't touch the status column."""
    return _CATEGORY_TO_STATUS.get(category)


def rank(status: str) -> int:
    """Funnel position of a status string. Unknown statuses rank 0 so they can
    still be moved forward rather than being treated as terminal."""
    key = (status or "").strip().lower()
    if key in _RANK:
        return _RANK[key]
    return _RANK_ALIASES.get(key, 0)


def is_upgrade(current: str, new: str) -> bool:
    """True when `new` moves the row further along than `current`.

    Equal ranks return False, so re-processing the same email (or a second
    interview email for a row already marked Interviewing) is a no-op.
    """
    return rank(new) > rank(current)
