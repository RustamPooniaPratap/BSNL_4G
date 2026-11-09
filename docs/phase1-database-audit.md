# Phase 1: Database audit, reset plan and proposed schema

Status: **audit complete, nothing changed**. No backup, deletion or migration has been run. Every step after the audit
waits for approval of the decisions in section 7.

Audit date: 4 Nov 2026, live PostgreSQL 18.6 database `4G-DB`, read-only queries.

## 1. Existing tables

| Group | Tables (rows) | Purpose | Phase 1 |
|---|---|---|---|
| Django / auth | `auth_user` (4), `auth_group` (4), `auth_permission` (156), `auth_user_groups` (2), `auth_*` others (0), `django_session` (164), `django_content_type` (39), `django_migrations` (36) | Sign-in, sessions, migrations | **Protected** |
| Access control | `accounts_accountprofile` (3), `accounts_role` (4), `accounts_rolepermission` (19), `accounts_accessassignment` (3), `accounts_accessevent` (8) | Roles, permissions, project/circle scopes, audit | **Protected** |
| Organization | `organization_project` (3), `organization_circle` (13), `organization_projectcircle` (14), `organization_circlealias` (53), `organization_organizationchange` (23) | Projects, circles, code aliases (used by the raw CSV import) | **Protected** |
| RCA | `rca_rcarecord` (178,692), `rca_rcaevent` (2,649), `rca_rcaimportbatch` (15), `rca_rcareportingcycle` (30), `rca_rcarequiredsubmission` (39), `rca_rcacausecategory` (2), `rca_rcacausemapping` (4), `rca_rcaworkflow`, `rca_rcacomment`, `rca_rcareport` (0) | RCA records and workflow | **Protected, untouched** |
| Alerts | `alerts_*` (all 0 rows) | Email automations | **Protected** |
| Configuration | `uptimedb_appsetting` (2: `dashboard_data_source = database`, `alerts_worker_heartbeat`) | Application settings | **Protected** |
| Site / performance | `uptimedb_uptimesite` (6,726), `uptimedb_sitedailyperformance` (401,544), `uptimedb_sitemonthlyperformance` (87,438), `uptimedb_dataimportbatch` (30), `uptimedb_escalationsite` (6,764), `uptimedb_escalationimportbatch` (2) | Site master, daily and monthly performance, upload history | **Reset candidates** |

Modules without tables of their own:
- **Team Performance** (`/api/dashboard/teams/*`), Dashboard, Site Portfolio, Thresholds, Top Performers, CI/IE pages,
  All KPI's (`/api/all-kpis/*`) and the report exports have no tables of their own. They are calculated live from the
  site/performance tables. A reset deletes nothing of theirs, but they show "no data" until new data is loaded.
- The Team Performance hierarchy migration `organization.0004_team_performance_hierarchy` (uncommitted Antigravity
  work) is **not applied**. Its future table `SitePersonnelAssignment` has a CASCADE foreign key to `UptimeSite`. It
  does not exist yet, so a reset cannot cascade into it. Keeping `UptimeSite` as the site master model (section 5)
  keeps that migration valid.

Foreign keys verified in `pg_constraint`: the only references to `uptimedb_*` tables come from other `uptimedb_*`
tables. RCA records reference sites by text (`site_id`, `site_key`), with no foreign key.

## 2. Current performance data flow

| Source | Code | Writes | Notes |
|---|---|---|---|
| Uptime Master workbook (Up-Time Report sheet) | `uptimedb/importer.py`, `parser.py` | sites, monthly, daily | Preview then commit. **Changed values overwrite** earlier values (also values from other sources). |
| Second Uptime workbook (RJ, MP & OD report) | `importer.py` + `reconcile.py` | same | Conflicts resolved by a per-import choice (`conflict_source`). |
| Consolidation (Escalation) Matrix | `uptimedb/escalation.py` | `EscalationSite` | A **second site table**; linked to `UptimeSite` by (project, circle, ID). |
| 4G raw daily CSV (CNMC dump) | `uptimedb/raw/*` | daily | `Nw Avail (4G TCS)`; never overwrites a different stored value (blocked as conflict); outage = 1440 × (1 − avail/100). |
| LWE raw daily CSV | `uptimedb/raw/*` | nothing | Blocked: the LWE ID / band mapping is not configured. |
| Data Panel edits | `masterdata/editors.py` | sites, daily, monthly, matrix | Direct edits, one `data_panel` batch per save. |
| Excel mode | `dashboard/workbook.py` via `datasource.current_dataset()` | none | When `dashboard_data_source = excel`, every page reads the workbook file instead of the database. |
| Monthly | `SiteMonthlyPerformance` | — | Source snapshot columns of the workbook, **all 87,438 rows from batch #1 (24 Oct)**; Oct-25 to Oct-26. Not recalculated from daily. |
| Weekly | `dashboard/metrics.WEEKS`, All KPI's | — | Calculated from daily values at request time. |

Daily rows by origin: Master workbooks 390,294 (batches 1, 3, 16, 17, 18, 23, 24), raw CSVs 11,250 (batches 9–15,
22, 25, 26). Range 1 Sep – 1 Nov 2026.

## 3. Duplicate and conflicting sources

1. **Two site tables**: `UptimeSite` (Uptime Master) and `EscalationSite` (Consolidation Matrix) both hold circle, BA,
   OA, CI/IE and On-Air for the same 6,724 sites. The matrix adds 40 non-dashboard sites (Sterlite 17, VI-HPSC 23).
2. **Daily values from two sources, last writer wins**: the Master workbook import overwrote 1,531 raw CSV (CNMC)
   values earlier (reported in `Data/processed/rca_reconciliation/`). There is no record of the overwritten value.
3. **Two upload tables**: `DataImportBatch` and `EscalationImportBatch`.
4. **Two dashboard sources**: Excel mode vs database mode.
5. **Stale monthly snapshot**: monthly values and O&M Start flags come from one 24 Oct import only.
6. **Band identifiers**: 4G matrix rows carry `BTS Site ID_B1` (1,222) and `_B28` (1,548) next to the site ID; LWE
   rows have none, and the LWE raw IDs (e.g. `JHDTJN001`) differ from master IDs (`LWEJH0001`). No LWE Band ID
   mapping file is present in `Data/`.

Site identity is clean: no BSNL Site ID occurs in more than one project or circle (Up-Time 6,726; matrix 6,764).

## 4. Dependencies to preserve

- `UptimeSite`, `SiteDailyPerformance`, `SiteMonthlyPerformance`, `DataImportBatch`, `EscalationSite` are read by
  `uptimedb/datasource.py` (every dashboard page), `masterdata` (Data Panel), `dashboard/report_export.py`,
  `allkpis/services.py`, `organization/hierarchy_serializers.py` and the raw CSV resolvers.
- APIs to keep working: `/api/dashboard/*`, `/api/all-kpis/*`, `/api/master-data/*`, `/api/data-source/`,
  `/api/imports/*`, `/api/raw-uploads/*`, `/api/arrival-tracker/`, `/api/rca/*`.
- Code with uncommitted Antigravity changes (`uptimedb/datasource.py`, `rca/*`) is changed only where Phase 1 needs it.

## 5. Proposed architecture

Approach: **evolve the existing `uptimedb` models with additive Django migrations** (applied after the reset, on empty
tables), instead of new parallel tables. This keeps one model per concept, keeps every existing API and the pending
`organization.0004` foreign key valid, and avoids a second data layer. Duplicates (`EscalationSite`,
`EscalationImportBatch`, Excel mode) are retired in Phase 2 once the importers write to the new structure.

**A. Site Master** (`UptimeSite`, one row per BSNL Site ID)
- `site_key` unique on its own (today: unique per project and circle).
- New: district, sub-district, village code, site type/category, technology (`4G Saturation` / `LWE`), O&M status,
  O&M Start Date, On-Air status and date, commissioning, EB/DG, location, escalation chain (from the matrix).
- `present_in_latest_matrix` + `last_matrix_batch`: a site missing from a new matrix is flagged, never deleted.
- `created_at`, `updated_at`, `source_batch`, per-field source (which upload set each attribute).

**A2. Site Identifier** (new): every ID that names a site: BSNL Site ID, BTS IP ID, B1 / 2100 MHz and B28 / 700 MHz
band IDs, LWE raw IDs. Unique per identifier. Raw rows resolve through this table to one site, so several band IDs
can never create several daily records.

**B. Daily Site Performance** (`SiteDailyPerformance`, the only daily table)
- Site FK, `report_date`, technology, circle (as reported), availability %, outage minutes, upload FK, source row,
  `created_at`, `updated_at`.
- Unique **(site, report_date, technology)**; checks 0 ≤ availability ≤ 100 and 0 ≤ outage ≤ 1,440.
- Every site belongs to one technology, so this equals one record per site and day; technology is kept as asked and
  validated against the site.

**B2. Daily Performance Change** (new, append-only): each insert, rejected conflict and authorized correction with the
old and new value, both uploads, user, time and reason. Nothing is overwritten silently.

**C. Monthly Site Performance** (`SiteMonthlyPerformance`)
- Site, month, calculation category (e.g. `daily_derived`, `source_snapshot`), total outage minutes, availability %,
  reporting days used, source upload, `finalized_at`, revision.
- One current record per (site, month, category); earlier revisions kept.
- Monthly O&M Start flag (used by USD / NSLA) moves to a small **Site Month Status** table (site, month, O&M Start,
  source upload), so it is not repeated per category.

**D. Upload History** (`DataImportBatch`)
- Kinds: Uptime Master, Consolidation Matrix, LWE Band ID mapping, 4G raw CSV, LWE raw CSV, Data Panel correction.
- Uploading user, file name, checksum, stored copy, upload / commit time, circle, reporting date, technology,
  records received / accepted / rejected / duplicate / unmatched, validation status, processing status, report, error.

**E. Traceability**: every daily, monthly and site record points to its upload and source row; corrections are uploads
of kind Data Panel with a user and a reason; B2 keeps the history.

## 6. Reset plan (after approval and a verified backup)

**Backup**
- `pg_dump -Fc` of the whole database to `Data/backups/4G-DB_pre_phase1_<timestamp>.dump`.
- SHA-256 recorded.
- `pg_restore --list` must read it.
- Row counts of every table saved beside it.
- The 32 old upload records are exported to CSV.

**Reset**: one transaction, by a dedicated management command with `--dry-run`. Each named model is deleted in
foreign-key order; no `TRUNCATE … CASCADE`, `DROP` or `flush`.

| Order | Table | Rows | Reason |
|---|---|---|---|
| 1 | `uptimedb_sitedailyperformance` | 401,544 | Rebuilt from approved sources |
| 2 | `uptimedb_sitemonthlyperformance` | 87,438 | Stale snapshot |
| 3 | `uptimedb_escalationsite` | 6,764 | Merged into the site master |
| 4 | `uptimedb_uptimesite` | 6,726 | Rebuilt from the latest matrix |
| 5 | `uptimedb_dataimportbatch` | 30 | Upload history of the removed data (exported first) |
| 6 | `uptimedb_escalationimportbatch` | 2 | Same |

**Safeguards**
- Before deleting, the command re-checks that no table outside this list references them.
- It counts and checksums every protected table before and after, and rolls back on any difference.
- `uptimedb_appsetting` and staged files on disk are kept.

**Afterwards**
- Apply migrations, verify constraints, protected tables, RCA counts, sign-in, `manage.py check`, test suite and API
  smoke tests.

## 7. Decisions needed before the backup and reset

1. **Field precedence** between the Consolidation Matrix and the Uptime Master for circle, BA, OA, CI/IE, On-Air,
   O&M Start.
2. **Daily source precedence** when the Uptime Master and the raw CSV disagree for the same site-day.
3. **LWE band rule**: which value counts when both the 2100 and 700 MHz IDs report; and the LWE Band ID mapping file.
4. **Monthly history** Oct-25 – Sep-26 exists only as workbook snapshot columns: re-import it as `source_snapshot`, or
   keep only months derived from daily data.
5. **Old upload history**: export to CSV and reset, or keep.
6. **Non-dashboard matrix sites** (Sterlite, VI-HPSC): store flagged, or exclude.
7. **Empty dashboard** between the reset and the Phase 2 reload; retiring Excel mode.
8. Leaving `organization.0004` (Antigravity) unapplied and untouched.
