# Sitedata Complete Migration and Legacy Retirement Plan

| | |
|---|---|
| Date | 11 Nov 2026 |
| Code baseline | `main` at `9a69ada` |
| Inputs | `COMPREHENSIVE_PROJECT_AUDIT.md` (issues `C-n`), `POSTGRESQL_DATABASE_STATE_AUDIT.md` (risks `R-n`). `DATABASE_RECOVERY_AND_MIGRATION_PLAN.md`, `DATABASE_ARCHITECTURE.md` and `MIGRATION_TRACKER.md` **do not exist** [V]; this plan provides their content (sections 2 and 12). |
| Status | **Plan only. Nothing has been implemented.** No migration was run, no record changed, no preview committed, and no file deleted. All database queries for this plan were `SELECT`s in read-only sessions. |
| Tags | **[V]** verified in code or database. **[I]** inference or assumption. **[BD]** business decision required before implementation. |

---

## 0. Findings That Shape This Plan (new in this pass)

1. **[V] Two working copies of the project share one database.**
   - This repository: `C:\Users\pc\Desktop\BSNL_4G`, `main@9a69ada`.
   - `C:\Users\pc\Desktop\4G Saturation_Portal\4G Saturation_Portal`: `e0cd4c4` plus an uncommitted working tree, same GitHub remote.
   - Both `backend/.env` files target `fourg_db@127.0.0.1:5432`.
   - The second copy ran today's legacy import: `uptimedb_dataimportbatch` 41–43 have `stored_path` under that folder.
   - Its `Data/` folders hold the source and staged files this plan needs.
   - **Implementation must use exactly one working copy and one database at a time.**
2. **[V] The November source files are on this machine** (second copy, `Data/processed/imports/`):

   | Legacy batch | File | Checksum (prefix) | Staged copy | Rows in legacy |
   |---|---|---|---|---|
   | 36 (5 Nov) | `RJ, MP & OD - Uptime Report- Nov-26.xlsx` | `33f2a1b93e` | `20261105-130225/130306/130325-33f2a1b93e.xlsx` | 9,883 (1–3 Nov) |
   | **43 (11 Nov, today)** | same name, **newer version** | `48e3e33a20` | `20261111-164427/164509/164533-48e3e33a20.xlsx` | 33,266 (30,180 reported; 3–10 Nov) |
   | 34 (5 Nov) | `LWE Uptime Report - Nov'26.xlsx` | `96617c84f6` | `20261105-130057-96617c84f6.xlsx` | 834 (278 sites, 1–3 Nov) |
   | 25, 26 | raw CNMC CSV MP / RJ, 1 Nov | `346a255c51` / `1b278e44ed` | `Data/processed/raw_uploads/2026-11-01/` | 1,351 / 940 |

3. **[V] The two previewed November `sitedata` batches (#23, #24) are identical previews of the *older* file `33f2a1b93e`.**
   - Each received 12,174 site-days, 12,170 accepted, 4 unmatched (UVRJJPR00057, UVRJUPR00612).
   - Their staged copies point to `C:\Users\gaura\OneDrive\...` and **do not exist on this machine**. `commit()` re-verifies the staged file, so they **cannot be committed here**, and they are superseded by `48e3e33a20` anyway.
4. **[V] All 2,493 October differences are a source-file difference:**
   - `sitedata` loaded `LWE Uptime Report - Oct'26.xlsx` (and `RJ MP OD - Uptime Report- Oct-26 (003).xlsx` for 4 OD 4G site-days);
   - legacy loaded `4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (and the `(005)` variant).
   - 399 sites, 1–27 Oct.
   - The direction is mixed: 1,227 site-days are higher in `sitedata`, 1,266 lower.
   - Record-level file: `C:\Users\pc\AppData\Local\Temp\claude\060f0d7cda492f67\cb105ccf-fc7d-4b01-b78f-f881d2091131\scratchpad\pg\october_layer_differences.csv`. It has 16 columns: site, date, both values, both source files and batch IDs, and the difference.
5. **[V] RCA recovery candidates exist,** but the authoritative one is not on this machine. See section 5.3.
6. **[V] Dashboard monthly history is already limited to Sep–Oct 2026.**
   - `sitedata/dataset.py` builds history only from `MonthlySitePerformance` and `DailySitePerformance`.
   - Legacy monthly rows for **Oct 2025 – Aug 2026** (6,726 sites per month) are no longer shown on any dashboard, and will be lost on retirement unless migrated **[BD-3]**.
7. **[V] The `uptimedb` migrations package cannot simply be deleted.**
   - `organization.0002_initial_organization` depends on `uptimedb.0004` and reads `uptimedb.UptimeSite` in a data step (`:59,121`).
   - `rca.0002_reporting_cycles` depends on `uptimedb.0003` and imports `apps.uptimedb.migrations.0002_escalation_matrix` (`:12,22`).
   - `organization.0004` depends on `uptimedb.0005`.

---

## 1. Gating Phase 0: Database Identity and Completeness (must finish before Phase 1 work touches data)

Nothing in Phases 2–8 that writes data may start until all of these are answered and signed off.

| # | Question | How | Owner |
|---|---|---|---|
| G1 | Which database is production: `4G-DB` on the original developer machine (`C:\Users\gaura\…`), or `fourg_db` here? | Run `POSTGRESQL_DATABASE_STATE_AUDIT.md` §11 Q1–Q13 read-only on each candidate | Project owner + DBA |
| G2 | Is the production RCA data intact (about 178,692 records on 4 Nov)? | Q12 on production; `pg_restore --list` of `C:\Users\gaura\Backups\4G-DB\20261104T124210Z\*.dump` | DBA |
| G3 | Is `organization.0004` unapplied in every environment? | Q2/Q3 | DBA |
| G4 | Which working copy is canonical (`BSNL_4G` vs `4G Saturation_Portal`)? Freeze the other (read-only; no uploads). | Team decision | Project owner |
| G5 | Fresh backup of the canonical database, **restore-tested into a scratch database**, with checksums recorded | `pg_dump -Fc`; `createdb <db>_restore_check`; `pg_restore`; row-count comparison | DBA |
| G6 | Copy `Data/processed` and `Data/raw` of both working copies to a backup location, with checksums (staged files are needed for re-imports) | File copy + `sha256sum` | Ops |

**Exit criteria:**
- the production database is named;
- its RCA completeness is known;
- a restore-tested backup exists;
- one working copy is canonical.

The rest of this plan assumes the canonical database has the same schema state as `fourg_db`. That schema is **verified identical to the models**, apart from the pending `organization.0004`.

---

## 2. Final Architecture

### 2.1 Ownership

| Responsibility | Owner (final) | Current state |
|---|---|---|
| Site master (identity, attributes, effective dates) | `sitedata.Site` (Consolidation Matrix) | [V] exists; 6,764 sites |
| Site identifiers (BSNL ID, BTS IP ID, 2100/700, Master BTS, alternate) | `sitedata.SiteIdentifier`, `IdentifierConflict` | [V] exists |
| LWE Band ID mapping (history) | `sitedata.LweMappingRow`, `LweMappingIdentifier` | [V] exists; import via command only |
| Daily 4G and LWE availability | `sitedata.DailySitePerformance` (one table, `technology` column) | [V] exists; to 31 Oct |
| Uptime Master values and Uptime-only attributes | `DailySitePerformance` (rank 2) + `Site.uptime_master_fields` (JSON) | [V] exists |
| Raw CNMC CSV values | `DailySitePerformance` (rank 1) | [V] model ready; **no entry point** |
| Authorized corrections | `DailySitePerformance` (rank 3) + `DailyPerformanceEvent` + `UploadBatch(kind=correction)` | [V] `daily.correct()` exists; **no entry point** |
| Conflict/supersede/correction history | `DailyPerformanceEvent` (append-only) | [V] exists |
| Monthly results | `MonthlySitePerformance` | [V] exists; **no recalculation trigger** |
| Import history | `sitedata.UploadBatch` | [V] exists |
| Import exceptions | **New `sitedata.ImportException`** | [V] today: CSV files at absolute paths, e.g. `C:\Users\gaura\…\upload-23-uptime_master-exceptions.csv` (not portable) |
| Pending unmatched records | **New `sitedata.PendingRecord`** | [V] today: in `UploadBatch.report` plus the staged file; unusable when the staged file is missing (batches 23/24) |
| Historical monthly reporting before Sep 2026 | **`MonthlySitePerformance` new category `historical_import`** [BD-3] | [V] only in legacy `uptimedb_sitemonthlyperformance` |
| RCA records | `rca.*` (unchanged ownership) | RCA facts stay in `rca` |
| RCA site and availability lookups | `sitedata` (Site, matrix dates, daily) via one service | [V] today: legacy (`rca/breakdown.py:106`, `overview.py:17-18,154`, `services.py:431`, `sitescope.py:37`, `importer.py:123`, `cycles.py:107`) |
| Arrival tracking | Derived from `UploadBatch` + `DailySitePerformance` + Organization `ProjectCircle` | [V] today: legacy (`uptimedb/arrivals.py`) |
| Application settings (alert worker heartbeat) | **New `common.Setting`** (or a field on `alerts`) | [V] today: `uptimedb.AppSetting` (`alerts/engine.py:282`, `alerts/views.py:154`) |
| Dashboard data-source switch | **Removed** | [V] `uptimedb/datasource.py`, `PUT /api/data-source/` |
| Personnel hierarchy site assignments | `organization.SitePersonnelAssignment.site` → `sitedata.Site` | [V] pending migration points at `uptimedb.UptimeSite` |

### 2.2 New or changed entities (normalised; not legacy copies)

| Entity | Fields (essentials) | Constraints / indexes | Why |
|---|---|---|---|
| `ImportException` | batch (FK UploadBatch, PROTECT), source_row, site_id_raw, identifier, circle_raw, report_date, original_value, reason_code, severity, message, created_at | index (batch, reason_code); index (reason_code, severity) | Exceptions queryable in the DB, portable across machines, reusable by the arrival tracker and UI. CSV export is generated on demand. |
| `PendingRecord` | batch (FK, PROTECT), technology, circle, report_date, identifier_kind, identifier_value, availability_pct / outage_minutes (as read), status (`pending` / `resolved` / `rejected`), resolved_site (FK Site, PROTECT, null), resolved_batch, resolved_by, resolved_at, reason | CHECK on outage 0–1440 / availability 0–100 when not null; index (status, identifier_value); unique (batch, source_row, report_date) | Unmatched rows stay pending **without depending on staged files**. Never creates sites. Resolution writes through the precedence engine. |
| `UploadBatch.Kind` additions | `alternate_mapping` (instead of reusing `correction`, C-49/C-18), `historical_monthly` | choices only | Distinguish mapping and historical imports from corrections |
| `DailySitePerformance` technology integrity | `UNIQUE (id, technology)` on `sitedata_site`, plus a composite FK `(site_id, technology) → sitedata_site(id, technology)` via a reviewed `RunSQL` | DB-enforced | Closes the gap "no DB constraint that daily.technology = site.technology" |
| `DailyPerformanceEvent` immutability | `BEFORE UPDATE OR DELETE` trigger raising an exception (`RunSQL`, reversible) | DB-enforced | The append-only rule is ORM-only today |
| `MonthlySitePerformance.Category` | add `historical_import` [BD-3] | existing partial unique `sitedata_monthly_current` applies | Preserve Oct 2025 – Aug 2026 history with provenance |
| Import lock | `pg_advisory_xact_lock(hash(kind))` plus `select_for_update()` on the batch inside `commit()` | — | Fixes the double-commit race (C-17) |
| `common.Setting` | key unique, value JSON, updated_at, updated_by | — | Replaces `uptimedb.AppSetting` (heartbeat only; the data-source key is dropped) |
| `rca.RcaRecord.site` (optional) [BD-6] | nullable FK → `sitedata.Site` PROTECT, filled at import; `site_key` kept | index | Referential link for RCA site lookups. Optional; the logical key is enough if the business prefers. |

**Deliberately not recreated:**
- `UptimeSite`, the legacy monthly flags table, `EscalationSite` (the matrix is the source; its band IDs are `SiteIdentifier`);
- `DataImportBatch` / `EscalationImportBatch` (replaced by `UploadBatch`);
- the `site_overview` view (replaced by ORM queries on `Site` and RCA).

### 2.3 Code structure (no runtime dependency on `apps.uptimedb`)

| Move | From | To |
|---|---|---|
| File parsers used by `sitedata` | `uptimedb/parser.py`, `daywise.py`, `escalation.py` (helpers `_header/_text/_date/_coordinate`, `COLUMNS`), `raw/parser.py`, `raw/rules.py` | `apps/sitedata/parsers/` (public functions; same behaviour, same tests) |
| `site_key` normaliser (5 copies) | `uptimedb/parser.site_key`, `raw/resolvers`, `rca/parser`, `report_export._site_key`, `sitedata/identifiers.key_of` | `apps/sitedata/identifiers.key_of` (single) |
| `Dataset` type and helpers | `dashboard/workbook.py` (Excel parser module) | `apps/dashboard/dataset.py` (type only); the Excel parsing in `workbook.py` is deleted with the Excel data source |
| `ENTITIES` | `dashboard/activity.py` | `apps/sitedata/rules.py` |
| Shared constants (`MINUTES_PER_DAY`, NSLA threshold, weeks) | 6 / 3 / 3 copies | `apps/sitedata/rules.py` (+ `metrics.py` imports) |

---

## 3. Write Workflows

Required properties for every workflow:
- validation;
- deterministic mapping;
- duplicate prevention (`daily.classify` → duplicate);
- one `transaction.atomic()` with batch lock;
- source precedence (`daily.SOURCE_RANK`);
- audit (`accounts.audit` + `UploadBatch` + `DailyPerformanceEvent`);
- exceptions stored in `ImportException`;
- rollback (the transaction rolls back on any error; a committed batch is reversed only by a new correction batch, never by deletion);
- idempotency (re-commit of the same checksum gives only duplicates);
- truthful status (`previewed` / `committed` / `failed` / `discarded`; the UI only says "imported" when `committed`).

| # | Workflow | Current [V] | Target | Changes |
|---|---|---|---|---|
| W1 | Consolidation Matrix import | `sitedata/matrix.py` via `/api/sitedata/matrix/*` (Admin); per-row writes (`:430-450`); no batch lock; imports private helpers from `uptimedb.escalation` (`:40`) | Same endpoints | Batch lock; bulk writes; parsers moved; **cross-kind identifier conflict check** (master ID vs existing alternate, C-18); exceptions to `ImportException`; after commit `portfolio.clear_cache()` and monthly recalculation for effective-date changes |
| W2 | LWE Band ID mapping | `sitedata/bandmap.py`; command `import_lwe_mapping` only, `user=None` | **New** `/api/sitedata/lwe-mapping/` (preview/commit/discard/issues, Admin) + UI panel on the Data Source page; the command remains for ops but requires `--user` | Attribute the uploader; batch lock; exceptions table |
| W3 | Uptime Master (Up-Time Report / Day-Wise) | `sitedata/uptime_master.py` via `/api/sitedata/uptime/*`; no recalculation; commit race; reads `uptimedb.DataImportBatch` for "legacy_imports" info (`:108`) | Same endpoints | Lock; remove the legacy lookup; after commit `calculate_month()` for affected months + cache clear; **provenance upgrade on higher-rank duplicate** (C-13, `daily.py:90-93`); unmatched rows → `PendingRecord`; circle consistency check (file circle vs site circle) |
| W4 | Raw CNMC 4G CSV | Writes **legacy** via `uptimedb/raw/service.py:286-300` + `/api/raw-uploads/*` (`Can(csv_upload, upload)`, scoped per pair) | **New** `/api/sitedata/raw/` endpoints wrapping `rawcsv.preview(path, name, technology, circle, reporting_date, user)` / `rawcsv.commit(batch, user, request)` (`rawcsv.py:234,248`), with the **same permission and pair scoping** as today; `UploadCsvPage.tsx` repointed | Port the useful UX parts of `raw/service.py` (row-level preview, `rows/` listing, issues CSV) onto the sitedata batch; unmatched → `PendingRecord`; the arrival tracker reads these batches |
| W5 | Raw CNMC LWE CSV | Legacy page validates but imports nothing (`uptimedb/raw/resolvers.py:73-82` `LweResolver`) | Same endpoint as W4 with `technology=LWE`; deterministic 2100/700 resolution in `rawcsv._resolve_lwe` (`:94-139`) | **[BD-1]** confirm `outage = 1440 × (1 − availability/100)` for LWE (verified only for 4G) |
| W6 | Authorized correction | `daily.correct(record, availability_pct, user, reason)` (`daily.py:160`); no caller | **New** `POST /api/sitedata/daily/<id>/correct/` (single) and `/api/sitedata/corrections/` (file upload, preview/commit) | Permission: new catalogue module `data_corrections` (edit) **[BD-2]** (Admin only, or also NOC Lead?); reason mandatory; rank 3; triggers monthly recalculation; blocked for finalized months unless `force` + Admin |
| W7 | RCA Excel uploads | `rca/importer.py` validates sites against `uptimedb.UptimeSite` (`:122-124`); records stay in `rca` | Same endpoints; site validation through `sitedata` (`Site` by `site_key` + technology → circle; alternate identifiers allowed; `outside_scope` sites rejected or flagged [BD-6]) | Optional `RcaRecord.site` FK fill; identical conflict/correction behaviour otherwise |
| W8 | Data Panel editing | `masterdata/datasets.py:22,71-99`, `editors.py` on legacy tables; saves create `DataImportBatch(kind=data_panel)`; clears the legacy cache (`editing.py:154`) | Datasets re-registered on `sitedata`: **Site Master** (read-only, matrix-authoritative [BD-4]), **Daily Performance** (edit = correction via `daily.correct`, rank 3, reason per save), **Monthly Performance** (read-only, derived), **Identifiers & Conflicts** (read-only), **Import Exceptions / Pending Records** (read; resolve via W9), **RCA Data** (unchanged) | Permission keys `data_<dataset>` regenerated from `DATASETS` (`accounts.catalog`); data migration renames or maps existing `RolePermission` rows (`accounts.0007` created them) without broadening access |
| W9 | Site master management and unmatched resolution | `unmatched.map_alternate` / `process_pending` (`unmatched.py:50,149`); no revoke; batch kind `correction` | Matrix import is the only way to create or alter sites. Admin "Pending records" screen: map to an existing site (alternate identifier, reason, kind `alternate_mapping`), reject, **revoke mapping** (new; reverses future matching; already-imported values corrected via W6) | Circle check; length validation (C-45); four-eyes approval optional **[BD-5]** |
| — | Legacy Master workbook import (`/api/imports/*`, `import_uptime`, `import_daywise`, `import_escalation`), Excel upload (`/api/dashboard/workbook/` POST), raw file store (`/api/upload/`) | Write legacy tables or Excel store | **Removed** (Phase 8). Endpoints return 410 Gone during a transition release, then are deleted | UI removed from `DatabaseImportPage.tsx` / `WorkbookPage.tsx` |

**UI status rule (all workflows).** The banner shows *"Committed to the reporting data: N records (M new, K superseded, C conflicts kept, P pending)"* only when the batch status is `committed`. A preview shows *"Validated, not yet imported"*. The false message at `UploadCsvPage.tsx:300` is removed in Phase 2. It may be changed earlier as a hot-fix, with approval.

---

## 4. Read Workflows (every legacy consumer → sitedata)

Search scope: `uptimedb|UptimeSite|SiteDailyPerformance|SiteMonthlyPerformance|EscalationSite|DataImportBatch|EscalationImportBatch|current_dataset|site_overview|AppSetting`. It found 31 non-test application files outside `apps/uptimedb` plus the `uptimedb` app itself (21 modules, 3,281 lines) [V]. In tests, 36 files reference legacy code [V].

| Consumer | Current [V] | Target |
|---|---|---|
| Dashboard 4G/LWE/Overview, Thresholds, Teams, exports, All KPI's, Site Portfolio | Already `sitedata` (`dashboard/views.py:23-34`, `allkpis/services.py:71`) | Keep. Remove the residual legacy calls: `dashboard/views.py:305,312` (`active_source` label) and `report_export.py:184` (`parse_workbook` fallback in `source_details`) |
| Dashboard conversion activity | Excel (`dashboard/activity.py`); endpoint unused by UI | Delete the endpoint; `portfolio.monthly_activity` is the single implementation (C-21) |
| O&M heads | Excel file `Data/reference/*first page*.xlsx` (`dashboard/reference.py`) | **[BD-7]** derive from `sitedata.Site.om_manager_*` per circle, or keep a reference upload in `sitedata`. Not a legacy table, but a runtime Excel dependency |
| Data Source & Quality calculation check | `crosscheck.py`: inert on sitedata | Replace with a sitedata reconciliation view (batch counts, exceptions, coverage) or remove |
| RCA breakdown (Total / USD / NSLA) | `current_dataset()` legacy (`breakdown.py:106-109`); own 21.6-min daily rule | `dashboard_source.dataset(pairs, scope)`. NSLA rule unchanged until **[BD-8]**; the float comparison fixed (section 7) |
| RCA overview | `current_dataset()` + `EscalationSite.bts_id_b1` NE map (`overview.py:17-18,84,154`) | `dashboard_source`; NE map from `SiteIdentifier(kind=band_2100)` |
| RCA summary population | `current_dataset().sites` (`services.py:431-433`) | `dashboard_source.dataset(pairs).sites` |
| RCA Site Scope | `SiteMonthlyPerformance.om_start` (`sitescope.py:37-44`) | Matrix effective dates: `rules.om_effective_from(Site.om_start_date, month)` by (technology, site_key). **[BD-9]** confirm this replaces the Uptime-Master monthly flag (legacy flags are absent for 7 of 13 months and for Nov 2026 [V]) |
| RCA cycles (available units) | `UptimeSite` distinct (project, circle) (`cycles.py:107`) | Organization active `ProjectCircle` ∩ `sitedata.Site` (dashboard scope) |
| RCA import validation | `UptimeSite` (`importer.py:123`) | W7 |
| CSV Arrival Tracker | `uptimedb/arrivals.py` (legacy daily coverage, `UptimeSite.on_air`, `DataImportBatch` raw uploads) | New `apps/sitedata/arrivals.py`: expected sites = On-Air by matrix date; coverage = `DailySitePerformance` per (technology, circle, date); uploads = `UploadBatch(kind in raw_csv_*, uptime_master)` with circle and date. Same API shape (`/api/arrival-tracker/`) |
| CSV reminder automation, `csv_arrival` report | `alerts/engine.py:147-152`, `alerts/reports.py:78-87` → legacy arrivals | `sitedata.arrivals` |
| Emailed uptime reports | `alerts/reports.py:61-77` → `current_dataset()` | `dashboard_source.dataset(recipient pairs)` + the same `report_export` functions as the portal download |
| Alert worker heartbeat | `uptimedb.AppSetting` (`engine.py:282`, `views.py:154`) | `common.Setting` (data migration copies the key) |
| Legacy email reminder validation | `common/views.py:183` → `current_dataset` | `dashboard_source`, or remove the legacy email stack in favour of `alerts` **[BD-10]** |
| Organization usage counts | `organization/services.py:181-202` (legacy tables) | `sitedata.Site`, `DailySitePerformance`, `MonthlySitePerformance`, `UploadBatch` counts per (technology, circle) |
| Organization circle resolvers | `organization/views.py:322` imports `uptimedb.raw.resolvers.RESOLVERS` | Resolver registry moves to `sitedata.parsers` |
| Data Panel | Legacy (W8) | W8 |
| Hierarchy services, serializers, views, reconciliation command | `UptimeSite` (`hierarchy_services.py:26,213`, `hierarchy_serializers.py:17`, `hierarchy_views.py:48`, `hierarchy_reconciliation_dry_run.py`) | `sitedata.Site` (section 6) |
| `site_overview` view | Created by `uptimedb.0002`; used only by `tests/test_escalation.py:153` | Dropped (Phase 8) |
| Frontend | `DatabaseImportPage.tsx:116` (data-source switch), `WorkbookPage.tsx` (Excel upload), `UploadCsvPage.tsx` (legacy raw uploads), `CsvArrivalPage.tsx`, `MasterDataPage.tsx`, `services/api.ts` legacy wrappers (`uploadDataFile`, `fetchConversionActivity`, `/data-source/`, `/raw-uploads/*`, `/imports/*`) | Repoint to new endpoints; remove the switch and Excel upload; types updated in `src/types/*` |

**Consistency rule.** Every figure, in every consumer, comes from `dashboard_source.dataset()` and `dashboard/metrics.py`, or from sitedata queries through one service module. No module may compute uptime, USD or NSLA from another source.

---

## 5. Known Data Discrepancies

### 5.1 November records

**Facts [V]:**
- Legacy holds 43,188 reported site-days: 4G 42,354 (1–10 Nov), LWE 834 (278 sites, 1–3 Nov).
- `sitedata` has no November rows.
- Previews #23/#24 (older file, staged copy missing) cannot be committed here.

**Reconciliation process** (executed in Phase 6, after Phases 1–2 deliver locking, `PendingRecord` and the raw CSV path):
1. **Discard previews #23 and #24** (`POST /api/sitedata/uptime/23/discard/`, `/24/discard/`) with approval. They are previews; discarding writes nothing to daily tables.
2. **Preview the newest 4G November Up-Time file** `48e3e33a20` (from the canonical copy's `Data/processed/imports/20261111-164533-48e3e33a20.xlsx`, or the original) into `sitedata`. Check that:
   - received site-days ≈ legacy 4G November reported rows **minus** the two RJ sites outside the matrix (they become `PendingRecord`s, never sites);
   - zero rejections beyond out-of-range values;
   - NULL cells (3,086 in legacy) are counted as *not reported*, never 0.
3. **[BD-11]** Decide whether the older file `33f2a1b93e` must also be imported (it covers 1–3 Nov; if `48e3` also covers 1–3 Nov with equal values, the result is duplicates). Precedence makes equal-rank re-imports conflicts (first value kept). **Import only the version the business approves as final.**
4. **LWE November:** preview `LWE Uptime Report - Nov'26.xlsx` (`96617c84f6`). It covers only 278 of 2,182 LWE sites.
   - Because `dataset.reporting_month` requires every technology/circle unit (`dataset.py:47`, C-20), **dashboards will stay on October** until LWE November is complete.
   - **[BD-12]** Either obtain complete LWE November data, or approve the change to "expected units = active Organization ProjectCircles with data obligations".
5. **Raw CSVs** of 1 Nov (MP, RJ) through W4 at rank 1. They are duplicates where the Up-Time file already provided the value; otherwise they fill gaps.
6. **Commit after review**, then `calculate_month(2026-11)`.
7. **Verify** with state-audit Q9: for November, `both_layers` = legacy reported rows − pending, `value_differs` = 0 (or explained), `sitedata_only` = 0.
8. **Record** every pending or unmatched site-day in `PendingRecord`, plus the reconciliation result in `docs/migration/november-2026-reconciliation.md`.

### 5.2 October differences

**Facts [V]:**
- 2,493 site-days: LWE OD 2,222, TL 211, AP 43, MH 13; 4G OD 4.
- All are explained by different source files (section 0.4).
- The CSV exists in scratch.

**Plan:**
1. Copy the CSV into `docs/migration/october-2026-layer-differences.csv` with a summary (with approval).
2. **[BD-13]** The business chooses, per circle, between `LWE Uptime Report - Oct'26.xlsx` (currently in `sitedata` and on dashboards) and `4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (legacy, RCA and emails).
3. **If `sitedata` stays:** nothing changes in data; the legacy values simply retire. Record the decision.
4. **If the consolidated file wins** for some circles: apply it as an **authorized correction batch** (W6, rank 3, reason "BD-13 approved source"), restricted to the approved circles and dates. All superseded values remain in `DailyPerformanceEvent`. Then `calculate_month(2026-10, force=True)`.
5. **Never** pick a winner silently, and never delete either value.

### 5.3 Missing RCA data

**Facts [V]:**
- `fourg_db.rca_rcarecord` has 0 rows (sequence 180,512), and `rca_rcaevent` has 0 (sequence 3,478).
- The statistics show 0 inserts and 0 deletes.
- 12 previewed consolidated batches hold staged rows.

**Recovery sources, in order of authority:**

| # | Source | Location | Completeness | Use |
|---|---|---|---|---|
| 1 | **Live production `4G-DB`** (if it is production and intact) | Original developer machine | Most current, including workflow, comments and events | **Preferred.** No recovery needed if production is intact; `fourg_db` is then just an incomplete copy |
| 2 | **4 Nov production dumps** | `C:\Users\gaura\Backups\4G-DB\20261104T122933Z\` and `20261104T124210Z\` (SHA-256 in `docs/production-backup-report-20261104.md`, `docs/production-sitedata-import-20261104.md`); **not on this machine** [V] | 178,692 records as of 4 Nov; misses RCA changes after the dump | `pg_restore -a -t rca_rcarecord -t rca_rcaevent -t rca_rcaworkflow -t rca_rcacomment -t rca_rcaimportbatch -t rca_rcareportingcycle -t rca_rcarequiredsubmission -t rca_rcareport …` **into a scratch database first**, verify counts and checksums, then plan a reviewed merge |
| 3 | Original RCA workbooks | Second copy `Data/processed/rca_uploads/` (batches 5–33, 26 Oct – 2 Nov) [V] | Imported facts only; manual records, workflow, comments and events are lost | Re-import through the RCA importer as a last resort |
| 4 | Staged rows of previewed batches 22–33 | `rca_rcaimportbatch.rows` JSON [V] (e.g. #22: 146,529 rows, Oct; #24/#26: about 5,600 rows, 1–2 Nov) | Unvalidated previews; versions differ (146k vs 95k vs 69k rows) | Evidence only; not a recovery source |

**Rule:** do not restore into the canonical database before G1/G2 are answered. Never run `pg_restore --clean` against a live database.

### 5.4 Site mapping

- Unmatched records from any source become `PendingRecord` rows (W3, W4, W5).
- No site is ever created from performance data; only W1 creates sites.
- Known cases [V]: UVRJJPR00057 and UVRJUPR00612 (in legacy and in the November file; not in the matrix). 40 matrix `outside_scope` sites are excluded by design.

---

## 6. `organization.0004` Redesign

**Facts [V]:**
- Not applied in `fourg_db`; its 10 tables are absent, so there is no hierarchy data.
- Dependencies: `organization.0003`, `auth.0001`, `uptimedb.0005`.
- `SitePersonnelAssignment.site` → `uptimedb.UptimeSite` `on_delete=CASCADE` (`organization/models.py:648-653`; migration `:240`).
- Every other FK is PROTECT or SET_NULL to `organization`/`auth`/self.
- PostgreSQL FKs are created `NO ACTION DEFERRABLE`; CASCADE is ORM-level.

**Design:**

| Aspect | Decision |
|---|---|
| Target | `site = models.ForeignKey('sitedata.Site', on_delete=models.PROTECT, related_name='personnel_assignments', db_index=True)` |
| Deletion behaviour | PROTECT. Sites are never deleted (a site missing from a newer matrix is flagged `present_in_latest_matrix=False`); assignments must be ended (`effective_to`), not cascaded |
| Technology | Assignment is per site; `Site.technology` already distinguishes 4G and LWE. Hierarchy queries filter `site__reporting_scope='dashboard'` |
| Migration approach | **Only if G3 confirms 0004 is unapplied in every database:** edit `0004` in place. Change the dependency `('uptimedb', '0005_data_panel_batch_kind')` → `('sitedata', '0001_initial')` and the field target. Otherwise add `0005_site_assignment_to_sitedata` (AlterField with a data step mapping `UptimeSite.id` → `sitedata.Site.id` by `site_key` + project/technology; unmapped rows reported and the migration aborted) |
| Ordering | After `sitedata.0001`/`0002`; before any `uptimedb` table drop. Applied with a **targeted** command (`migrate organization 0004`), never an unqualified `migrate` until Phase 8 |
| Reverse | `migrate organization 0003` drops the 10 tables. Safe only while they are empty; afterwards, reversal requires a backup of the hierarchy tables (documented in the rollback plan) |
| Code changes | `organization/models.py:648-653`; `hierarchy_services.py:26,207-213` (`select_for_update` on `sitedata.Site`); `hierarchy_serializers.py:17`; `hierarchy_views.py:48`; `management/commands/hierarchy_reconciliation_dry_run.py` (read matrix CI/IE names from `sitedata.Site`); `admin.py`; frontend `HierarchyTabs.tsx` types (site IDs change meaning) |
| Data | None exists [V]. Seed data (OAs, personnel) comes from `sitedata.Site` CI/IE/O&M fields via the dry-run command, after review |
| Tests | `tests/test_team_hierarchy.py` re-based on `sitedata` fixtures; PROTECT behaviour test (cannot delete a site with assignments); migration test (forward/backward on an empty DB; `sqlmigrate` review) |
| UI gating | Until the redesigned 0004 is applied, hide the hierarchy tabs and the mock `/teams/hierarchy` pages (C-8, C-9) |

---

## 7. Data Integrity and Validation

| Rule | Enforcement (target) | Status / action |
|---|---|---|
| Matrix authoritative | Only W1 writes `Site` attributes and dates; the Data Panel Site Master is read-only [BD-4] | Code |
| Precedence 3 > 2 > 1, order-independent | `daily.classify` with a provenance upgrade on higher-rank duplicates (C-13) | **Fix** in Phase 2; property-based test over all upload orders |
| Daily key (site, date, technology) | `sitedata_daily_unique` [V] + composite technology FK (section 2.2) | Add the composite FK |
| 4G / LWE separate | `Site.technology` + composite FK | Add |
| Missing ≠ 0 | No record for blanks; `PendingRecord` stores values as read (nullable) | Existing [V] + tests |
| Outage 0–1440 | `sitedata_daily_outage_range` [V]; `PendingRecord` CHECK | Existing + add |
| Availability in percentage points | `sitedata_daily_availability_range` [V] | Existing |
| LWE 2100/700 deterministic, no fuzzy matching | `rawcsv._resolve_lwe`, `IdentifierConflict` | Existing [V] + tests through the new endpoint |
| Weeks 1–7/8–14/15–21/22–end | Single `rules.WEEKS` | Consolidate (3 copies today) |
| Weekly values need all reporting days | `metrics.week_columns` on dashboard/thresholds [V]; **not applied** in Portfolio weekly, All KPI's week granularity, Consolidated export | **[BD-14]** apply everywhere, or label partial weeks. Not changed silently |
| Exact 98.5% boundary | Compare **availability**, not derived minutes, with a tolerance: `availability_pct < 98.5 - 1e-9`, or `round(x, 6)`. Same helper used by metrics, All KPI's and RCA breakdown | **Fix** (C-16, `rca/breakdown.py:162`; `1440*(1-0.985) = 21.60000000000002` [V]); boundary tests at 98.5, 98.4999999, 98.5000001 |
| USD / NSLA definitions | Three definitions exist (C-15) | **[BD-8]** unify or rename; not changed silently |
| Finalized months | Writes into a finalized month raise unless `force` + Admin + reason | Add (C-19) |
| Monthly recalculation | After each committed batch / correction / pending resolution: `calculate_month(m)` for affected months | Add |
| Transactions | Batch lock + `atomic` + re-validation inside the lock | Add (C-17) |
| Event immutability | DB trigger | Add |

---

## 8. Database Security Design (no roles created; approval required)

| Role | Purpose | Privileges | Used by |
|---|---|---|---|
| `bsnl_owner` (NOLOGIN) | Owns schema and objects | Owner of `public` objects | — |
| `bsnl_migrator` (LOGIN) | Deploy and migrations | Member of `bsnl_owner`; DDL | CI/CD or the operator running `migrate` (separate env file) |
| `bsnl_portal_app` (LOGIN) | Application runtime | `CONNECT`; `USAGE` on schema; `SELECT, INSERT, UPDATE` on app tables; `DELETE` only where the app deletes (sessions, previews, `rca_rcacausemapping`); `USAGE, SELECT` on sequences; **no DDL, no TRUNCATE, not superuser, no CREATEROLE** | Django |
| `bsnl_audit_ro` (LOGIN) | Audits and reporting | `SELECT` on all tables; `default_transaction_read_only = on` | Auditors |

- `ALTER DEFAULT PRIVILEGES FOR ROLE bsnl_owner …` so new tables get grants automatically.
- Revoke `CREATE` on `public` from `PUBLIC`.
- Passwords live in a secret store. The app `.env` holds only the app role; migrations use a separate env file.
- Rollout:
  1. create the roles;
  2. reassign ownership (`REASSIGN OWNED BY postgres` is **not** used; per-object `ALTER … OWNER TO bsnl_owner` in a reviewed script);
  3. switch `.env`;
  4. smoke test;
  5. keep `postgres` for DBA use only.

---

## 9. Execution Plan

Each phase is a separate pull request (or small series) with review, tests, and, where data changes, a restore-tested backup taken immediately before.

### Phase 1: Schema and migration design

| Item | Detail |
|---|---|
| Files | `apps/sitedata/models.py` (ImportException, PendingRecord, Kind/Category additions); `apps/sitedata/migrations/0003_*.py` (new tables), `0004_*.py` (composite technology FK + event trigger via reversible `RunSQL`); `apps/common/models.py` + `apps/common/migrations/0001_setting.py`; `apps/organization/models.py` + `migrations/0004_*` redesign (section 6); `apps/sitedata/parsers/` (moved code, no behaviour change); `apps/dashboard/dataset.py` (moved `Dataset`) |
| Tables | New: `sitedata_importexception`, `sitedata_pendingrecord`, `common_setting`; altered: constraints on `sitedata_site`/`_dailysiteperformance`; org hierarchy tables (created later, targeted) |
| API | None yet |
| Tests | Model/constraint tests on **PostgreSQL** (new CI job, section 9 Phase 7); migration forward/backward tests; parser move regression (existing parser tests pointed at new paths) |
| Data migration | `common.Setting` copy of `alerts_worker_heartbeat` (data step, reversible) |
| Risks | Composite FK fails if existing rows violate it. Pre-check: verified 0 technology mismatches between layers, but run `SELECT count(*) FROM sitedata_dailysiteperformance d JOIN sitedata_site s ON s.id=d.site_id WHERE d.technology<>s.technology` first |
| Rollback | All migrations reversible (`migrate sitedata 0002`, `migrate common zero`); restore-tested backup |
| Acceptance | `makemigrations --check` clean; `sqlmigrate` output reviewed; tests pass on SQLite **and** PostgreSQL; no behaviour change visible to users |

### Phase 2: Upload and ingestion migration (W1–W5, W9)

| Item | Detail |
|---|---|
| Files | `sitedata/daily.py` (provenance upgrade, finalized guard), `uploads.py` (lock helper, exceptions to table), `matrix.py`, `uptime_master.py`, `rawcsv.py`, `bandmap.py`, `unmatched.py` (PendingRecord, revoke, circle check), new `sitedata/raw_views.py` + `raw_urls.py`, `lwe_mapping_views.py`; `config/urls.py`; frontend `UploadCsvPage.tsx`, `DatabaseImportPage.tsx`, `components/data/*`, `services/api.ts`, `types/*` |
| Tables | Writes `sitedata_*` only |
| API | **New:** `/api/sitedata/raw/` (list, preview, `<id>/`, `<id>/rows/`, `<id>/issues.csv`, `<id>/commit/`, `<id>/discard/`; permission `Can(csv_upload, upload)` + pair scope), `/api/sitedata/lwe-mapping/*` (Admin), `/api/sitedata/pending/` (list/resolve/reject/revoke; Admin). **Changed:** `/api/sitedata/uptime/unmatched/*` folded into `pending`. **Deprecated:** `/api/raw-uploads/*` (410 after cut-over) |
| Tests | Port `test_raw_upload.py` scenarios to sitedata (4G and LWE); precedence order-independence; double-commit concurrency test on PostgreSQL (two connections); idempotent re-commit; pending lifecycle; UI tests for truthful status |
| Data migration | None (historical legacy raw uploads are covered by Phase 6) |
| Risks | CI users lose the legacy page during the switch. Mitigation: release both, with the legacy one read-only, for one cycle. LWE formula [BD-1] |
| Rollback | Feature flag `SITEDATA_RAW_UPLOAD` to show the old page; new batches remain valid in `sitedata` |
| Acceptance | A raw 4G and LWE CSV committed via the UI appears on the dashboard (after cache clear) for the expected sites; unmatched rows visible as pending; no write to `uptimedb_*` from any upload path (asserted by a test that counts legacy rows before/after) |

### Phase 3: Data correction and master-data migration (W6, W8)

| Item | Detail |
|---|---|
| Files | `sitedata/daily.py` (correction API), new `sitedata/correction_views.py`; `masterdata/datasets.py`, `editors.py`, `editing.py`, `views.py`; `accounts/catalog.py` (+ `data_corrections`); `accounts/migrations/0008_*` (map old `data_*` permission rows to new dataset keys, no broadening); frontend `MasterDataPage.tsx`, `components/masterdata/*` |
| Tables | `sitedata_dailysiteperformance`, `_dailyperformanceevent`, `_uploadbatch`, `_monthlysiteperformance`; `accounts_rolepermission` (data step) |
| API | `POST /api/sitedata/daily/<id>/correct/`; `/api/sitedata/corrections/` (file); `/api/master-data/<key>/…` unchanged in shape, keys and sources changed |
| Tests | Correction rank 3 beats everything and is never overridden; reason required; finalized guard; Data Panel save creates a correction batch and events; permission matrix tests for every dataset × role |
| Data migration | Permission mapping; no business data |
| Risks | Users lose Site Master editing [BD-4]; the RCA Data dataset is unchanged |
| Rollback | Revert the PR; the permission migration is reversible |
| Acceptance | Data Panel shows the same values as the dashboard for any site/date; an edit changes the dashboard after save; no Data Panel code imports `uptimedb` |

### Phase 4: Dashboard and reporting consumers

| Item | Detail |
|---|---|
| Files | `dashboard/views.py` (remove `active_source` use, `conversion_activity_view`), `report_export.py` (drop the `parse_workbook` fallback), `crosscheck.py` (replace/remove), `activity.py`, `reference.py` [BD-7]; new `sitedata/arrivals.py`; `uptimedb/views.py arrival_tracker` → `sitedata`; `alerts/reports.py`, `alerts/engine.py`, `alerts/views.py`; `common/views.py:183`; `organization/services.py:181-202`, `organization/views.py:322`; `allkpis/services.py:34` (`site_key` import); frontend `CsvArrivalPage.tsx`, `DataSourcePage.tsx` |
| Tables | Reads `sitedata_*`, `common_setting` |
| API | `/api/arrival-tracker/` same shape, new source; `/api/data-source/` GET returns sitedata status only, PUT removed; `/api/dashboard/conversion-activity/` removed |
| Tests | Emailed report equals portal download for the same pairs and date (byte-level on the data cells); arrival tracker scenarios on sitedata fixtures; org usage counts; **remove the runner substitution** (`tests/runner.py:33-49`) and convert workbook-factory tests to sitedata fixtures (C-23) |
| Data migration | None |
| Risks | Test-suite rework is large (36 files reference legacy) |
| Rollback | Revert the PR (read-only consumers) |
| Acceptance | `grep` finds no `uptimedb`/`current_dataset` import outside `apps/uptimedb` and its tests, except RCA (Phase 5) and hierarchy (Phase 5) |

### Phase 5: RCA and organization dependencies

| Item | Detail |
|---|---|
| Files | `rca/breakdown.py`, `overview.py`, `services.py`, `sitescope.py`, `cycles.py`, `importer.py`, `parser.py` (site_key helper); optional `rca/models.py` + migration (`RcaRecord.site` FK) [BD-6]; organization hierarchy files (section 6); frontend RCA pages unaffected except labels |
| Tables | Reads `sitedata_*`; optional new FK column on `rca_rcarecord` |
| API | Same endpoints; figures change where the legacy data differed (document per BD-8, BD-9, BD-13) |
| Tests | Site Scope by matrix dates (including months without legacy flags); breakdown USD/NSLA equal dashboard where the definitions are equal; float boundary; import validation (matrix-only site accepted; outside-scope behaviour [BD-6]; unknown → rejected); hierarchy on sitedata |
| Data migration | Optional backfill of `RcaRecord.site` by (technology, site_key), with unmatched listed, not forced |
| Risks | RCA numbers visibly change. Needs business sign-off and release notes |
| Rollback | Revert the PR; the optional FK migration is reversible |
| Acceptance | No RCA or organization module imports `uptimedb`; the RCA Site Scope returns non-empty O&M groups for Nov 2026 |

### Phase 6: Historical reconciliation and data recovery

| Item | Detail |
|---|---|
| Steps | (a) RCA recovery per section 5.3 (only after G1/G2). (b) November per section 5.1. (c) October per section 5.2 decision. (d) Historical monthly Oct 2025 – Aug 2026 [BD-3]: management command `import_historical_monthly` reading legacy `uptimedb_sitemonthlyperformance` **once**, mapping by (project→technology, site_key) to `sitedata.Site`. It writes `MonthlySitePerformance(calculation_category='historical_import', source_batches=[UploadBatch(kind=historical_monthly)])`, carries outage minutes and the reported day basis, keeps legacy `om_start` flags in the batch report for audit, and lists unmapped sites (2 RJ) as exceptions. `dataset.py` includes this category for months before the first daily month. (e) Legacy raw uploads (batches 25/26 etc.): re-run through W4 only if their dates are not covered by Up-Time files |
| Tables | `sitedata_*`, `rca_*` (recovery only) |
| Tests | Command dry-run/commit tests; counts reconcile (state-audit Q9–Q11 rerun); dashboard monthly history shows the restored months |
| Risks | Wrong winner; duplicates; restoring the wrong RCA source. Mitigation: dry-run reports, business sign-off per step, backups |
| Rollback | Each step is its own batch. Historical monthly rows can be retired by a reviewed migration marking them `is_current=False`; RCA recovery happens only after a scratch-database verification |
| Acceptance | Reconciliation report signed. Every legacy site-day either exists in `sitedata` (same value or recorded decision), or is in `PendingRecord`/exceptions with a reason |

### Phase 7: Regression and PostgreSQL validation

| Item | Detail |
|---|---|
| Work | CI job with PostgreSQL 18 service (test DB only); run the full backend suite on SQLite and PostgreSQL; frontend `tsc`, lint, vitest, build; contract tests (MSW or schema snapshots) for changed endpoints; a "no-legacy" test that runs the suite with `apps.uptimedb` tables absent (database router or migration to the pre-retirement state + drop in the test DB only) |
| Business-rule tests | Every row of section 7 has at least one named test |
| Performance | Measure dashboard and RCA summary latency on a production-sized copy (C-31, C-32) |
| Acceptance | All green on both databases; latency recorded; restore rehearsal from a fresh dump succeeds and reconciles counts |

### Phase 8: Legacy table retirement

Pre-conditions:
- Phases 1–7 accepted;
- grep shows **zero** runtime imports of `apps.uptimedb` models or services;
- a fresh restore-tested backup;
- business sign-off of Phase 6.

Ordered steps (each a reviewed migration; **no `DROP … CASCADE`**):
1. **Freeze writes:** remove legacy endpoints (`/api/imports/*`, `/api/raw-uploads/*`, `/api/upload/`, `/api/raw-files/`, `/api/data-source/` PUT, `/api/dashboard/workbook/` POST) and the commands `import_uptime`, `import_daywise`, `import_escalation`.
2. **`uptimedb.0006_drop_site_overview`:** `RunSQL('DROP VIEW site_overview', reverse_sql=<definition from rca.0004>)`.
3. **`uptimedb.0007_remove_models`:** explicit `DeleteModel` in dependency order:
   1. `SiteDailyPerformance`;
   2. `SiteMonthlyPerformance`;
   3. `EscalationSite`;
   4. `UptimeSite`;
   5. `DataImportBatch`;
   6. `EscalationImportBatch`;
   7. `AppSetting` (after Phase 1 copied the heartbeat).

   Django drops each FK constraint with its table, children first, so no CASCADE is needed. The reverse recreates empty tables (data comes back only from backup; documented).
4. **Keep `apps.uptimedb` as a migrations-only app:**
   - `models.py` empty; no urls, views or services;
   - parsers already moved in Phase 1.
   - Needed because `organization.0002`, `rca.0002` and the old `organization.0004` dependency reference its migrations [V].
   - The data step in `organization.0002` (`apps.get_model('uptimedb','UptimeSite')`) only runs on fresh databases, before `0007`.
   - A later, separately approved **migration squash** may remove the stub entirely.
5. **Stale metadata:** run `remove_stale_contenttypes` (deletes content types and permissions of removed models) with approval. Check that no `auth_permission` rows are referenced by groups first.
6. **Settings and docs:** remove `MASTER_WORKBOOK_PATH`, `WORKBOOK_STORE_DIR`, `RAW_UPLOAD_DIR` if unused; remove `dashboard/upload.py`, `store.py` and the Excel parsing in `workbook.py`; update docs.

| Item | Detail |
|---|---|
| Tests | The full suite on a database migrated to `uptimedb.0007`; the application smoke test (all pages, uploads, exports, emails in test mode) |
| Risks | Irreversible data loss if the backup is bad. Mitigation: G5-style restore test immediately before; keep the dump for an agreed retention period |
| Rollback | Restore from the pre-retirement dump into a new database and repoint the app (documented runbook); migration reverse only recreates empty tables |
| Acceptance | No `uptimedb_*` tables, views or FKs (`pg_class`/`pg_constraint` queries return 0); the app passes the smoke test |

### Phase 9: Final architecture and documentation

| Item | Detail |
|---|---|
| Docs | Rewrite `README.md` (UTF-8), `docs/architecture.md`; new `DATABASE_ARCHITECTURE.md` (section 2 as built), `MIGRATION_TRACKER.md` (section 12 with dates); update `PROJECT_HANDOVER.md`, `backend/apps/sitedata/README.md`, `docs/business-rules.md` (decided BDs), `docs/rca.md`, `docs/security.md` (roles), `docs/csv-arrival-tracking.md`, `docs/data-entry.md`, `docs/database-import.md` (replace with sitedata import guide); runbooks: deployment, backup/restore (rehearsed), import operations, correction operations |
| Code cleanup | Remove dead code identified in the audit that became dead after migration (legacy wrappers in `api.ts`, `hierarchyMockData.ts` per product decision, `crosscheck.py`, duplicate helpers) |
| Acceptance | Docs reviewed; handover matches code; a fresh setup from the README works on a clean machine |

---

## 10. Business Decisions Required

| ID | Decision | Default if undecided |
|---|---|---|
| BD-1 | LWE raw CSV outage formula `1440 × (1 − availability/100)` | LWE raw CSV import stays disabled |
| BD-2 | Who may apply authorized corrections (Admin only? NOC Lead?) and whether a second approver is needed | Admin only, reason mandatory |
| BD-3 | Preserve legacy monthly history Oct 2025 – Aug 2026 in `sitedata` (`historical_import`) | Preserve (retirement blocked until decided) |
| BD-4 | Site Master editing in the Data Panel: read-only (matrix authoritative) or matrix-override edits | Read-only |
| BD-5 | Four-eyes approval for alternate-identifier mappings | Single Admin with reason (current) |
| BD-6 | RCA: add `RcaRecord.site` FK; treatment of RCA rows for `outside_scope` sites | No FK; flag outside-scope rows |
| BD-7 | O&M heads source (matrix vs reference upload) | Keep the Excel reference until decided |
| BD-8 | USD/NSLA definitions (dashboard vs All KPI's vs RCA breakdown) | Keep the three, labelled distinctly |
| BD-9 | RCA Site Scope uses matrix O&M dates instead of Uptime-Master monthly flags | Matrix dates (legacy flags missing for most months) |
| BD-10 | Retire the legacy email stack (`common/email.py`) in favour of `alerts` | Keep until Phase 9 |
| BD-11 | Which November 4G file version is final (`48e3e33a20` vs `33f2a1b93e`) | `48e3e33a20` (newest), pending confirmation |
| BD-12 | Reporting-month rule when one technology/circle lacks data | Keep the current rule (dashboards stay on October until LWE November is complete) |
| BD-13 | October LWE source per circle (`LWE Uptime Report - Oct'26` vs `4G_LWE_Consolidated_Oct'26-Last_Changes`) | Keep `sitedata` values (current dashboards) |
| BD-14 | Partial weeks: hide everywhere, or show labelled | Unchanged until decided |

---

## 11. Rollback Strategy (overall)

- **Before each data-changing phase (2, 3, 6, 8):** take a fresh `pg_dump -Fc` with SHA-256, restore-tested into `<db>_restore_check`, and run state-audit Q4/Q9 counts against it.
- **Code-only phases (1 without data, 4, 5, 7, 9):** revert the pull request.
- **Data written through `sitedata` is never deleted to undo.** Undo is a correction batch (rank 3), recorded in events.
- **Phase 8 rollback** = restore the pre-retirement dump into a new database and repoint the application. Migration reversal recreates empty tables only.
- **Never** run `pg_restore --clean` against the live database without a verified dump of that database from minutes earlier.

---

## 12. Migration Tracker (initial state)

| Module | Reads | Writes | Target phase | Status |
|---|---|---|---|---|
| Dashboard / Thresholds / Teams / All KPI's / Portfolio / portal exports | sitedata | — | 4 (residuals) | Mostly done [V] |
| Matrix import | sitedata | sitedata | 2 (hardening) | Done, needs lock |
| Up-Time import | sitedata | sitedata | 2 | Done, needs lock and recalculation |
| LWE mapping | sitedata | sitedata | 2 | Command only |
| Raw 4G CSV | legacy | **legacy** | 2 | **Not migrated** |
| Raw LWE CSV | — | — | 2 | **Not available** |
| Corrections | — | — | 3 | **Not available** |
| Data Panel | legacy | **legacy** | 3 | **Not migrated** |
| Arrival tracker + reminders | legacy | — | 4 | Not migrated |
| Email reports | legacy/Excel | — | 4 | Not migrated |
| Heartbeat setting | legacy `AppSetting` | legacy | 1/4 | Not migrated |
| Org usage counts, circle resolvers | legacy | — | 4 | Not migrated |
| RCA breakdown / overview / summary / scope / cycles / import validation | legacy | (rca) | 5 | Not migrated |
| Hierarchy (0004) | legacy (pending) | — | 1/5 | Redesign pending |
| November data | legacy only | — | 6 | Pending BD-11, BD-12 |
| October LWE | both (differ) | — | 6 | Pending BD-13 |
| Historical monthly | legacy only | — | 6 | Pending BD-3 |
| RCA records | **missing in fourg_db** | — | 0/6 | Pending G1/G2 |
| Legacy tables, view | — | — | 8 | Blocked by all of the above |

---

## 13. Final Acceptance Criteria (mapping)

| # | Criterion | Evidence required |
|---|---|---|
| 1 | All writes use `sitedata` | Test asserting no `uptimedb_*` row changes across every upload/edit endpoint; grep |
| 2 | All reads use `sitedata` | Grep: no `apps.uptimedb` imports outside the migrations stub; suite passes with legacy tables absent |
| 3 | No active code depends on `uptimedb_*` | Same as 2 |
| 4 | No views or FKs depend on legacy tables | `SELECT … FROM pg_depend/pg_constraint` returns 0 |
| 5 | Historical records reconciled and preserved | Signed Phase 6 reports (Nov, Oct, monthly history, RCA) |
| 6 | Consistent figures across dashboard, RCA, exports, emails | Cross-surface regression tests on shared fixtures; manual sample sign-off |
| 7 | Business rules have regression tests | Section 7 matrix fully covered |
| 8 | PostgreSQL integration tests pass | CI job green |
| 9 | Backup and restore rehearsed | Restore report with checksums and row counts |
| 10 | Legacy tables retired | Phase 8 acceptance |
| 11 | App runs without legacy tables | Smoke test on the retired schema |

---

## 14. Verified Facts vs Assumptions (this plan)

| Statement | Status |
|---|---|
| Two working copies target `fourg_db`; batches 41–43 came from the second copy | Verified (`stored_path`, `.env` DB names) |
| November previews #23/#24 = file `33f2a1b93e`, staged copies missing here; newer file `48e3e33a20` committed to legacy as #43 | Verified |
| November source files and RCA workbooks exist in the second copy's `Data/` | Verified (file listing; not opened) |
| October differences are entirely a source-file difference | Verified (record-level query; CSV in scratch) |
| Dashboard monthly history limited to Sep–Oct 2026 | Verified (`sitedata/dataset.py` + data) |
| `uptimedb` migrations are depended on by `organization.0002`, `rca.0002`, `organization.0004` | Verified |
| No database dumps exist on this machine | Verified (filesystem search of the user profile, excluding AppData) |
| Production is `4G-DB` on the original developer machine and holds RCA data | Assumption (docs); gate G1/G2 |
| `organization.0004` unapplied everywhere | Assumption beyond `fourg_db`; gate G3 |
| The composite technology FK can be added without violations | Assumption (0 cross-layer mismatches verified; the in-table check runs in Phase 1) |

**Awaiting approval.** No implementation will begin until this plan, the Phase 0 gate and the business decisions in section 10 are approved.
