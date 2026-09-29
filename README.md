# Job Autopilot

Automatically scrapes job postings, filters them against your resume using Gemini AI, and writes qualifying jobs to a Google Sheet for tracking. A second pass reads your inbox and keeps the sheet up to date as replies come in — marking rejections, assessments, interviews and offers, and pinging Discord about the good news.

## How It Works

1. **Scrapes** job listings from your chosen source — LinkedIn (cookie-based auth via the `linkedin-api` library) or [hiring.cafe](https://hiring.cafe) (no authentication required). Select one with the `SCRAPER` config variable.
2. **Parses** your resume PDF using Gemini to extract structured data (cached as `resume.json`)
3. **Qualifies** each job by scoring resume-to-job fit with Gemini AI — only jobs scoring ≥ 80/100 pass
4. **Writes** new qualifying jobs to your Google Sheet, skipping duplicates

And separately, on its own schedule (`check_email.py`):

5. **Reads** recent mail from your Gmail inbox
6. **Classifies** each message — rejection, online assessment, interview, offer, acknowledgement, or noise
7. **Matches** it to the application it's about, across every tab in your sheet
8. **Marks** the row's Application Status and records what the email said
9. **Notifies** you on Discord when the news is good

See [Email status tracking](#email-status-tracking) below.

## Prerequisites

- Python 3.10+ (3.11 recommended; if using pyenv: `pyenv local 3.11.14`)
- A [Google Cloud Service Account](https://console.cloud.google.com/) with the Sheets API enabled
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- A Google Sheet set up with the column layout described below
- LinkedIn account cookies (`li_at` and `JSESSIONID`) — only required for the LinkedIn scraper (see below)

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

> Only needed if you use the LinkedIn scraper (`SCRAPER = "linkedin"`). The hiring.cafe scraper requires no authentication — you can skip this step.

The LinkedIn scraper authenticates using session cookies from your browser.

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

| A | B | C | D | E | F | G | H | I | J |
|---|---|---|---|---|---|---|---|---|---|
| Company Name | Application Status | Title | Description | Link to Job Req | Notes | Rejection Reason | Salary | Date Submitted | Score |

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
SCRAPER = "linkedin"         # which scraper to run: "linkedin" or "hiringcafe"

SEARCH_TERM = "Software Development"
LOCATION = "San Francisco, CA"
RESULTS_WANTED = 20          # max jobs to add per run
HOURS_OLD = 2                # only jobs posted in the last N hours (None = no limit)

# Companies to skip entirely (case-insensitive)
BLOCKED_COMPANIES = ["Revature", "Epic"]

IS_REMOTE = False
JOB_TYPE = "fulltime"        # "fulltime", "parttime", "internship", "contract", or None
EXPERIENCE_LEVEL = "entry level"  # None = all levels
# Note: hiring.cafe exposes only 4 coarse seniority buckets, so finer levels map to the nearest.

SHEET_TAB_NAME = "Tracking Template"
STATUS_ON_SCRAPE = "Have Not Applied"

# LinkedIn credentials are read from .env — only needed when SCRAPER = "linkedin"
```

`SCRAPER` can also be overridden at runtime via the `SCRAPER` environment variable
(e.g. `SCRAPER=hiringcafe python3 main.py`), which takes precedence over the value
in `config.py`. `BLOCKED_COMPANIES` can likewise be extended via the
`BLOCKED_COMPANIES` env var (comma-separated, e.g. `BLOCKED_COMPANIES="Google,Meta"`).

## Running

```bash
source .venv/bin/activate
python3 main.py                      # uses SCRAPER from config.py
SCRAPER=hiringcafe python3 main.py   # override the scraper for this run
```

`main.py` runs the scraper named by `SCRAPER` (the `SCRAPER` env var wins over `config.py`).
Output will show scraped jobs, any errors, and a summary of how many were added vs. skipped as duplicates.

## Email status tracking

`check_email.py` reads your inbox, works out what each recruiting email is saying, finds the
application it belongs to, and updates the sheet. Positive news also goes to Discord, with a
link that opens the email in Gmail. When the email can't be tied to a row, the notification
uses the company and role the email itself names.

Each line of the run log ends with who decided that email — `[rules]`, or `[gemini: <reason>]`
when it was sent to Gemini.

### What it writes

| Email says | Application Status becomes | Where the detail goes |
|---|---|---|
| Rejection | `Rejected` | Rejection Reason (column G) |
| Online assessment / coding challenge | `OA` | Notes (column F) |
| Interview invite or scheduling | `Interviewing` | Notes (column F) |
| Offer | `Offer Extended - In Progress` | Notes (column F) |
| "We received your application" | `Submitted - Pending Response` | Notes (column F) |
| Job alerts, newsletters, anything else | unchanged | — |

Each note is stamped with the email's date, e.g.
`[2026-09-22] Online assessment: Next step — your HackerRank assessment`. The existing cell
contents are kept underneath, so the Gemini fit analysis already in Notes isn't lost.

A row only ever moves **forward**: `Have Not Applied` → `Submitted - Pending Response` → `OA` →
`Interviewing` → `Offer Extended - In Progress`, with `Rejected` landing from anywhere. A late
auto-reply can't knock a row back from `Interviewing`. `Sent Follow Up Email`, `Re-Applied With
Updated Resume` and `Ghosted` sit level with `Submitted - Pending Response`: real news moves them
on, an auto-reply doesn't.

Rows you've closed out yourself — `Not For Me`, `Offer Extended - Did Not Accept`,
`Rescinded Application (Self) / Decided not a good fit`, `Job Rec Removed/Deactivated`, `N/A` —
are never overwritten, and neither is any status the checker doesn't recognise. Good news for
those still reaches Discord. If your sheet has statuses the checker has no rule for, the run log
lists them at the start.

Column I (Date Submitted) is never touched — it records when *you* applied, not when they replied.

Because the scraper writes a new tab per run, the checker scans **every** tracking tab in the
spreadsheet (any tab whose first header cell is "Company Name"), not just today's.

### How it decides

A weighted phrase matcher handles most recruiting mail on its own — the wording is formulaic, and
it costs nothing. Only genuinely unclear mail goes to Gemini, batched, with a shortlist of your
open applications so it can pick the role as well as the category. Email that matches none of your
applications and reads like nothing in particular never reaches Gemini at all.

Gemini is optional here. With no key set, or when it's overloaded, the rule verdict stands and
anything below `EMAIL_MIN_CONFIDENCE` (default 0.6) is reported but not acted on.

Work already done is tracked by a Gmail label (`Job Autopilot/Processed`, created on first run),
so re-running never double-writes a row or repeats a notification.

### Setup

**1. Gmail access.** The service account used for Sheets can't read a personal mailbox, so this
uses your own OAuth credentials.

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Gmail API** on the
   same project as your Sheets credentials
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app**
3. Download the JSON and save it as `gmail_client_secret.json` in the project root
4. Authorize once:

```bash
python3 gmail_service.py
```

That opens a browser, saves `gmail_token.json` locally, and prints the three values to paste into
GitHub Actions secrets. The scope requested is `gmail.modify` — read messages and change their
labels. It cannot send or delete mail.

**2. Discord notifications.** In your Discord server, open the notifications channel →
**Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**, and set it as
`DISCORD_WEBHOOK_URL`. Optionally set `DISCORD_MENTION` to `<@your-user-id>` so pings reach your
phone. With no webhook set, the checker still updates the sheet and just skips notifying.

**3. Check the status strings.** `STATUS_APPLIED`, `STATUS_ASSESSMENT`, `STATUS_INTERVIEW`,
`STATUS_OFFER` and `STATUS_REJECTED` in `config.py` must match your sheet's Application Status
dropdown exactly, or Sheets will flag the cells as invalid entries. The defaults match the tracking
template. `STATUS_WAITING` and `STATUS_FINAL` list the dropdown's other options, so the checker
knows which to move on from and which to leave alone.

### Running

```bash
EMAIL_DRY_RUN=1 python3 check_email.py   # print the plan, write nothing — do this first
python3 check_email.py                   # for real
```

A dry run leaves Gmail untouched too, so you can repeat it until the plan looks right.

To run it on a schedule, the `.github/workflows/check_email.yml` workflow must live on the
repo's **default branch** — GitHub only schedules workflows from there — while it checks the code
out from `linkedin-hiringcafe`. It needs these secrets: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
`GMAIL_REFRESH_TOKEN`, `DISCORD_WEBHOOK_URL`, plus the `SPREAD_SHEET_ID`, `GOOGLE_SHEETS_CREDS`
and `GEMINI_API_KEY(S)` the scraper already uses.

### Tests

```bash
python3 test_email_tracker.py
```

Runs offline against fixtures — no Gmail, Sheets, Gemini or credentials needed. Covers the
classifier, the email-to-row matcher and the status ladder.

## Project Structure

```
job-autopilot/
├── main.py              # Entry point — selects scraper and orchestrates the pipeline
├── linkedin_service.py  # Fetches jobs via LinkedIn API (cookie auth)
├── hiringcafe_service.py # Fetches jobs from hiring.cafe (no auth)
├── qualifiar.py         # Gemini AI resume-to-job scoring
├── resume_processor.py  # PDF parsing and resume caching
├── sheets.py            # Google Sheets read/write
├── job_model.py         # Job and tracking-row data models
├── check_email.py       # Entry point — inbox -> sheet status + Discord
├── gmail_service.py     # Gmail OAuth, fetching, processed-label bookkeeping
├── email_classifier.py  # Phrase rules, with Gemini for the unclear ones
├── email_model.py       # Email and verdict data models
├── application_matcher.py # Works out which sheet row an email is about
├── application_status.py  # Status names and the forward-only status ladder
├── discord_notifier.py  # Webhook notifications for good news
├── gemini_client.py     # Shared Gemini JSON calls with key rotation
├── test_email_tracker.py # Offline tests for the email pipeline
├── config.py            # All configuration
├── requirements.txt
├── .env                 # Your secrets (not committed)
├── resume.pdf           # Your resume (not committed)
├── gmail_token.json     # Gmail OAuth token (not committed)
├── credentials/         # Google service account key (not committed)
└── resume.json          # Cached parsed resume (not committed)
```
