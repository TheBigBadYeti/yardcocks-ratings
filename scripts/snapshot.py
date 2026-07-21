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

EXCEPTION -- same-day supersede (--supersede): if you refresh twice in one day
because the first run used stale exports, the dated snapshot would otherwise keep
the SUPERSEDED numbers while current_player_ratings.csv carries the newer ones.
That silently breaks the snapshot's contract (it must equal what you published).
--supersede overwrites the same-day file and REPLACES its manifest row, tagging the
label so the supersede is visible rather than silent. Use it only when the newer run
genuinely replaces the older one on the same date.
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
    ap.add_argument("--supersede", action="store_true",
                    help="overwrite a same-day snapshot because this run replaces it "
                         "(e.g. the earlier run used stale exports)")
    a = ap.parse_args()

    if not os.path.exists(a.ratings):
        raise SystemExit(f"[snapshot] ratings file not found: {a.ratings}")
    os.makedirs(SNAP_DIR, exist_ok=True)
    dst = os.path.join(SNAP_DIR, f"ratings_{a.date}.csv")
    superseded = False
    if os.path.exists(dst):
        if not a.supersede:
            raise SystemExit(
                f"[snapshot] {dst} already exists; snapshots are immutable.\n"
                f"            --supersede if this run REPLACES it (same-day rerun with\n"
                f"            better exports), or --date to tag a different day.")
        superseded = True
        print(f"[snapshot] SUPERSEDING existing {dst} -- the earlier same-day run is "
              f"being replaced by this one.")

    df = pd.read_csv(a.ratings)
    shutil.copyfile(a.ratings, dst)
    sha = hashlib.md5(open(dst, "rb").read()).hexdigest()[:10]
    row = pd.DataFrame([{
        "date": a.date,
        "label": a.label + ("+superseded_earlier_run" if superseded else ""),
        "file": os.path.basename(dst),
        "players": len(df),
        "has_asset_value": "asset_value" in df.columns,
        "md5": sha,
    }])
    if os.path.exists(MANIFEST):
        prior = pd.read_csv(MANIFEST)
        if superseded:                      # replace the stale row, don't duplicate it
            prior = prior[prior["date"].astype(str) != str(a.date)]
        row = pd.concat([prior, row], ignore_index=True)
    row.to_csv(MANIFEST, index=False)
    print(f"[snapshot] wrote {dst}  ({len(df)} players)")
    print(f"[snapshot] manifest -> {MANIFEST}  ({len(row)} snapshots banked)")
    print("[snapshot] commit data/snapshots/ so the record is durable.")


if __name__ == "__main__":
    main()
