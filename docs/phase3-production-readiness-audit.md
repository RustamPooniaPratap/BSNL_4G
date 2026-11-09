# Production-readiness audit: new site and performance data layer (`apps.sitedata`)

Date: 4 Nov 2026.

Method: code and migration review, plus checks on the throwaway replay databases.

**Not connected to the live PostgreSQL database; nothing applied, reset or changed there.**

Verdict: **the data layer itself is ready to be created in production** (one additive migration, isolated tables, three
defects found and fixed). **The cutover is not ready**: no dashboard page, upload screen or protected module reads the
new tables yet, and several protected modules (RCA, Team Performance hierarchy, Data Panel, All KPI's) read the old
tables directly. The old tables must therefore **not** be cleared until those modules are moved, which needs your
approval because they are protected.

## 1. Models, tables, constraints and keys

`sitedata.0001_initial` creates 9 tables, all empty at creation:

| Table | Purpose | Constraints | Indexes |
|---|---|---|---|
| `sitedata_uploadbatch` | Upload history of every file kind | – | (kind, circle, reporting_date); checksum |
| `sitedata_site` | Site master, one row per BSNL Site ID | `site_key` UNIQUE; CHECK dashboard ⇔ technology set | (reporting_scope, technology, circle) |
| `sitedata_siteidentifier` | Active identifiers (BSNL ID, BTS IP ID, 2100, 700, Master BTS ID) | UNIQUE (kind, key) | (site, kind) |
| `sitedata_identifierconflict` | Ambiguous identifiers (blocked) | UNIQUE (kind, key) | – |
| `sitedata_lwemappingrow` | Every row of every LWE mapping import | UNIQUE (batch, source_row) | master_key; (batch, status) |
| `sitedata_lwemappingidentifier` | Normalised IDs of mapping rows (history; repeats allowed) | UNIQUE (row, kind, key) | (kind, key) |
| `sitedata_dailysiteperformance` | **The only daily table** (4G + LWE) | UNIQUE (site, report_date, technology); CHECK 0 ≤ availability ≤ 100; CHECK 0 ≤ outage ≤ 1,440 | (report_date, technology, circle) |
| `sitedata_dailyperformanceevent` | Append-only conflict / supersede / correction log | – | (site, report_date); (action, created_at) |
| `sitedata_monthlysiteperformance` | Monthly results by category (all days, On-Air, O&M), with revisions | UNIQUE (site, month, category, revision); partial UNIQUE (site, month, category) WHERE is_current; CHECK reporting_days ≤ calendar_days | (month, technology, is_current) |

Foreign keys:
- **Within `sitedata`:** all `ON DELETE PROTECT`, so no history row can be deleted through a cascade.
- **To `auth_user`:**
  - `UploadBatch.uploaded_by`: SET NULL.
  - `DailyPerformanceEvent.user` and `MonthlySitePerformance.finalized_by`: PROTECT. The portal never deletes users (it
    deactivates them) and Django admin is not installed, so this keeps the audit trail without blocking any feature.
- **No foreign key** to `uptimedb`, `organization`, `rca`, `accounts`, `alerts` or any other app.

## 2. Migration dependencies

| Migration | Depends on | Creates / changes | Status (last read-only check, 4 Nov) |
|---|---|---|---|
| `sitedata.0001_initial` | `auth` (swappable user model) only | 9 new `sitedata_*` tables, 8 indexes, 7 constraints; no change to any existing table | Not applied on live; applied only in throwaway SQLite databases and the test database |
| `organization.0004_team_performance_hierarchy` (Antigravity) | `uptimedb.0005` | Team Performance hierarchy tables; `SitePersonnelAssignment.site` FK to **`uptimedb.UptimeSite`, ON DELETE CASCADE** | Not applied; **not needed by `sitedata`** |

```
auth ──► sitedata.0001_initial            (independent of organization.0004)
uptimedb.0005 ──► organization.0004        (separate; FK + CASCADE to the OLD site table)
```

`organization.0004` must be reviewed separately before it is applied. Once applied, clearing `uptimedb_uptimesite`
would cascade-delete its site assignments, and its FK points to the old site table, not to `sitedata_site`.

**Code dependencies** (not migration dependencies): `sitedata` reuses `uptimedb` parsers and `organization` circle
aliases, and it only reads them. The `uptimedb` app therefore stays installed; its tables can be emptied later but not
dropped.

## 3. PostgreSQL compatibility

| Item | Finding |
|---|---|
| Types | BigAutoField, varchar, double precision (Float), date, timestamptz, jsonb, boolean: all standard |
| CHECK constraints (Q expressions, F comparison) and the partial unique index | Supported natively |
| `bulk_create(ignore_conflicts=True)` (mapping identifiers) | ON CONFLICT DO NOTHING; the rows whose IDs are needed are inserted without it, so their IDs are returned |
| Column lengths | Every value of the full replay measured against its column: none over the limit (SQLite does not enforce limits; PostgreSQL does) |
| **Defect 1 (fixed)** | `Site.circle` holds 20 characters but the matrix preview checked 40, so an unknown circle name of 21–40 characters would pass the preview and fail the commit on PostgreSQL. The preview now checks every value against the site-master columns |
| **Defect 2 (fixed)** | The mapping history truncated over-long cells silently. Such a row is now rejected (`value_too_long`) and stored up to the column limit |
| **Defect 3 (fixed)** | A superseded daily record kept its old `updated_at` (`bulk_update` skips `auto_now`); now set explicitly |
| Transaction size | The largest commit (one Uptime Master) writes about 140,000 rows in one transaction: normal for PostgreSQL |

## 4. Transactions, rollback, duplicates, concurrency

| Item | Behaviour | Risk |
|---|---|---|
| Commit | Each commit re-reads the staged file (checksum), re-analyses, refuses if the counts changed since the preview, then writes in one `transaction.atomic()` | Any error rolls the whole upload back; nothing partial |
| Preview | Writes only its `UploadBatch` row, the staged copy and the exception CSV | – |
| Same batch committed twice | Refused (`require_previewed`) | – |
| Same file uploaded again | New batch; commit is idempotent (all values are duplicates; no change) | No warning that the checksum was already committed (recommended) |
| Concurrent commits | Analysis runs before the transaction and **no lock serialises imports**. Two overlapping commits cannot create duplicates (unique constraints): the second fails and rolls back | **Open:** add an import lock (e.g. a PostgreSQL advisory lock per import) before an upload screen allows parallel uploads. Until then imports run one at a time (management commands) |
| Staged files | Copied before the batch row; a failed preview can leave an orphan copy | Harmless; housekeeping only |
| Append-only log | Enforced by the ORM (update / delete raise) | Raw SQL could still change it. Optional: DB-level REVOKE or trigger |
| Corrections | Row lock (`select_for_update`) inside the transaction | – |

## 5. History retention

| Item | Retained? |
|---|---|
| Upload history (`UploadBatch`) | Never deleted by code; PROTECT from every dependent row |
| Mapping versions | Every workbook row of every import (`LweMappingRow`, `LweMappingIdentifier`); replaced identifiers leave the active table, never the history |
| Source precedence | Every conflict, supersede and correction (`DailyPerformanceEvent`) with both uploads and files; append-only |
| Monthly revisions | Earlier revisions kept (`is_current = False`) |
| Source files | Staged copies with SHA-256 under `<DATA_DIR>/processed/sitedata/`, exception reports under `.../exceptions/`. These are **files on disk**: include them in the backup |

## 6. Tables in a future controlled reset

**Created** by the migration: the 9 `sitedata_*` tables above (empty; nothing to clear).

**Modified:** none.

**To be cleared later, only after approval and only after every consumer is moved** (the six approved groups; row
counts as of the last read-only check, 4 Nov):

| Order | Table | Rows | Still read by |
|---|---|---|---|
| 1 | `uptimedb_sitedailyperformance` | 401,544 | dashboard datasource, Data Panel, organization usage counts |
| 2 | `uptimedb_sitemonthlyperformance` | 87,438 | datasource, **All KPI's** (O&M), **RCA Site Scope**, report export, Data Panel |
| 3 | `uptimedb_escalationsite` | 6,764 | **RCA overview**, Data Panel, organization usage |
| 4 | `uptimedb_uptimesite` | 6,726 | datasource, **RCA import (site validation)**, **RCA cycles (expected units)**, **Team Performance hierarchy**, report export, Data Panel |
| 5 | `uptimedb_dataimportbatch` | 30 (export to CSV first, as decided) | raw-upload screens, Data Panel |
| 6 | `uptimedb_escalationimportbatch` | 2 (export to CSV first) | Data Panel |

**Protected, never touched:**
- auth and sessions;
- accounts (users, roles, assignments, events);
- organization (5 tables; the `organization.0004` tables are not created);
- RCA (10 tables, 178,692 records);
- alerts;
- `uptimedb_appsetting` (data source setting, alert heartbeat).

`sitedata` writes to none of them: it only reads the role check, the audit logger, circle aliases and parsers.

**Consequence:** clearing tables 1–6 today would delete no protected data, but it would break protected functions:
- RCA uploads would fail site validation;
- RCA cycles would lose their units;
- Site Scope and All KPI's would lose O&M;
- the Team Performance hierarchy and the Data Panel would have no sites;
- every dashboard page would be empty.

## 7. Dashboard integration status

`sitedata.dataset.build()` produces the dashboard dataset. Tests run the dashboard, Team Performance and All KPI's
APIs on it, **but no page uses it**: `uptimedb.datasource.current_dataset()` still reads the old tables.

There is also no upload screen or API for the new importers; the existing CSV upload and Database Import pages use the
old importers.

The cutover needs changes in protected modules, each to be approved:

| Module | Change needed |
|---|---|
| `uptimedb.datasource` | A third source "new data layer" (→ `sitedata.dataset.build`), switched by the existing data-source setting, which also gives an instant rollback |
| All KPI's | O&M from the matrix date instead of `SiteMonthlyPerformance.om_start` |
| RCA (importer, cycles, sitescope, overview) | Site validation, expected units and O&M from `sitedata` |
| Team Performance hierarchy (`organization.0004`) | FK target `sitedata.Site` instead of `uptimedb.UptimeSite` before it is applied |
| Data Panel (masterdata), report export, organization usage counts | Read `sitedata` |
| Upload screens | Endpoints for the new importers (and the import lock above) |

## 8. Backup and rollback

**Before applying the migration** (additive, low risk):
1. Run `pg_dump -Fc` of the whole database to `Data/backups/4G-DB_<timestamp>.dump` and record its SHA-256.
2. Check that `pg_restore --list` reads it.
3. Save the row count of every table beside the dump.
4. Rollback: `manage.py migrate sitedata zero`. This drops only the 9 new tables; nothing else changes.

**Before the production import into `sitedata`:** the same dump, plus a copy of `Data/processed/` (staged files).
- Rollback: `migrate sitedata zero` (or delete the `sitedata` rows from a restored copy). The old tables and pages are
  unaffected throughout.

**Before clearing the six old tables** (only after the consumers are moved and approved):
1. Take the full dump, and export the 32 old upload records to CSV.
2. Record row counts and checksums of every protected table.
3. Test-restore into a separate scratch database (requires a CREATEDB-capable account), then compare the row counts.
4. Clear the six tables in the order of section 6, in one transaction, with a dry run first. Afterwards, check that every
   protected table's counts and checksums are unchanged.
5. Rollback: `pg_restore` of those six tables from the dump, or a full restore.

## 9. Proposed sequence

| Step | Action | Production effect | Approval |
|---|---|---|---|
| 1 | Backup (section 8) | none | yes |
| 2 | `migrate sitedata` on live (creates 9 empty tables) | none visible | yes |
| 3 | Import into `sitedata`: matrix → mapping → Uptime Masters → CSVs (the replay sequence) | none visible; old pages unchanged | yes |
| 4 | Compare `sitedata` with the replay figures (`docs/phase2-replay/full-replay/`) | none | – |
| 5 | Code changes of section 7 (protected modules) and the import lock | none until switched | yes, per module |
| 6 | Switch the data-source setting to the new layer; parallel run; switch back if needed | dashboard reads `sitedata` | yes |
| 7 | Review and re-target `organization.0004`, then apply it | Team Performance hierarchy | yes (separately) |
| 8 | Controlled clear of the six old tables (section 8) | old tables empty | yes, last |

## 10. Risks and blockers

| Risk / blocker | Severity | Mitigation |
|---|---|---|
| Protected modules read the old tables directly | **Blocker for any reset** | Section 7 changes, approved per module |
| No upload screen or API for the new importers | **Blocker for operation** | Endpoints + UI (with the import lock) |
| No import lock (concurrent commits) | Medium | Advisory lock; run commands one at a time until then |
| `organization.0004` FK + CASCADE to the old site table | Medium | Re-target before applying; never clear `uptimedb_uptimesite` after applying it unchanged |
| Matrix data gaps (78 + 3 O&M dates, 12 + 2 On-Air dates, 2 RJ sites, 436 ambiguous band IDs) | Data | Correct the matrix; figures change once corrected |
| Mapping gaps (LWEBH0141, BLG1394, 188 unmapped LWE sites) | Data | Correct the mapping workbook |
| Live LWE October gap (26–31 Oct) | Data | Resolved by the new layer's import of the LWE Oct'26 report |
| Staged files outside the database | Low | Include `Data/processed/` in backups |
| Append-only log enforced only in the ORM | Low | Optional DB-level protection |

## 11. Pre-production checklist

- [ ] Approval to apply `sitedata.0001_initial` to the live database.
- [ ] Full `pg_dump`, SHA-256 and `pg_restore --list` verified; row counts of every table saved.
- [ ] `Data/processed/` copied with the backup.
- [ ] `migrate sitedata` applied; `showmigrations` shows only `sitedata.0001` newly applied; `organization.0004` still
      unapplied.
- [ ] Every protected table's row count is unchanged after the migration.
- [ ] Production import in the replay order; counts equal the replay
      (`docs/phase2-replay/full-replay/full-replay-summary.md`).
- [ ] Exception reports reviewed (matrix, mapping, precedence).
- [ ] Section 7 changes approved, implemented and tested; import lock added.
- [ ] Data-source switch tested with an instant switch back.
- [ ] `organization.0004` reviewed and re-targeted before it is applied.
- [ ] Old-table clear: separate approval, fresh backup, dry run, protected checksums before and after.

## Test status

| Check | Result |
|---|---|
| `tests.test_sitedata` | 61 / 61 pass (3 new tests for the defects fixed in this audit) |
| Full backend suite | 574 tests, 2 failures, both pre-existing: `test_reconciliation.OctoberWorkbookReconciliationTests` (`test_dataset_shape`, `test_calculation_check_uses_each_formulas_population`), which read the live Master workbook; none from `sitedata` |
| `manage.py check` | No issues |
| `makemigrations sitedata --check` | No changes: the models match `0001_initial` |
