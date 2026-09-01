#!/usr/bin/env python3
"""
backtest_predictive.py - does the model PREDICT anything? (the roadmap's missing #3)

The aging/attrition curves were validated against real cohorts, but the scores that
actually drive decisions -- win_now_score, dynasty_score, forward_fpg -- were never
tested for forward predictive power. This does that with the dated snapshots.

For a pair of snapshots (t -> t2), a player's FUTURE production is what he scored in
between: future_pts = fpts[t2] - fpts[t]; future_fpg = future_pts / games in between.
We then rank-correlate (Spearman) each predictor observed at t against that future:

  predictors : win_now_score, dynasty_score, forward_fpg, fpg_regressed,
               fpts (naive 'past production'), rkov (the MARKET's rank), ros_pct
  targets    : future_pts (volume), future_fpg (rate)

The bar that matters: does our score beat rkov (what the market already knew) and beat
naive past-fpts? If not, the model adds no edge and decisions built on it inherit that.

    python scripts/backtest_predictive.py --from 2026-06-16 --to 2026-08-02
    python scripts/backtest_predictive.py --all      # every snapshot -> latest
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

SNAP = "data/snapshots"
PREDICTORS = ["win_now_score", "dynasty_score", "forward_fpg", "fpg_regressed",
              "fpts", "rkov_inv", "ros_pct"]
MIN_GAMES = 10          # need real playing time between snapshots to score a rate


def load(date):
    p = os.path.join(SNAP, f"ratings_{date}.csv")
    if not os.path.exists(p):
        sys.exit(f"[backtest] no snapshot {p}")
    d = pd.read_csv(p, encoding="utf-8", low_memory=False)
    for c in ["fpts", "estimated_games", "win_now_score", "dynasty_score", "forward_fpg",
              "fpg_regressed", "rkov", "ros_pct"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def pair(t, t2, role=None):
    a, b = load(t), load(t2)
    key = ["player", "role"]
    a = a.drop_duplicates(key).set_index(key)
    b = b.drop_duplicates(key).set_index(key)
    j = a.join(b[["fpts", "estimated_games"]], rsuffix="_2", how="inner")
    j["future_pts"] = j["fpts_2"] - j["fpts"]
    j["future_g"] = j["estimated_games_2"] - j["estimated_games"]
    j = j[(j["future_g"] >= MIN_GAMES) & (j["future_pts"].notna())]
    j["future_fpg"] = j["future_pts"] / j["future_g"]
    j["rkov_inv"] = -j["rkov"]                       # lower rank = better -> flip sign
    if role:
        j = j[j.index.get_level_values("role").isin(role)]
    return j


def spearman(x, y):
    m = x.notna() & y.notna()
    if m.sum() < 30:
        return np.nan, int(m.sum())
    return float(x[m].rank().corr(y[m].rank())), int(m.sum())


def report(t, t2, roles, label):
    j = pair(t, t2, roles)
    if j.empty:
        print(f"  ({label}: no rows)")
        return
    print(f"\n  [{label}]  n={len(j)} players with >= {MIN_GAMES} games in window")
    print(f"  {'predictor @ t':<16} {'-> future_pts':>14} {'-> future_fpg':>14}")
    rows = []
    for p in PREDICTORS:
        if p not in j.columns:
            continue
        r1, n = spearman(j[p], j["future_pts"])
        r2, _ = spearman(j[p], j["future_fpg"])
        rows.append((p, r1, r2))
    for p, r1, r2 in rows:
        print(f"  {p:<16} {r1:>14.3f} {r2:>14.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="t")
    ap.add_argument("--to", dest="t2")
    ap.add_argument("--all", action="store_true", help="every snapshot -> the latest")
    a = ap.parse_args()

    snaps = sorted(f[8:18] for f in os.listdir(SNAP)
                   if f.startswith("ratings_") and f.endswith(".csv"))
    pairs = ([(a.t, a.t2)] if a.t and a.t2
             else [(s, snaps[-1]) for s in snaps[:-1]] if a.all
             else [(snaps[0], snaps[-1])])

    print("Spearman rank correlation of predictor (observed at t) vs what the player "
          "actually produced between t and t2.\nHigher = more predictive. Compare our "
          "scores to rkov_inv (the market) and fpts (naive past production).")
    for t, t2 in pairs:
        print(f"\n=== {t} -> {t2} ===")
        report(t, t2, None, "ALL")
        report(t, t2, ["H"], "HITTERS")
        report(t, t2, ["SP", "SP/RP", "RP"], "PITCHERS")


if __name__ == "__main__":
    main()
