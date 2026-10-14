# Standard library
import os
from typing import Callable

# Local
import discord_notifier
import hiringcafe_service
import linkedin_service
import prefilter
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
    "linkedin": linkedin_service.enrich_details,
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


def _drop_rejected(jobs: list[Job], reason_fn: Callable[[Job], str | None], stage: str) -> list[Job]:
    """Jobs the prefilter keeps; each dropped job is logged with its reason."""
    kept: list[Job] = []
    for job in jobs:
        reason = reason_fn(job)
        if reason:
            print(f"[prefilter] {stage}: dropping {job.company} — {job.role} ({reason})")
        else:
            kept.append(job)
    return kept


def _scrape_and_add(scraper_name: str, scrape_fn: ScrapeFn, resume) -> tuple[list[Job], list[str], int]:
    """Scrape, filter, qualify and write to the sheet.

    Returns (jobs added to the sheet, scrape errors, Gemini batches that 503'd).
    """
    jobs, errors = scrape_fn()

    for err in errors:
        print(f"[error] {err}")

    if not jobs:
        print(f"No jobs returned from {scraper_name} service.")
        return [], errors, 0

    # Dedup against every tracking tab, not just today's: the scraper writes a
    # tab per run date, and the lookback window overlaps the previous day.
    # get_existing_links() also creates today's tab when it's missing.
    existing_links = sheets.get_existing_links() | {
        row.link for row in sheets.get_application_rows() if row.link
    }
    new_jobs = [j for j in jobs if j.link not in existing_links]
    duplicates = len(jobs) - len(new_jobs)

    blocked = {c.lower() for c in config.BLOCKED_COMPANIES}
    new_jobs = [j for j in new_jobs if (j.company or "").lower() not in blocked]

    # Free title cull before the per-job detail fetch.
    new_jobs = _drop_rejected(new_jobs, lambda j: prefilter.title_reject_reason(j.role), "title")

    if not new_jobs:
        print(f"No new jobs found ({duplicates} duplicates skipped).")
        return [], errors, 0

    # Fetch heavy per-job data (e.g. full descriptions) only for the jobs that
    # survived dedup/block filtering, before they go to Gemini qualification.
    enrich_fn = _ENRICHERS.get(scraper_name)
    if enrich_fn:
        for err in enrich_fn(new_jobs):
            print(f"[error] {err}")

    # Free description rules (years, graduation window, clearance) before the
    # paid Gemini call. The title is included so "New Grad (2026)" counts.
    new_jobs = _drop_rejected(
        new_jobs,
        lambda j: prefilter.jd_reject_reason(f"{j.role}.\n{j.description or ''}"),
        "description",
    )

    if not new_jobs:
        print("No jobs left after the description rules.")
        return [], errors, 0

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
        return [], errors, 0

    added: list[Job] = []
    if qualified_jobs:
        added = qualified_jobs[:config.RESULTS_WANTED]
        sheets.append_jobs(added)
        print(f"Done: {len(added)} new jobs added, {duplicates} duplicates skipped.")

    # Sort the sheet by Score (column J) descending, Z-to-A. Runs after everything
    # that could be added was added — even if Gemini 503'd on some batches.
    print("[sheets] sorting by score (column J), highest first...")
    sheets.sort_by_score()

    # Ensure rows scoring >= 90 are highlighted light green 1. Idempotent, so
    # safe to run every time.
    sheets.ensure_score_highlight_rule()

    if fallback_prompts:
        print(f"Gemini was overloaded for {len(fallback_prompts)} batch(es). Fallback prompts written to the workflow run summary.")

    return added, errors, len(fallback_prompts)


def _notify_tracks(added: list[Job], errors: list[str], overloaded_batches: int) -> None:
    """Post one digest per track webhook — a heartbeat when it got no matches.

    Tracks that share a webhook share one digest. The note carries anything
    that makes a quiet run suspicious: scrape errors or Gemini overload."""
    webhooks: dict[str, str] = getattr(config, "DISCORD_TRACK_WEBHOOKS", {})
    notes = []
    if errors:
        notes.append(f"⚠️ {len(errors)} scrape error(s), first: {errors[0][:300]}")
    if overloaded_batches:
        notes.append(f"⚠️ Gemini was overloaded for {overloaded_batches} batch(es) — "
                     "fallback prompts are in the workflow run summary.")
    note = "\n".join(notes)

    if not any(webhooks.values()):
        print("[discord] no track webhooks set — skipping job notifications")
    for url in dict.fromkeys(u for u in webhooks.values() if u):
        tracks = {t for t, u in webhooks.items() if u == url}
        discord_notifier.notify_jobs(
            [j for j in added if j.track in tracks], webhook_url=url, note=note,
        )


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

    tracks = getattr(config, "LINKEDIN_COMPANY_TRACKS", None) if scraper_name == "linkedin" else None
    if tracks:
        print(f"Scraping with '{scraper_name}': {len(tracks)} company track(s) "
              f"in {len(config.LINKEDIN_LOCATIONS)} location(s)\n")
    else:
        print(f"Scraping with '{scraper_name}': {config.SEARCH_TERM} in {config.LOCATION}\n")

    added, errors, overloaded_batches = _scrape_and_add(scraper_name, scrape_fn, resume)

    # Only the LinkedIn company tracks have Discord channels.
    if tracks:
        _notify_tracks(added, errors, overloaded_batches)


if __name__ == "__main__":
    main()
