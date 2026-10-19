"""Unit tests for the Gemini result logging in qualifiar.filtered_jobs.
No network: call_gemini is stubbed. Run with:

    pytest test_qualifier_logging.py
"""

import pytest

from config import Config as config

# qualifiar builds a Gemini client at import time and needs a key to do it.
config.GEMINI_API_KEYS = config.GEMINI_API_KEYS or ["test-key"]

import qualifiar  # noqa: E402
from job_model import Job  # noqa: E402
from qualifiar import QualifierData  # noqa: E402


def make_job(n: int) -> Job:
    return Job(company="Oracle", role=f"Software Engineer {n}", link=f"https://www.linkedin.com/jobs/view/{n}")


def make_result(n: int, score: int, reasoning: str = "Needs  5 years\nof Go.") -> QualifierData:
    return QualifierData(
        qualification_score=score,
        ai_reasoning=reasoning,
        matching_strengths=["Python"],
        job_link=f"https://www.linkedin.com/jobs/view/{n}",
    )


def run(monkeypatch: pytest.MonkeyPatch, jobs: list[Job], results: list[QualifierData]) -> list[Job]:
    monkeypatch.setattr(qualifiar, "call_gemini", lambda jobs, resume: results)
    return qualifiar.filtered_jobs(jobs, resume=None)


def test_rejected_jobs_are_logged_with_score_and_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    qualified = run(monkeypatch, [make_job(1), make_job(2)], [make_result(1, 62), make_result(2, 85)])

    out = capsys.readouterr().out
    assert [j.link for j in qualified] == ["https://www.linkedin.com/jobs/view/2"]
    assert "[gemini] rejected (score 62): Oracle — Software Engineer 1 — Needs 5 years of Go." in out
    assert "Software Engineer 2" not in out


def test_long_reasoning_is_truncated(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run(monkeypatch, [make_job(1)], [make_result(1, 40, reasoning="x" * 1000)])

    line = capsys.readouterr().out.strip()
    assert line.endswith("…") and len(line) < 400


def test_unknown_link_and_missing_score_are_logged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    qualified = run(monkeypatch, [make_job(1)], [make_result(9, 95)])

    out = capsys.readouterr().out
    assert qualified == []
    assert "score 95 for unknown link 'https://www.linkedin.com/jobs/view/9', dropped" in out
    assert "no score returned for Oracle — Software Engineer 1" in out
