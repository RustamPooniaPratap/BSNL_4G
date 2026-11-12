# PostgreSQL Database State Audit

| | |
|---|---|
| Date | 11 Nov 2026 |
| Code baseline | `main` at `9a69ada` |
| Companion report | `COMPREHENSIVE_PROJECT_AUDIT.md` (issue IDs `C-n` refer to it) |
| Mode | **Read-only.** Every query ran in a session opened with `default_transaction_read_only=on` and `psycopg` `read_only=True`, and every transaction was rolled back. Only `SELECT`/`SHOW` statements were issued (the script asserts this). No migration, DDL or DML was executed. No source or environment file was changed. No credentials are reproduced here. |
| Evidence tags | **[V]** verified directly in the database or code. **[I]** inferred or assumed; needs confirmation. |

> **The most important caveat:** the database inspected is the **local PostgreSQL on this workstation**. The handover calls it production, but nothing in the database proves that. Findings about "production" are inferences. Section 11 gives the exact queries to repeat against the real production server.

---

## 1. Summary

1. **[V] Connection target.** The application connects to `fourg_db` on `127.0.0.1:5432` (PostgreSQL 18.6, Windows). It does **not** use `4G-DB`, which the handover and backup reports name as production. A database called `4G-DB` exists on this server but **contains no tables**.
2. **[V] `fourg_db` looks like a copy of the production `4G-DB`:**
   - the migration timestamps match;
   - the `sitedata` import of 4 Nov 18:07–18:34 IST matches the documented production import, record for record (410,130 daily rows, 6,764 sites).
   - It was evidently restored or loaded on this machine today: autovacuum and analyze ran at 15:20 IST, and server statistics show the big tables freshly inserted. **[I]**
3. **[V] Migrations:**
   - 37 rows are applied.
   - **2 are pending:** `organization.0004_team_performance_hierarchy` and `sitedata.0002_alternate_site_identifier`.
   - No migration is applied that is missing on disk.
4. **[V] `organization.0004` is not applied, and none of its 10 tables exist.** It depends only on already-applied migrations, so **a plain `manage.py migrate` would apply it immediately.** It would create `org_site_personnel_assignment.site_id` → `uptimedb_uptimesite` with Django `on_delete=CASCADE`.
5. **[V] There is no foreign key between `sitedata_*` and `uptimedb_*`.** The only database object linking the layers is the view **`site_overview`** (from migration `uptimedb.0002`), which reads `uptimedb_uptimesite`, `uptimedb_escalationsite` and `rca_rcarecord`.
6. **[V] Schema drift: none,** apart from the 10 tables of the pending `0004`. Every expected table, column, nullability, `max_length`, FK target, named constraint and index exists. There are no extra tables or columns.
7. **[V] RCA operational data is absent from this database:**
   - `rca_rcarecord` has **0 rows**, while its ID sequence stands at **180,512** (production reportedly held 178,692 records on 4 Nov);
   - `rca_rcaevent` has 0 rows (sequence 3,478);
   - `rca_rcareportingcycle` has 0 rows (sequence 30);
   - 12 consolidated RCA upload batches are only "previewed".
   - The statistics show 0 inserts and 0 deletes into `rca_rcarecord`. This is consistent with a restore without RCA data rather than a deletion **[I]**.
8. **[V] The two layers diverge:**
   - September agrees exactly.
   - **October has 2,493 site-days with different outage values,** mostly LWE Odisha.
   - **November exists only in the legacy tables:** 43,188 reported site-days, 4G to 10 Nov, from a Master workbook committed **today at 16:47 IST**.
   - The new layer, which every dashboard reads, ends at **31 Oct**.
9. **[V] This confirms an inference from the earlier audit (C-5).** Legacy monthly rows for **November 2026 have no O&M Start values** (0 of 4,544 known). The RCA Site Scope reads exactly this, so its "O&M Start / Not Started" filters will be empty for November.
10. **[V] Security:**
    - the application role is **`postgres`, a superuser**, and it owns every table;
    - **it is the only login role on this server;**
    - the documented least-privilege role `bsnl_portal_app` **does not exist here**.

---

## 2. Database Connection Target (no credentials)

| Item | Value | Source |
|---|---|---|
| Engine | `django.db.backends.postgresql` | `backend/.env` `DB_ENGINE` [V] |
| Host / port | `127.0.0.1` / `5432` (server reports `127.0.0.1/32:5432`) | `.env`; `inet_server_addr()` [V] |
| Database | **`fourg_db`** | `.env` `DB_NAME`; `current_database()` [V] |
| Schema / search_path | `public` / `"$user", public` (only non-system schema) | [V] |
| Server | PostgreSQL **18.6** on x86_64-windows (service `postgresql-x64-18`), started 11 Nov 2026 12:54 IST | `version()`, `pg_postmaster_start_time()` [V] |
| Encoding / time zone | UTF8 / Asia/Calcutta | [V] |
| Extensions | `plpgsql` only | [V] |
| Role used by the app (and by this audit, read-only) | `postgres`: **superuser** | `pg_roles.rolsuper` [V] |
| Login roles on the server | `postgres` only. **`bsnl_portal_app` does not exist.** | `pg_roles` [V] |
| Databases on the server | `4G-DB` (7.9 MB, **0 relations in `public`**), `fourg_db` (285.5 MB), `postgres` | `pg_database`; separate read-only connection to `4G-DB` [V] |
| Default transaction mode during audit | `transaction_read_only = on`, `default_transaction_read_only = on` | `current_setting()` [V] |

**Discrepancy with the documentation [V]:**
- `docs/production-backup-report-20261104.md:13` and `docs/production-sitedata-import-20261104.md:3` identify production as `4G-DB` (backups under `C:\Users\gaura\Backups\4G-DB\`).
- On this workstation (`C:\Users\pc`), `4G-DB` is empty and the application uses `fourg_db`.
- Anyone following the handover's commands literally (`-d 4G-DB`) on this machine would target the wrong, empty database.

---

## 3. Applied Migrations [V]

Source: `SELECT id, app, name, applied FROM django_migrations ORDER BY id`. 37 rows. IDs 3–5 are missing (see section 8).

| App | Applied migrations (applied at, IST) |
|---|---|
| contenttypes | 0001_initial, 0002_remove_content_type_name (23 Oct 13:16) |
| auth | 0001 … 0012 (23 Oct 13:16) |
| sessions | 0001_initial (23 Oct 13:16) |
| accounts | 0001_initial, 0002_portal_roles (23 Oct 17:51); 0003_noc_lead_role (28 Oct 17:30); 0004_account_circles (29 Oct 00:13); 0005_rca_consolidated_group (30 Oct 17:04); 0006_access_control (31 Oct 13:36); 0007_data_panel_permissions (1 Nov 23:14) |
| uptimedb | 0001_initial (24 Oct 22:36); 0002_escalation_matrix (28 Oct 13:12); 0003_escalation_village_code (28 Oct 13:14); 0004_raw_daily_uploads (29 Oct 00:13); 0005_data_panel_batch_kind (1 Nov 23:14) |
| rca | 0001_initial (26 Oct 14:34); 0002_reporting_cycles (28 Oct 16:40); 0003_upload_details (28 Oct 17:30); 0004_incident_occurrence (28 Oct 17:45); 0005_upload_types (30 Oct 17:04) |
| organization | 0001_initial, 0002_initial_organization (30 Oct 14:04); 0003_access_moved_to_assignments (31 Oct 13:36) |
| alerts | 0001_initial (31 Oct 12:44) |
| sitedata | 0001_initial (4 Nov 18:07) |

These timestamps match the production history in the handover (for example, `sitedata.0001` "applied to production 4 Nov 2026"). This supports the conclusion that `fourg_db` is a copy of production **[I]**.

## 4. Pending Migrations [V]

Computed by comparing `MigrationLoader(None).disk_migrations` (no database connection) with `django_migrations`.

| Migration | Dependencies | All dependencies applied? | Schema effect |
|---|---|---|---|
| `organization.0004_team_performance_hierarchy` | `organization.0003`, `auth.0001`, `uptimedb.0005` | **Yes**, so `migrate` would apply it now | Creates 10 tables, 7 constraints, 4 indexes (section 5) |
| `sitedata.0002_alternate_site_identifier` | `sitedata.0001` | Yes | `AlterField` of `choices` on three `kind` fields: **no SQL** (Django choices are not enforced in PostgreSQL) |

- Applied but missing on disk: **none**.
- `makemigrations --check --dry-run` (run during the earlier audit, SQLite settings): "No changes detected". The models and migration files are consistent.

---

## 5. `organization.0004_team_performance_hierarchy`: Detailed Analysis

**Status [V]:** not in `django_migrations`. None of its tables exist (`org_operational_area`, `org_operational_area_alias`, `org_om_manager_assignment`, `org_om_manager_assignment_audit`, `org_personnel`, `org_personnel_alias`, `org_personnel_source_mapping`, `org_personnel_conflict`, `org_personnel_merge_audit`, `org_site_personnel_assignment`). No `django_content_type` rows exist for these models.

**What it would create** (`backend/apps/organization/migrations/0004_team_performance_hierarchy.py`, 326 lines) [V]:

| Table | Foreign keys (Django on_delete) |
|---|---|
| `org_om_manager_assignment` | circle → `organization_circle` PROTECT; project → `organization_project` PROTECT; user → `auth_user` SET_NULL; created_by/updated_by → `auth_user` PROTECT |
| `org_om_manager_assignment_audit` | assignment → `org_om_manager_assignment` SET_NULL; actor → `auth_user` PROTECT |
| `org_operational_area` | circle → `organization_circle` PROTECT |
| `org_operational_area_alias` | oa → `org_operational_area` PROTECT |
| `org_personnel` | merged_into → `org_personnel` PROTECT; merged_by → `auth_user` PROTECT; user → `auth_user` (one-to-one) SET_NULL |
| `org_personnel_alias` | personnel PROTECT; circle, project PROTECT |
| `org_personnel_conflict` | resolved_personnel PROTECT; reviewed_by PROTECT |
| `org_personnel_merge_audit` | target_personnel PROTECT; actor/rollback_actor PROTECT |
| `org_personnel_source_mapping` | personnel, source_circle, source_project, approved_by PROTECT |
| **`org_site_personnel_assignment`** | **site → `uptimedb_uptimesite` CASCADE** (line 240); personnel, parent_ci → `org_personnel` PROTECT; created_by/updated_by PROTECT |

**How the CASCADE would behave in PostgreSQL [V].** Every foreign key in this database is created by Django as `NO ACTION DEFERRABLE INITIALLY DEFERRED` (`confdeltype='a'` on all 55 FKs inspected). Django's `CASCADE` and `PROTECT` are applied in Python by the ORM delete collector, not by the database. Therefore:
- **Deleting an `UptimeSite` through the ORM** (Data Panel, an importer, a shell or a management command) would **silently delete that site's personnel assignments.**
- **A raw `DELETE FROM uptimedb_uptimesite`** would *fail* at commit while assignments reference it.
- **`TRUNCATE uptimedb_uptimesite CASCADE`** would **wipe every assignment.**
- The FK becomes a **hard database dependency on the legacy site table**, blocking the planned retirement of `uptimedb_*` (Phase 3 of the audit roadmap).

**Consequences of the current unapplied state:**
- **[V]** The code still ships the models and 17 live admin endpoints (`organization/urls.py`; `hierarchy_views.py`) plus the admin tabs in `HierarchyTabs.tsx`.
- **[I]** On this database every one of those endpoints would fail with "relation does not exist", returned as a generic 500, and the frontend renders it as empty lists. This is not exercised here, because it would mean running the application against the database.
- **[V]** The hierarchy design points at legacy `UptimeSite` (6,726 rows, Uptime-Master attributes). The dashboards use `sitedata_site` (6,764 rows, matrix attributes). Assignments created under 0004 would refer to a different site population than Team Performance.

**Risk if someone runs `python manage.py migrate` [V]:**
- It applies both pending migrations.
- Applying `0004` is reversible while its tables are empty (`migrate organization 0003`).
- Once assignments exist, the CASCADE dependency is live.

**Recommendation** (for the next phase, not implemented):
1. Do not run an unqualified `migrate` on any environment.
2. If `sitedata.0002` is wanted, run only `migrate sitedata 0002`. It is a no-op at the SQL level.
3. Before applying `0004` anywhere, confirm it is unapplied in the real production database (section 11, Q2).
4. If it is unapplied everywhere, edit or replace it so that the site FK targets `sitedata.Site` with `PROTECT`.
5. If it is applied anywhere, add a new migration instead.

---

## 6. Table Inventory [V]

52 base tables and 1 view in `public`. Exact `count(*)`. Sizes are `pg_total_relation_size`. All are owned by `postgres`.

### New data layer: `sitedata_*` (9 tables, from `sitedata.0001`)

| Table | Rows | Size |
|---|---|---|
| `sitedata_site` | 6,764 | 4.8 MB |
| `sitedata_siteidentifier` | 17,214 | 4.6 MB |
| `sitedata_identifierconflict` | 436 | 0.3 MB |
| `sitedata_lwemappingrow` | 1,996 | 0.7 MB |
| `sitedata_lwemappingidentifier` | 5,939 | 1.5 MB |
| `sitedata_dailysiteperformance` | **410,130** | 85.9 MB |
| `sitedata_dailyperformanceevent` | 1,552 (all `conflict`) | 0.6 MB |
| `sitedata_monthlysiteperformance` | 38,663 | 10.8 MB |
| `sitedata_uploadbatch` | 24 | 0.2 MB |

### Legacy layer: `uptimedb_*` (7 tables)

| Table | Rows | Size |
|---|---|---|
| `uptimedb_uptimesite` | 6,726 | 6.2 MB |
| `uptimedb_sitedailyperformance` | **456,530** | 70.2 MB |
| `uptimedb_sitemonthlyperformance` | 91,982 | 18.3 MB |
| `uptimedb_escalationsite` | 6,764 | 5.1 MB |
| `uptimedb_escalationimportbatch` | 2 | 0.1 MB |
| `uptimedb_dataimportbatch` | 43 | 4.8 MB |
| `uptimedb_appsetting` | 2 (`dashboard_data_source` = `database`; `alerts_worker_heartbeat`) | 0.1 MB |

### RCA: `rca_*` (10 tables)

| Table | Rows | ID sequence last value |
|---|---|---|
| `rca_rcarecord` | **0** | **180,512** |
| `rca_rcaevent` | 0 | 3,478 |
| `rca_rcaworkflow`, `rca_rcacomment`, `rca_rcareport` | 0 | never used |
| `rca_rcareportingcycle` | 0 | 30 |
| `rca_rcarequiredsubmission` | 0 | 39 |
| `rca_rcacausecategory` / `rca_rcacausemapping` | 0 / 0 | 2 / 11 |
| `rca_rcaimportbatch` | 12 (ids 22–33, all `consolidated` / `previewed`, 4–11 Nov, 59.3 MB of staged JSON) | 33 |

### Infrastructure

| Group | Rows |
|---|---|
| `accounts_*` | accessassignment 3, accessevent 8, accountprofile 3, role 4, rolepermission 19 |
| `organization_*` | project 3, circle 13, projectcircle 14, circlealias 53, organizationchange 23 |
| `alerts_*` (7 tables) | all 0 |
| `auth_*` | user 4 (1 superuser, 3 active), group 4, user_groups 2, permission 192 |
| `django_*` | content_type 48, migrations 37, session 178 (1 unexpired) |

### View

`site_overview`, created by `uptimedb.0002_escalation_matrix` (dropped and recreated by `uptimedb.0003`, `rca.0002`, `rca.0004`):
- `uptimedb_uptimesite` LEFT JOIN `uptimedb_escalationsite`;
- plus a correlated count of active `rca_rcarecord` rows per (project, site_key).
- Its definition in the database matches the migration.
- No application code queries it, apart from `tests/test_escalation.py:153`.

**There are no triggers, user functions, materialized views or additional schemas.**

---

## 7. Foreign-Key Dependency Map [V]

All 55 application foreign keys are `NO ACTION`, `DEFERRABLE INITIALLY DEFERRED`, and validated (Django default). Django-level `on_delete` is shown in brackets, from the models.

```
sitedata (self-contained; only external target = auth_user)
  sitedata_site.matrix_batch_id ─────────────→ sitedata_uploadbatch        [PROTECT]
  sitedata_siteidentifier.site_id ───────────→ sitedata_site               [PROTECT]
  sitedata_siteidentifier.batch_id ──────────→ sitedata_uploadbatch        [PROTECT]
  sitedata_siteidentifier.mapping_row_id ────→ sitedata_lwemappingrow      [PROTECT]
  sitedata_identifierconflict.batch_id ──────→ sitedata_uploadbatch        [PROTECT]
  sitedata_lwemappingrow.batch_id / site_id ─→ sitedata_uploadbatch / sitedata_site [PROTECT]
  sitedata_lwemappingidentifier.row_id ──────→ sitedata_lwemappingrow      [PROTECT]
  sitedata_dailysiteperformance.site_id ─────→ sitedata_site               [PROTECT]
  sitedata_dailysiteperformance.batch_id ────→ sitedata_uploadbatch        [PROTECT]
  sitedata_dailyperformanceevent.site_id / batch_id / stored_batch_id / user_id → site / uploadbatch / auth_user [PROTECT]
  sitedata_monthlysiteperformance.site_id / finalized_by_id → sitedata_site / auth_user [PROTECT]
  sitedata_uploadbatch.uploaded_by_id ───────→ auth_user                   [SET_NULL]

uptimedb (self-contained; only external target = auth_user)
  uptimedb_uptimesite.batch_id ──────────────→ uptimedb_dataimportbatch    [PROTECT]
  uptimedb_sitedailyperformance.site_id ─────→ uptimedb_uptimesite         [CASCADE]
  uptimedb_sitedailyperformance.batch_id ────→ uptimedb_dataimportbatch    [PROTECT]
  uptimedb_sitemonthlyperformance.site_id ───→ uptimedb_uptimesite         [CASCADE]
  uptimedb_sitemonthlyperformance.batch_id ──→ uptimedb_dataimportbatch    [PROTECT]
  uptimedb_escalationsite.uptime_site_id ────→ uptimedb_uptimesite         [SET_NULL, unique]
  uptimedb_escalationsite.batch_id ──────────→ uptimedb_escalationimportbatch [PROTECT]
  uptimedb_dataimportbatch / _escalationimportbatch / _appsetting → auth_user

rca (self-contained; external target = auth_user)
  rca_rcarecord.batch_id / withdrawn_by_batch_id → rca_rcaimportbatch ; created_by_id → auth_user
  rca_rcaworkflow / rca_rcacomment / rca_rcaevent .record_id → rca_rcarecord [CASCADE]
  rca_rcaimportbatch.cycle_id → rca_rcareportingcycle ; rca_rcareport / rca_rcarequiredsubmission .cycle_id → rca_rcareportingcycle
  rca_rcacausemapping.category_id → rca_rcacausecategory

organization / accounts
  organization_projectcircle → organization_project, organization_circle
  organization_circlealias → organization_project, organization_circle, auth_user
  accounts_accessassignment → organization_project, organization_projectcircle (+ role, user)
```

**Cross-app links at database level:** only to `auth_user`, plus `accounts` → `organization`. There is **no FK from `rca_*` to any site table.** RCA links to sites only logically, by text (project, circle, site_key).

---

## 8. Legacy-to-sitedata Dependency Map

### 8.1 Database level [V]

| Link | Type | Effect on retiring legacy tables |
|---|---|---|
| `sitedata_*` ↔ `uptimedb_*` | **None** (no FK, view, trigger or function) | — |
| `site_overview` view → `uptimedb_uptimesite`, `uptimedb_escalationsite`, `rca_rcarecord` | View | `DROP TABLE` on those tables fails unless the view is dropped first (or `CASCADE` is used) |
| `org_site_personnel_assignment.site_id` → `uptimedb_uptimesite` | **Pending** (0004, not created) | Would add a hard dependency once applied |
| RCA ↔ sites | None (text keys only) | — |

### 8.2 Application level

Verified in code in the companion audit, section 7.4. The legacy tables remain **read and written** by:
- the raw CSV upload (writes `uptimedb_sitedailyperformance`);
- the legacy Master-workbook import;
- the Data Panel (read/write);
- the CSV Arrival Tracker and reminders;
- emailed reports;
- RCA breakdown, overview, summary, Site Scope, import validation and cycles;
- the hierarchy services;
- organization usage counts.

The new layer is read by every dashboard, All KPI's, Site Portfolio and portal exports.

### 8.3 What the database shows about who writes where [V]

| Layer | Batches | Latest committed write | Who / how |
|---|---|---|---|
| `uptimedb` | 43: master_workbook 13 committed + 5 previewed; raw_daily_csv 9 committed, 7 previewed, 8 rejected, 1 discarded | **Batch #43, `master_workbook`, committed 11 Nov 2026 16:47 IST** (contains November data to 10 Nov) | Application (Data Source page / API) |
| `sitedata` | 24: consolidation_matrix 2, lwe_band_mapping 1, raw_csv_4g 8, raw_csv_lwe 7, uptime_master 4 committed; **uptime_master 2 previewed (7 Nov, never committed)** | Matrix re-import 5 Nov 12:52 IST | **20 of 24 batches have `uploaded_by_id` NULL.** The 4 Nov import ran through scripts or commands (raw_csv_* batches exist although no in-repo endpoint produces them). One matrix batch has a user (UI). |

**Interpretation [I].**
- Since 5 Nov, all new data on this database has gone into the legacy layer only. The two November Up-Time previews into `sitedata` (7 Nov) were never committed.
- The dashboards are therefore frozen at 31 Oct, while the Data Source page and the legacy tables show data to 10 Nov.
- This is the user-visible symptom of C-1, C-7 and C-12.

---

## 9. Schema Drift Findings [V]

Method:
- Django was loaded with SQLite settings, so the script made no PostgreSQL connection through Django.
- For every managed model it checked: the table exists; each `local_fields` column exists; nullability; `CharField` `max_length`; FK target table; every `Meta.constraints` and `Meta.indexes` name present in `pg_constraint` or `pg_indexes`.
- It also checked for database tables and columns that no model declares.

| Check | Result |
|---|---|
| Expected tables (61) vs database tables (52) | 9 + 1 missing = the **10 hierarchy tables of pending `organization.0004`**; nothing else |
| Tables in the database without a model | `django_migrations` only (expected) |
| Missing / extra columns | **None** |
| Nullability mismatches | **None** |
| `max_length` mismatches | **None** |
| FK target mismatches / missing FKs | **None** |
| Named constraints and indexes | **All present**, including `sitedata_daily_unique`, `sitedata_daily_outage_range` (0–1440), `sitedata_daily_availability_range` (0–100), the partial unique index `sitedata_monthly_current`, `sitedata_monthly_days`, `sitedata_site_scope_technology`, `uptime_site_identity`, `uptime_site_date`, `escalation_site_identity` |
| `sitedata.0002` | Pending, but choices-only, so **no schema difference** |
| `site_overview` view | Present; matches the migration definition |

**Observations (not drift):**
- **[V] `django_migrations` IDs 3, 4 and 5 are missing.** There is no `admin` content type and no `django_admin_log` table, and `django.contrib.admin` is not in `INSTALLED_APPS`.
- **[I]** The most likely cause is that the admin app's migration rows (normally IDs 3–5) were removed when admin was uninstalled. This is harmless, but it means the history was edited by hand at least once.
- **[V] Constraint gaps that are by design** (they are in the models too, so they are not drift):
  - legacy `uptimedb_sitedailyperformance` has **no CHECK on `outage_minutes`**: 4 rows exceed 1,440 (section 10);
  - there is no database constraint that `sitedata_dailysiteperformance.technology` equals the site's technology. The data is consistent today: 0 mismatches between layers.
- **[V] Expired sessions are not cleared:** 177 of 178 rows have expired, which means `clearsessions` never runs. Minor.

---

## 10. Data Count Reconciliation [V]

The two layers can be compared safely because:
- both normalise `site_key` the same way;
- `sitedata` `technology` values equal the legacy `project` keys (`4G Saturation`, `LWE`);
- legacy blanks are stored as NULL and are excluded from the comparison.

**Join key:** (`site_key`, date, technology/project).

### 10.1 Sites

| Measure | sitedata | legacy | Notes |
|---|---|---|---|
| Sites | 6,764 (6,724 `dashboard` + 40 `outside_scope`) | 6,726 | — |
| Distinct site_key in both | 6,724 | 6,724 | — |
| Only in sitedata | 40 | — | **All `outside_scope`**: Sterlite / VI-HPSC (DELHI-NCR 23, RJ 17); excluded from KPIs by design |
| Only in legacy | — | 2 | `4G Saturation / RJ / UVRJJPR00057` and `UVRJUPR00612`: the "2 RJ sites missing from the matrix" in the handover |
| Technology mismatch for shared keys | 0 | 0 | — |
| Circle mismatch for shared keys | 0 | 0 | — |
| Per project/circle (dashboard scope) | 4G: MP 1,483, OD 1,603, RJ 1,456; LWE: AP 62, BH 250, CG 364, JH 816, MH 65, MP 22, OD 256, TL 173, UP 78, WB 96 | Identical, except RJ 4G 1,458 (+2 above) | — |

### 10.2 Daily records

| Month | sitedata rows (4G / LWE) | legacy reported rows (4G / LWE) | Matched in both | Only legacy | Only sitedata | Matched with different outage |
|---|---|---|---|---|---|---|
| 2026-09 | 136,229 / 65,459 | 136,290 / 65,460 | 201,688 | 62 | 0 | **0** |
| 2026-10 | 140,802 / 67,640 | 140,864 / 67,642 | 208,442 | 64 | 0 | **2,493** |
| 2026-11 | — | 42,354 / 834 (4G to 10 Nov; LWE 1–3 Nov) | 0 | **43,188** | 0 | — |

**"Only legacy" rows in Sep/Oct:**
- 61 + 61 belong to the two RJ sites missing from the matrix.
- The rest are single LWE MH and 4G RJ rows. These match the legacy rows with outage over 1,440 minutes (Sep 1 + 1, Oct 2), which `sitedata` rejects by its 0–1,440 CHECK. **[I for the exact one-to-one match]**

**October value differences, by technology and circle:**

| Technology / circle | Site-days differing | Mean abs. difference (min) | Note |
|---|---|---|---|
| LWE / OD | 2,222 | 132 | — |
| LWE / TL | 211 | 81 | legacy shows 0 outage where sitedata has outage |
| LWE / AP | 43 | 12 | same direction as TL |
| LWE / MH | 13 | 1,440 | sitedata full-day outage vs legacy 0 |
| 4G / OD | 4 | 436 | sitedata 0 vs legacy outage |

This matches the handover note: legacy October LWE came from the consolidated October workbook, and `sitedata` from the approved LWE Oct'26 report. It is a **source difference, not a calculation error** **[I]**. Any comparison of October LWE figures between the RCA pages or emails (legacy) and the dashboards (sitedata) will disagree.

**Legacy November:** 45,440 4G rows, of which **3,086 have NULL outage** (sites listed but not reported).

### 10.3 Monthly records

| Layer | Content |
|---|---|
| sitedata | Sep and Oct 2026 × three categories: `daily_derived` 6,723 / 6,724; `om_start` 6,202 / 6,202; `on_air` 6,406 / 6,406. All `is_current`, **none finalized**. No November rows. |
| legacy | 14 months (Oct 2025 – Nov 2026). Oct 2025 – Oct 2026 have 6,726 rows each; **Nov 2026 has 4,544**. **O&M Start is known only for Nov 2025, Dec 2025, Jan 2026, Apr 2026, Jul 2026, Sep 2026 and Oct 2026**: NULL in every other month, **including November 2026 (0 of 4,544)**. |

**Consequence [V data, I behaviour].** The RCA Site Scope (`rca/sitescope.py`) takes O&M status from legacy `SiteMonthlyPerformance.om_start` for the record's reporting month. For November 2026, and for several earlier months, no site is classified, so the "O&M Start" and "O&M Not Started" filters return nothing.

Legacy October says 6,280 O&M = Yes. `sitedata` counts 6,202 `om_start` sites for October from matrix dates. The two O&M populations differ by 78 sites. That equals the "78 MP 4G sites without O&M Start Date in the matrix" noted in the handover **[I]**.

### 10.4 RCA

| Measure | Value |
|---|---|
| `rca_rcarecord` rows | **0** |
| `rca_rcarecord_id_seq` | **180,512** (records existed in the source database) |
| Production per backup report (4 Nov) | 178,692 records (`docs/production-backup-report-20261104.md:83`) |
| `pg_stat_user_tables` for `rca_rcarecord` | `n_tup_ins = 0`, `n_tup_del = 0`, no vacuum or analyze |
| RCA import batches | 12, all `consolidated` / `previewed` (staged rows, never committed) |

**Interpretation [I]:**
- The large tables were inserted into this database today. For example, `sitedata_dailysiteperformance` shows `n_tup_ins = 410,130` and an autovacuum at 15:20.
- With no insert and no delete recorded for `rca_rcarecord`, the most likely explanation is a restore whose RCA data was excluded or failed, with the sequence values restored. Deletion after the restore is less likely.
- **Either way, this database cannot serve as an RCA reference.** It must **never be copied over production**.

---

## 11. Verification Queries for the Real Production Database

Run these as a **read-only** role. Suggested setup by a DBA, outside this audit:

```sql
CREATE ROLE audit_ro LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE "4G-DB" TO audit_ro;
GRANT USAGE ON SCHEMA public TO audit_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO audit_ro;
ALTER ROLE audit_ro SET default_transaction_read_only = on;
```

Or open the session with `psql "dbname=4G-DB options='-c default_transaction_read_only=on'"`. Every statement below is a `SELECT`.

```sql
-- Q1 Identity and session safety
SELECT current_database(), current_user, version(), inet_server_addr(), inet_server_port(),
       current_setting('transaction_read_only') AS read_only,
       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser;
SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE NOT datistemplate;
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname NOT LIKE 'pg\_%';

-- Q2 Applied migrations (look for organization 0004 and sitedata 0002)
SELECT app, name, applied FROM django_migrations ORDER BY app, name;
SELECT app, name FROM django_migrations
 WHERE (app, name) IN (('organization','0004_team_performance_hierarchy'), ('sitedata','0002_alternate_site_identifier'));

-- Q3 Hierarchy tables present?
SELECT to_regclass('public.org_site_personnel_assignment') AS site_assign,
       to_regclass('public.org_personnel') AS personnel;
-- if present:
SELECT count(*) FROM org_site_personnel_assignment;

-- Q4 Table inventory with exact counts (generate, then run the output)
SELECT format('SELECT %L AS t, count(*) FROM public.%I UNION ALL', tablename, tablename)
  FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

-- Q5 Foreign keys touching site tables
SELECT cl.relname AS tbl, co.conname, fcl.relname AS ref, co.confdeltype, pg_get_constraintdef(co.oid)
  FROM pg_constraint co JOIN pg_class cl ON cl.oid = co.conrelid JOIN pg_class fcl ON fcl.oid = co.confrelid
 WHERE co.contype = 'f' AND (fcl.relname LIKE 'uptimedb%' OR fcl.relname LIKE 'sitedata%' OR cl.relname LIKE 'org\_%')
 ORDER BY 1, 2;

-- Q6 Views / triggers / functions depending on legacy tables
SELECT DISTINCT v.relname AS view, t.relname AS depends_on
  FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class
  JOIN pg_class t ON t.oid = d.refobjid
 WHERE t.relname LIKE 'uptimedb%' OR t.relname LIKE 'rca%' OR t.relname LIKE 'sitedata%';
SELECT event_object_table, trigger_name FROM information_schema.triggers WHERE trigger_schema = 'public';

-- Q7 Constraints of the data tables (compare with section 9)
SELECT conrelid::regclass, conname, contype, pg_get_constraintdef(oid)
  FROM pg_constraint WHERE conrelid::regclass::text ~ '^(sitedata_|uptimedb_)' AND contype IN ('c','u','p')
 ORDER BY 1, 2;

-- Q8 Daily coverage per layer
SELECT to_char(date_trunc('month', report_date), 'YYYY-MM') m, technology, count(*), max(report_date)
  FROM sitedata_dailysiteperformance GROUP BY 1, 2 ORDER BY 1, 2;
SELECT to_char(date_trunc('month', d.date), 'YYYY-MM') m, s.project, count(d.outage_minutes), max(d.date),
       sum((d.outage_minutes > 1440)::int) AS over_1440
  FROM uptimedb_sitedailyperformance d JOIN uptimedb_uptimesite s ON s.id = d.site_id GROUP BY 1, 2 ORDER BY 1, 2;

-- Q9 Layer overlap and value differences
WITH s AS (SELECT st.site_key, d.report_date dt, d.technology t, d.outage_minutes o
             FROM sitedata_dailysiteperformance d JOIN sitedata_site st ON st.id = d.site_id),
     l AS (SELECT u.site_key, d.date dt, u.project t, d.outage_minutes o
             FROM uptimedb_sitedailyperformance d JOIN uptimedb_uptimesite u ON u.id = d.site_id
            WHERE d.outage_minutes IS NOT NULL)
SELECT to_char(date_trunc('month', coalesce(s.dt, l.dt)), 'YYYY-MM') m,
       count(*) FILTER (WHERE s.site_key IS NOT NULL AND l.site_key IS NOT NULL) both_layers,
       count(*) FILTER (WHERE l.site_key IS NULL) sitedata_only,
       count(*) FILTER (WHERE s.site_key IS NULL) legacy_only,
       count(*) FILTER (WHERE abs(s.o - l.o) > 0.01) value_differs
  FROM s FULL JOIN l ON s.site_key = l.site_key AND s.dt = l.dt AND s.t = l.t GROUP BY 1 ORDER BY 1;

-- Q10 Site master overlap
SELECT (SELECT count(*) FROM sitedata_site) sd, (SELECT count(*) FROM uptimedb_uptimesite) legacy,
       (SELECT count(*) FROM sitedata_site s WHERE EXISTS (SELECT 1 FROM uptimedb_uptimesite u WHERE u.site_key = s.site_key)) both_layers;

-- Q11 Legacy monthly O&M availability per month (drives RCA Site Scope)
SELECT to_char(month, 'YYYY-MM'), count(*), count(om_start), sum(om_start::int)
  FROM uptimedb_sitemonthlyperformance GROUP BY 1 ORDER BY 1;

-- Q12 RCA integrity
SELECT count(*), sum((withdrawn_at IS NULL)::int) FROM rca_rcarecord;
SELECT last_value FROM rca_rcarecord_id_seq;
SELECT upload_type, status, count(*) FROM rca_rcaimportbatch GROUP BY 1, 2;

-- Q13 Upload history per layer
SELECT kind, processing_status, count(*), max(uploaded_at), sum((uploaded_by_id IS NULL)::int) AS no_user
  FROM sitedata_uploadbatch GROUP BY 1, 2;
SELECT kind, status, count(*), max(committed_at) FROM uptimedb_dataimportbatch GROUP BY 1, 2;
SELECT key, value FROM uptimedb_appsetting WHERE key = 'dashboard_data_source';
```

**Django commands that are safe to run** against the real settings. They read only, and `showmigrations` does not create tables:

```bat
cd backend
..\.venv\Scripts\python manage.py showmigrations organization sitedata
..\.venv\Scripts\python manage.py migrate --plan          :: prints the plan only; does not apply
..\.venv\Scripts\python manage.py sqlmigrate organization 0004   :: prints the SQL only
```

**Do not run** `migrate`, `makemigrations` (without `--check --dry-run`), `flush`, `dbshell` with DDL, or any importer command.

---

## 12. Risks

| # | Risk | Evidence | Severity |
|---|---|---|---|
| R1 | **Wrong-database operations.** Docs and backup commands name `4G-DB`, but the app here uses `fourg_db`, and `4G-DB` on this server is empty. Backups or restores run "by the book" could capture or overwrite the wrong database. | Sections 2, 8 | **High** |
| R2 | **This database lacks RCA records** (0 of about 180k). Restoring or copying it to another environment would lose RCA history; RCA pages here show nothing. | Section 10.4 | **High** |
| R3 | **An unqualified `migrate` applies `organization.0004`,** creating an ORM-CASCADE dependency on the legacy site table and blocking its retirement. | Section 5 | **High** |
| R4 | **Layer divergence.** Dashboards stop at 31 Oct (sitedata); legacy holds November to 10 Nov; October LWE values differ for 2,493 site-days. Screens on different layers disagree. | Section 10.2 | **High** |
| R5 | **RCA Site Scope has no O&M data for November 2026** (and 7 of the 13 earlier months). | Section 10.3 | Medium–High |
| R6 | **The application connects as a superuser** that owns everything, and no least-privilege role exists. Any SQL-level bug has cluster-wide reach. | Section 2 | High (security) |
| R7 | **Provenance gaps.** 20 of 24 `sitedata` batches have no uploader (script imports); out-of-repo scripts were used. | Section 8.3 | Medium |
| R8 | **The `site_overview` view silently blocks dropping legacy tables** and adds a hidden dependency on `rca_rcarecord`. | Section 8.1 | Low–Medium |
| R9 | **Manually edited migration history** (IDs 3–5 removed). | Section 9 | Low |
| R10 | **The legacy daily table accepts outage over 1,440** (4 rows present). | Section 10.2 | Low |

## 13. Recommended Next Actions (not implemented)

1. **Confirm which database is authoritative.**
   - Is `fourg_db` on this workstation a working copy, and the real production `4G-DB` elsewhere (the original developer machine)?
   - Run section 11 Q1–Q13 there with a read-only role, and update the handover with the correct database name and host.
2. **Investigate the RCA gap before anyone relies on this database.**
   - Compare against the 4 Nov dump: run `pg_restore --list` and `pg_restore -a -t rca_rcarecord` **into a scratch database** to confirm the dump contains the records.
   - Find out how `fourg_db` was created today.
3. **Freeze migrations.**
   - Communicate "no unqualified `migrate`".
   - Verify `organization.0004` status in production (Q2/Q3).
   - Plan the FK re-target (to `sitedata.Site`, PROTECT) as a reviewed change.
4. **Create least-privilege roles** (a DBA task, separately approved):
   - `bsnl_portal_app`: DML on app tables, no DDL outside migrations;
   - a migration/owner role;
   - `audit_ro` for audits like this one.
   - Switch the application off `postgres`.
5. **Decide the data path for November before migrating more modules.**
   - Either commit November Up-Time reports into `sitedata` (the 7 Nov previews were never committed),
   - or document clearly that dashboards stop at 31 Oct until the raw-CSV pipeline (C-1, C-12) lands.
6. **Reconcile October LWE with the business:** which source is approved (sitedata's LWE Oct'26 report or legacy's consolidated workbook)? Record the decision.
7. **Plan the RCA Site Scope fix** (C-5). With legacy monthly O&M flags missing for most months, matrix dates (sitedata) are the only complete O&M source.
8. **Before any future legacy retirement:**
   - drop or replace the `site_overview` view;
   - take and **restore-test** a fresh backup;
   - re-run Q9–Q11 to prove reconciliation.

---

## 14. Verified Facts vs Assumptions

| Statement | Status |
|---|---|
| App connects to `fourg_db` @ 127.0.0.1:5432, PostgreSQL 18.6, as superuser `postgres` | **Verified** |
| `4G-DB` on this server has no tables | **Verified** |
| Pending migrations: `organization.0004`, `sitedata.0002`; no unknown applied migrations | **Verified** |
| 10 hierarchy tables absent; 0004 site FK is Django CASCADE to `uptimedb_uptimesite` | **Verified** (database and migration file) |
| All database FKs are NO ACTION DEFERRABLE; no sitedata↔uptimedb FK; one cross-layer view | **Verified** |
| No schema drift beyond pending 0004 | **Verified** (automated model-vs-catalog comparison) |
| Row counts, overlaps, value differences, monthly O&M gaps, batch history | **Verified** (exact queries) |
| `fourg_db` is a copy of production `4G-DB` | **Assumption** (migration timestamps and import counts match) |
| `fourg_db` was restored or loaded today, without RCA record data | **Assumption** (table statistics, sequences) |
| `organization.0004` is unapplied in the real production database | **Assumption** (handover statement; matches this copy) |
| Hierarchy endpoints return 500 here | **Assumption** (tables absent; endpoints not called) |
| October LWE differences are a source difference | **Assumption** (handover explanation; pattern consistent) |
| Missing `django_migrations` IDs 3–5 are removed admin rows | **Assumption** |

**Artefacts** (scratch, outside the repository):
- `C:\Users\pc\AppData\Local\Temp\claude\060f0d7cda492f67\cb105ccf-fc7d-4b01-b78f-f881d2091131\scratchpad\pg\inspect_pg.py`: the read-only inspection script.
- `…\scratchpad\pg\state.json`: the full catalog and count capture.
- `…\scratchpad\pg\drift.py` and `drift.txt`: the drift comparison.
