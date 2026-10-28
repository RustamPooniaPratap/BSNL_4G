# RCA module

Root-cause analysis (RCA) records from the RCA workbook (`Book1_RCA_Rustam.xlsx`, sheet `Sheet1`), stored in PostgreSQL with reviewed cause categories and follow-up. Backend: `backend/apps/rca`. Frontend: `frontend/src/pages/rca`, `frontend/src/components/rca`.

## Pages

| Route | Page | Who |
|---|---|---|
| `/rca` | **RCA Register**: searchable, paginated records; filters; a row opens the record (source facts, category, follow-up, comments, history); "Record RCA" adds an incident | Admin, CI |
| `/rca/summary` | **RCA Summary**: KPIs, Final Bucket and Bucket - 2 rankings (incidents or outage minutes), circle comparison (incidents, outage minutes, per 100 sites; All / 4G / LWE), cause categories, 15 largest outages | Admin |
| `/rca/mappings` | **Cause mapping**: review queue of RCA descriptions; map selected ones to a category; mapped list | Admin |
| `/rca/import` | **RCA import**: upload, preview, commit, discard, validation report (CSV), history | Admin |

The filters are kept in the URL (`date_from`, `date_to`, `project`, `circle`, `final_bucket`, `bucket_2`, `category`, `status`, `q`), so a view can be refreshed or shared. `/rca?record=<id>` opens a record. Bars on the Summary page open the Register with that filter.

## Data model (migration `rca.0001_initial`, new tables only)

| Table | Holds |
|---|---|
| `RcaImportBatch` | File name, SHA-256, sheet, status (previewed / committed / failed / discarded), who, when, counts, validation report, the conflict choice |
| `RcaRecord` | Source facts as written: reporting date, project (`project_raw` plus normalised `project`), circle (`circle_raw` plus code), Site ID, Site Name, OA, BA, O&M Start (`om_start_raw` plus Yes/No/NULL), Outage Min., Final Bucket, Bucket - 2, RCA. It also stores matching keys (`site_key`, `final_bucket_key`, `bucket_2_key`, `rca_key`), the source (import / manual), batch, file, Excel row and author. An imported record is unique per (date, project, site). A site can have records on other dates, and manual records are not limited. |
| `RcaCauseCategory`, `RcaCauseMapping` | Admin-approved mapping from one normalised RCA description to a category. The source text is not changed |
| `RcaWorkflow` | Follow-up: status, root-cause review, corrective action, owner / team, target and actual dates, verification, reviewer, timestamps. It is created only when someone records follow-up |
| `RcaComment`, `RcaEvent` | Comments with evidence references, and the change history (workflow edits, source overwrites) |

## Import rules

- **Columns:** found by header (case and spaces ignored). A missing required column, or a missing `Sheet1`, rejects the file.
- **Rejected rows (errors):** an invalid date, a blank Site ID, an unknown project or circle, a non-numeric or negative Outage Min., or a duplicate (date, project, Site ID) within the file. Rows are never repaired.
- **Warnings:**
  - outage over 1,440 minutes;
  - blank outage, kept as not recorded rather than 0;
  - an O&M Start value other than Yes or No.
- **Notes:** blank or "-" in Final Bucket, Bucket - 2 or RCA (counted as unclassified, never as a cause), and trimmed spaces.
- **"4G Satu":** read as 4G Saturation, with the source label kept and a note asking to confirm the label.
- **Circles:** names are mapped to the dashboard codes (Odisha→OD, Rajasthan→RJ, Madhya Pradesh→MP, Jharkhand→JH, Bihar→BH, Chhattisgarh→CG, Uttar Pradesh→UP, West Bengal→WB).
- **Spelling and case variants** ("IaasP OFC" / "Iaasp OFC", "BSNL MEDIA" / "BSNL Media", "YES" / "Yes") share a key for filtering. Each record keeps its own spelling, and the most frequent spelling is shown as the label.
- **Preview** writes only the batch.
- **Commit** runs in one transaction:
  - new rows are inserted;
  - identical rows are left alone, so a repeat import adds nothing;
  - rows whose facts differ from a stored record are conflicts. The Admin must choose **skip** or **overwrite**, and an overwrite is recorded in the record's history.
- **Validation report:** `GET /api/rca/imports/<id>/issues.csv` lists every issue and conflict with its Excel row.

## Classification and categories

- **Source fields:** Final Bucket, Bucket - 2 and RCA are separate source fields. Their business meaning beyond the workbook is not assumed.
- **Cause categories:**
  - They exist only through explicit Admin mappings. Similar spellings ("Media Flactuation", "Media Fluctuation", "Flacuation") are not merged unless an Admin selects them.
  - Descriptions that differ only in case or spacing are one queue item.
  - Records without a mapping are **unreviewed**, and the Summary shows them separately.

## RCA applicability: Other Media

- **Rule:** records whose source **Final Bucket is "Other Media"** are **Other Media — RCA Not Applicable**: RCA recording is not applicable to them under the reporting process (`RCA_NOT_APPLICABLE` in `apps/rca/services.py`). No source value is changed.
- **Where they go:** they stay visible as their own KPI card and as a separate muted row in the Final Bucket chart (not ranked as a technical cause). They are left out of the missing-information count, the completeness denominator and the Bucket - 2 chart.
- **Missing information:** **RCA Required — Missing Information** counts the other (RCA-applicable) records with a blank or "-" Final Bucket, Bucket - 2 or RCA. Completeness = (applicable − missing) ÷ applicable.
- **A blank Bucket - 2 alone never makes a record Other Media.** Of the 343 records with Bucket - 2 "-", 120 are Other Media in the source and 223 have another Final Bucket (Iaasp Others 77, BBNL OFC 42, BSNL OFC 34, TCS 27, HFCL 22, IaasP OFC 21); those 223 are RCA required, missing Bucket - 2.
- **Filter:** `rca=not_applicable | required | missing` on the Register and Summary.

Counts on 26 Oct 2026 (import #1, checked against the workbook):

| Group | Records |
|---|---|
| Total | 1,819 |
| Other Media — RCA Not Applicable | 1,076 (120 with Bucket - 2 "-") |
| RCA-applicable | 743 |
| RCA Required — Missing Information | 223 (all 4G, Bucket - 2 "-"); completeness 70.0% |

## Follow-up workflow

Investigation → RCA Review → Action Pending → Action Completed → Verified / Closed.

- **Action Completed** needs the corrective action and the actual completion date. That date cannot be in the future or before the RCA's reporting date.
- **Closing** needs a verification outcome.
- **Nothing is set by the import:** an imported record shows "Not recorded" until someone records follow-up.

## Permissions (enforced by the API)

| Action | Admin | CI |
|---|---|---|
| Register, record detail, filters | ✓ | ✓ |
| Record a new RCA incident | ✓ | ✓ |
| Edit a manually recorded RCA | ✓ | Own records only |
| Edit imported source facts | ✗ (re-import instead) | ✗ |
| Follow-up up to Action Completed, comments | ✓ | ✓ |
| Root-cause review, verification, closure | ✓ | ✗ |
| Summary, import, categories and mappings | ✓ | ✗ |

The portal has no circle-level scope for CI users, so none is applied. Adding one needs a scope model first.

## Circle comparison

Raw counts favour large circles. The **Per 100 sites** measure divides each circle's records by its sites in the dashboard's current Master data (Excel or PostgreSQL, whichever is active). When no Master data is loaded, the rate shows "No population".

## Current data (imported 26 Oct 2026, import #1)

- **Records:** 1,819, all dated 21 Oct 2026, with 1,819 distinct Site IDs.
- **Projects:** "4G Satu" 1,346 and LWE 473.
- **Circles:**
  - 4G: OD 522, RJ 464, MP 360;
  - LWE: JH 293, BH 86, CG 44, UP 39, WB 11.
- **Outage:** 632,278.77 minutes in total. 0 rows were rejected, and one outage of 1,442.55 minutes (LWEBH0269) is flagged as over one day.
- **Unclassified:** 343 Bucket - 2 values are "-" (120 Other Media, not applicable; 223 RCA required). Final Bucket and RCA have no blanks.
- **Cause mapping:** 394 distinct descriptions, none reviewed yet.
- **Trend charts:** none, because there is only one reporting date.
