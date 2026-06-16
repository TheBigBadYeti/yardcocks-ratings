#!/usr/bin/env python3
"""Bank an immutable, dated copy of a ratings run for later backtesting.

A snapshot is the model's PREDICTION at a point in time. It is the historical
record, so it lives in data/snapshots/ -- COMMITTED, never gitignored, never
overwritten. The backtest harness (built later) joins snapshot[t]'s scores
against players' ACTUAL production in the weeks after t, to measure whether
win_now_score predicts next-period points and whether dynasty_score / asset
value track real forward value. That validation is impossible without these
files, and it is time-gated: you cannot snapshot a week that has already passed.
So run this after every ratings build, starting now.

    python scripts/snapshot.py --ratings data/processed/current_player_ratings.csv

Snapshots are immutable by design: re-running on the same date refuses to
overwrite (use --date to tag intentionally, e.g. backfilling).
"""
import argparse
import datetime
import hashlib
import os
import shutil
import pandas as pd

SNAP_DIR = "data/snapshots"
MANIFEST = os.path.join(SNAP_DIR, "manifest.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--date", default=datetime.date.today().isoformat(),
                    help="snapshot date tag (default: today, ISO format)")
    ap.add_argument("--label", default="weekly",
                    help="free-text tag, e.g. weekly / deadline / preseason")
    a = ap.parse_args()

    if not os.path.exists(a.ratings):
        raise SystemExit(f"[snapshot] ratings file not found: {a.ratings}")
    os.makedirs(SNAP_DIR, exist_ok=True)
    dst = os.path.join(SNAP_DIR, f"ratings_{a.date}.csv")
    if os.path.exists(dst):
        raise SystemExit(
            f"[snapshot] {dst} already exists; snapshots are immutable.\n"
            f"            Pass --date to tag a different day if this is intentional.")

    df = pd.read_csv(a.ratings)
    shutil.copyfile(a.ratings, dst)
    sha = hashlib.md5(open(dst, "rb").read()).hexdigest()[:10]
    row = pd.DataFrame([{
        "date": a.date, "label": a.label, "file": os.path.basename(dst),
        "players": len(df),
        "has_asset_value": "asset_value" in df.columns,
        "md5": sha,
    }])
    if os.path.exists(MANIFEST):
        row = pd.concat([pd.read_csv(MANIFEST), row], ignore_index=True)
    row.to_csv(MANIFEST, index=False)
    print(f"[snapshot] wrote {dst}  ({len(df)} players)")
    print(f"[snapshot] manifest -> {MANIFEST}  ({len(row)} snapshots banked)")
    print("[snapshot] commit data/snapshots/ so the record is durable.")


if __name__ == "__main__":
    main()
