from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache(maxsize=1)
def get_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def find_job_by_url(url: str) -> dict | None:
    result = get_client().table("jobs").select("*").eq("url", url).limit(1).execute()
    return result.data[0] if result.data else None


def find_job_by_title_company(title: str, company: str) -> dict | None:
    key = f"{title.lower()}::{company.lower()}"
    result = (
        get_client()
        .table("jobs")
        .select("*")
        .eq("title_company", key)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def upsert_job(data: dict) -> dict:
    result = (
        get_client()
        .table("jobs")
        .upsert(data, on_conflict="url")
        .execute()
    )
    return result.data[0]


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

def get_active_resume(user_id: str) -> dict | None:
    result = (
        get_client()
        .table("resumes")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def insert_resume(data: dict) -> dict:
    result = get_client().table("resumes").insert(data).execute()
    return result.data[0]


def set_active_resume(user_id: str, resume_id: str) -> None:
    """Atomically deactivate all resumes for the user and activate the given one."""
    get_client().rpc(
        "set_active_resume",
        {"p_user_id": user_id, "p_resume_id": resume_id},
    ).execute()


# ---------------------------------------------------------------------------
# Resume chunks
# ---------------------------------------------------------------------------

def insert_resume_chunks(chunks: list[dict]) -> None:
    if chunks:
        get_client().table("resume_chunks").insert(chunks).execute()


def delete_resume_chunks(resume_id: str) -> None:
    get_client().table("resume_chunks").delete().eq("resume_id", resume_id).execute()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def insert_project(data: dict) -> dict:
    result = get_client().table("user_projects").insert(data).execute()
    return result.data[0]


def get_projects(user_id: str) -> list[dict]:
    result = (
        get_client()
        .table("user_projects")
        .select("id, user_id, name, description, technologies, url, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------

def get_resume_by_id(resume_id: str) -> dict | None:
    result = get_client().table("resumes").select("*").eq("id", resume_id).limit(1).execute()
    return result.data[0] if result.data else None


def match_resume_chunks(user_id: str, resume_id: str, embedding: list[float], limit: int = 10) -> list[dict]:
    """Call the match_resume_chunks RPC to retrieve the most relevant chunks."""
    result = get_client().rpc(
        "match_resume_chunks",
        {
            "p_user_id": user_id,
            "p_resume_id": resume_id,
            "p_embedding": embedding,
            "p_limit": limit,
        },
    ).execute()
    return result.data or []


def match_best_project(user_id: str, embedding: list[float]) -> dict | None:
    """Call the match_best_project RPC to find the closest user project."""
    result = get_client().rpc(
        "match_best_project",
        {"p_user_id": user_id, "p_embedding": embedding},
    ).execute()
    return result.data[0] if result.data else None


def get_job_by_id(job_id: str) -> dict | None:
    result = get_client().table("jobs").select("*").eq("id", job_id).limit(1).execute()
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def upsert_application(data: dict) -> dict:
    result = (
        get_client()
        .table("applications")
        .upsert(data, on_conflict="user_id,job_id")
        .execute()
    )
    return result.data[0]


def get_applications(user_id: str, status: str | None = None) -> list[dict]:
    query = get_client().table("applications").select("*, jobs(*)").eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).execute()
    return result.data


def update_application_status(application_id: str, user_id: str, status: str) -> dict | None:
    result = (
        get_client()
        .table("applications")
        .update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", application_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None
