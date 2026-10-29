# Site Portfolio (`/portfolio`)

The management landing page, listed first in the sidebar.

**Landing:** opening the app at `/` with no filters lands here (`landsOnPortfolio` in `main.tsx`). Links with filters (`/?bucket=lt_60`, `/?report_type=LWE`) and the sidebar's Overview link still open the Overview, so no deep link changed.

**Sources:** existing endpoints only, with no backend change. No figure is recalculated in the browser.
- `summary/` for the On-Air, O&M Start and all-sites scopes, and for the previous reporting date;
- `summary/` (all sites) for 4G and LWE separately, for the split by network;
- `breakdowns/` and `trends/`.

**Filters:** one compact bar holds the period controls, **Project** (the report type: 4G Saturation or LWE) and **Circle**. Notes on unavailable periods appear in one line under the bar.

## Period filters (`lib/periods.ts`, `components/portfolio/PeriodControls.tsx`)

**Period type: Daily, Weekly or Monthly.** Each type shows only its own pickers, and the comparison is always a period of the same type. All choices are kept in the URL (`view`, `date`, `week`, `month`, `basis`, `vs`), so a refresh or a shared link restores them. Changing the type or the period resets the comparison to its default.

| Type | Selected period | Default comparison | Figures |
|---|---|---|---|
| Daily | A reporting date (calendar input, with previous/next stepping) | The previous date with data | `summary/` at both dates: uptime on the date and MTD to that date (unchanged cards) |
| Weekly | A workbook week (1–7, 8–14, 15–21, 22–end), labelled e.g. "Wk-3 · 15–21 Oct 2026", with previous/next | The week before | `period/` with the week's reported dates |
| Monthly | A month/year grid; **MTD** or **Full month** | The month before, on the same basis | MTD: `period/` with days 1..N; Full month: `period/` with the workbook's monthly total |

- **Coverage, from the workbook only:**
  - daily data for the reporting month;
  - any earlier months whose daily columns are present (`daily_history`);
  - full-month totals for the history months (currently Oct-25 to Sep-26).
- **MTD:** runs from the 1st to the latest reporting day (N). The comparison month uses its own days 1..N, shortened to the month's length (1–28 Feb when N is 30). It is never estimated from a monthly total. The month in progress has no Full month option.
- **Unavailable periods are explained, not replaced.** Examples: "Sep-26 has no daily data in the workbook…", or "No reported days in this week yet". Such periods are disabled in the pickers.
- **Different lengths:** when the two periods cover a different number of days (days with data, or calendar days for full months), the page says so, and outage minutes are not compared.
- **Period-based sections:** the uptime and bucket sections follow the period. Network scope, Site Conversion Progress and the circle-wise table use the current site flags, so the period does not change them. (The period summary box under the filters was removed on 23 Oct; a different-length warning appears in the notes line instead.)
- **Backend additions:** `period/` returns all five `buckets` and accepts dates from earlier months' daily columns. `filters/` lists `daily_history`.

## Layout

One card holds the title ("Site Portfolio · Summary (KPIs)" with the filters and period in words) and the filter bar. KPI cards follow in two sections:

| Section | Cards |
|---|---|
| Site portfolio | **Total sites** (all-sites scope, split 4G · LWE) · **On-Air vs O&M Start**: On-Air, O&M Start (`O&M Start - <month>` = Yes) and Difference = On-Air − O&M Start · **Site Conversion Progress**: **Sites Converted** (On-Air = Yes and O&M Start = Yes on the same site) with its share of all sites, then the follow-up groups *On-Air achieved; O&M Start outstanding or unrecorded* and *On-Air status outstanding or unrecorded* |
| Uptime buckets (MTD) | Sites at 98.5% or above · Sites below 60% · **Uptime bucket mix** split card: all five buckets for On-Air sites with a value |

- **Card anatomy:** every card has a title with its definition (ⓘ), an icon tile, the value with "of N" where there is a denominator, a context line and a "View … →" link.
- **Split cards:** the shares are of the bar's own total, and the parts add up to the big number (tested).
- **Site Conversion Progress** (renamed from Site handover status on 26 Oct 2026):
  - **Sites Converted** = sites with On-Air = "Yes" and `O&M Start - <month>` = "Yes" on the same row, counted by the API (`summary/` field `sites_converted`, over the filter whatever the scope). Shown as the count and its share of all sites in the filter.
  - **On-Air achieved; O&M Start outstanding or unrecorded** = On-Air sites − Sites Converted.
  - **On-Air status outstanding or unrecorded** = all sites − On-Air sites.
  - The three add up to Total sites. A blank or 0 flag means "not recorded yet", a follow-up item, never a confirmed failure.
  - On the card the follow-up groups are labelled **O&M Start pending** and **On-Air pending** (full wording on hover and in ⓘ).
  - **vs <previous month>**: change of each share in percentage points (▲/▼; green when converted rises or a pending group falls). It uses the previous month's `O&M Start - <month>` column with the current On-Air flag (`summary/` field `previous_month_conversion`). On-Air has no month history, so On-Air pending shows "—"; without the previous month's O&M Start column every change shows "—".
  - The workbook has no handover (HOTO) column, and the `Signoff status` sheet (quarterly, circle-level, 4G only) is not read, so this is not a handover-completion figure.
- **Removed on 24 Oct 2026:** the Circles / States and Sites not yet On-Air cards, the decorative icons on the top three cards, and the Uptime section (On-Air and O&M Start uptime, daily uptime, sites down all day) in every period type. Uptime remains on Overview and Threshold Analysis.
- **Sources:** every figure comes from the same endpoints listed above; the new cards add no API calls.

## KPI cards

| Card | Definition | Compared | Opens |
|---|---|---|---|
| Total sites | Site rows for the report type and circle | — | Overview, all sites |
| On-Air sites | On-Air = "Yes" | — (flag has no history) | Overview, On-Air |
| Sites not yet On-Air | Total − On-Air | — | Overview, all sites |
| Sites in O&M Start | "O&M Start - <month>" = "Yes" | — | Overview, O&M Start |
| On-Air MTD uptime | Outage-weighted: 1 − Σ outage ÷ (1,440 × site-days) | pts vs MTD to the previous date | Overview |
| O&M Start MTD uptime | Same, for O&M Start sites | — | Overview, O&M Start |
| On-Air daily uptime (sparkline: month so far) | Same, on the date | pts | Overview |
| Sites at 98.5% or above | On-Air sites whose own MTD uptime ≥ 98.5% | count and % | Threshold Analysis |
| Sites below 60% | On-Air sites whose own MTD uptime < 60% | count and % | Overview site table, below 60% |
| Sites down all day | ≥ 1,440 outage minutes on the date | count and % | Overview, below 60% on the date |
| Reporting completeness | On-Air sites with a value on the date ÷ On-Air sites | pts | Data source & quality |
| CSV submissions pending / late | From CSV arrival tracking; "late" only with a configured deadline and no stored data or upload | — | CSV arrival tracking |

## Removed sections

Removed from this page on 23 Oct 2026, at the business's request:
- the reporting and operations cards;
- Portfolio comparisons (4G vs LWE, Current vs previous reporting date);
- Circle-wise comparison;
- Operational differences;
- Needs attention.

Their figures remain on Overview, Data source & quality, CSV arrival tracking and the alerts bell. "Compare with" still drives the change shown on the KPI cards.

## Not available yet

| Item | Why |
|---|---|
| Pending sign-offs | The `Signoff status` sheet is not read yet |
| Saturation / activation % | No approved denominator |
| Same days of last month for portfolio KPIs | Needs the previous month's daily columns |

## Circle-wise Site Portfolio Breakdown

Directly under the KPI cards. Its layout follows the "first page" sheet (`BSNL 4G - first page(2).xlsx`, Sheet1): a totals strip above the headers, 4G then LWE, subtotals and an overall total.

**Sources:**

| Column | Source |
|---|---|
| Circle, Client | Master data; one row per circle and report type (MP and OD appear in both networks) |
| Site Scope / On Air / O&M Start | `breakdowns/` with scope `all` / `on_air` / `om_start` (`sites_in_scope` per circle) |
| Gap against Total Sites | Site Scope − O&M Start |
| Gap against On Air Sites | On Air − O&M Start |
| CIs, IEs | `breakdowns/` (scope `all`): distinct names in the CI Name / IE Name columns per circle (case and spacing ignored; blank, "-" and "0" are unassigned). Subtotals and the total use `team_totals`, which count a person named in several circles once, so they are not sums of the rows |
| Sites per CI / IE | Site Scope ÷ CIs / IEs, one decimal |
| O&M Head, Remarks | Not in the Master workbook. Shown as "—" and editable on the page, held in browser memory only |

- **Subtotals and the total** add the circle rows once, and their gaps come from the summed counts (`circleBreakdown` in `lib/portfolio.ts`).
- **Circles** keep the workbook's codes (RJ, BH, JH, MH, TL), where the sheet writes RAJ, BR, JKD, MAH, TGN.
- **Filters:** report type and circle apply. The counts are current flags, not daily figures, so the reporting date does not change them.

**Reconciliation with the reference sheet** (active workbook, 22 Oct 15:50 upload). Every gap matches its own counts; the differences come from the counts themselves:

| Row | Dashboard (Scope / On Air / O&M) | Reference | Difference |
|---|---|---|---|
| RJ 4G | 1,458 / 1,362 / 1,316 | 1,457 / 1,362 / 1,316 | Site Scope +1 |
| CG LWE | 364 / 357 / 357 | 362 / 357 / 357 | Site Scope +2 |
| JH LWE | 816 / 816 / 800 | 816 / 815 / 800 | On Air +1 |
| MH LWE | 65 / 63 / 61 | 61 / 61 / 61 | Scope +4, On Air +2 |
| MP LWE | 22 / 20 / 19 | 22 / 22 / 22 | On Air −2, O&M Start −3 |
| WB LWE | 96 / 94 / 94 | 94 / 94 / 94 | Site Scope +2 |
| 4G subtotal | 4,544 / 4,249 / 4,130 | 4,543 / 4,249 / 4,130 | |
| LWE subtotal | 2,182 / 2,169 / 2,150 | 2,174 / 2,168 / 2,153 | |
| Overall | 6,726 / 6,418 / 6,280 | 6,717 / 6,417 / 6,283 | Gaps 446 / 138 vs 434 / 134 |

MP 4G, OD 4G, and LWE AP, BH, OD, TL and UP match exactly. The reference's LWE MP row (22 / 22 / 22) matches the threshold sheets' population of 22, but in Up-Time Report two of those sites are not On-Air and three are not O&M Start. The reference sheet's own source rows need checking.
