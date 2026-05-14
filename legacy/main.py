# Standard library
import os

# Local
from legacy import linkedin_service
from legacy import sheets
from legacy.config import Config as config
from legacy.qualifiar import filtered_jobs, GeminiOverloadError
from legacy.resume_processor import load_resume, process_resume, RESUME_JSON_PATH

_RESUME_PDF_PATH = os.path.join(os.path.dirname(__file__), "resume.pdf")


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

    print(f"Scraping: {config.SEARCH_TERM} in {config.LOCATION}\n")

    jobs, errors = linkedin_service.run_scrape()

    for err in errors:
        print(f"[error] {err}")

    if not jobs:
        print("No jobs returned from linkedin service.")
        return

    existing_links = sheets.get_existing_links()
    new_jobs = [j for j in jobs if j.link not in existing_links]
    duplicates = len(jobs) - len(new_jobs)

    if not new_jobs:
        print(f"No new jobs found ({duplicates} duplicates skipped).")
        return

    # Filter jobs using Gemini AI API using user's resume
    batch_size = 6
    qualified_jobs = []
    fallback_prompts: list[str] = []
    n = len(new_jobs)
    for i in range(0, n, batch_size):
        batch = new_jobs[i:min(i + batch_size, n)]
        try:
            qualified_jobs.extend(filtered_jobs(batch, resume))
        except GeminiOverloadError as e:
            batch_num = i // batch_size + 1
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
