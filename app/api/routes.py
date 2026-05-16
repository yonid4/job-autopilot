from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File

from app.api.auth import get_current_user_id
from app.core import database
from app.models.schemas import (
    ApplicationOut,
    ApplicationStatusUpdate,
    IngestJobRequest,
    IngestJobResponse,
    JobManualCreate,
    JobOut,
    ProjectCreate,
    ProjectOut,
    ResumeOut,
    TailorCoverLetterRequest,
    TailorCoverLetterResult,
    TailorFullRequest,
    TailorFullResult,
    TailorResumeRequest,
    TailorResumeResult,
)
from app.services.resume_service import process_resume
from app.services import job_service
from app.services import tailoring_engine

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

@router.post("/resumes/upload", status_code=202)
async def upload_resume(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    label: str = "default",
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Upload a PDF resume. Processing (parse + embed) runs as a background task."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    _MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
    pdf_bytes = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    background_tasks.add_task(
        process_resume,
        user_id=user_id,
        pdf_bytes=pdf_bytes,
        filename=file.filename or "resume.pdf",
        label=label,
    )
    return {"status": "processing", "message": "Resume upload accepted and processing in background"}


@router.get("/resumes", response_model=list[ResumeOut])
async def list_resumes(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    """List all resume versions for the current user."""
    result = (
        database.get_client()
        .table("resumes")
        .select("id, user_id, label, storage_path, is_active")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.post("/jobs/ingest", response_model=IngestJobResponse)
async def ingest_job(
    body: IngestJobRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Ingest a job by LinkedIn URL. Returns existing job if already stored."""
    try:
        job_row, is_new = job_service.ingest_job_by_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"job_id": job_row["id"], "created": is_new}


@router.post("/jobs/manual", response_model=IngestJobResponse)
async def ingest_job_manual(
    body: JobManualCreate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Ingest a job with manually provided data (no scraping)."""
    job_row, is_new = job_service.ingest_job_manual(
        url=body.url,
        title=body.title,
        company=body.company,
        description=body.description,
        salary=body.salary,
        job_level=body.job_level,
    )
    return {"job_id": job_row["id"], "created": is_new}


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """List recently ingested jobs."""
    return job_service.list_jobs(limit=limit)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Create a user project (embedded for best-hook matching)."""
    return job_service.create_project(
        user_id=user_id,
        name=body.name,
        description=body.description,
        technologies=body.technologies,
        url=body.url,
    )


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    """List all projects for the current user."""
    return job_service.list_projects(user_id=user_id)


# ---------------------------------------------------------------------------
# Tailoring
# ---------------------------------------------------------------------------

@router.post("/tailor/resume", response_model=TailorResumeResult)
async def tailor_resume(
    body: TailorResumeRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Generate a tailored professional summary + fit score for a job."""
    try:
        return tailoring_engine.tailor_resume(
            user_id=user_id,
            job_id=str(body.job_id),
            resume_id=str(body.resume_id) if body.resume_id else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/tailor/cover-letter", response_model=TailorCoverLetterResult)
async def tailor_cover_letter(
    body: TailorCoverLetterRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Generate a tailored cover letter (with best project hook) for a job."""
    try:
        return tailoring_engine.tailor_cover_letter(
            user_id=user_id,
            job_id=str(body.job_id),
            resume_id=str(body.resume_id) if body.resume_id else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/tailor/full", response_model=TailorFullResult)
async def tailor_full(
    body: TailorFullRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Run the full tailoring pipeline: fit score + summary + cover letter in one call."""
    try:
        return tailoring_engine.tailor_full(
            user_id=user_id,
            job_id=str(body.job_id),
            resume_id=str(body.resume_id) if body.resume_id else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@router.get("/applications", response_model=list[ApplicationOut])
async def list_applications(
    status: str | None = None,
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """List all applications for the current user, optionally filtered by status."""
    return database.get_applications(user_id=user_id, status=status)


@router.patch("/applications/{application_id}/status", response_model=ApplicationOut)
async def update_application_status(
    application_id: str,
    body: ApplicationStatusUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Update the status of an application (e.g. applied, interviewing, rejected)."""
    updated = database.update_application_status(
        application_id=application_id,
        user_id=user_id,
        status=body.status,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Application not found")
    return updated
