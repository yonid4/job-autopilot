"""Unit tests for matching, re-sending and logging in qualifiar.filtered_jobs.
No network: call_gemini is stubbed. Run with:

    pytest test_qualifier_logging.py
"""

import pytest

from config import Config as config

# qualifiar builds a Gemini client at import time and needs a key to do it.
config.GEMINI_API_KEYS = config.GEMINI_API_KEYS or ["test-key"]

import qualifiar  # noqa: E402
from job_model import Job  # noqa: E402
from qualifiar import GeminiOverloadError, QualifierData  # noqa: E402


def make_job(n: int) -> Job:
    return Job(company="Oracle", role=f"Software Engineer {n}", link=f"https://www.linkedin.com/jobs/view/{n}")


def make_result(job_number: int, score: int, gap: str = "Needs  5 years\nof Go.") -> QualifierData:
    return QualifierData(
        qualification_score=score,
        ai_reasoning="Strong Python skills. However, the role needs Go.",
        matching_strengths=["Python"],
        main_gap=gap,
        job_number=job_number,
    )


def stub_gemini(monkeypatch: pytest.MonkeyPatch, *responses) -> list[list[Job]]:
    """Each call returns the next response (raised if it's an exception).
    Returns the list of job batches Gemini was sent, for asserting re-sends."""
    sent: list[list[Job]] = []
    queue = list(responses)

    def fake(jobs, resume):
        sent.append(list(jobs))
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(qualifiar, "call_gemini", fake)
    return sent


def test_results_match_by_job_number_not_order(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [make_job(1), make_job(2)]
    stub_gemini(monkeypatch, [make_result(2, 85), make_result(1, 90)])

    qualified = qualifiar.filtered_jobs(jobs, resume=None)

    assert [(j.link, j.score) for j in qualified] == [(jobs[0].link, 90), (jobs[1].link, 85)]


def test_rejected_jobs_are_logged_with_score_and_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_gemini(monkeypatch, [make_result(1, 62), make_result(2, 85)])

    qualified = qualifiar.filtered_jobs([make_job(1), make_job(2)], resume=None)

    out = capsys.readouterr().out
    assert [j.role for j in qualified] == ["Software Engineer 2"]
    assert "[gemini] rejected (score 62): Oracle — Software Engineer 1 — gap: Needs 5 years of Go." in out
    assert "Software Engineer 2" not in out


def test_long_gap_is_truncated(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stub_gemini(monkeypatch, [make_result(1, 40, gap="x" * 1000)])

    qualifiar.filtered_jobs([make_job(1)], resume=None)

    line = capsys.readouterr().out.strip()
    assert line.endswith("…") and len(line) < 400


def test_reasoning_is_logged_when_gap_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_gemini(monkeypatch, [make_result(1, 50, gap="")])

    qualifiar.filtered_jobs([make_job(1)], resume=None)

    assert "gap: Strong Python skills. However, the role needs Go." in capsys.readouterr().out


def test_bad_numbers_are_ignored_and_the_job_is_resent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    jobs = [make_job(1), make_job(2)]
    # JOB 2 gets an out-of-range number and a duplicate of JOB 1; the re-send
    # carries only JOB 2, which is JOB 1 of that smaller batch.
    sent = stub_gemini(
        monkeypatch,
        [make_result(1, 90), make_result(1, 95), make_result(7, 88)],
        [make_result(1, 84)],
    )

    qualified = qualifiar.filtered_jobs(jobs, resume=None)

    out = capsys.readouterr().out
    assert sent == [jobs, [jobs[1]]]
    assert [(j.role, j.score) for j in qualified] == [("Software Engineer 1", 90), ("Software Engineer 2", 84)]
    assert "second score 95 for JOB 1 (Oracle — Software Engineer 1), ignored" in out
    assert "score 88 for job number 7 (sent 2), ignored" in out
    assert "no usable score for 1 job(s), re-sending them once" in out
    assert "no score returned" not in out


def test_job_still_unscored_after_resend_is_logged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent = stub_gemini(monkeypatch, None, [])

    assert qualifiar.filtered_jobs([make_job(1)], resume=None) == []

    assert len(sent) == 2
    assert "no score returned for Oracle — Software Engineer 1 (https://www.linkedin.com/jobs/view/1)" in (
        capsys.readouterr().out
    )


def test_overload_on_resend_keeps_first_pass_scores(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_gemini(monkeypatch, [make_result(1, 90)], GeminiOverloadError("prompt"))

    qualified = qualifiar.filtered_jobs([make_job(1), make_job(2)], resume=None)

    out = capsys.readouterr().out
    assert [j.role for j in qualified] == ["Software Engineer 1"]
    assert "503 overload on the re-send" in out
    assert "no score returned for Oracle — Software Engineer 2" in out


def test_quota_failure_on_resend_keeps_first_pass_scores(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_gemini(monkeypatch, [make_result(1, 90)], RuntimeError("All Gemini API keys exhausted their quota"))

    qualified = qualifiar.filtered_jobs([make_job(1), make_job(2)], resume=None)

    assert [j.role for j in qualified] == ["Software Engineer 1"]
    assert "re-send failed: All Gemini API keys exhausted their quota" in capsys.readouterr().out


def test_overload_on_first_call_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_gemini(monkeypatch, GeminiOverloadError("prompt"))

    with pytest.raises(GeminiOverloadError):
        qualifiar.filtered_jobs([make_job(1)], resume=None)
