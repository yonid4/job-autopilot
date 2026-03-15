from __future__ import annotations

from app.core import database
from app.services.gemini_service import (
    embed_query,
    generate_cover_letter,
    generate_summary,
    qualify_job,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_job(job_id: str) -> dict:
    job = database.get_job_by_id(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    return job


def _resolve_resume(user_id: str, resume_id: str | None) -> dict:
    if resume_id:
        resume = database.get_resume_by_id(resume_id)
        if not resume:
            raise ValueError(f"Resume not found: {resume_id}")
        if resume["user_id"] != user_id:
            raise ValueError("Resume does not belong to this user")
        return resume
    resume = database.get_active_resume(user_id)
    if not resume:
        raise ValueError("No active resume found for this user")
    return resume


def _fetch_resume_chunks(user_id: str, resume_id: str, jd_embedding: list[float]) -> list[str]:
    rows = database.match_resume_chunks(
        user_id=user_id,
        resume_id=resume_id,
        embedding=jd_embedding,
        limit=10,
    )
    return [r["content"] for r in rows]


def _build_hook_text(hook_project: dict | None) -> str | None:
    if not hook_project:
        return None
    techs = ", ".join(hook_project.get("technologies") or [])
    text = f"{hook_project['name']}: {hook_project['description']}"
    return text + (f" ({techs})" if techs else "")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def tailor_resume(
    user_id: str,
    job_id: str,
    resume_id: str | None = None,
) -> dict:
    """Generate a tailored professional summary for a job.

    Runs: qualify → vector-search chunks → generate_summary.
    Upserts an application row (or updates existing) and returns result.

    Returns dict with: application_id, fit_score, strengths, gaps, summary_text.
    """
    job = _resolve_job(job_id)
    resume = _resolve_resume(user_id, resume_id)

    jd_text = f"{job.get('title', '')} at {job.get('company', '')}\n\n{job.get('description', '')}"
    jd_embedding = embed_query(jd_text)
    resume_chunks = _fetch_resume_chunks(user_id, resume["id"], jd_embedding)
    job_description = job.get("description") or ""

    qualify_result = qualify_job(resume_chunks, job_description)
    fit_score: int = qualify_result["score"]
    strengths: list[str] = qualify_result["strengths"]
    gaps: list[str] = qualify_result["gaps"]

    summary_text = generate_summary(
        resume_chunks=resume_chunks,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        job_description=job_description,
    )

    app_row = database.upsert_application({
        "user_id": user_id,
        "job_id": job_id,
        "resume_id": resume["id"],
        "fit_score": fit_score,
        "strengths": strengths,
        "gaps": gaps,
        "summary_text": summary_text,
        "status": "not_applied",
    })

    return {
        "application_id": app_row["id"],
        "fit_score": fit_score,
        "strengths": strengths,
        "gaps": gaps,
        "summary_text": summary_text,
    }


def tailor_cover_letter(
    user_id: str,
    job_id: str,
    resume_id: str | None = None,
) -> dict:
    """Generate a tailored cover letter for a job, with the best project hook woven in.

    Runs: vector-search chunks → match_best_project → generate_cover_letter.
    Upserts an application row (or updates existing) and returns result.

    Returns dict with: application_id, cover_letter, hook_project_id (may be None).
    """
    job = _resolve_job(job_id)
    resume = _resolve_resume(user_id, resume_id)

    jd_text = f"{job.get('title', '')} at {job.get('company', '')}\n\n{job.get('description', '')}"
    jd_embedding = embed_query(jd_text)
    resume_chunks = _fetch_resume_chunks(user_id, resume["id"], jd_embedding)
    job_description = job.get("description") or ""

    hook_project = database.match_best_project(user_id=user_id, embedding=jd_embedding)
    hook_project_id: str | None = hook_project["id"] if hook_project else None
    hook_text = _build_hook_text(hook_project)

    cover_letter = generate_cover_letter(
        resume_chunks=resume_chunks,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        job_description=job_description,
        hook_project=hook_text,
    )

    app_row = database.upsert_application({
        "user_id": user_id,
        "job_id": job_id,
        "resume_id": resume["id"],
        "cover_letter": cover_letter,
        "hook_project_id": hook_project_id,
        "status": "not_applied",
    })

    return {
        "application_id": app_row["id"],
        "cover_letter": cover_letter,
        "hook_project_id": hook_project_id,
    }


def tailor_full(
    user_id: str,
    job_id: str,
    resume_id: str | None = None,
) -> dict:
    """Run both resume tailoring and cover letter generation in one pass.

    More efficient than calling both separately because embeddings and chunk
    retrieval are computed once.

    Returns dict with: application_id, fit_score, strengths, gaps, summary_text,
    cover_letter, hook_project_id.
    """
    job = _resolve_job(job_id)
    resume = _resolve_resume(user_id, resume_id)

    jd_text = f"{job.get('title', '')} at {job.get('company', '')}\n\n{job.get('description', '')}"
    jd_embedding = embed_query(jd_text)
    resume_chunks = _fetch_resume_chunks(user_id, resume["id"], jd_embedding)
    job_description = job.get("description") or ""

    qualify_result = qualify_job(resume_chunks, job_description)
    fit_score: int = qualify_result["score"]
    strengths: list[str] = qualify_result["strengths"]
    gaps: list[str] = qualify_result["gaps"]

    hook_project = database.match_best_project(user_id=user_id, embedding=jd_embedding)
    hook_project_id: str | None = hook_project["id"] if hook_project else None
    hook_text = _build_hook_text(hook_project)

    summary_text = generate_summary(
        resume_chunks=resume_chunks,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        job_description=job_description,
    )

    cover_letter = generate_cover_letter(
        resume_chunks=resume_chunks,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        job_description=job_description,
        hook_project=hook_text,
    )

    app_row = database.upsert_application({
        "user_id": user_id,
        "job_id": job_id,
        "resume_id": resume["id"],
        "fit_score": fit_score,
        "strengths": strengths,
        "gaps": gaps,
        "summary_text": summary_text,
        "cover_letter": cover_letter,
        "hook_project_id": hook_project_id,
        "status": "not_applied",
    })

    return {
        "application_id": app_row["id"],
        "fit_score": fit_score,
        "strengths": strengths,
        "gaps": gaps,
        "summary_text": summary_text,
        "cover_letter": cover_letter,
        "hook_project_id": hook_project_id,
    }
