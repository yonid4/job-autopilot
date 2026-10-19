"""Unit tests for the per-company tally in linkedin_service's track searches.
No network: the LinkedIn search is stubbed. Run with:

    pytest test_linkedin_tracks.py
"""

import pytest

import linkedin_service
from linkedin_service import config


def make_card(job_id: int, company: str) -> dict:
    return {
        "jobPostingUrn": f"urn:li:fsd_jobPosting:{job_id}",
        "primaryDescription": {"text": company},
        "title": {"text": f"Software Engineer {job_id}"},
    }


def test_counts_include_zeros_in_config_order() -> None:
    counts = linkedin_service._company_counts(
        ["Oracle", "Oracle", "Intuit"], ["Bloomberg", "Oracle", "Intuit"]
    )
    assert counts == {"Bloomberg": 0, "Oracle": 2, "Intuit": 1}


def test_counts_match_case_insensitively() -> None:
    counts = linkedin_service._company_counts(["servicenow"], ["ServiceNow"])
    assert counts == {"ServiceNow": 1}


def test_unmatched_names_are_listed_after_configured() -> None:
    counts = linkedin_service._company_counts(["Bloomberg LP"], ["Bloomberg"])
    assert counts == {"Bloomberg": 0, "Bloomberg LP": 1}


@pytest.fixture
def two_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LINKEDIN_COMPANY_TRACKS", {
        "B": {"companies": {"Oracle": "1028", "Bloomberg": "2494"}, "keywords": "software engineer"},
    })
    monkeypatch.setattr(config, "LINKEDIN_LOCATIONS", [
        {"name": "Metro", "geo_id": "1", "remote": False},
        {"name": "United States", "geo_id": "2", "remote": True},
    ])
    monkeypatch.setattr(linkedin_service.time, "sleep", lambda _: None)


def test_track_logs_per_company_and_flags_missing(
    two_locations: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The remote posting (1) shows up in both searches but counts once per track.
    pages = iter([[make_card(1, "Oracle"), make_card(2, "Oracle")], [make_card(1, "Oracle")]])
    monkeypatch.setattr(linkedin_service, "_search_cards", lambda api, query: next(pages))

    jobs, errors = linkedin_service._run_track_searches(api=None)

    out = capsys.readouterr().out
    assert len(jobs) == 2 and errors == []
    assert "track B / Metro: 2 result(s), 2 new (Oracle 2, Bloomberg 0)" in out
    assert "track B / United States: 1 result(s), 0 new (Oracle 1, Bloomberg 0)" in out
    assert "track B unique jobs per company: Oracle 2, Bloomberg 0" in out
    assert "track B: no results in any location for Bloomberg" in out


def test_no_summary_when_every_search_failed(
    two_locations: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(api, query):
        raise RuntimeError("401")

    monkeypatch.setattr(linkedin_service, "_search_cards", fail)

    jobs, errors = linkedin_service._run_track_searches(api=None)

    assert jobs == [] and len(errors) == 2
    assert "no results in any location" not in capsys.readouterr().out
