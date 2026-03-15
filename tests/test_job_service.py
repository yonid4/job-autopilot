from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job_row(url: str = "https://www.linkedin.com/jobs/view/123", **kwargs) -> dict:
    return {
        "id": str(uuid4()),
        "url": url,
        "title": kwargs.get("title", "Software Engineer"),
        "company": kwargs.get("company", "Acme Corp"),
        "description": kwargs.get("description", "A great job"),
        "salary": None,
        "job_level": None,
    }


# ---------------------------------------------------------------------------
# _job_id_from_url
# ---------------------------------------------------------------------------

class TestJobIdFromUrl:
    def test_standard_linkedin_url(self):
        from app.services.job_service import _job_id_from_url
        url = "https://www.linkedin.com/jobs/view/1234567890"
        assert _job_id_from_url(url) == "1234567890"

    def test_url_with_trailing_slash(self):
        from app.services.job_service import _job_id_from_url
        url = "https://www.linkedin.com/jobs/view/9876543210/"
        assert _job_id_from_url(url) == "9876543210"

    def test_url_with_query_params(self):
        from app.services.job_service import _job_id_from_url
        url = "https://www.linkedin.com/jobs/view/111222333/?refId=abc"
        # strips trailing slash but query params don't affect view/ parsing
        result = _job_id_from_url(url)
        assert result is not None

    def test_non_numeric_returns_none(self):
        from app.services.job_service import _job_id_from_url
        url = "https://www.linkedin.com/jobs/view/not-a-number"
        assert _job_id_from_url(url) is None

    def test_empty_url_returns_none(self):
        from app.services.job_service import _job_id_from_url
        assert _job_id_from_url("") is None


# ---------------------------------------------------------------------------
# ingest_job_by_url — dedup (URL already exists)
# ---------------------------------------------------------------------------

class TestIngestJobByUrl:
    @patch("app.services.job_service.database.find_job_by_url")
    def test_returns_existing_job_when_found(self, mock_find):
        from app.services.job_service import ingest_job_by_url

        existing = _make_job_row()
        mock_find.return_value = existing

        job, is_new = ingest_job_by_url(existing["url"])

        assert job is existing
        assert is_new is False
        mock_find.assert_called_once_with(existing["url"])

    @patch("app.services.job_service._scrape_linkedin_job")
    @patch("app.services.job_service._store_job")
    @patch("app.services.job_service.database.find_job_by_url")
    def test_scrapes_and_stores_when_not_found(self, mock_find, mock_store, mock_scrape):
        from app.services.job_service import ingest_job_by_url

        mock_find.return_value = None
        scraped = _make_job_row(url="https://www.linkedin.com/jobs/view/999")
        mock_scrape.return_value = scraped
        stored = {**scraped, "id": str(uuid4())}
        mock_store.return_value = stored

        job, is_new = ingest_job_by_url("https://www.linkedin.com/jobs/view/999")

        assert is_new is True
        assert job is stored
        mock_scrape.assert_called_once()
        mock_store.assert_called_once_with(scraped)

    @patch("app.services.job_service._scrape_linkedin_job")
    @patch("app.services.job_service.database.find_job_by_url")
    def test_raises_when_scrape_fails(self, mock_find, mock_scrape):
        from app.services.job_service import ingest_job_by_url

        mock_find.return_value = None
        mock_scrape.return_value = None

        with pytest.raises(ValueError, match="Could not scrape job"):
            ingest_job_by_url("https://www.linkedin.com/jobs/view/000")


# ---------------------------------------------------------------------------
# ingest_job_manual — dedup (URL then title+company)
# ---------------------------------------------------------------------------

class TestIngestJobManual:
    @patch("app.services.job_service._find_existing_job")
    def test_returns_existing_without_storing(self, mock_find):
        from app.services.job_service import ingest_job_manual

        existing = _make_job_row()
        mock_find.return_value = existing

        job, is_new = ingest_job_manual(
            url=existing["url"],
            title=existing["title"],
            company=existing["company"],
        )

        assert job is existing
        assert is_new is False

    @patch("app.services.job_service._store_job")
    @patch("app.services.job_service._find_existing_job")
    def test_stores_new_job(self, mock_find, mock_store):
        from app.services.job_service import ingest_job_manual

        mock_find.return_value = None
        stored = _make_job_row()
        mock_store.return_value = stored

        job, is_new = ingest_job_manual(
            url="https://www.linkedin.com/jobs/view/42",
            title="Data Scientist",
            company="BigCo",
            description="Build ML models",
        )

        assert is_new is True
        assert job is stored
        call_data = mock_store.call_args[0][0]
        assert call_data["title"] == "Data Scientist"
        assert call_data["company"] == "BigCo"


# ---------------------------------------------------------------------------
# _store_job — embeds description before upsert
# ---------------------------------------------------------------------------

class TestStoreJob:
    @patch("app.services.job_service.database.upsert_job")
    @patch("app.services.job_service.embed_text")
    def test_embeds_description_and_upserts(self, mock_embed, mock_upsert):
        from app.services.job_service import _store_job

        embedding = [0.1] * 768
        mock_embed.return_value = embedding
        stored = _make_job_row()
        mock_upsert.return_value = stored

        data = {
            "url": "https://www.linkedin.com/jobs/view/1",
            "title": "Engineer",
            "company": "Acme",
            "description": "Some description",
        }
        result = _store_job(data)

        mock_embed.assert_called_once()
        upsert_data = mock_upsert.call_args[0][0]
        assert upsert_data["embedding"] == embedding
        assert result is stored

    @patch("app.services.job_service.database.upsert_job")
    @patch("app.services.job_service.embed_text")
    def test_skips_embedding_when_no_description(self, mock_embed, mock_upsert):
        from app.services.job_service import _store_job

        stored = _make_job_row(description=None)
        mock_upsert.return_value = stored

        _store_job({"url": "https://x.com", "title": "T", "company": "C", "description": None})

        mock_embed.assert_not_called()


# ---------------------------------------------------------------------------
# create_project — embeds and inserts
# ---------------------------------------------------------------------------

class TestCreateProject:
    @patch("app.services.job_service.database.insert_project")
    @patch("app.services.job_service.embed_text")
    def test_embeds_and_inserts(self, mock_embed, mock_insert):
        from app.services.job_service import create_project

        embedding = [0.5] * 768
        mock_embed.return_value = embedding
        user_id = str(uuid4())
        project_row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "name": "My Project",
            "description": "A cool app",
            "technologies": ["Python", "FastAPI"],
            "url": "https://github.com/me/project",
        }
        mock_insert.return_value = project_row

        result = create_project(
            user_id=user_id,
            name="My Project",
            description="A cool app",
            technologies=["Python", "FastAPI"],
            url="https://github.com/me/project",
        )

        mock_embed.assert_called_once()
        insert_data = mock_insert.call_args[0][0]
        assert insert_data["embedding"] == embedding
        assert insert_data["user_id"] == user_id
        assert result is project_row
