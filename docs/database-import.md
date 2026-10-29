# PostgreSQL import and the dashboard data source

Admin page: **Data → Data source** (`/workbook`; `/data/database` redirects there). Backend app: `backend/apps/uptimedb/`.

The page shows two tiles. **Excel workbook** shows the Master workbook upload. **PostgreSQL database** shows the import tools and the database contents. Picking the tile that is not in use offers to switch the dashboard to it, with a confirmation. While the database is empty it can be filled, but not yet used.

There are two separate actions:
- **Dashboard data source:** which source every page reads, the Excel workbook or PostgreSQL. It never imports anything.
- **Import:** copies an Up-Time Report workbook into PostgreSQL. It never changes the dashboard source.

## Tables (migration `uptimedb.0001_initial`, additive only)

| Table | One row per | Key fields |
|---|---|---|
| `uptimedb_uptimesite` | site | **unique (project, circle, site_key)**. Also stores: `site_id` (as read), `site_key` (trimmed, upper case), project and circle (normalised and raw), name, OA, BA, On-Air (raw and flag), EB, OD EB working status, Solar Logic Done Date, IE/CI names and contacts. `extra` keeps unused source columns (weekly uptime, Correction Plan). Lineage: `batch`, `source_file`, `source_row` |
| `uptimedb_sitemonthlyperformance` | site × month | **unique (site, month)**. FF count, outage minutes, uptime %, bucket (as written), O&M Start (raw and flag; NULL when the file has no column for that month) |
| `uptimedb_sitedailyperformance` | site × reporting date | **unique (site, date)**. Daily outage minutes (first date run, e.g. BT:CX) and daily uptime % (second run with the same dates, e.g. DG:EK) |
| `uptimedb_dataimportbatch` | import | File name, SHA-256, sheet, staged copy, optional second file, status, user, timestamps, the conflict choice. It also keeps the preview report, the inserted / updated / unchanged counts, and the rejected and skipped counts |
| `uptimedb_appsetting` | setting | `dashboard_data_source` = `excel` (default) or `database` |

**Rules:**
- Blanks and placeholders ("-", "NA") are stored as NULL, never 0.
- Only actual reporting dates are stored: a date counts when any site has a value on it.

## Import steps

1. **Preview.** Upload the Master workbook, and optionally a second report to compare.
   - The files are staged in `Data/processed/imports/` (git-ignored); the originals are never modified.
   - Columns are matched by header text, never by position.
   - The report lists: file, sheet, rows, sites, distinct IDs, counts per project, circle and month, daily coverage and missing values. Rejected rows (no ID, unknown project, duplicate key) and flagged rows are listed, with a CSV error report.
   - Blank rows and total/subtotal rows are skipped.
2. **Compare** (when a second file is given): every difference on the overlapping sites is shown. Nothing is merged; the commit requires a choice of which file's values to apply.
3. **Commit:**
   - The staged file is re-read and its checksum checked.
   - New records are inserted and changed ones updated, in one transaction, so a failure leaves no partial data.
   - Unchanged records are not written, so re-importing the same file changes nothing.
   - Nothing is ever deleted.

**Command line (same code):**
```
manage.py import_uptime <workbook.xlsx> [--reconciliation <report.xlsx>]
manage.py import_uptime --commit <batch> [--conflicts primary|reconciliation]
```

## Database mode

`datasource.database_dataset()` rebuilds the same `Dataset` structure the Excel loader produces, so every KPI, chart, threshold and team calculation runs unchanged. Tests check that each calculation gives identical results from both sources.

**Switching:**
- Admin only, with an explicit confirmation.
- Refused while the database is empty.
- Incomplete data (for example, no September daily history) must be acknowledged.
- The top bar shows the active source on every page.

## Import of 24 Oct 2026

| | |
|---|---|
| Primary file | `4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (the workbook the dashboard uses, uploaded 23 Oct; SHA-256 `b135a35c…`). No file named `…Last_Changes(2).xlsx` exists on this computer |
| Compared with | `RJ, MP & OD - Uptime Report- Oct-26.xlsx` (`Data/raw`, 24 Oct). Values applied: **primary** (consolidated) |
| Imported | 6,726 sites (4G 4,544, LWE 2,182) · 87,438 monthly records (Oct-25 to Oct-26) · 134,520 daily records (1–20 Oct) |
| Rejected / duplicate / flagged | 0 / 0 / 0 |
| Re-import of the same file | 0 inserted, 0 updated |
| Reconciliation | Identical results to the Excel source on 42 calculation checks. 66 of 66 sampled cells match. KPIs: 6,726 sites, On-Air 6,418, O&M Start 6,280, MTD 93.30% |
| Differences, second file | All 4,544 overlapping 4G sites differ somewhere. That file has 21 Oct, so its October totals, buckets and FF counts differ. It also differs in IE/CI names and contacts, EB values, May-26 FF counts (1,941 sites) and 4 daily values |
| Missing | September daily history (added later: 4G on 26 Oct, LWE on 29 Oct, below) |

## Import of 26 Oct 2026: September daily values (4G)

| | |
|---|---|
| File | `Data/raw/RJ, MP & OD - Uptime Report- Sep-26.xlsx` (identical copy in `Data/reference`) |
| How | **Daily values only** (`--daily-only`), project **4G Saturation** (`--project`, since the sheet has no Project column). Only daily records were written; site details and monthly figures were not changed |
| Checked first | 4,543 sites, all already in the database. For every site, the 1–30 Sep daily outage adds up exactly to both the file's and the database's Sep-26 monthly total |
| Imported | 136,290 daily records (4,543 sites × 30 days), batch #3. 0 rejected |
| Database now | 270,810 daily records: Sep 1–30 (4G) and Oct 1–20 (4G and LWE) |
| Still missing | September daily values for LWE (0 of 2,182 sites) and for one RJ 4G site that is not in the September file. Same-days comparisons for those sites stay unavailable |

**Command line:**
```
manage.py import_uptime "<file>.xlsx" --project "4G Saturation" --daily-only
manage.py import_uptime --commit <batch>
```
The import page offers the same two options.

## Import of 29 Oct 2026: September daily values (LWE)

| | |
|---|---|
| Before | September daily data existed for **4G only**: batch #3, 136,290 records, all 4,543 sites in the 4G September file, identical to that file on every site/day. **LWE had none** (0 of 2,182 sites); only its September monthly totals were stored. The dashboard therefore showed no same-days September comparison for any LWE circle. Nothing in the code limits comparisons to 4G: `datasource._build()` loads every earlier month's daily rows into `daily_history`, for every project |
| File | `Data/reference/LWE Uptime Report day wise - Sept'26.xlsx`, sheet **Day Wise Outage** (header on row 2): one row per site. **Site ID as per Nirikshan** is the master's LWE ID (e.g. `LWEBH0303`); **Circle** is the state name. 1–30 Sep outage minutes, then the same dates again as the uptime fraction |
| How | `manage.py import_daywise` (`apps/uptimedb/daywise.py`), daily values only. The Master-workbook parser reads only the Up-Time Report layout, and the raw CSV upload takes one date per file, so neither could read this sheet |
| Matching | ID within the LWE master, and the row's circle must be that site's circle. State names are mapped with the existing aliases (`apps.dashboard.activity.CIRCLES`). No site is created; sites and monthly figures are not changed |
| Checked first (read only) | 2,182 rows, all matched, 0 rejected. 65,460 site/days, 0 blank, 0 invalid, 0 already stored, 0 conflicts. The uptime run agrees with `1 − outage/1440` on every value. Every site's 30-day sum equals both the file's own Sept total and the stored Sep-26 monthly total (12,272,922.47 minutes overall). 1 value over 1,440 minutes (LWEMH1696, 26 Sep: 1,471.1), stored as in the source and flagged, as for the workbook import |
| Imported | **65,460** daily records (2,182 sites × 30 days), batch #16, in one transaction. Re-running the same file: 0 inserted, 65,460 identical skipped |
| Database now | 345,008 daily records. Sep 1–30 for all 4G (4,543) and LWE (2,182) sites. Sites (6,726) and monthly records (87,438) unchanged. Source setting unchanged (PostgreSQL) |
| Dashboard effect | October figures unchanged for every circle. LWE same-days September comparisons now exist for all 10 circles. LWE September from daily values: 86.902% (On-Air), equal to the monthly total. Per circle, the database reproduces the workbook's Circle Wise Summary "Sept'26 MTD" exactly over **all sites**. With the dashboard's default On-Air scope, CG, MP, MH and WB differ by excluding their non-On-Air sites |
| Still missing | One RJ 4G site has no September daily values (it is not in the 4G September file) |

**Command line** (the path is always explicit; nothing reads the file at runtime, and a staged copy is kept with the batch):
```
manage.py import_daywise "<file>.xlsx" --project LWE            # read-only reconciliation
manage.py import_daywise "<file>.xlsx" --project LWE --commit   # write; refuses rejected rows unless --allow-rejected
```
Stored values that differ from the file are never changed; they are listed as conflicts. Rows that cannot be matched are never written.
