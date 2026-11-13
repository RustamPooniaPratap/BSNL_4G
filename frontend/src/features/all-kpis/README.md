# All KPI's (optional module)

A self-contained page (`/all-kpis`, sidebar "All KPI's") with consolidated 4G Saturation and LWE KPIs: availability
(day / week / month), outage and USD Sites, SLA thresholds and NSLA Sites, RCA Final Buckets,
and the Circle → CI/Cluster → IE → Site drill-down. It reads existing data only. It has no database tables, migrations or
settings of its own, and no other module depends on it.

## Files

| Frontend (`frontend/src/features/all-kpis/`) | Purpose |
|---|---|
| `AllKpisPage.tsx` | Page: sticky filters, horizontal KPI tab bar, title card (with the reporting period), views (Overview, KPI trends, the KPI views, Ranking, RCA, drill-down) |
| `allkpis.css` | The reference report's design (colours, cards, tiles, tables, tabs), every rule scoped under `.akp` |
| `kpis.ts` | The KPI views: response field, format, direction and existing definition of each (no calculation) |
| `useKpiFilters.ts` | Filters kept in the URL (multi-select, cascading Circle → CI → IE → Site) |
| `api.ts`, `types.ts`, `format.ts` | API calls, response types, value formatting (null = "Not available", never 0) |
| `status.ts` | Display-only status colours (see below) |
| `components/` | `KpiFilters`, `MultiSelect`, `KpiCards`, `KpiTable` (+ `Pager`), `TrendPanel`, `TrendsView`, `ComparisonTable`, `DrillDown` (+ `SitesTable`), `UnitTable`, `KpiView` (+ `LevelCard`), `KpiNav`, `RcaPanel`, `Ui` and `theme` (page building blocks) |
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

- **Daily records:** the new data layer (`sitedata.dashboard_source`: Consolidation Matrix sites and the central daily
  table). Weekly and monthly figures are derived from these daily records.
- **Availability:** `metrics.uptime_pct` = 100 × (1 − Σ outage ÷ (1,440 × reported site-days)), outage-weighted over
  On-Air sites; never an average of daily percentages.
- **Thresholds:** `metrics.bucket_ids` on each site's availability over the period. Exactly 98.5% counts as
  "98.5% and above".
- **USD Sites** (shared rule B-3, `metrics.usd_dates`): distinct sites of the selected population with outage > 0 on at
  least one reported day of the period. A count of sites, not of outage events.
- **NSLA Sites** (`metrics.nsla_dates`): sites of the population whose uptime over the period, pooled over their reported
  days, is below 98.5%. Exactly 98.5% does not qualify; a missing value never does.
- **O&M Start:** `SiteMonthlyPerformance.om_start` of each day's own month, read directly. A month without values shows
  "Not available"; no other month is carried forward.
- **Missing availability:** a site-day without a value is a reporting gap, never 0%.
- **RCA:** `rca.services.filtered` plus the approved Final Bucket mapping `rca.taxonomy.approved_final`.
  Values outside it are "Not mapped".

## Display conventions (no effect on any value)

- **Layout** (13 Nov 2026) follows the reference report "4G_KPI_Report (2) 6.html": sticky filter bar, one
  horizontal KPI tab bar under it (KPIs, then Analysis; live values as badges; sticky; scrolls sideways), title card with the scope breadcrumb and "Data checks", tiles, stat strips,
  ranked unit tables (previous value and rank from the same endpoints with the summary's comparison period; the three
  lowest shaded), weakest-15 bars and sparklines. The portal's Geist font is kept.
- **Not shown (no data or no approved rule):** USD events, MTTR, sites down now, long-down and repeat sites, at-risk,
  planned outage, tickets, site categories and SLA targets per category, the composite score, Gross / Net SLA and the
  Own / Customer / Third-party split, the unit-by-period trend table, and the reference's import, sample data, template,
  export, print, settings, e-mail and letter features.

- **Status colours** (`status.ts`), using the existing thresholds only: availability green at 98.5% and above, amber below
  98.5%, red below 60%. Reporting coverage is amber below 100%. Counts of problem sites (USD, NSLA, below 98.5% / 60%,
  missing site-days) are amber or red only when above zero. In tables only amber and red are shown.
- **Comparison chips** only when both periods have a value: green when better, red when worse (more outage is worse).
- **Unavailable or pending values** use a neutral dashed card with the reason, never 0.
- **Charts:** one colour per series on every chart (availability = primary, USD = amber, NSLA = red), a dashed 98.5% SLA
  line, no animation.

## Pending (shown as such in the page)

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
- **Removed from this page (13 Nov 2026):** the navy title banner (its period details are in the title card), the
  Reporting / Data Completeness view and the Site Portfolio cards. The separate Site Portfolio page is unchanged. The
  overview shows its KPI tiles in one grid: five per row on desktop, three on medium, two on small, one on narrow screens.
- **Final refinement (13 Nov 2026):** every filter in one compact row on desktop (flexible widths with minimums; it wraps
  only when the screen is too narrow, Reset as an icon at the end); the tab bar in three groups (Overview & Reports,
  Performance KPIs, Analysis); no heading card on the overview (only its O&M Start data check, for the O&M Start
  population); reporting coverage, missing site-days and the site status columns (Total / On-Air / O&M Start, Days
  reported) removed from every table, chart and trend of this page.
