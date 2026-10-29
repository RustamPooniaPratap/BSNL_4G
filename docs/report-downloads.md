# Report downloads (Excel)

The **Download report** panel is on **Data Entry → Upload CSV**. (The former Raw Daily Records Export, `GET /api/raw-uploads/export/`, was removed on 29 Oct 2026.)

## Controls

| Control | Values |
|---|---|
| Report type | **Daily Uptime Report** or **Full Consolidated Report** |
| Project | All Projects, 4G Saturation, LWE |
| Circle | All Circles, or one of the user's circles. The list is limited to the chosen project; with All Projects, each circle appears once |
| Date | Daily: exactly one reporting date (current month, or an earlier month with daily values). Full: "Month to date, up to" a reported date of the current month (the latest by default) |
| Download | Fetches the file. A server error is shown in the panel and nothing is downloaded |

Both reports read the **active data source** (`current_dataset()`: Excel workbook or PostgreSQL). Exporting never changes the source setting. The server applies the user's circles (`accounts.scope.allowed_circles`): a CI user gets only assigned circles, and asking for another circle answers 403.

## Endpoints

| Endpoint | Parameters |
|---|---|
| `GET /api/dashboard/export/daily/` | `date` (required), `report_type`, `circle` |
| `GET /api/dashboard/export/consolidated/` | `reporting_date` (default: latest), `report_type`, `circle` |

Errors are JSON:
- 400: unknown circle, or a date that isn't reported;
- 403: a circle outside the user's scope;
- 404: no sites or no values for the selection.

File names:
- `Daily_Uptime_<project>_<circle>_<date>.xlsx`
- `4G_LWE_Consolidated_Report_<project>_<circle>_<Mon-YYYY>_to_<date>.xlsx`

## Daily Uptime Report

One sheet, one row per site of the selection.

Columns: Site ID, Site Name, Project, Circle, Reporting Date, Outage Minutes, Availability (%), Uptime Bucket.
- Availability = 1 − outage ÷ 1,440, computed with `metrics.site_uptime`.
- The bucket uses the workbook thresholds (`metrics.BUCKETS`).
- A site without a value on the date shows blank minutes and availability, and the bucket **Not reported**. It is never shown as 0.
- If no site of the selection has a value on that date, the server refuses (404).

## Full Consolidated Report

### Template
- The 13 sheets keep the consolidated workbook's names, order and visibility (6 hidden).
- The template is `backend/apps/dashboard/report_templates/consolidated_template.xlsx`. It was built once by `manage.py build_report_template <workbook>` from `Data/reference/4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (29 Oct 2026).
- It keeps styles, column widths, merged cells, freeze panes and headers. It holds no report data: no site rows, numbers, dates, formulas, names or phone numbers. A test checks this.
- The application never reads the source workbook or `ref/`.

### Up-Time Report
One row per site in scope.
- **A:U:** project, circle, site details, On-Air, EB, OD EB status, Solar date, O&M Start for the last 7 months, IE/CI and contacts.
- **Monthly blocks per history month:** FF count, outage, uptime, bucket.
- **Current month:**
  - FF count (`COUNTIF >0`), outage (`SUM`), uptime and bucket, as formulas;
  - each date's outage, filled up to the reporting date;
  - Wk-1..Wk-4 outage and uptime, as formulas;
  - each date's uptime, as a formula.
- **Formulas:** they divide by the number of reported days (`COUNT`), not a fixed day count, so blanks are never read as 0. Row-1 `SUBTOTAL`s cover exactly the exported rows.
- **Formatting:** filter on, panes frozen, duplicate IDs highlighted.

### Calculated sheets
These are calculated on the server for the same sites, with the dashboard rules: pooled outage over reported site-days, and workbook buckets. A period with no values is left blank.

| Sheet | Content |
|---|---|
| Summ | Per project: Overall Up-Time (On-Air), O&M Start Up-Time, Less than 60% trend, Overall and O&M outage minutes. Every history month plus the month to date, with a Grand Total |
| Uptime Bucketization | Bucket counts per month for O&M Start sites: all of the selection, then one table per circle |
| Day wise Trend | On-Air and O&M Start uptime per circle, by week and by date |
| All Circle - 98.5 / Below 60 | O&M Start sites per circle: count and % at or above 98.5% (or below 60%) for the last 3 months, month to date, weeks and dates |
| OD - EB & NEB | OD 4G On-Air uptime for EB and N-EB sites (last 3 months and daily), when OD 4G is in scope |
| CI's / IE's Performance | Per circle and person: site count, O&M Start count, month-to-date uptime and outage of their O&M Start sites |

### Not generated
Repeated Sites, Signoff status, Bucketization (RCA vendor buckets) and One Pager Summary are maintained by hand in the workbook. The application holds no data for them. They keep their headers and a note saying so; nothing is filled in. The same applies to OD's "unique site down" rows.

### Differences from the hand-made workbook
- **Summary layout:** tables are rebuilt for the circles in scope, stacked vertically per project. They keep the template's styles, but not every side-by-side position.
- **Summ chart:** not included. Charts don't survive the template copy.
- **Values instead of formulas:** the summary sheets hold values. The workbook mixed live formulas, fixed ranges such as `$A$4547:$A$6728`, and typed-in history, and those break once filtered.
- **Unreported days:** excluded from uptime. The workbook counts them as 0 outage; see business-rules.md.
