# Architecture

## Data flow

```text
Browser: Master workbook page ── POST /api/dashboard/workbook/ (multipart .xlsx)
        ▼
apps/dashboard/upload.py      Stage to a temp file → type/size/zip/macro checks →
        │                     full parse and validation → activate (atomic pointer swap)
apps/dashboard/store.py       Data/processed/workbooks/<timestamp>-<sha>.xlsx + active.json
        │  pandas.read_excel(header=None) — on upload, then cached
        ▼
apps/dashboard/workbook.py    Data access: resolve the active workbook, validate structure,
        │                     normalise sites, extract the daily outage matrix,
        │                     collect data-quality warnings → Dataset (in-memory cache)
        ▼
apps/dashboard/metrics.py     Business rules: scopes, uptime formula, MTD, buckets,
        │                     trends, circle breakdowns, site table (pure functions)
        ▼
apps/dashboard/serializers.py Parameter validation against the loaded Dataset
apps/dashboard/views.py       HTTP: JSON responses, consistent error envelope
        │
        ▼  REST (JSON)
frontend/src/services/api.ts  Typed client, ApiError with message and details
frontend/src/hooks/           useDashboardFilters (URL state), useApiQuery (abortable)
frontend/src/pages/           DashboardPage, DataSourcePage, DailyIngestionPage
```

No reporting data is stored in the database, and nothing is ever written back to the workbook.

## Backend

| Module | Responsibility |
|---|---|
| `upload.py` / `store.py` | Accept an upload: stage it, check it (`.xlsx` only, size limit, genuine OOXML package, no `vbaProject.bin`, expanded size limit), parse and validate it fully, and only then copy it into the store and atomically replace `active.json`. On any failure the staged file is deleted and the previous workbook stays active. The last 5 accepted uploads are kept. |
| `workbook.py` | Resolve the active workbook (the latest accepted upload; `MASTER_WORKBOOK_PATH` only as a fallback when nothing was uploaded; `Data/reference` is never read). List all sheets, extract the daily and monthly outage columns, and flag formula cells that have no cached result. Read `Up-Time Report` positionally, validate it, normalise report types and circle aliases, return an immutable `Dataset` (sites table plus an outage matrix of sites × dates, NaN = not reported). Cached under a lock and reloaded when the file's mtime or size changes. |
| `metrics.py` | Business rules only, with no HTTP or file I/O. `Selection(report_type, circle, scope)` → summary, trend, weekly, breakdown, site table, site detail, filter options. The planned ingestion pipeline should call these same functions. |
| `serializers.py` | DRF serializers for query parameters. Circles and dates are checked against the dataset, so unknown values return 400 instead of silently falling back. |
| `views.py` | Thin views: load dataset, validate, call metrics, add `filters` and `source` blocks. |
| `apps/common/exceptions.py` | DRF exception handler: every error is `{"error": str, "details": {}}`; unexpected exceptions are logged and returned as a generic 500. |
| `apps/common/views.py` | Health check; raw file upload (extension and size limits, sanitised names, never overwrites); raw file list. |

### API

All endpoints are `GET` under `/api/dashboard/` unless noted. Common parameters: `report_type` (`4G Saturation` | `LWE`; `4G Satu.` is accepted), `circle`, `scope` (`on_air` default | `om_start` | `all`).

| Endpoint | Extra parameters | Returns |
|---|---|---|
| `filters/` | — | report types, circles (with the report types they belong to), scopes, buckets, reporting dates, default date and trend range, month, source |
| `summary/` | `reporting_date` (default latest) | snapshot and MTD metrics, MTD window |
| `trends/` | `start_date`, `end_date` (default: reported range, max 92 days) | daily series (per report type), weekly uptime (per report type, change vs previous week) |
| `breakdowns/` | `reporting_date` | per (report type, circle): daily and MTD uptime, buckets; bucket totals |
| `records/` | `reporting_date`, `search`, `bucket`, `sort`, `direction`, `page`, `page_size` (≤100) | paginated site rows |
| `records/<site_id>/` | `report_type` (needed if the ID exists in both types) | site attributes, daily history, MTD bucket |
| `source/` | — | workbook info, site counts, reported, missing and unreported dates, validation warnings, sheets |
| `workbook/` (GET) | — | active workbook (name, upload time, sites, circles, dates, warnings, sheets), or `active: null` |
| `workbook/` (POST) | multipart `file` | 201 with the new active workbook, or 400/413/422 with `details.problems`; the previous workbook stays active |
| `monthly/` | `reporting_date` | uptime per month (combined and per report type, change vs previous month) plus the current month to date, and an `overall` pooled figure |
| `teams/` | `reporting_date`, `group` (`ci` \| `ie`) | uptime per CI or IE, worst MTD first |
| `thresholds/` | `reporting_date` | sites ≥ 98.5% and < 60% (count and % of scope) per circle and Grand Total for every month, MTD, week and reported day |
| `period/` | `period` (`range` \| `days` \| `weeks` \| `months`), `start_date`, `end_date`, `days`, `weeks`, `months` | uptime, outage minutes and sites below 60% / at 98.5%+ for the selected trend period |
| `alerts/` | — | ranked alerts for the latest reporting date (`critical` → `warning` → `info`) with an in-app link each; the header bell shows the top 3 |
| `/api/health/` | — | service status |
| `/api/auth/csrf/`, `login/` (POST), `logout/` (POST), `me/`, `password/` (POST), `users/…` (Admin) | see [security.md](security.md) | sign-in, password change, user management. Every other endpoint needs a signed-in portal user |
| `/api/upload/` (POST), `/api/raw-files/` | — | raw file storage and preview (inspection only) |
| `/api/arrival-tracker/?date=&start=&end=` (GET, Admin) | see [csv-arrival-tracking.md](csv-arrival-tracking.md#data) | Stored daily-data coverage and raw CSV uploads per project/circle and date; read only |
| `/api/email/status/`, `reminder-template/`, `reminder/` (POST), `send/` (POST) | see [csv-arrival-tracking.md](csv-arrival-tracking.md#email) | CSV reminders and personal emails; console backend (test mode) by default |

Status codes: 200 OK; 400 invalid parameters (with field `details`); 404 unknown site; 413 upload too large; 422 workbook rejected; 503 no or unreadable workbook (`details.code` = `no_workbook` / `invalid_workbook`); 500 unexpected (generic message).

## Frontend

- **Filter model.** `useDashboardFilters` keeps report type, circle, scope, reporting date and trend range in the URL. Values the workbook doesn't offer are ignored. Snapshot endpoints (summary, breakdowns, records) receive `reporting_date`; the trend endpoint receives `start_date`/`end_date`. Calculations happen only in Django; React formats.
- **Active workbook.** `WorkbookProvider` holds the active workbook status. Its `version` (name + upload time) is part of every query key, so after an upload every panel refetches and no data from the previous workbook can remain on screen. With no workbook the dashboard shows an upload prompt and makes no data requests.
- **Stale responses.** `useApiQuery` aborts the previous request whenever its key (the serialised parameters) changes, so an older response can't overwrite a newer selection.
- **Failure isolation.** Each panel has its own loading, error and empty state (`ChartCard`), so one failing endpoint doesn't blank the page. If the workbook itself is unavailable, the page shows the backend's message and no data.
- **Accessibility.** Radix-based selects and sheet (keyboard and ARIA), sortable headers with `aria-sort`, keyboard-openable rows, skip link, and a "Show data table" alternative under every chart.
- **Code splitting.** Pages are lazy-loaded, so Recharts is loaded only with the dashboard.

## Design decisions

| Decision | Reason |
|---|---|
| Upload replaces the dataset only after full validation | A failed or partial upload can never blank or corrupt the dashboard. Single-user local phase: files on disk plus an atomic pointer, no database or job queue. |
| Formulas are never trusted blindly | pandas/openpyxl read cached formula results and do not recalculate. The dashboard recalculates every KPI from raw outage minutes and flags formula cells without cached values. |
| Read the workbook directly instead of importing it into PostgreSQL | The workbook remains the source of truth in this phase; there's no requirement for persistent copies yet. The `Dataset` boundary allows a database-backed source later without changing `metrics.py`. |
| In-memory cache keyed by file mtime and size | Parsing takes about 10 s; every request after the first is fast, and edits to the workbook are picked up automatically. Each server process holds its own copy (about 2 MB for 6.7k sites × 31 days). |
| Read columns by position | Header labels repeat (dates twice, `Bucket` many times). Label-based reading previously picked the wrong date block. |
| Outage minutes rather than the derived uptime block | The derived block shows 100% for unreported days. |
| Blank = not reported | Avoids inventing 100% uptime; matches the workbook whenever data is complete. |
| No authentication yet | Single-user local phase. Must be added before any shared deployment. |

## Future ingestion pipeline (not implemented)

The intended flow reuses the existing layers: upload → validate (reporting date, circle, LWE ID mapping, 2100 MHz selection, duplicates, unmatched IDs, out-of-range availability, stale files) → normalised daily outage rows → a `Dataset` built from processed data instead of the workbook → the same `metrics.py`. Processing history and validation reports would live in PostgreSQL, behind authentication.
