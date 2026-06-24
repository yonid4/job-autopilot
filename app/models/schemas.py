from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    url: str
    title: str
    company: str
    description: str | None = None
    salary: str | None = None
    job_level: str | None = None


class JobOut(BaseModel):
    id: UUID
    url: str
    title: str
    company: str
    description: str | None = None
    salary: str | None = None
    job_level: str | None = None


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

class ResumeOut(BaseModel):
    id: UUID
    user_id: UUID
    label: str
    storage_path: str
    is_active: bool


class ResumeDetailOut(ResumeOut):
    parsed_json: dict | None = None


# ---------------------------------------------------------------------------
# User projects
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: str
    technologies: list[str] = []
    url: str | None = None


class ProjectOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str
    technologies: list[str]
    url: str | None = None


# ---------------------------------------------------------------------------
# Job ingestion (scrape + store)
# ---------------------------------------------------------------------------

class IngestJobRequest(BaseModel):
    url: str


class ScrapeJobsResponse(BaseModel):
    ingested: int
    skipped: int
    qualified: int = 0
    errors: list[str]


class ScrapeConfig(BaseModel):
    """Editable (non-secret) scrape + qualification settings."""

    search_term: str
    location: str
    results_wanted: int
    hours_old: int | None = None
    distance: int
    is_remote: bool
    job_type: str | None = None
    experience_level: str | None = None
    blocked_companies: list[str] = []
    min_fit_score: int
    qualify_batch_size: int
    sheet_tab_name: str = ""


class JobManualCreate(BaseModel):
    url: str
    title: str
    company: str
    description: str | None = None
    salary: str | None = None
    job_level: str | None = None


class IngestJobResponse(BaseModel):
    job_id: UUID
    created: bool  # True if new, False if already existed


# ---------------------------------------------------------------------------
# Tailoring (qualify + cover letter)
# ---------------------------------------------------------------------------

class TailorResumeRequest(BaseModel):
    job_id: UUID
    resume_id: UUID | None = None  # defaults to active resume


class TailorCoverLetterRequest(BaseModel):
    job_id: UUID
    resume_id: UUID | None = None  # defaults to active resume


class TailorFullRequest(BaseModel):
    job_id: UUID
    resume_id: UUID | None = None  # defaults to active resume


class TailorResumeResult(BaseModel):
    application_id: UUID
    fit_score: int                  # 0–100
    strengths: list[str]
    gaps: list[str]
    summary_text: str


class TailorCoverLetterResult(BaseModel):
    application_id: UUID
    cover_letter: str
    hook_project_id: UUID | None = None


class TailorFullResult(BaseModel):
    application_id: UUID
    fit_score: int
    strengths: list[str]
    gaps: list[str]
    summary_text: str
    cover_letter: str
    hook_project_id: UUID | None = None


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

class ApplicationOut(BaseModel):
    id: UUID
    user_id: UUID
    job_id: UUID
    resume_id: UUID | None = None
    status: str
    fit_score: int | None = None
    strengths: list[str] | None = None
    gaps: list[str] | None = None
    summary_text: str | None = None
    cover_letter: str | None = None
    hook_project_id: UUID | None = None


class ApplicationStatusUpdate(BaseModel):
    status: Literal["not_applied", "applied", "interviewing", "offered", "rejected", "withdrawn"]
