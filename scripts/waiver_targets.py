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
    """name -> recent per-game FPts, so we can catch a hot call-up the season rate
    (and thus win_now/dynasty/EWP) still fades."""
    if not os.path.exists(path):
        return {}
    d = pd.read_csv(path, encoding="utf-8")
    return {ol.norm_name(r["name"]): _f(r.get("recent_fpg"))
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
        rec["recent_fpg"] = recency.get(ol.norm_name(rec["player"]))
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

    # 1) OPENINGS -- collapse identical slots, fill regardless of posture
    print("\n--- FILL THESE OPENINGS (unfilled = 0 pts; posture-agnostic) ---")
    opens = Counter((s["slot"], s["eligible"]) for s in needs["unfilled"])
    if not opens:
        print("   none -- lineup is fully fielded.")
    for (slot, elig), count in opens.items():
        cands = dedupe(sorted([f for f in fa if fa_fits(f, elig) and f["ewp"] > 0],
                              key=lambda x: _sort_key(x, elig)))[:a.n]
        need_note = f"  (you have {count} -- pick {count})" if count > 1 else ""
        pitch = "  [starters only -- reliever appearances don't fill a slot here]" \
            if elig in ("SP", "RP") else ""
        print(f"  {slot} slot, needs {elig}{need_note}{pitch}:")
        for c in cands:
            print(_line(c))
        if not cands:
            print("     (no eligible starting FA with a game this week)")

    # 2) UPGRADES -- weak filled slots, gated by churn/posture, hard-capped & deduped
    if a.churn != "empty":
        want_keeper = (a.churn == "keeper")
        ups = []
        for s in needs["slots"]:
            if not s["filled"]:
                continue
            for f in fa:
                if not fa_fits(f, s["eligible"]) or f["ewp"] <= s["bar_ewp"] * UPGRADE_MARGIN:
                    continue
                if want_keeper and not keeper_quality(f):
                    continue
                ups.append((s, f, f["ewp"] - s["bar_ewp"]))
        # best gain per FA, then top a.n overall
        best = {}
        for s, f, gain in ups:
            if f["player"] not in best or gain > best[f["player"]][2]:
                best[f["player"]] = (s, f, gain)
        top = sorted(best.values(), key=lambda x: -x[2])[:a.n]
        print(f"\n--- UPGRADES over weak slots "
              f"({'keeper-quality only' if want_keeper else 'any upgrade'}) ---")
        if not top:
            print("   none clear the bar -- your starters hold their slots.")
        for s, f, gain in top:
            print(_line(f, extra=f"   -> over {s['slot']} "
                                 f"({s['player']} @ {s['bar_ewp']}, +{gain:.1f})"))

    # 3) HOT / RECENT FORM -- call-ups & heaters the season-rate model still fades
    def has_team(f):
        t = str(f.get("team")).strip().lower()
        return t and "n/a" not in t and t not in ("nan", "none")
    hot = [f for f in fa if f.get("recent_fpg") is not None
           and not np.isnan(f["recent_fpg"]) and f["recent_fpg"] >= 6
           and (f["recent_fpg"] - f["ffpg"]) >= 3 and has_team(f)]
    hot = dedupe(sorted(hot, key=lambda x: -(x["recent_fpg"] - x["ffpg"])))[:a.n]
    print("\n--- HOT / RECENT FORM (recent > season rate; call-ups & heaters the model "
          "is still fading) ---")
    if not hot:
        print("   none flagged.")
    for c in hot:
        yng = " [young]" if _f(c.get("age")) <= YOUNG else ""
        print(f"   {c['player']:<21} {str(c['team']):<4} {c['pos']:<9} recent "
              f"{c['recent_fpg']:>4.1f} vs season {c['ffpg']:>4.1f}  "
              f"({int(_f(c.get('age'), 0))}yo, dyn {int(_f(c.get('dynasty'), 0))}){yng}")

    # 3b) RETURNING FROM INJURY -- available FAs on an MLB rehab assignment (grab
    # before activation). Only GOOD ones: a value floor keeps fringe prospects on
    # rehab out (the valuable returners are usually rostered). Valued by asset scores,
    # not this-week EWP (they may not play yet).
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

    # 4) STASH -- young dynasty upside (posture spec spots)
    stash = dedupe(sorted([f for f in fa if _f(f.get("age")) <= YOUNG
                           and _f(f.get("dynasty"), 0) > 0],
                          key=lambda x: -_f(x.get("dynasty"), 0)))[:a.n]
    print("\n--- STASH (young dynasty upside; not tied to a hole) ---")
    for c in stash:
        print(_line(c))

    # 5) DROPS -- what an add costs, if at the cap. IL players are HOLDS, not cuts.
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
