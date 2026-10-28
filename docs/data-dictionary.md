# Data dictionary: Master workbook

Source examined: `4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (Oct'26 reporting month). Two revisions were inspected: 19 Oct and 22 Oct 2026. Their `Up-Time Report` site data is identical; the 22 Oct revision adds rows to `Summ` and `Uptime Bucketization`. The workbook is confidential and git-ignored. This document describes its structure, not its contents.

## Sheets

| Sheet | Size | Role | Used by the app |
|---|---|---|---|
| **Up-Time Report** | 6,728 rows × 141 columns (A:EK) | Site-level source data: one row per site, daily outage minutes | **Yes**, the only sheet read |
| Summ | A3:BY81 | Circle summaries: site counts, monthly and MTD uptime, outage totals, below-60% counts (4G and LWE). Rows 58–81 are a transposed static copy | Reconciliation reference |
| Day wise Trend | B2:CC29 | Daily and weekly uptime per circle (On-Air and O&M Start scopes) | Reconciliation reference |
| Uptime Bucketization | B1:AF191 | Site counts per MTD uptime bucket per circle, plus monthly history | Reconciliation reference |
| One Pager Summary | B2:R28 | Manually maintained per-circle operational figures (HOTO, EB, CCTV, theft, PM) | Not used (manual values, no source columns) |
| Signoff status | C1:AG15 | Quarterly sign-off and raw/commercial uptime (static values) | Not used |
| CI's Performance, IE's Performance | small | Static site counts per CI / IE; their Up-Time columns are empty and counts are stale (e.g. MP 1,454 vs 1,483 sites) | Not used; the dashboard computes CI/IE uptime from `CI Name` / `IE Name` |
| Repeated Sites | A2:F7 | Static counts of "Power Bucket" sites over the last 2–3 months, with no definition in the data | Not used (cannot be derived) |
| All Circle - 98.5, All Circle - Below 60, OD - EB & NEB, Bucketization | small | Derived or manually maintained views | Not used |

Summary sheets are formulas over `Up-Time Report`. Their cached values were used to reconcile the application's calculations (see [business-rules.md](business-rules.md)).

## Up-Time Report

### Layout

- **Excel row 1**: column totals and checks (for example `#DIV/0!` and sums). Not data.
- **Excel row 2**: headers.
- **Excel row 3 onward**: one row per site. Rows 3–4546 are 4G Saturation; rows 4547–6728 are LWE.
- Header labels repeat (`Bucket` many times; every October date twice), so the loader reads columns **by position** rather than by label.

### Row grain and key

- **Grain**: one row per site for the reporting month. Daily values are stored **in columns**, not rows.
- **Business key**: (`Project`, `btsIpId`). In the Oct'26 workbook all 6,726 `btsIpId` values are unique.

### Columns read by the application

| Column | Header | Meaning | Notes |
|---|---|---|---|
| A | `Project` | Report type | `4G Satu.` (4,544 rows) → "4G Saturation"; `LWE` (2,182 rows) |
| B | `Circle` | Circle | 4G uses codes `MP`, `RJ`, `OD`. LWE uses `BH`, `CG`, `JH`, `MH`, `UP`, `AP`, `TL`, `WB`, but spells out **`Madhya Pradesh`** (22) and **`Odisha`** (256). Normalised to `MP`/`OD`, as the workbook's Summ formulas do |
| C | `btsIpId` | Site identifier | e.g. `UVMPBPL00012` (4G), `LWEMH1710` (LWE) |
| D | `Site name` | Site name | |
| E, F | `OA`, `BA` | Operational / business area | Used for search |
| G | `On-Air` | On-Air flag | `Yes` (6,418), blank (295), `0` (13). Only `Yes` counts as On-Air |
| H | `EB` | Power source | `EB` / `N-EB` |
| K | `O&M Start - Oct-26` | O&M started this month | `Yes` (6,280), blank (414), `0` (32). The header includes the month label; the loader derives it from the date block |
| R, T | `IE Name`, `CI Name` | Responsible engineers | Shown in the site detail panel |
| BQ | `Oct-26 Outage Min.` | Month-to-date outage | `=SUM(BT:CX)`. Used only to cross-check the daily block |
| **BT:CX** | `2026-10-01` … `2026-10-31` | **Daily outage minutes** per site | First block of date headers. Blank = not yet reported |

### Columns not read

| Columns | Content | Why not used |
|---|---|---|
| I, J | OD EB working status, Solar logic done date | Not part of current KPIs |
| L:Q | `O&M Start` flags for earlier months | Historical scopes |
| S, U | IE / CI contact numbers | Personal data, not needed |
| V:BO | Monthly outage, uptime, FF count and bucket, Oct-25 to Sep-26 | **`<Mon-YY> Outage Min.` columns are read** for the monthly uptime history (headers use both `Jun-26` and `June-26` spellings); the uptime, FF count and bucket columns are recomputed or not used |
| BR, BS | `Oct-26 UpTime` (`=1-BQ/(1440*14)`), `Bucket` | Recomputed by the app. The `14` is typed by hand and must be edited daily |
| CY:DF | `Wk-1`..`Wk-4` outage sums and uptimes | Recomputed by the app from daily values |
| **DG:EK** | Second block of `2026-10-01` … `2026-10-31` headers | **Derived daily uptime** `=1-BT/(1440*1)`. Shows **100% for unreported days**, so it must not be used as data |

### Date representation

- Reporting dates are **column headers** (Excel dates) in BT:CX, one per calendar day of the month.
- A date counts as **reported** when at least one site has a value in its column. Oct'26: 1–14 October reported for every site; 15–31 October blank.
- The reporting month is taken from the date block (`Oct-26`). The block must be consecutive days within one month, or the workbook is rejected.

### Values

- Daily outage minutes are floats in 0–1440 with two exceptions: `LWEMH1710` on 9 Oct (1,454.5) and `LWEMH1685` on 12 Oct (2,367.1). These are reported as data-quality warnings.
- Outage values are numeric (no text) in the Oct'26 file. Text such as `NA` or `-` would be flagged as non-numeric rather than silently treated as blank.

## Validation performed on every load

| Check | Result if it fails |
|---|---|
| Sheet `Up-Time Report` exists | Error (503): dashboard shows "Reporting data is unavailable" |
| Required columns `Project`, `Circle`, `btsIpId`, `Site name`, `On-Air` | Error |
| Consecutive daily date block within one month | Error |
| `O&M Start - <month>` column present | Warning; O&M Start scope disabled |
| Blank `btsIpId`, unknown `Project` values | Rows excluded, warning |
| Duplicate (`Project`, `btsIpId`) | First row kept, warning |
| Non-numeric outage values | Treated as not reported, warning |
| Outage < 0 or > 1440 minutes | Included as in the workbook, warning |
| Gaps before the latest reported date; partially reported dates | Warning |
| `<month> Outage Min.` ≠ sum of daily values | Warning |
| On-Air values other than `Yes`/blank; circle aliases | Informational note |

Results are shown on the **Data source & quality** page and returned by `GET /api/dashboard/source/`.

## Other data files (not used by the dashboard)

- `Data/raw/nw_aval_btsipid_wise_*.csv`: CNMC exports, the input for the planned ingestion pipeline. Columns used by `match_master.py`: `BTS IP ID`, `Nw Avail (4G TCS)`, `Report Date` (`dd-mm-yyyy`).
- `Data/reference/` held the workbook for inspection only. The application does not read it; the dashboard uses the uploaded copy in `Data/processed/workbooks/`.
- **No LWE ID-mapping reference file exists in the repository.** It is required before raw LWE files can be processed.

## Consolidated Escalation Matrix (stored in PostgreSQL)

Source: `Data/reference/Consolidated Escalation Matrix _<month>.xlsx`, sheet **Raw Data** (header on row 3, one row per site).
Import with `python manage.py import_escalation` (preview of the latest matrix) and then `--commit <id>`.

| Table / view | Grain | Contents |
|---|---|---|
| `uptimedb_escalationsite` | One row per (project, BSNL Site ID) | Site type, district, commissioning / On-Air / O&M Start dates, EB / DG status, case type, the escalation chain (IE, CI, IL, O&M Manager, CBH, CT, rigger, with contacts), address, coordinates, BTS IDs. Unnamed columns go to `extra` (e.g. "Column AZ", the LWE connection status). |
| `uptimedb_escalationimportbatch` | One row per import | File, checksum, status, counts and the cross-check report. |
| `site_overview` (view) | One row per Up-Time Report site | The Up-Time site joined with its escalation details and its number of RCA records. |

**Links.** `uptimedb_escalationsite.uptime_site_id` points to `uptimedb_uptimesite.id` (same project, circle and normalised site ID), and through it to `uptimedb_sitemonthlyperformance` / `uptimedb_sitedailyperformance` (`site_id`). RCA records join on `(project, site_key)`. Links are refreshed after every Up-Time or escalation import. `match_status` is `matched`, `not_in_uptime`, or `other_entity` (VI-HPSC and Sterlite rows, which are not dashboard projects).

**Normalisation.** Entities "4G Saturation" / "LWE" become the dashboard projects; circle names become codes, including the matrix's spellings Chattishgarh, Maharastra, Telangna and West Bangal. Dates written as text ("NO", "-") are NULL, with the text in `*_raw`; coordinates of 0 are NULL. The serial number and the "@" / "Combo" helper columns are not stored.

**Cross-check (reported, never applied).** Sites in only one source; CI / IE names that differ (ignoring case and spacing); On-Air status vs the Up-Time Report; O&M Status vs the latest month's O&M Start flag.

## RCA uploads and reporting periods (stored in PostgreSQL)

The NOC Lead (role **NOC Lead**, or an Admin) uploads the completed RCA workbook on **Upload RCA Data** with a report name, a reporting date or period, a project scope (4G Saturation, LWE or both) and optional remarks. The data sheet is found by its header within the first 10 rows (e.g. "RCA Backup" of the Daily RCA Compilation, header on row 2; "Sheet1" of a plain RCA file); pivot and summary sheets are ignored. Admins monitor every upload and every period on **RCA Submissions**.

| Table | Grain | Contents |
|---|---|---|
| `rca_rcaimportbatch` | One row per uploaded workbook | Report name, period (`period_start`, `period_end`), project scope, remarks, uploader, timestamps, status (previewed, committed, rejected = no valid row, failed = unreadable, discarded), counts (total, valid, rejected, inserted, updated, skipped, withdrawn, correction), the validation report, the projects / circles in the valid rows (`units`) and a copy of the file (`Data/processed/rca_uploads/<start>_<end>/`). |
| `rca_rcarecord` | One row per incident: (reporting date, project, site, occurrence) | The accepted records, with the source columns as written and the upload they came from (`batch_id`). `occurrence` ranks a site's rows of one date by cause and outage (1 for a single row), so several outages of a site on one date are separate records. `withdrawn_at` marks a record a corrected workbook no longer listed and the uploader withdrew; it stays for the audit trail and is left out of the register, summary, reports and `site_overview`. |
| `rca_rcareportingcycle` | One row per reporting period | First day (`reporting_date`), last day (`period_end`, blank for one date), name. Periods never overlap. Created by the first accepted upload for the period, or by an Admin in advance. |
| `rca_rcarequiredsubmission` | One row per (period, project, circle) | The expected scope, configured by an Admin; a new period starts with the previous period's scope (none before the first). Fixed once a final report exists. |
| `rca_rcareport` | One row per final report version | File (`Data/processed/rca_reports/<period>/RCA_Master_<period>_FINAL_v<n>.xlsx`), checksum, fingerprint of the records it was built from, the RCA Summary snapshot and the coverage at generation. A superseded version keeps its file. |

**Daily uploads.** The NOC Lead uploads the Daily RCA Compilation once a day with that day's reporting date. The workbook is cumulative (on 26 Oct it held 21–26 Oct), so rows are classified by their own date: rows of the reporting date are the day's data; rows of earlier dates are history (identical rows skipped, rows not yet stored added under their own date and period, differing rows shown as corrections needing an explicit choice, nothing withdrawn); rows dated after the reporting date are rejected. The preview lists each date as new, repeated or corrected, and checks the reporting date's rows against the expected projects / circles (the period's, or the latest earlier period's).

**Validation.** Required columns; no date after the reporting date; project within the scope; known circle; Site ID in the Up-Time Report; numeric, non-negative outage minutes. Rows identical in every column to an earlier row are rejected as duplicates. Rows with errors are rejected; the valid rows are imported only after the uploader confirms importing without them. Final Bucket labels found in no stored record are listed in the preview and kept as written.

**Duplicates and corrections.** A repeat upload adds nothing (identical records are counted as skipped). Rows that differ from a stored record with the same identity are kept as stored unless the uploader chooses to update them; stored records of the period and scope that the workbook no longer lists are kept or withdrawn by explicit choice. Every update or withdrawal is recorded in `rca_rcaevent`; earlier uploads stay in the history. Outage minutes come from the RCA workbook; the Up-Time Report tables are never changed by an RCA upload.

**Received and pending.** For a period with an expected scope, a project / circle is *received* when accepted records of that project and circle exist in the period, and *pending* otherwise; data outside the scope is shown but never counted. Without a configured scope the period reports "Expected scope not configured". Upload status (imported, imported with rejected rows, failed...) is separate from period completeness. The consolidated workbook is labelled partial until every expected project / circle has data; the final report is then generated automatically; if records change afterwards the period is *revised* until an Admin generates the next version.
