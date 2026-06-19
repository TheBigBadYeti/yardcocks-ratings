#!/usr/bin/env python3
"""
backtest_cohort.py - aging decline measured on an unbiased cohort.

Reads data/career/cohort.csv (fetch_cohort.py) and, by age-at-base, reports:
  survive%   - share of the cohort still logging a real line `gap` years later
  surv_ret   - retention among SURVIVORS only (fpg_plus / fpg_base) -- the biased
               view the old career-pool backtest was stuck with
  pop_ret    - retention across the WHOLE cohort, washouts counted as 0 -- the
               honest population number
  curve_ret  - what the model's aging curve implies over the same span

The decision rule:
  pop_ret ~ curve_ret      -> curve is calibrated for the population (keep it)
  pop_ret > curve_ret      -> curve too steep (real evidence to flatten)
  pop_ret < curve_ret      -> curve too gentle

Because the asset model holds games-per-year fixed, the rate curve is the only
place aging lives, so it must match pop_ret (rate decline AND attrition), not
surv_ret. The gap between surv_ret and pop_ret is the survivorship illusion made
explicit -- if they're far apart, any backtest that dropped washouts was lying.

    python scripts/backtest_cohort.py --cohort data/career/cohort.csv
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dynasty_asset as da   # curve

AGE_BUCKETS = [(0, 23, "<=23"), (24, 27, "24-27"), (28, 30, "28-30"),
               (31, 33, "31-33"), (34, 36, "34-36"), (37, 99, "37+")]


def bucket(age):
    for lo, hi, lab in AGE_BUCKETS:
        if lo <= age <= hi:
            return lab
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="data/career/cohort.csv")
    ap.add_argument("--group", choices=["both", "hitting", "pitching"], default="both")
    ap.add_argument("--min-fpg-base", type=float, default=0.5,
                    help="drop near-zero base lines so retention ratios are meaningful")
    ap.add_argument("--min-games-base", type=float, default=0.0,
                    help="entry floor on base-year games -- raise it (e.g. 100 hitters, "
                         "40+ pitchers) to isolate REGULARS from the MLB fringe, whose "
                         "attrition is talent level, not aging")
    ap.add_argument("--drop-plus-years", default="",
                    help="comma list of plus-years to exclude (e.g. 2020 for COVID)")
    a = ap.parse_args()

    df = pd.read_csv(a.cohort)
    if a.group != "both":
        df = df[df["group"] == a.group]
    for col in ("age_base", "fpg_base", "fpg_plus", "played_plus", "gap",
                "games_base", "base_year"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[(df["age_base"].notna()) & (df["fpg_base"] > a.min_fpg_base)
            & (df["games_base"] >= a.min_games_base)].copy()
    if a.drop_plus_years:
        drop = {int(x) for x in a.drop_plus_years.split(",")}
        df = df[~(df["base_year"] + df["gap"]).isin(drop)]
    if df.empty:
        raise SystemExit("[cohort] no usable rows (check fetch + filters)")
    gap = int(df["gap"].mode().iloc[0])
    df["is_p"] = df["group"].astype(str).str.startswith("p")
    print(f"[cohort] {len(df)} player-cohort rows, gap={gap}y, "
          f"base years {sorted(df['base_year'].astype(int).unique())}, group={a.group}, "
          f"min_games_base={a.min_games_base:g}")

    df["ret"] = df["fpg_plus"] / df["fpg_base"]          # washout -> 0
    df["curve_ret"] = [da.curve(ag + gap, ip) / da.curve(ag, ip)
                       if da.curve(ag, ip) > 0 else np.nan
                       for ag, ip in zip(df["age_base"], df["is_p"])]
    df["bucket"] = df["age_base"].map(bucket)

    print(f"\n[retention over {gap} years, by age at base]")
    print(f"  {'bucket':8s} {'n':>5s} {'survive%':>9s} {'surv_ret':>9s} "
          f"{'pop_ret':>8s} {'curve':>7s}   verdict")
    overall = []
    for lo, hi, lab in AGE_BUCKETS:
        b = df[df["bucket"] == lab]
        if len(b) < 5:
            continue
        surv = b["played_plus"].mean()
        surv_ret = b.loc[b["played_plus"] == 1, "ret"].mean()
        pop_ret = b["ret"].mean()
        curve_ret = b["curve_ret"].mean()
        diff = pop_ret - curve_ret
        verdict = ("curve ~right" if abs(diff) < 0.05
                   else "curve TOO STEEP" if diff > 0 else "curve too gentle")
        overall.append((lab, pop_ret, curve_ret))
        print(f"  {lab:8s} {len(b):>5d} {surv * 100:>8.0f}% {surv_ret:>9.2f} "
              f"{pop_ret:>8.2f} {curve_ret:>7.2f}   {verdict}")

    if overall:
        pr = np.array([o[1] for o in overall])
        cr = np.array([o[2] for o in overall])
        mae = np.mean(np.abs(pr - cr))
        bias = np.mean(pr - cr)
        print(f"\n[curve vs population]  MAE={mae:.3f}  mean(pop-curve)={bias:+.3f}")
        print("  bias > 0  -> curve steeper than reality (flatten);  "
              "< 0 -> too gentle;  ~0 -> calibrated")
    print("\n[note] surv_ret vs pop_ret is the survivorship gap. Where pop_ret is "
          "far below surv_ret, dropping washouts (the old backtest) overstated how "
          "well that age holds value.")


if __name__ == "__main__":
    main()
