# Data management

Three workflows under **Data Entry** in the sidebar prepare records and check them **in the browser only**. Nothing is saved, uploaded, or written to the database or the Master workbook. Site checks read the active workbook through the existing read-only `GET /api/dashboard/records/` endpoint. No backend code or API contract changed.

| Route | Sidebar | Prepares | Confirmation message |
|---|---|---|---|
| `/data/add-row` | Add Row | one daily record: outage minutes for one existing site on one date | Record validated locally. Backend integration is not enabled yet. |
| `/data/upload-csv` | Upload CSV | the raw daily CNMC availability file of one circle and date | Validated on the server and saved to PostgreSQL after explicit confirmation (see below). |
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

## Upload CSV: raw daily data to PostgreSQL

Route `/data/upload-csv`. API under `/api/raw-uploads/` (`apps/uptimedb/raw_views.py`); processing in `apps/uptimedb/raw/` (parser, rules, resolvers, service). Every step is enforced on the server; the browser only checks the file type and size before sending.

1. **Details:** project (4G Saturation or LWE), circle, reporting date, the CSV and optional remarks. The uploader is the signed-in account.
2. **Who:** Admin and NOC Lead for every circle; a CI user only for the circles an Admin assigns on Users & Roles (none assigned: no upload, no export). Uploads, previews, reports and commits are visible to the uploader and Admins only.
3. **File:** the daily dump (`nw_aval_btsipid_wise_day…`). The header is found by its column names within the first 10 rows (a title row above it is reported as a preamble); columns are matched by name. The monthly dump (MONTH / YEAR columns) is refused. Binary, empty and over-size files are refused.
4. **File-level checks** (any failure blocks the whole file): one Report Date, equal to the entered date; only the selected circle (the dump writes `OR` for Odisha: mapped to `OD`).
5. **Row checks:** the BTS IP ID must resolve to exactly one approved master site of the selected project and circle (unknown, other-circle, other-project, blank and ambiguous IDs are rejected; master sites are never created); availability (`Nw Avail (4G TCS)`) must be a number 0–100 (blank or invalid is rejected, never read as 0); a site repeated with the same value is skipped, with different values rejected.
6. **Against stored data:** an identical stored value is skipped; a different stored value is never overwritten (rejected as a conflict); a stored day without a value is filled.
7. **Outage minutes** = 1440 × (1 − availability / 100), calculated on the server and stored unrounded.
8. **Preview** shows every row with its master site, availability, outage and reason, and the counts per category; nothing is written to the daily table. **Import** needs an explicit second confirmation; the commit re-reads the stored copy (checksum), repeats the checks in one transaction and refuses if the approved records changed.
9. **Results:** inserted / skipped / rejected counts from the server, a validation report (CSV of every row not imported), and a consolidated export (CSV / Excel) of the stored daily records of approved master sites, limited to the user's circles.
10. **Dashboard:** the import is a committed `DataImportBatch` (kind `raw_daily_csv`), so database-backed pages rebuild from the new rows; the Excel / PostgreSQL source setting is never changed by an upload.

**LWE:** files are validated with the same pipeline, but no LWE row is importable until the authoritative raw-ID mapping (and any 2100 / 700 MHz selection) is configured in `apps/uptimedb/raw/resolvers.py` (`LweResolver`) and the availability column is confirmed in `rules.py`.
