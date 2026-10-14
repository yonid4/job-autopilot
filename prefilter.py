"""Free prefilters that run before the paid Gemini call.

Ported from faang_scraper's jobtracker/prefilter.py. Two stages:

- `title_reject_reason(title)` runs on the search result, before the per-job
  detail fetch. LinkedIn ignores NOT in the keyword box, so senior and intern
  titles come back from the search and are culled here instead.
- `jd_reject_reason(jd)` runs on the full description once it has been
  fetched. It drops roles that require 3+ years, restrict graduation to 2026 or
  later, or require a security clearance.

Each rule only fires on an unambiguous signal; anything borderline is left for
Gemini to weigh. Pure module: imports only `config` and stdlib `re`.
"""

# Standard library
import re

# Local
from config import Config as config


def _token_patterns(terms: list[str]) -> tuple[re.Pattern[str], ...]:
    # Lookarounds rather than \b so multi-word and punctuated terms work
    # ("head of", "sr.", "co-op") and substrings never false-trigger
    # ("leadership" survives "lead"; "architecture" survives "architect").
    return tuple(
        re.compile(r"(?<!\w)" + re.escape(t.lower()) + r"(?!\w)") for t in terms
    )


# ── Title rule (before the detail fetch) ─────────────────────────────────────

_EXCLUDE_TITLE_PATTERNS = _token_patterns(config.EXCLUDE_TITLE_TERMS)


def title_reject_reason(title: str | None) -> str | None:
    """The excluded term a title contains, or None to keep the job.

    Standard IC titles like "Member of Technical Staff" are blanked first so
    their "staff" doesn't count. A blank title is kept: nothing to judge on."""
    text = (title or "").strip().lower()
    for phrase in config.IC_TITLE_PHRASES:
        text = text.replace(phrase, " ")
    for term, pattern in zip(config.EXCLUDE_TITLE_TERMS, _EXCLUDE_TITLE_PATTERNS):
        if pattern.search(text):
            return f"title contains {term!r}"
    return None


# ── JD rules (after the detail fetch, before Gemini) ─────────────────────────

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
# "3+ years", "2-4 years", "1 to 3 yrs", "5 or more years", "two years". A bare
# "4-year degree" doesn't match: after "-" the range needs a second number.
_YEARS_RE = re.compile(
    r"(?<![\w.$])" + _NUM + r"\s*(?:\+|plus)?\s*"
    r"(?:(?:-|–|—|to)\s*" + _NUM + r"\s*\+?\s*)?"
    r"(?:or more\s+|or greater\s+)?(?:years?|yrs?)(?!\w)"
)
_EXPERIENCE_RE = re.compile(r"experience|\bexp\b")
# Sentences about the company, not the candidate ("for over 20 years we've…").
_COMPANY_SENTENCE_RE = re.compile(
    r"\b(we|our|we've|we're|founded|history)\b|for over|for more than"
)
_PREFERRED_PATTERNS = _token_patterns(config.PREFERRED_MARKERS)
# "Bachelor's or 4 years of equivalent experience" is a degree substitute, not a
# years requirement for someone who has the degree.
_DEGREE_ALT_RE = re.compile(r"equivalent|in lieu|instead of a degree")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+|•")

_GRAD_RE = re.compile(r"graduat\w*|\bgrads?\b|class of|degree completion|degree conferral")
_YEAR_RE = re.compile(r"(?<!\d)(20[2-3]\d)(?!\d)")

_CLEARANCE_PATTERNS = _token_patterns(config.CLEARANCE_TERMS)
_CLEARANCE_NEGATION_PATTERNS = _token_patterns(config.CLEARANCE_NEGATIONS)


def _num(token: str) -> int:
    return int(token) if token.isdigit() else _NUM_WORDS[token]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.lower()) if s.strip()]


def required_years(jd: str) -> int | None:
    """The smallest years-of-experience minimum the JD *requires*, or None.

    Only sentences that mention experience count; preferred/nice-to-have and
    company-history sentences are skipped. Taking the smallest minimum keeps the
    rule conservative ("1+ years of Python, 3+ years overall" → 1, left for
    Gemini to weigh) — a hard drop has to be unambiguous."""
    minimums: list[int] = []
    for sentence in _sentences(jd):
        if not _EXPERIENCE_RE.search(sentence):
            continue
        if any(p.search(sentence) for p in _PREFERRED_PATTERNS):
            continue
        if _COMPANY_SENTENCE_RE.search(sentence) or _DEGREE_ALT_RE.search(sentence):
            continue
        for m in _YEARS_RE.finditer(sentence):
            minimums.append(_num(m.group(1)))
    return min(minimums) if minimums else None


def grad_years(jd: str) -> list[int]:
    """Every year named in a sentence that talks about graduation."""
    years: list[int] = []
    for sentence in _sentences(jd):
        if _GRAD_RE.search(sentence) and not _COMPANY_SENTENCE_RE.search(sentence):
            years.extend(int(y) for y in _YEAR_RE.findall(sentence))
    return years


def requires_clearance(jd: str) -> bool:
    text = (jd or "").lower()
    for p in _CLEARANCE_NEGATION_PATTERNS:
        text = p.sub(" ", text)
    return any(p.search(text) for p in _CLEARANCE_PATTERNS)


def jd_reject_reason(jd: str | None) -> str | None:
    """Why the full JD rules this job out, or None to send it to Gemini."""
    if not jd:
        return None
    years = required_years(jd)
    if years is not None and years >= config.MAX_REQUIRED_YEARS:
        return f"requires {years}+ years of experience"
    grads = grad_years(jd)
    if grads and min(grads) >= config.GRAD_YEAR_CUTOFF:
        return f"graduation window {min(grads)}–{max(grads)}"
    if requires_clearance(jd):
        return "security clearance required"
    return None
