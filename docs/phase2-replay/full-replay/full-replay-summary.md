# Full historical replay: September–October 2026, 4G Saturation + LWE (4 Nov 2026)

## Isolation

- Two new throwaway SQLite databases in the session scratchpad:
  - `full/um_first`: Uptime Master first, then raw CSVs (the reported run);
  - `full/csv_first`: raw CSVs first, then Uptime Master (order check).
- Each replay script refuses to run on anything but SQLite. Only the `sitedata` schema and the organization alias
  tables (up to `organization.0003`) were migrated there.
- **No connection to PostgreSQL** was made in this task. The "live / dashboard" figures come from the read-only
  snapshot exported earlier today (`verify/live.pkl`, 6,726 sites, 401,544 site-days).
- No migration was applied to the live database, and `organization.0004` was not applied anywhere persistent.

## Pre-replay checks

| Check | Result |
|---|---|
| LWE mapping source | `Data/reference/LWE Band ID.xlsx`, imported into the replay database (upload #2). Runtime matching reads `SiteIdentifier` rows only; no mapping is in code |
| Source precedence | `daily.SOURCE_RANK`: correction > Uptime Master > raw CSV |
| Order independence | **Confirmed.** Both runs end with the same 410,130 keys and the same values (no value differs by more than 0.000001 points). The only difference is attribution: 11,993 identical values (10,101 4G, 1,892 LWE) stay credited to the CSV that delivered them first in the CSV-first run, because an identical value is a matching duplicate and changes nothing |
| `test_sitedata` | 58 / 58 pass |
| Full backend suite | 571 tests, 2 failures, both pre-existing (`test_reconciliation`, which reads the live workbook); no application code changed since |
| `manage.py check` | No issues |

## Imports (Uptime Master first)

| Step | Source | Tech | Received | Accepted | Duplicate | Conflict | Superseded | Unmatched | Rejected |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Consolidated Escalation Matrix _Oct'26 | all | 6,764 sites | 6,764 | 0 | 436 ambiguous IDs | – | 0 | 0 |
| 2 | LWE Band ID.xlsx | LWE | 1,996 rows | 1,994 | 1 | 0 | – | 0 | 1 |
| 3 | RJ, MP & OD Uptime Report Sep-26 | 4G | 136,290 | 136,229 | 0 | 0 | 0 | 60 | 1 |
| 3 | LWE Uptime Report day wise Sept'26 | LWE | 65,460 | 65,459 | 0 | 0 | 0 | 0 | 1 |
| 3 | RJ MP OD Uptime Report Oct-26 (003) | 4G | 140,864 | 140,802 | 0 | 0 | 0 | 62 | 0 |
| 3 | LWE Uptime Report Oct'26 | LWE | 67,642 | 67,640 | 0 | 0 | 0 | 0 | 2 |
| 4 | 4G CSVs: OD 13/25/26/27 Oct, RJ 25/26/27 Oct, MP 27 Oct | 4G | 49,474 rows | 0 | 10,126 | 1,531 | 0 | 36,957 | 0 |
| 5 | LWE CSVs: OD 13/25/26/27 Oct, JH 13 Oct, AP 25 Oct, MP 27 Oct | LWE | 30,899 rows | 0 | 1,898 | 21 | 0 | 21,398 | 14 |

- Site-days are counted for the workbooks, rows for the CSVs.
- **CSV accepted = 0:** every CSV day is also in an October workbook. CSV values are identical (duplicates) or differ
  (conflicts: the Uptime Master value kept, the CSV value logged).
- **CSV-first run:** the October workbooks supersede the same 1,531 4G and 21 LWE values, and the result is identical.
- **CSV "unmatched":** dump rows that are not dashboard sites (the dumps list every BTS of the circle); listed in
  `raw-dump-rows-not-in-site-master.csv` (58,355 rows).
- **4G rows in LWE uploads** and LWE rows in 4G uploads are skipped as the other technology.

## Validation

| Check | Result |
|---|---|
| Daily records | **410,130**: 4G Saturation 277,031, LWE 133,099 |
| Unique (site, date, technology) | **0 duplicates** |
| Outage outside 0–1,440 / availability outside 0–100 | **0 / 0**. 4 out-of-range workbook values rejected, not capped: Sep 4G 1, Sep LWE 1, Oct LWE 2 |
| Missing days as zero | None. A site-day without a value has no record. Zero-outage records (215,710) are all values written as 0 in the source |
| Technology of each record = technology of its site | Yes |
| Circles with both technologies | MP (1,483 4G + 22 LWE), OD (1,603 4G + 256 LWE); counted separately, never double-counted |
| MTD continuity | 54 scopes (month × technology × circle): every one has data on every day, so MTD runs to 30 Sep / 31 Oct |
| Missing On-Air site-days | 2 in September (the 2 rejected out-of-range values) |
| Mapping conflicts and gaps reported | Yes (`mapping-exceptions.csv`, `import-exceptions.csv`) |

## Results (new layer)

Availability is outage-weighted over site-days with a record. On-Air and O&M counts use the matrix dates, counted
from the effective date.

| Month | Technology | Sites | On-Air | O&M | Site-days | Overall | On-Air | O&M |
|---|---|---|---|---|---|---|---|---|
| Sep | 4G Saturation | 4,542 | 4,237 | 4,052 | 136,229 | 86.0609% | 85.1070% | 86.0978% |
| Sep | LWE | 2,182 | 2,169 | 2,150 | 65,459 | 86.9814% | 86.9034% | 87.0435% |
| Sep | **Combined** | 6,724 | 6,406 | 6,202 | 201,688 | 86.3596% | 85.7161% | 86.4256% |
| Oct | 4G Saturation | 4,542 | 4,237 | 4,052 | 140,802 | 91.3172% | 90.8403% | 91.0682% |
| Oct | LWE | 2,182 | 2,169 | 2,150 | 67,640 | 93.8568% | 93.8305% | 93.9408% |
| Oct | **Combined** | 6,724 | 6,406 | 6,202 | 208,442 | 92.1413% | 91.8527% | 92.0640% |

MTD equals the month in every scope (no gaps).

**Weekly, On-Air basis** (weeks 1–7, 8–14, 15–21, 22–month end):

| Month | Technology | Week 1 | Week 2 | Week 3 | Week 4 |
|---|---|---|---|---|---|
| Sep | 4G | 82.0750% | 86.4727% | 88.3564% | 83.8731% |
| Sep | LWE | 82.6035% | 88.4968% | 91.9657% | 85.0709% |
| Sep | Combined | 82.2545% | 87.1594% | 89.5801% | 84.2787% |
| Oct | 4G | 92.8509% | 93.4951% | 91.7001% | 86.9725% |
| Oct | LWE | 94.2972% | 94.4503% | 95.7679% | 91.7138% |
| Oct | Combined | 93.3406% | 93.8185% | 93.0774% | 88.5779% |

Per circle: `availability-comparison.csv`, `weekly-availability.csv`, `mtd-validation.csv`.

## Comparison and explanation of every material difference

**Site-day values vs the live snapshot:**

| Scope | Identical | Explained differences |
|---|---|---|
| 4G Sep | 136,229 | 61 only in live: 2 sites not in the matrix (60), 1 rejected value |
| 4G Oct | 140,802 | 62 only in live (the 2 sites) |
| LWE Sep | 65,459 | 1 only in live (rejected value) |
| LWE Oct | 56,074 | 11,424 only in the new layer, 142 different, 2 only in live (rejected values) |

### LWE October: the live database is incomplete

- For 26–31 Oct, the live snapshot has LWE values for only 278 sites a day; the LWE Oct'26 report has 2,182.
- Live built LWE October mostly from the two consolidated October workbooks (41,937 + 10,432 site-days). Its LWE
  Oct'26 import added only 3,849.
- The 142 differing values are all live values from those consolidated workbooks.
- Effect: live LWE October looks better (94.5461% On-Air vs 93.8305%) because it misses the last six days, which were
  worse.
- **The new layer matches the LWE Oct'26 workbook exactly** in every circle where the populations agree (AP 98.7235%,
  BH 95.6164%, JH 91.5273%, OD 88.3913%, TL 98.8092%, UP 95.9971%; O&M the same).

### O&M counts follow the matrix date (approved rule)

| Case | New | Live / Excel | Cause |
|---|---|---|---|
| 4G Oct | 4,052 | 4,130 | 78 MP sites with no O&M Start Date in the matrix |
| LWE Oct | 2,150 | Excel 2,153 | MP: Excel counts 22 O&M and 22 On-Air sites; the matrix has dates for 19 and 20 |
| LWE Sep | 2,150 | live 0 | The live snapshot has no LWE O&M flags for September; the new count equals Excel exactly (2,150) |

### On-Air population (approved rule)

- 12 sites (6 MP, 6 OD, 4G) are On-Air in the Uptime Master but have no On-Air Date in the matrix.
- 25 4G sites started mid-month and count from their date. This explains the 4G On-Air differences, for example Sep
  85.1070% vs Excel 85.1319%.

### Excel definitions differ between the two workbook families

- **4G "Overall Up-Time"** is the On-Air availability: RJ Oct 94.8970% in all three sources.
- **LWE "Overall Raw Uptime"** is the all-sites availability. The new overall equals it exactly in every circle (e.g.
  CG Sep 95.5450%, MP Sep 95.0721%, WB Sep 88.9246%). Comparing it with On-Air therefore shows a gap that is not a
  calculation difference.
- **The LWE workbooks' Grand Total is not outage-weighted.** Sep 91.6162% is the plain average of the ten circle
  percentages, so Jharkhand (816 sites) weighs the same as Andhra Pradesh (62). The weighted LWE total is 86.9814%.
  October: Excel 95.2959% vs weighted 93.8305%.

### Precedence

- 1,531 4G conflicts: RJ 25–27 Oct 1,530, OD 13 Oct 1. They are mostly rounding: 1,291 are under 1 minute.
- 21 LWE conflicts: all 20 LWE rows of the MP 27 Oct dump, and 1 OD row on 27 Oct, differ from the LWE Oct'26 workbook.
- In each case the Uptime Master value is kept and the CSV value logged (`source-precedence-audit.csv`).

### Totals

- 4G: 4,542 vs 4,544 (live) / 4,543 (Excel Sep): the 2 RJ sites not in the matrix.

## Exceptions

| Source | Item | Count |
|---|---|---|
| Matrix | Ambiguous band IDs (blocked) | 436 |
| Matrix | O&M Start Date missing (review) | 522 |
| Matrix | On-Air Date missing (review) | 318 |
| Mapping | Single-`;` cell (LWEBH0141) | 1 rejected |
| Mapping | Identical repeat | 1 |
| Mapping | LWE sites without a mapping row | 188 |
| Uptime Master | Sites not in the matrix (UVRJJPR00057, UVRJUPR00612) | 2 sites (4 rows) |
| Uptime Master | Outage > 1,440 | 4 values |
| 4G CSV | Conflicts with the Uptime Master | 1,531 |
| LWE CSV | Conflicts with the Uptime Master | 21 |
| LWE CSV | `identifier_not_in_mapping` | 6 |
| LWE CSV | `conflicting_rows` | 6 |
| LWE CSV | `identifier_mismatch` (BLG1394) | 1 |
| LWE CSV | `invalid_identifier` (LWEJH1243) | 1 |

## Files (this folder)

| File | Content |
|---|---|
| `full-replay-summary.md` | This report |
| `availability-comparison.csv` | Month × technology (4G, LWE, ALL) × circle: sites, On-Air, O&M, site-days, outage, Overall / On-Air / O&M / MTD availability, missing site-days; new vs live snapshot vs Excel |
| `weekly-availability.csv` | Week 1–4 per month, technology and circle |
| `mtd-validation.csv` | Dates with data, MTD days, first missing date, MTD vs month availability |
| `import-exceptions.csv` | Every rejected, unmatched-site, review, conflict and superseded record of every upload |
| `source-precedence-audit.csv` | Each conflict / supersede: site, date, kept and other value, both uploads and files |
| `mapping-exceptions.csv` | Mapping import exceptions |
| `raw-dump-rows-not-in-site-master.csv` | 58,355 dump rows of BTS that are not dashboard sites |

## Open before any production step

1. **Matrix:**
   - O&M Start Dates for 78 MP 4G sites and 3 MP LWE sites;
   - On-Air Dates for 12 4G sites and 2 MP LWE sites;
   - the 2 missing RJ sites;
   - the 436 ambiguous band IDs.
2. **Mapping:**
   - LWEBH0141 (single `;`);
   - BLG1394 (2100 and 700 IDs map to different Master IDs);
   - 188 LWE sites without a mapping row.
3. **Live LWE October gap** (26–31 Oct, 1,904 sites a day): the new layer resolves it from the LWE Oct'26 report.
4. **Excel Grand Totals for LWE are unweighted averages.** The dashboard should keep the outage-weighted figure; to
   be confirmed.

No production operation has been started.
