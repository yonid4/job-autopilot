"""Unit tests for the Discord job digest in discord_notifier.py. No network:
the webhook POST is stubbed. Run with:

    pytest test_discord_jobs.py
"""

import pytest

import discord_notifier
from job_model import Job


def make_job(n: int = 0, *, score: int = 85, notes: str = "Good fit.", track: str = "A") -> Job:
    return Job(
        company="Oracle",
        role=f"Software Engineer {n}",
        link=f"https://www.linkedin.com/jobs/view/{n}",
        score=score,
        notes=notes,
        track=track,
    )


def test_empty_run_is_a_heartbeat() -> None:
    messages = discord_notifier.build_job_messages([])
    assert messages == [{"content": discord_notifier._HEARTBEAT_CONTENT}]


def test_note_is_appended_to_the_first_message() -> None:
    assert "⚠️ boom" in discord_notifier.build_job_messages([], note="⚠️ boom")[0]["content"]
    assert "⚠️ boom" in discord_notifier.build_job_messages([make_job()], note="⚠️ boom")[0]["content"]


def test_header_and_embed_fields() -> None:
    messages = discord_notifier.build_job_messages([make_job(1, score=92)])
    assert messages[0]["content"].startswith("🎯 1 new match ")
    embed = messages[0]["embeds"][0]
    assert embed["title"] == "Software Engineer 1"
    assert embed["url"] == "https://www.linkedin.com/jobs/view/1"
    assert embed["color"] == discord_notifier._STRONG_COLOR
    assert {f["name"]: f["value"] for f in embed["fields"]} == {
        "Company": "Oracle", "Track": "A", "Score": "92/100",
    }


def test_chunks_at_ten_embeds() -> None:
    messages = discord_notifier.build_job_messages([make_job(i) for i in range(23)])
    assert [len(m["embeds"]) for m in messages] == [10, 10, 3]
    assert "23 new matches" in messages[0]["content"]
    assert "content" not in messages[1]


def test_chunks_by_combined_characters() -> None:
    wordy = [make_job(i, notes="x" * 3000) for i in range(4)]
    messages = discord_notifier.build_job_messages(wordy)
    for message in messages:
        total = sum(discord_notifier._embed_chars(e) for e in message["embeds"])
        assert total <= discord_notifier._MESSAGE_CHARS_BUDGET
    assert sum(len(m["embeds"]) for m in messages) == 4


def test_notify_jobs_skips_without_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discord_notifier, "_post", lambda *a, **k: pytest.fail("posted"))
    assert discord_notifier.notify_jobs([make_job()], webhook_url="") == 0


def test_notify_jobs_counts_only_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([True, False, True])
    sent_to: list[str] = []

    def fake_post(payload: dict, url: str = "") -> bool:
        sent_to.append(url)
        return next(results)

    monkeypatch.setattr(discord_notifier, "_post", fake_post)
    monkeypatch.setattr(discord_notifier, "_SEND_SPACING_SECONDS", 0)
    delivered = discord_notifier.notify_jobs(
        [make_job(i) for i in range(25)], webhook_url="https://hook",
    )
    assert delivered == 10 + 5     # the middle message of 10 failed
    assert sent_to == ["https://hook"] * 3
