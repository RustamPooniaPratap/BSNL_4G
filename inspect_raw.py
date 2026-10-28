"""
inspect_raw.py
Read-only inspection of a raw CNMC CSV. Does not modify any file.

Usage (from project root, venv active):
    python inspect_raw.py
    python inspect_raw.py "data/raw/some_other_file.csv"
"""

import sys
from pathlib import Path

import pandas as pd

RAW_DIR = Path("Data") / "raw"

# Keywords used only to SUGGEST candidate columns. They decide nothing.
ID_HINTS = ["site", "bts", "ip id", "id"]
AVAIL_HINTS = ["avail", "aval", "uptime", "up time"]
DATE_HINTS = ["date", "day", "month", "period", "time"]


def pick_file() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {RAW_DIR.resolve()}")
    if len(files) > 1:
        print("Multiple CSVs found, using the first one. Pass a path to choose:")
        for f in files:
            print("   ", f.name)
    return files[0]


def candidates(columns, hints):
    return [c for c in columns if any(h in str(c).lower() for h in hints)]


def main():
    path = pick_file()
    print("=" * 70)
    print("FILE:", path.name)
    print("=" * 70)

    # dtype=str on a separate read so we see the raw text exactly as exported
    # (no silent conversion of IDs like 00123 -> 123).
    df = pd.read_csv(path)
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)

    print(f"\nRows: {len(df):,}   Columns: {df.shape[1]}")

    print("\n--- ALL COLUMNS (index, name, pandas dtype, non-null, unique) ---")
    for i, col in enumerate(df.columns):
        print(f"{i:>3}  {col!r:<45} {str(df[col].dtype):<10} "
              f"{df[col].notna().sum():>6}  {df[col].nunique(dropna=True):>6}")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 30)
    print("\n--- FIRST 5 ROWS (as raw text) ---")
    print(raw.head(5).T.to_string())  # transposed: 62 columns are unreadable side by side

    print("\n--- CANDIDATE COLUMNS (keyword match only, NOT confirmed) ---")
    print("Site ID     :", candidates(df.columns, ID_HINTS))
    print("Availability:", candidates(df.columns, AVAIL_HINTS))
    print("Date/period :", candidates(df.columns, DATE_HINTS))

    print("\n--- DETAIL FOR CANDIDATE COLUMNS ---")
    shown = set()
    for col in (candidates(df.columns, ID_HINTS)
                + candidates(df.columns, AVAIL_HINTS)
                + candidates(df.columns, DATE_HINTS)):
        if col in shown:
            continue
        shown.add(col)
        s = df[col]
        print(f"\n[{col}]  dtype={s.dtype}  nulls={s.isna().sum()}  unique={s.nunique()}")
        print("  sample values:", s.dropna().unique()[:6].tolist())
        if pd.api.types.is_numeric_dtype(s):
            print(f"  min={s.min()}  max={s.max()}  mean={s.mean():.4f}")

    print("\nDone. Nothing was written or modified.")


if __name__ == "__main__":
    main()