# Production import into the new data layer (`sitedata`): 4 Nov 2026

Approved operation: import September–October 2026 data into the new `sitedata` tables of `4G-DB` (127.0.0.1:5432,
role `bsnl_portal_app`). The validated replay sequence was used, with the Uptime Master first.

Scope held:
- writes went only to the 9 `sitedata` tables;
- no old table, data-source setting, RCA or other module was changed;
- no migration was run;
- `organization.0004` is still unapplied.

The dashboard still reads the old tables.

## Before

| Step | Result |
|---|---|
| Fresh backup | `C:\Users\gaura\Backups\4G-DB\20261104T124210Z\`: dump SHA-256 `f512a552d8d60f55d4bbb2d05c8530e27bbf87cceb858397745f33f6347cb839` (41,755,646 bytes); `pg_restore --list` reads 52 table definitions and 52 TABLE DATA entries; 65 `Data/processed` files copied; `sha256sum -c` all OK |
| Counts before (12:44:13 UTC) | 52 tables; all 9 `sitedata` tables empty |
| Script guards | Refuses unless the database is `4G-DB` on 127.0.0.1 with role `bsnl_portal_app` and every `sitedata` table is empty |

## Uploads (each committed in its own transaction)

| # | Source | Tech | Received | Accepted | Duplicate | Conflict | Unmatched | Rejected |
|---|---|---|---|---|---|---|---|---|
| 1 | Consolidated Escalation Matrix _Oct'26 | all | 6,764 | 6,764 | 0 | 436 (ambiguous IDs) | 0 | 0 |
| 2 | LWE Band ID.xlsx | LWE | 1,996 | 1,994 | 1 | 0 | 0 | 1 |
| 3 | RJ, MP & OD Uptime Report Sep-26 | 4G | 136,290 | 136,229 | 0 | 0 | 60 | 1 |
| 4 | LWE Uptime Report day wise Sept'26 | LWE | 65,460 | 65,459 | 0 | 0 | 0 | 1 |
| 5 | RJ MP OD Uptime Report Oct-26 (003) | 4G | 140,864 | 140,802 | 0 | 0 | 62 | 0 |
| 6 | LWE Uptime Report Oct'26 | LWE | 67,642 | 67,640 | 0 | 0 | 0 | 2 |
| 7–14 | 4G CSVs (OD 13/25/26/27, RJ 25/26/27, MP 27 Oct) | 4G | 49,474 | 0 | 10,126 | 1,531 | 36,957 | 0 |
| 15–21 | LWE CSVs (OD 13/25/26/27, JH 13, AP 25, MP 27 Oct) | LWE | 30,899 | 0 | 1,898 | 21 | 21,398 | 14 |

Monthly calculation:
- September: 19,331 records (6,723 sites; 6,406 On-Air; 6,202 O&M).
- October: 19,332 records (6,724 sites).

## Verification

| Check | Result |
|---|---|
| Daily records | **410,130** (4G 277,031, LWE 133,099) |
| Equal to the validated replay | **Yes**: same keys, values and sources for all 410,130 records (0 differences) |
| Row counts of the 9 tables | identical to the replay: upload batches 21, sites 6,764, identifiers 17,214, mapping rows 1,996, mapping identifiers 5,939, identifier conflicts 436, daily 410,130, precedence events 1,552, monthly 38,663 |
| `manage.py check` | No issues |
| Migrations | `sitedata.0001_initial` applied; `organization.0004` not applied |

## Changes to other tables during the import window (12:44–13:06 UTC): made by portal users, not by this import

| Table | Before | After | Cause |
|---|---|---|---|
| `rca_rcaimportbatch` / `rca_rcarecord` / `rca_rcaevent` | 20 / 178,692 / 2,649 | 21 / 180,512 / 3,478 | RCA upload `RCA_Consolidation_Nov.xlsx` committed 12:44–12:46 UTC by user #1 |
| `uptimedb_dataimportbatch` / `uptimedb_sitedailyperformance` | 30 / 401,544 | 31 / 412,968 | Old-system import #31 `4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` by `pratap.admin` at 13:00–13:01 UTC through the portal (13,813 October daily rows, 13,809 of them LWE) |

Consequences:
- These changes are newer than both backups: restoring a 4 Nov backup would undo them.
- The old dashboard's LWE October now includes the consolidated workbook. The new layer uses the LWE Oct'26 report
  (the approved October source), so the two can differ for LWE October.

## Rollback

The data can be removed only by deleting from the `sitedata` tables or with `manage.py migrate sitedata zero`. Both
need approval, and neither affects any other table.
