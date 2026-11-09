# sitedata: new site master and performance data layer (Phase 1)

Status: **in development and tested; not connected to any page, and its migration is not applied to the live
database.** The dashboard still runs on `apps.uptimedb`. Cutover, backup and reset happen only after explicit
approval (see `docs/phase1-database-audit.md`).

## Business rules (`rules.py`, confirmed 4 Nov 2026)

`rules.py` is the only place these rules are defined. Every importer, the monthly calculation and the dataset builder
use it.

- **Availability** (4G and LWE alike):
  - Taken from `Nw Avail (4G TCS)`, read as a percentage (98.50 = 98.50%), valid 0–100.
  - A blank is not reported: no record, never 0.
  - Outage = 1440 × (1 − availability / 100).
- **Outage** (Uptime Master): valid 0–1,440 minutes. Anything else is rejected with its original value, never capped
  or corrected.
- **O&M Start:**
  - Comes only from the Consolidation Matrix O&M Start Date.
  - A site is O&M Start in a month when the date is on or before the month's last day; its O&M days start on the later
    of the 1st and the date.
  - A missing or unreadable date means not O&M Start, and the site is flagged for review (`Site.om_start_date_issue`).
  - Uptime Master O&M flags are never used, only compared and reported.
- **Unmatched sites:** a site that isn't in the matrix stays unmatched. No site is ever created, and nothing of it
  reaches the dashboard.
- **Ambiguous identifiers:**
  - An identifier the matrix gives to more than one site is assigned to none of them; any earlier assignment is
    removed.
  - It is recorded as an active `IdentifierConflict` and can never be matched by the mapping or a raw CSV.
  - There is no first match and no fuzzy matching. The other records continue to import.
- **Source precedence** (`daily.SOURCE_RANK`), the same whatever the upload order:

  | Rank | Source |
  |---|---|
  | 3 | Authorized correction |
  | 2 | Uptime Master |
  | 1 | Raw CNMC CSV (4G or LWE) |

  - A raw CSV value is accepted where no value exists.
  - An identical value is a duplicate.
  - A different value from an equal or lower source is a conflict: the stored value is kept and the proposed value
    logged.
  - A different value from a higher source supersedes the stored value; the replaced value, its upload and file stay in
    the append-only log.
  - Corrections go through `daily.correct()`, which requires an Admin and a reason, and are never overridden.
- **Identifier cells** (`identifiers.split_ids`):
  - Split on `;;`, trimmed, with empty tokens and placeholders (`-`, `NA`, …) dropped and distinct IDs kept.
  - A token with any other separator is invalid and is never split or chosen.

## Tables

| Model | Purpose | Key rule |
|---|---|---|
| `UploadBatch` | Upload history of every file kind (Uptime Master, Consolidation Matrix, LWE Band ID mapping, 4G / LWE raw CSV, authorized correction) | Uploader, file, checksum, staged copy, circle, date, technology, counts received / accepted / rejected / duplicate / unmatched / conflict, validation and processing status, report with the exception summary and the exception report path |
| `Site` | One record per BSNL Site ID | `site_key` unique; matrix attributes are authoritative; `reporting_scope` is dashboard or outside scope (Sterlite, VI-HPSC: excluded from every KPI); a site missing from a newer matrix is flagged, never deleted; `om_start_date_issue` flags a missing or unreadable O&M Start Date |
| `SiteIdentifier` | Every identifier of a site (BSNL Site ID, BTS IP ID, 2100 / 700 MHz IDs, Master BTS ID) | Unique per kind; never moved to another site silently |
| `IdentifierConflict` | Identifiers the matrix gives to several sites | Never assigned or matched while active; lists every claiming site |
| `DailySitePerformance` | **The only daily table**, 4G and LWE | Unique (site, report_date, technology); 0–100% and 0–1,440 min checks; upload and source row of the value; no record = not reported (never 0) |
| `DailyPerformanceEvent` | Append-only log of conflicting values and authorized corrections | Cannot be updated or deleted |
| `MonthlySitePerformance` | Monthly result per site, month and category: `daily_derived` (all reported days) and `om_start` (reported days from the O&M effective date) | Outage-weighted over reported days; `effective_from`; revisions kept; one current record; finalized months need a forced recalculation |

## Importers (preview, then commit)

How a file goes through an importer:
- **Preview:** stages a copy of the file and analyses it. It stores the report and writes the **exception report**: a
  CSV of every rejected, unmatched, not-reported or review record, with source file, row, site ID, circle, date,
  identifier, original value, reason code, severity and message. The CSV goes to `SITEDATA_EXCEPTION_DIR` (default
  `<DATA_DIR>/processed/sitedata/exceptions`).
- **Commit:** re-reads the staged copy (checksum verified) and repeats the analysis. It refuses if anything changed
  since the preview, then writes in one transaction.

| Module | File | Writes |
|---|---|---|
| `matrix.py` | Consolidation (Escalation) Matrix, "Raw Data" sheet | `Site`, matrix identifiers, `IdentifierConflict` |
| `bandmap.py` | LWE Band ID mapping (Circle, BTS IP ID, BTS Site ID (2100), BTS Site ID (700), btsIpId -Master ID) | LWE identifiers |
| `uptime_master.py` | Uptime Master in either format: "Up-Time Report" sheet (with or without a Project column; without one, the project is stated at upload) or "Day Wise Outage" sheet (LWE day-wise; project stated at upload) | Daily values of the months in scope (`SITEDATA_MASTER_DAILY_MONTHS`, default Sep and Oct 2026) and the Uptime-only columns; never matrix attributes and never O&M flags. Counts are site-days |
| `rawcsv.py` | CNMC daily dump, per technology, circle and date | Daily values |

LWE raw rows:
- Every 2100 / 700 token must match its mapping column, and every resolved token must name the same Master ID. One band
  token is enough.
- A BTS IP ID that appears nowhere in the mapping is not mandatory and is ignored (counted). One that names another site
  is a conflict.
- Rows that conflict, are ambiguous, or have no identifier are rejected. Rows none of whose identifiers is known are
  unmatched.
- Several rows of one site make one record. If their values differ, all of those rows are rejected.

Other modules:
- `calculations.py`: monthly results from daily records (both categories).
- `dataset.py`: the dashboard `Dataset` built from these tables, with O&M Start from the matrix date. Tests use it to
  verify that the existing pages run on the new tables, by patching `uptimedb.datasource.current_dataset`.

## Reused, unchanged

- `uptimedb.parser.parse_workbook`: Up-Time Report.
- `uptimedb.daywise.parse`: Day Wise Outage.
- `uptimedb.escalation.parse`: matrix.
- `uptimedb.raw.parser`: CSV decoding and dates.
- `uptimedb.raw.rules.canonical_circle` and the `organization` circle aliases.
- `accounts.roles`: Admin check.
- `accounts.audit`.

## Tests

`backend/tests/test_sitedata.py`, run on the test database.
