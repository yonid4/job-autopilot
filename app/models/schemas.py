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
