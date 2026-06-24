from __future__ import annotations

import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_LINK_COLUMN = "E"
_LINK_COLUMN_INDEX = 4
_SCORE_COLUMN_INDEX = 9   # column J (numeric fit score) — sort key
_LAST_COLUMN_INDEX = 10   # columns A:J are written by append_jobs
_TEMPLATE_SPREADSHEET_ID = "1nq5tb-i-zVW7ZBCcT3GLHhX8smXZALLcC_kScNswNAQ"


def _settings():
    from app.config import settings
    return settings


def _get_service():
    s = _settings()
    creds = Credentials.from_service_account_file(s.google_credentials_path, scopes=_SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()


def _ensure_tab_exists(service) -> None:
    s = _settings()
    spreadsheet = service.get(spreadsheetId=s.smart_google_sheet_id).execute()
    existing = {
        sh["properties"]["title"]: sh["properties"]["sheetId"]
        for sh in spreadsheet["sheets"]
    }

    if s.sheet_tab_name in existing:
        return

    template = service.get(spreadsheetId=_TEMPLATE_SPREADSHEET_ID).execute()
    template_sheet_id = template["sheets"][0]["properties"]["sheetId"]

    result = service.sheets().copyTo(
        spreadsheetId=_TEMPLATE_SPREADSHEET_ID,
        sheetId=template_sheet_id,
        body={"destinationSpreadsheetId": s.smart_google_sheet_id},
    ).execute()

    new_sheet_id = result["sheetId"]
    service.batchUpdate(
        spreadsheetId=s.smart_google_sheet_id,
        body={"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": new_sheet_id, "title": s.sheet_tab_name},
            "fields": "title",
        }}]},
    ).execute()

    service.values().clear(
        spreadsheetId=s.smart_google_sheet_id,
        range=f"{s.sheet_tab_name}!A2:Z",
        body={},
    ).execute()


def _get_sheet_id(service) -> int:
    s = _settings()
    spreadsheet = service.get(spreadsheetId=s.smart_google_sheet_id).execute()
    for sh in spreadsheet["sheets"]:
        if sh["properties"]["title"] == s.sheet_tab_name:
            return sh["properties"]["sheetId"]
    raise ValueError(f"Sheet tab {s.sheet_tab_name!r} not found")


def _sort_by_score_desc(service, last_row: int) -> None:
    """Sort data rows (row 2..last_row) by column J (score) descending (Z→A)."""
    if last_row < 2:
        return
    s = _settings()
    sheet_id = _get_sheet_id(service)
    service.batchUpdate(
        spreadsheetId=s.smart_google_sheet_id,
        body={"requests": [{"sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,            # skip header row
                "endRowIndex": last_row,       # exclusive end == 1-based last data row
                "startColumnIndex": 0,
                "endColumnIndex": _LAST_COLUMN_INDEX,
            },
            "sortSpecs": [{
                "dimensionIndex": _SCORE_COLUMN_INDEX,
                "sortOrder": "DESCENDING",
            }],
        }}]},
    ).execute()


def get_existing_links() -> set[str]:
    s = _settings()
    service = _get_service()
    _ensure_tab_exists(service)
    range_ = f"{s.sheet_tab_name}!{_LINK_COLUMN}:{_LINK_COLUMN}"
    result = service.values().get(spreadsheetId=s.smart_google_sheet_id, range=range_).execute()
    rows = result.get("values", [])
    return {row[0] for row in rows[1:] if row and row[0]}


def _get_first_empty_row(service) -> int:
    s = _settings()
    range_ = f"{s.sheet_tab_name}!A:A"
    result = service.values().get(spreadsheetId=s.smart_google_sheet_id, range=range_).execute()
    rows = result.get("values", [])
    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            return i
    return len(rows) + 1


def append_jobs(jobs: list[dict]) -> None:
    """Write newly scraped job dicts into the Google Sheet."""
    if not jobs:
        return

    s = _settings()
    print("[sheets] building service client...")
    service = _get_service()
    print("[sheets] ensuring tab exists...")
    _ensure_tab_exists(service)
    print("[sheets] tab ready, writing rows...")

    start_row = _get_first_empty_row(service)
    end_row = start_row + len(jobs) - 1
    range_ = f"{s.sheet_tab_name}!A{start_row}:J{end_row}"

    def _notes(job: dict) -> str:
        parts = []
        if job.get("score") is not None:
            parts.append(f"Score: {job['score']}/100")
        if job.get("strengths"):
            parts.append("Strengths:\n" + "\n".join(f"• {s}" for s in job["strengths"]))
        if job.get("gaps"):
            parts.append("Gaps:\n" + "\n".join(f"• {g}" for g in job["gaps"]))
        return "\n\n".join(parts)

    rows = [
        [
            job.get("company") or "",
            s.status_on_scrape,
            job.get("title") or "",
            job.get("description") or "",
            job.get("url") or "",
            _notes(job),
            "N/A",
            job.get("salary") or "",
            "",                                          # I: Date Submitted (left blank)
            job["score"] if job.get("score") is not None else "",  # J: numeric score (sort key)
        ]
        for job in jobs
    ]

    service.values().update(
        spreadsheetId=s.smart_google_sheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    print("[sheets] sorting rows by column J (score, Z→A)...")
    _sort_by_score_desc(service, end_row)
    print("[sheets] sort done")
