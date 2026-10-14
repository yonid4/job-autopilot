"""Unit tests for prefilter.py. Pure functions, no network.

The JD cases are ported from faang_scraper's tests/test_prefilter.py. Run with:

    pytest test_prefilter.py
"""

import pytest

import prefilter


# ── Title rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title",
    [
        "Senior Software Engineer",
        "Sr Software Engineer",
        "Sr. Backend Engineer",
        "Staff Engineer, Platform",
        "Principal Platform Software Engineer",
        "Lead Software Engineer",
        "Engineering Manager",
        "Director of Engineering",
        "Solutions Architect",
        "Software Engineering Intern",
        "Software Engineer Co-op",
        "SENIOR SOFTWARE ENGINEER",
    ],
)
def test_title_rejected(title: str) -> None:
    assert prefilter.title_reject_reason(title) is not None


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer",
        "Software Engineer 2",
        "Forward Deployed Engineer",
        "Solutions Engineer, Enterprise",
        "Full Stack Engineer",
        "Member of Technical Staff, Applied AI",   # "staff" here is not seniority
        "Engineering Leadership Software Engineer",  # "leadership" survives "lead"
        "Software Engineer, Architecture Guild",     # "architecture" survives "architect"
        "",
    ],
)
def test_title_kept(title: str) -> None:
    assert prefilter.title_reject_reason(title) is None


# ── JD rules ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "jd",
    [
        "0-2 years of experience building web services.",
        "1-3 years of experience with backend systems.",
        "1+ year of experience with Python.",
        "2+ years of experience in software development",
        "Two years of experience with Java required.",
        "Bachelor's degree in CS or related field, or 4 years of equivalent experience.",
        "BS in Computer Science. 5+ years of experience preferred.",
        "For over 20 years, our company has had experience serving banks.",
        "A 4-year degree and experience with APIs.",
        "Salary $120,000 - $150,000 per year. Experience with Go.",
        "New grads who graduated between May 2024 and August 2026 are welcome.",
        "Open to candidates graduating between December 2025 and June 2027.",
        "No clearance required for this role.",
        "",
    ],
)
def test_jd_passes(jd: str) -> None:
    assert prefilter.jd_reject_reason(jd) is None


@pytest.mark.parametrize(
    ("jd", "reason"),
    [
        ("Requirements:\n- 3+ years of professional software engineering experience", "3+ years"),
        ("3+ years of experience in software development", "3+ years"),
        ("Three years of experience with Java required.", "3+ years"),
        ("3-5 years of backend experience.", "3+ years"),
        ("Open to candidates graduating between January 2026 and June 2027.", "graduation"),
        ("Software Engineer, New Grad (2026).\nBuild things.", "graduation"),
        ("Class of 2026 graduates only.", "graduation"),
        ("Must have an active TS/SCI clearance.", "clearance"),
        ("Ability to obtain a security clearance.", "clearance"),
    ],
)
def test_jd_rejected(jd: str, reason: str) -> None:
    assert reason in (prefilter.jd_reject_reason(jd) or "")


def test_required_years_takes_the_smallest_minimum() -> None:
    jd = "1+ years of experience with Python.\n3+ years of experience overall."
    assert prefilter.required_years(jd) == 1
