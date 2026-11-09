# Phase 2: data-quality issues found by the replay

These come from the 4G Saturation replay of September–October 2026 (throwaway database) and the matrix load. Every
record is in `import-exceptions.csv`. Nothing was corrected, guessed or capped; each item needs a source fix or a
decision.

## Consolidation Matrix (`Consolidated Escalation Matrix _Oct'26.xlsx`)

| Issue | Count | Effect under the approved rules | Needed |
|---|---|---|---|
| O&M Start Date missing (dashboard sites) | 522 (490 4G, 32 LWE) | Not O&M Start in any month; flagged for review | Add the dates in the matrix |
| … of which O&M Start in the October Uptime Master | **78 MP sites** (e.g. UVMPBLG00002, UVMPBLG00039, UVMPBLG00040) | Excluded from October O&M: new 4,052 vs live / Excel 4,130 O&M sites, 91.0682% vs 91.0915% O&M availability | The matrix is dated 28 Oct and has blank O&M status and date for them. Update the matrix if they started O&M in October |
| Site On-Air Date missing | 318 (305 4G) | Not On-Air in any month; flagged for review | Add the dates |
| … of which On-Air in the Uptime Master | **12** (6 MP, 6 OD) | Excluded from On-Air in Sep and Oct (live counts them through the Uptime On-Air column) | Update the matrix |
| Band IDs claimed by more than one site | **436** (241 B28 / 700 MHz, 195 B1 / 2100 MHz; 337 on two sites, 99 on three; 239 among 4G sites, 197 among LWE sites). Example: `T4OD28BRBERP9R35sa` on UVORBPR00305 and UVORBPR00350 | Assigned to no site and blocked for every importer; the sites themselves are imported | Correct the band IDs in the matrix |

## Uptime Master workbooks

| Issue | Where | Effect | Needed |
|---|---|---|---|
| Sites not in the matrix | `UVRJJPR00057`, `UVRJUPR00612` (RJ): 30 Sep + 31 Oct site-days each | Unmatched, excluded (Sep 60, Oct 62 site-days); no master record created | Add them to the matrix through the master-data process, or confirm they are out of scope |
| Outage above 1,440 minutes | `UVRJSGR00104`, 16 Sep 2026, 1,457.47 min (row 2240 of the Sep workbook) | Rejected, not capped. RJ O&M September 93.3659% instead of the workbook's 93.3635% | Correct the source value |
| Site attributes differ from the matrix | Sep / Oct: IE name 1,590 / 1,591, OA 907 / 908, BA 896 / 897, CI name 232 / 233, site name 13 / 13, On-Air 4 / 26 | Matrix value kept (approved rule) | Informational; most are naming or format differences |
| O&M Start flags differ from the matrix date | Oct: 78 (the MP sites above) | Flags not used (approved rule) | See matrix O&M dates |

## CNMC raw CSVs vs the October Uptime Master (RJ)

| Issue | Count | Detail |
|---|---|---|
| Value conflicts | **1,531**: RJ 424 (25 Oct), 423 (26 Oct), 683 (27 Oct); OD 1 (13 Oct) | Resolved by the confirmed precedence: the Uptime Master value is kept, every CSV value is logged with its file and upload |
| Size | median 0.21 min, 90th percentile 46.74 min, maximum 1,439.98 min; 1,291 differ by under 1 minute | The workbook writes RJ outage rounded (e.g. 1.5 vs CNMC 1.44, 1.0 vs 0.576 minutes on 27 Oct). The larger ones are real differences |
| Direction | workbook higher 830, CNMC higher 701 | |

This is the same set as the 1,531 values the old import overwrote (Phase 1 audit).

**Resolved (4 Nov):** the Uptime Master is authoritative where both sources have a value. The rule is explicit source
precedence (`daily.SOURCE_RANK`), not import order:
- A CSV loaded after the workbook is logged as a conflict.
- A workbook loaded after a CSV supersedes it, and the replaced CSV value stays in the log.

## Raw CSV files

| Issue | File | Detail |
|---|---|---|
| Wrong circle at upload | `raw_uploads/2026-10-13/4_044d3ab3dbc7.csv` | A Jharkhand (JH) dump uploaded as MP / OD. All 817 rows rejected as `other_circle`; belongs to the LWE replay |
| LWE-only circle dump | `raw_uploads/2026-10-25/19_d2d15f4e89f8.csv` (AP, 63 rows; also staged under 2026-11-01) | Held back with the LWE replay |
| Same file uploaded several times | e.g. `5/6/7_6dd1c7654e5d` (OD 13 Oct), `8/9/12_46719afd9394` (RJ 25 Oct) | Each unique file imported once |

## LWE (mapping and raw rows, preliminary: mapping read from the Downloads copy)

Mapping workbook details: `lwe-mapping-quality.md`.

| Issue | Count | Detail |
|---|---|---|
| Mapping row with a single `;` between two 700 IDs | 1 | LWEBH0141 (row 1074). Rejected; not split |
| LWE sites without a mapping row | 188 of 2,182 | Their dump rows match only if the BTS IP ID is their own Master ID |
| Dump rows whose BTS IP ID is not in the mapping but whose band IDs are | 47 per OD dump, 6 per MP dump | **Now accepted** by the confirmed rule (the BTS IP ID is not mandatory when absent from the mapping) |
| `…sa;;…lw` band cells: the `lw` ID is in the mapping, the `sa` ID is not | 1 row per OD dump (OD9RBOLLWE1597) | Rejected (`identifier_not_in_mapping`): every identifier must match |
| AP site whose 2100 / 700 IDs differ from the mapping | 1 (BTS IP ID 16059017, AP 25 Oct) | Rejected (`identifier_not_in_mapping`) |
| Mapping inconsistency | BLG1394 (MP): the 2100 ID maps to LWEMP1663, the 700 ID to another Master ID | Rejected (`identifier_mismatch`) in both MP dumps; the mapping needs correcting |
| One site on two dump rows with different values | LWEOD1896 (BTS IP IDs `LWE_1569` and `OD9RJJPLWE1569`), 13 and 27 Oct; one more pair on 27 Oct | All rows of that site rejected (`conflicting_rows`) |
| Single `;` in a dump band cell | 44 rows; 43 of them name no known site (other BTS of the circle) | 43 are unmatched like any other non-project row; the 1 touching LWEJH1243 (JH 13 Oct) is rejected (`invalid_identifier`) |
