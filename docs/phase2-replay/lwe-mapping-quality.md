# LWE Band ID mapping: quality report (4 Nov 2026)

Source: `Data/reference/LWE Band ID.xlsx` (SHA-256 `9b5ad5cd…`, the same file as the earlier Downloads copy).
- The workbook was imported by the database-backed importer (`apps/sitedata/bandmap.py`) into a throwaway SQLite
  database only; the workbook itself was not changed.
- Nothing was written to the live database.

Row-level exceptions: `lwe-mapping-exceptions.csv`.

## Structure

| Check | Result |
|---|---|
| Sheet | `Sheet1` (also `Sheet2`: a pivot of counts per circle, not read) |
| Headers | All five expected: Circle, BTS IP ID, BTS Site ID (2100), BTS Site ID (700), btsIpId -Master ID; none missing |
| Data rows | 1,996 |

## Contents

| Check | Result |
|---|---|
| Blank cells | BTS IP ID 0; **2100: 42** (33 empty + 9 written "-"); **700: 6** (all written "-"); Master ID 0; Circle 0 |
| Placeholder cells ("-") | 2100: 9, 700: 6, all on UP rows 881–895. Read as empty cells, as the existing workbook parser does |
| Cells with several IDs joined by `;;` | 0 |
| Cells with another separator | **1**: row 1074, LWEBH0141 (BH), 700 = `T4BR28BGBGHP09WE1910lw;T4BR28BGKTHP09KAH009` (single `;`). Row rejected (`invalid_identifier`); not split |
| Identifiers on rows of different Master IDs | 0 |
| Master IDs on several rows | 0 |
| Identical repeated rows | 1 (counted as a duplicate) |
| Missing Master IDs | 0 |
| Circle mismatches (mapping circle vs matrix circle) | 0 |
| Master IDs not LWE sites / not in the matrix | 0 / 0 |
| Identifiers ambiguous in the matrix | 0 |

Correction to my previous report: the "15 duplicate identifiers" were these 15 "-" placeholders read as one shared
identifier. With placeholders read as empty, every one of those rows is accepted.

## Result

| | Count |
|---|---|
| Rows accepted | **1,994** |
| Rows rejected | **1** (LWEBH0141, single `;`) |
| Identical repeats | 1 |
| Identifiers created | 5,930 |
| LWE sites mapped | 1,994 of 2,182 |
| LWE sites without any mapping row | **188**. Their raw CSV rows can match only through the BTS IP ID being their own Master ID |

## Needed in the source

1. Write row 1074's two 700 MHz IDs separated by `;;`, or confirm which one is correct.
2. Provide mapping rows for the 188 LWE sites without any, if they report in the CNMC dumps.
3. Optional: use empty cells instead of "-".
