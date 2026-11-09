# Production backup report: Phase 1 (4 Nov 2026)

Authorised scope: backup and verification only. Each item below was done or verified as stated:
- **Database:** read-only access only; no migration applied, no table created or changed, no record written, updated or
  deleted, and `organization.0004` not applied.
- **Configuration:** unchanged; no password printed or written.

## 1. Database identity (read-only transaction)

| Item | Configured (`backend/.env`, no secrets shown) | Reported by the server |
|---|---|---|
| Engine | `django.db.backends.postgresql` | PostgreSQL 18.6 on x86_64-windows |
| Database | `4G-DB` | `current_database()` = `4G-DB` |
| Host / port | `127.0.0.1` / `5432` | `inet_server_addr()` = 127.0.0.1, port 5432 |
| Role | `bsnl_portal_app` (password set, not shown) | `current_user` = `session_user` = `bsnl_portal_app` |
| Role rights | – | not superuser, cannot create databases |
| Server state | – | primary (not in recovery); `transaction_read_only` = on |
| Size / tables | – | 253 MB, 43 tables in `public` |

**Identity confirmed:** the target is the existing production database `4G-DB`.

## 2. Backup location

`C:\Users\gaura\Backups\4G-DB\20261104T122933Z\` (387 MB in total)

Chosen **outside the project folder and outside OneDrive**:
- the project lives under `OneDrive\Desktop`, which syncs to the cloud;
- `Data/backups/` is not git-ignored.

The dump contains user accounts, password hashes and sessions: keep it access-restricted, and copy it to separate
offline storage.

## 3. Consistency

All database artifacts come from **one snapshot**:
1. A `REPEATABLE READ READ ONLY` transaction exported its snapshot (taken 2026-11-04 12:29:33.945 UTC).
2. `pg_dump --snapshot` used it.
3. The row counts and the two upload-history exports were read in the same transaction.
4. The transaction was then rolled back (no writes possible).

## 4. Artifacts

| File | Bytes | SHA-256 |
|---|---|---|
| `4G-DB_20261104T122933Z.dump` (custom format, gzip) | 41,065,525 | `90327eddee716b74c519f8a4ab55e9e0ab7832ab220ddfd8226cc25399ac0094` |
| `pg_restore-list.txt` (archive table of contents) | 37,442 | `0dffb1e9d8d69775015765b17f4f257f346d4c5c177f5dc75f0a9ba630c66143` |
| `row-counts.csv` (every table, exact `count(*)`) | 1,369 | `9e7415ef4764f5374a3c912cb56019343551c3fc81e3ffa3d297ae45b2c56f7b` |
| `uptimedb_dataimportbatch.csv` (30 rows, 24 columns) | 53,529,558 | `4b72f39e44e025179b49827d03f52cdc6d25b4bcdeac162d57e3897d502dec26` |
| `uptimedb_escalationimportbatch.csv` (2 rows, 13 columns) | 9,287 | `a2b680012208959ed581f66078d5854e9c5ecc02696d9c2d73c853957db36551` |
| `Data-processed.sha256` (per-file checksums of the copy) | 7,070 | `9a6bf5047e3b40e4d4945b5fd849a73f47f34c53f92ffe6c6f47cc0aa954bb5d` |
| `Data-processed/` (copy of `Data/processed/`, structure preserved) | 310,912,547 (64 files) | per file in `Data-processed.sha256` |
| `SHA256SUMS` (list of the six files above) | 545 | `f74a5914625a6557d49b856b8eebc2c782ee29395b9b8b29d1fccd15728ada80` |
| `backup-manifest.json` (identity, timings, results) | 2,533 | `49350e6280045fd5d0818f465d405df6085f9f6c4ba916451ce21c180724c7fa` |

The upload-history CSV is large because each batch's stored validation report (JSON) is exported in full.

## 5. Timestamps (UTC)

| Step | Time |
|---|---|
| Identity check | 12:28:45 |
| Snapshot exported | 12:29:33.945 |
| `pg_dump` | 12:29:33.953 – 12:30:01.219 (exit code 0, no warnings) |
| Backup finished | 12:30:11.693 |
| Checksum lists rewritten with LF endings (for standard `sha256sum -c`); dump unchanged | after 12:30 |

## 6. Verification

| Check | Result |
|---|---|
| `pg_dump` exit code / stderr | 0 / empty |
| `pg_restore --list` | Reads the archive: custom format, gzip, dump version 1.16-0, dumped from and by 18.6, dbname `4G-DB`, 416 TOC entries |
| Tables in the archive vs tables counted | 43 table definitions and 43 TABLE DATA entries = 43 tables counted; none missing on either side |
| Row counts | 43 tables, 684,488 rows; key tables equal the audit (below) |
| Upload-history exports | 30 and 2 rows = the counts in the same snapshot |
| `Data/processed/` copy | 64 of 64 files; every file's SHA-256 equals its source |
| Independent check | `sha256sum -c SHA256SUMS`: 6 / 6 OK; `sha256sum -c Data-processed.sha256`: 64 / 64 OK |

Key table counts in the snapshot:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `uptimedb_sitedailyperformance` | 401,544 | `rca_rcarecord` | 178,692 |
| `uptimedb_sitemonthlyperformance` | 87,438 | `rca_rcaevent` | 2,649 |
| `uptimedb_escalationsite` | 6,764 | `auth_user` | 4 |
| `uptimedb_uptimesite` | 6,726 | `accounts_role` | 4 |
| `uptimedb_dataimportbatch` | 30 | `organization_circlealias` | 53 |
| `uptimedb_escalationimportbatch` | 2 | `django_migrations` | 36 |
| `uptimedb_appsetting` | 2 | `sitedata_*` / `organization.0004` tables | none exist |

## 7. Not verified, and why

**A test restore was not performed.** The application role `bsnl_portal_app` cannot create databases, and restoring
into `4G-DB` itself is out of scope.

To prove the archive restores, a role with CREATEDB (e.g. the PostgreSQL administrator) can run:

```
createdb -h 127.0.0.1 -U <admin> 4G-DB_restore_check
pg_restore -h 127.0.0.1 -U <admin> -d 4G-DB_restore_check --no-owner "C:\Users\gaura\Backups\4G-DB\20261104T122933Z\4G-DB_20261104T122933Z.dump"
```

Then compare its row counts with `row-counts.csv` and drop the check database. This needs your approval and an admin
role.

## 8. Restore procedure (for reference; not run)

- **Full restore** (replaces the database; only on explicit approval): stop the application, then:

  ```
  pg_restore -h 127.0.0.1 -U <admin> -d 4G-DB --clean --if-exists "<dump>"
  ```

  Then compare with `row-counts.csv`.
- **Selected tables only:** `pg_restore ... --table=<name>`.
- **Files:** copy `Data-processed\` back to `Data\processed\`, then verify with `Data-processed.sha256`.

Next phase (applying `sitedata.0001_initial`) waits for explicit approval.
