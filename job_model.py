# Standard library
from datetime import datetime
from typing import Optional

# Third-party
from pydantic import BaseModel


class Job(BaseModel):
    company: Optional[str] = None
    status: str = "Have Not Applied"
    role: Optional[str] = None
    description: Optional[str] = None
    salary: Optional[str] = None
    date_submitted: Optional[datetime] = None
    link: Optional[str] = None
    job_level: Optional[str] = None
    # Gemini qualification results, populated after filtering and written to the
    # sheet (Score column, Notes column).
    score: Optional[int] = None
    notes: Optional[str] = None
    # Source-specific id (e.g. hiring.cafe objectID) used to lazily fetch the
    # full description after filtering. Not written to the sheet.
    source_id: Optional[str] = None


class ApplicationRow(BaseModel):
    """One populated row of the tracking sheet, as read back for email matching.

    `tab` plus the 1-based `row` locate the cell range to update. Both are
    needed because the scraper writes a separate tab per run date.
    """
    row: int
    tab: str = ""
    company: str = ""
    status: str = ""
    role: str = ""
    link: str = ""
    notes: str = ""
    rejection_reason: str = ""
    date_submitted: str = ""


class StatusUpdate(BaseModel):
    """One pending write to the tracking sheet, produced by the email checker."""
    tab: str
    row: int
    status: str = ""          # new Application Status (column B); "" leaves it alone
    note_column: str = "F"    # "F" (Notes) or "G" (Rejection Reason)
    note_text: str = ""       # full replacement text for that cell
