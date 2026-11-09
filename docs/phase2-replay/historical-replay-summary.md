# Phase 2: historical replay summary (4 Nov 2026)

**Scope run: 4G Saturation, September and October 2026.** The LWE replay is held back: `LWE Band ID.xlsx` is not in
the project (see `missing-source-files.md`), and as instructed no other workbook was substituted.

Isolation:
- All replay data went into a new throwaway SQLite database in the session scratchpad (`replay/verify.sqlite3`).
- Only the `sitedata` schema and the organization alias tables were migrated (up to `organization.0003`).
- The live PostgreSQL database was only read: a `READ ONLY` export for the comparison.
- No migration, reset or write touched it.

## 1. Pre-replay checks

| Check | Result |
|---|---|
| Business rules (matrix authority, first value wins, `Nw Avail (4G TCS)`, LWE IDs → one site, 0–1,440, missing ≠ 0, ambiguous / unmatched reported) | Implemented in `apps/sitedata/rules.py` and the importers; covered by tests |
| Rules decided on 4 Nov | Implemented before the replay: On-Air from the Site On-Air Date (O&M rule), Week 4 = 22–month end, MTD stops before the first date without data |
| Circle and technology independent | Yes. `Site` has both; daily records are unique on (site, date, technology). MP (1,483 4G + 22 LWE) and OD (1,603 4G + 256 LWE) hold both |
| `tests.test_sitedata` | **40 / 40 pass** |
| Full backend suite | 550 tests, **2 failures, both pre-existing**: `test_reconciliation.OctoberWorkbookReconciliationTests.test_dataset_shape` and `test_calculation_check_uses_each_formulas_population`. They read the live Master workbook; known before this work. No failure from the new code. |
| `manage.py check` | No issues |

## 2. Source files used

| Step | Source | Note |
|---|---|---|
| 1 | `Data/reference/Consolidated Escalation Matrix _Oct'26.xlsx` | Site master |
| 2 | LWE Band ID mapping | **Not run**: file not in the project |
| 3 | `Data/reference/RJ, MP & OD - Uptime Report- Sep-26.xlsx` | Sep 4G (no Project column; stated 4G Saturation) |
| 3 | `RJ MP  OD - Uptime Report- Oct-26 (003).xlsx` | Oct 4G (your choice). Read from the staged copy `Data/processed/imports/20261103-160629-617c583e1d.xlsx`, byte-identical (same SHA-256) to the Downloads file |
| 4 | 4G CNMC dumps in `Data/processed/raw_uploads/` | October only, each unique file once (repeat uploads with the same checksum skipped) |
| – | Not used | Consolidated Oct workbook (overlaps the chosen files); November files; LWE Sep / Oct workbooks and LWE dumps (held back) |

No September CSV exists anywhere; September comes only from the Uptime Master workbook.

## 3. Imports

| Step | Source file | Period | Circle | Technology | Received | Accepted | Duplicate | Conflict | Unmatched | Rejected | Not reported | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Consolidated Escalation Matrix _Oct'26.xlsx | as of Oct 2026 | all | all | 6,764 | 6,764 | 0 | 436 (ambiguous IDs) | 0 | 0 | 0 | committed |
| 2 | LWE Band ID.xlsx | – | – | – | – | – | – | – | – | – | – | **Not run** |
| 3 | RJ, MP & OD - Uptime Report- Sep-26.xlsx | Sep 2026 | MP, RJ, OD | 4G Saturation | 136,290 | 136,229 | 0 | 0 | 60 | 1 (outage out of range) | 0 | committed |
| 3 | RJ MP  OD - Uptime Report- Oct-26 (003).xlsx | Oct 2026 | MP, RJ, OD | 4G Saturation | 140,864 | 140,802 | 0 | 0 | 62 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-13/5_6dd1c7654e5d.csv | 13 Oct | OD | 4G Saturation | 6,131 | 0 | 1,546 | 1 | 4,584 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-13/4_044d3ab3dbc7.csv | 13 Oct | (JH file) | 4G Saturation | 817 | 0 | 0 | 0 | 0 | 817 (other circle) | 0 | committed |
| 4 | raw_uploads/2026-10-25/9_46719afd9394.csv | 25 Oct | RJ | 4G Saturation | 6,485 | 0 | 939 | 424 | 5,122 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-25/13_d6171d056bdd.csv | 25 Oct | OD | 4G Saturation | 6,132 | 0 | 1,548 | 0 | 4,584 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-26/10_ef87112449dc.csv | 26 Oct | RJ | 4G Saturation | 6,485 | 0 | 940 | 423 | 5,122 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-26/14_b326f51b2970.csv | 26 Oct | OD | 4G Saturation | 6,147 | 0 | 1,561 | 0 | 4,586 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-27/11_8097de1af83c.csv | 27 Oct | RJ | 4G Saturation | 6,485 | 0 | 680 | 683 | 5,122 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-27/15_812b8d620cf9.csv | 27 Oct | OD | 4G Saturation | 6,147 | 0 | 1,561 | 0 | 4,586 | 0 | 0 | committed |
| 4 | raw_uploads/2026-10-27/22_227381355e2d.csv | 27 Oct | MP | 4G Saturation | 5,462 | 0 | 1,351 | 0 | 4,111 | 0 | 0 | committed |
| 5 | LWE rows of the dumps; AP 25 Oct file | – | – | LWE | – | – | – | – | – | – | – | **Not run** |

What the counts mean:
- **Uptime Master rows** are site-days. **CSV rows** are file rows.
- **CSV "duplicate":** the value equals the stored first value, or the row repeats a site within the file.
- **CSV "unmatched":** dump rows whose BTS IP ID is not a 4G Saturation site. The CNMC dumps list every BSNL BTS of the
  circle. While the mapping is missing, these also include the LWE rows (e.g. 256 OD LWE sites). They are listed in
  `raw-dump-rows-not-in-site-master.csv`.
- **The 13 Oct `4_044d…` file** is a Jharkhand (JH, LWE-only circle) dump uploaded as OD: all 817 rows are rejected as
  `other_circle`. It belongs to the held-back LWE replay.

Result:

| Check | Value |
|---|---|
| Daily records | **277,031** (Sep 136,229 + Oct 140,802) |
| Duplicate (site, date, technology) keys | **0** |
| Conflicts logged | **1,531** (DailyPerformanceEvent): 1,530 RJ on 25–27 Oct, 1 OD on 13 Oct; first value kept |
| Matrix attributes overwritten | **None**: the Uptime Master differences are only reported. Sep: IE 1,590, OA 907, BA 896, CI 232, name 13, On-Air 4. Oct: IE 1,591, OA 908, BA 897, CI 233, name 13, On-Air 26 |
| Missing dates | None. Every 4G circle reported all 30 / 31 days; MTD runs to 30 Sep and 31 Oct. Blank cells: 0. Missing On-Air site-days: 1 (the rejected RJ value) |

## 4. Calculations (new layer)

Every figure is outage-weighted over the site-days with a record: 100 × (1 − Σ outage ÷ (1,440 × site-days)).

**Worked example** (`UVMPBPL00012`, MP, On-Air 5 Oct 2024, O&M Start 15 Nov 2025):

| | Value |
|---|---|
| 1 Sep | outage 984.40 min → 100 × (1 − 984.40 / 1440) = **31.6389%** |
| 2 Sep | 747.18 min → **48.1123%** |
| 3 Sep | 680.08 min → **52.7720%** |
| September | 30 reported days, 13,232.683 min → 100 × (1 − 13,232.683 / (1,440 × 30)) = **69.3688%** |
| Stored monthly results | `daily_derived`, `om_start` and `on_air` are identical here, because both dates are before September (effective from 1 Sep) |

**Monthly, 4G Saturation** (all circles; per circle in `availability-comparison.csv`):

| Month | Sites | On-Air sites (date rule) | O&M sites (date rule) | Site-days | All sites | On-Air | O&M | On-Air MTD |
|---|---|---|---|---|---|---|---|---|
| Sep 2026 | 4,542 | 4,237 | 4,052 | 136,229 | 86.0609% | 85.1070% | 86.0978% | 85.1070% (to 30 Sep) |
| Oct 2026 | 4,542 | 4,237 | 4,052 | 140,802 | 91.3172% | 90.8403% | 91.0682% | 90.8403% (to 31 Oct) |

- **Weekly:** calendar-month weeks 1–7, 8–14, 15–21, 22–end, On-Air basis. Week 4 was 83.87% (Sep) and 86.97% (Oct).
  Every week of every circle is in the CSV.
- **Effective dates:** 25 4G sites became On-Air or O&M Start after the 1st during Sep–Oct. Those sites count only from
  that date.
- **Combined 4G + LWE:** not computable yet (LWE held back). Records are keyed by technology, so a site can't be counted
  twice.

## 5. Comparison: new layer vs live database vs Excel

**Site-day values** (new vs live, read-only):

| Month | Identical site-days | Different | Only in live |
|---|---|---|---|
| Sep | 136,229 | 0 | 61: 60 for the 2 sites not in the matrix, 1 for the rejected 1,457.5-min value |
| Oct | 140,802 | 0 | 62 (the 2 sites) |

Live kept the October workbook values over the CSVs too, because the workbook was imported last there.

**Metrics** (all 4G; per circle in the CSV):

| Month | Metric | New | Live | Excel (`Summ`) | Source of the difference |
|---|---|---|---|---|---|
| Sep | Total sites | 4,542 | 4,544 | 4,543 | 2 RJ sites not in the matrix (UVRJJPR00057, UVRJUPR00612), unmatched by rule |
| Sep | O&M sites | 4,052 | 4,052 | 4,052 | none |
| Sep | O&M availability | 86.0978% | 86.0971% | 86.0971% | the 1 rejected RJ value (1,457.5 min > 1,440) |
| Sep | On-Air sites | 4,237 | 4,249 | 4,233 | **12** sites are On-Air in the Uptime Master but have no On-Air Date / status in the matrix (6 MP, 6 OD); Excel's "On-Air Done" is the workbook's own count |
| Sep | On-Air availability | 85.1070% | 85.1454% | 85.1319% | those 12 sites, and effective dates (sites On-Air from mid-month count only from that date: 656 fewer site-days than live) |
| Oct | O&M sites | 4,052 | 4,130 | 4,130 | **78 MP sites** are O&M Start in the Oct workbook but have **no O&M Start Date and blank O&M status in the matrix**: excluded and flagged for review |
| Oct | O&M availability | 91.0682% | 91.0915% | 91.0915% | the same 78 sites (2,418 site-days) |
| Oct | On-Air sites | 4,237 | 4,249 | 4,263 | the same 12 sites; the Oct workbook lists 26 more On-Air sites than the matrix |
| Oct | On-Air availability | 90.8403% | 90.7707% | 90.7605% | population (above) and effective dates |
| Sep / Oct | All-sites availability | 86.0609% / 91.3172% | 86.0664% / 91.3210% | – | only the 2 unmatched sites and the rejected value |

The new layer reproduces the workbook exactly where the populations agree. RJ October matches on every metric
(On-Air 94.8970% and O&M 94.9619%, all three sources), and so do all September O&M figures. Every remaining difference
comes from the approved rules applied to the Consolidation Matrix (dates, unmatched sites, range check), not from the
arithmetic. Nothing was adjusted to match the old figures.

## 6. Output files (`docs/phase2-replay/`)

| File | Content |
|---|---|
| `historical-replay-summary.md` | This report |
| `availability-comparison.csv` | Per month, circle (MP, RJ, OD, ALL) and technology: sites, On-Air / O&M counts, reported dates, MTD end, site-days, outage, availability (all, On-Air, O&M, MTD, Week 1–4), with new, live, Excel and the differences |
| `import-exceptions.csv` | 2,098 exception records: matrix (436 ambiguous IDs, 522 O&M Start Date missing, 318 On-Air Date missing), Uptime Master (4 unmatched-site rows, 1 out-of-range value), CSV (817 other-circle rows) |
| `raw-dump-rows-not-in-site-master.csv` | 37,817 CNMC dump rows that are not 4G Saturation sites (other BSNL BTS, and LWE rows while the mapping is missing) |
| `data-quality-issues.md` | Issues to resolve in the source data |
| `missing-source-files.md` | Files needed for the LWE replay |

## 7. Open before cutover

1. **LWE replay.** Copy `LWE Band ID.xlsx` into `Data/reference/`; the LWE workbooks and dumps are then replayed the
   same way.
2. **Matrix O&M and On-Air dates.** 78 MP sites have October O&M Start in the workbooks but no matrix date; 12 sites
   have On-Air status in the Uptime Master but no matrix On-Air Date. Under the approved rule they are excluded until the
   matrix is updated (data-quality-issues.md).
3. **RJ CSV vs workbook.** The CNMC dumps and the October workbook disagree on 1,530 RJ site-days (25–27 Oct). The
   workbook value is kept only because it was loaded first. Confirm which source is authoritative for days covered by
   both, or the import order to use in production.

Production cutover has not been started and waits for your approval.
