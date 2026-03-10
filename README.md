# Job Autopilot

Automatically scrapes job postings, filters them against your resume using Gemini AI, and writes qualifying jobs to a Google Sheet for tracking.

## How It Works

1. **Scrapes** job listings directly from LinkedIn using cookie-based authentication via the `linkedin-api` library
2. **Parses** your resume PDF using Gemini to extract structured data (cached as `resume.json`)
3. **Qualifies** each job by scoring resume-to-job fit with Gemini AI — only jobs scoring ≥ 80/100 pass
4. **Writes** new qualifying jobs to your Google Sheet, skipping duplicates

## Prerequisites

- Python 3.10+ (3.11 recommended; if using pyenv: `pyenv local 3.11.14`)
- A [Google Cloud Service Account](https://console.cloud.google.com/) with the Sheets API enabled
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- A Google Sheet set up with the column layout described below
- LinkedIn account cookies (`li_at` and `JSESSIONID`) — see below

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/yonid4/job-autopilot.git
cd job-autopilot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_CREDENTIALS_PATH=credentials/service_account.json
LINKEDIN_LI_AT=your_li_at_cookie_value
LINKEDIN_JSESSIONID=your_jsessionid_cookie_value
```

- **`GEMINI_API_KEY`** — from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **`GOOGLE_SHEET_ID`** — the long ID in your Google Sheet URL: `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`
- **`GOOGLE_CREDENTIALS_PATH`** — path to your service account JSON key file (see step 3)
- **`LINKEDIN_LI_AT`** — your LinkedIn `li_at` session cookie (see "Getting LinkedIn Cookies" below)
- **`LINKEDIN_JSESSIONID`** — your LinkedIn `JSESSIONID` cookie (see "Getting LinkedIn Cookies" below)

### 3. Getting LinkedIn Cookies

The scraper authenticates with LinkedIn using session cookies from your browser.

1. Log into [linkedin.com](https://www.linkedin.com) in your browser
2. Open DevTools (`F12` or `Cmd+Option+I`)
3. Go to **Application** > **Storage** > **Cookies** > `https://www.linkedin.com`
4. Find and copy the values for:
   - `li_at` — set as `LINKEDIN_LI_AT` in your `.env`
   - `JSESSIONID` — set as `LINKEDIN_JSESSIONID` in your `.env` (include the surrounding quotes if present)

> **Note:** These cookies expire periodically (typically every few weeks). If the scraper stops returning results or throws auth errors, repeat the steps above to refresh them.

### 4. Set up Google Sheets access

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → Create or select a project
2. Enable the **Google Sheets API**
3. Create a **Service Account** (IAM & Admin → Service Accounts → Create)
4. Generate a JSON key for the service account and save it to `credentials/service_account.json`
5. Share your Google Sheet with the service account's email address (give it **Editor** access)

### 5. Set up your Google Sheet

Make a copy of the [Google Sheet template](https://docs.google.com/spreadsheets/d/1nq5tb-i-zVW7ZBCcT3GLHhX8smXZALLcC_kScNswNAQ/copy) (File → Make a copy). It already has the correct tab name and column layout.

The sheet has a tab named `"Tracking Template"` with these columns:

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| Company Name | Application Status | Title | Description | Salary | Date Submitted | Link to Job Req | Rejection Reason | Notes |

Row 1 is the header row. The script writes into the first blank row in column A, preserving any existing formatting.

### 6. Add your resume

Place your resume as `resume.pdf` in the project root. On first run, Gemini parses it and caches the result as `resume.json`. Subsequent runs use the cache.

To re-parse your resume (e.g., after updating it), delete `resume.json`.

## Configuration

Copy the example config and edit it:

```bash
cp config.example.py config.py
```

Edit `config.py` to customize your search (`config.py` is gitignored — each user keeps their own):

```python
SEARCH_TERM = "software engineer"
LOCATION = "San Francisco, CA"
RESULTS_WANTED = 20          # max jobs to add per run
HOURS_OLD = 2                # only jobs posted in the last N hours (None = no limit)

IS_REMOTE = False
JOB_TYPE = "fulltime"        # "fulltime", "parttime", "internship", "contract", or None
EXPERIENCE_LEVEL = "entry level"  # None = all levels

SHEET_TAB_NAME = "Tracking Template"
STATUS_ON_SCRAPE = "Have Not Applied"

# LinkedIn credentials are read from .env — see step 2
```

## Running

```bash
source .venv/bin/activate
python3 main.py
```

Output will show scraped jobs, any errors, and a summary of how many were added vs. skipped as duplicates.

## Project Structure

```
job-autopilot/
├── main.py              # Entry point — orchestrates the pipeline
├── linkedin_service.py  # Fetches jobs via LinkedIn API (cookie auth)
├── qualifiar.py         # Gemini AI resume-to-job scoring
├── resume_processor.py  # PDF parsing and resume caching
├── sheets.py            # Google Sheets read/write
├── job_model.py         # Job data model
├── config.py            # All configuration
├── requirements.txt
├── .env                 # Your secrets (not committed)
├── resume.pdf           # Your resume (not committed)
├── credentials/         # Google service account key (not committed)
└── resume.json          # Cached parsed resume (not committed)
```
