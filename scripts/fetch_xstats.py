#!/usr/bin/env python3
"""
fetch_xstats.py - Statcast expected stats from Baseball Savant (free, no key).

WHY: the predictive backtest showed our scores add nothing beyond surface production
and the market. Expected stats (xwOBA, xBA, xSLG, xERA) exist precisely because they
predict FUTURE performance better than actuals. This is the raw material for a
projection that can beat the market. Savant also carries MLB player_id, which ends
our name-only joins.

WRITES BOTH a latest file and a DATED copy. The dated copies are the point: no history
of these inputs existed, so nothing built on them could ever be backtested. From now on
every fetch is a future validation window. Runs daily in the GitHub Action.

  data/xstats/hitters_latest.csv      data/xstats/hitters_YYYY-MM-DD.csv
  data/xstats/pitchers_latest.csv     data/xstats/pitchers_YYYY-MM-DD.csv
"""
import datetime as dt
import io
import os
import sys
import urllib.request

import pandas as pd

OUT = "data/xstats"
YEAR = dt.date.today().year
UA = {"User-Agent": "Mozilla/5.0 (yardcocks-ratings; free public leaderboard)"}
URL = ("https://baseballsavant.mlb.com/leaderboard/expected_statistics"
       "?type={kind}&year={year}&position=&team=&min={minpa}&csv=true")


def fetch(kind, minpa):
    url = URL.format(kind=kind, year=YEAR, minpa=minpa)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        raw = r.read().decode("utf-8-sig", errors="ignore")
    d = pd.read_csv(io.StringIO(raw))
    # "last_name, first_name" -> a join-friendly "First Last"
    nm = d.columns[0]
    d["name"] = d[nm].astype(str).str.split(",").map(
        lambda p: f"{p[1].strip()} {p[0].strip()}" if len(p) == 2 else p[0].strip())
    d = d.rename(columns={"player_id": "mlbam_id"})
    d["fetched"] = dt.date.today().isoformat()
    return d


def main():
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today().isoformat()
    for kind, minpa in (("batter", 25), ("pitcher", 25)):
        label = "hitters" if kind == "batter" else "pitchers"
        try:
            d = fetch(kind, minpa)
        except Exception as e:
            print(f"[xstats] {label} fetch FAILED ({e}); leaving prior files", file=sys.stderr)
            continue
        d.to_csv(os.path.join(OUT, f"{label}_latest.csv"), index=False)
        d.to_csv(os.path.join(OUT, f"{label}_{today}.csv"), index=False)
        print(f"[xstats] {label}: {len(d)} players, cols={list(d.columns)[:8]}...")
    print(f"[xstats] wrote latest + dated ({today}) copies to {OUT}/")


if __name__ == "__main__":
    main()
