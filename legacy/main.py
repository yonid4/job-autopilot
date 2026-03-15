# Standard library
import os

# Local
from legacy import linkedin_service
from legacy import sheets
from legacy.config import Config as config
from legacy.qualifiar import filtered_jobs
from legacy.resume_processor import load_resume, process_resume, RESUME_JSON_PATH

_RESUME_PDF_PATH = os.path.join(os.path.dirname(__file__), "resume.pdf")


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
    n = len(new_jobs)
    for i in range(0, n, batch_size):
        qualified_jobs.extend(filtered_jobs(new_jobs[i:min(i + batch_size, n)], resume))

    if not qualified_jobs:
        print("No jobs passed the qualification threshold.")
        return

    new_jobs = qualified_jobs[:config.RESULTS_WANTED]

    sheets.append_jobs(new_jobs)
    print(f"Done: {len(new_jobs)} new jobs added, {duplicates} duplicates skipped.")


if __name__ == "__main__":
    main()
