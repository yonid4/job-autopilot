# Remote Dispatch

Trigger the job scraper manually from the GitHub web UI or the GitHub mobile app — no laptop needed.

## How to trigger

1. Go to the repo → **Actions** tab → **Run Job Scraper**
2. Click **Run workflow**
3. Fill in the inputs (all optional — defaults shown below)
4. Click **Run workflow**

## Inputs

| Input | Default | Description |
|---|---|---|
| `branch` | `feature/jobspy` | Which scraper to run (`feature/jobspy` or `feature/linkedin-only`) |
| `hours_old` | `12` | Only fetch jobs posted in the last N hours |
| `sheet_name` | `Tracking Template` | Sheet tab to write jobs into — created automatically if it doesn't exist |

## Required secrets

Set these once in **Settings → Secrets and variables → Actions**:

| Secret | What to paste |
|---|---|
| `GEMINI_API_KEY` | Your primary Gemini API key |
| `GEMINI_API_KEYS` | Comma-separated keys for rotation (optional) |
| `SPREAD_SHEET_ID` | The ID from your Google Sheet URL |
| `GOOGLE_SHEETS_CREDS` | Full contents of `credentials.json` |
| `LINKEDIN_LI_AT` | Your LinkedIn `li_at` cookie |
| `LINKEDIN_JSESSIONID` | Your LinkedIn `JSESSIONID` cookie |
| `RESUME_JSON` | Full contents of your `resume.json` |
| `PROXIES` | Comma-separated proxy list (optional) |
