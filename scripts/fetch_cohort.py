#!/usr/bin/env python3
"""
fetch_cohort.py - unbiased cohorts for the aging-decline backtest.

The career cache is built from the 2026 player universe, so it is pre-filtered
for survival: anyone who declined out of the league before 2026 isn't in it, and
the aging backtest on it can only ever see survivors. This fetch fixes that by
selecting players on PAST relevance instead. For each base season B it pulls
EVERY player who logged real time that year (playerPool=All), then looks them up
again in season B+gap. A player with no qualifying B+gap line didn't get dropped
-- he's recorded as a washout (fpg_plus = 0), because producing nothing is the
actual aging outcome we need to measure.

  data/career/cohort.csv
    mlb_id, name, group, base_year, gap, age_base, games_base, fpg_base,
    played_plus, games_plus, fpg_plus

Age is computed from each player's birthDate against a ~July 1 baseball-age
reference. backtest_cohort.py reads this and compares real population retention
(washouts included) to the curve -- the test the survivor pool can't run.

NETWORK: MLB 403s from a Claude cloud VM only due to that sandbox egress allowlist;
MLB allows datacenter IPs (GitHub Actions gets 200). Stdlib + pandas; imports the proven
converters from fetch_recency / fetch_career.
"""
import argparse
import os

import pandas as pd
import fetch_recency as fr     # _get / fp_hitter / fp_pitch / norm_name / API
import fetch_career as fc      # season_fp (league scoring incl QS estimate)

API = fr.API


def season_pool(season, group):
    """All players with a line in `season` for `group` (playerPool=All), scored
    on league rules. Returns {mlb_id: {name, games, fpg}}."""
    url = (f"{API}/stats?stats=season&group={group}&season={season}"
           f"&sportId=1&gameType=R&playerPool=All&limit=5000")
    out = {}
    for sp in fr._get(url).get("stats", [{}])[0].get("splits", []):
        p = sp.get("player", {})
        pid = p.get("id")
        if not pid:
            continue
        st = sp.get("stat", {})
        games = float(st.get("gamesPlayed", 0) or 0)
        fp = fc.season_fp(st, group)
        out[pid] = {"name": p.get("fullName", ""), "games": games,
                    "fpg": round(fp / games, 2) if games else 0.0}
    return out


def birthdates(ids):
    """Batch /people lookups -> {id: 'YYYY-MM-DD'}."""
    bd, ids = {}, list(ids)
    for i in range(0, len(ids), 100):
        chunk = ",".join(str(x) for x in ids[i:i + 100])
        for person in fr._get(f"{API}/people?personIds={chunk}").get("people", []):
            bd[person.get("id")] = person.get("birthDate")
    return bd


def age_in(birth_date, season):
    """Baseball age in `season`, ~July 1 reference."""
    if not birth_date:
        return None
    try:
        y, m, d = (int(x) for x in birth_date.split("-")[:3])
    except Exception:
        return None
    return season - y - (1 if (m, d) > (7, 1) else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-years", default="2013,2014,2015,2016,2017,2018",
                    help="comma list of cohort base seasons")
    ap.add_argument("--gap", type=int, default=5, help="years to track forward")
    ap.add_argument("--min-games", type=float, default=20.0,
                    help="min games to count as a real line (base AND plus)")
    ap.add_argument("--out", default="data/career/cohort.csv")
    a = ap.parse_args()
    base_years = [int(x) for x in a.base_years.split(",")]

    rows = []
    for B in base_years:
        for group in ("hitting", "pitching"):
            base = season_pool(B, group)
            plus = season_pool(B + a.gap, group)
            ids = [pid for pid, v in base.items() if v["games"] >= a.min_games]
            bd = birthdates(ids)
            survived = 0
            for pid in ids:
                b = base[pid]
                p = plus.get(pid)
                played = bool(p and p["games"] >= a.min_games)
                survived += played
                rows.append({
                    "mlb_id": pid, "name": b["name"], "group": group,
                    "base_year": B, "gap": a.gap, "age_base": age_in(bd.get(pid), B),
                    "games_base": b["games"], "fpg_base": b["fpg"],
                    "played_plus": int(played),
                    "games_plus": p["games"] if p else 0.0,
                    "fpg_plus": p["fpg"] if played else 0.0,   # washout -> 0
                })
            print(f"[cohort] {B} {group}: cohort={len(ids)} "
                  f"survived_to_{B + a.gap}={survived} "
                  f"({100 * survived / max(len(ids), 1):.0f}%)")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    pd.DataFrame(rows).to_csv(a.out, index=False)
    print(f"[cohort] wrote {len(rows)} player-cohort rows -> {a.out}")
    print("[cohort] now run: python scripts/backtest_cohort.py --cohort "
          f"{a.out}")


if __name__ == "__main__":
    main()
