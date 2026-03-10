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

    # --- Filters ---
    IS_REMOTE = False
    # Options: "fulltime", "parttime", "internship", "contract" (None = all)
    JOB_TYPE = "fulltime"
    # Options: "internship", "entry level", "associate", "mid-senior level", "director", "executive" (None = all)
    # Note: only LinkedIn populates this field — other sites always pass through
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
