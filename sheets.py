# Standard library
import os

# Third-party
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Local
from config import Config as config
from job_model import ApplicationRow, Job, StatusUpdate

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


# --- Email status tracking ---------------------------------------------------
# The scraper writes a new tab per run (the workflow defaults the tab name to
# the run date), so a reply that lands today can be about a row written weeks
# ago on another tab. These helpers therefore work across every tracking tab in
# the spreadsheet rather than just config.SHEET_TAB_NAME.

_STATUS_COLUMN = "B"
_NOTES_COLUMN = "F"
_REJECTION_COLUMN = "G"

# A tab counts as a tracking tab when its first header cell matches this. Keeps
# dashboards, notes tabs and anything else in the spreadsheet out of the way.
_TRACKING_HEADER = "company name"

# Column positions within the A:J block read back for each tab.
_IDX_COMPANY, _IDX_STATUS, _IDX_ROLE = 0, 1, 2
_IDX_LINK, _IDX_NOTES, _IDX_REJECTION, _IDX_DATE = 4, 5, 6, 8

# Ranges travel in the query string, so a sheet with a year of daily tabs is
# read in batches rather than one enormous request.
_MAX_RANGES_PER_READ = 50


def _cell(row: list[str], index: int) -> str:
    """Value at `index`, tolerating the short rows the API returns for trailing blanks."""
    return row[index].strip() if index < len(row) and row[index] else ""


def _quote_tab(title: str) -> str:
    """Sheet-name syntax for an A1 range; tab names contain spaces ('Sep 22')."""
    return "'" + title.replace("'", "''") + "'"


def get_application_rows(tabs: list[str] | None = None) -> list[ApplicationRow]:
    """Every populated row across the spreadsheet's tracking tabs.

    Pass `tabs` to restrict the scan; the default walks all of them, which is
    what the email checker wants — a reply has no idea which run-date tab its
    job landed on.
    """
    service = _get_service()
    spreadsheet = service.get(spreadsheetId=_SHEET_ID, fields="sheets(properties(title))").execute()
    titles = [s["properties"]["title"] for s in spreadsheet["sheets"]]
    if tabs is not None:
        wanted = set(tabs)
        titles = [t for t in titles if t in wanted]
    if not titles:
        print("[sheets] no tabs to scan")
        return []

    # Batched reads, header row included so non-tracking tabs can be skipped.
    value_ranges: list[dict] = []
    for start in range(0, len(titles), _MAX_RANGES_PER_READ):
        chunk = titles[start:start + _MAX_RANGES_PER_READ]
        result = service.values().batchGet(
            spreadsheetId=_SHEET_ID,
            ranges=[f"{_quote_tab(title)}!A1:J" for title in chunk],
            majorDimension="ROWS",
        ).execute()
        value_ranges.extend(result.get("valueRanges", []))

    rows: list[ApplicationRow] = []
    skipped: list[str] = []
    for title, value_range in zip(titles, value_ranges):
        values = value_range.get("values", [])
        if not values or _cell(values[0], _IDX_COMPANY).lower() != _TRACKING_HEADER:
            skipped.append(title)
            continue
        for offset, raw in enumerate(values[1:], start=2):  # row 1 is the header
            company = _cell(raw, _IDX_COMPANY)
            if not company:
                continue
            rows.append(ApplicationRow(
                row=offset,
                tab=title,
                company=company,
                status=_cell(raw, _IDX_STATUS),
                role=_cell(raw, _IDX_ROLE),
                link=_cell(raw, _IDX_LINK),
                notes=_cell(raw, _IDX_NOTES),
                rejection_reason=_cell(raw, _IDX_REJECTION),
                date_submitted=_cell(raw, _IDX_DATE),
            ))

    print(f"[sheets] read {len(rows)} application(s) from {len(titles) - len(skipped)} tracking tab(s)"
          + (f"; skipped {', '.join(repr(t) for t in skipped)}" if skipped else ""))
    return rows


def apply_status_updates(updates: list[StatusUpdate]) -> int:
    """Write status and note cells back to the sheet. Returns the cells written.

    Values go in as RAW so text lifted from an email subject is stored verbatim
    — USER_ENTERED would turn a subject starting with '=' or '+' into a formula.
    """
    if not updates:
        return 0

    data = []
    for update in updates:
        tab = _quote_tab(update.tab)
        if update.status:
            data.append({"range": f"{tab}!{_STATUS_COLUMN}{update.row}", "values": [[update.status]]})
        if update.note_text:
            column = update.note_column if update.note_column in (_NOTES_COLUMN, _REJECTION_COLUMN) else _NOTES_COLUMN
            data.append({"range": f"{tab}!{column}{update.row}", "values": [[update.note_text]]})

    if not data:
        return 0

    _get_service().values().batchUpdate(
        spreadsheetId=_SHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"[sheets] updated {len(data)} cell(s) across {len(updates)} row(s)")
    return len(data)
