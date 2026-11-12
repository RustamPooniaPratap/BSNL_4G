# BSNL 4G Portal: Data Pipeline Audit (Phase 1)

| | |
|---|---|
| Date | 11 Nov 2026 |
| Scope | Every stage from source file to management reporting, on the `sitedata` data layer (the only operational layer since the legacy tables were removed) |
| Mode | **Read-only.** No source code, migration, database record, upload batch, preview or staged file was changed. Database inspection used read-only sessions. Defects were reproduced only in throwaway in-memory SQLite databases (scripts under the session scratch folder, `scratchpad\audit_ingest\` and `scratchpad\audit_calc\`). The November files were analysed with the importer's read-only `analyse()` inside a `SET TRANSACTION READ ONLY` transaction that was rolled back. |
| Database | `fourg_db` @ 127.0.0.1:5432 (PostgreSQL 18.6) |
| Evidence tags | **[CODE]** verified by reading code. **[EXP]** reproduced in a scratch experiment. **[DB]** read-only query on `fourg_db`. **[FILE]** read-only analysis of a source file. **[INF]** inferred, not reproduced. |
| Status values | **Confirmed**: code or experiment proves it. **Suspected**: inferred, needs PostgreSQL concurrency or production verification. **Business decision pending**: the code works as written, but the rule must be chosen by the business. |

---

## Executive summary

The ingestion core is sound:
- **Identifier matching:** deterministic matching; LWE 2100/700 resolution; no fuzzy matching. **No path creates a site from a raw row** [CODE].
- **Source precedence:** correction 3 > Uptime Master 2 > raw CSV 1, now order-independent [CODE/EXP].
- **Database constraints:** 0–100 % and 0–1440 min checks; unique site + date + technology [DB].
- **Commits:** a PostgreSQL advisory lock and a batch row lock serialise every commit [CODE].

The pipeline is **not yet production-ready**, for four reasons:

1. **Reporting completeness can silently freeze or blank the dashboards.**
   - **Critical:** "expected units" means every technology/circle unit that has ever reported. A unit that starts mid-month can wipe out every reporting date (C-1).
   - **One technology's gaps hide another's data:** incomplete LWE data stops the 4G month-to-date (C-2).
   - **This matters for November now.** The available November files would put 4G through 9/10 Nov on screen only up to **3 Nov**, because LWE November ends on 3 Nov [FILE + EXP].
2. **The same KPI is defined differently in different places.**
   - There are three USD/NSLA definitions (C-3).
   - Partial weeks are shown in some consumers and hidden in others (C-5).
   - Emailed reports use a different site population from the portal download: **86.11 % vs 92.42 % on the same data** (C-6).
   - The Consolidated export treats missing days as zero outage in history months (C-4).
3. **Wrong files can reach the daily table.**
   - future-dated values (I-1);
   - Up-Time Report rows of the wrong or unknown circle (I-2);
   - raw CSVs reporting availability as a fraction (I-4);
   - duplicated or shifted CSV columns (I-5);
   - files covering a fraction of the sites (I-6).
   - In addition, one Up-Time Report layout passes preview and then crashes at commit (I-3).
4. **Storage and exceptions are not durable.**
   - Staged files and exception reports are stored by **absolute local path**. For **all 24 batches** they exist only on the original developer's machine (S-1) [DB].
   - Pending (unmatched) handling has three problems:
     - it works only for Uptime Master batches;
     - it silently ignores sites after the first 200;
     - it can overwrite an Admin correction under concurrency (M-2, M-3, M-4).

**Counts (issue register, section 9):**

| Category | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| Confirmed defects | 1 | 12 | 23 | 13 | 49 |
| Suspected defects | 0 | 0 | 2 | 1 | 3 |
| Missing infrastructure | 0 | 2 | 4 | 1 | 7 |
| Business decisions pending | | | | | 8 |

---

## 1. End-to-end data-flow diagram

```
SOURCES (files / manual)                    INGESTION (apps/sitedata)                        STORAGE (fourg_db)                       CONSUMERS
───────────────────────────                 ─────────────────────────────                    ──────────────────                        ─────────
Consolidation Matrix .xlsx ──► matrix_views ─► matrix.preview ─► analyse ─┐                 sitedata_site
  (sheet "Raw Data")            (Admin)        (staged copy,             │ commit           sitedata_siteidentifier
                                                exception CSV)            ├─(lock)────────► sitedata_identifierconflict
LWE Band ID mapping .xlsx ───► data_views ───► bandmap.preview/analyse ───┤                 sitedata_lwemappingrow/_identifier
                                (Admin)                                    │
Up-Time Report / Day Wise ───► uptime_views ─► uptime_master.preview ─────┤ daily.classify  sitedata_dailysiteperformance  ◄── precedence 3>2>1
  .xlsx (Uptime Master, rank 2) (Admin)         └ sources/uptime_report,   │  (new/dup/upgraded/  (+ sitedata_dailyperformanceevent,
                                                  sources/daywise          │   superseded/conflict) append-only)
Raw CNMC CSV (4G / LWE) ─────► raw_views ────► rawcsv.preview/analyse ────┤                 sitedata_uploadbatch (history, report JSON,
  (rank 1)                      (CSV Upload     └ sources/cnmc_csv,        │                   absolute stored_path / exception path)
                                 + pair scope)    identifiers, rules       │
Corrections (rank 3) ─────────► data_views.daily_correct (Admin) ──────────┤ daily.correct/  
                       └──────► Data Panel save (Edit/Add perm) ───────────┘ add_correction
Unmatched resolution ─────────► uptime_views.unmatched_map/process ─► SiteIdentifier(alternate) + process_pending (Uptime batches only)

                                            AFTER EVERY DAILY WRITE (outside the transaction):
                                            uploads.refresh_after_daily_write ─► calculations.calculate_month ─► sitedata_monthlysiteperformance
                                                                              └► portfolio.clear_cache()

READ PATH:  dataset.build (completeness → reporting_month; outage matrix; history) ─► portfolio (variants all/on_air/om_start, cache, continuous MTD)
            ─► dashboard_source.dataset(pairs, scope) ─► dashboard/metrics.py ─► Dashboard 4G/LWE/Overview, Thresholds, Teams/CI-IE/Top, Site Portfolio,
                                                                                Excel exports (report_export), emailed reports (alerts/reports),
                                                                                All KPI's (own USD/NSLA), RCA breakdown (own USD/NSLA)
            DailySitePerformance/UploadBatch directly ─► CSV Arrival Tracker (sitedata/arrivals.py) ─► CSV reminders (alerts/engine.pending)
            ORM directly ─► Data Panel (masterdata), Organization usage counts, RCA site lookups (sitescope, importer, cycles)
            Frontend mock data ─► Team Hierarchy pages (not data-driven)          PowerPoint export: none exists
```

---

## 2. Source-to-database mapping

| Source | Format, columns and identifiers | Reporting date | Writes | Permission |
|---|---|---|---|---|
| **Consolidation Matrix** | .xlsx/.xlsm, sheet "Raw Data", header found by "BSNL Site ID". Required: Entity, Circle Name, BSNL Site ID. Also attributes, On-Air / O&M Start dates, B1 (2100) / B28 (700) band IDs and Master BTS ID (`matrix.py`, `sources/matrix_sheet.py`) | None (effective dates per site) | `sitedata_site`, `_siteidentifier`, `_identifierconflict`; then recalculates every month with daily data | Admin |
| **LWE Band ID mapping** | .xlsx, first sheet with "btsIpId -Master ID" plus BTS IP ID / BTS Site ID (2100) / (700) columns; cells split on ";;" (`bandmap.py`) | None | `_lwemappingrow`, `_lwemappingidentifier` (history), `_siteidentifier` (active) | Admin |
| **Uptime Master** (Up-Time Report / Day Wise Outage) | .xlsx/.xlsm. Up-Time Report: header on row 2, Circle and btsIpId, date columns of outage minutes. Day-wise: "Site ID as per Nirikshan" or btsIpId plus Circle and date runs (`uptime_master.py`, `sources/uptime_report.py`, `sources/daywise.py`) | Date column headers; only months in `months_in_scope()` = 2026-09 … current month (hard-coded default, no setting) | `_dailysiteperformance` (rank 2), `_dailyperformanceevent`, `Site.uptime_master_fields` | Admin |
| **Raw CNMC CSV 4G / LWE** | .csv, header with "BTS IP ID" in the first 10 lines. Required: BTS IP ID, Circle, Report Date, "Nw Avail (4G TCS)". LWE also uses BTS Site ID (2100) / (700) (`rawcsv.py`, `sources/cnmc_csv.py`) | Entered by the user (not in the future); each row's Report Date must match | `_dailysiteperformance` (rank 1) | CSV Upload, per project/circle |
| **Authorized correction** | Site, date, availability % (or outage in the Data Panel) plus a mandatory reason (`daily.correct/add_correction`, `data_views.daily_correct`, `masterdata/editing.py`) | Entered by the user | `_dailysiteperformance` (rank 3), a correction `UploadBatch`, `DailyPerformanceEvent` | Admin (API); Data Panel Edit/Add per pair |
| **Alternate-ID mapping and pending processing** | One identifier → existing site, with a reason (`unmatched.map_alternate`, `process_pending`) | From the staged Uptime Master file | `_siteidentifier` (alternate), `_dailysiteperformance` | Admin |
| **RCA workbooks** | Site lookup only, by (technology, site_key) → circle (`rca/importer.py`) | n/a | RCA tables only | RCA upload |
| **Add Row / Add Site pages** | Checked in the browser only | n/a | **Nothing** | CSV Upload |

---

## 3. File-by-file implementation map

| File | Role |
|---|---|
| `apps/sitedata/models.py` | All tables (section 4) |
| `apps/sitedata/rules.py` | Availability/outage conversion and range checks, effective dates, weeks, MTD dates, ENTITIES |
| `apps/sitedata/identifiers.py` | `key_of`, `split_ids`, `is_valid_id`, `IdentifierIndex` (blocked IDs) |
| `apps/sitedata/uploads.py` | Staging (`new_batch`, `staged_file` with checksum), `record_preview`, `same_counts`, **`committing` (advisory lock + row lock)**, `write_lock`, `refresh_after_daily_write`, `discard` |
| `apps/sitedata/exceptions.py` | Exception records and the CSV written to `<DATA_DIR>/processed/sitedata/exceptions/` (absolute path stored in the report) |
| `apps/sitedata/daily.py` | `SOURCE_RANK`, `classify` (new / duplicate / upgraded / superseded / conflict), `write` (finalized guard), `correct`, `add_correction` |
| `apps/sitedata/matrix.py`, `matrix_views.py`, `sources/matrix_sheet.py` | Matrix import |
| `apps/sitedata/bandmap.py`, `data_views.py` (mapping_*) | LWE mapping import |
| `apps/sitedata/uptime_master.py`, `uptime_views.py`, `sources/uptime_report.py`, `sources/daywise.py` | Uptime Master import |
| `apps/sitedata/rawcsv.py`, `raw_views.py`, `sources/cnmc_csv.py` | Raw CSV import (`/api/raw-uploads/*`) |
| `apps/sitedata/unmatched.py` | Unmatched report, alternate mapping, pending processing (Uptime Master only) |
| `apps/sitedata/calculations.py` | Monthly results (daily_derived / om_start / on_air), revisions, finalize |
| `apps/sitedata/dataset.py` | Dashboard `Dataset` build, `completeness`, `reporting_month` |
| `apps/sitedata/portfolio.py`, `dashboard_source.py` | Variants, cache, continuous MTD, the single dataset entry point |
| `apps/sitedata/arrivals.py` | CSV Arrival Tracker |
| `apps/dashboard/metrics.py` | Metric engine (uptime, buckets with 6-dp comparison, weeks, monthly, USD, NSLA, thresholds, teams, alerts) |
| `apps/dashboard/report_export.py` | Daily and Consolidated Excel exports |
| `apps/allkpis/services.py` | All KPI's (own per-site USD/NSLA) |
| `apps/rca/breakdown.py`, `sitescope.py`, `services.py`, `importer.py`, `cycles.py` | RCA site metrics and lookups |
| `apps/alerts/reports.py`, `engine.py` | Emailed reports, CSV reminders |
| `apps/masterdata/*` | Data Panel views and corrections |
| `apps/organization/services.py` | Usage counts per pair |

---

## 4. Database model and table mapping [DB]

| Table | Rows | Key constraints | Written by | Read by |
|---|---|---|---|---|
| `sitedata_site` | 6,764 (6,724 dashboard scope) | `site_key` unique; scope/technology CHECK | matrix | everything |
| `sitedata_siteidentifier` | 17,214 | unique (kind, key) | matrix, bandmap, `map_alternate` | importers, RCA overview |
| `sitedata_identifierconflict` | 436 | unique (kind, key) | matrix | `IdentifierIndex` |
| `sitedata_lwemappingrow` / `_identifier` | 1,996 / 5,939 | unique (batch, row) | bandmap | history |
| `sitedata_dailysiteperformance` | 410,130 (4G and LWE, 1 Sep–31 Oct 2026) | unique (site, date, technology); CHECK 0–100, 0–1440 | importers, corrections, pending | dataset, arrivals, Data Panel, calculations |
| `sitedata_dailyperformanceevent` | 1,552 (all `conflict`) | append-only (ORM only) | `daily.write`/`correct` | daily history API |
| `sitedata_monthlysiteperformance` | 38,663 (Sep, Oct; none finalized) | partial unique current; revisions | calculations | export history, Data Panel, months API |
| `sitedata_uploadbatch` | 24 | — | all importers | history, tracker, previews |
| `common_setting` | 0 | key unique | alert worker | alert status |
| `org_*` (10 hierarchy tables) | 0 | site FK → `sitedata_site` | hierarchy admin | hierarchy pages |

**Traceability of a daily record** [CODE/DB]:
- Each record links to the `batch` that set its current value, which gives the file name, SHA-256 checksum, staged path, uploader, upload and commit times, kind (= precedence), technology, circle and reporting date.
- The record also stores `source_row`, `source_identifier`, `revision` and the matched `site`.
- Earlier values, conflicts and corrections are in `DailyPerformanceEvent`.

**Gaps:**
- **Missing uploader:** 20 of 24 batches have no `uploaded_by` (script imports, 4 Nov).
- **No circle or date on Uptime Master batches:** they span many dates and circles (the per-record value carries both).
- **Identifier route not stored:** the record does not store which identifier kind resolved the site (BSNL ID, BTS IP, band or alternate).
- **Audit trail:** accounts audit events are log lines only, not database rows.

---

## 5. Validation checklist [CODE/EXP]

PASS = enforced. PARTIAL = enforced with gaps. FAIL = not enforced; wrong data can be stored.

| Check | Matrix | Raw CSV | LWE mapping | Uptime Master | Corrections |
|---|---|---|---|---|---|
| Extension | PASS | PASS | PASS | PASS | n/a |
| Content / format (magic, zip, macro, zip-bomb) | PARTIAL: no zip-bomb guard, .xlsm accepted | PASS: NUL bytes refused, decode checked [EXP] | PARTIAL | PARTIAL: pandas loads the whole sheet | n/a |
| Size limit before streaming | PARTIAL: after the full body is received | PARTIAL: 25 MB view vs 50 MB service | PARTIAL | PARTIAL | n/a |
| Required columns | PASS | PASS [EXP] | PASS | PASS | PASS |
| Duplicate or renamed columns | PARTIAL | **FAIL**: duplicated TCS column, last one wins silently [EXP] (I-5) | PARTIAL | PARTIAL | n/a |
| Row structure | n/a | **FAIL**: extra or short cells padded or ignored [EXP] (I-5) | n/a | n/a | n/a |
| Missing / invalid values | PASS | PASS (blank = not reported); `-`/`NA` rejected (inconsistent with Uptime Master, I-11) | PASS | PASS for blanks; **FAIL**: "50%" in an outage cell read as 0.5 min [EXP] (I-10) | PASS |
| Reporting date in file vs selected | n/a | PASS (per row) | n/a | n/a (dates in the headers) | n/a |
| Future dates | n/a | PARTIAL: view only; the service accepts them [EXP] | n/a | **FAIL** [EXP] (I-1) | **FAIL** in `daily_correct` [EXP] (I-1) |
| Months in scope | n/a | n/a | n/a | PARTIAL: hard-coded from 2026-09; out-of-scope months dropped silently (I-7, I-13) | n/a |
| Circle | PASS | PASS | PASS | **FAIL**: unknown or other circle imported [EXP] (I-2) | PASS |
| Technology | PASS | PASS | PASS | PASS | PASS |
| Duplicate file (checksum) | none | warning only | none | warning only | n/a |
| Previously imported period | none | record level only | n/a | record level only | n/a |
| Availability 0–100 | n/a | PASS + DB CHECK | n/a | n/a | PASS |
| Outage 0–1440 | n/a | derived | n/a | PASS + DB CHECK | PASS |
| Identifier validity | PASS | PASS (LWE); PARTIAL (4G: blocked ID reported as unmatched, I-14) | PASS | PARTIAL | PASS |
| Empty / header-only file | PASS | PASS [EXP] | PASS | PARTIAL: warning only | n/a |
| Partial coverage of master sites | review list | **FAIL**: no warning [EXP] (I-6) | review | **FAIL** (I-6) | n/a |
| All rows rejected | n/a | **FAIL**: still committable [EXP] (I-6) | n/a | PARTIAL | n/a |
| Fraction instead of percentage | n/a | **FAIL**: 0.995 stored as 0.995 % [EXP] (I-4) | n/a | n/a | n/a |
| Site no longer in latest matrix | n/a | **FAIL** [EXP] (I-8) | n/a | **FAIL** (I-8) | n/a |
| Same site-day twice in one file | n/a | PASS | n/a | **FAIL**: preview passes, commit 500 [EXP] (I-3) | n/a |

**Proven routes for wrong data into `sitedata_dailysiteperformance`:**
- fraction availability;
- duplicated column;
- shifted or extra cells;
- future-dated Uptime Master zeros (stored as 100 %);
- an unknown or other-circle Uptime row;
- "50%" in an outage cell;
- sites removed from the matrix;
- future-dated corrections;
- partial files passing as complete.

---

## 6. Import, transformation and mapping logic

- **Identifier normalisation:**
  - `identifiers.key_of`: trim, upper case, collapse spaces (the same rule as the matrix).
  - `split_ids` splits on ";;" only and drops placeholders.
  - `is_valid_id` is applied to LWE and the mapping only.
  - Zero-width characters are not stripped (Low).
- **Matching:**
  - `IdentifierIndex` with blocked (ambiguous) IDs.
  - 4G: BTS IP ID = BSNL Site ID, then the BTS_IP_ID identifier.
  - LWE: every band token must resolve, and all to one site; a BTS IP ID absent from the mapping is ignored and counted.
  - Uptime Master: `site_key`, then approved alternates.
  - **No fuzzy matching. No site is created by any importer except the matrix** [CODE].
- **Formulas:**
  - outage = 1440 × (1 − availability/100), and the reverse (`rules.py`);
  - raw CSV values are always percentages;
  - Uptime Master uses outage minutes; its uptime-fraction run is parsed but never cross-checked.
- **Missing values:** no record; never 0 [CODE/DB].
- **Effective dates:** applied when reading (dataset variants, monthly categories), not when importing. By design, `daily_derived` counts every reported day.
- **Duplicates:**
  - In-file: the raw CSV groups by site (identical values → one record, different → rejected). The Up-Time Report does not (I-3).
  - Across files: `daily.classify` plus the unique constraint.
- **Unmatched handling:**
  - Raw CSV unmatched rows are recorded in `report['rows']`, the exception CSV and the staged copy, but **cannot be processed later** except by re-uploading the file (M-2).
  - Uptime Master unmatched rows are kept as capped lists in the report and processed by `process_pending` (M-3, M-4, M-5).

### 6.1 Unmatched classification of whole-circle CNMC dumps [DB]

| Batch | File rows | Matched (programme) | Other technology (skipped) | "Unmatched" (`not_in_site_master`) | Programme sites with no row |
|---|---|---|---|---|---|
| #7 4G OD 13 Oct | 6,131 | 1,543 | 211 | **4,373** | 60 of 1,603 |
| #15 LWE OD 13 Oct | 6,131 | 254 | 1,547 | **4,326** | 2 of 256 |
| #21 LWE MP 27 Oct | 5,462 | 20 | 1,351 | **4,089** | 2 of 22 |

The CNMC daily file is a dump of **every BTS in the circle**. "Unmatched" therefore mixes two different things:
1. **BTSs outside the programme** (never in the Consolidation Matrix). These are the bulk.
2. **Programme sites the matrix cannot match** (a genuine mapping gap).

The current code cannot tell them apart. The 4G resolver has only "found / not found", and `raw_views` presents all of them as "Not in the site master: kept pending".

**Proposed deterministic classification** (a business decision on the rule, M-1). In order, first match wins:
1. **Matched**: resolves to a dashboard-scope site of the selected technology and circle.
2. **Other technology / outside dashboard scope**: resolves to a site of the other technology, or to Sterlite / VI-HPSC (already implemented).
3. **Programme identifier, unresolved**: the row carries an identifier the matrix or LWE mapping knows (a partial band match, a blocked/ambiguous ID, a mismatch). This is a real mapping exception and must stay **pending**.
4. **Duplicate row** (already implemented).
5. **Invalid identifier**: the format fails `is_valid_id` (already implemented for LWE).
6. **Outside the programme**: no identifier of the row is known anywhere in `sitedata_siteidentifier`, `identifierconflict` or `lwemappingidentifier`. These are reported as an informational count only and are **not** pending.

The complementary "programme sites with no row in the file" (`sites_without_value`) is the real coverage gap and should be shown prominently (I-6). Uptime Master rows are programme rows by definition, so their unmatched rows stay pending, as now.

### 6.2 Preview validity

| Event after preview | Current behaviour [CODE/EXP] |
|---|---|
| Master, mapping or effective dates change | Commit re-runs `analyse` and compares **aggregate counts only** (`same_counts`). If the counts change it is refused (409). If they don't, it commits the *new* analysis, never the stale one. Value moves with equal counts go undetected in the preview the user approved (P-1). |
| Another user commits the same date | Second commit re-analyses inside the lock; counts differ → 409 [CODE] |
| Month finalized after preview | `daily.write` raises `FinalizedPeriod` → 409 [EXP] |
| Staged file deleted | `staged_file` raises "staged copy … is missing" → 409 [CODE] |
| Preview never committed | **No expiry**; stays "previewed" indefinitely (P-2) |
| Discard racing a commit | **A committed batch can be marked discarded** [EXP] (P-3) |

### 6.3 Previews #23 and #24 [DB/FILE]

| | #23 | #24 |
|---|---|---|
| Kind / status | uptime_master / **previewed** (passed with warnings) | identical |
| File | `RJ, MP & OD - Uptime Report- Nov-26.xlsx`, checksum `33f2a1b93e…` (older Nov file, 1–3 Nov) | identical (a second preview of the same file) |
| Counts at preview | received 12,174, accepted 12,170, unmatched 4 (UVRJJPR00057, UVRJUPR00612) | identical |
| Staged copy | `C:\Users\gaura\OneDrive\…` (**missing on this machine**) | identical |
| Consequence | **Cannot be committed here** (`staged_file` → 409). Does not block anything else. Appears in import history as an open preview. Superseded by the newer file `48e3e33a20…`, whose 1–3 Nov values are identical (12,170 overlapping site-days, 0 differences [FILE]). | identical |
| Recommendation (not executed) | Discard after approval. Never needed for November. | identical |

### 6.4 November source files [FILE, read-only `analyse()`]

| File (other project copy, `Data/processed/imports/`) | Technology | Dates | Importable site-days | Coverage | Unmatched |
|---|---|---|---|---|---|
| `20261111-164533-48e3e33a20.xlsx` (newest, 11 Nov) | 4G | MP and OD 1–9 Nov, **RJ 1–10 Nov** | 42,334 | **every** dashboard site every day (MP 1,483; OD 1,603; RJ 1,456) | 2 RJ sites (not in the matrix) → pending |
| `20261105-130325-33f2a1b93e.xlsx` (older) | 4G | MP and OD 1–3, RJ 1–2 Nov | 12,170 | every site | same 2 |
| `20261105-130057-96617c84f6.xlsx` | LWE | **1–3 Nov** | 6,546 | every site of all 10 LWE circles | 0. The file declares a 2026-12 month; no values imported from it. |
| Raw CSV 1 Nov MP / RJ / OD (`raw_uploads/2026-11-01/`) | 4G | 1 Nov | 1,351 / 1,361 / 1,556 | 1,351 of 1,483 / 1,361 of 1,456 / 1,556 of 1,603 | 4,095 / 5,077 / 4,316 (whole-circle dump) |

**Duplicate safety:**
- The database has no November rows, so the 48e3 file would import as all-new.
- Re-importing 33f2 afterwards gives duplicates only.
- The raw CSVs of 1 Nov after the Uptime Master give duplicates or conflicts at rank 1, never overwrites.

**Consequences for reporting** (C-1, C-2):
- After importing 48e3 + 96617, 1 Nov is complete for every unit, so the reporting month becomes November.
- But the MTD stops at **3 Nov** for *every* user, because LWE has no 4–10 Nov data. 4G 4–10 Nov stays invisible.
- Importing 4G alone would leave the reporting month at **October** (LWE missing on 1 Nov).
- How November should be presented is a business decision (B-1).

---

## 7. Calculation and aggregation logic [CODE/EXP]

| Measure | Implementation | Notes |
|---|---|---|
| Daily availability / outage | `rules.outage_from_availability` / `availability_from_outage` | 98.50 % → 21.60000000000002 min (float) |
| Site uptime (period) | `metrics.site_uptime`: 100 × (1 − Σoutage / (1440 × reported days)) | not rounded |
| Pooled uptime | `metrics.uptime_pct` (rounded to 4 dp for the API) | 4-dp API value vs 6-dp bucket comparison (C-12) |
| Buckets / 98.5 % | `metrics.bucket_ids` with `comparable()` (6 dp) | **Correct in Python.** Excel formulas do not round (C-13). Frontend colours use rounded API values (C-12). |
| Weekly | `metrics.week_columns`; complete weeks only (dashboard, thresholds, trend-period KPI) | All KPI's, Consolidated export and Portfolio weekly show week-to-date (C-5) |
| Monthly | `metrics.month_values`: daily history over reporting days; falls back to `monthly_outage` over calendar days | export uses calendar days (C-4) |
| MTD | `portfolio.continuous` → `rules.mtd_dates(complete_dates)` | global completeness (C-1, C-2) |
| Completeness | `dataset.completeness`: each unit that ever reported has ≥ 1 record on the date | vs the tracker: every On-Air site (C-9) |
| On-Air | dataset: date ≤ end of reporting month; tracker: ≤ the date; org counts: ≤ today; All KPI's: ≤ period end | four definitions (C-8) |
| O&M Start | variants mask values before the effective date; history months use the reporting month's flags | C-7 |
| USD / NSLA | dashboard: On-Air, any outage / period-pooled < 98.5; All KPI's: O&M per day, any single day < 98.5; RCA: reporting-month flags, "all" variant, any single day | three definitions (C-3) |
| 4G vs LWE | identical formulas, separate technologies; completeness is global | C-2 |
| Monthly table | `calculations.calculate_month` (three categories, revisions, finalize) | read only by the export history, Data Panel, org counts, months API |
| RCA | `rca/breakdown.site_metrics`, `sitescope` (matrix O&M date ≤ month end) | C-3, C-7, C-11 |

**Duplicated logic:**
- weeks ×3 (`rules`, `metrics`, frontend `periods.ts`);
- the uptime formula in ≥ 7 places;
- the 98.5 threshold ×3 constants plus frontend literals;
- effective-date masking ×5 (`portfolio._effective`, `allkpis._effective`, `calculations`, `sitescope` SQL, `report_export._new_layer_details`).

**PowerPoint:** no PowerPoint export exists in the backend or frontend. `.pptx` is accepted only as a manually uploaded email attachment (`alerts/reports.py:28`).

---

## 8. Downstream consumer dependency map

| Consumer | Data path | Calculations | Same period as the dashboard? | Known inconsistencies |
|---|---|---|---|---|
| Dashboard 4G / LWE / Overview, Threshold Analysis, circle tables, Teams, CI/IE, Top Performers | `dashboard_source.dataset(pairs, scope)` | `metrics` | yes | alerts, site detail and filters use the "all" variant (C-6); history populations (C-7) |
| Site Portfolio | same, plus `portfolio` helpers | `metrics` | yes | weekly shows partial weeks (C-5) |
| All KPI's | `dashboard_source.dataset(pairs)` ("all") plus its own masks | own `per_site`/`aggregate` | current month yes | USD/NSLA (C-3), partial weeks (C-5), "(MTD)" labels (C-10), On-Air (C-8) |
| RCA | RCA tables plus `dashboard_source` "all" | own USD/NSLA | mixed | C-3, C-7, C-11, C-15 |
| Data Panel | ORM on daily / monthly / site | stored values | shows every date | none material |
| CSV Arrival Tracker and reminders | daily table and batches directly | own coverage | own date | C-8, C-9 |
| Excel exports (portal) | scope variant | `metrics` + `monthly_outage` + Excel formulas | yes | C-4, C-5, C-13 |
| Emailed reports | "all" variant | `report_export` | yes | **C-6** |
| Organization usage | ORM counts | On-Air ≤ today | n/a | C-8 |
| Team Hierarchy pages | **frontend mock data** | n/a | n/a | C-14 |
| PowerPoint | **none** | | | |

---

## 9. Issue register

Fields: ID · Severity · Category · Location · Existing → Expected · Evidence · Proposed fix · Required tests · Dependencies · Status.

### 9.1 Confirmed defects

**C-1 · Critical · Reporting**
- **Location:** `apps/sitedata/dataset.py:completeness`, `reporting_month`; `portfolio.continuous`
- **Existing:** Expected units = every unit that has *ever* reported. A unit that starts mid-month makes every earlier date incomplete. If the latest month's 1st is then incomplete, `reported_dates = ()`: dashboards, Portfolio, All KPI's, RCA site metrics, exports and emails return no data or 400. A unit that stops reporting freezes the month forever.
- **Expected:** Adding or removing a unit never invalidates dates complete before or after it.
- **Evidence:** [EXP e1 C]
- **Fix:** Make the expected units date-dependent, e.g. `expected(d)` = units with ≥ 1 dashboard site with `on_air_date ≤ d` (the registry choice is B-2). Fall back to the latest fully complete month instead of an empty MTD.
- **Tests:**
  - a unit starting mid-month keeps earlier dates complete;
  - a ceased unit does not freeze the month;
  - a restricted user never gets empty dates while their units are complete.
- **Dependencies:** B-2
- **Status:** Confirmed

**C-2 · High · Reporting**
- **Location:** `dataset.completeness` (global); `portfolio.continuous`; `dashboard/scope._subset` (drops warnings)
- **Existing:**
  - Incomplete LWE stops the 4G MTD; LWE missing on the 1st keeps 4G on the previous month.
  - A 4G-only user gets no explanation (the `pending_month` warning is dropped).
  - With the available November files: 4G visible only to **3 Nov**.
- **Expected:** Per the decision in B-3 (network-wide vs per technology vs per user scope), and always explained.
- **Evidence:** [EXP e1 A/B], [FILE] November analysis
- **Fix:** Store per-date unit sets; compute complete dates against the expected units ∩ the units in the restricted dataset; optionally a per-technology reporting month; keep the warnings in restricted datasets.
- **Tests:** 4G complete with LWE partial, for a 4G-only, an LWE-only and an all-circles user.
- **Dependencies:** B-3, C-1
- **Status:** Confirmed (behaviour); rule = Business decision

**C-3 · High · Calculation**
- **Location:** `metrics.unique_sites_down`/`_nsla_values`; `allkpis/services.per_site/aggregate`; `rca/breakdown.site_metrics`; frontend `RcaBreakdown.tsx:23`
- **Existing:** Three USD and three NSLA definitions. On the same data: USD 2/1/1/2 and NSLA 1/0/1/2 across consumers. The RCA label says "over the period" while the code uses "any single day".
- **Expected:** One approved definition each, implemented once.
- **Evidence:** [EXP e4, e2]
- **Fix:** `metrics.usd_mask()` and `metrics.nsla_mask()` used by every consumer; correct the labels.
- **Tests:** one fixture asserted identically in `period_summary`, `allkpis.summary`, `rca.site_metrics` and `team_monthly_nsla`.
- **Dependencies:** B-4
- **Status:** Confirmed (behaviour); definition = Business decision

**C-4 · High · Calculation**
- **Location:** `report_export.ConsolidatedReport.month_block/uptime/site_uptimes/_uptime_cell`
- **Existing:** History months use `monthly_outage / (1440 × calendar days)`, so missing days count as zero outage. On the same data the export gives 96.77 % and the dashboard 96.08 %.
- **Expected:** The same as `metrics.monthly` (reporting days).
- **Evidence:** [EXP e3]
- **Fix:** Build history values from `ds.daily_history` through `metrics.month_values`; mask `monthly_outage` in `_effective` or stop using it.
- **Tests:** a history month with gaps gives equal values in every sheet and on the dashboard.
- **Dependencies:** —
- **Status:** Confirmed

**C-5 · High · Reporting**
- **Location:** `allkpis/services.trends` (week); `report_export.windows` and the Wk formulas; frontend `lib/periods.ts:weekPeriod`
- **Existing:** The dashboard and thresholds hide incomplete weeks. All KPI's, the Consolidated export and Portfolio weekly show week-to-date values (Week 2 = 86.11 % from 2 days).
- **Expected:** One rule (B-5), applied everywhere.
- **Evidence:** [EXP e3]
- **Fix:** A shared `metrics.week_columns` rule; blank or mark incomplete weeks in All KPI's, the export (values and formulas) and Portfolio.
- **Tests:** data through the 9th → Week 2 blank (or marked) in all four consumers.
- **Dependencies:** B-5
- **Status:** Confirmed

**C-6 · High · Reporting**
- **Location:** `alerts/reports.build` (no scope); `dashboard/views.alerts_view`, `record_detail_view`, `filters_view`
- **Existing:** Emails and header alerts use the "all" variant. The portal uses the On-Air variant. Same data: email 86.11 % vs portal 92.42 %. Alerts miss unreported sites.
- **Expected:** Emails and alerts equal the portal for the same pairs and scope.
- **Evidence:** [EXP e3, e5]
- **Fix:** Pass `scope=metrics.DEFAULT_SCOPE` (or the automation's scope) in those calls.
- **Tests:** email bytes equal the portal export; alerts equal the summary on on_air.
- **Dependencies:** —
- **Status:** Confirmed

**C-7 · Medium · Calculation**
- **Location:** `metrics.scope_mask` for history periods; `report_export.rows_for`; `rca.site_metrics`
- **Existing:** History months use the *reporting month's* On-Air/O&M flags. A site On-Air from November counts as no-value in October.
- **Expected:** Per-month eligibility from effective dates (B-6).
- **Evidence:** [EXP e5, e4]
- **Fix:** Compute history populations with `om_effective_from` / `on_air_effective_from` per month.
- **Tests:** a site On-Air in November is excluded from October everywhere.
- **Dependencies:** B-6
- **Status:** Confirmed

**C-8 · Medium · Calculation**
- **Location:** `dataset.build:110`; `arrivals._pairs`; `organization/services.usage_by_pair`; `allkpis.per_site`
- **Existing:** Four On-Air rules (end of reporting month / the date / today / period end). The dashboard shows "missing 50 %" while the tracker says complete.
- **Expected:** One rule (B-6).
- **Evidence:** [EXP e5]
- **Fix:** A shared `rules.on_air_on(date)` used by all consumers.
- **Tests:** a site On-Air after the latest data date.
- **Dependencies:** B-6
- **Status:** Confirmed

**C-9 · Medium · Reporting**
- **Location:** `dataset.completeness` vs `arrivals.data_state`
- **Existing:** The dashboard calls a unit complete with 1 site of N; the tracker needs every On-Air site.
- **Expected:** One coverage rule (B-7).
- **Evidence:** [CODE]
- **Fix:** Use the tracker's expected-site logic (and an approved threshold) in `completeness`.
- **Tests:** a unit with 1 of 500 sites; the dashboard and tracker agree.
- **Dependencies:** B-7
- **Status:** Confirmed

**C-10 · Medium · Reporting**
- **Location:** `dataset.build` history; `metrics.monthly` (`partial: False`); `allkpis.trends` month label
- **Existing:** History months include incomplete dates and are shown as complete; closed months with gaps are labelled "(MTD)". A month's figure changes at rollover.
- **Expected:** Expose `days_reported`, `days_in_month` and `finalized`; label incomplete months.
- **Evidence:** [CODE/EXP e3]
- **Fix:** As expected; the rule for incomplete days in closed months is B-8.
- **Tests:** a closed month with a gap shows "incomplete".
- **Dependencies:** B-8
- **Status:** Confirmed

**C-11 · Medium · Calculation**
- **Location:** `rca/breakdown.site_metrics:185`, `rca/services.summary:642`
- **Existing:** The "NSLA RCA" filter builds keys from the raw `site_id` and ignores the project; a lower-case or double-spaced ID drops the record.
- **Expected:** Match on (technology, `key_of(site_id)`).
- **Evidence:** [EXP e4]
- **Fix:** As expected.
- **Tests:** a mixed-case or double-space ID; the same ID in two technologies.
- **Dependencies:** —
- **Status:** Confirmed

**C-12 · Medium · Calculation**
- **Location:** `metrics.uptime_pct` (4 dp); `_record`; frontend `constants.ts:uptimeColor`, `SiteDetailSheet.tsx`, `formatPct`, hard-coded 98.5 / 60
- **Existing:** 98.49996 % is returned as 98.5 and coloured green while it sits in bucket 97–98.5 and in the NSLA list; there are two colour scales.
- **Expected:** Colour from the API bucket id; one `bucketOf` with 6-dp rounding.
- **Evidence:** [EXP e2]
- **Fix:** As expected; expose the bucket bounds in the filters response.
- **Tests:** frontend unit tests at 98.49996, 98.5 and 98.495.
- **Dependencies:** —
- **Status:** Confirmed

**C-13 · Medium · Calculation**
- **Location:** `report_export._bucket_formula`, `f_uptime`/`w_up`
- **Existing:** Excel bucket formulas do not round; 109 fuzz cases differ from Python (a mean of exactly 98.5 → ">97 To <98.5").
- **Expected:** `IF(ROUND(x*100,6)>=98.5, …)`.
- **Evidence:** [EXP e2 fuzz]
- **Fix:** As expected.
- **Tests:** the formula text contains ROUND; optional LibreOffice evaluation.
- **Dependencies:** —
- **Status:** Confirmed

**C-14 · Medium · Reporting**
- **Location:** `frontend/src/pages/hierarchy/*` + `services/hierarchyMockData.ts`
- **Existing:** Admin-routed Team Hierarchy pages show demo data.
- **Expected:** No non-authoritative figures in production.
- **Evidence:** [CODE]
- **Fix:** Hide the route, or wire it to the hierarchy tables / `metrics.team_monthly_nsla`.
- **Tests:** route hidden / no mock import.
- **Dependencies:** —
- **Status:** Confirmed

**I-1 · High · Ingestion**
- **Location:** `uptime_master.analyse`; `rawcsv.preview` (service); `daily._check_correction`, `data_views.daily_correct`
- **Existing:** Future dates are accepted: Uptime Master zero outage on 12–13 Nov stored as 100 %; a raw CSV for 1 Dec via the service; a correction on 2027-01-15.
- **Expected:** Refuse `report_date > today` everywhere.
- **Evidence:** [EXP U4, E15, C1]
- **Fix:** A central check in `daily.classify`/`write`, plus row rejection `future_date` in the analysers.
- **Tests:** one per source.
- **Dependencies:** —
- **Status:** Confirmed

**I-2 · High · Ingestion**
- **Location:** `sources/uptime_report.parse_workbook:252`; `uptime_master.analyse:258-293`
- **Existing:** An unknown circle is kept as written; a row circle ≠ the site's circle is only counted as an attribute difference; status PASSED.
- **Expected:** Reject `unknown_circle` and `site_of_other_circle` (as documented in the module docstring).
- **Evidence:** [EXP U1, U2]
- **Fix:** As expected; also put attribute differences into warnings.
- **Tests:** unknown circle → rejected; RJ row for an MP site → rejected.
- **Dependencies:** —
- **Status:** Confirmed

**I-3 · High · Ingestion**
- **Location:** `uptime_master.read_up_time_report/analyse`
- **Existing:** The same site twice in one file (two circles, or master + alternate ID): preview PASSED, commit **IntegrityError → HTTP 500**; the batch is uncommittable.
- **Expected:** Reject duplicate site-days (as the raw CSV and day-wise paths do).
- **Evidence:** [EXP U1, U6]
- **Fix:** Group resolved values by (site, day); identical → duplicate, different → reject all; catch IntegrityError → 409.
- **Tests:** both layouts.
- **Dependencies:** —
- **Status:** Confirmed

**I-4 · Medium · Ingestion**
- **Location:** `rawcsv.analyse`, `rules.check_availability`
- **Existing:** A file reporting fractions (0.995) is imported as 0.995 % (outage 1,425.7 min); PASSED.
- **Expected:** Detect implausible scales.
- **Evidence:** [EXP E6]
- **Fix:** A file-level plausibility rule (e.g. ≥ 90 % of values ≤ 1.0 → FAILED, Admin override); record unknown headers.
- **Tests:** an all-fraction file → FAILED.
- **Dependencies:** —
- **Status:** Confirmed

**I-5 · Medium · Ingestion**
- **Location:** `rawcsv.read:69,77`
- **Existing:** A duplicated TCS column: the last one wins silently; rows with extra or short cells are padded or ignored.
- **Expected:** Reject duplicate headers and malformed rows.
- **Evidence:** [EXP E3, E4b]
- **Fix:** Reuse `cnmc_csv.parse` checks; `len(cells) != len(header)` → `malformed_row`; `csv.Error` → UploadRejected.
- **Tests:** both cases.
- **Dependencies:** —
- **Status:** Confirmed

**I-6 · Medium · Ingestion**
- **Location:** `rawcsv.analyse:227-247`, `uploads.record_preview`; `uptime_master.analyse`
- **Existing:** 1 of 2 sites → PASSED; an all-rows-rejected file is committable; no coverage warning.
- **Expected:** A coverage warning below a threshold; FAILED when nothing is importable and rows were rejected.
- **Evidence:** [EXP E6, E13]
- **Fix:** As expected (threshold = B-7).
- **Tests:** coverage warning; all rejected → FAILED.
- **Dependencies:** B-7
- **Status:** Confirmed

**I-7 · Medium · Ingestion**
- **Location:** `uptime_master.months_in_scope:90-101`
- **Existing:** Scope is the hard-coded 2026-09 up to the current month (no setting); an old workbook silently rewrites past months via precedence.
- **Expected:** Configured scope; warn on past months.
- **Evidence:** [EXP U7]
- **Fix:** `SITEDATA_DAILY_FROM` / `SITEDATA_MASTER_DAILY_MONTHS` in settings; past-month warning; optional explicit month selection.
- **Tests:** a past-month warning.
- **Dependencies:** —
- **Status:** Confirmed

**I-8 · Medium · Ingestion**
- **Location:** `rawcsv.analyse:180-190`, `uptime_master.analyse:258-271`
- **Existing:** Values are accepted for sites the latest matrix no longer lists.
- **Expected:** Skip or warn (`not_in_latest_matrix`).
- **Evidence:** [EXP E16]
- **Fix:** As expected.
- **Tests:** one per importer.
- **Dependencies:** —
- **Status:** Confirmed

**I-9 · Medium · Security / Ingestion**
- **Location:** `raw_views`, `matrix_views`, `uptime_views`, `data_views` size checks; `settings.py`
- **Existing:** Size is checked after the full body is received; no zip-bomb guard; `.xlsm` accepted.
- **Expected:** Early limit and package checks.
- **Evidence:** [CODE]
- **Fix:** A proxy/WSGI body limit; a custom `FileUploadHandler`; a zip size/ratio check; drop `.xlsm`.
- **Tests:** an oversized upload aborted; a high-ratio zip rejected.
- **Dependencies:** —
- **Status:** Confirmed

**I-10 · Low · Ingestion**
- **Location:** `sources/uptime_report._number:103`
- **Existing:** "50%" in an outage cell is stored as 0.5 min.
- **Expected:** Reject.
- **Evidence:** [EXP U5]
- **Fix:** For outage columns, text ending in % → `invalid_value`.
- **Tests:** a unit test.
- **Dependencies:** —
- **Status:** Confirmed

**I-11 · Low · Ingestion**
- **Location:** `rules._number` vs `uptime_report`
- **Existing:** `-`/`NA` is rejected in the raw CSV but means "not reported" in the Uptime Master.
- **Expected:** One rule.
- **Evidence:** [CODE]
- **Fix:** Use `identifiers.PLACEHOLDERS` in `check_availability`.
- **Tests:** placeholder → not reported.
- **Dependencies:** —
- **Status:** Confirmed

**I-12 · Low · Ingestion**
- **Location:** `rawcsv.analyse:159`
- **Existing:** An `AliasResolver` is built per row, giving extra queries under the global lock.
- **Expected:** One resolver per analysis.
- **Evidence:** [CODE]
- **Fix:** As expected.
- **Tests:** a query-count test.
- **Dependencies:** —
- **Status:** Confirmed

**I-13 · Low · Ingestion**
- **Location:** `uptime_master._in_scope` callers
- **Existing:** Values in months outside the scope are dropped without a warning (e.g. the LWE Nov file declares 2026-12).
- **Expected:** Count and warn.
- **Evidence:** [FILE/CODE]
- **Fix:** Report `out_of_scope_site_days` per month in warnings.
- **Tests:** a file with an out-of-scope month.
- **Dependencies:** —
- **Status:** Confirmed

**I-14 · Low · Mapping**
- **Location:** `rawcsv._resolve_4g`
- **Existing:** A blocked (ambiguous) BSNL ID is reported as "unmatched", not "ambiguous".
- **Expected:** `ambiguous_identifier`.
- **Evidence:** [CODE]
- **Fix:** Check `index.is_blocked`.
- **Tests:** a unit test.
- **Dependencies:** —
- **Status:** Confirmed

**M-1 · Medium · Mapping**
- **Location:** `rawcsv._resolve_4g/_resolve_lwe`, `raw_views.REASONS`
- **Existing:** Whole-circle CNMC dumps make thousands of non-programme BTSs "unmatched … kept pending" (e.g. 4,373 of 6,131), drowning genuine mapping gaps.
- **Expected:** The deterministic classification of §6.1.
- **Evidence:** [DB] batches #7, #15, #21
- **Fix:**
  - Classify as `outside_programme` when no identifier is known in any identifier table (informational count).
  - Keep only rows with a known-but-unresolved identifier as pending.
  - Surface `sites_without_value`.
- **Tests:** a dump with programme, non-programme and partially-known rows.
- **Dependencies:** B-1 (rule approval)
- **Status:** Confirmed (behaviour); rule = Business decision

**M-2 · Medium · Mapping**
- **Location:** `unmatched._uploads` (Uptime Master only)
- **Existing:** Raw CSV unmatched rows cannot be reprocessed after a mapping fix, except by re-uploading the file.
- **Expected:** A persistent pending record with a resolve/reprocess path.
- **Evidence:** [CODE]
- **Fix:** A `PendingRecord` table (see S-5) covering both sources.
- **Tests:** map an identifier → process → value imported at its source rank.
- **Dependencies:** S-5
- **Status:** Confirmed

**M-3 · High · Mapping**
- **Location:** `uptime_master.analyse` lists capped at 200; `unmatched.report/process_pending`
- **Existing:** Unmatched sites beyond the first 200 never appear and can never be processed.
- **Expected:** All of them are processable.
- **Evidence:** [EXP t6]
- **Fix:** Store an uncapped key list (or a `PendingRecord` table); keep the capped lists for display.
- **Tests:** > 200 unmatched, map the last one, process.
- **Dependencies:** S-5
- **Status:** Confirmed

**M-4 · High · Mapping / Commit**
- **Location:** `unmatched.process_pending:166-173`
- **Existing:** Classify runs **outside** the lock; an Admin correction made in that window is overwritten by the Uptime value (the event records a stale stored value).
- **Expected:** Classify under the lock; the correction is kept.
- **Evidence:** [EXP P1]
- **Fix:** Move `analyse` + `classify` inside `atomic` after `write_lock()` and `select_for_update`.
- **Tests:** an injected concurrent correction is kept.
- **Dependencies:** —
- **Status:** Confirmed

**M-5 · High · Mapping / Commit**
- **Location:** `unmatched.process_pending:149-188`
- **Existing:** A `FinalizedPeriod` on one upload aborts the loop before the refresh: earlier uploads stay written with stale monthly results, and every later run fails.
- **Expected:** Skip and report the finalized dates; always refresh what was written.
- **Evidence:** [EXP t3]
- **Fix:** Catch per upload; `try/finally` refresh.
- **Tests:** open October + finalized November pending.
- **Dependencies:** —
- **Status:** Confirmed

**M-6 · Medium · Mapping**
- **Location:** `uptime_views.unmatched_process`
- **Existing:** Pending processing writes without a preview.
- **Expected:** Dry run, then confirm.
- **Evidence:** [CODE]
- **Fix:** A dry-run endpoint returning per-upload counts; commit on a count match.
- **Tests:** dry run equals commit.
- **Dependencies:** M-4
- **Status:** Confirmed

**P-1 · Low · Ingestion**
- **Location:** `uploads.same_counts`
- **Existing:** Commit compares only aggregate counts with the preview; equal-count value changes are committed without re-approval.
- **Expected:** Compare a digest of the classified (site, date, value, action).
- **Evidence:** [CODE]
- **Fix:** Store `classification_digest` at preview; refuse on mismatch.
- **Tests:** a changed value with equal counts → 409.
- **Dependencies:** —
- **Status:** Confirmed

**P-3 · Medium · Ingestion**
- **Location:** `uploads.discard`; `matrix_views.matrix_discard`; `uptime_views.uptime_discard`
- **Existing:** Discard checks status without a row lock; a committed batch can be marked "discarded" while its daily rows remain.
- **Expected:** Lock the row and re-check the status.
- **Evidence:** [EXP D1]
- **Fix:** `select_for_update` in `atomic`; use `uploads.discard` in every view.
- **Tests:** discard after commit → 409.
- **Dependencies:** —
- **Status:** Confirmed

**E-1 · Medium · Commit**
- **Location:** `uploads.refresh_after_daily_write` callers (rawcsv, uptime_master, matrix, unmatched, masterdata)
- **Existing:** The monthly recalculation runs after the transaction. If it fails, the batch is committed with stale monthly results, the API returns 500, and there is no recalculate endpoint.
- **Expected:** A durable "month needs recalculation" record and a retry.
- **Evidence:** [EXP R1]
- **Fix:** A dirty-months record (set in the commit transaction), a retry worker/endpoint, `transaction.on_commit`.
- **Tests:** a patched failure → month marked dirty → recalculated.
- **Dependencies:** —
- **Status:** Confirmed

**E-4 · Medium · Calculation**
- **Location:** `calculations.calculate_month:65-89`
- **Existing:** When the matrix moves a site's O&M/On-Air date out of a month, the old category row stays current.
- **Expected:** Supersede rows no longer produced.
- **Evidence:** [EXP t5]
- **Fix:** `is_current=False` for current non-finalized keys absent from the results.
- **Tests:** a date change removes the row.
- **Dependencies:** —
- **Status:** Confirmed

**E-5 · Low · Commit**
- **Location:** `masterdata/editing._save_corrections`; `accounts/audit`
- **Existing:** The audit line is written even when the Data Panel save rolls back; audit is log-only.
- **Expected:** Audit after the commit.
- **Evidence:** [CODE]
- **Fix:** `transaction.on_commit(audit)`.
- **Tests:** a rolled-back save leaves no audit.
- **Dependencies:** T-2
- **Status:** Confirmed

**S-1 · High · Storage**
- **Location:** `uploads.staging_dir/new_batch`, `exceptions.exception_dir/write`; `UploadBatch.stored_path`, `report['exception_report']`
- **Existing:**
  - Staged copies and exception CSVs are written to `<DATA_DIR>/processed/sitedata` (default: the project's git-ignored `Data/` folder) and referenced by **absolute local path**.
  - All 24 batches point to `C:\Users\gaura\…` and none exist here.
- **Expected:** Application-managed storage with relative keys and checksums.
- **Evidence:** [DB] all 24 batches `staged_exists=False`, `exc_exists=False`
- **Fix:** See section 10 (storage architecture).
- **Tests:** storage relocation keeps every batch resolvable; a missing file is reported as missing.
- **Dependencies:** —
- **Status:** Confirmed

**S-2 · Medium · Storage**
- **Location:** `matrix_views.matrix_issues_csv`, `uptime_views` issues, `data_views._issues`
- **Existing:** A missing exception file returns a header-only CSV, indistinguishable from "no exceptions"; historical exception downloads are empty.
- **Expected:** "Source file / exception report missing" (HTTP 410) or regeneration from stored exceptions.
- **Evidence:** [CODE/DB]
- **Fix:** Persist exceptions in a table (S-5) and generate CSVs on demand; return an explicit missing status otherwise.
- **Tests:** a missing file → explicit message.
- **Dependencies:** S-5
- **Status:** Confirmed

**S-3 · Medium · Storage**
- **Location:** batches #3, #5 (Uptime Master, pending 60 / 62 site-days of the two RJ sites not in the matrix)
- **Existing:** `process_pending` needs the staged file, which is missing, so those pending rows can never be processed.
- **Expected:** Pending rows persisted independently of files.
- **Evidence:** [DB]
- **Fix:** S-5; for existing batches, re-upload the source files (not executed).
- **Tests:** —
- **Dependencies:** S-5
- **Status:** Confirmed

**T-1 · Medium · Storage / Traceability**
- **Location:** `sitedata_uploadbatch.uploaded_by_id`
- **Existing:** 20 of 24 committed batches have no uploader (script imports on 4 Nov).
- **Expected:** Every batch attributed.
- **Evidence:** [DB]
- **Fix:** Require a user in every service entry point (commands take `--user`); add a NOT NULL check for new batches (`uploaded_by` or `system_actor` text).
- **Tests:** a command without a user → refused.
- **Dependencies:** —
- **Status:** Confirmed

**C-15 · Low · Calculation**
- **Location:** `rca/services._population`
- **Existing:** The unrestricted dataset includes non-On-Air sites; the per-100-site rates use a different denominator.
- **Expected:** Pairs and On-Air.
- **Evidence:** [CODE]
- **Fix:** Pass `pairs`; use On-Air sites.
- **Tests:** restricted user rates.
- **Dependencies:** C-3
- **Status:** Confirmed

**C-16 · Low · Calculation**
- **Location:** `portfolio.monthly_activity:164`
- **Existing:** The latest dates are computed over all sites, not the user's pairs.
- **Expected:** Within pairs.
- **Evidence:** [CODE]
- **Fix:** Filter by pairs.
- **Tests:** restricted user.
- **Dependencies:** —
- **Status:** Confirmed

**C-17 · Low · Calculation**
- **Location:** duplicated helpers (§7)
- **Existing:** Weeks ×3, uptime formula ×7, threshold ×3, effective-date masking ×5; the unused `NSLA_OUTAGE_MINUTES_THRESHOLD`; a stale `dataset.py` docstring.
- **Expected:** One helper each.
- **Evidence:** [CODE]
- **Fix:** Consolidate in `rules`/`metrics`.
- **Tests:** existing suites.
- **Dependencies:** C-3, C-5
- **Status:** Confirmed

**C-18 · Low · Calculation**
- **Location:** frontend `OutageChart.CircleOutage`
- **Existing:** Divides summed outage by sites in scope, so missing days lower per-site outage.
- **Expected:** Divide by reported site-days from the API.
- **Evidence:** [CODE]
- **Fix:** As expected.
- **Tests:** a frontend unit test.
- **Dependencies:** —
- **Status:** Confirmed

**I-15 · Low · Ingestion**
- **Location:** `uptime_master.analyse` failure path
- **Existing:** A non-`UploadRejected` exception leaves validation "pending", which `require_previewed` allows (the commit then fails again).
- **Expected:** Mark FAILED.
- **Evidence:** [CODE]
- **Fix:** Catch → `record_preview(failed=True)`.
- **Tests:** a parser crash → FAILED.
- **Dependencies:** —
- **Status:** Confirmed

**I-16 · Low · Ingestion**
- **Location:** `daily.correct` / views
- **Existing:** No finalized-month warning at preview for imports (only a refusal at commit).
- **Expected:** A preview warning.
- **Evidence:** [CODE]
- **Fix:** Add `finalized_months(dates)` to the preview warnings.
- **Tests:** a preview into a finalized month warns.
- **Dependencies:** —
- **Status:** Confirmed

### 9.2 Suspected defects

**E-2 · Medium · Commit**
- **Location:** `data_views.months_finalize`; `calculations.finalize_month`
- **Existing:** Calculate + finalize run without the write lock; a commit between them leaves finalized results that exclude committed values.
- **Expected:** Serialised.
- **Evidence:** [INF] (needs PostgreSQL concurrency)
- **Fix:** Wrap in `atomic()` + `uploads.write_lock()`.
- **Tests:** a PostgreSQL integration test.
- **Dependencies:** —
- **Status:** Suspected

**E-3 · Medium · Commit**
- **Location:** `calculations.calculate_month`
- **Existing:** No lock; two concurrent refreshes can hit the `sitedata_monthly_current` / `_revision` unique constraints → E-1.
- **Expected:** Serialised recalculation.
- **Evidence:** [INF]
- **Fix:** A per-month advisory lock.
- **Tests:** a PostgreSQL integration test.
- **Dependencies:** E-1
- **Status:** Suspected

**L-5 · Low · Calculation**
- **Location:** `portfolio._key`
- **Existing:** 5 aggregate queries per request; a per-process cache; correct for every write path seen.
- **Expected:** A cheap version counter.
- **Evidence:** [INF]
- **Fix:** A data-version row bumped on every commit.
- **Tests:** —
- **Dependencies:** —
- **Status:** Suspected (performance)

### 9.3 Missing infrastructure

| ID | Sev | Category | What is missing | Proposed implementation | Acceptance |
|---|---|---|---|---|---|
| S-4 | High | Storage | Persistent, application-managed file storage (§10) | A storage abstraction (`django.core.files.storage`, configurable root or S3-compatible) with **relative keys** and SHA-256 in `UploadBatch` | Every batch file resolvable on any machine/deployment; a missing file is detected and reported |
| S-5 | High | Storage / Mapping | Persistent exceptions and pending records | Tables `ImportException` (batch FK, row, identifier, code, severity, message, values) and `PendingRecord` (batch FK, technology, circle, date, identifier, value as read, status pending/resolved/rejected/outside_programme, resolved_site, resolved_by/at, reason) | Exceptions downloadable after restart; pending rows reprocessable without staged files; no duplicate pending rows on re-upload (unique on (identifier, date, technology, source rank)) |
| P-2 | Medium | Ingestion | Preview expiry | `expires_at` on previews (e.g. 7 days) plus re-validation of master/mapping/finalized state at commit; a daily job marks expired previews | An expired preview cannot be committed; the UI shows it |
| T-2 | Medium | Security / Traceability | Durable audit trail | An `AuditEvent` table (actor, action, object, payload, request id) written on commit | Every import, correction, mapping, finalize and discard is queryable |
| T-3 | Medium | Traceability | Resolution route per daily record | `resolved_by` field (bsnl_id / bts_ip / band_2100 / band_700 / alternate) on `DailySitePerformance` | Every value traceable to the identifier that matched |
| D-1 | Medium | Ingestion | Duplicate-file and period policy | Block an exact checksum re-commit unless the earlier batch was discarded; warn on "same technology/circle/date already committed (different checksum)" and show the precedence outcome; allow higher-precedence sources and corrections | A re-uploaded identical file never creates records or pending duplicates; legitimate corrections still allowed |
| R-1 | Low | Reporting | PowerPoint export | None exists; build on `report_export` and `metrics` only if required | Out of scope until requested |

### 9.4 Business decisions pending

| ID | Decision | Evidence | Affects |
|---|---|---|---|
| B-1 | How to treat whole-circle CNMC rows not in any identifier table (proposed: `outside_programme`, informational, not pending) | §6.1 | M-1 |
| B-2 | Registry of expected reporting units per date (matrix On-Air sites per unit / Organization associations / units with records in the month) | C-1 | C-1 |
| B-3 | Completeness scope: network-wide, per technology, or per user scope; may 4G November be reported while LWE is incomplete? | C-2, §6.4 | C-2, November |
| B-4 | One definition each for USD and NSLA (population, period vs any single day, value basis) | C-3 | C-3, C-15 |
| B-5 | Partial weeks: hide everywhere, or show labelled "week to date" | C-5 | C-5 |
| B-6 | On-Air / O&M eligibility per period: on the reporting date, any day of the period, or the reporting month's end | C-7, C-8 | C-7, C-8 |
| B-7 | Coverage threshold for "complete" per unit and date (all On-Air sites, or ≥ X %) | C-9, I-6 | C-9, I-6 |
| B-8 | Closed months with missing days: include the incomplete dates or not; can an incomplete month be finalized? | C-10 | C-10, finalization |

---

## 10. Data integrity and operational risks

| Risk | Likelihood | Impact | Mitigation (issue) |
|---|---|---|---|
| A new circle or technology starts reporting → dashboards go blank | Medium | Critical | C-1 |
| November displayed only to 3 Nov, or not at all, depending on import order | High (now) | High | C-2, B-3 |
| Management sees different USD/NSLA/uptime in dashboard, All KPI's, RCA, exports and emails | Certain | High | C-3–C-6 |
| A wrong file (fractions, future dates, wrong circle, shifted columns) is stored and reported | Medium | High | I-1–I-6 |
| An Admin correction is overwritten during pending processing | Low | High | M-4 |
| Audit evidence (source files, exceptions) unavailable after a machine change | Certain (already) | High | S-1, S-4, S-5 |
| Stale monthly results after a failed refresh | Low | Medium | E-1, E-3 |
| A month finalized with incomplete data | Medium | Medium | B-8, E-2 |
| Unmatched backlog unmanageable (thousands per file) | Certain | Medium | M-1, M-3 |
| The application connects as a PostgreSQL superuser (from the earlier audit) | Certain | High | operational (§11, phase 9) |

**Recommended storage architecture** (S-1/S-4/S-5, not implemented):
1. A `SITEDATA_STORAGE` setting resolving to a Django `Storage` backend: a local filesystem root outside the project for development and single servers, or S3-compatible object storage for deployments.
2. Store **relative keys** (`uploads/<kind>/<yyyy>/<mm>/<batch_id>-<sha10>.<ext>`) plus `size_bytes` and SHA-256 in `UploadBatch`. Never store absolute paths.
3. The original upload is written once (write-once) and verified by checksum on every read. A `file_status` (present / missing / checksum_mismatch) is computed by a health job and shown in import history.
4. Exceptions and pending records live in database tables (S-5). CSV downloads are generated on demand, so they never depend on a file existing.
5. A retention policy: keep committed sources for the audit retention period; delete discarded or expired previews after N days.
6. Back up storage with the database; a restore test covers both.

---

## 11. Prioritized remediation roadmap

| Phase | Scope (issues) | Acceptance criteria | Dependencies |
|---|---|---|---|
| **1. File persistence and import traceability** | S-1, S-4, S-2, T-1, T-2, T-3, E-5 | Every batch has a relative storage key and checksum; missing files are reported explicitly; every batch and record is attributable (user or system actor, resolution route); a durable audit table | — |
| **2. Master data and programme site eligibility** | I-8, B-2, B-6, C-8 groundwork, matrix-date audit of 78/14 sites without dates | One `rules` helper for On-Air/O&M per date; values for sites no longer in the matrix flagged; expected-unit registry agreed | B-2, B-6 |
| **3. CSV validation and site mapping** | I-1–I-14, M-1, B-1 | Each experiment in §5 becomes a failing-then-passing test; whole-circle dumps classified per §6.1; no wrong-format file reaches the daily table | B-1, B-7 |
| **4. Preview and exception management** | S-5, M-2, M-3, M-6, P-1, P-2, P-3, S-3 | Exceptions and pending rows persisted and reprocessable without files; previews expire; equal-count changes refused; discard is race-safe; stale previews #23/#24 discarded after approval | Phase 1 |
| **5. Commit safety, idempotency, concurrency** | M-4, M-5, E-1, E-2, E-3, D-1, I-15, I-16 | PostgreSQL integration tests: concurrent commits, finalize vs commit, process_pending vs correction, failed refresh → retry; duplicate-file policy enforced | Phase 4 |
| **6. Daily and monthly calculation consistency** | C-3, C-4, C-7, C-11, C-13, C-15, C-17, E-4 | One fixture gives identical USD/NSLA/uptime in dashboard, All KPI's, RCA, Excel (Python and formulas) and emails | B-4, B-6 |
| **7. Reporting completeness and finalization** | C-1, C-2, C-9, C-10, C-5, B-3, B-5, B-7, B-8 | No dashboard blanking; documented per-technology/scope behaviour; received/covered/complete/finalized exposed in the API and UI; finalization blocked or flagged for incomplete months | B-2, B-3, B-5, B-7, B-8 |
| **8. Dashboard, RCA and export reconciliation** | C-6, C-12, C-14, C-16, C-18; November import (after phases 3–7) | Email = portal; frontend colours = backend buckets; no mock pages; a reconciliation report for November signed off | Phases 6–7 |
| **9. Operational monitoring and deployment** | I-9, I-12, L-5, file health job, least-privilege DB role, Python 3.11–3.13 environment, backups incl. storage | Health dashboard (file status, dirty months, pending backlog, last import per unit); app role not superuser; restore rehearsed | Phases 1–8 |

---

## Appendix: commands and evidence

**Read-only database checks on `fourg_db`:**
- batch inventory: `kind`, status, counts, staged/exception file existence;
- report JSON breakdown of batches #7, #15, #21;
- `dataset.completeness` / `reporting_month`;
- monthly and finalization status;
- max daily date per technology.

**File analysis:**
- `uptime_master.analyse()` and `rawcsv.analyse()` on the November files in the other project copy;
- an overlap comparison of 48e3 vs 33f2 (12,170 site-days, 0 differences);
- all inside a read-only transaction, rolled back.

**Scratch experiments (in-memory SQLite):**
- ingestion: `scratchpad\audit_ingest\` (E1–E16, U1–U7, C1, D1, P1, R1, t3, t5, t6);
- calculations: `scratchpad\audit_calc\` (e1–e5, fuzz).

**Not verified:**
- PostgreSQL concurrency behaviour (E-2, E-3);
- Excel formula evaluation in Excel itself (C-13 is evaluated by equivalent arithmetic);
- whether the original developer's machine still holds the staged files.
