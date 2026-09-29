# Job Autopilot

Job Autopilot takes the grind out of a job search. It scrapes new job postings, uses Gemini AI to score each one against your resume, and writes the jobs that fit into a Google Sheet so you can track your applications in one place. The most complete version also reads your Gmail inbox and updates each application's status as replies come in (rejections, online assessments, interviews, offers), and pings you on Discord when the news is good.

The application code lives on the branches below. Each one takes a different approach, so pick the one that fits your setup. `main` holds this overview and the shared GitHub Actions workflows:

- **Run Job Scraper** (`dispatch.yml`): run a scraper branch on demand from the GitHub UI or mobile app. See [`dispatch/README.md`](dispatch/README.md).
- **Check Application Email** (`check_email.yml`): runs the inbox checker from `linkedin-hiringcafe` once a day. GitHub only schedules workflows from the default branch, which is why it lives here.
- **CI** (`ci.yml`): a Python syntax check on pull requests to `main`.

Each branch has its own README with full setup steps.

---

## Branches

### [`linkedin-hiringcafe`](../../tree/linkedin-hiringcafe) *(recommended)*

The most complete, actively developed version, and the default target of both workflows. It scrapes either LinkedIn (via the [`linkedin-api`](https://github.com/tomquirk/linkedin-api) library and browser session cookies) or [hiring.cafe](https://hiring.cafe) (no authentication). You pick the source with the `SCRAPER` setting. A second script, `check_email.py`, classifies recruiting emails and updates the Application Status of the matching row in your sheet.

**Pros**
- Two scraping sources; hiring.cafe needs no cookies, proxies, or login
- Email status tracking: rejections, OAs, interviews and offers are written to the sheet automatically, and a row's status only ever moves forward
- Discord notifications for assessments, interviews and offers
- Company blocklist (`BLOCKED_COMPANIES`), Gemini key rotation, and a Score column (J) that the sheet is sorted and highlighted by
- Offline tests for the email pipeline and the hiring.cafe scraper

**Cons**
- The most setup: Gmail OAuth credentials and a Discord webhook are needed for the email tracker
- The LinkedIn source still relies on cookies that expire every few weeks
- hiring.cafe only has 4 coarse seniority buckets, so experience level filtering is approximate

---

### [`legacy-scraper`](../../tree/legacy-scraper)

The original single-purpose CLI pipeline: scrape LinkedIn, score each job with Gemini, and write the jobs that pass to the sheet. The FastAPI experiment was removed from this branch and its files moved back to the project root.

**Pros**
- Small and easy to follow: one `main.py` and a few modules
- Includes the company blocklist, Gemini's fit analysis in the Notes column, and sorting by score
- Includes a Gemini 503 fallback that writes the prompts to the workflow run summary so no run is wasted

**Cons**
- LinkedIn only, and it needs browser cookies
- No email tracking or notifications
- Not actively developed; new features land on `linkedin-hiringcafe`

---

### [`feature/linkedin-only`](../../tree/feature/linkedin-only)

Uses the [`linkedin-api`](https://github.com/tomquirk/linkedin-api) library to scrape LinkedIn directly via browser session cookies.

**Pros**
- No rate limiting issues, since it authenticates as your own LinkedIn session
- Fetches full job descriptions natively (no extra requests needed)
- Supports LinkedIn-native filters: experience level, job type, remote, hours old
- No proxy required

**Cons**
- LinkedIn only; it cannot scrape Indeed, Glassdoor, or other boards
- Requires manually extracting session cookies from your browser (`li_at` + `JSESSIONID`)
- Cookies expire every few weeks and must be refreshed manually
- Breaks if LinkedIn changes its internal API
- An early branch that has since been superseded by `legacy-scraper` and `linkedin-hiringcafe`

---

### [`feature/jobspy`](../../tree/feature/jobspy)

Uses the [`python-jobspy`](https://github.com/Bunsly/JobSpy) library to scrape multiple job boards at once.

**Pros**
- Multi-site: LinkedIn, Indeed, Glassdoor, ZipRecruiter and Google Jobs in a single run
- No cookie management and no manual browser steps
- More stable long-term (a maintained open-source library with community support)
- Creates the sheet tab automatically, copying the template's formatting

**Cons**
- LinkedIn scraping is unauthenticated and subject to rate limiting / blocks
- May require proxies to reliably scrape LinkedIn at scale
- Job descriptions may be incomplete on some sites
- Experience level filtering is LinkedIn-only; jobs from other sites always pass that filter
- No longer actively developed

---

### [`feature/local-app`](../../tree/feature/local-app)

An experimental rewrite as a local web app: a FastAPI backend with a SQLite database and a Streamlit UI. On top of scraping and qualifying, it generates a tailored resume summary, fit score and cover letter for any stored job, and tracks each application's status in the app.

**Pros**
- Tailored resumes (rendered to PDF with LaTeX) and cover letters that weave in your best-matching project
- REST API with interactive docs, plus a Streamlit UI over every feature
- Stores every scraped job locally; only jobs above `MIN_FIT_SCORE` are pushed to the sheet
- Resume versioning and application status tracking built in
- Has a pytest suite

**Cons**
- Heavier setup: needs a running API server, `pdflatex`, and more configuration
- Runs locally only; it isn't wired into the GitHub Actions workflows
- LinkedIn only, with cookie auth
- Experimental: a work in progress towards a larger multi-user platform

---

## Which should I use?

| | `linkedin-hiringcafe` | `legacy-scraper` | `feature/linkedin-only` | `feature/jobspy` | `feature/local-app` |
|---|---|---|---|---|---|
| Sources | LinkedIn or hiring.cafe | LinkedIn only | LinkedIn only | LinkedIn + Indeed + Glassdoor + more | LinkedIn only |
| Auth | Cookies (LinkedIn) / none (hiring.cafe) | Browser cookies | Browser cookies | None (unauthenticated) | Browser cookies |
| Rate limits | Rarely hit | Rarely hit | Rarely hit | Common on LinkedIn | Rarely hit |
| Email status tracking | Yes (+ Discord) | No | No | No | In-app, manual |
| Resume / cover letter tailoring | No | No | No | No | Yes |
| Interface | CLI + GitHub Actions | CLI + GitHub Actions | CLI | CLI | FastAPI + Streamlit |
| Setup effort | Medium–High | Medium | Medium | Low | High |
| Status | Active | Stable, no new features | Superseded | Inactive | Experimental |

**Use `linkedin-hiringcafe`** for most setups. It's the most complete version, runs from GitHub Actions, and keeps your sheet up to date from your inbox.

**Use `legacy-scraper`** if you just want the simple LinkedIn → Gemini → Sheet pipeline without the email tracker.

**Use `feature/jobspy`** if you want to cast a wider net across multiple job boards and don't mind possible rate limiting.

**Use `feature/local-app`** if you want tailored resumes and cover letters and are happy running a local server.

`feature/linkedin-only` is kept for reference; `legacy-scraper` and `linkedin-hiringcafe` build on it.
