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
    DISTANCE = 25                       # miles around each LinkedIn metro

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

    # --- LinkedIn company tracks ---
    # Keep in sync with the Config written by .github/workflows/scrape_linkedin.yml
    # on main; that file builds config.py from scratch for the scheduled runs.
    # One search per track per location. Company IDs are the numbers LinkedIn's
    # company filter uses (resolved from each company page's slug). Keywords must
    # stay plain "a OR b" — LinkedIn returns nothing for parentheses or several
    # quoted phrases, and ignores NOT (the title prefilter does that job).
    # Empty = fall back to the single SEARCH_TERM/LOCATION search.
    LINKEDIN_COMPANY_TRACKS: dict[str, dict] = {
        "A": {
            "companies": {"Bright Data": "4000016", "Deloitte": "1038", "Slalom": "166000"},
            "keywords": "solutions engineer OR forward deployed OR implementation engineer"
                        " OR integration engineer OR software engineer",
        },
        "B": {
            "companies": {
                "Franklin Templeton": "3676", "Oracle": "1028", "Intuit": "1666",
                "ServiceNow": "29352", "Bloomberg": "2494",
            },
            "keywords": "software engineer OR backend engineer OR full stack engineer"
                        " OR software developer",
        },
    }
    # geo_id is LinkedIn's location id; a location name alone is ignored by the
    # search. Remote searches skip DISTANCE and filter to remote workplaces.
    LINKEDIN_LOCATIONS: list[dict] = [
        {"name": "San Francisco Bay Area", "geo_id": "90000084", "remote": False},
        {"name": "New York City Metropolitan Area", "geo_id": "90000070", "remote": False},
        {"name": "Greater Seattle Area", "geo_id": "90000091", "remote": False},
        {"name": "San Diego Metropolitan Area", "geo_id": "90010472", "remote": False},
        {"name": "United States", "geo_id": "103644278", "remote": True},
    ]

    # --- Prefilter (prefilter.py) ---
    # Keep in sync with .github/workflows/scrape_linkedin.yml on main.
    # Titles containing any of these (whole words, case-insensitive) are dropped
    # before the per-job detail fetch.
    EXCLUDE_TITLE_TERMS: list[str] = [
        "senior", "sr.", "sr", "staff", "principal", "distinguished", "fellow",
        "lead", "manager", "mgr", "director", "vp", "vice president",
        "head of", "chief", "architect",
        "intern", "internship", "co-op", "apprentice",
    ]
    # Standard IC titles whose words would otherwise trip the list above.
    IC_TITLE_PHRASES: list[str] = ["member of technical staff"]
    # Drop when the description requires this many years or more ("2+" is fine).
    MAX_REQUIRED_YEARS = 3
    # Sentences with these words state a preference, not a requirement.
    PREFERRED_MARKERS: list[str] = [
        "preferred", "nice to have", "nice-to-have", "bonus", "a plus", "ideally",
        "desired", "desirable",
    ]
    # Drop when every graduation year a description names is >= this
    # ("Class of 2026", "graduating between 2026 and 2027").
    GRAD_YEAR_CUTOFF = 2026
    # Clearance-required roles are dropped; the negated phrasings are removed
    # first so "no clearance required" doesn't trip the rule.
    CLEARANCE_TERMS: list[str] = [
        "security clearance", "secret clearance", "top secret", "ts/sci", "ts-sci",
        "active clearance", "clearance required", "clearance is required",
        "polygraph", "public trust clearance", "dod clearance",
    ]
    CLEARANCE_NEGATIONS: list[str] = [
        "no clearance required", "no security clearance required",
        "clearance is not required", "clearance not required",
        "does not require a security clearance", "does not require a clearance",
        "does not require clearance",
    ]

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
    # Job digests from the LinkedIn company tracks, one webhook per track. Both
    # tracks share the startup channel; unset = no job notifications.
    DISCORD_TRACK_WEBHOOKS: dict[str, str] = {
        "A": os.getenv("DISCORD_WEBHOOK_URL_STARTUP", ""),
        "B": os.getenv("DISCORD_WEBHOOK_URL_STARTUP", ""),
    }
