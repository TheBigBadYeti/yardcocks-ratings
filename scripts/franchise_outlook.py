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

STANDINGS (actual record) is now WIRED IN via scripts/standings.py: when the Fantrax
standings export is present and the franchise name maps to an owner handle, the ACTUAL
standings rank replaces the roster-inferred now-rank for the posture call, and every
team's real record is shown. Roster inference is a proxy; the record is ground truth.
Unmapped franchises fall back to the inference and are flagged.

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

    # ACTUAL RECORD is ground truth for present strength; roster value is only a proxy.
    try:
        import standings as st
        recs, prov, unmapped = st.by_owner()
    except Exception:
        recs, prov, unmapped = {}, {}, []
    mine = recs.get(a.team)
    now_rank_used = mine["rank"] if mine else int(me["now_rank"])
    name, plan = posture(now_rank_used, int(me["fut_rank"]), n)

    print("=" * 64)
    print(f"  FRANCHISE OUTLOOK  --  {a.team}")
    print("=" * 64)
    if mine:
        print(f"  RECORD (actual)  : {st.summary_line(mine)}")
        print(f"  Roster proxy     : now #{int(me['now_rank'])} of {n} "
              f"(startable forward value {me['now']:.0f}) -- record overrides this")
    else:
        print(f"  Present strength : #{int(me['now_rank'])} of {n}   "
              f"(startable forward value {me['now']:.0f})  [no standings match]")
    print(f"  Future strength  : #{int(me['fut_rank'])} of {n}   (dynasty {me['future']:.0f}, "
          f"{me['young_studs']} young studs, avg age {me['avg_age']})")
    print(f"\n  POSTURE: {name}")
    print(f"  {plan}")
    print("\n  League table (actual record where mapped; * = provisional mapping):")
    order = sorted(t.to_dict("records"),
                   key=lambda r: recs[r["owner"]]["rank"] if r["owner"] in recs else 99)
    for r in order:
        rec = recs.get(r["owner"])
        mark = "  <-- you" if r["owner"] == a.team else ""
        if rec:
            star = "*" if rec["provisional"] else ""
            print(f"    {rec['rank']:2}. {r['owner']:9} {rec['w']:>2}-{rec['l']:<2}{star:1} "
                  f"({rec['pct']:.3f})  roster-now#{int(r['now_rank']):2} "
                  f"future#{int(r['fut_rank']):2}{mark}")
        else:
            print(f"     ?. {r['owner']:9} {'--':>5}    "
                  f"(no standings map)  roster-now#{int(r['now_rank']):2} "
                  f"future#{int(r['fut_rank']):2}{mark}")
    if prov:
        print("\n  PROVISIONAL name mappings (confirm): "
              + ", ".join(f"{h}={f}" for h, f in prov.items()))
    if unmapped:
        print(f"  UNMAPPED franchises: {', '.join(unmapped)} "
              f"-- those owners fall back to roster inference.")
    print("\n  NOTE: present strength runs on forward value -- regenerate ratings WITH the")
    print("  recency cache before trusting the rank (injured stars read dead otherwise).")


if __name__ == "__main__":
    main()
