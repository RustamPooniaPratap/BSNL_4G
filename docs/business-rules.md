# Business rules and KPI definitions

The rules below reproduce the Master workbook's own summary formulas. Each was reconciled against the workbook's cached values (see [Reconciliation](#reconciliation)). Implementation: `backend/apps/dashboard/metrics.py`.

## Core formula

```
uptime % = 100 × (1 − Σ outage minutes ÷ (1,440 × site-days reported))
```

This is **outage-weighted**: a pooled ratio over all site-days, not an average of per-site percentages. For a fixed set of sites that all report every day, the two are equal, which is why the workbook's `AVERAGE` of daily values for weeks gives the same result.

**One deliberate difference from the workbook:** the workbook's `SUM` treats a blank cell as 0 minutes of outage (100% uptime) and divides by a hand-typed day count. The application treats a blank as *not reported*: it is left out of the denominator and shown as missing coverage. With the Oct'26 data (no blanks on reported days) both approaches give identical results.

## Scopes

| Scope | Rule | Workbook equivalent |
|---|---|---|
| On-Air sites (default) | `On-Air` = `Yes` | "Overall Up-Time" (Summ col. K, Day wise Trend rows 4–7) |
| O&M Start sites | `O&M Start - <month>` = `Yes` | "O&M Start - Up-Time" (Summ col. S) |
| All sites | every row of the report type | Used for LWE in Uptime Bucketization rows 11–21 |

## KPIs

| Metric | Definition | Source columns | Aggregation | Missing data | Unit |
|---|---|---|---|---|---|
| Sites in scope | Sites matching report type, circle and scope | A, B, G or K | count | — | sites |
| Sites in total | Sites matching report type and circle, any scope | A, B | count | — | sites |
| Reporting coverage | sites with a value on the date ÷ sites in scope | daily outage column | ratio | blank = not reported | % |
| Daily uptime | core formula over sites in scope on the date | daily outage column | pooled | blanks excluded | % (2 dp) |
| MTD uptime | core formula from the 1st of the month to the selected date | BT … selected date | pooled | blanks excluded; unreported days listed | % (2 dp) |
| Outage minutes on date | Σ outage minutes on the date (card also shows the MTD total) | daily outage column | sum | blanks excluded | minutes |
| Sites down all day | sites with outage ≥ 1,440 on the date | daily | count | — | sites |
| Sites with no outage | sites with outage = 0 on the date | daily | count | — | sites |
| Site MTD bucket | each site's MTD uptime: `<60`, `60–<90`, `90–<97`, `97–<98.5`, `≥98.5` | BT … date | per site, then count | site with no data: no bucket | sites |
| Sites below 60% MTD | sites in the `<60` bucket | — | count | — | sites |
| Weekly uptime | core formula for days 1–7, 8–14, 15–21, 22–end (workbook `Wk-1..4`) | daily | pooled | only reported days; unreported weeks shown as "Not reported" | % |
| Combined (4G + LWE) | core formula over both report types together | — | pooled | — | % |

Bucket thresholds come from the workbook formula `=IF(x>=98.5%,">98.5",IF(x>=97%,">97 To <98.5",IF(x>=90%,">90 To <97",IF(x>=60%,">60 To <90","<60"))))`. A value of exactly 98.5% is in the top bucket.

| Monthly uptime | core formula per month: Σ `<Mon-YY> Outage Min.` ÷ (1,440 × days in month × sites with a value) | V:BO monthly outage | pooled | blank months excluded; the workbook's "blank = 100%" figure is also returned | % |
| Overall (whole period) | core formula pooled over every month shown (monthly history + current month to date) | V:BO + daily | pooled | months/sites without values excluded | % |
| Change vs previous period | uptime minus the previous week/month that has data | — | difference | periods without data are skipped | percentage points |
| CI / IE performance | core formula over the sites whose `CI Name` / `IE Name` is the person; blank or `-` grouped as Unassigned | R, T | pooled | as daily/MTD | % |
| Daily site bucket | each site's uptime on the selected day, bucketed with the same thresholds | daily | per site, then count | not reported: no bucket | sites |

**Combined (4G + LWE)** is the one figure the workbook never shows. It's shown when "All report types" is selected, always with the per-type lines alongside it in the trend chart.

## Reconciliation

Method: automated tests (`backend/tests/test_reconciliation.py`) load the real Oct'26 workbook, compute each figure with `metrics.py`, and compare it with the value cached in the workbook (computed by Excel). They run whenever the workbook is present and are skipped otherwise. Result on 22 Oct 2026, against both workbook revisions: **all pass**.

| Workbook cell(s) | Figure | Workbook | Application |
|---|---|---|---|
| Summ C5:D7, L5:L7 | 4G site counts (total / On-Air / O&M) MP, RJ, OD | 1483/1351/1332, 1458/1362/1316, 1603/1536/1482 | identical |
| Summ K5, K6, K7, K8 | 4G MTD uptime, On-Air: MP, RJ, OD, total | 93.07%, 95.43%, 91.18%, 93.14% | 93.07%, 95.43%, 91.18%, 93.14% |
| Summ S5, S8 | 4G MTD uptime, O&M Start: MP, total | 93.22%, 93.42% | 93.22%, 93.42% |
| Summ K30, S32, S33 | LWE MTD uptime: BH On-Air, JH O&M, MP O&M | 96.46%, 92.20%, 97.25% | identical |
| Day wise Trend H4, H5, U6 | 4G daily uptime: MP 1 Oct, RJ 1 Oct, OD 14 Oct | 89.60%, 97.09%, 88.85% | identical |
| Day wise Trend D11, E11 | 4G MP weekly uptime, O&M | 91.64%, 94.80% | identical |
| Uptime Bucketization C4:G6 | 4G buckets, O&M scope: MP, OD, RJ | 31/260/288/120/633, 69/319/315/86/693, 17/143/237/136/783 | identical |
| Uptime Bucketization C11:G11 | LWE BH buckets, all sites | 1/26/53/29/141 | identical |

### Trend views

The **Trend period** control in the filter bar chooses what the trend card shows; the kind of period also sets the chart view:

| Period | View | URL | Notes |
|---|---|---|---|
| Date range | Daily | `from`, `to` | Every day in the range (reporting month only) |
| Specific dates | Daily | `days=2026-10-01,2026-10-08` | Only the picked days, joined by straight lines; the daily outage chart shows the same days |
| Weeks | Weekly | `trend=weekly&weeks=1,2` | Workbook weeks 1–7, 8–14, 15–21, 22–end; empty = all. Change is against the previous week shown |
| Months | Monthly | `trend=monthly&months=2026-04,2026-10` | Any months of history plus the current MTD; empty = all. The API recomputes *overall* and month-to-month change for the months picked |

All views split by report type when "All report types" is selected. The **Outage minutes** chart under the uptime trend follows the same view and period (its own Daily / Weekly / Monthly switch moves both charts): total outage minutes per day, per workbook week (reported days only) or per month (the current month to date as the last point), combined and per report type. A period with no reported value is shown as a gap, never as zero. Days and weeks exist only for the reporting month, because the workbook holds daily values only for that month. Unknown dates, weeks or months in the URL are ignored by the page; the monthly API rejects unknown month keys (400).

**KPI cards vs Trend period.** The six KPI cards are a snapshot for the **Reporting date** (daily, and MTD from the 1st to that date); report type, circle, scope and reporting date change them. The **Trend period** card under them (`metrics.period_summary()`, endpoint `period/`) is shown on the 4G Saturation and LWE pages (a report type is selected), not on the Overview, and covers exactly the selected trend period:
- **Uptime:** all outage minutes ÷ (1,440 × all site-days reported in the period). For months this is the same pooled figure as the monthly chart's *Overall*.
- **Outage minutes:** the total for the period.
- **Sites below 60% / at 98.5% or above:** each site's own uptime over the whole period, using the workbook bucket edges.
- **Months:** month totals ÷ (1,440 × days in month) for sites with a value; the current month's key means its reported days so far.

### Circle comparison on the uptime and outage charts (Overview, 4G, LWE)

- **Data:** `trends/` (days and weeks) and `monthly/` also return one series per circle within a network (`by_circle`, `outage_by_circle`, keyed `"<report type>|<circle>"`), plus the list `circles`.
  - The series use the same formula as the totals, over that circle's own sites. A circle with no value in a period is `null` and drawn as a gap, never 0.
  - MP 4G and MP LWE are separate series.
- **Picker:** **Compare circles** above the two charts offers only the circles in the current data (only LWE circles on the LWE page). It has All and Clear, a checkbox per network (4G, LWE) that selects or clears all its circles (partly ticked when some are chosen), and the choice is kept in `?series=`.
- **Default:** every circle when there are at most 5 (the 4G page has 3). Otherwise the overall and per-network lines, so the Overview and LWE charts open uncluttered.
- **Chart behaviour:** the date, week and month filters apply unchanged. With circles chosen, only their series are drawn: the overall line and its data-table column are hidden. With none chosen, the overall and per-network lines return.
- **Colours:** each circle has a fixed colour on every page.
- **Reporting coverage:** the card was removed from these pages (24 Oct 2026). The `coverage_pct` metric is still used by Site Portfolio and Data source & quality.

### Header alerts

Computed by `metrics.alerts()` for the latest reporting date, On-Air scope, all report types. Only workbook thresholds and facts about the data are used:

| Alert | Severity | Rule |
|---|---|---|
| Calculation mismatch | critical | A workbook summary figure differs from the dashboard's calculation (see *Calculation check*); listed first |
| Sites down all day | critical | On-Air sites with outage ≥ 1,440 minutes on the latest date |
| Sites below 60% this month | critical | On-Air sites in the workbook's `<60` MTD bucket |
| Data age | warning | Latest reporting date more than 1 day before today (India time) |
| Sites not reported | warning | On-Air sites without a value on the latest date |
| Data-quality findings | warning | Each validation warning from the workbook load |
| Lowest circle | info | Circle with the lowest MTD uptime |

The bell shows the count of critical + warning alerts and lists every alert grouped by priority (critical, warning, information); each links to the relevant view (for example `/?bucket=lt_60` opens the site table filtered to that bucket).

### Threshold Analysis (`/thresholds`)

Reproduces the workbook sheets **`All Circle - 98.5`** (count table `B3:AQ17`, percentage table `B19:AQ33`) and **`All Circle - Below 60`** (same ranges), computed by `metrics.threshold_analysis()` (endpoint `thresholds/`).

- **Population:** sites in the selected scope. The page defaults to **O&M Start**, the workbook's population (`COUNTIFS(... 'Up-Time Report'!K:K,"Yes", ...)`, K = `O&M Start - <month>`). The global scope, report type, circle and reporting-date filters apply.
- **Site uptime per period:** 1 − Σ outage ÷ (1,440 × days the site reported), the same formula as everywhere else; thresholds are the workbook bucket edges (`bucket_ids`): **≥ 98.5%** and **< 60%** (98.5% and 60.0% exactly are inclusive / not below).
- **Periods:** each monthly history column (`<Mon-YY> Outage Min.` ÷ 1,440 × days in month); **MTD** = 1st to the reporting date; **weeks** = days 1–7, 8–14, 15–21, 22–end, counting only days up to the reporting date (a week in progress is marked partial); **daily** = each reported date up to the reporting date.
- **Percentage** = count ÷ all sites in scope in the row (the workbook's denominator). A site with no value in a period is not counted; a row or period with no reported value is shown as "—", never 0.
- **Grand Total** is computed over all sites in scope and equals the sum of the circle rows (tested).
- **All five buckets** (`thresholds/` returns every bucket per row and period, plus `buckets` with their bounds). The bounds follow the workbook's Bucket formula in Up-Time Report (`IF(x>=98.5%,">98.5",IF(x>=97%,…,IF(x>=90%,…,IF(x>=60%,">60 To <90","<60"))))`): each **lower bound is inclusive**, so exactly 60% falls in "60 to <90" even though the workbook labels it ">60". The buckets are <60, 60–90, 90–97, 97–98.5 and ≥98.5.
- **Period vs period (filters `Period` and `Compare with`, URL `period` and `vs`):**
  - Each picker offers every period with reported data: MTD, each month, each week and each date, all from the one `thresholds/` response.
  - A site is bucketed by its uptime over the chosen period.
  - The default comparison is the period of the same kind just before: previous date, previous week or previous month. MTD defaults to the latest month. "No comparison" turns it off.
  - When the two periods cover different numbers of days, the page says so: compare the percentages rather than the counts.
- **Monthly comparison (first on the page; `ThresholdMonthlyTable`):**
  - Columns: the last 7 full months with data (Mar-26 to Sep-26 today), the previous month's MTD and the current MTD. Values are counts or % of sites in scope, per bucket, for the page's filters.
  - Full months come from the `<Mon-YY> Outage Min.` columns (monthly totals), and the current MTD from the reporting month's daily columns. Both come from `thresholds/`.
  - The previous month's MTD covers the same days (1..N, where N is the reporting date's day, shortened for a shorter month). It is computed by `period/` from that month's daily columns and shown as "Not available", with the reason, when the workbook has none (the case for September 2026 today). It is never estimated from the monthly total.
  - Selecting a bucket row draws its line chart across the columns. Periods without data are gaps, not zero.
- **Comparison table (below it):**
  - Each bucket's sites and share in the period and in the comparison period, with the change in sites and in points.
  - A "No value in the period" row and the total. The rows add up to every site in scope, which is tested.
- **Bucket detail:** select a bucket to open one reusable detail view (`?view=<bucket>`), with "All buckets" to go back. The global filters are never changed. The view has:
  - the rule and summary;
  - the KPIs, daily/monthly trend and by-circle chart;
  - each circle's count, share, change and rank within its network;
  - the period table;
  - the affected sites (Site Explorer table filtered to the bucket). Picking a circle narrows only this list. For a date the list uses uptime on that date; for MTD, a week or a month it uses MTD uptime, because `records/` cannot bucket by a week or month yet.

  The summary, by-circle chart and circle changes follow the chosen period and comparison.

  Only <60% is styled as critical.
- **Reconciliation:** MTD counts per bucket match `Uptime Bucketization` C4:G6 (4G MP, OD, RJ, O&M Start), and the per-bucket MTD totals equal the site-bucket breakdown. The `Uptime Bucketization` sheet counts each month's bucket column over **all** LWE rows by fixed row ranges (`$A$4547:$A$6728`); the page uses the selected scope.
- **View affected sites** opens the Overview site table with `bucket=lt_60`, the circle, date and scope; `bucket_basis=daily` filters on uptime on that date instead of MTD.

**Reconciliation (Oct'26 workbook, 14 Oct, `test_reconciliation.py`):** 4G MTD (H4:H6), weeks (I4, J5), daily (M6, Z4), RJ months (E5, G5), LWE week 1 (I7) and daily (M9, Z7) match exactly. Live drill-down: MP 4G below 60% = 86 on 14 Oct (Z4) and 31 MTD (H4).

**Differences found in the workbook sheets (not reproduced):**

1. **Monthly columns (E:G) and every LWE row are typed values, not formulas.** Only the 4G rows' MTD, week and daily cells are `COUNTIFS`. Some typed values no longer match the site data: 4G MP Jul–Sep (98 / 118 / 166 at ≥98.5% vs 113 / 124 / 171 recomputed), 4G OD Jul–Aug, and LWE MTD (e.g. JH 370 vs 354, CG 239 vs 235).
2. **The population column D is typed and inconsistent:** LWE MP uses 22 (all sites) while O&M Start is 19, so the Grand Total population is 6,283 instead of 6,280.
3. **Week 2 is blank for all LWE rows**, so the Grand Total Wk-2 (2,594 / 157) counts 4G only. Recomputed: 3,950 / 226.
4. **Unreported days count as 100%** (`1-outage/(1440*days)` with a blank outage), and weeks 3–4 and dates after the last report show 0 in the Grand Total. The page shows them as no data.
5. **The Week-4 formula uses 10 days in one row and 9 in the next** (`Up-Time Report!DF3` vs `DF4`).

### Team performance and responsibility (`/teams`)

- Each site is the responsibility of the **CI** and **IE** named in its `CI Name` / `IE Name` cells. Blank, `-` or `0` is shown as **Unassigned** and counted separately.
- A team row is one name within one report type and circle, using the same uptime formula as every other figure. KPI counts ("CIs", "CIs with sites below 60%") count distinct people, so a CI covering two circles counts once.
- Bucket mix and "Sites <60%" use each site's MTD uptime and the workbook bucket thresholds. For a CI the page lists the IEs under it; for an IE, the CI(s) it reports to.
- The site list defaults to sites below 60% MTD with their IE and CI. Every IE/CI name in a site table or site panel links to that person's team page (`/teams?group=ie&team=<name>&report_type=…&circle=…`).

### Circle comparison: month to date against the same days of last month

- **What it compares:** each circle's MTD uptime (1st to the reporting date, e.g. 1–14 Oct) against the **same days of the previous month** (1–14 Sep), using the standard formula over reported days, plus the change in points.
- **Source of the previous month's data:** the previous month's **daily outage columns in the same `Up-Time Report`** (for example 1–30 Sep added next to 1–31 Oct).
  - The loader reads the first run of each month's dates as that month's outage block. The second run of the same dates is the derived uptime % block and is ignored.
  - The **latest** month is the reporting month, wherever the columns sit.
  - A previous-month block holding values between 0 and 1 (uptime fractions) is rejected with a warning instead of being read as minutes.
- **Without that month's daily columns:** the chart shows MTD and daily uptime and says the comparison will appear once the daily data is added. Monthly totals are **never** spread over days to estimate it.

### Calculation check

Every time a workbook is loaded, `crosscheck.py` reads the cached results in `Summ` (site counts and `<Mon-YY> MTD` uptime, On-Air and O&M Start) and `Day wise Trend` (daily uptime and fully reported weeks), recalculates each one from the daily outage minutes, and lists the differences on the Data source page (`/data-source#calculation-check`).

- Tables are found by their labels (`Circle`, `Total Site count`, `On-Air Done`, `O&M Start Site count`, `Oct-26 MTD`, `Week-1 (1-7) Oct-26`, date headers), not fixed cells.
- **The population of each `Summ` MTD cell comes from its formula:** the site-count cell it divides by (`$C` Total Site count → all sites, `D` On-Air Done → On-Air, `L`/`R` O&M Start Site count → O&M Start). Formulas are read from the workbook XML, including Excel "shared" formulas copied down a column. Without a readable formula, the column position decides. The formula is shown next to each difference on the Data source page.
- **Major difference:** uptime differs by ≥ 0.5 percentage points, or a site count differs at all (`UPTIME_TOLERANCE_PTS`, `COUNT_TOLERANCE`). This threshold is a proposal; confirm it with the business.
- Days not yet reported and partly reported weeks are skipped (the workbook shows 100% for them). Earlier months are not compared, because their Summ totals are frozen values (see below).
- Oct'26 workbook (11:30 upload): 434 figures checked, 4 major differences: S40, K33, Day wise Trend E7 and E14 (inconsistencies 1, 3 and 6 below). `…_new.xlsx` (15:19 upload): only **K33** remains.
- **Rechecked 22 Oct:** `Summ!K17` (94.95%) was wrongly flagged as On-Air. Its formula divides the outage of all 22 LWE MP sites by all 22 sites (`/(1440*14*$C17)`), so it is the all-sites figure, and the dashboard's all-sites value is 94.9487%, an exact match. `Summ!K33` (94.44%) divides the same 22 sites' outage (`BL15` = 22,403.65 min) by the **20 On-Air** sites (`/(1440*$D33*14)`). The consistent On-Air figure is 16,219.71 ÷ (1,440 × 14 × 20) = **95.98%**. The difference is the 6,184 outage minutes of LWEMP1664 and LWEMP1668, which are not On-Air.

### Monthly history

`Summ!E5:P7` (and the transposed copy in rows 58–81) divide **frozen, pasted monthly outage totals** (`AZ:BK`, not formulas) by today's On-Air count and a hand-typed day count. The application recomputes each month from the site-level `<Mon-YY> Outage Min.` columns with today's flags.

- The frozen totals still equal the site data for some months, and those reconcile exactly (MP Oct-25 71.08%, MP Nov-25 67.97%, RJ Jan-26 90.81%, RJ Sep-26 93.28%, OD Oct-25 68.33%; `test_reconciliation.py`).
- Other months differ by 0.1–3 points (e.g. 4G total Sep-26: workbook 85.13%, recomputed 85.15%; MP Apr-26: 84.25% vs 84.24%), because sites' On-Air flags changed after the month was reported. O&M Start history in the workbook used each month's own O&M flag (columns L:Q), so it differs more.
- The dashboard therefore labels monthly figures as *recomputed with current flags*. Use the workbook's frozen figures where the reported number must be quoted.

## Workbook inconsistencies found (not reproduced)

1. **LWE "Overall" MTD uptime mixes two scopes.** Summ rows 30–39 compute `1 − AX/(1440 × D × days)`. The numerator `AX` (rows 12–21) sums outage for **all** LWE sites, but `D` counts **On-Air** sites only. 4G uses On-Air for both. Example: LWE MP shows 94.44% in the workbook; the consistent On-Air figure is 95.98%. The application uses the consistent rule.
2. **The first LWE table is an all-sites figure under an "Overall Up-Time" heading.** Summ rows 14–23 (column K) divide all sites' outage by Total Site count (`$C`), which is consistent but is the all-sites population, while the 4G table's same column is On-Air. Rows 30–39 divide all sites' outage by the On-Air count (`$D`), which mixes scopes (see 1).
3. **The LWE Grand Total row uses 31 days for every month**, including "Oct-26 MTD" (K40 = `1-AX22/(1440*D40*31)`), which overstates MTD uptime (97.32% shown).
4. **The day count is typed by hand.** `Oct-26 UpTime` = `1-BQ/(1440*14)`, Summ K = `…*14`. These must be edited every day; if they're forgotten, every MTD figure is wrong. The application derives the day count from the data.
5. **Unreported days show 100%.** The derived uptime block (DG:EK) and Day wise Trend show 1 (100%) for 15–31 Oct and weeks 3–4. The application shows these as not reported.
6. **The Day wise Trend 4G Grand Total "Week-2"** averages `O7:V7` (8 days including 15 Oct at 100%) instead of 8–14 Oct.
7. **Monthly day counts are typed by hand and inconsistent.** `Summ!I5` divides Feb-26 by 30 days, `W8` by 28, `W5` by 31; `T5` uses 31 for Nov-25.
8. **Monthly outage totals in Summ are pasted values** (`AZ:BK`), so they don't follow later edits to the site data.
9. **Bucket counts use fixed row ranges** (`$A$4547:$A$6728`), which break silently if rows are added.

## Open questions for the business

| # | Question | Current behaviour |
|---|---|---|
| 1 | For LWE "Overall" uptime, should non-On-Air sites' outage count (as the workbook does) or not? | On-Air sites only, consistent with 4G |
| 2 | How should outage > 1,440 minutes in a day be handled (cap at 1,440, exclude, or correct at source)? | Included unchanged, as in the workbook, and flagged |
| 3 | Is a blank daily value "not reported" or "no outage"? | Not reported (excluded from the denominator) |
| 4 | Is `On-Air` = `0` the same as blank (not On-Air)? | Treated as not On-Air |
| 5 | Which scope should management see by default: On-Air or O&M Start? | On-Air |
| 6 | Is there an availability **target** (for example 98.5%) to report achievement against? | No target applied; the 98.5% bucket is shown as a bucket only |
| 7 | Outage-minute formula for raw CNMC files: is `1440 × (1 − availability/100)` correct for the reporting interval? | **Resolved for 4G Saturation (29 Oct 2026):** for all 1,543 matching Odisha sites of the 13 Oct daily dump, `Nw Avail (4G TCS)` equals the workbook's daily uptime and `1440 × (1 − TCS/100)` equals its outage minutes at full precision. Used by the raw upload (`apps/uptimedb/raw/rules.py`). Not confirmed for LWE. |
| 9 | Should monthly history be shown as reported at the time (frozen Summ figures) or recomputed from current site data? | Recomputed, clearly labelled |
| 10 | Threshold percentages: of all sites in scope (workbook) or of sites that reported in the period? | All sites in scope; sites reported shown on hover |
| 11 | Threshold Analysis population: O&M Start (workbook sheets) or On-Air (rest of the dashboard)? | O&M Start by default on that page; selectable |
| 8 | LWE ID mapping and 2100 MHz selection rules for raw files: where is the mapping reference? | Still open. Raw LWE IDs (e.g. JHDTJN001) differ from the master's (LWEJH0001); the escalation matrix's BTS IDs (B1 21 MHz / B28 7 MHz) are only a candidate. The raw upload validates LWE files but imports no LWE row (`LweResolver`) until the mapping is supplied. |
