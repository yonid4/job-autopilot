from __future__ import annotations

import random
import time

from app.core import database
from app.services.gemini_service import embed_text


# ---------------------------------------------------------------------------
# LinkedIn scraping helpers (adapted from legacy/linkedin_service.py)
# ---------------------------------------------------------------------------

def _build_linkedin_client():
    """Build a LinkedIn API client using cookie auth from settings."""
    from requests.cookies import RequestsCookieJar
    from linkedin_api import Linkedin
    from app.config import settings

    jar = RequestsCookieJar()
    jar.set("li_at", settings.linkedin_li_at, domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", settings.linkedin_jsessionid, domain=".linkedin.com", path="/")
    return Linkedin("", "", cookies=jar)


def _job_id_from_url(url: str) -> str | None:
    """Extract LinkedIn job ID from URL."""
    # e.g. https://www.linkedin.com/jobs/view/1234567890
    parts = url.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part == "view" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate.isdigit():
                return candidate
    # fallback: last numeric segment
    for part in reversed(parts):
        if part.isdigit():
            return part
    return None


def _parse_company(details: dict) -> str:
    company_details = details.get("companyDetails", {})
    return (
        company_details.get(
            "com.linkedin.voyager.deco.jobs.web.shared.WebCompactJobPostingCompany", {}
        )
        .get("companyResolutionResult", {})
        .get("name")
        or "Unknown"
    )


def _parse_description(details: dict) -> str | None:
    desc = details.get("description", {})
    if isinstance(desc, dict):
        return desc.get("text")
    return str(desc) if desc else None


def _scrape_linkedin_job(url: str) -> dict | None:
    """Scrape a single LinkedIn job by URL. Returns raw job data dict or None."""
    job_id = _job_id_from_url(url)
    if not job_id:
        return None

    try:
        api = _build_linkedin_client()
    except Exception:
        return None

    try:
        time.sleep(random.uniform(1, 3))
        details = api.get_job(job_id)
    except Exception:
        return None

    title = details.get("title", "Unknown")
    company = _parse_company(details)
    description = _parse_description(details)

    return {
        "url": url,
        "title": title,
        "company": company,
        "description": description[:10000] if description else None,
    }


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------

def _find_existing_job(url: str, title: str | None = None, company: str | None = None) -> dict | None:
    """Check for existing job by URL first, then title+company."""
    existing = database.find_job_by_url(url)
    if existing:
        return existing
    if title and company:
        return database.find_job_by_title_company(title, company)
    return None


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def ingest_job_by_url(url: str) -> tuple[dict, bool]:
    """Ingest a job by LinkedIn URL.

    Returns (job_row, is_new). Scrapes only if not already in DB.
    Raises ValueError if scraping fails and job not in DB.
    """
    existing = database.find_job_by_url(url)
    if existing:
        return existing, False

    scraped = _scrape_linkedin_job(url)
    if not scraped:
        raise ValueError(f"Could not scrape job at URL: {url}")

    return _store_job(scraped), True


def ingest_job_manual(url: str, title: str, company: str, description: str | None = None,
                      salary: str | None = None, job_level: str | None = None) -> tuple[dict, bool]:
    """Ingest a manually provided job (no scraping needed).

    Returns (job_row, is_new).
    """
    existing = _find_existing_job(url, title, company)
    if existing:
        return existing, False

    data = {
        "url": url,
        "title": title,
        "company": company,
        "description": description,
        "salary": salary,
        "job_level": job_level,
    }
    return _store_job(data), True


def _store_job(data: dict) -> dict:
    """Embed the job description and upsert into the jobs table."""
    description = data.get("description") or ""
    if description:
        embed_input = f"{data.get('title', '')} at {data.get('company', '')}\n\n{description}"
        embedding = embed_text(embed_input)
        data["embedding"] = embedding

    return database.upsert_job(data)


def list_jobs(limit: int = 50) -> list[dict]:
    """Return recently ingested jobs (shared across all users)."""
    result = (
        database.get_client()
        .table("jobs")
        .select("id, url, title, company, description, salary, job_level, created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(user_id: str, name: str, description: str,
                   technologies: list[str], url: str | None) -> dict:
    """Embed and store a user project."""
    embed_input = f"{name}\n{description}\nTechnologies: {', '.join(technologies)}"
    embedding = embed_text(embed_input)

    data = {
        "user_id": user_id,
        "name": name,
        "description": description,
        "technologies": technologies,
        "url": url,
        "embedding": embedding,
    }
    return database.insert_project(data)


def list_projects(user_id: str) -> list[dict]:
    """Return all projects for a user."""
    return database.get_projects(user_id)
