# Job Autopilot

Automatically scrapes job postings, filters them against your resume using Gemini AI, and writes qualifying jobs to a Google Sheet for tracking.

This repo has two functional branches, each using a different scraping backend. Choose the one that fits your setup.

---

## Branches

### [`feature/linkedin-only`](../../tree/feature/linkedin-only)

Uses the [`linkedin-api`](https://github.com/tomquirk/linkedin-api) library to scrape LinkedIn directly via browser session cookies.

**Pros**
- No rate limiting issues — authenticates as your own LinkedIn session
- Fetches full job descriptions natively (no extra requests needed)
- Supports LinkedIn-native filters: experience level, job type, remote, hours old
- No proxy required

**Cons**
- LinkedIn only — cannot scrape Indeed, Glassdoor, or other boards
- Requires manually extracting session cookies from your browser (`li_at` + `JSESSIONID`)
- Cookies expire every few weeks and must be refreshed manually
- Breaks if LinkedIn changes its internal API

---

### [`feature/jobspy`](../../tree/feature/jobspy)

Uses the [`python-jobspy`](https://github.com/Bunsly/JobSpy) library to scrape multiple job boards simultaneously.

**Pros**
- Multi-site: LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google Jobs — all in one run
- No cookie management — no manual browser steps
- More stable long-term (maintained open-source library with community support)

**Cons**
- LinkedIn scraping is unauthenticated and subject to rate limiting / blocks
- May require proxies to reliably scrape LinkedIn at scale
- Job descriptions may be incomplete on some sites
- Experience level filtering is LinkedIn-only; other sites always pass through

---

## Which should I use?

| | `feature/linkedin-only` | `feature/jobspy` |
|---|---|---|
| Sources | LinkedIn only | LinkedIn + Indeed + Glassdoor + more |
| Auth | Browser cookies | None (unauthenticated) |
| Rate limits | Rarely hit | Common on LinkedIn |
| Setup effort | Medium (cookie extraction) | Low |
| Description quality | Full | Varies by site |

**Use `feature/linkedin-only`** if you only care about LinkedIn and want reliable, full-description results without proxies.

**Use `feature/jobspy`** if you want to cast a wider net across multiple job boards.
