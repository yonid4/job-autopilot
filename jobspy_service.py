# Third-party
import jobspy
import pandas as pd

# Local
from config import Config as config
from job_model import Job


_EXPERIENCE_LEVEL_OVERFETCH_MULTIPLIER = 3


def _scrape_sync() -> pd.DataFrame:
    """
    Synchronous jobspy call.

    When experience_level is set, we over-fetch by a multiplier so that after
    post-filtering by job_level (LinkedIn-only field) we still have enough results.
    Non-LinkedIn results always pass through since they never populate job_level.
    """
    results_wanted = (
        config.RESULTS_WANTED * _EXPERIENCE_LEVEL_OVERFETCH_MULTIPLIER
        if config.EXPERIENCE_LEVEL
        else config.RESULTS_WANTED
    )
    kwargs: dict = {
        "site_name": config.SITE_NAMES,
        "search_term": config.SEARCH_TERM,
        "location": config.LOCATION,
        "results_wanted": results_wanted,
        "distance": config.DISTANCE,
        "is_remote": config.IS_REMOTE,
        "linkedin_fetch_description": config.LINKEDIN_FETCH_DESCRIPTION,
    }
    if config.HOURS_OLD is not None:
        kwargs["hours_old"] = config.HOURS_OLD
    if config.JOB_TYPE is not None:
        kwargs["job_type"] = config.JOB_TYPE
    return jobspy.scrape_jobs(**kwargs)


def _row_to_job(row: pd.Series) -> Job:
    """
    Convert a single jobspy DataFrame row into a dictionary of columns in google sheet.
    """
    # jobspy provides salary as min/max integers — format as string to match existing schema
    salary = None
    if pd.notna(row.get("min_amount")) and pd.notna(row.get("max_amount")):
        salary = f"${int(row['min_amount']):,} - ${int(row['max_amount']):,}"
    elif pd.notna(row.get("min_amount")):
        salary = f"${int(row['min_amount']):,}+"

    job_level = str(row["job_level"]) if pd.notna(row.get("job_level")) else None

    return Job(
        company=str(row.get("company", "Unknown")),
        role=str(row.get("title", "Unknown")),
        description=str(row.get("description", ""))[:10000] if pd.notna(row.get("description")) else None,
        salary=salary,
        date_submitted=None,
        link=str(row.get("job_url", "")) if pd.notna(row.get("job_url")) else None,
        job_level=job_level,
    )


def run_scrape() -> tuple[list[Job], list[str]]:
    """
    Main entry point called by main.py.
    Returns (jobs, errors).
    """
    errors: list[str] = []

    try:
        df: pd.DataFrame = _scrape_sync()
    except Exception as e:
        return [], [f"Scraping failed: {str(e)}"]

    if df.empty:
        return [], []

    jobs: list[Job] = []
    for _, row in df.iterrows():
        try:
            jobs.append(_row_to_job(row))
        except Exception as e:
            errors.append(f"Row parse error: {str(e)}")

    for j in jobs:
        print(f"role:{j.role}, url:{j.link}, job level:{j.job_level if j.job_level else 'no level'}\n")

    return jobs, errors
