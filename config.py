# Standard library
import os

# Third-party
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Search ---
    SEARCH_TERM = "software engineer"
    LOCATION = "San Francisco, CA"
    RESULTS_WANTED = 20                 # max jobs to add per run
    HOURS_OLD = 2                       # only jobs posted in the last N hours (None = no limit)
    DISTANCE = 50                       # miles

    # --- Sites ---
    # Options: "linkedin", "indeed", "glassdoor", "zip_recruiter", "google"
    SITE_NAMES = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]

    # --- Filters ---
    IS_REMOTE = False
    # Options: "fulltime", "parttime", "internship", "contract" (None = all)
    JOB_TYPE = "fulltime"
    # Options: "internship", "entry level", "associate", "mid-senior level", "director", "executive" (None = all)
    # Note: only LinkedIn populates this field — other sites always pass through
    EXPERIENCE_LEVEL = "entry level"

    # --- LinkedIn specific ---
    # Fetches full description and direct job URL from LinkedIn (slower)
    LINKEDIN_FETCH_DESCRIPTION = True

    # --- Google Sheet ---
    # Column order must match your Google Sheet exactly
    SHEET_TAB_NAME = "Tracking Template"
    STATUS_ON_SCRAPE = "Have Not Applied"

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")