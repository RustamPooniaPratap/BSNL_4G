# Project Handover: BSNL 4G Saturation & LWE Reporting Portal

State as of **2 Nov 2026**. Repository at commit `c6de8f6` ("rca filters updated"); the working tree had no uncommitted changes when this was written.

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
│   │   ├── uptimedb/        PostgreSQL uptime data: sites, daily/monthly performance, escalation matrix, imports,
│   │   │                    raw CSV upload (raw/), CSV arrival tracker, data-source switch
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
│       ├── services/api.ts  every API call
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
| `/api/dashboard/` | dashboard metrics and exports |
| `/api/rca/` | RCA |
| `/api/organization/` | organization |
| `/api/master-data/` | Data Panel |
| `/api/alerts/` | alerts |

### Database configuration

- PostgreSQL via `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` in `backend/.env`. `settings.py` refuses to start without a valid `DB_ENGINE` (no silent fallback).
- Developer machine: database `4G-DB`, host 127.0.0.1, port 5432 (values seen in the health check; credentials are not documented here).
- `backend/db.sqlite3` exists in the folder; it is used only if `DB_ENGINE` is set to SQLite. Not verified what it contains; do not rely on it.

### Authentication and authorization (summary; details in section 5)

- Django sessions, no public registration, Admin-provisioned accounts with temporary passwords, login throttling, idle timeout, optional "remember me", development-only login bypass (`DEV_LOGIN_BYPASS`, DEBUG and local requests only).
- Authorization is enforced in the API: DRF default permission `IsPortalUser`, plus `IsAdminRole`, `Can(module, action)` and data restriction by project/circle (`apps/accounts/access.py`). The frontend guards (`RequireAdmin`, `RequirePage`, `context/auth.ts`) only decide what to show.

---

## 2. Implemented features

Status legend: **Complete** = implemented, tested, in use; **Partial** = works with stated gaps; **Pending** = not implemented.

| Feature | Route(s) | What it does / how | Key files | Status |
|---|---|---|---|---|
| Overview dashboard | `/`, `/?report_type=…` | KPI cards (MTD uptime, Not meeting SLA, Unique sites down, Below 60% MTD, Outage minutes Day/MTD/Month), trends, breakdowns, alerts. Filters: project, circle, site scope, reporting date, trend period. | `pages/DashboardPage.tsx`, `components/dashboard/*`, `apps/dashboard/views.py`, `metrics.py` | Complete |
| Threshold Analysis | `/thresholds`, `/thresholds/buckets` | Uptime buckets by period with comparisons; Uptime Buckets & Site Details table (also opened from CI & IE Performance with a person filter, see below). | `ThresholdPage.tsx`, `BucketsSitesPage.tsx`, `metrics.threshold_analysis` | Complete |
| Site Portfolio | `/portfolio` | Portfolio KPIs per project/circle. | `PortfolioPage.tsx`, `lib/portfolio.ts`, docs/site-portfolio.md | Complete |
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

### Migrations (all applied on the developer PostgreSQL as of this writing)

| App | Migrations |
|---|---|
| accounts | 0001_initial, 0002_portal_roles, 0003_noc_lead_role, 0004_account_circles, 0005_rca_consolidated_group, 0006_access_control, 0007_data_panel_permissions |
| organization | 0001_initial, 0002_initial_organization (seeds projects, circles, associations, aliases), 0003_access_moved_to_assignments (drops `UserCircleAccess` after copying) |
| uptimedb | 0001_initial, 0002_escalation_matrix, 0003_escalation_village_code, 0004_raw_daily_uploads, 0005_data_panel_batch_kind (choices only) |
| rca | 0001_initial, 0002_reporting_cycles, 0003_upload_details, 0004_incident_occurrence, 0005_upload_types |
| alerts | 0001_initial |
| dashboard, common | no models |

### Business data tables (actual operational data)

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

---

## 4. Business logic and calculations

Detailed rules: [docs/business-rules.md](docs/business-rules.md) (dashboard), [docs/rca.md](docs/rca.md) (RCA). Main implementation: `backend/apps/dashboard/metrics.py`.

### Reporting basics

- **Projects (report types):** `4G Saturation` (written "4G Satu." in the workbook) and `LWE`. A site belongs to one project and circle; **4G and LWE site identities are kept separate**. MP under 4G and MP under LWE are different networks.
- **Dataset:** the dashboard reads one in-memory dataset (`dashboard/workbook.py: Dataset`) built from the **active source**: the Master workbook (Excel) or PostgreSQL (`uptimedb/datasource.py`). The source is switched explicitly by an Admin (`AppSetting`). Without the setting the default is Excel; the developer machine is set to PostgreSQL. The database dataset is cached and rebuilt when a newer committed import batch exists.
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

### Partial / in progress

- Raw daily CSV upload for **LWE**: validated, but no rows imported until the LWE site-ID mapping is supplied.
- Add Row / Add Site pages: browser-only validation (superseded in practice by Data Panel editing).
- Alert e-mail: real SMTP / Microsoft 365 sending not verified; needs company IT approval (SMTP AUTH or relay, sender mailbox, firewall).

### Pending / not implemented

- PDF exports (none exist; only Excel/CSV).
- "O&M Start = No" as a **dashboard** site-scope option, and multi-circle selection in dashboard filters (requested in the USD task; not added because it would change every page using the filter).
- OAuth (Microsoft Graph) mail sending.
- A "closed / inactive" site status (not present in the data).

### Last known development task

The **RCA Site Scope** filter (All / O&M Start / O&M Not Started Sites) across the RCA Register, all RCA Summary tabs and RCA Submissions. Finished and committed. Before that came the Data Panel editing framework.

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
| `backend/.env` (via `settings.py`) | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `LOG_LEVEL`, `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DATA_DIR`, `WORKBOOK_STORE_DIR`, `MASTER_WORKBOOK_PATH`, `MAX_WORKBOOK_BYTES`, `RAW_UPLOAD_DIR`, `MAX_UPLOAD_BYTES`, `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_TIMEOUT`, `SESSION_IDLE_MINUTES`, `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE`, `REMEMBER_ME_DAYS`, `LOGIN_RATE_PER_USER`, `LOGIN_RATE_PER_IP`, `AUDIT_LOG_FILE`, `DEV_LOGIN_BYPASS`, `DEV_LOGIN_USER`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `TRUST_X_FORWARDED_PROTO` |
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

Latest results (2 Nov 2026):

- Backend: 476 tests, 474 pass. The 2 failures are the known `test_reconciliation` tests, which read the live October workbook (section 9).
- Frontend: 297 / 297 pass; type-check, lint and build clean.

### Deployment

No production deployment configuration (Docker, CI pipeline, web server config) exists in the repository. Production security settings are applied when `DEBUG=False` (see docs/security.md); the alert worker must run as a separate long-running process (docs/alerts.md).

---

## 9. Known issues and risks

| Area | Issue |
|---|---|
| Tests | `tests/test_reconciliation.py`: 2 tests fail because they read the live October workbook, whose dates moved on (e.g. expected 14 Oct, now later). Not a regression. |
| Performance | The RCA Summary request takes about 11–16 s on the full data (~177,690 RCA records), mostly the existing aggregations; the Site Scope adds little. |
| RCA data quality | 2 RCA records have no Site Master site: 4G AP `dhssghks` (28 Oct), LWE CG `LWEBH0269` (26 Oct). 67 RCA records of 3 LWE MP sites say O&M Start "Yes" on the RCA row but "No" in Site Master (Site Scope follows Site Master). |
| Raw uploads | LWE raw CSV rows are not imported (no ID mapping); open question 8 in docs/business-rules.md. |
| Excel runtime reads | `dashboard/activity.py` (conversion activity) reads `Data/reference/*Escalation Matrix*.xlsx`; `dashboard/reference.py` (O&M heads) reads `Data/reference/*first page*.xlsx`; the Excel data source reads the uploaded Master workbook. These are the remaining runtime file dependencies. |
| Dashboard filters | No "O&M Start = No" dashboard scope and no multi-circle selection. "All sites" scope still excludes non-On-Air sites from USD by design. |
| Permissions | Project-wide assignments include circles added to the project later. NOC Lead gets View/Export on new datasets automatically. CI users without assignments see nothing. |
| RCA edit rules | Register forbids editing imported RCA facts; the Data Panel allows it (recorded as events; a later re-import shows them as conflicts). |
| Data Panel | Saves are limited to 500 rows; the browser Back button is not intercepted by the unsaved-changes guard (links and reload are); each save becomes the "latest import", so the dashboard source label shows "Data Panel edit". |
| Operations | The backend must be started separately (`start_backend.bat`); when it is not running the frontend shows "The reporting API could not be reached". The alert worker is another separate process. |
| Docs out of date | docs/rca.md "Current data" still describes the first import (1,819 records, 26 Oct 2026); the database now holds about 177,690 records (October 2026). |
| Accounts on the dev DB | Not verified beyond what is listed: the developer database had 2 Admin accounts (one still with a temporary password) and 1 CI account without assignments on 31 Oct 2026. |
| Handle with care | `dashboard/metrics.py` (all KPIs), `rca/breakdown.py` + `taxonomy.py` (business-approved), `accounts/access.py` (security), `uptimedb/importer.py` and `rca/importer.py` (data writes), migrations with data steps (`accounts.0006/0007`, `organization.0002/0003`). |

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
