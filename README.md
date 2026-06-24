# Job Autopilot

FastAPI backend that scrapes LinkedIn jobs, qualifies them against your resume using Gemini AI, generates tailored resumes and cover letters, and pushes qualifying jobs to a Google Sheet.

## How It Works

1. **Scrapes** job listings from LinkedIn using cookie-based authentication
2. **Qualifies** each job by batch-scoring resume-to-job fit with Gemini — only jobs scoring ≥ `MIN_FIT_SCORE` are pushed to the sheet (all are stored locally)
3. **Embeds** lazily — job embeddings are computed on first tailor request and cached; no embedding calls at scrape time
4. **Tailors** on demand — generates a professional summary, fit score, and cover letter for any stored job; the best-matching project is automatically woven into the cover letter as a hook
5. **Tracks** applications with status progression (`not_applied → applied → interviewing → offered / rejected / withdrawn`)

## Prerequisites

- Python 3.11 (if using pyenv: `pyenv local 3.11.14`)
- `pdflatex` installed (for resume PDF rendering): `brew install --cask mactex-no-gui`
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- A Google Cloud Service Account with the Sheets API enabled
- LinkedIn account cookies (`li_at` and `JSESSIONID`)
- A Google Sheet based on the template linked in Setup

## Setup

### 1. Clone and install

```bash
git clone https://github.com/yonid4/job-autopilot.git
cd job-autopilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy the example config:

```bash
cp app/config.example.py app/config.py
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
SMART_GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_CREDENTIALS_PATH=credentials/service_account.json
LINKEDIN_LI_AT=your_li_at_cookie_value
LINKEDIN_JSESSIONID=your_jsessionid_cookie_value

# Job search
SEARCH_TERM=Software Engineer
LOCATION=San Francisco, CA
RESULTS_WANTED=50
HOURS_OLD=12
IS_REMOTE=false
JOB_TYPE=fulltime
EXPERIENCE_LEVEL=entry level
BLOCKED_COMPANIES=Company A,Company B

# Qualification
MIN_FIT_SCORE=80
QUALIFY_BATCH_SIZE=6
```

### 3. Get LinkedIn cookies

1. Log into [linkedin.com](https://www.linkedin.com) in your browser
2. Open DevTools (`F12` or `Cmd+Option+I`)
3. Go to **Application → Storage → Cookies → `https://www.linkedin.com`**
4. Copy `li_at` → `LINKEDIN_LI_AT` and `JSESSIONID` → `LINKEDIN_JSESSIONID`

Cookies expire every few weeks. If scraping stops returning results, refresh them.

### 4. Set up Google Sheets

1. [Google Cloud Console](https://console.cloud.google.com/) → Enable the **Google Sheets API**
2. Create a Service Account, generate a JSON key, save it to `credentials/service_account.json`
3. Make a copy of the [sheet template](https://docs.google.com/spreadsheets/d/1nq5tb-i-zVW7ZBCcT3GLHhX8smXZALLcC_kScNswNAQ/copy)
4. Share the copy with the service account email (Editor access)
5. Set `SMART_GOOGLE_SHEET_ID` to the ID from the sheet URL

The template has a tab named `"Jobs"` with columns: Company | Status | Title | Description | Salary | Date | Link | Rejection Reason | Notes

## Running

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

For a simple UI over all features, run the Streamlit app in a second terminal (the API must be running):

```bash
source .venv/bin/activate
streamlit run ui.py
```

The UI opens at `http://localhost:8501`. Set `JOB_AUTOPILOT_API_URL` if the API is not on `http://localhost:8000`.

```bash
pytest tests/ -v   # run tests
```

## API Endpoints

All endpoints are under `/api/v1`.

### Resumes
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/resumes/upload` | Upload a PDF resume (parse + embed runs in background) |
| `GET` | `/resumes` | List all resume versions |

### Jobs
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs/ingest` | Ingest a job by LinkedIn URL (scrapes if not cached) |
| `POST` | `/jobs/manual` | Ingest a job with manually provided data |
| `GET` | `/jobs` | List recently ingested jobs |
| `POST` | `/jobs/scrape` | Bulk LinkedIn scrape using config params (runs in background) |

### Projects
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/projects` | Add a project (embedded for cover letter hook matching) |
| `GET` | `/projects` | List your projects |

### Tailoring
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tailor/resume` | Generate a tailored summary + fit score for a job |
| `POST` | `/tailor/cover-letter` | Generate a tailored cover letter with best project hook |
| `POST` | `/tailor/full` | Run the full pipeline (summary + cover letter) in one call |

### Applications
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/applications` | List applications, optionally filtered by `?status=` |
| `PATCH` | `/applications/{id}/status` | Update application status |

## Project Structure

```
app/
├── api/
│   ├── auth.py          # User identity (single local user)
│   └── routes.py        # All FastAPI route handlers
├── core/
│   └── database.py      # SQLite helpers (data.db)
├── models/
│   └── schemas.py       # Pydantic request/response models
├── services/
│   ├── gemini_service.py    # Gemini generation + embedding + batch qualify
│   ├── job_service.py       # Job ingestion, dedup, bulk scrape, projects
│   ├── latex_service.py     # LaTeX → PDF resume rendering
│   ├── resume_service.py    # PDF parse, chunk, embed
│   ├── sheets_service.py    # Google Sheets push
│   └── tailoring_engine.py  # Fit score + summary + cover letter pipeline
├── utils/
│   └── resume_formatter.py  # LaTeX escaping and template injection
├── config.example.py    # Copy to config.py and fill in values
└── main.py              # FastAPI app entry point
tests/
templates/               # LaTeX .tex templates
data.db                  # Local SQLite database (not committed)
legacy/                  # Original CLI pipeline (kept for reference)
```

## Notes

- `app/config.py` and `.env` are gitignored — each user keeps their own
- `data.db`, `credentials/`, `resume.pdf` are never committed
- The single local user ID is hardcoded in `auth.py` — no login required
- Job embeddings are computed lazily on first tailor request and cached to avoid unnecessary API calls during scraping
