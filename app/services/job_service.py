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
# Bulk search helpers
# ---------------------------------------------------------------------------

_EXPERIENCE_LEVEL_MAP = {
    "internship": "1",
    "entry level": "2",
    "associate": "3",
    "mid-senior level": "4",
    "director": "5",
    "executive": "6",
}

_JOB_TYPE_MAP = {
    "fulltime": "F",
    "parttime": "P",
    "contract": "C",
    "internship": "I",
}


def _build_search_kwargs() -> dict:
    from app.config import settings

    kwargs: dict = {
        "keywords": settings.search_term,
        "location_name": settings.location.replace(",", ""),
        "limit": settings.results_wanted,
    }
    if settings.hours_old is not None:
        kwargs["listed_at"] = settings.hours_old * 3600
    level = (settings.experience_level or "").lower()
    if level in _EXPERIENCE_LEVEL_MAP:
        kwargs["experience"] = [_EXPERIENCE_LEVEL_MAP[level]]
    jtype = (settings.job_type or "").lower()
    if jtype in _JOB_TYPE_MAP:
        kwargs["job_type"] = [_JOB_TYPE_MAP[jtype]]
    if settings.is_remote:
        kwargs["remote"] = ["2"]
    return kwargs


def _fetch_job_details(api, job_id: str) -> dict:
    try:
        time.sleep(random.uniform(2, 5))
        return api.get_job(job_id)
    except Exception:
        return {}


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
    return database.upsert_job(data)


def list_jobs(limit: int = 50) -> list[dict]:
    """Return recently ingested jobs (shared across all users)."""
    return database.list_jobs(limit=limit)


def run_scrape(user_id: str) -> dict:
    """Bulk LinkedIn search using config params. Returns {ingested, skipped, qualified, errors}."""
    from app.config import settings

    ingested = 0
    skipped = 0
    qualified = 0
    errors: list[str] = []
    new_jobs: list[dict] = []
    blocked = {c.lower() for c in settings.blocked_companies}

    try:
        api = _build_linkedin_client()
    except Exception as e:
        return {"ingested": 0, "skipped": 0, "qualified": 0, "errors": [str(e)]}

    try:
        results = api.search_jobs(**_build_search_kwargs())
    except Exception as e:
        return {"ingested": 0, "skipped": 0, "qualified": 0, "errors": [f"LinkedIn search failed: {e}"]}

    for result in results:
        try:
            entity = result.get("entityUrn", "")
            job_id = entity.split(":")[-1] if entity else None
            if not job_id:
                skipped += 1
                continue

            url = f"https://www.linkedin.com/jobs/view/{job_id}"

            if _find_existing_job(url):
                skipped += 1
                continue

            details = _fetch_job_details(api, job_id)
            company = _parse_company(details)

            if company.lower() in blocked:
                skipped += 1
                continue

            title = details.get("title") or result.get("title", "Unknown")
            description = _parse_description(details)

            job_data = {
                "url": url,
                "title": title,
                "company": company,
                "description": description[:10000] if description else None,
            }
            _store_job(job_data)
            new_jobs.append(job_data)
            ingested += 1
        except Exception as e:
            errors.append(str(e))

    if not new_jobs or not settings.smart_google_sheet_id or not settings.google_credentials_path:
        return {"ingested": ingested, "skipped": skipped, "qualified": 0, "errors": errors}

    resume = database.get_active_resume(user_id)
    if not resume:
        print(f"[scrape] no active resume for user {user_id} — skipping qualification + sheet push")
        return {"ingested": ingested, "skipped": skipped, "qualified": 0, "errors": errors}

    resume_chunks = database.get_resume_chunks(resume["id"])
    if not resume_chunks:
        print(f"[scrape] resume {resume['id']} has no chunks — skipping qualification + sheet push")
        return {"ingested": ingested, "skipped": skipped, "qualified": 0, "errors": errors}

    from app.services import gemini_service, sheets_service

    batch_size = settings.qualify_batch_size
    qualified_jobs: list[dict] = []

    for i in range(0, len(new_jobs), batch_size):
        batch = new_jobs[i : i + batch_size]
        try:
            scored = gemini_service.qualify_jobs_batch(resume_chunks, batch)
            for job in scored:
                if job.get("score", 0) >= settings.min_fit_score:
                    qualified_jobs.append(job)
                    qualified += 1
        except Exception as e:
            errors.append(f"Qualification batch {i // batch_size + 1} failed: {e}")

    if qualified_jobs:
        try:
            sheets_service.append_jobs(qualified_jobs)
        except Exception as e:
            errors.append(f"Sheets push failed: {e}")

    return {"ingested": ingested, "skipped": skipped, "qualified": qualified, "errors": errors}


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
