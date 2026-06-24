# Standard library
import json
import math
import random
import re
import time

# Third-party
import requests

# Local
from config import Config as config
from job_model import Job


_BASE = "https://hiring.cafe"
_HOME_URL = f"{_BASE}/"
_SEARCH_LOCATION_URL = f"{_BASE}/api/searchLocation"
_JOB_DESCRIPTION_URL = f"{_BASE}/api/job-description"

# hiring.cafe's public POST /api/search-jobs endpoint is locked down (405/401).
# The site's own frontend reads search results from the Next.js SSR data route,
# which is open and unauthenticated:
#   GET /_next/data/<buildId>/index.json?searchState=<json>&page=<n>
# The buildId rotates on each deploy, so we scrape it from the homepage per run.
_BUILD_ID_RE = re.compile(r"/_next/static/([^/\"]+)/_buildManifest\.js")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_PAGE_SIZE = 40             # hiring.cafe returns 40 hits/page (pageProps.ssrPageSize)
_MAX_PAGES = 25            # safety cap on pagination
_FULL_DESCRIPTION_CAP = 25  # hybrid: fetch the full per-job description for at most N jobs
_DESCRIPTION_MAX_CHARS = 10000
_DEFAULT_RADIUS_MILES = 50  # matches hiring.cafe's own defaultRadius


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def _api_headers(next_data: bool = False) -> dict:
    headers = {
        "Accept": "*/*",
        "Origin": _BASE,
        "Referer": _HOME_URL,
    }
    if next_data:
        headers["x-nextjs-data"] = "1"
    return headers


def _get_build_id(session: requests.Session) -> str:
    resp = session.get(_HOME_URL, timeout=30)
    resp.raise_for_status()
    match = _BUILD_ID_RE.search(resp.text)
    if not match:
        raise ValueError("could not locate buildId in hiring.cafe homepage")
    return match.group(1)


def _resolve_location(session: requests.Session, location_text: str | None) -> dict | None:
    """Resolve a free-text location into a hiring.cafe searchState location object.

    Uses the site's own /api/searchLocation autocomplete, then attaches the
    `options` block hiring.cafe expects for the resolved place type (the API
    returns zero results if `options` is missing). Returns None on any failure
    so the caller can fall back to an unfiltered (location-less) search.
    """
    if not location_text:
        return None
    try:
        resp = session.get(
            _SEARCH_LOCATION_URL,
            params={"query": location_text},
            headers=_api_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        matches = resp.json()
    except Exception:
        return None

    if not matches:
        return None
    place = matches[0].get("placeDetail")
    if not place:
        return None

    loc_type = (place.get("types") or [""])[0]
    if loc_type == "locality":
        place["options"] = {
            "radius": getattr(config, "DISTANCE", _DEFAULT_RADIUS_MILES) or _DEFAULT_RADIUS_MILES,
            "radius_unit": "miles",
            "ignore_radius": False,
        }
    elif loc_type == "administrative_area_level_1":
        place["options"] = {
            "flexible_regions": ["anywhere_in_country", "anywhere_in_continent", "anywhere_in_world"]
        }
    elif loc_type == "country":
        place["options"] = {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]}
    else:
        place["options"] = {"flexible_regions": ["anywhere_in_world"]}
    return place


def _build_search_state(session: requests.Session) -> dict:
    # Kept intentionally minimal — only the filters we map from config.
    state: dict = {
        "searchQuery": config.SEARCH_TERM or "",
        "defaultToUserLocation": False,
    }

    location = _resolve_location(session, config.LOCATION)
    if location:
        state["locations"] = [location]

    if config.IS_REMOTE:
        state["workplaceTypes"] = ["Remote"]

    # hiring.cafe only exposes a coarse, day-based "fetched" filter. Map HOURS_OLD
    # up to whole days (1 day minimum) as a best-effort recency bound.
    if config.HOURS_OLD is not None:
        state["dateFetchedPastNDays"] = max(1, math.ceil(config.HOURS_OLD / 24))

    return state


def _format_salary(v5: dict) -> str | None:
    low = v5.get("yearly_min_compensation")
    high = v5.get("yearly_max_compensation")
    if not (low or high):
        return None
    currency = v5.get("listed_compensation_currency")
    frequency = v5.get("listed_compensation_frequency")
    if low and high and low != high:
        amount = f"{low:,} - {high:,}"
    else:
        amount = f"{(low or high):,}"
    return " ".join(part for part in (currency, amount, frequency) if part)


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _HTML_TAG_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _fetch_full_description(session: requests.Session, object_id: str | None) -> str | None:
    if not object_id:
        return None
    try:
        time.sleep(random.uniform(0.2, 0.6))
        resp = session.get(
            _JOB_DESCRIPTION_URL,
            params={"id": object_id},
            headers=_api_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        job = resp.json().get("job") or {}
        return (job.get("job_information") or {}).get("description")
    except Exception:
        return None


def _hit_to_job(session: requests.Session, hit: dict, fetch_full: bool) -> Job:
    job_info = hit.get("job_information") or {}
    v5 = hit.get("v5_processed_job_data") or {}
    company_data = hit.get("enriched_company_data") or {}

    role = job_info.get("title") or hit.get("hc_title")
    company = v5.get("company_name") or company_data.get("name") or "Unknown"
    link = hit.get("apply_url") or hit.get("hc_apply_url") or None
    salary = _format_salary(v5)

    # Hybrid description: the listing has no full description, so fall back to the
    # inline requirements_summary and only pay for a full per-job fetch on a capped
    # number of jobs (decided by the caller).
    description = None
    if fetch_full:
        description = _strip_html(_fetch_full_description(session, hit.get("objectID")))
    if not description:
        description = v5.get("requirements_summary") or None

    return Job(
        company=company,
        role=role,
        description=description[:_DESCRIPTION_MAX_CHARS] if description else None,
        salary=salary,
        link=link,
    )


def run_scrape() -> tuple[list[Job], list[str]]:
    errors: list[str] = []
    session = _session()

    try:
        build_id = _get_build_id(session)
    except Exception as e:
        return [], [f"hiring.cafe: could not obtain buildId (site may have changed): {e}"]

    try:
        search_state = _build_search_state(session)
    except Exception as e:
        return [], [f"hiring.cafe: failed to build search state: {e}"]

    data_url = f"{_BASE}/_next/data/{build_id}/index.json"

    hits: list[dict] = []
    page = 0
    while page < _MAX_PAGES and len(hits) < config.RESULTS_WANTED:
        params = {"searchState": json.dumps(search_state), "page": page}
        try:
            resp = session.get(data_url, params=params, headers=_api_headers(next_data=True), timeout=40)
            resp.raise_for_status()
            page_props = resp.json().get("pageProps") or {}
        except Exception as e:
            errors.append(f"hiring.cafe: page {page} request failed: {e}")
            break

        page_hits = page_props.get("ssrHits") or []
        if not page_hits:
            break
        hits.extend(page_hits)

        if page_props.get("ssrIsLastPage") or len(page_hits) < _PAGE_SIZE:
            break
        page += 1
        time.sleep(random.uniform(0.5, 1.5))

    hits = hits[: config.RESULTS_WANTED]
    print(f"Found {len(hits)} jobs\n")

    if not hits:
        return [], errors

    jobs: list[Job] = []
    for index, hit in enumerate(hits):
        try:
            jobs.append(_hit_to_job(session, hit, fetch_full=index < _FULL_DESCRIPTION_CAP))
        except Exception as e:
            errors.append(f"Row parse error: {e}")

    for j in jobs:
        print(f"role:{j.role}, company:{j.company}, url:{j.link}\n")

    return jobs, errors
