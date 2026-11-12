# Comprehensive Project Audit: BSNL 4G Saturation & LWE Reporting Portal

| | |
|---|---|
| Audit date | 11 Nov 2026 |
| Code baseline | `main` at `9a69ada` (code identical to `18b6a63`; `9a69ada` changes only `.vscode/settings.json`). Working tree clean. |
| Type | Analysis only. No source, schema, data, dependency or environment file was changed. |
| Evidence tags | **[C]** confirmed by reading code or running a check. **[I]** inferred; needs runtime or production verification. |

---

## 1. Executive Summary

The portal is a substantial and generally well-engineered internal application:
- Django 5.1 / DRF on PostgreSQL, with a React 19 / TypeScript frontend.
- About 51,500 lines of application code and about 16,500 lines of tests.
- Authentication and server-side authorization are solid:
  - Default-deny API.
  - Forced password change enforced on the server.
  - Project/circle scoping enforced in the backend.
  - No sign-in bypass.
  - No SQL injection surface found.
  - No XSS sinks found.

**The application is in the middle of an incomplete data-layer migration, and the split is now causing silent, user-visible data errors.**

The dashboards have been moved to the new `sitedata` layer:
- Overview, 4G, LWE, Thresholds, Team Performance, All KPI's and Site Portfolio.
- Portal Excel downloads.

Several production workflows still write to or read from the legacy `uptimedb` tables:
- **The daily raw CSV upload page writes only to legacy tables.** No dashboard reads them. The page still tells users "Database-backed dashboard pages now include them" (P0).
- **The Data Panel views and edits legacy tables only.** Its edits change nothing on the dashboards (P1).
- **Several other features still read legacy data:**
  - the CSV Arrival Tracker and its reminder emails;
  - scheduled report emails;
  - the RCA breakdown, overview, site scope and import validation;
  - the "data source" switch.
  - Users therefore see different numbers for the same KPI on different screens (P1).
- **The new layer has no reachable path for raw CNMC CSV import, authorized corrections or monthly recalculation.** These importers exist only in tests and out-of-repo scripts (P1).

Other serious findings:
- The Team Performance **Hierarchy pages show mock data** in production navigation. The mock data includes names, employee codes and phone numbers.
- The hierarchy admin tabs call APIs whose migration (`organization.0004`) is reportedly unapplied in production.
- The local configuration is a development configuration: `DEBUG=True`, an insecure-prefixed secret key, the PostgreSQL superuser account, and no production deployment setup.
- Several business-rule inconsistencies:
  - three different USD/NSLA definitions;
  - partial weeks are shown as values on some pages but not others;
  - source precedence depends on upload order in one edge case;
  - a floating-point boundary bug at exactly 98.5%.

**Overall health:** good code quality and security fundamentals, but **data consistency is not production-safe** until the migration is completed or the remaining legacy paths are clearly fenced off.

**Issue counts (master register, section 17):** P0: 1, P1: 11, P2: 30, P3: 25. Total 67.

---

## 2. Project Overview

**Purpose.** BSNL's 4G Saturation and LWE (Left Wing Extremism) mobile-site programmes are run from a consolidated Excel "Master workbook". This portal replaces that workbook. It does the following:
- Imports the Consolidation Matrix, the Uptime Master and the daily CNMC availability dumps.
- Computes daily, MTD, weekly and monthly uptime/outage per project, circle and site.
- Assigns sites to uptime buckets: <60, 60–90, 90–97, 97–98.5 and ≥98.5%.
- Counts NSLA (below 98.5%) and USD (unique sites down) sites.
- Tracks CI/IE field performance.
- Records RCA (root cause analysis) of outages.
- Sends automated emails.

**Users and roles** (`backend/apps/accounts/roles.py`, `catalog.py`, `access.py`):

| Role | Scope |
|---|---|
| Admin / superuser | Everything, including all admin-only modules |
| NOC Lead | Every project/circle; CI rights plus RCA workbook uploads and Data Panel view/export |
| CI | Only the project/circle pairs granted by `AccessAssignment` rows with the CI role |
| `member` ("assigned access only") | Documented as assignment-only. **[C] Cannot sign in at all:** `LoginView` rejects users whose `role_of()` is None (`accounts/views.py:130`). |

There is no public registration. Accounts are created by an Admin with a temporary password.

**Documentation present:**
- `PROJECT_HANDOVER.md` (the primary reference).
- `README.md`: stale and encoding-damaged.
- `docs/*.md` (20 files).
- `backend/apps/sitedata/README.md`, `apps/allkpis/README.md`, `frontend/src/features/all-kpis/README.md`.

**Requested files that do not exist [C]:** `CLAUDE.md`, `PROJECT_CONTEXT.md`, `PROJECT_STATUS.md`, `DATABASE_ARCHITECTURE.md`, `FEATURE_INVENTORY.md`, `MIGRATION_TRACKER.md`.

---

## 3. Current Architecture

```
React 19 SPA (Vite)            Django 5.1 + DRF (session auth + CSRF)                PostgreSQL "4G-DB"
frontend/src/services/api.ts → /api/auth, /api/dashboard, /api/all-kpis,          →  sitedata_*   (NEW: matrix sites,
  useApiQuery (abortable)        /api/site-portfolio, /api/sitedata/*  ── reads ──→    daily, monthly, uploads)
  guards: context/auth.ts        /api/rca, /api/master-data, /api/arrival-tracker,
                                 /api/raw-uploads, /api/data-source ── reads/writes →  uptimedb_*   (LEGACY)
                                 /api/organization, /api/alerts                     →  rca_*, accounts_*, organization_*, alerts_*
                                                                                       + Excel files in Data/ (runtime reads)
```

**Backend apps.** Sizes are non-test, non-migration lines:

| App | Lines | Role |
|---|---|---|
| dashboard | 4,130 | `metrics.py` KPI engine (1,365 lines, shared by both layers), `workbook.py` (`Dataset` type and Excel parser), upload/store, `report_export.py`, crosscheck, Excel runtime readers (`activity.py`, `reference.py`) |
| rca | 4,044 | Register, importer/parser, cycles, summary, breakdown, overview, taxonomy |
| organization | 3,436 | Organization master (~600) plus the dormant Team Performance Hierarchy (~2,580) |
| sitedata | 3,426 | New data layer: matrix, uptime_master, rawcsv, bandmap, daily (precedence), calculations, dataset, portfolio, dashboard_source, unmatched |
| uptimedb | 3,281 | Legacy tables, Master workbook importer, escalation, day-wise, raw CSV upload, arrival tracker, data-source switch |
| accounts | 1,622 | Authentication, roles, permission catalogue, access resolver, audit |
| alerts | 1,329 | SMTP account (Fernet), automations, queue/worker (`run_alerts`) |
| masterdata | 948 | Data Panel (dataset registry, editing) |
| common | 503 | Health check, legacy raw-file upload and email |
| allkpis | 491 | All KPI's read APIs |

**Frontend.** 150 source files, 27,932 lines:
- 46 portal routes plus 2 auth routes; 31 lazy-loaded pages.
- Contexts: Auth, Workbook, Tracking, PageHeader.
- Service layer: `services/api.ts` (167 exports).
- UI: shadcn/radix components; charts with Recharts.

**API surface.** 157 registered URL patterns [C, introspected]:
- 143 are called by the frontend; 1 is called by `health_log.bat`.
- 13 are never called.
- No frontend call targets a missing route.

**The documentation is out of date on the architecture.** See section 16.

---

## 4. Complete Application Workflow

1. **Organization setup (Admin).** An Admin defines projects, circles, project-circle associations and circle aliases (`/admin/organization`). Users are created, and roles and assignments granted (`/admin/users`).
2. **Master data into the new layer (Admin, `/workbook` "Data Source" page):**
   - **Consolidation Matrix:** preview → commit (`/api/sitedata/matrix/*` → `sitedata/matrix.py`). Writes `sitedata.Site`, identifiers and conflicts.
   - **Up-Time Report / Day-Wise Outage:** preview → commit (`/api/sitedata/uptime/*` → `sitedata/uptime_master.py`). Writes `DailySitePerformance` at precedence rank 2.
   - **Unmatched sites:** report, map an alternate identifier, then process pending rows (`/api/sitedata/uptime/unmatched/*`).
   - **LWE Band ID mapping:** management command `import_lwe_mapping` only.
3. **Daily raw CNMC CSV (CI or uploader, `/data/upload-csv`).** Validate → preview → commit into **legacy** `uptimedb.SiteDailyPerformance` (`uptimedb/raw/service.py:286`). **[C] This does not reach the dashboards.** LWE rows are always rejected there (`LweResolver`).
4. **Calculation and display.** `sitedata/dashboard_source.dataset()` builds an in-memory `Dataset` from the new tables:
   - Sites come from the matrix.
   - On-Air and O&M Start effective dates come from the matrix.
   - The dataset is cached per process (`sitedata/portfolio.py`).
   - `dashboard/metrics.py` computes every KPI.
   - Every response is restricted to the user's (project, circle) pairs (`dashboard/scope.restrict`).
5. **RCA.** Circle and consolidated RCA workbooks are uploaded, previewed and committed (`rca/importer.py`). Then:
   - The register supports a follow-up workflow.
   - Summary and breakdown pages are available; these **read legacy site data** (`current_dataset()`).
   - Reporting cycles and submissions are tracked.
6. **Monitoring and notifications:**
   - The CSV Arrival Tracker (legacy coverage).
   - The alert worker `run_alerts` sends CSV reminders, RCA reminders and uptime reports (legacy/Excel dataset).
7. **Exports:**
   - Daily Uptime and Full Consolidated `.xlsx` from the dashboard (new layer).
   - Data Panel CSV/XLSX (legacy).
   - RCA period workbooks.
   - Emailed report attachments (legacy/Excel).

---

## 5. Frontend Audit

**Strengths [C]:**
- No `any` types, no `@ts-ignore`, no `dangerouslySetInnerHTML`.
- The CSRF token is held in memory only, and nothing is written to localStorage.
- All context values are memoised.
- Pages are split by route.
- Every portal route is behind `RequireAuth`.
- Admin pages are behind `RequireAdmin`, and the backend enforces the same rules independently.

**Findings:**

| # | Pri | Finding | Evidence |
|---|---|---|---|
| F-1 | P1 | **Team Performance Hierarchy pages use mock data only.** They are linked from the sidebar ("Performance Hierarchy"). The bundle includes names, employee codes and 10-digit phone numbers (17 contacts). Filters only change subtitles. A hardcoded `2026-10` / "Oct-26 MTD" appears in five pages. `aggregateKpis` returns 0 for no data, against the "missing ≠ 0" rule. The pages show an infinite skeleton on error. This violates handover rules §7.3 and §10.5. | `services/hierarchyMockData.ts` (935 lines; `IS_DEMO_DATA` at :11, `MOCK_CIRCLES` at :17-24); `pages/hierarchy/*` (5 pages, 1,545 lines); `Sidebar.tsx:62`; `App.tsx:64-68` |
| F-2 | P1 | **`HierarchyTabs.tsx`** (1,410 lines, 61 `useState`): load errors are caught with `console.error` and rendered as empty "No … found" lists, and native `alert()` is used. It is effectively untested (only tab labels are asserted). It calls `/api/organization/hierarchy/*`, which depends on the reportedly unapplied `organization.0004` **[I]**. | `components/organization/HierarchyTabs.tsx:67,311,350,639,864,975,987,1193` (`console.error`); `:1009,1024,1252,1255` (`alert`) |
| F-3 | P1 | **Upload CSV success banner is false.** It says "Database-backed dashboard pages now include them", but the dashboards read `sitedata`. | `pages/data/UploadCsvPage.tsx:300` |
| F-4 | P2 | **CSV-arrival contacts, follow-ups, deadlines and Portfolio notes live in memory only.** A refresh loses them, and the "late" status differs per browser. | `context/TrackingProvider.tsx:5-11`, `lib/tracking.ts:116-164` |
| F-5 | P2 | **Add Row / Add Site validate in the browser only and save nothing, but sit in navigation.** The UI gates them on `csv_upload.upload` while their API calls need `dashboard.view`, so upload-only roles get 403s. They page through a whole circle's records in the browser. | `auth.ts:35`; `pages/data/AddRowPage.tsx`, `AddSitePage.tsx`; `hooks/useSiteRegistry.ts:6-39`; `components/data/DataEntry.tsx:45-56` |
| F-6 | P2 | **`canOpen` allows any unknown path (default-allow).** | `context/auth.ts:59-60` |
| F-7 | P2 | **Business rules duplicated from the backend:** bucket keys and labels, threshold colours (98.5/97/90/60), week definitions, the 98.5 SLA line. `SiteDetailSheet` uses a different colour scale. | `components/dashboard/constants.ts:4-12,47-49`; `SiteDetailSheet.tsx:21`; `lib/periods.ts:38`; `features/all-kpis/status.ts:7` |
| F-8 | P2 | **The API base URL silently falls back to `http://localhost:8000/api` in production builds.** | `services/api.ts:50` |
| F-9 | P2 | **Weak tooling:**<br>• lint enables only 2 rules (no `exhaustive-deps`);<br>• `strict` is not set explicitly in `tsconfig.app.json`;<br>• no unused-export check;<br>• about 165 non-null assertions (48 in `AllKpisPage.tsx`). | `.oxlintrc.json`; `tsconfig.app.json` |
| F-10 | P2 | **No contract tests.** 27 test files stub `services/api` functions with hand-written fixtures, so backend shape drift is undetected. | `src/test/fixtures.ts` |
| F-11 | P2 | **Oversized pages:** `CsvArrivalPage.tsx` (854 lines, one ~480-line component) and `ThresholdPage.tsx` (714). | — |
| F-12 | P3 | **Downloads bypass the 401 and error handling of `request()`:**<br>• XHR workbook upload and `downloadReport` raw fetch;<br>• 8 `<a href>` download URL builders show raw JSON on 401/403. | `api.ts:179-200,393-406`; `matrixIssuesUrl` etc. |
| F-13 | P3 | **Duplicate UI:**<br>• six KPI-card implementations;<br>• two `Field` components;<br>• sorting implemented in 7 places;<br>• 4 pagers;<br>• two formatters ('—' vs 'Not available');<br>• two `formatDate`;<br>• the "4G Saturation→4G" short-label helper re-implemented 14 times. | see section 11 |
| F-14 | P3 | **`Unauthorized` always links to `/portfolio`**, even for roles that cannot open it. **The All KPI's RCA panel needs `rca_summary.view`**, which the page gate does not check. | `Guards.tsx:44-57`; `auth.ts:34` |
| F-15 | P3 | **No request caching:** `fetchFilterOptions` is re-fetched on every page. **No `build` block in `vite.config.ts`** (no chunking or visualizer). | — |

Frontend tests: 40 files, 6,311 lines, 325 cases. **They were not run** (see section 23).

---

## 6. Backend Audit

**Strengths [C]:**
- Consistent `{error, details}` envelope (`apps/common/exceptions.py`), with no stack traces leaked.
- ORM only: no `cursor.execute`, `.raw()` or `.extra()`.
- Allow-listed filter and sort fields.
- Preview → commit importers with checksum re-verification (sitedata).
- Business rules centralised in `sitedata/rules.py` and `dashboard/metrics.py`.

**Findings:**

| # | Pri | Finding | Evidence |
|---|---|---|---|
| B-1 | P1 | **New-layer pipeline has no entry points.** The following have no view and no management command, and are referenced only by `tests/test_sitedata.py`:<br>• `sitedata/rawcsv.py` (raw 4G/LWE CSV, 192 lines);<br>• `sitedata/calculations.py` (monthly calculation and finalization);<br>• `sitedata/daily.correct()` (authorized corrections).<br>Production September/October data came from out-of-repo scripts. | grep: no callers outside the module and tests [C] |
| B-2 | P1 | **Test fidelity.** `tests/runner.py:33-49` patches `dashboard_source.load` to fall back to the Excel workbook dataset whenever no `sitedata.Site` exists. As a result, most dashboard API, permission and calculation tests exercise the Excel path, not the production path, and runtime-inert code looks tested (`crosscheck.py`). | `backend/tests/runner.py:33-49` |
| B-3 | P2 | **Duplicated rules:**<br>• `site_key` normalisation ×5 identical implementations, plus 2 non-collapsing variants;<br>• `MINUTES_PER_DAY` ×6;<br>• NSLA threshold ×3 with different semantics;<br>• `WEEKS` ×2;<br>• `canonical_circle` ×2 with *different* behaviour on unknown codes;<br>• hardcoded `CIRCLE_ALIASES`;<br>• `may_use` ×2;<br>• inline discard ×2;<br>• 3 dataset caches;<br>• 2 email stacks. | section 11 |
| B-4 | P2 | **Layer coupling.** The new layer imports private helpers of legacy parsers (`escalation._header/_text/_date/_coordinate`, `raw_parser._decode`), and the core `Dataset` type lives in an Excel-parsing module. These legacy modules therefore cannot be removed with the legacy tables. | `sitedata/matrix.py:39-40`, `rawcsv.py:39-40`, `dataset.py:28` |
| B-5 | P2 | **RCA summary takes 11–16 s:**<br>• about 30 separate aggregate queries over the filtered queryset;<br>• a legacy `current_dataset()` build;<br>• `site_metrics`;<br>• a large `site_key__in` list. | `rca/services.py:431-700` |
| B-6 | P2 | **Per-row writes inside commits:**<br>• `matrix.commit`: about 6.7k site UPDATEs and about 17k identifier DELETEs;<br>• `uptime_master.commit`: per-site UPDATE;<br>• `rca/importer.commit`: per-record save plus an event;<br>• `rca/views.py:459` loops over days × cycles. | `sitedata/matrix.py:430-450`; `uptime_master.py:370-371`; `rca/importer.py:314-340` |
| B-7 | P2 | **Cache-key cost.** `portfolio._key` runs 5 queries, including `COUNT(*)` over about 410k daily rows, on every load. `load()` is called about twice per dashboard request. A rebuild reloads the full history ×3 variants under a global lock. | `sitedata/portfolio.py:39-42,69-78`; `dataset.py:130-134` |
| B-8 | P2 | **`rca/services.py` formatting damage:** 429 of 807 lines are blank (lines ~300–650 double-spaced). | [C] counted |
| B-9 | P3 | **Problematic exception handling:**<br>• `dashboard/views.py:382`: silent fallback, no logging;<br>• `rca/services.py:437`: INFO log, returns None, which masks DB errors;<br>• `uptimedb/importer.py:197` and `escalation.py:310`: echo `type(exc): exc` to clients.<br>Failed sitedata previews omit `details` (`matrix_views.py:79`, `uptime_views.py:64`). | — |
| B-10 | P3 | **Uploads:** sitedata `MAX_BYTES` is hardcoded at 50 MB instead of coming from settings. Staged and raw uploads are never cleaned up. Pandas loads whole workbooks, including just to preview 5 rows (`common/views.py:143`). | — |
| B-11 | P3 | **Code hygiene:** 34 unused imports (AST check), 2 empty `tests.py` stubs, merged comments on `config/urls.py:31`, deprecated `CheckConstraint(check=)` in `organization/models.py`. | — |

**Management commands [C]:**

| Command | Status |
|---|---|
| `set_role`, `run_alerts`, `rca_bucketization`, `import_lwe_mapping` | Active |
| `import_uptime`, `import_daywise`, `import_escalation` | Write **legacy** tables; now the only runtime path to `uptimedb/importer.py` |
| `build_report_template` | One-off tool |
| `hierarchy_reconciliation_dry_run` | 286 lines, **undocumented**; writes to hierarchy tables that may not exist |

---

## 7. Database Audit

### 7.1 Models and constraints (key points) [C]

- **`sitedata`** is well constrained:
  - `DailySitePerformance`: UNIQUE (site, report_date, technology); CHECK 0 ≤ availability ≤ 100; CHECK 0 ≤ outage ≤ 1440 (`sitedata/models.py:287-292`).
  - `MonthlySitePerformance`: partial unique `is_current`; CHECK reporting_days ≤ calendar_days.
  - `Site`: CHECK on scope/technology.
  - Every FK is PROTECT.
  - `DailyPerformanceEvent` is append-only **in the ORM only**; the database does not enforce it.
- **Gap:** no DB constraint that `daily.technology = site.technology`. Only the importers enforce it.
- **Legacy `uptimedb`:** `SiteDailyPerformance` has **no CHECK on outage**, so the legacy table accepts values above 1440. The site FK is CASCADE.
- **Redundancy:**
  - three site masters (`UptimeSite`, `EscalationSite`, `sitedata.Site`);
  - two daily tables;
  - two monthly tables;
  - three upload-batch tables.
- **Unused data:**
  - `MonthlySitePerformance` categories `om_start` and `on_air` are written but never read;
  - `daily_derived` is used only as a fallback;
  - `UploadBatch.Kind.RAW_CSV_4G/LWE` are never produced by reachable code.

### 7.2 Migrations

- `makemigrations --check --dry-run`: **No changes detected** (run on SQLite) [C].
- **`organization.0004_team_performance_hierarchy`** [C]:
  - creates `SitePersonnelAssignment.site` → `uptimedb.UptimeSite` **ON DELETE CASCADE** (`organization/models.py:648-653`);
  - is reportedly **unapplied in production** [I; handover §3];
  - **a plain `manage.py migrate` would apply it.** That creates a CASCADE dependency on a table scheduled for retirement.
  - **P1:** re-target the FK (to `sitedata.Site`, PROTECT) before any migrate, or migrate only named apps.
- **`sitedata.0002_alternate_site_identifier`** [C]: changes `choices` only, so no SQL. Its production application is unverified.

### 7.3 SQLite vs PostgreSQL (tests run only on SQLite)

| Item | Risk |
|---|---|
| `select_for_update` (daily.correct, unmatched.process_pending, masterdata editing, hierarchy services, rca cycles, alerts engine) | No-op on SQLite, so **no locking behaviour is tested** |
| **Importer commit race** [C] (P2) | In `uptime_master.commit`, `matrix.commit`, `bandmap.commit` and `rawcsv.commit`, `require_previewed` and `analyse` run outside the transaction and the batch is not locked. On PostgreSQL READ COMMITTED, a double-submit can commit twice: duplicate events and revision +2. SQLite serialises writers and hides this. |
| `max_length` not enforced on SQLite | `unmatched.map_alternate` stores an unchecked value into an 80-character field, which gives a 500 on PostgreSQL (P3) |
| `bulk_create(ignore_conflicts=True)` (`bandmap.py:230`) | SQLite's `INSERT OR IGNORE` also swallows NOT NULL and CHECK errors; PostgreSQL does not (P3) |
| JSONField `icontains` (`alerts/views.py:416`) | Non-ASCII search differs (P3) |
| Raw SQL / `distinct(fields)` | None found |

### 7.4 Migration matrix: legacy (L) vs new (S) [C]

| Module | Reads | Writes | Evidence |
|---|---|---|---|
| Dashboard (Overview/4G/LWE), Thresholds, Buckets, records, Teams/CI-IE/Top, period, monthly | **S** | – | `dashboard/views.py:23-34` → `sitedata/dashboard_source.py` |
| Portal Excel exports (Daily, Consolidated) | **S** | – | `dashboard/views.py:425-457`; `report_export.py:195-216` |
| All KPI's | **S** + RCA | – | `allkpis/services.py:66-72` |
| Site Portfolio | **S** | – | `sitedata/portfolio_views.py` |
| Dashboard `/conversion-activity/` (unused by UI) | **Excel file** | – | `dashboard/activity.py` |
| O&M heads (Portfolio) | **Excel file** `Data/reference/*first page*.xlsx` | – | `dashboard/reference.py` |
| Matrix import, Up-Time import, unmatched map/process (UI) | S | **S** | `sitedata/matrix_views.py`, `uptime_views.py` |
| **Raw CSV upload page** | L | **L** | `uptimedb/raw/service.py:286-300` |
| **Data Panel** | **L** + RCA | **L** + RCA | `masterdata/datasets.py:22,71-99`; `editors.py` |
| **CSV Arrival Tracker and CSV reminders** | **L** | – | `uptimedb/arrivals.py:76-138`; `alerts/engine.py:147-152` |
| **Emailed uptime reports** | **L or Excel** (`current_dataset`) | – | `alerts/reports.py:61-77` |
| **RCA breakdown / overview / summary population** | **L** (`current_dataset`, EscalationSite) | – | `rca/breakdown.py:106-109`; `overview.py:84,154`; `services.py:431-433` |
| **RCA Site Scope** | **L** (`SiteMonthlyPerformance.om_start`) | – | `rca/sitescope.py:37-44` |
| **RCA import validation, RCA cycles** | **L** (`UptimeSite`) | rca | `rca/importer.py:122-124`; `cycles.py:105-108` |
| Data-source switch (`PUT /api/data-source/`) | – | L (`AppSetting`) | `uptimedb/views.py:142-160` |
| Hierarchy services | **L** (`UptimeSite`) | org 0004 tables | `organization/hierarchy_services.py:26,213` |
| Organization usage counts | **L** + RCA | – | `organization/services.py:181-202` |
| Legacy reminder validation (`/api/email/*`) | **L or Excel** | – | `common/views.py:183-200` |

**Read/write splits a user will observe** (details in section 8):
1. A raw CSV upload never appears on any dashboard.
2. Data Panel edits have no dashboard effect.
3. Emailed reports differ from downloaded reports.
4. The arrival tracker and reminders follow legacy coverage.
5. The RCA USD/NSLA/Total and O&M scope differ from the dashboard.
6. RCA import rejects matrix-only sites.
7. The data-source switch affects only RCA, emails and reminders.

### 7.5 Can any legacy table be retired? **No [C].**

| Table | Still used by |
|---|---|
| `uptimedb_uptimesite` | `datasource._build`, RCA import/cycles, raw upload, arrivals, Data Panel, hierarchy (+0004 FK), org usage, legacy importer |
| `uptimedb_sitedailyperformance` | `datasource._build`, arrivals, raw upload (writes), Data Panel (r/w), org usage, legacy importers |
| `uptimedb_sitemonthlyperformance` | `datasource._build`, **RCA Site Scope on every RCA page**, Data Panel, org usage |
| `uptimedb_escalationsite` / `_escalationimportbatch` | RCA overview NE map, Data Panel, `import_escalation`. **Closest to retirable** once RCA overview uses the `sitedata` BAND_2100 identifiers and the Data Panel matrix dataset moves |
| `uptimedb_dataimportbatch` | PROTECT FK target; cache keys; arrivals; Data Panel batches |
| `uptimedb_appsetting` | Configuration (data source, alert heartbeat). Keep. |

Retirement requires all of the following:
1. Every consumer above migrated.
2. Reconciliation of legacy and new figures.
3. `organization.0004` re-targeted.
4. A fresh, **restore-tested** backup.

`docs/production-backup-report-20261104.md` records backups. A restore test is not evidenced in the repo. **[I]**

---

## 8. Business Logic Audit

| Rule | Status | Evidence / issue |
|---|---|---|
| Matrix authoritative for attributes and effective dates | **OK in sitedata [C]** | The Up-Time importer only compares attributes (`uptime_master.py:276-287`); dates come from the matrix (`dataset.py:113-117`). **Not true for legacy consumers** (RCA, emails, Data Panel), which use Uptime Master attributes and flags. |
| Precedence: correction 3 > Uptime Master 2 > raw CSV 1 | **Implemented, with an order-dependence bug [C] (P2)** | `daily.SOURCE_RANK` (`daily.py:180`). The duplicate test runs before the rank test (`daily.py:90-93`), and a higher-rank duplicate does not upgrade provenance. Scenario: raw A is stored; Uptime #1 sends A (duplicate, stays rank 1); Uptime #2 sends B, which *supersedes*. Without the raw file, Uptime #2 would be a *conflict*. The result depends on upload order. |
| Correction path | **Not reachable [C] (P1)** | `daily.correct()` has no endpoint. Equal-rank conflicts keep the first value, so a revised Up-Time Report can never fix a wrong value. |
| Daily key (site, date, technology); 4G and LWE distinct | **OK [C]** | UNIQUE constraint; technology checked at import |
| Missing ≠ 0 | **OK in backend [C]** | A blank creates no record; metrics are NaN-aware. **Frontend mock hierarchy returns 0** (F-1); `TeamsPage.tsx:162` defaults `share` to 0. |
| Outage 0–1440 | **OK in sitedata (DB CHECK and importer) [C]** | The legacy table has no CHECK; legacy-driven pages (RCA, emails) still include values over 1440 |
| Availability in percentage points | **OK [C]** | CHECK 0–100; `rules.availability_from_outage` |
| LWE 2100/700 deterministic, no fuzzy matching | **OK in code, unreachable [C]** | `rawcsv._resolve_lwe` (:94-139), `identifiers.split_ids` (";;" only), ambiguous IDs blocked. There is no UI or command for it. The legacy page rejects every LWE row (`uptimedb/raw/resolvers.py:73-82`). |
| No auto-created sites | **OK [C]** | Only `matrix.commit` creates sites (`matrix.py:428`) |
| Unmatched stay pending until confirmed | **Partially [C] (P2)** | Up-Time unmatched rows stay pending, then Admin maps (reason required, audited) and processes (`confirm:true`). Gaps:<br>• **no revoke/unmap** (PROTECT, no endpoint);<br>• **no circle check** on mapping or Up-Time import;<br>• **a later matrix master ID can silently take over an alternate key** (`unmatched.py:43-47`; matrix conflict check is per-kind, `matrix.py:326-347`);<br>• single-person action;<br>• raw-CSV unmatched rows have no pending mechanism. |
| Weeks 1–7 / 8–14 / 15–21 / 22–end | **Boundaries consistent [C]** | `metrics.py:48`, `rules.py:128`, `periods.ts:38` |
| Weekly values only when all days reported | **Inconsistent [C] (P2)** | Enforced: dashboard trend (`metrics.py:327-329`), trend-period KPI (`serializers.py:139-146`), thresholds (`metrics.py:531-538`).<br>**Not enforced:**<br>• Site Portfolio weekly view ("N of M days", `periods.ts:110-127`);<br>• All KPI's `granularity=week` (`allkpis/services.py:265-271`);<br>• Full Consolidated export (`report_export.py:322-327`). |
| Uptime formula (pooled, outage-weighted) | **OK, consistent [C]** | `metrics.uptime_pct`, `allkpis.aggregate`, `calculations` |
| USD / NSLA definitions | **Three definitions under the same labels [C] (P2)** | Dashboard/Portfolio: On-Air sites; NSLA = period/MTD uptime < 98.5 (`metrics.py:697-704`).<br>All KPI's: O&M Start sites; NSLA = **any single day** < 98.5 (`allkpis/services.py:152-173`).<br>RCA Breakdown: legacy On-Air ∩ O&M flags; NSLA = daily outage > 21.6 min (`rca/breakdown.py:135-162`). |
| Exactly 98.5% is not NSLA | **Float boundary bug [C] (P2)** | `1440*(1-98.5/100) = 21.60000000000002 > 21.6` [verified]. `breakdown.py:162` compares raw floats, so outage minutes *derived* from a 98.5% availability count as NSLA, contradicting the comment at `breakdown.py:159`. All KPI's rounds to 6 dp, so the pages disagree. Impact depends on whether stored minutes were derived or taken from the workbook [I]. |
| Finalized months frozen | **Not enforced [C] (P2)** | `daily.write` and `process_pending` never check `finalized_at`; finalization is unreachable anyway |
| Monthly recalculation after uploads | **Missing [C] (P2)** | No caller of `calculations.calculate_month`. The dashboard recomputes from daily rows, so the impact is limited to the stale monthly table. |
| Reporting month advance | **Can stick [C] (P2)** | Expected units are "every technology/circle that ever reported" (`dataset.py:47`). A 4G-only November load, or a unit that stops reporting, blocks month advance indefinitely. |
| On-Air definition | **Needs business confirmation [C] (P3)** | On-Air is decided by `on_air_date` only; matrix status `Site.on_air` is ignored (`dataset.py:113`) |
| Daily export date | **P3 [C]** | The Daily export accepts incomplete dates (`serializers.py:196-198`) |
| `nsla_site_keys` key form | **P3 [I]** | Built from raw `site_id`, not normalised `site_key` (`rca/breakdown.py:183`) |

---

## 9. Feature Completion Matrix

| Feature | FE | BE / API | DB layer | Data | Status | Key issues |
|---|---|---|---|---|---|---|
| Site Portfolio | `PortfolioPage.tsx`, `services/sitePortfolioApi.ts` | `/api/site-portfolio/*` (`sitedata/portfolio_views.py`) | S (+ Excel O&M heads) | Real | **Complete** | Partial weeks shown as values; O&M heads read an Excel file at runtime; "workbook monthly total" copy is false (`lib/portfolio.ts:309`) |
| 4G / LWE / Overview dashboard | `DashboardPage.tsx`, `components/dashboard/*` | `/api/dashboard/*` | S | Real | **Complete** | Reporting month can stick; no November data in new layer as of handover |
| Threshold Analysis & Buckets | `ThresholdPage.tsx`, `BucketsSitesPage.tsx` | `/api/dashboard/thresholds`, `records` | S | Real | **Complete** | — |
| Circle-wise breakdown (Portfolio / dashboard) | `CircleBreakdownTable.tsx`, `CircleComparison.tsx` | `breakdowns/` | S | Real | **Complete** | — |
| All KPI's | `features/all-kpis/*` | `/api/all-kpis/*` | S + RCA | Real | **Partially Complete** | Different USD/NSLA definitions; partial weeks; CI can see per-CI/IE KPIs (security F6); RCA ownership "Not configured" |
| Team Performance (CI/IE, top performers) | `TeamsPage`, `CiIePerformancePage`, `TopPerformersPage` | `/api/dashboard/teams*` (IsAdminRole) | S | Real | **Complete** | — |
| Team Performance **Hierarchy** pages | `pages/hierarchy/*` | none used (only filter options) | none | **Mock** | **Mock Data** | In sidebar; names/phones in bundle |
| Hierarchy admin tabs (OAs, OM assignments, personnel, conflicts, merge) | `HierarchyTabs.tsx` | `/api/organization/hierarchy/*` (17 routes) | org 0004 tables (FK → L) | Real if migrated | **Needs Verification** (likely Broken) | 0004 reportedly unapplied, so 500s, hidden as empty lists [I] |
| Matrix import | `MatrixImportPanel.tsx` | `/api/sitedata/matrix/*` | S | Real | **Complete** | Commit not locked (double-submit); per-row writes |
| Up-Time / Day-Wise import into new layer | `SitedataUptimePanel.tsx` | `/api/sitedata/uptime/*` | S | Real | **Partially Complete** | No monthly recalculation; equal-rank revisions cannot correct |
| Unmatched sites mapping | `UnmatchedSitesCard.tsx` | `/api/sitedata/uptime/unmatched/*` | S | Real | **Partially Complete** | No revoke, no circle check, takeover risk |
| LWE Band ID mapping | — | command `import_lwe_mapping` | S | Real | **Partially Complete** | No UI; commits with `user=None` |
| Raw daily CSV upload | `UploadCsvPage.tsx` | `/api/raw-uploads/*` | **writes L** | Real | **Broken** | Data never reaches dashboards; LWE always rejected; misleading success text |
| Raw CSV into new layer | — | `sitedata/rawcsv.py` (no entry point) | S | — | **Not Implemented** (code exists, unreachable) | — |
| Authorized daily corrections | — | `sitedata/daily.correct()` (no entry point) | S | — | **Not Implemented** | — |
| Monthly calculation / finalization | — | `sitedata/calculations.py` (no entry point) | S | — | **Not Implemented** | — |
| Master workbook upload / legacy DB import / data-source switch | `DatabaseImportPage.tsx`, `WorkbookPage.tsx` | `/api/dashboard/workbook`, `/api/data-source`; `/api/imports/*` unused | Excel store, L | Real | **Broken** (misleading) | Switch no longer affects dashboards but silently changes RCA, emails and reminders |
| Data Source & Quality | `DataSourcePage.tsx` | `/api/dashboard/source` | S | Real | **Partially Complete** | Calculation check always empty on sitedata (`crosscheck.py:122-133`) |
| CSV Arrival Tracker | `CsvArrivalPage.tsx` | `/api/arrival-tracker/` (IsAdminRole) | **L** | Real (stale layer) | **Partially Complete** | Coverage from legacy; contacts/deadlines in memory only |
| Add Row / Add Site | `AddRowPage.tsx`, `AddSitePage.tsx` | none (validation only) | none | n/a | **Partially Complete** (browser-only by design) | Permission mismatch; nothing saved |
| RCA Register & workflow | `RcaRegisterPage.tsx`, `components/rca/*` | `/api/rca/records*` | rca | Real | **Complete** | PATCH can move record out of scope (security F4) |
| RCA uploads (circle/consolidated) | `RcaImportPage.tsx` | `/api/rca/imports/*` | rca + **L validation** | Real | **Partially Complete** | Matrix-only sites rejected; validation on legacy site master |
| RCA Summary / Breakdown / Overview | `RcaSummaryPage.tsx`, `RcaBreakdown.tsx` | `/api/rca/summary`, `overview` | rca + **L** | Real | **Partially Complete** | USD/NSLA differ from dashboard; 11–16 s; float boundary |
| RCA Site Scope | `RcaShared.tsx` | `rca/sitescope.py` | **L** monthly flags | Real | **Needs Verification** | O&M scope may be empty for months without legacy monthly rows [I] |
| RCA Submissions / cycles | `RcaSubmissionsPage.tsx` | `/api/rca/cycles*` | rca + L | Real | **Complete** | Units from legacy site master |
| RCA cause mapping | `RcaMappingPage.tsx` (unlinked) | `/api/rca/causes*` | rca | Real | **Complete** (hidden) | — |
| Data Panel (Master Data) | `MasterDataPage.tsx`, `components/masterdata/*` | `/api/master-data/*` | **L** + RCA | Real (stale layer) | **Partially Complete** | Edits do not reach dashboards; 500-row save limit |
| Organization management | `OrganizationPage.tsx`, `MasterTabs.tsx` | `/api/organization/*` | org | Real | **Complete** | Usage counts legacy only |
| Users & Roles, Access | `UsersPage.tsx`, `components/users/*` | `/api/auth/*` | accounts | Real | **Complete** | `member` role cannot sign in |
| Authentication | `LoginPage.tsx`, `Guards.tsx` | `/api/auth/login` etc. | auth | Real | **Complete** | Throttle XFF bypass; timing enumeration |
| Alerts & email automation | `pages/alerts/*` | `/api/alerts/*`, `run_alerts` | alerts + **L/Excel** for reports | Real | **Needs Verification** | Real SMTP sending unverified; reports from legacy |
| Legacy email reminders | `CsvArrivalPage.tsx` | `/api/email/*` | L/Excel | Real | **Partially Complete** | Second email stack |
| Report Excel exports (portal) | `ReportDownload.tsx` | `/api/dashboard/export/*` | S | Real | **Complete** | Formula injection; partial weeks in Consolidated |
| PDF exports | — | — | — | — | **Not Implemented** | — |
| Raw file store (legacy) | — | `/api/upload/`, `/api/raw-files/` | file system | — | Dead endpoint | — |

**Tally:**
- Complete: 13.
- Partially Complete: 11.
- Not Implemented: 4.
- Mock Data: 1.
- Broken: 2.
- Needs Verification: 3.
- Plus 1 dead endpoint.

---

## 10. Dead Code Analysis

### Methodology

**Frontend:**
- A Python script parsed every import form: named, default, namespace, re-exports, and `lazy(() => import(...).then(m => m.X))`.
- It resolved `@/` and relative paths, and matched imports to the 879 exported symbols.
- Each finding was confirmed with `grep -w`.

**Backend:**
- An AST call-graph reachability analysis over 1,003 top-level definitions.
- Roots:
  - URL views called by the frontend;
  - management commands;
  - AppConfigs, models and admin;
  - `config/*` string references.
- Never-called endpoints and tests were analysed as separate root sets.

**Unused imports:** an AST check. pyflakes and ruff were not installed and were not added.

**Limitations:**
- Dynamic dispatch via `getattr`/strings was checked by grep only.
- Out-of-repo scripts (the production sitedata import) may call "orphaned" modules. Those are classified as required, not dead.
- Line counts are physical lines.

### Findings

| Classification | Item | Path | Lines | Confidence |
|---|---|---|---|---|
| Confirmed dead (unreferenced) | `continuity`, `staged_exists`, `uploads.discard` (duplicated inline) | `sitedata/dashboard_source.py:46`, `sitedata/unmatched.py:190`, `sitedata/uploads.py:95` | 10 | High |
| Confirmed dead | Empty Django `tests.py` stubs | `apps/common/tests.py`, `apps/dashboard/tests.py` | 6 | High |
| Confirmed dead at runtime (endpoint never called; tests exist) | Legacy workbook import API `/api/imports/*` (frontend test asserts it is never called) | `uptimedb/views.py:24-135` | 83 | High |
| Confirmed dead at runtime | Raw file store `/api/upload/` + helpers (`list_raw_files` lists only its output) | `common/views.py:20-58,101-171` | ~96 | High |
| Confirmed dead at runtime | `/api/dashboard/conversion-activity/` + Excel `monthly_activity` (keep `ENTITIES` and `source_file`) | `dashboard/views.py:366-389`; `dashboard/activity.py:39-137` | ~106 | High |
| Confirmed dead (frontend) | 8 unused API wrappers: `fetchHealthStatus`, `fetchOperationalAreaAliases`, `updateOmAssignment`, `fetchPersonnelDetail`, `updatePersonnel`, `fetchPersonnelAliases`, `createPersonnelAlias`, `createSiteAssignment` (plus their 3 types) | `services/api.ts:133,508-606`; `types/index.ts:1-5`; `types/organization.ts:150-159,219-232` | ~72 | High |
| Confirmed dead (frontend) | `OverviewLinks`, `VIEW_LOOK`, `filterSearch`, `Kpis`; `siteScopeLabel`; `IS_DEMO_DATA` export | `pages/rca/RcaSummaryPage.tsx:145-265`; `lib/rca.ts:10`; `hierarchyMockData.ts:11` | ~50 | High |
| Confirmed dead (asset) | `src/assets/logo.png` (byte-identical to `public/logo.png`) | — | 18 KB | High |
| Probably unused | Hierarchy routes with no UI caller (`om_assignment_detail`, `personnel_detail`, `personnel_aliases`, `PersonnelAliasSerializer`); sitedata detail GETs | `organization/hierarchy_views.py:212,335,371`; `matrix_views.py:85`; `uptime_views.py:70` | ~139 | Medium-high |
| Probably unused (runtime-inert) | `dashboard/crosscheck.py`: reachable, but `reference_sheets` is always empty for sitedata datasets | `dashboard/crosscheck.py:122-133` | 284 | High (inert) |
| Probably unused (frontend) | 14 unused shadcn sub-exports (`CardFooter`, `SelectGroup`, `SheetTrigger`, …) | `components/ui/*` | ~135 | Medium (upstream code; keep or prune) |
| Test-only (frontend) | Client-side CSV validator cluster (replaced by server preview) | `lib/dataEntry.ts:32-42,99-366` | ~268 | High |
| Test-only (frontend) | `previousReportingDate`, `circleExtremes`, `buildExceptions` etc.; `uploadDataFile`; `fetchConversionActivity` | `lib/portfolio.ts:35-38,152-212`; `api.ts:137-141,315-316` | ~82 | High |
| Test-only (backend) | `accounts/scope.may_use`, `workbook.clear_cache`, `breakdown.category_of`, `rules.weeks` | — | 14 | High |
| Legacy, ops-required, **missing entry point** (not dead) | `sitedata/rawcsv.py`, `calculations.py`, `daily.correct`, `rules.check_availability` / `outage_from_availability` | — | 298 | High |
| Legacy but still required | `uptimedb/parser.py`, `daywise.py`, `escalation.py`, `raw/parser.py`, `raw/rules.py` (imported by sitedata); `dashboard/workbook.py` (`Dataset`); `uptimedb/datasource.py` (RCA, emails); `dashboard/upload.py`/`store.py` (live upload UI); `dashboard/reference.py` (O&M heads); `uptimedb/reconcile.py` (command) | — | n/a | High |
| Uncertain (unreleased feature: product decision) | Team Performance Hierarchy backend: `organization/models.py:130-888`, `hierarchy_views.py`, `hierarchy_services.py`, `hierarchy_serializers.py`, admin, reconciliation command | — | ~2,580 | — |
| Uncertain (placeholder: product decision) | Mock hierarchy frontend: `hierarchyMockData.ts`, `pages/hierarchy/*`, `components/hierarchy/*`, `types/hierarchy.ts` | — | 2,974 | — |
| Uncertain (placeholder) | Browser-only Add Row / Add Site + `useSiteRegistry` | — | ~513 | — |
| Unused imports | 34 (backend AST check) | see B-11 | — | High |
| Unused dependencies | None (frontend or backend). `numpy` used directly but unpinned; `shadcn` CLI and `tailwindcss` could be devDependencies | — | — | High |

### Quantification

| Measure | Frontend | Backend | Total |
|---|---|---|---|
| Source files inspected (non-test, non-migration) | 150 | 155 | **305** |
| Source lines inspected | 27,932 | 23,591 | **51,523** |
| Also read: tests / migrations / docs | 6,711 test lines | 9,802 test lines; 2,106 migration lines | 3,775 doc lines; **~73,900 lines overall** |
| **Confirmed dead lines** (unreferenced + dead-at-runtime endpoints) | ~122 | ~301 | **~423 (0.8%)** |
| Probably unused + test-only (excluding confirmed) | ~485 (test-only 350 + shadcn 135) | ~437 (probable 423 + test-only 14) | ~922 |
| **Potential dead lines** (confirmed + probable + test-only) | ~607 | ~738 | **~1,345 (2.6%)** |
| Placeholder or unreleased features (removal is a product decision) | ~3,487 | ~2,580 | ~6,067 |
| Potentially removable including placeholders | ~4,094 | ~3,318 | **~7,412 (14.4%)** |

**Duplicate code:** not measured by a clone detector (none installed). Instances are enumerated in section 11.

**Obsolete documentation:** `README.md` (265 lines) and `docs/architecture.md` (95) are wholly obsolete. Eight further documents are partially stale (section 16).

---

## 11. Duplicate Code Analysis

| Duplicate | Copies | Locations | Risk |
|---|---|---|---|
| `site_key` normalisation (trim/upper/collapse spaces) | 5 identical, plus 2 non-collapsing variants and 2 upper-only | `uptimedb/parser.py:51`, `uptimedb/raw/resolvers.py:20`, `rca/parser.py:79`, `sitedata/identifiers.py:15`, `dashboard/report_export.py:219`; variants `rca/overview.py:174,235`, `allkpis/services.py:99,123` | Key mismatch for IDs with double spaces [I] |
| `canonical_circle` | 2, with different semantics (None vs raw upper-case for unknown codes) | `uptimedb/daywise.py:49`, `uptimedb/raw/rules.py:24`; ad-hoc fallbacks `escalation.py:114`, `matrix.py:234` | Inconsistent circle handling |
| Hardcoded circle aliases | 1 backend, 1 frontend | `dashboard/workbook.py:47`; `frontend/src/lib/dataEntry.ts:32` | Violates the "no hardcoded data" rule |
| `MINUTES_PER_DAY = 1440` | 6 | `dashboard/workbook.py:41`, `rca/parser.py:48`, `sitedata/rules.py:31`, `uptimedb/arrivals.py:31`, `uptimedb/daywise.py:41`, `uptimedb/raw/rules.py:19` | Low |
| NSLA threshold | 3 definitions with different semantics | `metrics.PENALTY_THRESHOLD` (`:438`), `allkpis/services.py:36`, `rca/breakdown.py:31` (21.6 min) | Conflicting KPIs (section 8) |
| Week definitions | 2 backend + 1 frontend | `metrics.py:48`, `sitedata/rules.py:128`, `frontend/src/lib/periods.ts:38` | Drift |
| Bucket thresholds and colours | Backend + 4 frontend places | `metrics.py:39-43`; `constants.ts:4-12,47-49`, `SiteDetailSheet.tsx:21`, `status.ts:7`, `TrendPanel.tsx:58` | Drift |
| Up-Time sheet parser | 2 | `dashboard/workbook.py:206` (pandas), `uptimedb/parser.py:136` | Divergent parsing |
| In-memory dataset cache pattern | 3 | `dashboard/workbook.py:137`, `uptimedb/datasource.py:26`, `sitedata/portfolio.py:34` | Maintenance |
| Email stacks | 2 | `common/email.py` (Django backend) vs `alerts/mailer.py` (encrypted SMTP account) | Two reminder systems, two test modes |
| `may_use` | 2 | `accounts/scope.py:56` (test-only), `uptimedb/raw_views.py:38` | Low |
| Batch discard | 3 | `sitedata/uploads.discard` (unused) + inline in `matrix_views.py:108`, `uptime_views.py:93` | Low |
| KPI card components | 6 | `components/dashboard/KpiCards.tsx`, `features/all-kpis/components/KpiCards.tsx`, `PortfolioKpis.tsx`, `RcaTiles.tsx`, `HierarchyKpiCards.tsx`, dead `RcaSummaryPage.Kpis` | UI inconsistency |
| Table sorting / pagers | 7 / 4 | `SiteTable`, `DataGrid`, `DrillDown`, `CiIePerformancePage`, `CsvArrivalPage`, `TeamsPage`, `ThresholdPage` | Maintenance |
| "4G Saturation → 4G" label helper | 14 | e.g. `lib/circleSeries.ts:14`, `lib/tracking.ts:101` (identical exports) | Low |
| Change/delta helpers; formatters | 2 / 2 | `lib/portfolio.ts:21` vs `features/all-kpis/format.ts:14`; '—' vs 'Not available' | UI inconsistency |
| JSON-write helpers | 2 | `api.ts:204` `postJson` vs `api.ts:221` `send` | Low |

---

## 12. Security Audit

**Verified good [C]:**
- **Default-deny API** (`IsPortalUser`). Only `health/`, `auth/csrf/` and `auth/login/` are open.
- **No public registration.** User creation is Admin-only, and mass assignment is blocked.
- **Forced password change is enforced on the server** (`accounts/permissions.py:30-36`).
- **The `DEV_LOGIN_BYPASS` removal is complete.**
- **Sessions:** HttpOnly cookie, SameSite Lax, 30-minute idle timeout. Login cycles the session key. A password change invalidates other sessions.
- **Password validation:** minimum 10 characters plus common/numeric/similarity checks. Hashing uses PBKDF2.
- **CORS** uses an allow-list.
- **Uploads:** the RCA register and raw uploads re-check scope. Files are always served from server-written paths, so **no path traversal** was found. Stored filenames are generated.
- **No raw SQL; no XSS sinks.** Email HTML is escaped, and previews render in sandboxed iframes.
- **SMTP password** is Fernet-encrypted and never returned.
- **Secrets:** `.env` is git-ignored. The current `.env` secret values are not in git history. Only a dev fallback key in `settings.py` (DEBUG-only) and test fixture passwords appear in history.

**Required-design check [C].** CI users get 403 from the backend `IsAdminRole` on:
- the CSV Arrival Tracker;
- `dashboard/teams*`;
- `organization/*` (including hierarchy);
- users and access;
- alerts;
- RCA cycles and causes;
- the legacy imports;
- workbook upload;
- the data-source switch;
- `sitedata/*` imports and unmatched mapping.

CI users can add data: raw CSV upload, RCA create, Data Panel create/edit (when granted). **Exception: F6 below.**

| # | Pri | Finding | Evidence | Recommendation |
|---|---|---|---|---|
| S-1 | P1 | **`backend/.env` is a development configuration:**<br>• `DEBUG=True`;<br>• `SECRET_KEY` has the `django-insecure` prefix;<br>• `DB_USER` is the PostgreSQL superuser, not the documented `bsnl_portal_app` role;<br>• `ALERT_ENCRYPTION_KEY` is unset, so the SMTP key is derived from `SECRET_KEY`.<br>`check --deploy` reports 6 warnings (W004, W008, W009, W012, W016, W018). Values were not printed. | `backend/.env`; `config/settings.py:28-34,214-223`; `alerts/mailer.py:30-32` | `DEBUG=False`; new random key in a secret store; dedicated non-superuser DB role; separate Fernet key; run `check --deploy` in CI |
| S-2 | P1 | **No production deployment setup:**<br>• `runserver` (`start_backend.bat:79`);<br>• no WSGI server, TLS, `STATIC_ROOT` or shared cache (throttles and dedupe are per-process LocMem);<br>• no CSP;<br>• no log rotation or retention policy. | `requirements.txt`; `settings.py:170` | waitress or gunicorn behind IIS/nginx with TLS; Redis or DB cache; proxy body limit; CSP |
| S-3 | P2 | **Spreadsheet formula injection.** User text (RCA text, site names, Data Panel columns, issue CSVs) is written raw into XLSX/CSV, and openpyxl treats a leading `=` as a formula. | `rca/report.py:157-161`; `report_export.py:151`; `masterdata/views.py:222-246`; `uptimedb/views.py:97-109`; `rca/views.py:420-440`; `raw_views.py:200-206` | Shared export sanitiser that prefixes `'` for values starting with `= + - @ \t \r` |
| S-4 | P2 | **RCA PATCH can move a record outside the editor's scope.** Scope is checked on the current project/circle only; the new project/circle in the body is not checked. | `rca/views.py:94,101-105` | Check `can(edit)` on the new pair, or make project/circle read-only |
| S-5 | P2 | **Login IP throttle bypass via spoofed `X-Forwarded-For`.** `NUM_PROXIES` is unset, and the cache is per-process. | `accounts/throttles.py:9`; `settings.py:226-243` | Set `NUM_PROXIES`; shared cache |
| S-6 | P2 | **CI users can rebuild per-CI/IE performance through other endpoints**, which goes against the "no Team Performance" requirement:<br>• `GET /api/all-kpis/hierarchy/?level=ci|ie` (dashboard.view);<br>• `team_*` / `ci_name` / `ie_name` filters on `/api/dashboard/records/`.<br>Data remains within the user's own pairs. | `allkpis/views.py:38-41`; `allkpis/services.py:290-310`; `dashboard/views.py:42-53,125-154` | Business decision; if confirmed, restrict CI/IE levels and filters to Admin |
| S-7 | P2 | **An Admin can send the stored SMTP password to an arbitrary host.** Changing `host` keeps the encrypted password, and "test" authenticates against the new host. The test also allows internal port probing (SSRF) and returns banner text. | `alerts/views.py:67,89-93,111-135`; `alerts/mailer.py:52-65` | Clear the password on host/port/user change; host allow-list; generic errors |
| S-8 | P2 | **Upload size is checked only after the full body is received.** Zip-bomb and macro checks apply only to the Master workbook; RCA, matrix and uptime `.xlsx`/`.xlsm` files have no expanded-size check. Authenticated denial of service is possible. | `dashboard/upload.py:79-95` vs `rca/parser.py:205`, `sitedata/matrix.py:98`, `uptime_master.py:120` | Shared package check; proxy body limit; reject `.xlsm` |
| S-9 | P3 | **Sign-in timing enumeration:** `EmailBackend` skips hashing for unknown users. | `accounts/backends.py:14-28` | Dummy hash |
| S-10 | P3 | **Sessions:** remember-me renews for 7 days with no absolute cap. There is no password-change throttle and no self-service "sign out everywhere". | `accounts/views.py:134-136,162-188` | Absolute session lifetime; throttle |
| S-11 | P3 | **Audit gaps:**<br>• workbook upload, raw file store, personal emails, Data Panel exports, hierarchy edits and 403s are not audited;<br>• `login_failed` stores the raw login ID, which may contain mistyped passwords;<br>• the log is a local plain file. | `accounts/audit.py`; `accounts/views.py:131` | Add audits; mask IDs; central log |
| S-12 | P3 | **Over-broad responses:**<br>• `GET /api/data-source/` gives CI users database-wide completeness;<br>• alert `distribution=same` can exceed a recipient's scope;<br>• RCA batch detail does not re-check scope after revocation. | `uptimedb/views.py:162-165`; `alerts/engine.py:120-135`; `rca/views.py:309-313` | Limit to Admin; per-recipient default |
| S-13 | P3 | **Admin governance:** an Admin can reset a peer Admin's password and receives the temporary password. `email/send` is an unaudited free-text send channel. | `accounts/views.py:379-394`; `common/views.py:249-262` | Superuser-only for Admin accounts |
| S-14 | P3 | **File hygiene:** a temp-file leak in a legacy import error path; no retention policy for raw, staged or alert files. | `uptimedb/views.py:75`; `sitedata/uploads.py:41-46` | try/finally; retention job |
| S-15 | P3 | **Minor:**<br>• invalid alert-history params give a 500;<br>• email/username cross-collision can lock a user out of username sign-in;<br>• HSTS default is 3600 s;<br>• `docs/security.md` is outdated (mentions `/admin/`, which is not installed, and "CI sees every circle"). | `alerts/views.py:407-419`; `backends.py:21-24` | — |

---

## 13. Performance Audit

| # | Pri | Issue | Evidence |
|---|---|---|---|
| P-1 | P2 | **RCA summary takes 11–16 s:** about 30 aggregates, a legacy dataset build and a large IN list. | `rca/services.py:431-700` |
| P-2 | P2 | **Per-request `COUNT(*)` over about 410k daily rows** (cache key) about twice per dashboard request, plus a full-history rebuild ×3 variants under a global lock after every upload. Cost grows with history. | `sitedata/portfolio.py:39-42`; `dataset.py:130-134`; `portfolio._effective` (`:48-66`, a Python loop over sites × dates) |
| P-3 | P2 | **Per-row UPDATE and DELETE in matrix, uptime and RCA commits.** | section 6, B-6 |
| P-4 | P3 | **RCA Site Scope** has no index on legacy monthly `(month, om_start)` and uses an OR of subqueries. | `rca/sitescope.py:38-44` |
| P-5 | P3 | **The arrival tracker aggregates the whole legacy daily table on every request**, with no date bound. | `uptimedb/arrivals.py:84-95` |
| P-6 | P3 | **`dataset.completeness()` joins every daily row to Site** instead of using the denormalised columns and index. | `sitedata/dataset.py:38-50` |
| P-7 | P3 | **pandas reads whole workbooks**, including a 50 MB Master workbook and a full file just to preview 5 rows. Per-process caches multiply memory per worker. | `dashboard/workbook.py:176`; `common/views.py:143-145` |
| P-8 | P3 | **Frontend:**<br>• Add Row pages through a whole circle's records;<br>• filter options are re-fetched on every page;<br>• no chunk analysis (build not run). | `useSiteRegistry.ts`; `vite.config.ts` |

---

## 14. Testing and Reliability

**Executed [C]:**
- **Backend suite, on SQLite** (`DB_ENGINE=django.db.backends.sqlite3`, set in the process environment; `load_dotenv` does not override it, so PostgreSQL was not touched):
  - 642 tests in 331 s;
  - **636 passed, 2 failed, 4 errors.**
- **The 2 failures:** `test_reconciliation` (`test_dataset_shape`, `test_calculation_check_uses_each_formulas_population`). These are the known failures: they read a live workbook whose dates moved (expected 14 Oct, found 25 Oct).
- **The 4 errors are new and are environment-caused:**
  - `test_accounts`: `CiRoleTests`, `CsrfTests`, `NoLoginBypassTests`, `SignedOutTests`.
  - Root cause: `AttributeError: 'super' object has no attribute 'dicts'` in `django/template/context.py:41` (`Context.__copy__`).
  - This is raised when the test client copies the template context of Django's default 404/CSRF pages.
  - **The venv runs Python 3.15.2**, while Django 5.1 supports Python up to 3.13 and the project documents Python 3.11.
  - It is not an application defect, but the environment is unsupported (P2). Pin Python 3.11–3.13, or upgrade Django to a release that supports the interpreter.

**Coverage characteristics:**
- 42 backend test modules, one per area; 40 frontend test files with 325 cases.
- **The test runner substitutes the Excel dataset for sitedata** in most dashboard tests (B-2).
- Frontend page tests stub the API functions; there are no contract tests (F-10).
- Locking and concurrency are untested because SQLite makes `select_for_update` a no-op.
- `HierarchyTabs.tsx` is effectively untested. The hierarchy page tests assert the mock data.
- No coverage tool is configured, so a coverage percentage is **not measured**.

**Not executed (and why):**
- Frontend `tsc`, `oxlint`, `vitest` and `vite build`: `frontend/node_modules` is absent, and installing dependencies required approval.
- `pip-audit` / `npm audit`: not installed.
- Any check against PostgreSQL: deliberately avoided.

---

## 15. Dependency Audit

**Backend** (`requirements.txt`; installed versions in `.venv`):

| Package | Requirement | Installed | Notes |
|---|---|---|---|
| Django | >=5.1,<5.2 | 5.1.15 | **Not supported on the Python 3.15 interpreter** (test errors above) |
| djangorestframework | >=3.17,<3.18 | 3.17.2 | OK |
| django-cors-headers | >=4.9,<5 | 4.9.0 | OK |
| python-dotenv | >=1.0 | 1.2.4 | No upper bound |
| pandas | >=2.2.0 | **3.1.1** | **No upper bound.** The installed major version is newer than the project was written against (copy-on-write and string dtype changes). Tests pass, but the range is risky. |
| openpyxl | >=3.1 | 3.1.5 | OK |
| psycopg[binary] | >=3.2 | 3.3.8 | OK |
| cryptography | >=43,<46 | 45.0.7 | OK |
| numpy | **not listed** | 2.5.4 | Imported directly in 12 modules. Pin it. |

- No unused packages.
- Missing for production: a WSGI server, static serving (whitenoise), `defusedxml`.
- No lock file and no hash pinning for Python.

**Frontend** (`package.json`, lockfile with 596 packages):
- React 19.3, react-router-dom 7.18, recharts 3.10, radix-ui 1.8, Tailwind 4.3, Vite 8.3, TypeScript ~6.0, Vitest 5.0, oxlint 1.88.
- No unused dependencies.
- `shadcn` (the full CLI, which brings babel and an MCP SDK) is listed in `dependencies` only to supply a CSS file. Move it, and `tailwindcss` and `@tailwindcss/vite`, to `devDependencies`.
- Known-vulnerability scan: **not executed** (no `npm audit` without `node_modules`; no `pip-audit`).

---

## 16. Documentation Audit

| Document | Problem | Action |
|---|---|---|
| `README.md` | Wholly obsolete: describes "no authentication", SQLite default, Excel-only and missing ingestion. It references `inspect_raw.py`/`match_master.py`, which do not exist. **The file is encoding-damaged:** about 160 leading blank lines and a UTF-16 tail (`# B S N L _ 4 G`), so `file` reports "data". | Rewrite in UTF-8 |
| `docs/architecture.md` | Describes the Excel-only, unauthenticated phase ("No reporting data is stored in the database", "No authentication yet") | Rewrite |
| `PROJECT_HANDOVER.md` | It says:<br>• "Only Site Portfolio reads sitedata": false; every dashboard, All KPI's and the exports do;<br>• the sitedata work is "uncommitted": false;<br>• "no upload screens for new importers": false.<br>Its command table misses `import_lwe_mapping` and `hierarchy_reconciliation_dry_run`.<br>It says RCA reuses `period_summary` for USD/NSLA: false (`rca/breakdown.py` has its own rule).<br>It omits the mock Hierarchy pages from the feature table. | Update sections 1–3, 6 and 8 |
| `backend/apps/sitedata/README.md` | Says "not connected to any page; migration not applied", and that the default months are Sep/Oct (the code uses `SITEDATA_DAILY_FROM`→current month; no such setting is in `settings.py`) | Update |
| `docs/site-portfolio.md` | Describes legacy sources | Update |
| `docs/rca.md` | The "Current data" section describes the first import (1,819 records) | Update |
| `docs/business-rules.md` | Weekly and monthly definitions differ from the code (incomplete weeks are nulled; months come from reporting days) | Update |
| `docs/security.md` | Says "Django admin `/admin/`" (not installed), "CI sees every circle" (false since assignments) and has an outdated role table | Update |
| `docs/access-control.md` | Says `member` users get rights from assignments; they cannot sign in | Fix the docs or the code |
| `scripts/README.md` | Lists two scripts not present in the repository | Update |
| Stale docstrings | `uptimedb/datasource.py:1-7`, `uptimedb/views.py:142`, `dashboard/report_export.py:1`, `sitedata/dataset.py:3-4`; UI text `UploadCsvPage.tsx:300`, `lib/portfolio.ts:309` | Update |

**Missing:**
- deployment guide;
- **backup and restore runbook with a tested restore**;
- API reference for the sitedata endpoints;
- a migration tracker (module → layer);
- an operations guide for the new-layer importers (how to run the raw CSV, monthly calculation and corrections that have no UI).

---

## 17. Critical Bugs (master issue register)

### P0: Critical

| ID | Issue | Evidence | Business impact | Recommended solution | Dependencies / risks |
|---|---|---|---|---|---|
| **C-1** | **Raw daily CSV uploads never reach any dashboard, and the UI says they do** [C] | `uptimedb/raw/service.py:286-300` writes `uptimedb.SiteDailyPerformance` and clears only `datasource` cache. Every dashboard, export, All KPI's and Portfolio reads `sitedata` (`dashboard/views.py:23-34`). `sitedata/rawcsv.py` has no caller. `UploadCsvPage.tsx:300` claims inclusion. | Circles upload daily data that silently disappears from reporting. Management sees stale or incomplete uptime. Data-loss-equivalent for daily operations. | Short term: change the success message and add a page warning; tell operators to load Up-Time reports. Fix: add `/api/sitedata/raw/*` endpoints wrapping `rawcsv.preview`/`commit` (rank 1, LWE mapping), clear the `portfolio` cache, and repoint `UploadCsvPage`. Then retarget the arrival tracker. | Business confirmation of LWE outage formula; concurrency lock (C-17); arrival tracker migration (C-6) |

### P1: High

| ID | Issue | Evidence | Impact | Solution | Dependencies / risks |
|---|---|---|---|---|---|
| **C-2** | Data Panel reads and edits legacy tables only | `masterdata/datasets.py:22,71-99`; `editors.py`; `editing.py:154` clears legacy cache | Corrections made in the only editing UI have no effect; panel shows different values from the dashboard | Retarget datasets to `sitedata.Site` / `DailySitePerformance`; route daily edits through `daily.correct()` | C-3; permission catalogue keys per dataset |
| **C-3** | No authorized correction path; revised Up-Time reports cannot fix values | `sitedata/daily.py:160` (`correct`) has no caller; equal rank keeps the first value | Known-wrong daily figures cannot be corrected in the reporting layer | Admin correction endpoint and UI (reason, audit) or a "correction file" upload kind | Governance decision on who may correct |
| **C-4** | Emailed reports use legacy/Excel data; portal downloads use sitedata | `alerts/reports.py:61-77` (`current_dataset`) | Same report, different numbers; possible automation failure if the workbook is missing [I] | Use `dashboard_source.dataset(pairs)` | Alerts tests |
| **C-5** | RCA breakdown, overview, summary, Site Scope, import validation and cycles read legacy site data | `rca/breakdown.py:106`; `overview.py:84,154`; `services.py:433`; `sitescope.py:37-44`; `importer.py:122-124`; `cycles.py:107` | USD/NSLA/Total differ from dashboards; O&M scope may be empty for new months [I]; valid matrix sites rejected on RCA import | Migrate RCA's *site* reads to sitedata (matrix dates for O&M, `sitedata.Site` for validation), keeping RCA records untouched | Handover says RCA excluded from migration: needs business approval |
| **C-6** | CSV Arrival Tracker and reminder emails use legacy coverage | `uptimedb/arrivals.py:76-138`; `alerts/engine.py:147-152` | False "received" status; missed or false reminders | Compute coverage from `sitedata.DailySitePerformance` and `UploadBatch` | C-1 |
| **C-7** | Data-source switch no longer controls dashboards but silently changes RCA, emails and reminder validation | `DatabaseImportPage.tsx:116`; `uptimedb/views.py:142-160`; `dashboard/views.py:305-334` | Admins misled; silent changes in RCA and email figures | Remove or relabel the switch; pin remaining consumers to sitedata | C-4, C-5 |
| **C-8** | `organization.0004` hazard and hierarchy admin tabs on likely-missing tables | migration FK → `UptimeSite` CASCADE (`organization/models.py:648-653`); 17 live routes; `HierarchyTabs.tsx` hides errors | A plain `migrate` creates a CASCADE dependency on a table due for retirement; admin tabs likely 500 and appear empty [I] | Re-target FK to `sitedata.Site` (PROTECT) before any migrate; gate tabs and routes until applied; surface errors | Verify `django_migrations` in production (read-only) |
| **C-9** | Mock Team Performance Hierarchy pages in production navigation, with names, employee codes and phone numbers | `hierarchyMockData.ts`; `Sidebar.tsx:62`; `App.tsx:64-68` | Management may act on fake figures; possible PII exposure [I: real or fictitious?] | Remove from sidebar and routes, or gate behind a feature flag; delete PII from the bundle | Product decision |
| **C-10** | Development configuration in `backend/.env`: DEBUG, insecure key, superuser DB account | section 12 S-1 | Session forgery, info leak, full DB cluster compromise on any app bug if deployed as-is | See S-1 | Secret store; DB role creation (DBA) |
| **C-11** | No production deployment setup | section 12 S-2 | Cannot be deployed securely as-is | See S-2 | IT infrastructure |
| **C-12** | New-layer monthly calculation and raw CSV / LWE CSV import exist only in tests and out-of-repo scripts | `sitedata/calculations.py`, `rawcsv.py` | Monthly table stale; LWE daily CSVs cannot be loaded into reporting; dependence on undocumented scripts | Management commands plus endpoints; document the operations runbook | C-1, C-17 |

### P2: Medium

| ID | Issue | Evidence |
|---|---|---|
| C-13 | Precedence outcome depends on upload order (higher-rank duplicate does not upgrade provenance) | `sitedata/daily.py:90-93` |
| C-14 | Partial weeks shown as values in Portfolio, All KPI's and the Consolidated export, but nulled on the dashboard and thresholds | `periods.ts:110-127`; `allkpis/services.py:265-271`; `report_export.py:322-327` |
| C-15 | Three USD/NSLA definitions under the same labels | `metrics.py:697-704`; `allkpis/services.py:152-173`; `rca/breakdown.py:135-162` |
| C-16 | Float boundary: exactly 98.5% counted as NSLA in the RCA breakdown (21.60000000000002 > 21.6) | `rca/breakdown.py:31,162` |
| C-17 | Importer commits not locked; double-submit commits twice on PostgreSQL | `uptime_master.py:363-371`; `matrix.py:417-427`; `unmatched.py:149-175` |
| C-18 | Alternate-ID mapping: no revoke, no circle check, silent takeover by a later master ID | `unmatched.py:43-79`; `uptime_master.py:268-280`; `matrix.py:326-347` |
| C-19 | Finalized months not protected; no recalculation trigger | `daily.write`; `unmatched.process_pending` |
| C-20 | Reporting month can stick ("ever-reported" expected units) | `sitedata/dataset.py:47,53-58` |
| C-21 | Conversion activity: Excel (Overview) vs matrix (Portfolio) | `dashboard/views.py:364-388` vs `sitedata/portfolio.py:152` |
| C-22 | Team Performance (matrix names) vs Hierarchy (legacy `UptimeSite`) use different people | `organization/hierarchy_services.py:26,213` |
| C-23 | Test runner substitutes the Excel dataset for sitedata in most dashboard tests | `tests/runner.py:33-49` |
| C-24 | Unsupported interpreter: Python 3.15 with Django 5.1 (4 test errors); pandas unbounded at 3.x; numpy unpinned | section 14/15 |
| C-25 | Spreadsheet formula injection (S-3) | — |
| C-26 | RCA PATCH scope escape (S-4) | — |
| C-27 | Login throttle XFF bypass (S-5) | — |
| C-28 | CI access to per-CI/IE performance via All KPI's and records filters (S-6) | — |
| C-29 | SMTP password redirect / SSRF (S-7) | — |
| C-30 | Upload size/zip-bomb checks incomplete (S-8) | — |
| C-31 | RCA summary 11–16 s (P-1) | — |
| C-32 | Per-request COUNT(*) and full-history rebuild (P-2) | — |
| C-33 | Per-row writes in commits (P-3) | — |
| C-34 | In-memory-only tracking data lost on refresh (F-4) | — |
| C-35 | Add Row / Add Site browser-only with permission mismatch (F-5) | — |
| C-36 | `canOpen` default-allow (F-6) | — |
| C-37 | Frontend duplicates business thresholds, weeks and buckets (F-7) | — |
| C-38 | API base URL falls back to localhost (F-8) | — |
| C-39 | Lint/strict gaps; no contract tests (F-9, F-10) | — |
| C-40 | Backend duplicated rules and layer coupling (B-3, B-4) | — |
| C-41 | `rca/services.py` formatting damage (429 blank lines) (B-8) | — |
| C-42 | Stale documentation misleading operators and AI assistants (section 16) | — |

### P3: Low

| ID | Issue |
|---|---|
| C-43 | Calculation check always empty on sitedata (`crosscheck.py:122-133`) |
| C-44 | Daily export accepts incomplete dates (`serializers.py:196-198`) |
| C-45 | No length check on alternate mapping value; 500 on PostgreSQL (`unmatched.py:77`) |
| C-46 | On-Air decided by date only; matrix status ignored (`dataset.py:113`). Business confirmation needed |
| C-47 | No index (month, om_start) for RCA Site Scope; arrival-tracker unbounded aggregate (P-4, P-5) |
| C-48 | Organization usage counts legacy-only (`organization/services.py:181-202`) |
| C-49 | `import_lwe_mapping` commits with `user=None` (audit gap) |
| C-50 | `member` role documented but cannot sign in (`accounts/views.py:130`) |
| C-51 | `nsla_site_keys` built from raw `site_id` (`rca/breakdown.py:183`) [I] |
| C-52 | Sign-in timing enumeration (S-9) |
| C-53 | Session lifetime / password-change throttle (S-10) |
| C-54 | Audit log gaps and raw login ID logging (S-11) |
| C-55 | Over-broad `data-source` GET, alert distribution, RCA batch scope (S-12) |
| C-56 | Admin can reset peer Admin; unaudited free-text email (S-13) |
| C-57 | Temp-file leak and no file retention (S-14) |
| C-58 | Minor input robustness, HSTS default (S-15) |
| C-59 | Exception-handling and envelope deviations (B-9) |
| C-60 | Hardcoded sitedata `MAX_BYTES`; whole-file pandas previews (B-10) |
| C-61 | 34 unused imports, stub files, deprecated `CheckConstraint(check=)` (B-11) |
| C-62 | Dead code: ~423 confirmed lines plus unused API wrappers and duplicate asset (section 10) |
| C-63 | Duplicate UI components and helpers (F-13) |
| C-64 | Download paths bypass 401 handling (F-12) |
| C-65 | `Unauthorized` link; All KPI's RCA panel permission (F-14) |
| C-66 | No request caching / no build chunk config (F-15) |
| C-67 | `README.md` encoding damage; `shadcn` CLI in runtime dependencies |

**Totals: P0 1 · P1 11 · P2 30 · P3 25 = 67.**

---

## 18. Technical Debt

1. **Dual data layers.** Three site masters, two daily and monthly tables and three batch tables. Legacy parsers are imported by the new layer.
2. **Orphaned operational code.** New-layer importers, calculations and corrections run only through out-of-repo scripts.
3. **The core `Dataset` type lives in an Excel parser module.** Three copies of the cache pattern.
4. **Duplicated domain rules** across backend and frontend (section 11).
5. **Oversized modules:**
   - `metrics.py` 1,365 lines;
   - `HierarchyTabs.tsx` 1,410;
   - `CsvArrivalPage.tsx` 854;
   - functions over 250 lines: `rca/services.summary`, `rca/parser.parse`, `rca/overview.get_rca_overview`, `hierarchy_reconciliation_dry_run.handle`.
6. **The unreleased hierarchy feature** (about 5,500 lines across FE and BE) is built on a legacy FK.
7. **Tests that test the wrong path** (runner substitution); no PostgreSQL CI; no contract tests.
8. **Two email systems.**
9. **Browser-only workflow state** (tracking) and browser-only data entry pages.
10. **Excel files read at runtime** from `Data/reference` (O&M heads, legacy activity).

---

## 19. Risk Assessment

| Risk | Likelihood | Impact | Rating |
|---|---|---|---|
| Daily data uploaded but not reported (C-1) | Certain while the page is used | High | **Critical** |
| Conflicting KPI numbers across screens and emails (C-4, C-5, C-15) | Certain | High (management decisions, penalties) | **High** |
| Inability to correct wrong data (C-2, C-3) | High | High | **High** |
| Deploying with the dev configuration (C-10, C-11) | Medium | Critical | **High** |
| Accidental `migrate` applying 0004 CASCADE FK (C-8) | Medium | High (future data loss) | **High** |
| Mock figures or PII in production UI (C-9) | Certain (visible) | Medium–High | **High** |
| Double-commit on PostgreSQL (C-17) | Low–Medium | Medium | Medium |
| Formula injection via exports (C-25) | Low–Medium | Medium | Medium |
| Performance degradation as history grows (C-31, C-32) | High over months | Medium | Medium |
| Dependency drift (Python 3.15, pandas 3) (C-24) | Medium | Medium | Medium |
| Retiring legacy tables prematurely | Low (documented caution) | Critical | Medium (keep the guardrails) |

---

## 20. Recommended Refactoring Plan

| Phase | Scope | Complexity | Risk | Dependencies | Benefits | Order |
|---|---|---|---|---|---|---|
| **1. Critical bugs and security** | C-1 messaging and warning, then sitedata raw CSV endpoint; hide mock hierarchy (C-9); gate hierarchy tabs/routes (C-8); production `.env` hardening and deploy stack (C-10/11); formula-injection sanitiser; RCA PATCH scope; `NUM_PROXIES`; SMTP password reset on host change | Medium | Low–Medium | IT for TLS/DB role; business confirmation of LWE formula | Stops silent data loss and PII exposure; deployable posture | 1st |
| **2. Database and data integrity** | Lock batch rows in commits (C-17); provenance upgrade on higher-rank duplicates (C-13); alternate-mapping revoke, circle check and cross-kind conflict (C-18); finalized-month guard and recalculation trigger (C-19); expected units from Organization (C-20); `technology` consistency constraint; re-target 0004 FK; float-safe threshold comparisons (C-16) | Medium | Medium (data writes) | Phase 1; fresh verified backup | Deterministic, order-independent data | 2nd |
| **3. Legacy migration completion** | One module at a time, each with reconciliation: arrival tracker and reminders → Data Panel (+ corrections UI) → emailed reports → RCA site reads (scope, breakdown, validation, cycles) → hierarchy → org usage. Then retire the data-source switch. Then restore-tested backup and retirement of legacy tables in a separately approved step | High | High | Phases 1–2; business approval for RCA | Single source of truth; consistent numbers | 3rd |
| **4. API and business logic cleanup** | Unify or rename USD/NSLA definitions (C-15); apply weekly completeness everywhere (C-14); single `site_key`/`canonical_circle`/constants module; move `Dataset` out of `workbook.py`; stop private legacy imports; consolidate the RCA summary into conditional aggregates and cache; bulk writes in commits; cheap cache version stamp | Medium–High | Medium | Phase 3 for RCA pieces | Consistency, speed | 4th |
| **5. Frontend cleanup** | Default-deny `canOpen`; persist tracking data server-side or remove it; retire Add Row/Add Site; read thresholds and labels from the API; shared KPI card, table, sort and pager components; split `CsvArrivalPage`/`ThresholdPage`/`HierarchyTabs`; `VITE_API_BASE_URL` required at build | Medium | Low | Phase 4 API for thresholds | Maintainability | 5th |
| **6. Dead code removal** | ~423 confirmed lines; test-only clusters; dead endpoints with their tests; 34 unused imports; duplicate asset; decide on hierarchy placeholders (~6,000 lines) | Low | Low | Phases 3–5 (some "dead" code becomes dead only after migration) | ~2.6–14% smaller codebase | 6th |
| **7. Performance optimization** | Incremental dataset rebuild; index (month, om_start) or migrate RCA scope; bounded arrival aggregates; shared cache (Redis) for multi-worker; streaming Excel reads | Medium | Low–Medium | Phases 3–4 | Scales with history | 7th |
| **8. Testing and documentation** | PostgreSQL CI job; remove runner substitution and add sitedata fixtures; concurrency tests; MSW/contract tests; `strict`, exhaustive-deps and knip; coverage tool; rewrite README/architecture/handover; deployment, backup-restore and operations runbooks | Medium | Low | Continuous; start the CI job in Phase 1 | Confidence; onboarding | Parallel, finish last |

---

## 21. Prioritized Action Plan

1. **Today:**
   - Change the Upload CSV success message.
   - Warn on the page that raw CSV uploads are not yet included in dashboards (C-1).
   - Tell circles which file actually feeds the dashboards.
2. **Hide or flag the mock Hierarchy pages** and remove PII from the bundle (C-9). Gate the hierarchy admin tabs (C-8).
3. **Do not run a plain `manage.py migrate`** until the `organization.0004` FK is re-targeted. Verify `django_migrations` read-only in production.
4. **Build the sitedata raw CSV upload endpoint** (rank 1, LWE mapping) and repoint the page. Move the arrival tracker to sitedata coverage (C-1, C-6, C-12).
5. **Add an Admin correction path** (`daily.correct`) and repoint the Data Panel to sitedata (C-2, C-3).
6. **Pin emailed reports to `dashboard_source`.** Retire or relabel the data-source switch (C-4, C-7).
7. **Decide the business definitions:**
   - USD/NSLA (C-15);
   - partial weeks (C-14);
   - CI access to per-CI/IE KPIs (C-28);
   - On-Air by date vs status (C-46);
   - whether RCA's site reads may move to sitedata (C-5).
8. **Harden for production:**
   - `DEBUG=False`, new secret key, non-superuser DB role, separate Fernet key;
   - WSGI + TLS + shared cache + CSP;
   - formula-injection sanitiser;
   - RCA PATCH scope check;
   - `NUM_PROXIES`;
   - SMTP password reset on host change (C-10, C-11, C-25–C-29).
9. **Fix data-integrity edge cases:**
   - commit locking (C-17);
   - precedence provenance (C-13);
   - alternate-ID safeguards (C-18);
   - finalized months and recalculation (C-19);
   - 98.5% float boundary (C-16).
10. **Fix the toolchain and tests:**
    - pin Python 3.11–3.13 (or upgrade Django), bound pandas and pin numpy (C-24);
    - add a PostgreSQL CI job and remove the test-runner dataset substitution (C-23);
    - install frontend dependencies and run `tsc`, lint, vitest and build;
    - update the handover, README and docs (C-42).

---

## 22. Files and Modules Requiring Attention

| File | Why |
|---|---|
| `backend/apps/uptimedb/raw/service.py`, `raw_views.py`, `frontend/src/pages/data/UploadCsvPage.tsx` | C-1 |
| `backend/apps/sitedata/rawcsv.py`, `calculations.py`, `daily.py` | No entry points; precedence bug (C-12, C-3, C-13) |
| `backend/apps/sitedata/uptime_master.py`, `matrix.py`, `unmatched.py` | Commit locking, mapping safeguards, per-row writes |
| `backend/apps/sitedata/portfolio.py`, `dataset.py`, `dashboard_source.py` | Cache cost, reporting-month logic |
| `backend/apps/masterdata/datasets.py`, `editors.py`, `editing.py` | Legacy-only Data Panel (C-2) |
| `backend/apps/alerts/reports.py`, `engine.py`, `views.py`, `mailer.py` | Legacy reports; SMTP redirect |
| `backend/apps/uptimedb/arrivals.py`, `datasource.py`, `views.py` | Legacy coverage; misleading switch |
| `backend/apps/rca/breakdown.py`, `overview.py`, `services.py`, `sitescope.py`, `importer.py`, `cycles.py`, `views.py`, `report.py` | Legacy reads, float bug, performance, PATCH scope, formula injection, formatting damage |
| `backend/apps/allkpis/services.py`, `views.py` | KPI definitions, partial weeks, CI/IE exposure |
| `backend/apps/dashboard/metrics.py`, `report_export.py`, `views.py`, `crosscheck.py`, `activity.py`, `workbook.py` | Shared engine (handle with care); export injection and partial weeks; dead and inert code; `Dataset` location |
| `backend/apps/organization/models.py`, `migrations/0004_*`, `hierarchy_*.py` | CASCADE FK to legacy; unreleased feature |
| `backend/apps/accounts/throttles.py`, `backends.py`, `views.py`, `audit.py` | Throttle bypass, timing, sessions, audit |
| `backend/config/settings.py`, `backend/.env`, `backend/requirements.txt`, `start_backend.bat` | Deployment posture, dependency pins |
| `backend/tests/runner.py` | Test fidelity |
| `frontend/src/services/hierarchyMockData.ts`, `pages/hierarchy/*`, `components/organization/HierarchyTabs.tsx`, `components/Sidebar.tsx` | Mock data, PII, hidden errors |
| `frontend/src/context/auth.ts`, `TrackingProvider.tsx`, `lib/tracking.ts`, `lib/periods.ts`, `components/dashboard/constants.ts`, `services/api.ts` | Default-allow, lost state, duplicated rules, base URL |
| `README.md`, `PROJECT_HANDOVER.md`, `docs/architecture.md`, `docs/security.md`, `docs/access-control.md`, `docs/business-rules.md`, `backend/apps/sitedata/README.md` | Stale documentation |

---

## 23. Commands and Tests Executed

All commands were read-only with respect to the repository and the PostgreSQL database. `DB_ENGINE=django.db.backends.sqlite3` was exported in the shell; `settings.py` uses `load_dotenv` without override, so the process value takes precedence over `backend/.env`.

| Command | Result |
|---|---|
| `git ls-files`, `git log`, `git show --stat`, `git status`, `git diff` | Inventory and history; working tree verified clean after the audit |
| `wc -l` over tracked sources | Sizes in section 10 |
| `python manage.py check` | **No issues** |
| `python manage.py check --deploy` | **6 warnings:** W004 HSTS, W008 SSL redirect, W009 weak `SECRET_KEY`, W012 session cookie not secure, W016 CSRF cookie not secure, W018 `DEBUG=True` |
| `python manage.py makemigrations --check --dry-run` | **No changes detected** |
| `python manage.py test tests --noinput` (SQLite, in-memory test DB) | **642 tests, 331 s: 636 passed, 2 failures (known reconciliation), 4 errors (Python 3.15 / Django 5.1 template-context incompatibility)** |
| `pip list` | Installed versions (section 15) |
| `python -c "print(1440*(1-98.5/100))"` | `21.60000000000002` (C-16) |
| URL introspection via `django.setup()` (SQLite) | 157 patterns with permission classes |
| AST reachability and unused-import scripts; TypeScript import-graph script (scratch directory) | Section 10 figures |
| `git log -p` grep for secret patterns (presence only, no values printed) | Only a dev fallback key and test fixtures in history |

**Not executed:**
- Frontend `npx tsc -b`, `npm run lint`, `npm test` and `npm run build`: no `node_modules`, and `npm install` needs approval.
- `npm audit` / `pip-audit`.
- Any query against PostgreSQL `4G-DB`.
- Any migration.

---

## 24. Audit Limitations and Unverified Findings

- **No production database access.** Not verified:
  - whether `organization.0004` and `sitedata.0002` are applied;
  - row counts;
  - whether legacy `SiteMonthlyPerformance` has November rows (this determines whether RCA O&M scope is empty for November);
  - the current `AppSetting` data source;
  - whether `UploadBatch` rows of kind `raw_csv_*` or `correction` exist.

  Suggested read-only SQL: `SELECT app, name FROM django_migrations WHERE app IN ('organization','sitedata');` and counts by `kind` on `sitedata_uploadbatch`.
- **Frontend checks were not run.** TypeScript, lint, test and build status are unknown for this machine. The handover's 318/318 result (4 Nov) has not been re-verified.
- **The production deployment topology is unknown.** Single process vs multiple workers affects the cache-staleness findings.
- **Unknown whether the names and phone numbers in `hierarchyMockData.ts` are real people.**
- **Real SMTP/M365 sending was not verified.**
- **Out-of-repo scripts used for the 4 Nov production import were not available.** "Orphaned" modules may be used by them.
- **Dead-code analysis is static.** Code reached only via string-based dynamic dispatch, or by external callers, may be misclassified. Placeholder features are reported separately as product decisions, not as dead code.
- **Performance figures are inferred from code structure,** apart from the documented 11–16 s RCA summary. No profiling was done.
- **No vulnerability database scan** of dependencies was performed.
- **The test results come from an unsupported interpreter** (Python 3.15.2). Results on the documented Python 3.11 may differ.
