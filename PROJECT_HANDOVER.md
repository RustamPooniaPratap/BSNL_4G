# Project Handover: BSNL 4G Saturation & LWE Reporting Portal

State as of **4 Nov 2026**. Repository at commit `e0cd4c4` ("updated"). The new site data layer (`backend/apps/sitedata/`), the Site
Portfolio migration, the All KPI's Site Handover removal and the Phase 1–3 / production reports in `docs/` are **uncommitted
changes in the working tree** at this writing.

**Migration in progress.** A new site and performance data layer (`sitedata`) exists in the production database and is
populated with September–October 2026. **Only Site Portfolio reads it so far**; every other dashboard module still reads the
legacy `uptimedb` tables (section 3, "Data layers", and section 6).

This document is the entry point for an AI coding assistant continuing development. It summarises the whole project and links to the detailed guides in [`docs/`](docs/README.md). Those guides remain the reference for their topics; where they and this file differ, the code wins (check it).

Anything marked **Not verified** could not be confirmed from the code or a running system while writing this.

---

## 1. Project architecture

### Purpose

An internal web portal for BSNL's **4G Saturation** and **LWE** (Left Wing Extremism) mobile site programmes. It replaces a large Excel "Master workbook" with a database-backed application. Its main jobs:

- Report daily and month-to-date site **uptime / outage** per project, circle and site, with threshold buckets, NSLA and trends.
- Ingest the daily raw availability files (CNMC CSV dumps) and the Master workbook into PostgreSQL.
- Record and analyse **RCA** (root cause analysis) of outages, including reporting periods and circle submissions.
- Track CI/IE (field personnel) performance.
- Manage users, roles and project/circle-level access; send automated emails.

### Technology stack

| Layer | Technology (from `backend/requirements.txt`, `frontend/package.json`) |
|---|---|
| Backend | Python 3.11, Django 5.1, Django REST Framework 3.17, django-cors-headers, python-dotenv, pandas, openpyxl, psycopg 3, cryptography (Fernet) |
| Database | PostgreSQL (database `4G-DB` on the developer machine). SQLite is used only by the test suite (`DB_ENGINE=django.db.backends.sqlite3`). |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS 4, shadcn/radix-ui, lucide-react, recharts, react-router-dom 7 |
| Tests | Django test runner (backend, `backend/tests/`); Vitest + Testing Library (frontend, `*.test.tsx`); oxlint |
| OS used in development | Windows 11, VS Code; the project lives in a OneDrive folder |

### Folder structure

```
4G Saturation_Portal/
├── backend/                 Django project
│   ├── config/              settings.py (reads backend/.env), urls.py
│   ├── apps/
│   │   ├── accounts/        sign-in, users, roles, permission catalogue, access assignments, access history
│   │   ├── organization/    projects, circles, project-circle associations, circle aliases, change history
│   │   ├── sitedata/        NEW data layer (source of truth for site master and performance): Consolidation Matrix
│   │   │                    site master, LWE Band ID mapping, central daily table, monthly results, upload history,
│   │   │                    importers, shared rules (rules.py), Site Portfolio API (portfolio.py); see its README.md
│   │   ├── uptimedb/        LEGACY uptime data: sites, daily/monthly performance, escalation matrix, imports,
│   │   │                    raw CSV upload (raw/), CSV arrival tracker, data-source switch (still used by most pages)
│   │   ├── allkpis/         All KPI's module (read-only APIs; reads the legacy dataset)
│   │   ├── dashboard/       KPI/metric engine (metrics.py), dataset loading (workbook.py), Excel report exports
│   │   ├── rca/             RCA records, imports, reporting periods, taxonomy, summary, breakdown, site scope
│   │   ├── masterdata/      Data Panel (Master Data explorer): dataset registry, editing framework
│   │   ├── alerts/          SMTP account, automations, email queue/worker, history
│   │   └── common/          health check, legacy raw-file upload and email endpoints
│   ├── tests/               all backend tests (one module per area)
│   ├── logs/audit.log       audit log (sign-ins, admin actions)
│   └── .env / .env.example  configuration (never commit .env)
├── frontend/
│   └── src/
│       ├── App.tsx          routes and guards
│       ├── pages/           one file per page (rca/, alerts/, data/, auth/ subfolders)
│       ├── components/      shared UI: dashboard/, rca/, masterdata/, organization/, users/, auth/, ui/ (shadcn)
│       ├── context/         auth.ts (page permissions), workbook, page header
│       ├── hooks/           useApiQuery, useDashboardFilters, useOrganization …
│       ├── features/all-kpis/  All KPI's module (self-contained; README.md)
│       ├── services/api.ts  API calls (sitePortfolioApi.ts: Site Portfolio on the new data layer)
│       ├── types/           TypeScript types of API responses
│       └── test/            fixtures and render helpers
├── Data/                    raw/ (uploaded raw files), processed/ (staged imports, reports), reference/ (reference workbooks)
├── docs/                    detailed guides (see docs/README.md)
├── scripts/                 README only (utility scripts referenced there are not in this folder)
├── start_backend.bat, start_frontend.bat, start_all.bat, health_log.bat   Windows launch / health scripts
└── PROJECT_HANDOVER.md      this file
```

### Frontend ↔ backend communication

- REST/JSON over HTTP. The frontend calls `VITE_API_BASE_URL` (frontend/.env; default `http://localhost:8000/api`). All calls are in `frontend/src/services/api.ts` (`request()` for GET, `send()` for JSON writes).
- Session authentication with CSRF: `GET /api/auth/csrf/` gives the token, sent back as `X-CSRFToken`. Errors are `{error, details}` JSON (`ApiError` in api.ts).
- URL mounting (`backend/config/urls.py`):

| Prefix | App |
|---|---|
| `/api/auth/` | accounts (sign-in, users, roles, access) |
| `/api/` | common (health, legacy upload/email) and uptimedb (data-source, imports, raw-uploads, arrival-tracker) |
| `/api/dashboard/` | dashboard metrics and exports (legacy dataset) |
| `/api/site-portfolio/` | Site Portfolio on the new data layer (`apps/sitedata/portfolio_views.py`) |
| `/api/all-kpis/` | All KPI's (`apps/allkpis`; legacy dataset) |
| `/api/rca/` | RCA |
| `/api/organization/` | organization |
| `/api/master-data/` | Data Panel |
| `/api/alerts/` | alerts |

### Database configuration

- PostgreSQL via `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` in `backend/.env`. `settings.py` refuses to start without a valid `DB_ENGINE` (no silent fallback).
- Developer machine: database `4G-DB`, host 127.0.0.1, port 5432 (values seen in the health check; credentials are not documented here).
- `backend/db.sqlite3` exists in the folder; it is used only if `DB_ENGINE` is set to SQLite. Not verified what it contains; do not rely on it.

### Authentication and authorization (summary; details in section 5)

- Django sessions, no public registration, Admin-provisioned accounts with temporary passwords, login throttling, idle timeout, optional "remember me". No sign-in bypass: the former development bypass (`DEV_LOGIN_BYPASS`) was removed on 5 Nov 2026.
- Authorization is enforced in the API: DRF default permission `IsPortalUser`, plus `IsAdminRole`, `Can(module, action)` and data restriction by project/circle (`apps/accounts/access.py`). The frontend guards (`RequireAdmin`, `RequirePage`, `context/auth.ts`) only decide what to show.

---

## 2. Implemented features

Status legend: **Complete** = implemented, tested, in use; **Partial** = works with stated gaps; **Pending** = not implemented.

| Feature | Route(s) | What it does / how | Key files | Status |
|---|---|---|---|---|
| Overview dashboard | `/`, `/?report_type=…` | KPI cards (MTD uptime, Not meeting SLA, Unique sites down, Below 60% MTD, Outage minutes Day/MTD/Month), trends, breakdowns, alerts. Filters: project, circle, site scope, reporting date, trend period. | `pages/DashboardPage.tsx`, `components/dashboard/*`, `apps/dashboard/views.py`, `metrics.py` | Complete |
| Threshold Analysis | `/thresholds`, `/thresholds/buckets` | Uptime buckets by period with comparisons; Uptime Buckets & Site Details table (also opened from CI & IE Performance with a person filter, see below). | `ThresholdPage.tsx`, `BucketsSitesPage.tsx`, `metrics.threshold_analysis` | Complete |
| Site Portfolio | `/portfolio` | Portfolio KPIs (total, On-Air, O&M Start, difference, conversion activity, uptime buckets, week / month views) and the circle-wise breakdown. **Reads the new `sitedata` layer** via `/api/site-portfolio/`: sites and effective dates from the Consolidation Matrix, daily / monthly performance from the new models (details in section 3, "Site Portfolio on the new data layer"). | `PortfolioPage.tsx`, `services/sitePortfolioApi.ts`, `apps/sitedata/portfolio.py`, `portfolio_views.py` | Complete (migrated 4 Nov 2026; `docs/site-portfolio.md` still describes the legacy sources) |
| All KPI's | `/all-kpis` | Consolidated KPIs: portfolio, availability (day / week / month), outage, USD, SLA thresholds, NSLA, RCA Final Buckets, completeness, Circle → CI → IE → Site drill-down. Reads the legacy dataset. The Site Handover card and field were removed on 4 Nov 2026 (not a project concept); RCA ownership (Own / Customer / Third Party / Pending) remains "Not configured". | `features/all-kpis/*`, `apps/allkpis/*`, `features/all-kpis/README.md` | Complete (still on the legacy data layer) |
| Team Performance | `/teams`, `/teams/ci-ie`, `/teams/top` | CI/IE performance, CI-wise NSLA table (names link to the person's sites), circle-wise top performers. Admin only. | `TeamsPage.tsx`, `CiIePerformancePage.tsx`, `TopPerformersPage.tsx`, `metrics.team_*` | Complete |
| Data source switch & PostgreSQL import | `/workbook` | Upload the Master workbook (Excel source) or import it into PostgreSQL (preview → commit); switch the dashboard source between Excel and PostgreSQL. Admin only. | `DatabaseImportPage.tsx`, `apps/uptimedb/views.py`, `importer.py`, `datasource.py`, docs/database-import.md | Complete |
| Data Source & Quality | `/data-source` | Data coverage, warnings, calculation check against workbook figures. | `DataSourcePage.tsx`, `dashboard/crosscheck.py` | Complete |
| Raw daily CSV upload | `/data/upload-csv` | Upload one circle's CNMC availability dump; validate, preview, commit into `SiteDailyPerformance`. Outage = 1440 × (1 − availability/100). | `UploadCsvPage.tsx`, `apps/uptimedb/raw/*`, `raw_views.py` | Partial: 4G Saturation imports; LWE files validate but import no rows (LWE ID mapping not supplied, `LweResolver`) |
| Add Row / Add Site | `/data/add-row`, `/data/new-site` | Validate a daily value / site record **in the browser only**; nothing is saved. | `pages/data/AddRowPage.tsx`, `AddSitePage.tsx`, docs/data-entry.md | Partial by design (no backend integration); the Data Panel now offers real Add/Edit |
| CSV Arrival Tracking | `/daily-ingestion` | Per project/circle and date: daily data coverage and raw upload state; reminder emails. Admin only. | `CsvArrivalPage.tsx`, `apps/uptimedb/arrivals.py`, docs/csv-arrival-tracking.md | Complete |
| Report downloads | Overview/4G/LWE | Daily Uptime Report and Full Consolidated Report (.xlsx). | `dashboard/report_export.py`, docs/report-downloads.md | Complete (Excel only; no PDF exists) |
| RCA Register | `/rca` | Browse/filter RCA records; record manual RCA; follow-up workflow (status, corrective action, review), comments. | `pages/rca/RcaRegisterPage.tsx`, `components/rca/*`, `apps/rca/views.py`, `services.py` | Complete |
| RCA uploads | `/rca/import`, `/rca/import/consolidated` | Upload Circle RCA (one project/circle/date) and Upload Consolidated RCA (all circles; Admins and the "RCA Consolidated Uploaders" group); preview → commit, conflicts and corrections. | `RcaImportPage.tsx`, `apps/rca/importer.py`, `parser.py`, docs/rca.md | Complete |
| RCA Summary | `/rca/summary/*` | Overview, Circle-wise RCA Breakdown (with Total / USD / NSLA site columns), Root Cause Analysis, Project & Circle Analysis, Daily & Monthly Trends. | `RcaSummaryPage.tsx`, `RcaBreakdown.tsx`, `apps/rca/services.summary`, `breakdown.py` | Complete |
| RCA Site Scope | all RCA pages with site data | All Sites / O&M Start Sites / O&M Not Started Sites, applied on the server. | `apps/rca/sitescope.py`, `components/rca/RcaShared.tsx` | Complete |
| RCA Submissions | `/rca/submissions` | Reporting periods (cycles), expected circles, circle submissions vs data availability, period workbook generation. Admin only. | `RcaSubmissionsPage.tsx`, `apps/rca/cycles.py` | Complete |
| RCA cause mapping | `/rca/mappings` | Admin maps RCA descriptions to cause categories. Not in the sidebar (page kept). | `RcaMappingPage.tsx`, `services.cause_queue` | Complete (hidden from navigation) |
| RCA bucketization correction | command | `manage.py rca_bucketization` (dry run, `--report`, `--apply`) against the approved taxonomy. | `apps/rca/taxonomy.py`, `management/commands/rca_bucketization.py` | Complete (applied 30 Oct 2026) |
| Master Data / Data Panel | `/master-data/*` | Explorer of 5 datasets (Site Master, Daily Performance, Monthly Performance, Escalation Matrix, RCA Data): filters, period views, sorting, paging, column choice, CSV/Excel export, and **spreadsheet-like editing** (Add/Edit, no Delete) saved in one transaction. | `MasterDataPage.tsx`, `components/masterdata/*`, `apps/masterdata/*` | Complete |
| Organization | `/admin/organization/*` | Projects, circles, project-circle mapping, user access (CI-role assignments), code mapping (circle aliases), change history. Admin only. | `OrganizationPage.tsx`, `components/organization/*`, `apps/organization/*`, docs/organization.md | Complete |
| Users & Roles | `/admin/users/*` | Users (create, edit, activate/deactivate, reset password, sign out everywhere, effective permissions), Roles & Permissions matrix, Access Assignments with Access Preview, Access History. Admin only. | `UsersPage.tsx`, `components/users/*`, `apps/accounts/*`, docs/access-control.md | Complete |
| Alert & Email Automation | `/admin/alerts/*` | SMTP account (encrypted password, test, activate), automations (CSV reminder, RCA reminder, uptime report, upload-failure alert, custom), email history with retry/resend; background worker `run_alerts`. Admin only. | `pages/alerts/*`, `apps/alerts/*`, docs/alerts.md | Complete in code; real sending not verified (needs company SMTP / M365 approval) |
| Legacy email (CSV arrival reminders) | — | `apps/common/email.py`, `EMAIL_BACKEND` setting (console backend by default = test mode). | `apps/common/*` | Complete (separate from the Alert module) |
| Windows launch scripts | — | `start_backend.bat`, `start_frontend.bat`, `start_all.bat`, `health_log.bat`. | project root | Complete |

---

## 3. Database documentation

Source: the models in `backend/apps/*/models.py` and the migrations listed below. Django's own tables (`auth_user`, `auth_group`, `django_session`, …) are used for users, built-in role groups and sessions.

### Data layers (read this first)

| Layer | Tables | Role now | Notes |
|---|---|---|---|
| **New: `sitedata`** | `sitedata_site`, `_siteidentifier`, `_identifierconflict`, `_lwemappingrow`, `_lwemappingidentifier`, `_dailysiteperformance`, `_dailyperformanceevent`, `_monthlysiteperformance`, `_uploadbatch` | **Source of truth for site master and performance data.** Read by Site Portfolio only, so far | Migration `sitedata.0001_initial` applied to production 4 Nov 2026; populated the same day (section 6) |
| **Legacy: `uptimedb`** | `uptimedb_uptimesite`, `_sitedailyperformance`, `_sitemonthlyperformance`, `_escalationsite`, `_dataimportbatch`, `_escalationimportbatch`, `_appsetting` | **Retained** and still used by every other module, the raw CSV upload, the Database Import page and the Data Panel | Not deleted or cleared; still written by the existing importers (e.g. a Master workbook import on 4 Nov 2026). `uptimedb_appsetting` holds application settings (data source, alert heartbeat) and is not part of the site data |
| **RCA** | `rca_*` | Existing operational data | **Must remain intact.** RCA stays on its existing system and is excluded from the migration. It also reads legacy site tables (site validation, cycles, Site Scope, overview), so the legacy site tables cannot be cleared while RCA depends on them |
| **Infrastructure** | `auth_*`, `accounts_*`, `organization_*`, `alerts_*`, `django_*` | Users, sign-in, roles, permissions, organization, alerts | Retained, unchanged |

Detailed design and history: `docs/phase1-database-audit.md` (audit and design), `docs/phase2-replay/` (validation),
`docs/phase3-production-readiness-audit.md` (readiness, dependencies, the future controlled reset), `docs/production-backup-report-20261104.md`,
`docs/production-sitedata-import-20261104.md`, `backend/apps/sitedata/README.md`.

### Migrations (applied on the production PostgreSQL `4G-DB` as of this writing)

| App | Migrations |
|---|---|
| accounts | 0001_initial, 0002_portal_roles, 0003_noc_lead_role, 0004_account_circles, 0005_rca_consolidated_group, 0006_access_control, 0007_data_panel_permissions |
| organization | 0001_initial, 0002_initial_organization (seeds projects, circles, associations, aliases), 0003_access_moved_to_assignments (drops `UserCircleAccess` after copying) |
| uptimedb | 0001_initial, 0002_escalation_matrix, 0003_escalation_village_code, 0004_raw_daily_uploads, 0005_data_panel_batch_kind (choices only) |
| rca | 0001_initial, 0002_reporting_cycles, 0003_upload_details, 0004_incident_occurrence, 0005_upload_types |
| alerts | 0001_initial |
| sitedata | 0001_initial (9 new tables only; applied 4 Nov 2026) |
| dashboard, common, allkpis | no models |

**Not applied:** `organization.0004_team_performance_hierarchy` (Team Performance hierarchy). Its `SitePersonnelAssignment.site`
foreign key points to the legacy `uptimedb.UptimeSite` with ON DELETE CASCADE; review and re-target it before applying.

### New data layer tables (`sitedata`)

| Model | Purpose | Key rules |
|---|---|---|
| `Site` | One row per BSNL Site ID (6,764), attributes from the **Consolidation Matrix**: circle, BA, OA, district, CI / IE, Site On-Air Date, O&M Start Date | `site_key` unique; `technology` (4G Saturation / LWE) and `circle` are independent fields; Sterlite and VI-HPSC sites kept as `outside_scope` (excluded from every KPI); a site missing from a newer matrix is flagged, never deleted |
| `SiteIdentifier`, `IdentifierConflict` | Every identifier of a site (BSNL ID, BTS IP ID, 2100 / 700 MHz IDs); ambiguous IDs blocked | unique (kind, key) |
| `LweMappingRow`, `LweMappingIdentifier` | Every row of every LWE Band ID mapping import (history) | never deleted |
| `DailySitePerformance` | **The only daily table**, 4G and LWE | unique (site, report_date, technology); 0–100% and 0–1,440 min checks; no record = not reported |
| `DailyPerformanceEvent` | Append-only log of conflicts, supersedes and corrections | source precedence: correction > Uptime Master > raw CSV |
| `MonthlySitePerformance` | Monthly results per site: all reported days, On-Air days, O&M Start days (from the effective dates), with revisions | outage-weighted over reporting days |
| `UploadBatch` | Upload history of every file (staged copy, checksum, counts, exception report) | — |

Business rules of this layer: `backend/apps/sitedata/rules.py` and its README.

### Legacy business data tables (`uptimedb`, retained) and RCA tables

| Model (app) | Purpose | Key columns | Constraints / indexes | Relations |
|---|---|---|---|---|
| `UptimeSite` (uptimedb) | **Site Master**: one row per project, circle and site | project, circle, site_id (as written), site_key (trimmed, upper case, spaces collapsed), site_name, oa, ba, on_air_raw / on_air, eb, ie_name/contact, ci_name/contact, extra (JSON), source_file/row | unique (project, circle, site_key); index (project, circle) | batch → DataImportBatch (PROTECT) |
| `SiteDailyPerformance` (uptimedb) | Daily outage per site | date, outage_minutes (NULL = not reported), uptime_pct | unique (site, date); index (date) | site → UptimeSite (CASCADE), batch → DataImportBatch (PROTECT) |
| `SiteMonthlyPerformance` (uptimedb) | Monthly figures per site, incl. **O&M Start** of that month | month (first day), outage_minutes, uptime_pct, bucket, ff_count, om_start_raw / om_start (NULL = no column) | unique (site, month) | site → UptimeSite, batch → DataImportBatch |
| `DataImportBatch` (uptimedb) | Provenance of every uptime import | kind (master_workbook / raw_daily_csv / data_panel), status, project/circle/reporting_date (raw uploads), checksum, counts, report (JSON) | index (kind, project, circle, reporting_date) | imported_by → User |
| `EscalationSite` (uptimedb) | CI-wise Consolidation & Escalation Matrix, one row per site | project (entity), circle, site_id/site_key, dates (commissioning, on-air, O&M start) with raw text, statuses, CI/IE/IL/O&M manager/CBH contacts, coordinates, match_status | unique (project, site_key); indexes (project, circle), (site_key) | uptime_site → UptimeSite (one-to-one, SET_NULL), batch → EscalationImportBatch |
| `EscalationImportBatch` (uptimedb) | Provenance of escalation imports | status, counts, report | — | — |
| `RcaRecord` (rca) | One RCA incident | reporting_date, project/_raw, circle/_raw, site_id, site_key, occurrence, om_start_raw/om_start (as written in the RCA row), outage_minutes, final_bucket/_key, bucket_2/_key, rca_text/rca_key, source (import / manual), withdrawn_at | unique (reporting_date, project, site_key, occurrence) **for source=import**; indexes on reporting_date, (project, circle), final_bucket_key, bucket_2_key, site_key | batch → RcaImportBatch (PROTECT), withdrawn_by_batch, created_by |
| `RcaImportBatch` (rca) | One RCA upload | upload_type (circle / consolidated / legacy), status, project_scope, circle, period_start, report, rows | index (upload_type, status, period_start) | cycle → RcaReportingCycle |
| `RcaWorkflow`, `RcaComment`, `RcaEvent` (rca) | Follow-up of a record, comments, history of every change | — | — | record → RcaRecord (CASCADE) |
| `RcaReportingCycle`, `RcaRequiredSubmission`, `RcaReport` (rca) | Reporting periods, expected (project, circle) units, generated period workbooks (versions) | — | unique (cycle, project, circle); unique (cycle, version) | — |
| `RcaCauseCategory`, `RcaCauseMapping` (rca) | Admin cause categories and description → category mappings | — | category name unique | — |

`RcaRecord.objects` is a manager that hides withdrawn records (`ActiveRecordManager`). Check this when counting records.

### Reference, configuration and audit tables

| Model | Purpose |
|---|---|
| `Project`, `Circle`, `ProjectCircle`, `CircleAlias`, `OrganizationChange` (organization) | Organization master: project key (stored on data rows as text, e.g. "4G Saturation"), circle code (e.g. "MP"), which circles a project covers, how sources write circle codes, history. Identity values are fixed once created. |
| `AccountProfile` (accounts) | must_change_password, legacy circle-only list (now grants nothing) |
| `Role`, `RolePermission`, `AccessAssignment`, `AccessEvent` (accounts) | Roles (3 built-in + custom), (module, action) grants, user × role × project [× circle] assignments, access history |
| `AppSetting` (uptimedb) | Key/value settings: dashboard data source (`excel` / `database`), alert worker heartbeat |
| `EmailAccount`, `AlertFile`, `Automation`, `Execution`, `Message`, `Attempt` (alerts) | Alert module (password stored Fernet-encrypted) |

### Data dependencies to respect

- Data rows reference projects and circles **by text** (`project` key, `circle` code), not by foreign key to Organization. Renaming a project key or circle code would orphan data, so these are fixed once created.
- Every uptime row points to the import batch that last wrote it (PROTECT): batches cannot be deleted while rows reference them.
- RCA records link to the Site Master only logically (project, circle, site_key). Two current RCA records have no Site Master match (section 9).
- The new `sitedata` tables have no foreign key to `uptimedb`, `rca` or `organization`; they reference only `auth_user` and each other.

---

## 4. Business logic and calculations

Detailed rules: [docs/business-rules.md](docs/business-rules.md) (dashboard), [docs/rca.md](docs/rca.md) (RCA). Main implementation: `backend/apps/dashboard/metrics.py`.

### Reporting basics

- **Projects (report types):** `4G Saturation` (written "4G Satu." in the workbook) and `LWE`. A site belongs to one project and circle; **4G and LWE site identities are kept separate**. MP under 4G and MP under LWE are different networks.
- **Dataset (legacy pages):** the dashboard reads one in-memory dataset (`dashboard/workbook.py: Dataset`) built from the **active source**: the Master workbook (Excel) or PostgreSQL (`uptimedb/datasource.py`). The source is switched explicitly by an Admin (`AppSetting`). Without the setting the default is Excel; production is set to PostgreSQL. The database dataset is cached and rebuilt when a newer committed import batch exists. The global setting was **not** changed by the migration.
- **Dataset (Site Portfolio):** built from the new `sitedata` tables (`sitedata/dataset.py`, cached in `sitedata/portfolio.py`) and run through the same `dashboard/metrics.py` functions, unchanged.
- **Missing values:** a blank daily value is **not reported**: left out of numerator and denominator, never treated as 0.

### Uptime and outage

```
uptime % = 100 × (1 − Σ outage minutes ÷ (1,440 × site-days reported))      (outage-weighted, pooled)
```

- Raw CNMC files: outage minutes = 1440 × (1 − availability / 100) (verified for 4G Saturation; not confirmed for LWE).
- **Site scopes** (dashboard filter): On-Air sites (default; On-Air = Yes), O&M Start sites (O&M Start of the current month = Yes), All sites. Internal scopes `on_air_om_start` / `on_air_om_not_started` exist for the RCA Site Scope and are not offered as dashboard filters.
- **Buckets** (MTD or period uptime per site): <60%, 60–<90%, 90–<97%, 97–<98.5%, ≥98.5%.
- **NSLA / Not meeting SLA:** sites whose uptime is **below 98.5%** (`PENALTY_THRESHOLD`, the penalty buckets); sites without a value are not counted.

### USD (Unique Sites Down)

`metrics.unique_sites_down` (in `period_summary`):

- Count = distinct **active (On-Air = Yes)** sites of the selection with **outage > 0 at least once** in the selected period. Each site counts once, and daily counts are never summed.
- Denominator = every active site of the selection in the Site Master (not only those that reported).
- The Overview card uses the **Trend period** filter. Example (live, 1–27 Oct 2026): 6,281 of 6,418 active sites (97.87%), verified against SQL.
- There is no "closed / inactive" status in the data; On-Air is the only activity flag.

### Dates and periods

- **Reporting date:** a date with data; **MTD** = 1st of the month up to the reporting date (reported dates only).
- **Weeks:** days 1–7, 8–14, 15–21, 22–end of month.
- **Trend period:** a date range, picked days, weeks, or months. Earlier months use monthly totals or daily history columns.
- Outage comparison: Day vs previous day; MTD vs the same elapsed dates of the previous month (only when all are reported); Month vs previous full month (only when the month is complete).

### CI / IE performance

- People are the **CI Name / IE Name text on each site row**; there is no person table. Blank, "-" or "0" become "Unassigned".
- CI-wise NSLA table: per (project, circle, name), the NSLA sites per month (months: monthly outage totals; current month: MTD).
- A person is identified by group + name + project + circle (`dashboard/scope.restrict_team`).
- Top performers: ranked only with ≥ 10 sites all reported and ≥ 2 eligible people per circle.

### RCA classification

- **Approved taxonomy** in `apps/rca/taxonomy.py` (`APPROVED`): Final Bucket → Bucket - 2. Matching ignores case, spaces and punctuation; anything else is kept as written and flagged, never forced into "Others".
- **Circle-wise RCA Breakdown** columns: `FINAL_BUCKET_CATEGORIES` in `apps/rca/breakdown.py`, with business-confirmed equivalents.
  - BSNL-Link and PTPL-Techn were removed (out of scope).
  - Unmapped values are counted under "Not mapped", outside the Grand Total.
  - The site columns (Total, USD, NSLA) come from Site Master / performance data via `period_summary`, not from RCA counts.
- **Other Media:** Final Bucket "Other Media" means "RCA Not Applicable". It is left out of the missing-information and completeness figures.
- **RCA Site Scope** (`apps/rca/sitescope.py`): an RCA record's O&M status is the **Site Master monthly O&M Start for the record's reporting month**, matched by (project, circle, site_key). The O&M Start written on the RCA row is not used. Records without a Site Master match or monthly value appear under All Sites only.
- Bucket keys: `parser.text_key` (case and spacing folded). Site keys: `site_key` (trim, upper case, collapse spaces), the same in uptimedb and rca.

### Organization / circle mapping

- Source circle codes and names (e.g. raw CSV "OR", "Madhya Pradesh") are resolved with `CircleAlias` (`organization/services.AliasResolver`). Unknown codes are reported, never turned into new circles.
- Raw uploads, RCA uploads and assignments accept only active project-circle associations.

### Site Portfolio on the new data layer

- **Sites and populations:** total sites = dashboard sites of the Consolidation Matrix (6,724; Sterlite and VI-HPSC excluded). On-Air and O&M Start come from the matrix **Site On-Air Date** and **O&M Start Date**: a site counts in a month when its date is on or before the month's last day. A site without a date is not counted and is flagged for review. No site is created from performance records.
- **Availability:** site-weighted (outage-weighted): 100 × (1 − Σ outage ÷ (1,440 × reported site-days)); a missing record is not reported, never 0. On-Air and O&M Start figures count each site only from its effective date, as in the validated replay. This is done in the portfolio service with dataset variants, without changing `metrics.py`.
- **Periods:** weeks 1–7, 8–14, 15–21, 22–month end. Whole months use their reporting days, not calendar days, and the page shows the number of reporting days. MTD ends at the last continuous date with data; later dates after a gap are not offered and a notice explains it.
- **Circle-wise breakdown:** one row per circle and technology (e.g. MP has separate 4G and LWE rows), the same population as the KPI cards, so totals reconcile.
- **Filters:** project (technology) and circle are independent; dates come from the new layer.
- **Coverage:** September and October 2026, through **31 Oct 2026**. The new layer has no November data yet, while the legacy tables do.
- **No fallback:** if the new layer cannot serve the page, the error is shown; legacy data is never substituted.
- **Reconciled:** 81 checks on production data (every technology and circle; all sites, On-Air, O&M Start; counts and October MTD availability) equal the validated replay with no difference.
- **Still on legacy sources:** the Dashboard and Threshold pages its cards link to. O&M heads come from the reference sheet (not site data).

---

## 5. User management and permissions

Details: [docs/access-control.md](docs/access-control.md), [docs/security.md](docs/security.md).

### Account roles (Django groups)

| Role | Scope | Notes |
|---|---|---|
| Admin (or superuser) | every page, project and circle | Several Admin accounts are supported. Admin-only pages: Team Performance, CSV Arrival Tracking, Data Source (`/workbook`), RCA Submissions, RCA cause mappings, Organization, Users & Roles, Alert. |
| NOC Lead | every project and circle | CI permissions plus RCA workbook uploads; View/Export of every Data Panel dataset; not the RCA Summary unless granted |
| CI | **only assigned project/circle pairs** | Rights come from assignments with the built-in CI role |
| "Assigned access only" (`member`) | only assigned pairs | No built-in role; rights only from assignments |

### Permission model (`apps/accounts/catalog.py`, `access.py`)

- **Modules / actions** (no Delete anywhere):
  - Dashboard & Uptime (view, export)
  - CSV Upload (upload)
  - RCA Register (view, create = "Add", edit)
  - RCA Upload (upload)
  - RCA Summary (view)
  - one Data Panel module per dataset, `data_<dataset>` (view, create, edit, export), generated from `apps/masterdata/datasets.DATASETS`
- **Assignments:** user + role + project, covering the **entire project** (every circle associated with it, including circles added later) or **one circle** per row.
- **Resolution:** a permission holds on a (project, circle) pair when an applying assignment covering that pair grants it.
  - An assignment applies only if it is active, not expired, and its role, project and association are active.
  - Pairs never mix (a project-wide View gives no Edit).
  - There are no deny rules.
- **Data-level enforcement:**
  - Dashboard endpoints compute from a dataset restricted to the user's pairs (`dashboard/scope.restrict`).
  - The RCA register, summary, Master Data, raw uploads and RCA uploads filter by pairs on the server.
  - Exports check the Export permission.
- **Self-protection:** Admins cannot change their own role or assignments; built-in roles cannot be edited (clone them instead).
- **Consolidated RCA upload:** granted per user through the "RCA Consolidated Uploaders" group (not an assignment).
- **History:** `AccessEvent` (Access History tab) and `OrganizationChange`; `backend/logs/audit.log` for sign-ins and admin actions.

### Known permission gaps / behaviours to be aware of

- CI users **without assignments** see no data (deliberate since the access-control change).
- Legacy circle-only assignments (`AccountProfile.circles`) grant nothing until reviewed.
- NOC Lead automatically gets View/Export on any new Data Panel dataset; the CI role and custom roles do not.
- The RCA Register refuses edits to *imported* RCA facts, but the Data Panel (RCA Data) allows Admins / users with Edit to change them. Edits are recorded as `RcaEvent`. This is a deliberate but inconsistent pair of rules; see section 9.

---

## 6. Current development status

### Completed

- Dashboard (Overview, 4G, LWE), Threshold Analysis, Site Details, Site Portfolio, Team Performance (CI/IE NSLA with clickable names to site details), report downloads.
- PostgreSQL import of Master workbook and Escalation Matrix; data-source switch; raw 4G daily CSV upload; CSV arrival tracking.
- RCA module: register, workflow, circle and consolidated uploads, reporting periods and submissions, summary pages, circle-wise breakdown with Total/USD/NSLA site columns, taxonomy correction, Site Scope filter.
- Organization management; Users & Roles with custom roles, permission matrix, scoped assignments, access preview and history.
- Data Panel (Master Data) explorer with per-dataset View/Add/Edit/Export permissions and transactional editing.
- USD KPI correction (distinct sites with outage > 0 in the period).
- Alert & Email Automation module (code, tests, worker).
- Windows launch and health scripts.
- **New site data layer (`sitedata`), 4 Nov 2026:**
  - created in production (`sitedata.0001_initial`, 9 new tables only);
  - verified backups taken before the migration and before the import (`C:\Users\gaura\Backups\4G-DB\`, outside the repository and OneDrive);
  - populated with the validated replay sequence: **6,764 sites** (Consolidation Matrix), the LWE Band ID mapping (1,996 rows read, 1,994 accepted), **410,130 daily records** (4G 277,031; LWE 133,099) from the September and October Uptime Masters, the 4G and LWE CSVs, and the **September and October monthly calculations** (19,331 + 19,332 records). The result equals the replay record for record.
- **Site Portfolio migrated** to the new layer and reconciled against the validated replay (section 4).
- **All KPI's:** Site Handover card and `site_handover_status` field removed; RCA ownership remains "Not configured".

### Partial / in progress

- **Migration to the new data layer** (only Site Portfolio done). Modules still on the legacy `uptimedb` tables:

  | Module | Legacy dependency (from the code) |
  |---|---|
  | Dashboard 4G / LWE (and Overview) | `/api/dashboard/*` on `uptimedb.datasource.current_dataset()` |
  | Threshold Analysis | the same dashboard endpoints and dataset |
  | All KPI's | the legacy dataset, plus O&M Start flags from `SiteMonthlyPerformance` |
  | CSV Arrival Tracker | reads `SiteDailyPerformance` (coverage), `UptimeSite.on_air` (expected sites) and `DataImportBatch` raw uploads directly; its uploads come from the legacy raw CSV importer |
  | Team Performance | `/api/dashboard/teams*` on the legacy dataset; the hierarchy services read `UptimeSite`; the pending `organization.0004` FK targets `UptimeSite` |
  | Also on legacy tables | raw CSV upload and Database Import pages (write the legacy tables), Data Panel, report exports, organization usage counts |

  **RCA remains on its existing system and is excluded from the migration.**
- Upload screens and an import lock for the new importers do not exist yet; new-layer imports run as management/scripted operations.

- Raw daily CSV upload for **LWE** on the legacy page: validated, but no rows imported (the legacy resolver has no mapping). The new data layer has the LWE Band ID mapping and imports LWE rows.
- Add Row / Add Site pages: browser-only validation (superseded in practice by Data Panel editing).
- Alert e-mail: real SMTP / Microsoft 365 sending not verified; needs company IT approval (SMTP AUTH or relay, sender mailbox, firewall).

### Pending / not implemented

- PDF exports (none exist; only Excel/CSV).
- "O&M Start = No" as a **dashboard** site-scope option, and multi-circle selection in dashboard filters (requested in the USD task; not added because it would change every page using the filter).
- OAuth (Microsoft Graph) mail sending.
- A "closed / inactive" site status (not present in the data).

### Last known development task

**Site Portfolio migration to the new `sitedata` layer** (4 Nov 2026), followed by removing Site Handover from All KPI's.
Before that:
- the production backup;
- `sitedata.0001_initial` applied;
- the September–October production import into the new layer.

**Next steps need approval, one module at a time:** migrate the remaining modules, add new-layer upload screens, and
re-target `organization.0004`. The legacy tables are **not** cleared (see `docs/phase3-production-readiness-audit.md`).

### Unresolved issues / known bugs

See section 9.

---

## 7. Important development decisions (follow these)

1. **PostgreSQL is the permanent source of truth.** Excel files are imported and exported, and the dashboard can still read the Master workbook when the Admin selects the Excel source. Do not add new runtime dependencies on Excel files.
2. **No hardcoded data.** No hardcoded site lists, project names, circle names, counts or classifications. Projects and circles come from Organization.
3. **Never invent data.** A missing value is NULL / "not reported", never 0. No mock or sample data in business workflows (tests use isolated fixtures).
4. **Project-specific site identity:** (project, circle, site_key) for Site Master; RCA uses (reporting_date, project, site_key, occurrence).
5. **No destructive operations without explicit authorization:** no database reset/flush, no deleting business records, no destructive sync (records missing from a file are not deleted). The Data Panel has no delete.
6. **Do not modify the original Master workbook** or other source files.
7. **Do not guess business rules or mappings.** Examples: LWE ID mapping, O&M status for unmatched records. Ask, and document open questions (docs/business-rules.md "Open questions").
8. **Backend enforces security.** Hiding a link is never sufficient; every endpoint checks permission and project/circle scope.
9. **Reuse, don't duplicate:**
   - One permission catalogue (`accounts/catalog.py`) and one resolver (`accounts/access.py`).
   - One metric engine (`dashboard/metrics.py`; e.g. USD and NSLA in RCA reuse `period_summary`).
   - One RCA filter path (`rca/services.filtered`).
   - One dataset registry (`masterdata/datasets.py`).
10. **Provenance:** every uptime/escalation row points to the import batch that last wrote it; Data Panel saves create their own batch (kind `data_panel`); RCA changes create `RcaEvent`s.
11. **Changes are incremental and preserve existing workflows**, filters, exports and calculations. The data source selector is never switched automatically.
12. **Secrets:** never print, log or commit passwords, keys or tokens; `.env` stays out of Git; the SMTP password is encrypted and never returned by the API.
13. **Email:** no automated messages until an email account is tested and activated; tests use mocked/locmem email.
14. **Taxonomy and breakdown layout are business-approved:** do not rename or restructure bucket columns. Only map unmapped values when the business confirms them.

---

## 8. Environment and execution

### Requirements

- Python 3.11 (virtual environment `.venv` in the project root), Node.js (v22 used) and npm, PostgreSQL (16 or later assumed; the exact server version is not verified).

### Backend

```bat
:: one-time
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
copy backend\.env.example backend\.env      :: then fill in the values
cd backend
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py createsuperuser   :: or manage.py set_role for existing users

:: run (or start_backend.bat)
..\.venv\Scripts\python manage.py runserver 8000
```

Other management commands:

| Command | Purpose |
|---|---|
| `import_uptime` | Import the Master workbook into PostgreSQL |
| `import_daywise` | Import day-wise outage reports |
| `import_escalation` | Import the Consolidated Escalation Matrix |
| `rca_bucketization` | Taxonomy correction (dry run by default) |
| `run_alerts` (`--once`) | Alert email worker |
| `set_role` | Assign a portal role to a user |
| `build_report_template` | Report template |

Check each command's `--help` before running.

### Frontend

```bat
cd frontend
npm install
npm run dev        :: Vite on http://localhost:5173 (or start_frontend.bat)
```

`start_all.bat` opens both servers in separate windows. `health_log.bat` checks frontend, backend, the database connection (credentials hidden) and the audit log.

### Environment variable names (values are not documented)

| Where | Names |
|---|---|
| `backend/.env` (via `settings.py`) | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `LOG_LEVEL`, `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DATA_DIR`, `WORKBOOK_STORE_DIR`, `MASTER_WORKBOOK_PATH`, `MAX_WORKBOOK_BYTES`, `RAW_UPLOAD_DIR`, `MAX_UPLOAD_BYTES`, `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_TIMEOUT`, `SESSION_IDLE_MINUTES`, `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE`, `REMEMBER_ME_DAYS`, `LOGIN_RATE_PER_USER`, `LOGIN_RATE_PER_IP`, `AUDIT_LOG_FILE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `TRUST_X_FORWARDED_PROTO` |
| Alert module | `ALERT_ENCRYPTION_KEY` (optional; else derived from `SECRET_KEY`), `PORTAL_URL` |
| `frontend/.env` | `VITE_API_BASE_URL` |

### Build and test

```bat
:: backend (SQLite test database; never touches PostgreSQL)
cd backend
set DB_ENGINE=django.db.backends.sqlite3
..\.venv\Scripts\python manage.py check
..\.venv\Scripts\python manage.py test tests            :: about 15 minutes for the full suite
..\.venv\Scripts\python manage.py makemigrations --check --dry-run

:: frontend
cd frontend
npx tsc -b --noEmit
npm run lint
npm test            :: vitest run
npm run build
```

Latest results (4 Nov 2026):

- Backend: 585 tests, 583 pass. The 2 failures are the known `test_reconciliation` tests, which read the live October workbook (section 9). The `sitedata` suite (61), Site Portfolio (12) and All KPI's (8) pass.
- Frontend: 318 / 318 pass; type-check, lint and build clean.

### Deployment

No production deployment configuration (Docker, CI pipeline, web server config) exists in the repository. Production security settings are applied when `DEBUG=False` (see docs/security.md); the alert worker must run as a separate long-running process (docs/alerts.md).

---

## 9. Known issues and risks

| Area | Issue |
|---|---|
| Tests | `tests/test_reconciliation.py`: 2 tests fail because they read the live October workbook, whose dates moved on (e.g. expected 14 Oct, now later). Not a regression. |
| Performance | The RCA Summary request takes about 11–16 s on the full data (~177,690 RCA records), mostly the existing aggregations; the Site Scope adds little. |
| RCA data quality | 2 RCA records have no Site Master site: 4G AP `dhssghks` (28 Oct), LWE CG `LWEBH0269` (26 Oct). 67 RCA records of 3 LWE MP sites say O&M Start "Yes" on the RCA row but "No" in Site Master (Site Scope follows Site Master). |
| Raw uploads | The legacy raw CSV page still imports no LWE rows (no mapping in the legacy resolver). The new data layer has the LWE Band ID mapping, but no upload screen yet. |
| Two data layers | Site Portfolio (new layer, through 31 Oct 2026) and the other pages (legacy tables, include 1 Nov) can show different latest dates and figures until the remaining modules are migrated. The legacy LWE October data also differs from the new layer: the legacy import of 4 Nov used the consolidated October workbook, the new layer the approved LWE Oct'26 report. |
| Source data gaps (new layer) | 78 MP 4G sites and 3 MP LWE sites have no O&M Start Date in the matrix, and 12 4G sites (6 MP, 6 OD) and 2 MP LWE sites have no On-Air Date; they are excluded from those populations until the matrix is corrected. 2 RJ sites are missing from the matrix; 436 matrix band IDs are claimed by several sites; mapping row LWEBH0141 uses a single `;`; BLG1394's 2100 and 700 IDs map to different Master IDs; 188 LWE sites have no mapping row (`docs/phase2-replay/`). |
| Excel runtime reads | `dashboard/activity.py` (legacy conversion activity) reads `Data/reference/*Escalation Matrix*.xlsx`; `dashboard/reference.py` (O&M heads, used by Site Portfolio too) reads `Data/reference/*first page*.xlsx`; the Excel data source reads the uploaded Master workbook. Site Portfolio's conversion activity now comes from the matrix dates in the database. |
| Dashboard filters | No "O&M Start = No" dashboard scope and no multi-circle selection. "All sites" scope still excludes non-On-Air sites from USD by design. |
| Permissions | Project-wide assignments include circles added to the project later. NOC Lead gets View/Export on new datasets automatically. CI users without assignments see nothing. |
| RCA edit rules | Register forbids editing imported RCA facts; the Data Panel allows it (recorded as events; a later re-import shows them as conflicts). |
| Data Panel | Saves are limited to 500 rows; the browser Back button is not intercepted by the unsaved-changes guard (links and reload are); each save becomes the "latest import", so the dashboard source label shows "Data Panel edit". |
| Operations | The backend must be started separately (`start_backend.bat`); when it is not running the frontend shows "The reporting API could not be reached". The alert worker is another separate process. |
| Docs out of date | docs/rca.md "Current data" still describes the first import (1,819 records, 26 Oct 2026); the production database held 178,692 records at the 4 Nov 2026 backup (before that day's November RCA upload). docs/site-portfolio.md still describes Site Portfolio's legacy sources (Master workbook flags, the escalation file); the current implementation is in section 4 of this file. |
| Accounts on the dev DB | Not verified beyond what is listed: the developer database had 2 Admin accounts (one still with a temporary password) and 1 CI account without assignments on 31 Oct 2026. |
| Handle with care | `dashboard/metrics.py` (all KPIs, shared by both data layers), `rca/breakdown.py` + `taxonomy.py` (business-approved), `accounts/access.py` (security), `uptimedb/importer.py`, `sitedata/*` importers and `rca/importer.py` (data writes), migrations with data steps (`accounts.0006/0007`, `organization.0002/0003`). |
| Legacy table reset | Clearing the legacy `uptimedb` site and performance tables is a **future, separately approved** step, only after every consumer (including RCA's site validation, cycles and Site Scope) no longer reads them, with a fresh verified backup (`docs/phase3-production-readiness-audit.md`). Nothing has been cleared. |

---

## 10. Instructions for GitHub Copilot (or any AI assistant)

1. **Read before writing.** Inspect the relevant models, services, views, serializers, frontend page, `services/api.ts` and existing tests before changing anything. Check this file and the matching `docs/` guide.
2. **Verify, don't assume:** field names, stored values (e.g. "Yes"/"YES"), API response shapes and existing calculations. Query the data read-only if needed. Never reset, flush or rewrite the database.
3. **Make minimal, incremental changes** that follow the existing structure. Extend `catalog.py`, `access.py`, `metrics.py`, `rca/services.filtered`, `masterdata/datasets.py` + `editors.py` instead of writing parallel logic.
4. **Security in the backend:** every new endpoint needs a permission class (`IsAdminRole`, `Can(module, action)` or explicit checks) and project/circle scoping via `access.pairs_for` / `pairs_q`. Update the frontend guards (`context/auth.ts`) only for display.
5. **No mock data in business workflows;** tests use isolated fixtures (SQLite test DB, `tests/auth_helpers.portal_user`, `tests/workbook_factory`).
6. **Do not modify or delete business data** unless the user explicitly asks; data changes go through existing import/edit paths that keep provenance.
7. **Test after every significant change:**
   - Run the affected backend test modules, e.g. `manage.py test tests.test_rca` with `DB_ENGINE=django.db.backends.sqlite3`.
   - Run `npx vitest run <file>`, then `tsc`, `lint` and `build`.
   - Do not report success without running them; quote the 2 known reconciliation failures if they appear.
8. **Migrations:** additive and reversible; data migrations must not broaden anyone's access; run `makemigrations --check`. Show the plan (`migrate --plan`) before applying to PostgreSQL.
9. **Ask when requirements are ambiguous** (business rules, mappings, which O&M source, thresholds). Record open questions in docs instead of guessing.
10. **Conventions:**
    - Backend: Django REST function views with `@api_view`; JSON errors `{error, details}`; docstrings explain the business rule; one module per concern.
    - Frontend: `useApiQuery(key, fetcher)` for data; filters in the URL (`useSearchParams`); shared filter components (`FilterBar`, `RcaFilterBar`, `SiteScopeField`); shadcn UI components in `components/ui`; types in `src/types`.
    - Comment density: short comments only where a business rule needs explaining.
11. **Keep docs current:** update the relevant `docs/*.md` file and this handover when behaviour changes.
