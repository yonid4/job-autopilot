from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.models.schemas import (
    IngestJobRequest,
    IngestJobResponse,
    JobCreate,
    JobOut,
    ProjectCreate,
    ProjectOut,
    ResumeOut,
    TailorFullRequest as TailorRequest,
    TailorFullResult as TailorResult,
)


def test_job_create_minimal():
    job = JobCreate(url="https://example.com/job", title="SWE", company="Acme")
    assert job.url == "https://example.com/job"
    assert job.description is None


def test_job_create_full():
    job = JobCreate(
        url="https://example.com/job",
        title="SWE",
        company="Acme",
        description="Write code",
        salary="100k",
        job_level="mid",
    )
    assert job.salary == "100k"
    assert job.job_level == "mid"


def test_job_out_requires_id():
    job = JobOut(id=uuid4(), url="https://x.com", title="Eng", company="Co")
    assert isinstance(job.id, UUID)


def test_resume_out():
    r = ResumeOut(
        id=uuid4(),
        user_id=uuid4(),
        label="default",
        storage_path="resumes/abc.pdf",
        is_active=True,
    )
    assert r.is_active is True


def test_project_create_defaults():
    p = ProjectCreate(name="My App", description="Does stuff")
    assert p.technologies == []
    assert p.url is None


def test_project_out():
    p = ProjectOut(
        id=uuid4(),
        user_id=uuid4(),
        name="My App",
        description="Does stuff",
        technologies=["Python", "FastAPI"],
    )
    assert "Python" in p.technologies


def test_ingest_job_request():
    r = IngestJobRequest(url="https://linkedin.com/jobs/123")
    assert "linkedin" in r.url


def test_ingest_job_response():
    r = IngestJobResponse(job_id=uuid4(), created=True)
    assert r.created is True


def test_tailor_request_no_resume():
    r = TailorRequest(job_id=uuid4())
    assert r.resume_id is None


def test_tailor_result():
    result = TailorResult(
        application_id=uuid4(),
        fit_score=85,
        strengths=["Python", "FastAPI"],
        gaps=["Kubernetes"],
        summary_text="Strong fit for backend role.",
        cover_letter="Dear Hiring Manager...",
    )
    assert result.fit_score == 85
    assert len(result.strengths) == 2
