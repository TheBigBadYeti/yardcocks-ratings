#!/usr/bin/env python3
"""
audit_qtier.py - sanity-check the production-tier (q_tier) that drives the
durability premium in the attrition model.

q_tier is each player's recency-weighted FP/G rate, percentile-ranked WITHIN role.
A high-talent player gets under-tiered (and therefore OVER-attritted) only if his
recent RATE is depressed. That can be legitimate (real multi-year decline) or an
artifact (one injury-shortened / poor season dragging the recency-weighted rate
below his established level). This script can't tell them apart for you - but it
auto-flags the candidates and prints the season-by-season detail so YOU can.

Reads the career cache only (data/career/career_stats.csv). No network.

  python scripts\\audit_qtier.py
  python scripts\\audit_qtier.py --watch "Trea Turner" "Jose Altuve" --top 25
"""
import argparse
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dynasty_asset as da   # reuse raw_baseline + norm_name + the real constants


def build(cr, group):
    """Per-player recency-weighted rate + within-group percentile for one group."""
    rows = []
    sub = cr[cr["group"] == group]
    current_season = int(cr["season"].max()) if len(cr) else None
    for name, g in sub.groupby("name"):
        seasons = list(zip(g["season"].astype(int), g["games"].astype(float),
                           g["fpg"].astype(float)))
        raw, tg = da.raw_baseline(seasons, current_season)
        last3 = sorted(seasons, key=lambda x: x[0], reverse=True)[:3]
        best3 = max((f for _, _, f in last3), default=0.0)
        recent = sorted(seasons, key=lambda x: x[0], reverse=True)[0]
        rows.append({
            "name": name, "raw_base": round(raw, 2), "recent_games": tg,
            "best3_fpg": round(best3, 2), "drag": round(best3 - raw, 2),
            "recent_yr": int(recent[0]), "recent_g": int(recent[1]),
            "recent_fpg": round(recent[2], 2),
            "detail": " | ".join(f"{int(s)}:{int(gm)}g@{fp:.1f}"
                                 for s, gm, fp in
                                 sorted(seasons, reverse=True)[:3]),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["q_tier"] = df["raw_base"].rank(pct=True).round(2)
    return df.sort_values("q_tier", ascending=False).reset_index(drop=True)


def show(df, idx_label):
    cols = ["name", "q_tier", "raw_base", "best3_fpg", "drag", "recent_games", "detail"]
    return df[cols].to_string(index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--career", default="data/career/career_stats.csv")
    ap.add_argument("--min-games", type=float, default=100.0,
                    help="floor on recent games to count as an established vet")
    ap.add_argument("--top", type=int, default=20,
                    help="how many auto-flagged drag candidates to show")
    ap.add_argument("--watch", nargs="*", default=["Trea Turner"],
                    help="names to spotlight with full breakdown")
    a = ap.parse_args()

    if not os.path.exists(a.career):
        sys.exit(f"[audit] career cache not found: {a.career}")
    cr = pd.read_csv(a.career, encoding="utf-8")
    if "group" not in cr.columns:
        cr["group"] = "hitting"

    for group in ("hitting", "pitching"):
        df = build(cr, group)
        if df.empty:
            continue
        print(f"\n{'='*70}\n{group.upper()}  (n={len(df)})\n{'='*70}")

        # auto-flag: ESTABLISHED players whose weighted rate trails their best
        # recent season the most -> a recent weak/short season may be dragging
        # them below tier. The per-season detail tells you artifact vs real.
        est = df[df["recent_games"] >= a.min_games].copy()
        flagged = est.sort_values("drag", ascending=False).head(a.top)
        print(f"\n-- biggest 'drag' (best recent season - weighted rate); "
              f"large drag + a short/low recent season = possible mis-tier --")
        print(show(flagged, "drag"))

        # specifically: high-talent players who slipped OUT of the elite tier
        slipped = est[(est["best3_fpg"].rank(pct=True) >= 0.80) &
                      (est["q_tier"] < 0.75)]
        if len(slipped):
            print(f"\n-- top-20%% by BEST season but q_tier < 0.75 "
                  f"(elite ceiling, sub-elite tier -> check) --")
            print(show(slipped.sort_values("drag", ascending=False), "slip"))

        # spotlight watchlist names
        watch = df[df["name"].isin(a.watch)]
        if len(watch):
            print(f"\n-- watchlist --")
            print(show(watch, "watch"))


if __name__ == "__main__":
    main()
