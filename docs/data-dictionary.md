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
