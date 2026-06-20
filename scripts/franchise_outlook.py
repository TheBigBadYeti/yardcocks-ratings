#!/usr/bin/env python3
"""
franchise_outlook.py  --  contend / retool / rebuild posture for the managed team
=================================================================================

Reads the engine's current_player_ratings.csv, ranks every team in the league on
present strength and future strength, places the managed team, and returns a
posture that should frame every trade/waiver/lineup call. This is the hand on the
wheel: a trade that's right for a contender is malpractice for a rebuilder.

SIGNALS (all league-relative -- your rank among the 14 owners):
  * NOW strength   = sum of the team's top-18 ros_vor (startable forward value).
                     Runs on forward value, so it needs the ratings to have been
                     generated WITH the recency cache -- otherwise injured stars
                     read dead and a contender can look like a seller.
  * FUTURE strength = total dynasty score + count of young (<=25) high-dynasty
                     studs.
  * AGE            = roster average age (context, not a ranked axis).

STANDINGS (actual record / playoff odds) is a third axis, deliberately NOT wired
in yet: the standings export on hand is incomplete and keys teams by name, not
owner handle. Provide a clean export + a name->handle map and it slots in here.

USAGE
  python3 scripts/franchise_outlook.py --ratings data/processed/current_player_ratings.csv --team Kipp
"""

import argparse
import pandas as pd
import numpy as np

OWNERS = ["CLANK", "Coop", "GoldTY", "Greenbet", "Hutch", "JMerkle", "Jpanner",
          "KRetiree", "Kipp", "Sasso", "Sethmc44", "joeybats", "kyfaess", "zyoung51"]
STARTERS = 18          # active lineup size
YOUNG_AGE = 25
STUD_DYNASTY = 70


def team_table(d):
    rows = []
    for o, g in d[d["owner_status"].isin(OWNERS)].groupby("owner_status"):
        top = g.sort_values("ros_vor", ascending=False).head(STARTERS)
        rows.append({
            "owner": o,
            "now": round(top["ros_vor"].sum(), 0),
            "future": round(g["dynasty_score"].sum(), 0),
            "young_studs": int(((g["age"] <= YOUNG_AGE) & (g["dynasty_score"] >= STUD_DYNASTY)).sum()),
            "avg_age": round(g["age"].mean(), 1),
            "roster": len(g),
        })
    t = pd.DataFrame(rows)
    t["now_rank"] = t["now"].rank(ascending=False).astype(int)
    t["fut_rank"] = t["future"].rank(ascending=False).astype(int)
    return t.sort_values("now_rank")


def _tier(rank, n):
    """strong (top third) / mid / weak (bottom third)."""
    if rank <= n / 3:
        return "strong"
    if rank > 2 * n / 3:
        return "weak"
    return "mid"


def posture(now_rank, fut_rank, n=14):
    """Map present x future tiers to a posture. All nine cells handled explicitly."""
    now, fut = _tier(now_rank, n), _tier(fut_rank, n)
    if now == "strong":
        if fut == "weak":
            return ("CONTEND (win-now window)", "Built to win now but the future is thin -- your "
                    "window is open and short. Go for it: spend prospects/picks on upgrades. Just "
                    "know you're borrowing from a future that needs replenishing afterward.")
        return ("CONTEND", "Built to win now. Spend prospects/picks on win-now upgrades, buy at the "
                "deadline, accept a slightly worse future. Do NOT sell the present for youth.")
    if now == "weak":
        if fut == "strong":
            return ("REBUILD (rising)", "Weak now, strong young core -- the rebuild is working. Sell "
                    "win-now veterans for more youth/picks and let the core mature. Punt this season.")
        if fut == "weak":
            return ("TEARDOWN", "Weak now AND weak future -- the hardest spot. Sell everything with "
                    "trade value, hoard youth and picks, bottom out on purpose and rebuild the base.")
        return ("REBUILD", "Not competing now, with only a so-so future. Convert win-now veterans "
                "(wasted on a non-contender) into youth and picks -- turn that middling future into a "
                "strong one. This is the trade direction that fits you.")
    if now == "mid":
        if fut == "mid":
            return ("STUCK IN THE MIDDLE", "Mediocre now, mediocre future -- the worst place to be. "
                    "PICK A DIRECTION: go all-in to contend, or sell vets and commit to youth. "
                    "Drifting here is how dynasty teams stay irrelevant for years.")
        if fut == "strong":
            return ("RETOOL (rising)", "On the doorstep with a strong young core. Make targeted "
                    "win-now upgrades but do NOT mortgage the future -- you're close and getting closer.")
        return ("RETOOL toward youth", "Middling now and a fading future -- don't chase this season. "
                "Move aging vets for younger value and rebuild the pipeline before it empties.")
    return ("RETOOL", "Make value-positive moves, stay flexible, don't overpay to chase this season.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--team", default="Kipp")
    a = ap.parse_args()

    d = pd.read_csv(a.ratings)
    # ros_vor = forward startable value (forward_fpg above replacement level).
    # Graceful fallback to win_now_score for old ratings files without the column.
    if "ros_vor" not in d.columns:
        d["ros_vor"] = d["win_now_score"]
    t = team_table(d)
    me = t[t["owner"] == a.team]
    if not len(me):
        print(f"team {a.team!r} not found among owners"); return
    me = me.iloc[0]
    n = len(t)
    name, plan = posture(int(me["now_rank"]), int(me["fut_rank"]), n)

    print("=" * 64)
    print(f"  FRANCHISE OUTLOOK  --  {a.team}")
    print("=" * 64)
    print(f"  Present strength : #{int(me['now_rank'])} of {n}   (startable forward value {me['now']:.0f})")
    print(f"  Future strength  : #{int(me['fut_rank'])} of {n}   (dynasty {me['future']:.0f}, "
          f"{me['young_studs']} young studs, avg age {me['avg_age']})")
    print(f"\n  POSTURE: {name}")
    print(f"  {plan}")
    print("\n  League now-strength ranking:")
    for _, r in t.iterrows():
        mark = "  <-- you" if r["owner"] == a.team else ""
        print(f"    {int(r['now_rank']):2}. {r['owner']:9} now={r['now']:>6.0f}  "
              f"future#{int(r['fut_rank']):2}{mark}")
    print("\n  NOTE: present strength runs on forward value -- regenerate ratings WITH the")
    print("  recency cache before trusting the rank (injured stars read dead otherwise).")


if __name__ == "__main__":
    main()
