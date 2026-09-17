# Standard library
import os

# Third-party
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Local
from config import Config as config
from job_model import Job

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
_CREDENTIALS_PATH = os.environ["GOOGLE_CREDENTIALS_PATH"]

# Column E (index 4) — "Link to Job Req"
_LINK_COLUMN = "E"
_LINK_COLUMN_INDEX = 4

# Column J (index 9) — "Score"
_SCORE_COLUMN_INDEX = 9

# Conditional formatting: highlight rows with Score >= threshold in
# Google Sheets' "light green 1" swatch (#b7e1cd).
_SCORE_HIGHLIGHT_THRESHOLD = 95
_LIGHT_GREEN_1 = {"red": 0.717647, "green": 0.882353, "blue": 0.803922}
_SCORE_HIGHLIGHT_FORMULA = f"=$J2>={_SCORE_HIGHLIGHT_THRESHOLD}"


def _get_service():
    creds = Credentials.from_service_account_file(_CREDENTIALS_PATH, scopes=_SCOPES)
    return build("sheets", "v4", credentials=creds).spreadsheets()


_TEMPLATE_SPREADSHEET_ID = "1nq5tb-i-zVW7ZBCcT3GLHhX8smXZALLcC_kScNswNAQ"


def _ensure_tab_exists(service) -> None:
    """Copy the first sheet from the template spreadsheet if SHEET_TAB_NAME doesn't exist."""
    spreadsheet = service.get(spreadsheetId=_SHEET_ID).execute()
    sheets = spreadsheet["sheets"]
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in sheets}

    print(f"[sheets] target tab: '{config.SHEET_TAB_NAME}'")
    print(f"[sheets] existing tabs: {list(existing.keys())}")

    if config.SHEET_TAB_NAME in existing:
        print(f"[sheets] tab already exists, skipping creation")
        return

    print(f"[sheets] fetching template from external spreadsheet")
    template = service.get(spreadsheetId=_TEMPLATE_SPREADSHEET_ID).execute()
    template_sheet_id = template["sheets"][0]["properties"]["sheetId"]

    # Copy the template sheet into the user's spreadsheet
    result = service.sheets().copyTo(
        spreadsheetId=_TEMPLATE_SPREADSHEET_ID,
        sheetId=template_sheet_id,
        body={"destinationSpreadsheetId": _SHEET_ID},
    ).execute()

    new_sheet_id = result["sheetId"]

    # Rename from "Copy of ..." to the desired tab name
    service.batchUpdate(
        spreadsheetId=_SHEET_ID,
        body={"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": new_sheet_id, "title": config.SHEET_TAB_NAME},
            "fields": "title",
        }}]},
    ).execute()

    # Clear any data rows so only the header remains
    service.values().clear(
        spreadsheetId=_SHEET_ID,
        range=f"{config.SHEET_TAB_NAME}!A2:Z",
        body={},
    ).execute()
    print(f"[sheets] tab created from external template successfully")


def get_existing_links() -> set[str]:
    """
    Read all values in the 'Link to Job Req' column and return them as a set.
    Used for deduplication before appending new jobs.
    """
    service = _get_service()
    _ensure_tab_exists(service)
    range_ = f"{config.SHEET_TAB_NAME}!{_LINK_COLUMN}:{_LINK_COLUMN}"
    result = service.values().get(spreadsheetId=_SHEET_ID, range=range_).execute()
    rows = result.get("values", [])
    # Each row is a list with one element; skip header row
    return {row[0] for row in rows[1:] if row and row[0]}


def _get_sheet_id(service) -> int:
    """Return the numeric sheetId for config.SHEET_TAB_NAME."""
    spreadsheet = service.get(spreadsheetId=_SHEET_ID).execute()
    for s in spreadsheet["sheets"]:
        if s["properties"]["title"] == config.SHEET_TAB_NAME:
            return s["properties"]["sheetId"]
    raise RuntimeError(f"Sheet tab {config.SHEET_TAB_NAME!r} not found")


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
    E: Link to Job Req | F: Notes | G: Rejection Reason | H: Salary | I: Date Submitted
    J: Score
    """
    if not jobs:
        return

    service = _get_service()
    start_row = _get_first_empty_row(service)
    end_row = start_row + len(jobs) - 1
    range_ = f"{config.SHEET_TAB_NAME}!A{start_row}:J{end_row}"

    rows = [
        [
            job.company or "",           # A: Company Name
            config.STATUS_ON_SCRAPE,     # B: Application Status
            job.role or "",              # C: Title
            job.description or "",       # D: Description
            job.link or "",              # E: Link to Job Req
            job.notes or "",             # F: Notes
            "N/A",                       # G: Rejection Reason
            job.salary or "",            # H: Salary
            "",                          # I: Date Submitted
            job.score if job.score is not None else "",  # J: Score
        ]
        for job in jobs
    ]

    service.values().update(
        spreadsheetId=_SHEET_ID,
        range=range_,
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def ensure_score_highlight_rule() -> None:
    """Ensure a conditional formatting rule exists that colors entire data
    rows light green 1 when Score (column J) >= 95.

    Idempotent — checks for an existing matching rule before adding one, so
    it's safe to call on every run. The rule uses an open-ended row range,
    so it keeps applying to new rows added in future runs without needing
    to be re-created.
    """
    service = _get_service()
    sheet_id = _get_sheet_id(service)

    spreadsheet = service.get(
        spreadsheetId=_SHEET_ID,
        fields="sheets(properties(sheetId),conditionalFormats)",
    ).execute()

    for sheet in spreadsheet["sheets"]:
        if sheet["properties"]["sheetId"] != sheet_id:
            continue
        for rule in sheet.get("conditionalFormats", []):
            condition = rule.get("booleanRule", {}).get("condition", {})
            values = condition.get("values", [])
            if (
                condition.get("type") == "CUSTOM_FORMULA"
                and values
                and values[0].get("userEnteredValue") == _SCORE_HIGHLIGHT_FORMULA
            ):
                print("[sheets] score highlight rule already exists, skipping")
                return

    service.batchUpdate(
        spreadsheetId=_SHEET_ID,
        body={"requests": [{
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1,   # skip header
                        "startColumnIndex": 0,
                        "endColumnIndex": 10,  # through column J
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": _SCORE_HIGHLIGHT_FORMULA}],
                        },
                        "format": {"backgroundColor": _LIGHT_GREEN_1},
                    },
                },
                "index": 0,
            },
        }]},
    ).execute()
    print("[sheets] added score highlight conditional formatting rule")


def sort_by_score() -> None:
    """Sort the data rows by Score (column J) descending — Z-to-A, highest first.

    Leaves the header row and any trailing pre-formatted empty rows untouched.
    Safe to call even when no new rows were added this run (it no-ops on an
    empty sheet).
    """
    service = _get_service()
    first_empty_row = _get_first_empty_row(service)
    # Data occupies 1-based rows 2..first_empty_row-1. Nothing to sort if empty.
    if first_empty_row <= 2:
        return

    sheet_id = _get_sheet_id(service)
    service.batchUpdate(
        spreadsheetId=_SHEET_ID,
        body={"requests": [{"sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,                  # skip header (row 1)
                "endRowIndex": first_empty_row - 1,  # exclusive, last filled row
                "startColumnIndex": 0,               # column A
                "endColumnIndex": 10,                # through column J
            },
            "sortSpecs": [{
                "dimensionIndex": _SCORE_COLUMN_INDEX,
                "sortOrder": "DESCENDING",
            }],
        }}]},
    ).execute()
