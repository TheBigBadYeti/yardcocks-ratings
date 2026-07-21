#!/usr/bin/env python3
"""
waiver_targets.py - posture-aware waiver recommendations that FILL the specific holes
/lineups identifies, and name the drop each add costs.

It reuses optimize_lineup to compute this week's lineup NEEDS (unfilled slots, weak
slots + their "bar to beat", IL openings, roster fullness), then searches the FA pool
for real adds that clear each bar. No network; reads the ratings + committed caches.

Format note that shapes pitching picks: this is a start-driven, IP-heavy league. You
fill an open pitching slot with a STREAMING STARTER (SP or SP/RP who starts this week),
not a mop-up reliever -- a reliever's appearance-based value is both low-leverage here
and noisy. So pitching fills are drawn only from arms that actually start.

Recommendation logic:
- OPENINGS (unfilled slots, 0 pts): filled regardless of posture -- free points and a
  fieldable lineup come first. Best eligible FA by this-week EWP.
- UPGRADES (weak filled slots): only surfaced when a KEEPER-QUALITY FA (young/upside)
  beats the current starter by a margin. A rebuild doesn't churn a 32-yo in for 3
  points, but a 24-yo who also helps now is worth the roster move. --churn tunes this:
    empty      = openings only
    keeper     = openings + keeper-quality upgrades   (default; the rebuild choice)
    aggressive = openings + ANY upgrade that beats the bar (contender-style streaming)
- STASH: young dynasty FAs worth a speculative roster spot.
- DROPS: at the roster cap, every add costs a cut. Lowest-value non-keeper, never a
  young high-dynasty keeper (KEEP_DYNASTY floor), never an IL guy (you IR, not drop).
  Named as candidates -- the actual release is your call.
"""
import argparse
import os
import sys
from collections import Counter
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import optimize_lineup as ol

OWNERS = {"CLANK", "Coop", "GoldTY", "Greenbet", "Hutch", "JMerkle", "Jpanner",
          "KRetiree", "Kipp", "Sasso", "Sethmc44", "joeybats", "kyfaess", "zyoung51"}
APPETITE = {"contend": 0.80, "retool": 0.55, "rebuild": 0.20}
YOUNG, VET, KEEP_DYNASTY = 25, 29, 60
KEEPER_AGE, KEEPER_DYN = 26, 55        # "keeper-quality" for a weak-slot upgrade
UPGRADE_MARGIN = 1.15                  # an upgrade must beat the slot's bar by >=15%
DROP_CEILING = 60                      # above this value-to-us a player is a trade
                                       # asset, not a cut -- never a drop candidate
RETURN_FLOOR = 50                      # a returning FA must clear this (win_now or
                                       # dynasty) to be worth grabbing off waivers
LABEL_RANK = {"confirmed": 0, "projected": 1, "assumed": 2}


def _f(v, default=np.nan):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def keeper_quality(rec):
    """Young/upside enough that adding him is a roster-building move, not a churn."""
    age, dyn = _f(rec.get("age")), _f(rec.get("dynasty"))
    return (not np.isnan(age) and age <= KEEPER_AGE) or (
        not np.isnan(dyn) and dyn >= KEEPER_DYN)


def breakout_boost(rec):
    """A young player producing ABOVE his season rate over a real sample may be a
    lasting breakout, not a one-week fluke -- nudge his add-value up, but cap it so
    recent form BALANCES season+future value rather than dominating it."""
    rf, rg = rec.get("recent_fpg"), rec.get("recent_games")
    if rf is None or np.isnan(rf) or (rg is not None and not np.isnan(rg) and rg < 5):
        return 0.0
    lift = rf - _f(rec.get("ffpg"), 0.0)          # recent minus season per-game
    if lift <= 0:
        return 0.0
    age = _f(rec.get("age"))
    youth = 1.0 if age <= 24 else 0.5 if age <= 27 else 0.2 if not np.isnan(age) else 0.4
    return min(lift * 1.3 * youth, 12.0)


def add_value(rec, app):
    """Value of ADDING this player: season-now + future (the dual valuation, same as
    trades) with a capped breakout boost. NOT this-week EWP -- an add is a roster
    commitment, judged on total value, not one week of projected starts."""
    base = app * _f(rec.get("win_now"), 0.0) + (1 - app) * _f(rec.get("dynasty"), 0.0)
    return base, breakout_boost(rec)


def _starts(rec):
    return rec["role"] in ("SP", "SP/RP")   # will accrue a start this week


def fa_fits(rec, eligible):
    """Can this FA fill a slot whose eligibility token is `eligible`? Pitching slots
    are start-driven here, so only starting arms qualify (a pure RP is not a fill)."""
    if eligible == "SP":
        return rec["role"] in ("SP", "SP/RP")
    if eligible == "RP":
        return rec["role"] == "SP/RP"        # SP/RP can slot at RP AND will start
    if eligible == "H":                       # UT: any hitter
        return rec["role"] == "H"
    return rec["role"] == "H" and eligible in rec["tok"]   # specific hitter position


def _sort_key(rec, eligible):
    # rank by expected points; the (projected)/(assumed) label rides along in the
    # detail as a verify-flag rather than demoting a higher-EWP two-start arm.
    return -rec["ewp"]


def dedupe(cands):
    seen, out = set(), []
    for c in cands:
        if c["player"] in seen:
            continue
        seen.add(c["player"]); out.append(c)
    return out


def load_recency(path="data/recency/recent_fpg.csv"):
    """name -> (recent per-game FPts, recent games). The sample size lets us tell a
    durable breakout from a one-week fluke."""
    if not os.path.exists(path):
        return {}
    d = pd.read_csv(path, encoding="utf-8")
    return {ol.norm_name(r["name"]): (_f(r.get("recent_fpg")), _f(r.get("recent_games")))
            for _, r in d.iterrows()}


def load_returning(path="data/injuries/returning.csv"):
    """norm_names of players on an MLB rehab assignment (about to be activated) -- a
    good player to grab off waivers BEFORE he returns and gets scooped."""
    if not os.path.exists(path):
        return set()
    d = pd.read_csv(path, encoding="utf-8")
    return {ol.norm_name(n) for n in d["name"].astype(str)}


def build_fa_pool(df_all, games, dates, week_end, probables, recency):
    """Every unowned, MLB-level free agent, valued with the same EWP model as the
    roster pool (so a stream is comparable to the guy he'd replace), tagged with
    recent form."""
    fa = df_all[~df_all["owner_status"].astype(str).isin(OWNERS)]
    fa = fa[~fa["roster_status"].astype(str).str.lower().str.contains("minor", na=False)]
    pool = []
    for _, r in fa.iterrows():
        rec = ol.make_rec(r, games, dates, week_end, probables)[0]
        rf, rg = recency.get(ol.norm_name(rec["player"]), (np.nan, np.nan))
        rec["recent_fpg"], rec["recent_games"] = rf, rg
        pool.append(rec)
    return pool


def _line(rec, extra=""):
    age, dyn = _f(rec.get("age")), _f(rec.get("dynasty"))
    tag = (f"{int(age)}yo" if not np.isnan(age) else "?") + \
          (f", dyn {int(dyn)}" if not np.isnan(dyn) else "")
    kq = " [keeper]" if keeper_quality(rec) else ""
    return (f"   {rec['player']:<21} {str(rec['team']):<4} {rec['pos']:<9} "
            f"{rec['detail']:<20} EWP {rec['ewp']:>5.1f}  ({tag}){kq}{extra}")


def compute_needs(df_all, games, dates, week_end, probables, team):
    players, _m, il = ol.build_pool(df_all, games, dates, week_end, probables, team)
    hit_lineup = ol.optimal_hitters([p for p in players if p["role"] == "H"])
    sp_lineup, rp_lineup, _ = ol.assign_pitchers(players)
    started = ({r["player"] for _, r in hit_lineup if r}
               | {p["player"] for _, p in sp_lineup + rp_lineup})
    roster_count = int((df_all["owner_status"].astype(str)
                        .str.fullmatch(team, case=False, na=False)).sum())
    needs = ol.diagnose_needs(hit_lineup, sp_lineup, rp_lineup, players, week_end,
                              il, roster_count)
    return needs, started


def drop_candidates(df_all, team, app, n, exclude):
    """Lowest value-to-us non-keepers you can actually spare: excludes this week's
    starters (you don't cut who you're starting), keepers, IL (you IR), and minors."""
    mine = df_all[df_all["owner_status"].astype(str).str.fullmatch(team, case=False,
                                                                   na=False)].copy()
    rs = mine["roster_status"].astype(str).str.lower()
    mine = mine[~rs.str.contains("minor|inj|il", na=False, regex=True)]
    mine = mine[~mine["player"].isin(exclude)]           # not a current starter
    age = pd.to_numeric(mine.get("age"), errors="coerce")
    dyn = pd.to_numeric(mine.get("dynasty_score"), errors="coerce")
    wn = pd.to_numeric(mine.get("win_now_score"), errors="coerce").fillna(0)
    keep = (age < VET) & (dyn >= KEEP_DYNASTY)
    pool = mine[~keep].copy()
    if pool.empty:
        return []
    pool["_v"] = app * wn[~keep] + (1 - app) * dyn[~keep].fillna(0)
    pool = pool[pool["_v"] < DROP_CEILING].sort_values("_v")   # not a trade asset
    return [(r["player"], round(r["_v"], 0), int(_f(r.get("age"), 0)),
             int(_f(r.get("dynasty_score"), 0))) for _, r in pool.head(n).iterrows()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--schedule", default="data/schedule/team_schedule.csv")
    ap.add_argument("--probables", default="data/schedule/probable_starts.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--posture", default="rebuild",
                    choices=["rebuild", "retool", "contend"])
    ap.add_argument("--churn", default="keeper",
                    choices=["empty", "keeper", "aggressive"])
    ap.add_argument("--n", type=int, default=4, help="options to show per section")
    a = ap.parse_args()

    if not os.path.exists(a.ratings):
        sys.exit(f"[waivers] ratings not found: {a.ratings}")
    df_all = pd.read_csv(a.ratings, encoding="utf-8")
    games, dates, week_end = ol.load_schedule(a.schedule)
    probables = ol.load_probables(a.probables)
    app = APPETITE[a.posture]

    needs, started = compute_needs(df_all, games, dates, week_end, probables, a.team)
    recency = load_recency()
    returning = load_returning()
    fa = build_fa_pool(df_all, games, dates, week_end, probables, recency)

    print(f"\n=== {a.team} WAIVER TARGETS | posture={a.posture} churn={a.churn} "
          f"| week ending {needs['week_end']} ===")
    print(f"Roster {needs['roster_count']}/{needs['roster_limit']}"
          + ("  (FULL -- each add needs a drop below)" if needs["roster_full"]
             else f"  ({needs['roster_limit'] - needs['roster_count']} open)"))

    def has_team(f):
        t = str(f.get("team")).strip().lower()
        return t and "n/a" not in t and t not in ("nan", "none")

    unfilled_elig = {s["eligible"] for s in needs["unfilled"]}
    for f in fa:
        f["_base"], f["_boost"] = add_value(f, app)
        f["_val"] = f["_base"] + f["_boost"]

    # 1) BEST ADDS -- the headline: total value NOW + FUTURE (posture-weighted), with a
    # capped breakout boost. A waiver add is a roster commitment judged on season +
    # future value, NOT one week of projected starts. Tagged with what each also does.
    cand = [f for f in fa if has_team(f) and f["_val"] > 0]
    top = dedupe(sorted(cand, key=lambda x: -x["_val"]))[:a.n + 3]
    print("\n--- BEST ADDS (value NOW + FUTURE, posture-weighted; a roster move, not a "
          "1-week rental) ---")
    for f in top:
        tags = []
        if any(fa_fits(f, e) for e in unfilled_elig):
            tags.append("fills opening")
        if f["_boost"] > 0.5:
            tags.append(f"breakout +{f['_boost']:.0f}")
        if ol.norm_name(f["player"]) in returning:
            tags.append("returning")
        if keeper_quality(f):
            tags.append("keeper")
        rec = (f", rec {f['recent_fpg']:.0f}" if not np.isnan(_f(f.get("recent_fpg")))
               else "")
        tg = ("  [" + ", ".join(tags) + "]") if tags else ""
        print(f"   {f['player']:<21} {str(f['team']):<4} {f['pos']:<9} "
              f"val {f['_val']:>4.0f} (now {_f(f.get('win_now'), 0):.0f}/"
              f"fut {_f(f.get('dynasty'), 0):.0f})  {int(_f(f.get('fpts'), 0))}pt szn{rec}"
              f"  {int(_f(f.get('age'), 0))}yo{tg}")

    # breakout watch: the biggest recent-form risers NOT already in the top list -- hot
    # young guys whose season value hasn't caught up. Could be lasting; small sample, so
    # it's a flagged judgment call, kept separate so value stays the headline.
    top_names = {f["player"] for f in top}
    breakers = dedupe(sorted([f for f in cand if f["_boost"] >= 4
                              and f["player"] not in top_names and has_team(f)],
                             key=lambda x: -x["_boost"]))[:3]
    if breakers:
        print("  breakout watch (recent >> season, could be for real -- small sample, "
              "your judgment):")
        for f in breakers:
            print(f"     {f['player']:<20} {str(f['team']):<4} {f['pos']:<9} recent "
                  f"{_f(f.get('recent_fpg'), 0):.0f} vs season {_f(f.get('ffpg'), 0):.0f}"
                  f"  ({int(_f(f.get('age'), 0))}yo, fut {_f(f.get('dynasty'), 0):.0f})")

    # 2) STREAM to fill THIS WEEK's openings -- explicitly short-term (this-week points
    # for empty slots). Secondary to value: only when you just need to plug a hole now.
    if needs["unfilled"]:
        print("\n--- STREAM TO FILL THIS WEEK'S OPENINGS (short-term; this-week points "
              "only, for the empty slots) ---")
        opens = Counter((s["slot"], s["eligible"]) for s in needs["unfilled"])
        for (slot, elig), count in opens.items():
            cands = dedupe(sorted([f for f in fa if fa_fits(f, elig) and f["ewp"] > 0],
                                  key=lambda x: _sort_key(x, elig)))[:a.n]
            note = f" (x{count})" if count > 1 else ""
            pitch = "  [starters only]" if elig in ("SP", "RP") else ""
            print(f"  {slot}{note}, needs {elig}{pitch}:")
            for c in cands:
                print(f"     {c['player']:<20} {str(c['team']):<4} {c['detail']:<20} "
                      f"EWP {c['ewp']:>4.1f}")
            if not cands:
                print("     (no eligible starter with a game this week)")

    # 3) RETURNING FROM INJURY -- available FAs on an MLB rehab assignment (grab before
    # activation). Value-floored so it's real assets, not fringe rehabbing prospects.
    ret = [f for f in fa if ol.norm_name(f["player"]) in returning
           and (_f(f.get("win_now"), 0) >= RETURN_FLOOR
                or _f(f.get("dynasty"), 0) >= RETURN_FLOOR)]
    ret = dedupe(sorted(ret, key=lambda x: -_f(x.get("win_now"), 0)))[:a.n]
    print("\n--- RETURNING FROM INJURY (on MLB rehab -- grab before he's activated) ---")
    if not ret:
        print("   none worth grabbing among available FAs "
              "(good returners are already rostered).")
    for c in ret:
        print(f"   {c['player']:<21} {str(c['team']):<4} {c['pos']:<9} "
              f"win {_f(c.get('win_now'), 0):.0f}/dyn {_f(c.get('dynasty'), 0):.0f}  "
              f"({int(_f(c.get('age'), 0))}yo)")

    # 4) DROPS -- what an add costs, if at the cap. IL players are HOLDS, not cuts.
    if needs["roster_full"]:
        print("\n--- DROP CANDIDATES (lowest value to you; YOUR call, not auto) ---")
        il = needs["il_openings"]
        if il:
            holds = [x["player"] + (" (on rehab -- back soon)"
                                    if ol.norm_name(x["player"]) in returning else "")
                     for x in il if x["hold"]]
            cuttable = [x["player"] for x in il if not x["hold"]]
            print("   FIRST: IR your IL players -- frees a slot with NO cut.")
            if holds:
                print(f"     HOLD (top assets, do NOT drop -- they return): "
                      f"{', '.join(holds)}")
            if cuttable:
                print(f"     low-value IL (droppable if you need the spot): "
                      f"{', '.join(cuttable)}")
        exclude = started | {x["player"] for x in il}   # never cut an injured hold
        drops = drop_candidates(df_all, a.team, app, a.n, exclude)
        if not drops:
            print("   no easy cut -- your bottom pieces still hold value (all >"
                  f"{DROP_CEILING}). Free a spot by trade, not a drop.")
        for name, v, age, dyn in drops:
            print(f"   {name:<21} val {v:>4.0f}  ({age}yo, dyn {dyn})")

    print("\n[waivers] adds are model+eligibility reads -- confirm Fantrax slot "
          "eligibility and injury news before you commit a move.")


if __name__ == "__main__":
    main()
