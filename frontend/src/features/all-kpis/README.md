# All KPI's (optional module)

A self-contained page (`/all-kpis`, sidebar "All KPI's") with consolidated 4G Saturation and LWE KPIs: site portfolio,
availability (day / week / month), outage and USD, SLA thresholds and NSLA, RCA Final Buckets, reporting completeness,
and the Circle → CI/Cluster → IE → Site drill-down. It reads existing data only. It has no database tables, migrations or
settings of its own, and no other module depends on it.

## Files

| Frontend (`frontend/src/features/all-kpis/`) | Purpose |
|---|---|
| `AllKpisPage.tsx` | Page, tabs, KPI groups, period and data-limitation notices |
| `useKpiFilters.ts` | Filters kept in the URL (multi-select, cascading Circle → CI → IE → Site) |
| `api.ts`, `types.ts`, `format.ts` | API calls, response types, value formatting (null = "Not available", never 0) |
| `status.ts` | Display-only status colours (see below) |
| `components/` | `KpiFilters`, `MultiSelect`, `KpiCards`, `KpiTable` (+ `Pager`), `TrendPanel`, `ComparisonTable`, `DrillDown` (+ `SitesTable`), `RcaPanel` |
| `AllKpisPage.test.tsx` | Frontend tests |

| Backend (`backend/apps/allkpis/`) | Purpose |
|---|---|
| `services.py` | All calculations (read-only) |
| `views.py`, `urls.py` | Endpoints under `/api/all-kpis/` |
| `README.md` | Points here |
| `backend/tests/test_allkpis.py` | Backend tests |

## API (read-only, GET)

| Endpoint | Returns | Permission |
|---|---|---|
| `/api/all-kpis/filters/` | Dates with daily data, projects, circles, CIs, IEs, sites (cascading), buckets, Final Buckets | Dashboard View |
| `/api/all-kpis/summary/` | KPIs of the period and of the same number of days before | Dashboard View |
| `/api/all-kpis/trends/?granularity=day\|week\|month` | Trend points | Dashboard View |
| `/api/all-kpis/hierarchy/?level=circle\|ci\|ie` | KPI rows per circle, CI or IE | Dashboard View |
| `/api/all-kpis/sites/` | Site-wise rows (search `q`, `sort`, `page`) | Dashboard View |
| `/api/all-kpis/rca/` | RCA records by the 10 approved Final Buckets, Not mapped, by circle | RCA Summary View |

Filters (all endpoints): `date_from`, `date_to`, and comma-separated `project`, `circle`, `ci` (`circle::CI`),
`ie` (`circle::CI::IE`), `site`, `bucket`, `final_bucket` (RCA only). Every figure is limited to the user's projects
and circles (`dashboard.scope.restrict`, `rca.services.filtered`).

## Data and calculations (existing code reused, not changed)

- **Daily records:** the dashboard dataset `uptimedb.datasource.current_dataset()` (current month plus earlier months'
  `daily_history`). Weekly and monthly figures are derived from these daily records, **not** from
  `SiteMonthlyPerformance` totals.
- **Availability:** `metrics.uptime_pct` = 100 × (1 − Σ outage ÷ (1,440 × reported site-days)), outage-weighted over
  On-Air sites; never an average of daily percentages.
- **Thresholds:** `metrics.bucket_ids` on each site's availability over the period. Exactly 98.5% counts as
  "98.5% and above".
- **USD sites (approved for this module):** distinct O&M Start sites with outage > 0 on at least one day of the period.
- **NSLA sites (approved):** distinct O&M Start sites with daily availability strictly below 98.5% on at least one day.
  Exactly 98.5% does not qualify; a missing value never does.
- **O&M Start:** `SiteMonthlyPerformance.om_start` of each day's own month, read directly. A month without values shows
  "Not available"; no other month is carried forward.
- **Missing availability:** a site-day without a value is a reporting gap (Data Completeness tab), never 0%.
- **RCA:** `rca.services.filtered` plus the approved Final Bucket mapping `rca.breakdown.FINAL_BUCKET_CATEGORIES`.
  Values outside it are "Not mapped".

## Display conventions (no effect on any value)

- **Status colours** (`status.ts`), using the existing thresholds only: availability green at 98.5% and above, amber below
  98.5%, red below 60%. Reporting coverage is amber below 100%. Counts of problem sites (USD, NSLA, below 98.5% / 60%,
  missing site-days) are amber or red only when above zero. In tables only amber and red are shown.
- **Comparison chips** only when both periods have a value: green when better, red when worse (more outage is worse).
- **Unavailable or pending values** use a neutral dashed card with the reason, never 0.
- **Charts:** one colour per series on every chart (availability = primary, USD = amber, NSLA = red), a dashed 98.5% SLA
  line, no animation.

## Pending (shown as such in the page)

- **Site Handover Status:** not defined yet.
- **Own / Customer / Third Party / Pending:** no approved mapping; shown as "Not Configured".
- **O&M Start for November 2026:** no source data yet, so "Not available".

## Dependencies

None added (recharts, radix/shadcn and lucide were already installed). The only shared-code change is `export` added
to `request()` in `src/services/api.ts`: no behaviour change, and harmless to keep after removal.

## Removing the module

1. Delete `frontend/src/features/all-kpis/` and `backend/apps/allkpis/` and `backend/tests/test_allkpis.py`.
2. Revert one line in each of these files:
   - `frontend/src/App.tsx`: the `AllKpisPage` lazy import and the `/all-kpis` route.
   - `frontend/src/components/Sidebar.tsx`: the "All KPI's" entry and the `LayoutGrid` icon import.
   - `frontend/src/lib/pageTitles.ts`: the `/all-kpis` title.
   - `frontend/src/context/auth.ts`: `'/all-kpis': 'dashboard.view'`.
   - `backend/config/urls.py`: `path('api/all-kpis/', ...)`.
3. Remove `"All KPI's"` from the expected link lists in `frontend/src/components/Sidebar.test.tsx` and
   `frontend/src/pages/auth/Auth.test.tsx`.
4. Optional: `export` on `request()` in `frontend/src/services/api.ts` can stay.
5. Run `npx tsc -b --noEmit`, `npm test`, `npm run build` and `manage.py check` / `manage.py test tests`.

No database change is needed: the module never created tables, migrations or records.
