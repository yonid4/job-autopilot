# Standard library
import os
from typing import Callable

# Local
import hiringcafe_service
import linkedin_service
import sheets
from config import Config as config
from job_model import Job
from qualifiar import filtered_jobs, GeminiOverloadError
from resume_processor import load_resume, process_resume, RESUME_JSON_PATH

_RESUME_PDF_PATH = os.path.join(os.path.dirname(__file__), "resume.pdf")

# Selectable scrapers. Each exposes the same run_scrape() contract.
ScrapeFn = Callable[[], tuple[list[Job], list[str]]]
_SCRAPERS: dict[str, ScrapeFn] = {
    "linkedin": linkedin_service.run_scrape,
    "hiringcafe": hiringcafe_service.run_scrape,
}

# Optional post-filter enrichers: fetch heavy per-job data (e.g. full
# descriptions) only for jobs that survive dedup/block filtering. Mutate jobs in
# place and return a list of error strings. Scrapers without one are left as-is.
EnrichFn = Callable[[list[Job]], list[str]]
_ENRICHERS: dict[str, EnrichFn] = {
    "hiringcafe": hiringcafe_service.enrich_descriptions,
}


def _select_scraper() -> tuple[str, ScrapeFn] | tuple[None, None]:
    """Resolve which scraper to run.

    Prefers the SCRAPER env var (passed from the GitHub workflow), then
    config.SCRAPER, then defaults to "linkedin". Returns (name, run_scrape) or
    (None, None) if the requested scraper is unknown.
    """
    name = (os.getenv("SCRAPER") or getattr(config, "SCRAPER", "") or "linkedin").strip().lower()
    return (name, _SCRAPERS[name]) if name in _SCRAPERS else (None, None)


def _write_fallback_summary(prompts: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        print("[fallback] GITHUB_STEP_SUMMARY not set — printing prompts to stdout instead")
        for i, prompt in enumerate(prompts, 1):
            print(f"\n{'='*60}\nFALLBACK PROMPT — BATCH {i}\n{'='*60}\n{prompt}\n")
        return

    total = len(prompts)
    lines = [
        "## Gemini Overloaded — Manual Fallback Prompts\n",
        f"Gemini returned **503 (high demand)** for **{total} batch{'es' if total != 1 else ''}** of jobs. "
        "Paste each prompt below into [Google Gemini](https://gemini.google.com) to get the same qualification analysis.\n",
        "**How to use:**\n",
        "1. Open [Google Gemini](https://gemini.google.com)\n",
        "2. Start a new chat and paste the prompt for each batch\n",
        "3. Gemini will return a JSON array — jobs with `qualification_score >= 80` are your matches\n",
        "\n---\n",
    ]

    for i, prompt in enumerate(prompts, 1):
        lines += [
            f"\n<details>\n<summary>Batch {i} of {total} — click to expand prompt</summary>\n\n",
            "```\n",
            prompt,
            "\n```\n\n</details>\n",
        ]

    with open(summary_path, "a") as f:
        f.writelines(lines)


def main() -> None:
    if os.path.isfile(RESUME_JSON_PATH):
        print("Loading cached resume...")
        resume = load_resume()
    else:
        print("Resume not found. Processing resume.pdf...")
        resume = process_resume(_RESUME_PDF_PATH)
        print("Resume processed and saved.")

    scraper_name, scrape_fn = _select_scraper()
    if scraper_name is None or scrape_fn is None:
        print(f"Unknown SCRAPER {os.getenv('SCRAPER') or getattr(config, 'SCRAPER', None)!r}. "
              f"Valid options: {', '.join(_SCRAPERS)}.")
        return

    print(f"Scraping with '{scraper_name}': {config.SEARCH_TERM} in {config.LOCATION}\n")

    jobs, errors = scrape_fn()

    for err in errors:
        print(f"[error] {err}")

    if not jobs:
        print(f"No jobs returned from {scraper_name} service.")
        return

    existing_links = sheets.get_existing_links()
    new_jobs = [j for j in jobs if j.link not in existing_links]
    duplicates = len(jobs) - len(new_jobs)

    blocked = {c.lower() for c in config.BLOCKED_COMPANIES}
    new_jobs = [j for j in new_jobs if (j.company or "").lower() not in blocked]

    if not new_jobs:
        print(f"No new jobs found ({duplicates} duplicates skipped).")
        return

    # Fetch heavy per-job data (e.g. full descriptions) only for the jobs that
    # survived dedup/block filtering, before they go to Gemini qualification.
    enrich_fn = _ENRICHERS.get(scraper_name)
    if enrich_fn:
        for err in enrich_fn(new_jobs):
            print(f"[error] {err}")

    # Filter jobs using Gemini AI API using user's resume
    batch_size = 6
    qualified_jobs = []
    fallback_prompts: list[str] = []
    n = len(new_jobs)
    total_batches = (n + batch_size - 1) // batch_size
    print(f"\n[gemini] Qualifying {n} job(s) via {total_batches} request(s) "
          f"(batch size {batch_size})...")
    for i in range(0, n, batch_size):
        batch = new_jobs[i:min(i + batch_size, n)]
        batch_num = i // batch_size + 1
        print(f"[gemini] Sending request {batch_num}/{total_batches} "
              f"({len(batch)} job(s))...")
        try:
            qualified_jobs.extend(filtered_jobs(batch, resume))
        except GeminiOverloadError as e:
            print(f"[gemini] 503 overload on batch {batch_num} — saving fallback prompt")
            fallback_prompts.append(e.prompt)

    if fallback_prompts:
        _write_fallback_summary(fallback_prompts)

    if not qualified_jobs and not fallback_prompts:
        print("No jobs passed the qualification threshold.")
        return

    if qualified_jobs:
        new_jobs = qualified_jobs[:config.RESULTS_WANTED]
        sheets.append_jobs(new_jobs)
        print(f"Done: {len(new_jobs)} new jobs added, {duplicates} duplicates skipped.")

    if fallback_prompts:
        print(f"Gemini was overloaded for {len(fallback_prompts)} batch(es). Fallback prompts written to the workflow run summary.")


if __name__ == "__main__":
    main()
