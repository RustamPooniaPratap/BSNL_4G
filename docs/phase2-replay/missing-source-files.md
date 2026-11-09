# Phase 2 replay: missing source files

Checked on 4 Nov 2026, read-only. The **4G Saturation replay has been run** (see `historical-replay-summary.md`).
The **LWE replay is held back** until the mapping file below is in the project.

## Required in the project but missing

| File | Needed for | Where it is now | Action |
|---|---|---|---|
| `LWE Band ID.xlsx` (Circle, BTS IP ID, BTS Site ID (2100), BTS Site ID (700), btsIpId -Master ID) | Every LWE identifier match; LWE raw CSV replay | Only `C:\Users\<user>\Downloads\LWE Band ID.xlsx`; an Excel lock file next to it suggests it is open | Copy into `Data/reference/` (close it in Excel first). The LWE replay is blocked until then. |
| `LWE Uptime Report - Oct'26.xlsx` | October LWE daily values (LWE replay) | In Downloads. A byte-identical copy (same SHA-256, `5ca7396c…`) is staged as `Data/processed/imports/20261103-161246-5ca7396ce0.xlsx` | Usable from the staged copy once the LWE replay runs; copying it into `Data/reference/` is cleaner |
| `RJ MP  OD - Uptime Report- Oct-26 (003).xlsx` | October RJ/MP/OD daily values (your choice, 4 Nov) | In Downloads. A byte-identical copy (SHA-256 `617c583e…`) is staged as `Data/processed/imports/20261103-160629-617c583e1d.xlsx` | **Used for the 4G replay** from the staged copy |

## Not available for the period (no file anywhere)

| Data | Status |
|---|---|
| September 2026 4G raw CSVs (CNMC dumps) | None in the project or Downloads. September comes only from the Uptime Master workbooks. |
| September 2026 LWE raw CSVs | None. |
| October 2026 LWE raw CSVs (separate LWE uploads) | None. LWE rows exist inside the 4G circle dumps (OD and MP), so they can be imported with LWE technology from the same files once the mapping file is in place. |
| October 2026 4G raw CSVs | Staged copies in `Data/processed/raw_uploads/` only for RJ, OD and MP on 25–27 Oct (and OD 13 Oct, previewed earlier). Other days have no CSV; the Uptime Master workbooks cover them. |

## Present in the project

- `Data/reference/Consolidated Escalation Matrix _Oct'26.xlsx` (Consolidation Matrix)
- `Data/reference/RJ, MP & OD - Uptime Report- Sep-26.xlsx` and `Data/raw/` copy (September 4G Uptime Master)
- `Data/reference/LWE Uptime Report day wise - Sept'26.xlsx` (September LWE day-wise)
- `Data/raw/RJ, MP & OD - Uptime Report- Oct-26.xlsx` (October 4G Uptime Master, version to confirm)
- `Data/raw/` and `Data/reference/4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx` (October consolidated 4G + LWE). It
  overlaps the RJ/MP/OD and LWE October reports; only one October source per site-day should be loaded, to be confirmed.
