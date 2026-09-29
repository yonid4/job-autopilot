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
    # Optional pool of keys, rotated when one hits its quota.
    _gemini_keys_raw = os.getenv("GEMINI_API_KEYS")
    GEMINI_API_KEYS: list[str] = (
        [k.strip() for k in _gemini_keys_raw.split(",") if k.strip()]
        if _gemini_keys_raw
        else ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
    )
    GEMINI_PRIMARY_MODEL = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-2.5-flash")

    # --- Email status tracking (check_email.py) ---
    # How far back to read the inbox. Processed mail is labelled in Gmail, so a
    # wide window costs nothing and covers skipped runs.
    EMAIL_LOOKBACK_HOURS = 48
    EMAIL_MAX_RESULTS = 150
    # Gmail label applied to messages already triaged. Created on first run.
    EMAIL_PROCESSED_LABEL = "Job Autopilot/Processed"
    # Verdicts below this confidence are reported but never written or sent.
    EMAIL_MIN_CONFIDENCE = 0.6

    # Status values written to the Application Status column. These must match
    # your sheet's dropdown exactly, or Sheets will flag the cells as invalid.
    STATUS_APPLIED = "Submitted - Pending Response"
    STATUS_ASSESSMENT = "OA"
    STATUS_INTERVIEW = "Interviewing"
    STATUS_OFFER = "Offer Extended - In Progress"
    STATUS_REJECTED = "Rejected"
    # Waiting-to-hear-back statuses: real news moves them on, auto-replies don't.
    STATUS_WAITING = ["Sent Follow Up Email", "Re-Applied With Updated Resume", "Ghosted"]
    # Statuses you close a row out with. The checker never overwrites these, and
    # also leaves alone any status it doesn't recognise.
    STATUS_FINAL = [
        "Offer Extended - Did Not Accept",
        "Rescinded Application (Self) / Decided not a good fit",
        "Not For Me",
        "Job Rec Removed/Deactivated",
        "N/A",
    ]

    # --- Discord ---
    # Incoming webhook for the notifications channel. Unset = no notifications.
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    # Which categories are worth a ping. Rejections stay out of it by default.
    DISCORD_NOTIFY_CATEGORIES = ["assessment", "interview", "offer"]
