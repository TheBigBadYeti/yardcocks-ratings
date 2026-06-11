#!/usr/bin/env python3
"""
identify_exports.py — map Fantrax CSV exports to engine flags by HEADER CONTENT.

The Fantrax `__N_` filename suffix reflects only download order and shifts between
export batches, so it must never be trusted. This script inspects each file's
header and classifies it by signature, then prints a ready-to-run engine command.

Signatures (verified):
  - "Roster Status" column present  -> rostered family; absent -> free-agent family
  - "IP" column present             -> pitcher split file
  - hitter component cols (AB/HR/RBI/SB) present, no IP -> hitter split file
  - ~11 cols, no component stats     -> combined no-stats export (ignored)

Usage:  python3 scripts/identify_exports.py [raw_dir]   (default: data/raw)
"""
import os
import sys
import glob
import pandas as pd

RAW = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
HITTER_MARKERS = {"AB", "HR", "RBI", "SB", "1B", "2B"}
PITCHER_MARKERS = {"IP", "ER", "QS", "SV", "HLD", "ERA"}


def classify(path):
    try:
        cols = set(pd.read_csv(path, nrows=0).columns)
    except Exception as e:
        return None, f"unreadable ({e})"
    rostered = "Roster Status" in cols
    is_pitcher = "IP" in cols and len(PITCHER_MARKERS & cols) >= 2
    is_hitter = (not is_pitcher) and len(HITTER_MARKERS & cols) >= 3
    fam = "rostered" if rostered else "fa"
    if is_pitcher:
        return f"{fam}-pitchers", None
    if is_hitter:
        return f"{fam}-hitters", None
    # multi-section team roster export (has Hitting/Pitching section rows)
    base = os.path.basename(path).lower()
    if "team" in base and "roster" in base:
        return "team-roster", None
    if "standings" in base:
        return "standings", None
    return "combined/ignore", None


def main():
    files = sorted(glob.glob(os.path.join(RAW, "*.csv")))
    if not files:
        print(f"No CSVs in {RAW}/ — drop the Fantrax exports there first.")
        return
    found = {}
    print(f"Scanning {RAW}/ by header signature:\n")
    for f in files:
        role, err = classify(f)
        tag = err or role
        print(f"  {os.path.basename(f):55} -> {tag}")
        if role in {"rostered-hitters", "rostered-pitchers",
                    "fa-hitters", "fa-pitchers", "team-roster"} and role not in found:
            found[role] = f

    need = ["rostered-hitters", "rostered-pitchers", "fa-hitters", "fa-pitchers"]
    missing = [n for n in need if n not in found]
    print()
    if missing:
        print(f"!! Missing required split files: {missing}")
        print("   Check the exports — you need all four split (stats) files.")
        return
    tr = found.get("team-roster", "data/raw/team_roster_real.csv")
    print("Verified run command:\n")
    print("python3 inseason_ratings_engine.py \\")
    print(f"  --rostered-hitters  {found['rostered-hitters']} \\")
    print(f"  --rostered-pitchers {found['rostered-pitchers']} \\")
    print(f"  --fa-hitters        {found['fa-hitters']} \\")
    print(f"  --fa-pitchers       {found['fa-pitchers']} \\")
    print(f"  --team-roster       {tr} \\")
    print("  --outdir data/processed --mode faithful --team Kipp")


if __name__ == "__main__":
    main()
