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