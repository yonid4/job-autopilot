from __future__ import annotations

import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_LINK_COLUMN = "E"
_LINK_COLUMN_INDEX = 4
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
    service = _get_service()
    _ensure_tab_exists(service)

    start_row = _get_first_empty_row(service)
    end_row = start_row + len(jobs) - 1
    range_ = f"{s.sheet_tab_name}!A{start_row}:I{end_row}"

    rows = [
        [
            job.get("company") or "",
            s.status_on_scrape,
            job.get("title") or "",
            job.get("description") or "",
            job.get("url") or "",
            "",
            "N/A",
            job.get("salary") or "",
            "",
        ]
        for job in jobs
    ]

    service.values().update(
        spreadsheetId=s.smart_google_sheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
