from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

USER_ID = str(uuid4())
JOB_ID = str(uuid4())
RESUME_ID = str(uuid4())
APP_ID = str(uuid4())
PROJECT_ID = str(uuid4())

FAKE_EMBEDDING = [0.1] * 768

FAKE_JOB = {
    "id": JOB_ID,
    "url": "https://www.linkedin.com/jobs/view/1",
    "title": "Software Engineer",
    "company": "Acme",
    "description": "Build great software.",
}

FAKE_RESUME = {
    "id": RESUME_ID,
    "user_id": USER_ID,
    "label": "default",
    "storage_path": "resumes/test.pdf",
    "is_active": True,
}

FAKE_CHUNKS = [
    {"content": "Experienced in Python and FastAPI.", "section": "experience", "chunk_index": 0},
    {"content": "Built scalable microservices.", "section": "experience", "chunk_index": 1},
]

FAKE_PROJECT = {
    "id": PROJECT_ID,
    "name": "MyApp",
    "description": "A cool SaaS app",
    "technologies": ["Python", "FastAPI"],
    "url": "https://github.com/me/myapp",
    "similarity": 0.92,
}

FAKE_APP_ROW = {
    "id": APP_ID,
    "user_id": USER_ID,
    "job_id": JOB_ID,
    "resume_id": RESUME_ID,
    "status": "not_applied",
    "fit_score": 82,
    "strengths": ["Python", "FastAPI"],
    "gaps": ["Kubernetes"],
    "summary_text": "Experienced engineer...",
    "cover_letter": "Dear Hiring Manager...",
    "hook_project_id": PROJECT_ID,
}


def _patch_db_and_gemini(
    job=FAKE_JOB,
    resume=FAKE_RESUME,
    chunks=FAKE_CHUNKS,
    project=FAKE_PROJECT,
    qualify_result=None,
    summary="Experienced engineer...",
    cover_letter="Dear Hiring Manager...",
    app_row=FAKE_APP_ROW,
):
    qualify_result = qualify_result or {"score": 82, "strengths": ["Python", "FastAPI"], "gaps": ["Kubernetes"]}
    return [
        patch("app.services.tailoring_engine.database.get_job_by_id", return_value=job),
        patch("app.services.tailoring_engine.database.get_active_resume", return_value=resume),
        patch("app.services.tailoring_engine.database.get_resume_by_id", return_value=resume),
        patch("app.services.tailoring_engine.database.match_resume_chunks", return_value=chunks),
        patch("app.services.tailoring_engine.database.match_best_project", return_value=project),
        patch("app.services.tailoring_engine.database.upsert_application", return_value=app_row),
        patch("app.services.tailoring_engine.embed_query", return_value=FAKE_EMBEDDING),
        patch("app.services.tailoring_engine.qualify_job", return_value=qualify_result),
        patch("app.services.tailoring_engine.generate_summary", return_value=summary),
        patch("app.services.tailoring_engine.generate_cover_letter", return_value=cover_letter),
    ]


# ---------------------------------------------------------------------------
# tailor_resume
# ---------------------------------------------------------------------------

class TestTailorResume:
    def test_full_flow_with_active_resume(self):
        from app.services.tailoring_engine import tailor_resume

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6], patches[7], patches[8], patches[9]:
            result = tailor_resume(user_id=USER_ID, job_id=JOB_ID)

        assert result["fit_score"] == 82
        assert result["strengths"] == ["Python", "FastAPI"]
        assert result["gaps"] == ["Kubernetes"]
        assert result["summary_text"] == "Experienced engineer..."
        assert "application_id" in result
        # cover_letter should NOT be in tailor_resume result
        assert "cover_letter" not in result

    def test_raises_when_job_not_found(self):
        from app.services.tailoring_engine import tailor_resume

        with patch("app.services.tailoring_engine.database.get_job_by_id", return_value=None):
            with pytest.raises(ValueError, match="Job not found"):
                tailor_resume(user_id=USER_ID, job_id=JOB_ID)

    def test_raises_when_no_active_resume(self):
        from app.services.tailoring_engine import tailor_resume

        with patch("app.services.tailoring_engine.database.get_job_by_id", return_value=FAKE_JOB), \
             patch("app.services.tailoring_engine.database.get_active_resume", return_value=None):
            with pytest.raises(ValueError, match="No active resume"):
                tailor_resume(user_id=USER_ID, job_id=JOB_ID)

    def test_raises_when_explicit_resume_not_found(self):
        from app.services.tailoring_engine import tailor_resume

        with patch("app.services.tailoring_engine.database.get_job_by_id", return_value=FAKE_JOB), \
             patch("app.services.tailoring_engine.database.get_resume_by_id", return_value=None):
            with pytest.raises(ValueError, match="Resume not found"):
                tailor_resume(user_id=USER_ID, job_id=JOB_ID, resume_id=str(uuid4()))

    def test_raises_when_resume_belongs_to_other_user(self):
        from app.services.tailoring_engine import tailor_resume

        other_user_resume = {**FAKE_RESUME, "user_id": str(uuid4())}
        with patch("app.services.tailoring_engine.database.get_job_by_id", return_value=FAKE_JOB), \
             patch("app.services.tailoring_engine.database.get_resume_by_id", return_value=other_user_resume):
            with pytest.raises(ValueError, match="does not belong"):
                tailor_resume(user_id=USER_ID, job_id=JOB_ID, resume_id=RESUME_ID)

    def test_embeds_job_description_for_chunk_retrieval(self):
        from app.services.tailoring_engine import tailor_resume

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6] as mock_embed, patches[7], patches[8], patches[9]:
            tailor_resume(user_id=USER_ID, job_id=JOB_ID)

        mock_embed.assert_called_once()
        call_text = mock_embed.call_args[0][0]
        assert "Software Engineer" in call_text
        assert "Acme" in call_text


# ---------------------------------------------------------------------------
# tailor_cover_letter
# ---------------------------------------------------------------------------

class TestTailorCoverLetter:
    def test_full_flow_includes_hook_project(self):
        from app.services.tailoring_engine import tailor_cover_letter

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6], patches[7], patches[8], patches[9] as mock_cl:
            result = tailor_cover_letter(user_id=USER_ID, job_id=JOB_ID)

        assert result["cover_letter"] == "Dear Hiring Manager..."
        assert result["hook_project_id"] == PROJECT_ID
        assert "application_id" in result
        # fit_score / summary_text should NOT be in cover letter result
        assert "fit_score" not in result
        assert "summary_text" not in result

    def test_hook_project_woven_into_cover_letter_call(self):
        from app.services.tailoring_engine import tailor_cover_letter

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6], patches[7], patches[8], patches[9] as mock_cl:
            tailor_cover_letter(user_id=USER_ID, job_id=JOB_ID)

        call_kwargs = mock_cl.call_args[1]
        assert call_kwargs["hook_project"] is not None
        assert "MyApp" in call_kwargs["hook_project"]

    def test_no_hook_when_no_project(self):
        from app.services.tailoring_engine import tailor_cover_letter

        no_hook_app_row = {**FAKE_APP_ROW, "hook_project_id": None}
        patches = _patch_db_and_gemini(project=None, app_row=no_hook_app_row)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6], patches[7], patches[8], patches[9] as mock_cl:
            result = tailor_cover_letter(user_id=USER_ID, job_id=JOB_ID)

        call_kwargs = mock_cl.call_args[1]
        assert call_kwargs["hook_project"] is None
        assert result["hook_project_id"] is None


# ---------------------------------------------------------------------------
# tailor_full
# ---------------------------------------------------------------------------

class TestTailorFull:
    def test_returns_all_fields(self):
        from app.services.tailoring_engine import tailor_full

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6], patches[7], patches[8], patches[9]:
            result = tailor_full(user_id=USER_ID, job_id=JOB_ID)

        assert result["fit_score"] == 82
        assert result["summary_text"] == "Experienced engineer..."
        assert result["cover_letter"] == "Dear Hiring Manager..."
        assert result["hook_project_id"] == PROJECT_ID
        assert "application_id" in result

    def test_embed_called_once(self):
        """Embedding should be computed only once even though both summary and cover letter use it."""
        from app.services.tailoring_engine import tailor_full

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patches[6] as mock_embed, patches[7], patches[8], patches[9]:
            tailor_full(user_id=USER_ID, job_id=JOB_ID)

        mock_embed.assert_called_once()

    def test_upsert_application_called_with_all_fields(self):
        from app.services.tailoring_engine import tailor_full

        patches = _patch_db_and_gemini()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as mock_upsert, \
             patches[6], patches[7], patches[8], patches[9]:
            tailor_full(user_id=USER_ID, job_id=JOB_ID)

        upsert_data = mock_upsert.call_args[0][0]
        assert upsert_data["fit_score"] == 82
        assert upsert_data["summary_text"] == "Experienced engineer..."
        assert upsert_data["cover_letter"] == "Dear Hiring Manager..."
        assert upsert_data["hook_project_id"] == PROJECT_ID
