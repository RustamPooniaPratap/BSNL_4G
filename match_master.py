"""
match_master.py
Read-only: match a daily raw CSV against the Master Sheet (Up-Time Report)
and print matched / missing / unexpected counts. Writes nothing.

Usage (project root, venv active):
    python match_master.py
"""

import sys
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data") / "raw"
REF_DIR = Path("data") / "reference"

MASTER_SHEET = "Up-Time Report"
MASTER_HEADER_ROW = 1          # zero-based: headers are on Excel row 2
PROJECT = "4G Satu."
CIRCLE = "MP"

RAW_ID = "BTS IP ID"
RAW_AVAIL = "Nw Avail (4G TCS)"
RAW_DATE = "Report Date"
NEW_SITE_PREFIX = "UV"         # proposed rule, awaiting confirmation


def first_file(folder: Path, pattern: str) -> Path:
    files = [f for f in sorted(folder.glob(pattern)) if not f.name.startswith("~$")]
    if not files:
        sys.exit(f"No {pattern} file found in {folder.resolve()}")
    return files[0]


def main():
    master_path = first_file(REF_DIR, "*.xlsx")
    raw_path = first_file(RAW_DIR, "*_day_*.csv")
    print("MASTER:", master_path.name)
    print("RAW   :", raw_path.name)

    # --- Master (this can take 10-30 seconds) ---
    m = pd.read_excel(master_path, sheet_name=MASTER_SHEET,
                      header=MASTER_HEADER_ROW,
                      usecols=["Project", "Circle", "btsIpId", "On-Air"])
    m = m.dropna(subset=["btsIpId"])
    m["btsIpId"] = m["btsIpId"].astype(str).str.strip()
    master = m[(m["Project"].astype(str).str.strip() == PROJECT)
               & (m["Circle"].astype(str).str.strip() == CIRCLE)]
    master_ids = set(master["btsIpId"])

    # --- Raw: read only the columns we need ---
    raw = pd.read_csv(raw_path, usecols=[RAW_ID, RAW_AVAIL, RAW_DATE])
    raw[RAW_ID] = raw[RAW_ID].astype(str).str.strip()
    dates = pd.to_datetime(raw[RAW_DATE].str.strip(), format="%d-%m-%Y", errors="coerce")
    raw_ids = set(raw[RAW_ID])

    matched = raw[raw[RAW_ID].isin(master_ids)]
    unmatched = raw[~raw[RAW_ID].isin(master_ids)]
    uv_unmatched = unmatched[unmatched[RAW_ID].str.startswith(NEW_SITE_PREFIX)]
    missing = master[~master["btsIpId"].isin(raw_ids)]

    print(f"\nReport date(s) in file : {[str(d.date()) for d in dates.dropna().unique()]}"
          f"  (unparseable: {int(dates.isna().sum())})")
    print(f"Master {PROJECT} {CIRCLE} sites : {len(master_ids):,}")
    print("  On-Air breakdown     :", master["On-Air"].value_counts(dropna=False).to_dict())
    print(f"Raw rows               : {len(raw):,}  (duplicate IDs: {int(raw[RAW_ID].duplicated().sum())})")

    print(f"\nMATCHED                : {len(matched):,}")
    print(f"  blank availability   : {int(matched[RAW_AVAIL].isna().sum())}")
    print(f"  outside 0-100        : {int(((matched[RAW_AVAIL] < 0) | (matched[RAW_AVAIL] > 100)).sum())}")

    print(f"\nMASTER SITES MISSING FROM RAW : {len(missing):,}")
    print("  On-Air breakdown     :", missing["On-Air"].value_counts(dropna=False).to_dict())

    print(f"\nRAW IDs NOT IN MASTER  : {len(unmatched):,}")
    print(f"  starting '{NEW_SITE_PREFIX}' (potential new sites): {len(uv_unmatched)}")
    print(f"  other (ignored, not 4G Saturation)    : {len(unmatched) - len(uv_unmatched):,}")
    if len(uv_unmatched):
        print("  potential new site IDs:", uv_unmatched[RAW_ID].head(10).tolist())

    print("\nDone. Nothing was written or modified.")


if __name__ == "__main__":
    main()