# Standard library
import os

# Third-party
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Scraper selection ---
    # Which scraper main.py runs: "linkedin" or "hiringcafe".
    # Overridable via the SCRAPER env var (passed from the GitHub workflow).
    SCRAPER = os.getenv("SCRAPER", "linkedin")

    # --- Search ---
    SEARCH_TERM = "Software Development"
    LOCATION = "San Francisco, CA"
    RESULTS_WANTED = 20                 # max jobs to add per run
    HOURS_OLD = 2                       # only jobs posted in the last N hours (None = no limit)

    # --- Filters ---
    # Companies to skip entirely (case-insensitive). Add more via BLOCKED_COMPANIES env var
    # (comma-separated, e.g. BLOCKED_COMPANIES="Google,Meta").
    _blocked_extra = os.getenv("BLOCKED_COMPANIES")
    BLOCKED_COMPANIES: list[str] = ["Revature", "Epic"] + (
        [c.strip() for c in _blocked_extra.split(",") if c.strip()]
        if _blocked_extra else []
    )

    IS_REMOTE = False
    # Options: "fulltime", "parttime", "internship", "contract" (None = all)
    JOB_TYPE = "fulltime"
    # Options: "internship", "entry level", "associate", "mid-senior level", "director", "executive" (None = all)
    # Note: LinkedIn and hiring.cafe honor this; other sites pass through.
    # hiring.cafe only has 4 coarse buckets, so finer levels map to the nearest.
    EXPERIENCE_LEVEL = "entry level"

    # --- Google Sheet ---
    # Column order must match your Google Sheet exactly
    SHEET_TAB_NAME = "Tracking Template"
    STATUS_ON_SCRAPE = "Have Not Applied"

    # --- LinkedIn Auth ---
    # Get these from your browser cookies when logged into linkedin.com
    LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT")
    LINKEDIN_JSESSIONID = os.getenv("LINKEDIN_JSESSIONID")

    # --- GEMINI ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
