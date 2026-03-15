# Standard library
import os

# Third-party
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Local
from legacy.config import Config as config
from legacy.job_model import Job

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
_CREDENTIALS_PATH = os.environ["GOOGLE_CREDENTIALS_PATH"]

# Column G (index 6) — "Link to Job Req"
_LINK_COLUMN = "G"
_LINK_COLUMN_INDEX = 6


def _get_service():
    creds = Credentials.from_service_account_file(_CREDENTIALS_PATH, scopes=_SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()


def get_existing_links() -> set[str]:
    """
    Read all values in the 'Link to Job Req' column and return them as a set.
    Used for deduplication before appending new jobs.
    """
    service = _get_service()
    range_ = f"{config.SHEET_TAB_NAME}!{_LINK_COLUMN}:{_LINK_COLUMN}"
    result = service.values().get(spreadsheetId=_SHEET_ID, range=range_).execute()
    rows = result.get("values", [])
    # Each row is a list with one element; skip header row
    return {row[0] for row in rows[1:] if row and row[0]}


def _get_first_empty_row(service) -> int:
    """
    Find the first row where column A (Company Name) is blank.
    Returns the 1-based row number.
    """
    range_ = f"{config.SHEET_TAB_NAME}!A:A"
    result = service.values().get(spreadsheetId=_SHEET_ID, range=range_).execute()
    rows = result.get("values", [])
    # rows is a list of ["value"] for filled cells; missing entries = blank
    # Find first index after header (index 0) where value is missing or empty
    for i, row in enumerate(rows[1:], start=2):  # start=2 because row 1 is header
        if not row or not row[0].strip():
            return i
    # All rows filled — return one past the last
    return len(rows) + 1


def append_jobs(jobs: list[Job]) -> None:
    """
    Write jobs into existing pre-formatted empty rows starting at the first blank
    Company Name row. Uses update (not insert) so cell formatting is preserved.

    Column order (must match sheet exactly):
    A: Company Name | B: Application Status | C: Title | D: Description
    E: Salary | F: Date Submitted | G: Link to Job Req | H: Rejection Reason | I: Notes
    """
    if not jobs:
        return

    service = _get_service()
    start_row = _get_first_empty_row(service)
    end_row = start_row + len(jobs) - 1
    range_ = f"{config.SHEET_TAB_NAME}!A{start_row}:I{end_row}"

    rows = [
        [
            job.company or "",           # A: Company Name
            config.STATUS_ON_SCRAPE,     # B: Application Status
            job.role or "",              # C: Title
            job.description or "",       # D: Description
            job.salary or "",            # E: Salary
            "",                          # F: Date Submitted (empty on scrape)
            job.link or "",              # G: Link to Job Req
            "N/A",                       # H: Rejection Reason
            "",                          # I: Notes
        ]
        for job in jobs
    ]

    service.values().update(
        spreadsheetId=_SHEET_ID,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
