# Standard library
import random
import re
import time
from urllib.parse import urlencode

# Third-party
from linkedin_api import Linkedin
from requests.cookies import RequestsCookieJar

# Local
from config import Config as config
from job_model import Job


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

# Company-track searches call LinkedIn's job-cards endpoint directly instead of
# Linkedin.search_jobs: search_jobs only sends a location *name*, which LinkedIn
# treats as a fallback and ignores (every metro returned the same jobs), and it
# discards the search cards that carry the company name and location.
_JOB_CARDS_PATH = "/voyagerJobsDashJobCards"
_JOB_CARDS_DECORATION = "com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-174"
_JOB_CARD_TYPE = "com.linkedin.voyager.dash.jobs.JobPostingCard"
_SEARCH_PAGE_SIZE = 25
_REMOTE_WORKPLACE = "2"
# These characters are the query's own syntax; inside the keywords they change
# its structure and LinkedIn silently returns nothing.
_QUERY_SYNTAX_RE = re.compile(r"[(),:]")


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


# --- Company-track searches ---------------------------------------------------

def _selected_filters(company_ids: list[str], location: dict) -> str:
    filters = [f"company:List({','.join(company_ids)})"]
    if location.get("remote"):
        filters.append(f"workplaceType:List({_REMOTE_WORKPLACE})")
    elif config.DISTANCE:
        filters.append(f"distance:List({config.DISTANCE})")
    if config.EXPERIENCE_LEVEL and config.EXPERIENCE_LEVEL.lower() in _EXPERIENCE_LEVEL_MAP:
        filters.append(f"experience:List({_EXPERIENCE_LEVEL_MAP[config.EXPERIENCE_LEVEL.lower()]})")
    if config.JOB_TYPE and config.JOB_TYPE.lower() in _JOB_TYPE_MAP:
        filters.append(f"jobType:List({_JOB_TYPE_MAP[config.JOB_TYPE.lower()]})")
    if config.HOURS_OLD is not None:
        filters.append(f"timePostedRange:List(r{config.HOURS_OLD * 3600})")
    return ",".join(filters)


def _track_query(keywords: str, company_ids: list[str], location: dict) -> str:
    keywords = " ".join(_QUERY_SYNTAX_RE.sub(" ", keywords).split())
    return (
        "(origin:JOB_SEARCH_PAGE_QUERY_EXPANSION,"
        f"keywords:{keywords},"
        f"locationUnion:(geoId:{location['geo_id']}),"
        f"selectedFilters:({_selected_filters(company_ids, location)}),"
        "spellCorrectionEnabled:true)"
    )


def _search_cards(api: Linkedin, query: str) -> tuple[list[dict], int, list[str]]:
    """Every search card for `query`, paged up to config.RESULTS_WANTED.

    Also returns the total LinkedIn reports for the search and the IDs of
    postings the response mentioned but that never became a kept card, so a
    gap between what LinkedIn found and what we kept shows in the log."""
    cards: list[dict] = []
    reported = 0
    seen_ids: set[str] = set()
    start = 0
    while len(cards) < config.RESULTS_WANTED:
        params = {
            "decorationId": _JOB_CARDS_DECORATION,
            "count": _SEARCH_PAGE_SIZE,
            "q": "jobSearch",
            "query": query,
            "start": start,
        }
        res = api._fetch(
            f"{_JOB_CARDS_PATH}?{urlencode(params, safe='(),:')}",
            headers={"accept": "application/vnd.linkedin.normalized+json+2.1"},
        )
        res.raise_for_status()
        data = res.json()
        included = data.get("included", [])
        seen_ids |= _posting_ids(included)
        # Each posting comes back as a JOBS_SEARCH card (title, company,
        # location) and an empty JOB_DETAILS card; only the first is useful.
        page = [
            item for item in included
            if item.get("$type") == _JOB_CARD_TYPE and "JOBS_SEARCH" in item.get("entityUrn", "")
        ]
        total = data.get("data", {}).get("paging", {}).get("total", 0)
        reported = reported or total
        if not page:
            break
        cards.extend(page)
        start += _SEARCH_PAGE_SIZE
        if start >= total:
            break
        time.sleep(random.uniform(1, 3))
    cards = cards[: config.RESULTS_WANTED]
    kept_ids = {(card.get("jobPostingUrn") or "").split(":")[-1] for card in cards}
    return cards, reported, sorted(seen_ids - kept_ids)


_POSTING_URN_RE = re.compile(r"urn:li:fsd_jobPosting:(\d+)")


def _posting_ids(items: list[dict]) -> set[str]:
    """Every job posting ID referenced anywhere in a response's included items,
    whatever the item's type, to catch postings the card filter leaves out."""
    ids: set[str] = set()
    for item in items:
        for key in ("entityUrn", "jobPostingUrn", "*jobPosting"):
            match = _POSTING_URN_RE.search(str(item.get(key) or ""))
            if match:
                ids.add(match.group(1))
    return ids


def _text(card: dict, key: str) -> str:
    return ((card.get(key) or {}).get("text") or "").strip()


def _card_to_job(card: dict, track: str) -> Job | None:
    job_id = (card.get("jobPostingUrn") or "").split(":")[-1]
    if not job_id:
        return None
    return Job(
        company=_text(card, "primaryDescription") or "Unknown",
        role=_text(card, "title") or "Unknown",
        link=f"https://www.linkedin.com/jobs/view/{job_id}",
        track=track,
    )


def _company_counts(companies: list[str], configured: list[str]) -> dict[str, int]:
    """Results per company: every configured company (zeros included, in config
    order), then any name LinkedIn returned that matches none of them, which
    usually means the company page is named differently from the config key."""
    by_key = {name.casefold(): name for name in configured}
    counts = {name: 0 for name in configured}
    for company in companies:
        name = by_key.get(company.casefold(), company)
        counts[name] = counts.get(name, 0) + 1
    return counts


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name} {n}" for name, n in counts.items())


def _run_track_searches(api: Linkedin) -> tuple[list[Job], list[str]]:
    """One search per track per location. Descriptions are left empty here and
    fetched later by enrich_details, only for jobs that survive dedup."""
    errors: list[str] = []
    jobs_by_link: dict[str, Job] = {}
    for track, spec in config.LINKEDIN_COMPANY_TRACKS.items():
        company_ids = list(spec["companies"].values())
        configured = list(spec["companies"].keys())
        # Each track is one combined search, so without a per-company tally a
        # company whose ID returns nothing is indistinguishable from a quiet day.
        track_jobs: list[Job] = []
        searched = False
        for location in config.LINKEDIN_LOCATIONS:
            label = f"track {track} / {location['name']}"
            try:
                cards, reported, skipped = _search_cards(
                    api, _track_query(spec["keywords"], company_ids, location)
                )
            except Exception as e:
                errors.append(f"LinkedIn search failed for {label} (session may be expired): {e}")
                continue
            searched = True
            new = 0
            location_jobs: list[Job] = []
            for card in cards:
                job = _card_to_job(card, track)
                if not job:
                    continue
                location_jobs.append(job)
                # Remote postings also show up in every metro search.
                if job.link and job.link not in jobs_by_link:
                    jobs_by_link[job.link] = job
                    track_jobs.append(job)
                    new += 1
            counts = _company_counts([j.company for j in location_jobs], configured)
            print(f"[linkedin] {label}: {len(cards)} result(s) (LinkedIn reports {reported}), "
                  f"{new} new ({_format_counts(counts)})")
            if skipped:
                print(f"[linkedin] {label}: {len(skipped)} posting(s) in the response but not kept: "
                      f"{', '.join(skipped)}")
            time.sleep(random.uniform(2, 4))
        if not searched:
            continue
        totals = _company_counts([j.company for j in track_jobs], configured)
        print(f"[linkedin] track {track} unique jobs per company: {_format_counts(totals)}")
        missing = [name for name in configured if totals[name] == 0]
        if missing:
            print(f"[linkedin] track {track}: no results in any location for {', '.join(missing)}")
    return list(jobs_by_link.values()), errors


def enrich_details(jobs: list[Job]) -> list[str]:
    """Fetch and attach full descriptions to the given jobs, in place.

    Call this AFTER dedup/block filtering so a detail request is only made for
    jobs that are actually kept. Jobs that already have a description (the
    single-search fallback fetches inline) are skipped."""
    errors: list[str] = []
    targets = [j for j in jobs if j.description is None and j.link]
    if not targets:
        return errors

    try:
        api = _build_client()
    except ValueError as e:
        return [str(e)]

    print(f"[linkedin] fetching details for {len(targets)} job(s)...")
    for job in targets:
        job_id = (job.link or "").rstrip("/").split("/")[-1]
        details = _fetch_job_details(api, job_id)
        if not details:
            errors.append(f"LinkedIn: detail fetch failed for {job.link}")
            continue
        description = _parse_description(details)
        job.description = description[:10000] if description else None
        if job.company in (None, "", "Unknown"):
            job.company = _parse_company(details)
    return errors


def run_scrape() -> tuple[list[Job], list[str]]:
    errors: list[str] = []

    try:
        api = _build_client()
    except ValueError as e:
        return [], [str(e)]

    if getattr(config, "LINKEDIN_COMPANY_TRACKS", None):
        jobs, errors = _run_track_searches(api)
        print(f"Found {len(jobs)} unique jobs across {len(config.LINKEDIN_COMPANY_TRACKS)} track(s)\n")
        return jobs, errors

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
