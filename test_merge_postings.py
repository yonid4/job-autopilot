"""Unit tests for prefilter.merge_same_postings. Pure, no network. Run with:

    pytest test_merge_postings.py
"""

import pytest

import prefilter
from job_model import Job


def make_job(n: int, *, role: str = "Cyber Full-Stack Engineer", description: str | None = "Build  tools.\n",
             company: str = "Deloitte") -> Job:
    return Job(company=company, role=role, description=description, link=f"https://www.linkedin.com/jobs/view/{n}")


def test_same_company_title_and_description_merge_to_first(capsys: pytest.CaptureFixture[str]) -> None:
    jobs = [make_job(1), make_job(2, description="Build tools."), make_job(3, role="cyber full-stack engineer ")]

    kept = prefilter.merge_same_postings(jobs)

    assert [j.link for j in kept] == ["https://www.linkedin.com/jobs/view/1"]
    assert ("[dedup] Deloitte — Cyber Full-Stack Engineer: 3 postings with the same description, scoring "
            "https://www.linkedin.com/jobs/view/1 only (also https://www.linkedin.com/jobs/view/2, "
            "https://www.linkedin.com/jobs/view/3)") in capsys.readouterr().out


@pytest.mark.parametrize("other", [
    make_job(2, description="Different team, different work."),
    make_job(2, role="Software Engineer"),
    make_job(2, company="Slalom"),
])
def test_any_difference_keeps_both(other: Job, capsys: pytest.CaptureFixture[str]) -> None:
    assert len(prefilter.merge_same_postings([make_job(1), other])) == 2
    assert "[dedup]" not in capsys.readouterr().out


def test_jobs_without_description_are_never_merged() -> None:
    jobs = [make_job(1, description=None), make_job(2, description=None)]

    assert prefilter.merge_same_postings(jobs) == jobs
