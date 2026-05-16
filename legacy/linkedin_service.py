# Standard library
import random
import time

# Third-party
from linkedin_api import Linkedin
from requests.cookies import RequestsCookieJar

# Local
from legacy.config import Config as config
from legacy.job_model import Job


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


def _build_client() -> Linkedin:
    if not config.LINKEDIN_LI_AT:
        raise ValueError("LINKEDIN_LI_AT is not set in .env")
    if not config.LINKEDIN_JSESSIONID:
        raise ValueError("LINKEDIN_JSESSIONID is not set in .env")
    jar = RequestsCookieJar()
    jar.set("li_at", config.LINKEDIN_LI_AT, domain=".linkedin.com", path="/")
    jar.set("JSESSIONID", config.LINKEDIN_JSESSIONID, domain=".linkedin.com", path="/")
    return Linkedin("", "", cookies=jar)


def _build_search_kwargs() -> dict:
    kwargs: dict = {
        "keywords": config.SEARCH_TERM,
        "location_name": config.LOCATION.replace(",", ""),
        "limit": config.RESULTS_WANTED,
    }
    if config.HOURS_OLD is not None:
        kwargs["listed_at"] = config.HOURS_OLD * 3600
    if config.EXPERIENCE_LEVEL and config.EXPERIENCE_LEVEL.lower() in _EXPERIENCE_LEVEL_MAP:
        kwargs["experience"] = [_EXPERIENCE_LEVEL_MAP[config.EXPERIENCE_LEVEL.lower()]]
    if config.JOB_TYPE and config.JOB_TYPE.lower() in _JOB_TYPE_MAP:
        kwargs["job_type"] = [_JOB_TYPE_MAP[config.JOB_TYPE.lower()]]
    if config.IS_REMOTE:
        kwargs["remote"] = ["2"]  # linkedin-api remote filter value
    return kwargs


def _fetch_job_details(api: Linkedin, job_id: str) -> dict:
    try:
        time.sleep(random.uniform(2, 5))
        return api.get_job(job_id)
    except Exception:
        return {}


def _parse_company(details: dict) -> str:
    company_details = details.get("companyDetails", {})
    return (
        company_details.get("com.linkedin.voyager.deco.jobs.web.shared.WebCompactJobPostingCompany", {})
        .get("companyResolutionResult", {})
        .get("name")
        or "Unknown"
    )


def _parse_description(details: dict) -> str | None:
    desc = details.get("description", {})
    if isinstance(desc, dict):
        return desc.get("text")
    return str(desc) if desc else None


def _result_to_job(api: Linkedin, result: dict) -> Job:
    entity = result.get("entityUrn", "")
    job_id = entity.split(":")[-1] if entity else None
    job_url = f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else None

    title = result.get("title", "Unknown")

    details = _fetch_job_details(api, job_id) if job_id else {}
    company = _parse_company(details)
    description = _parse_description(details)

    return Job(
        company=company,
        role=title,
        description=description[:10000] if description else None,
        link=job_url,
    )


def run_scrape() -> tuple[list[Job], list[str]]:
    errors: list[str] = []

    try:
        api = _build_client()
    except ValueError as e:
        return [], [str(e)]

    try:
        results = api.search_jobs(**_build_search_kwargs())
    except Exception as e:
        return [], [f"LinkedIn search failed (session may be expired): {e}"]

    print(f"Found {len(results)} jobs\n")

    if not results:
        return [], []

    jobs: list[Job] = []
    for result in results:
        try:
            jobs.append(_result_to_job(api, result))
        except Exception as e:
            errors.append(f"Row parse error: {e}")

    for j in jobs:
        print(f"role:{j.role}, url:{j.link}\n")

    return jobs, errors
