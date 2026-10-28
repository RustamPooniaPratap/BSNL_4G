# Data management (frontend only)

Three workflows under **Data Entry** in the sidebar prepare records and check them **in the browser only**. Nothing is saved, uploaded, or written to the database or the Master workbook. Site checks read the active workbook through the existing read-only `GET /api/dashboard/records/` endpoint. No backend code or API contract changed.

| Route | Sidebar | Prepares | Confirmation message |
|---|---|---|---|
| `/data/add-row` | Add Row | one daily record: outage minutes for one existing site on one date | Record validated locally. Backend integration is not enabled yet. |
| `/data/upload-csv` | Upload CSV | many daily records for one report type, circle and date | CSV validated locally. Backend ingestion is not enabled yet. |
| `/data/new-site` | Add Site | one master site record | Site details validated locally. Master DB integration is not enabled yet. |

Each workflow goes **Details → Review → Validated**, and you can go back to edit at every step. Drafts live in page state only; nothing is kept in browser storage.

## Schema used (from the workbook's `Up-Time Report`)

- **Daily record:** Project, Circle, btsIpId, reporting date and outage minutes. In the workbook a daily value is an outage-minutes cell in a site's row.
- **Master site:** Project, Circle, btsIpId, Site name, OA, BA, On-Air, EB/N-EB, `O&M Start - <month>`, IE Name, CI Name. The workbook requires `Project, Circle, btsIpId, Site name, On-Air`, so only those are mandatory on the form.
- **Site ID formats:**
  - 4G: `UV` + 5 letters + 5 digits (`UVMPBPL00012`, 4,544 sites).
  - LWE: `LWE` + 2–3 letters + 4 digits (`LWEBH0303`, `LWEUPE2212`, 2,182 sites).
  - IDs are unique across both report types. The circle letters inside an ID do not reliably match the Circle column (65% for 4G), so only the format is checked.

## Rules

**Add Row**
- All five fields are required.
- The date must be valid and not in the future. There is a warning if it falls outside the workbook month.
- Outage must be a number of 0 or more. Over 1,440 minutes gives a warning, matching the workbook's open rule.
- The Site ID must have the right format and exist in the chosen report type and circle. If it exists in another circle, the form says so and offers that circle.
- There is a warning if the workbook already has a value for that site and date (read from the site detail endpoint).
- Unknown sites block the review and offer **Add new site** (pre-filled); they are never created automatically.

**Upload CSV**
- **Required upload details:** report type, circle and reporting date. The file picker stays locked until all three are chosen.
- **File:** `.csv` only, up to 10 MB, read with `File.text()`. It can be removed or replaced.
- **Parsing:** RFC 4180 (quotes, escaped quotes, CRLF, BOM).
- **Columns:** header names are matched case-insensitively.
  - **Required:** Site ID (`btsIpId` / `BTS IP ID` / `Site ID`).
  - **Required, exactly one:** outage minutes (`Outage Minutes` / `Outage Min.` / `Outage`) or availability % (`Nw Avail (4G TCS)` / `Nw Avail` / `Availability` / `Uptime %`).
  - **Required:** the reporting date (`Report Date` / `Reporting Date` / `Date`), as in the sample file `Data/raw/test_sample_upload.csv` (DD-MM-YYYY).
  - **Optional:** Circle, Site name, Project / Report type.
- **Errors (block confirmation):**
  - empty file or no data rows;
  - missing or repeated columns;
  - rows with the wrong number of values;
  - empty values or values that aren't numbers;
  - negative minutes, or availability outside 0–100;
  - wrong Site ID format;
  - a Site ID that appears twice (one file covers one date);
  - a Site ID not in the chosen circle's master data;
  - a row date, circle or report type that differs from the upload details (flagged, never overwritten).
- **Warnings:**
  - availability values, because their conversion to outage minutes is not confirmed;
  - outage over 1,440 minutes;
  - rows that are exact copies of another row;
  - columns that aren't used.
- **Reporting date check** (its own panel):
  - Dates are normalised to YYYY-MM-DD before comparing (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY and DD.MM.YYYY are read; day comes first).
  - **Passes** only when every row has the selected date.
  - **Fails** and blocks confirmation when the column is missing, a date is empty or unreadable, a row has another date, or the file mixes dates.
  - Shows the expected date, each date found with its row count, and the line numbers of every mismatch.
- **Repeated column headers** (same name ignoring case and spaces, or two names meaning the same field) are errors.
- **Shown on the page:** the preview (first 10 rows, with each column's detected meaning), the row count, every finding with its line number, and links to Add New Site for unknown IDs.

**Add New Site**
- Required fields: report type, circle (existing circles only), Site ID (format), site name and On-Air.
- A Site ID that already exists anywhere is refused, and the form shows the existing site with a link to review its circle.
- The form can be pre-filled from an unknown ID (`?site_id=&report_type=&circle=`).
- Suggested OA, BA, IE and CI names come from the chosen circle.

## Assumptions to confirm

1. **CSV layout:** the cleaned CSV is one file per report type, circle and date, with one row per site. The only sample (`Data/raw/test_sample_upload.csv`) is a raw availability file, so both value kinds are accepted.
2. **Availability conversion:** converting availability % to outage minutes is not defined (open question 7 in business-rules.md).
3. **Fields not in the workbook:** District, Block, GP code, site status (Active/Inactive), On-Air date and O&M Start date aren't columns in the workbook, so the form doesn't ask for them.
4. **Unknown Site IDs** block confirmation in both Add Row and Upload CSV.
5. **Existing values:** a daily record for a site and date that already has a value only gets a warning; whether it should replace the value is a decision for the backend phase.
