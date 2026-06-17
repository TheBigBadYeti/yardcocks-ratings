#!/usr/bin/env python3
"""Retrospective backtest of the career baseline + aging curve.

Validates the projection engine against outcomes we ALREADY have. Hold out the
most recent complete season, build each player's baseline from ONLY the seasons
before it, age it one step forward with the curve, and compare to what the
player actually did in the held-out year. Answers the question we have so far
answered only by face validity: does the aging curve predict, and does aging the
baseline beat naive persistence?

    python scripts/backtest_aging.py \
        --career data/career/career_stats.csv \
        --ratings data/processed/current_player_ratings.csv

Reports:
  - overall prediction error: raw baseline vs regressed (flat) vs regressed+aged.
    If "regressed + aged" beats "regressed (flat)" on MAE/RMSE, the aging curve
    is earning its keep. This headline is robust to the confounds below.
  - aging calibration by age bucket: realized 1-year change vs the curve-implied
    change. Directional only -- it blends true aging with mean reversion (a hot
    year regresses down, a cold year up, regardless of age), so read the SIGN and
    ORDERING across buckets, not the exact percentages.
  - survivorship: players with a baseline but no held-out actual (retired/injured)
    drop out, so the worst late-career collapses are invisible here -- the real
    late-age cliff is likely a bit steeper than the surviving olds show.

Two seasons of prior history is the floor; 5-6 makes the age buckets trustworthy.
The header prints the cache span so you can judge.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dynasty_asset as da   # reuse norm_name, raw_baseline, curve, THIN_GAMES

AGE_BUCKETS = [(0, 23, "<=23"), (24, 27, "24-27"), (28, 30, "28-30"),
               (31, 33, "31-33"), (34, 36, "34-36"), (37, 99, "37+")]


def bucket(age):
    for lo, hi, lab in AGE_BUCKETS:
        if lo <= age <= hi:
            return lab
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--career", default="data/career/career_stats.csv")
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--holdout", type=int, default=None,
                    help="season to predict (default: latest complete season)")
    ap.add_argument("--current-year", type=int, default=2026,
                    help="treated as incomplete; used to back-date ages")
    ap.add_argument("--min-games", type=float, default=20.0,
                    help="min games in the holdout year to count as a real actual")
    a = ap.parse_args()

    cr = pd.read_csv(a.career, encoding="utf-8")
    for col in ("season", "games", "fpg"):
        cr[col] = pd.to_numeric(cr[col], errors="coerce")
    seasons_all = sorted(cr["season"].dropna().unique())
    if not seasons_all:
        raise SystemExit("[backtest] no seasons in career cache")
    print(f"[backtest] career cache spans {int(min(seasons_all))}-{int(max(seasons_all))} "
          f"({len(seasons_all)} seasons)")

    complete = [s for s in seasons_all if s < a.current_year]
    Y = a.holdout or (int(max(complete)) if complete else int(max(seasons_all)))
    prior = [s for s in seasons_all if s < Y]
    if not prior:
        raise SystemExit(f"[backtest] no seasons before holdout {Y}; cache too shallow")
    print(f"[backtest] holdout = {Y}; baseline from {int(min(prior))}-{Y - 1}")

    rt = pd.read_csv(a.ratings, encoding="utf-8")
    rt["k"] = rt["player"].map(da.norm_name)
    age_now = dict(zip(rt["k"], pd.to_numeric(rt["age"], errors="coerce")))
    role_of = dict(zip(rt["k"], rt["role"].astype(str)))

    cr["k"] = cr["name"].map(da.norm_name)
    rows, dropped = [], 0
    for k, g in cr.groupby("k"):
        gp = g[g["season"] < Y]
        gh = g[g["season"] == Y]
        an_age = age_now.get(k)
        if gp.empty or gh.empty or an_age is None or pd.isna(an_age):
            dropped += 1
            continue
        if gh["games"].sum() < a.min_games:
            dropped += 1
            continue
        seasons = list(zip(gp["season"].astype(int), gp["games"].astype(float),
                           gp["fpg"].astype(float)))
        base, tg = da.raw_baseline(seasons)
        # effective anchor age of the baseline: the same recency*games weighting
        # raw_baseline uses, applied to each prior season's age. The aged
        # predictor must step from HERE to the holdout year, not from age-1.
        last3 = sorted(seasons, key=lambda x: x[0], reverse=True)[:3]
        aw = an_num = ad = 0.0
        for i, (s, gms, _) in enumerate(last3):
            w = da.RECENCY_W[i] * gms
            an_num += w * (float(an_age) - (a.current_year - s))
            ad += w
        anchor_age = an_num / ad if ad else float(an_age) - 1
        actual = float((gh["fpg"] * gh["games"]).sum() / max(gh["games"].sum(), 1e-9))
        role = role_of.get(k, "H")
        age_Y = float(an_age) - (a.current_year - Y)   # age entering the holdout year
        rows.append({"role": role, "is_p": role != "H", "age_Y": age_Y,
                     "anchor_age": anchor_age, "games": tg, "raw_base": base,
                     "actual": actual})

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("[backtest] no testable players (check the ratings/career name join)")
    print(f"[backtest] {len(df)} players testable; {dropped} dropped "
          "(no prior, no/low holdout line, or no age)")

    role_med = df.groupby("role")["raw_base"].median().to_dict()

    def reg(r):
        thin = da.THIN_GAMES.get(r["role"], 200)
        conf = min(r["games"] / thin, 1.0)
        return r["raw_base"] * conf + role_med.get(r["role"], 0.0) * (1 - conf)

    df["reg_base"] = df.apply(reg, axis=1)

    def aged(base, anchor_age, age_Y, is_p):
        cm = da.curve(anchor_age, is_p)
        return base * (da.curve(age_Y, is_p) / cm) if cm > 0 else base

    df["pred_raw_flat"] = df["raw_base"]
    df["pred_flat"] = df["reg_base"]
    df["pred_aged"] = [aged(b, an, ay, ip)
                       for b, an, ay, ip in zip(df["reg_base"], df["anchor_age"],
                                                df["age_Y"], df["is_p"])]
    for col in ("pred_raw_flat", "pred_flat", "pred_aged"):
        df[col + "_ae"] = (df[col] - df["actual"]).abs()

    def line(name, col):
        e = df[col + "_ae"]
        print(f"  {name:20s} MAE={e.mean():6.3f}  RMSE={np.sqrt((e ** 2).mean()):6.3f}")

    print("\n[overall error vs actual holdout FP/G]  (lower = better)")
    line("raw baseline", "pred_raw_flat")
    line("regressed (flat)", "pred_flat")
    line("regressed + aged", "pred_aged")
    win = "aged" if df["pred_aged_ae"].mean() < df["pred_flat_ae"].mean() else "flat"
    print(f"  -> aging {'HELPS' if win == 'aged' else 'does NOT help'} "
          "over flat persistence on this holdout")

    df["bucket"] = df["age_Y"].map(bucket)
    df["actual_ratio"] = df["actual"] / df["raw_base"].replace(0, np.nan)
    df["curve_ratio"] = [da.curve(ay, ip) / da.curve(an, ip)
                         if da.curve(an, ip) > 0 else np.nan
                         for ay, an, ip in zip(df["age_Y"], df["anchor_age"], df["is_p"])]
    print("\n[aging calibration: realized vs curve-implied 1yr change, by age]")
    print(f"  {'bucket':8s} {'n':>4s} {'actual':>9s} {'curve':>8s}")
    for lo, hi, lab in AGE_BUCKETS:
        b = df[df["bucket"] == lab]
        if len(b) == 0:
            continue
        ac = (b["actual_ratio"].median() - 1) * 100
        cc = (b["curve_ratio"].median() - 1) * 100
        print(f"  {lab:8s} {len(b):>4d} {ac:>8.1f}% {cc:>7.1f}%")
    print("  (read sign + ordering across buckets, not exact %; reversion is mixed in)")
    print(f"\n[survivorship] {dropped} players had a baseline but no usable {Y} line.")


if __name__ == "__main__":
    main()
