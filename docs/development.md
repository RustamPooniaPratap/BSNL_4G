# Development guide (Windows / VS Code)

Commands are for PowerShell in the VS Code terminal, run from the repository root unless stated otherwise.

## Prerequisites

- Python 3.11 with the virtual environment in `.venv`
- Node.js 22+ and npm
- The consolidated Master workbook (`.xlsx`), uploaded through the UI after starting the app

## First-time setup

```powershell
# Backend
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
# Edit backend\.env: keep DEBUG=True locally and set SECRET_KEY.
.\.venv\Scripts\python.exe backend\manage.py migrate

# Frontend
cd frontend
npm.cmd install
Copy-Item .env.example .env          # VITE_API_BASE_URL=http://localhost:8000/api
```

## Running

```powershell
# Terminal 1: API on http://127.0.0.1:8000
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000

# Terminal 2: UI on http://localhost:5173
cd frontend
npm.cmd run dev
```

Smoke checks:

```powershell
curl.exe http://127.0.0.1:8000/api/health/
curl.exe "http://127.0.0.1:8000/api/dashboard/summary/?report_type=4G%20Saturation&circle=MP"
curl.exe http://127.0.0.1:8000/api/dashboard/source/
```

## Loading the Master workbook

1. Open http://localhost:5173/workbook (or **Upload workbook** in the header).
2. Choose or drop the consolidated `.xlsx`. Validation takes about 10–20 seconds.
3. If accepted, every dashboard panel switches to the new workbook. If rejected, the page lists the problems and the previous workbook stays in use.

Scripted alternative (same endpoint the UI uses):

```powershell
curl.exe -F "file=@C:\path\to\Master.xlsx" http://127.0.0.1:8000/api/dashboard/workbook/
```

Accepted files are stored in `Data/processed/workbooks/` with `active.json` pointing at the current one. The app never reads `Data/reference/`. After a server restart the active workbook is re-read on the first request (about 10 seconds).

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DEBUG` | `False` | Enable only locally. |
| `SECRET_KEY` | none | Required when `DEBUG=False`. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | |
| `CORS_ALLOWED_ORIGINS` | Vite dev origins | Browser origins allowed to call the API. |
| `DATA_DIR` | `<repo>/Data` | Root for `raw/` and `processed/`. |
| `WORKBOOK_STORE_DIR` | `Data/processed/workbooks` | Accepted Master uploads and `active.json`. |
| `MAX_WORKBOOK_BYTES` | 50 MB | Master workbook upload limit. |
| `MASTER_WORKBOOK_PATH` | unset | Fallback workbook used only while nothing has been uploaded. |
| `RAW_UPLOAD_DIR` | `Data/raw` | Upload destination. |
| `MAX_UPLOAD_BYTES` | 25 MB | Upload size limit. |
| `LOG_LEVEL` | `INFO` | Root log level. |
| `DB_ENGINE`, `DB_*` | SQLite | PostgreSQL settings for future features. |

## Tests and checks

```powershell
# Backend: 134 tests (workbook loading/validation, upload flow and failure cases, business rules,
# API contract, raw uploads, reconciliation against the real workbook when available)
.\.venv\Scripts\python.exe backend\manage.py test tests
.\.venv\Scripts\python.exe backend\manage.py check

# Frontend (from frontend\)
npm.cmd test          # Vitest + Testing Library, 146 tests
npm.cmd run lint      # oxlint
npm.cmd run build     # type-check and production build
```

Backend tests build small synthetic workbooks (`backend/tests/workbook_factory.py`) that mirror the real sheet's layout, so they need no confidential data. The custom test runner (`tests/runner.py`) points the workbook store and raw-upload folders at temporary directories, so tests never see or change the real active workbook. `test_reconciliation.py` reconciles against `RECONCILIATION_WORKBOOK`, else the active upload, else `Data/reference`; it is skipped when none exists, and its expected values apply to the Oct'26 workbook only.

Log lines such as `ERROR django.request: Service Unavailable` during the test run come from tests that deliberately trigger 503 and 500 responses.

## Adding or changing a KPI

1. Implement it in `backend/apps/dashboard/metrics.py` (pure function over `Dataset` and `Selection`).
2. Add a hand-computed test in `backend/tests/test_metrics.py` and, if the workbook has an equivalent cell, a reconciliation test.
3. Expose it from the relevant view, add it to `frontend/src/types/index.ts`, and display it.
4. Document the definition in `docs/business-rules.md`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Dashboard says "No Master workbook loaded" | Upload the workbook on the Master workbook page. |
| Upload rejected: "not a valid Excel .xlsx workbook" | The file is renamed or corrupted; save it from Excel as `.xlsx`. |
| Data source page warns about formula cells without cached results | The workbook was saved without recalculation (e.g. by a script). Open it in Excel, let it recalculate, save, and upload again. |
| "…has no 'Up-Time Report' sheet" / "missing required columns" | The workbook layout changed; see `docs/data-dictionary.md`. |
| UI shows "The reporting API could not be reached" | Backend not running, or `VITE_API_BASE_URL` / `CORS_ALLOWED_ORIGINS` mismatch. |
| `ImproperlyConfigured: SECRET_KEY must be set` | Set `SECRET_KEY`, or `DEBUG=True` for local work. |
| A new month's workbook shows no O&M Start scope | The `O&M Start - <Mon-YY>` header doesn't match the month of the date columns. |
