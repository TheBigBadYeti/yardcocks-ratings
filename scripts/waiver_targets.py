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

# Hard roster structure (SYSTEM_SPEC s2): 40 total = 18 Active + 8 Reserve + 4 IR +
# 10 Minors. The IR cap is the one that bites: with 4/4 used you CANNOT park an
# injured player there to free an active slot until you clear an IR spot first.
SLOTS_ACTIVE, SLOTS_RESERVE, SLOTS_IR, SLOTS_MINORS = 18, 8, 4, 10
ROSTER_TOTAL = 40
MAX_CLAIMS_WEEK = 7                    # FAAB: 100 budget, max 7 claims/week
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
    # season_fpg is the RAW season rate; ffpg is now form-blended, so compare to season
    lift = rf - _f(rec.get("season_fpg"), 0.0)    # recent minus season per-game
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
    """Can this FA fill a slot whose eligibility token is `eligible`?
    NOTE: an earlier version barred pure RPs from RP slots on the theory that only
    starts matter here. That was wrong -- checked against the data, a multi-inning
    reliever like Headrick has 50 IP / 187 pts on a full-season sample, and with IP+3
    and HLD+3 he genuinely out-earns a weak one-start arm. Ranking is now decided by
    MEASURED lineup impact, so no heuristic exclusion is needed."""
    if eligible == "SP":
        return rec["role"] in ("SP", "SP/RP")
    if eligible == "RP":
        return rec["role"] in ("RP", "SP/RP")
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
        # pass recency so an FA's EWP is form-blended the same way a rostered player's
        # is -- otherwise a stream would be compared against the guy he'd replace on
        # two different models.
        rec = ol.make_rec(r, games, dates, week_end, probables, recency)[0]
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


def move_confidence(f):
    """HIGH / MED / LOW for an ADD, derived from real signals rather than vibes:
    how well-sampled the player's rate is, how certain his playing time is, and how
    big the measured gain is. Returns (level, [reasons])."""
    score, why = 2, []
    conf = _f(f.get("conf"))
    if not np.isnan(conf):
        if conf < 0.5:
            score -= 2; why.append(f"thin sample (conf {conf:.2f})")
        elif conf < 0.8:
            score -= 1; why.append(f"moderate sample (conf {conf:.2f})")
    lab = f.get("start_label")
    if lab == "projected":
        score -= 1; why.append("2nd start projected, not yet posted")
    elif lab == "assumed":
        score -= 1; why.append("start assumed from team schedule")
    if f.get("_impact", 0) < 3:
        score -= 1; why.append("marginal gain")
    return ("HIGH" if score >= 2 else "MED" if score >= 1 else "LOW"), why


def lineup_total(players):
    """Total EWP of the optimal lineup buildable from this pool."""
    hit = ol.optimal_hitters([p for p in players if p["role"] == "H"])
    sp, rp, _ = ol.assign_pitchers(players)
    return (sum(r["ewp"] for _, r in hit if r)
            + sum(p["ewp"] for _, p in sp + rp))


def add_impact(players, base_total, cand):
    """REAL lineup gain from adding this player: re-run the optimizer with him in the
    pool and diff the total. Answers 'how does this add actually make us better?'
    rather than just asserting a player is good. 0 means he wouldn't crack the 18."""
    return lineup_total(players + [cand]) - base_total


def _cheap_ir_occupants(df_all, team, app, n=2):
    """Lowest-value players sitting in the scarce IR slots -- releasing one is what
    unblocks parking an injured stud there."""
    k = df_all[df_all["owner_status"].astype(str)
               .str.fullmatch(team, case=False, na=False)].copy()
    k = k[k["roster_status"].astype(str).str.lower().str.contains("inj", na=False)]
    if k.empty:
        return []
    wn = pd.to_numeric(k.get("win_now_score"), errors="coerce").fillna(0)
    dy = pd.to_numeric(k.get("dynasty_score"), errors="coerce").fillna(0)
    k["_v"] = app * wn + (1 - app) * dy
    return [(r["player"], r["_v"]) for _, r in k.nsmallest(n, "_v").iterrows()]


def roster_ledger(df_all, team):
    """Slot accounting against the league's hard limits, so recommendations respect
    what you can actually DO -- not just who's available."""
    k = df_all[df_all["owner_status"].astype(str)
               .str.fullmatch(team, case=False, na=False)]
    rs = k["roster_status"].astype(str).str.lower()
    return {
        "total": len(k),
        "active": int((rs == "active").sum()),
        "reserve": int((rs == "reserve").sum()),
        "ir": int(rs.str.contains("inj", na=False).sum()),
        "minors": int(rs.str.contains("minor", na=False).sum()),
    }


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
    return needs, started, players


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
    # same overlay as /lineups, so we never re-recommend a player you already added
    df_all = ol.apply_pending(pd.read_csv(a.ratings, encoding="utf-8"), a.team)
    games, dates, week_end = ol.load_schedule(a.schedule)
    probables = ol.load_probables(a.probables)
    app = APPETITE[a.posture]

    needs, started, players = compute_needs(df_all, games, dates, week_end,
                                            probables, a.team)
    recency = load_recency()
    returning = load_returning()
    fa = build_fa_pool(df_all, games, dates, week_end, probables, recency)
    led = roster_ledger(df_all, a.team)
    base_total = lineup_total(players)

    print(f"\n=== {a.team} WAIVERS | posture={a.posture} | week ending "
          f"{needs['week_end']} | lineup now {base_total:.0f} EWP ===")

    # ---- ROSTER LEDGER: what you can actually DO -------------------------------
    print(f"\n--- ROSTER ({led['total']}/{ROSTER_TOTAL}) vs hard limits ---")
    for label, have, cap in (("Active", led["active"], SLOTS_ACTIVE),
                             ("Reserve", led["reserve"], SLOTS_RESERVE),
                             ("Inj Res", led["ir"], SLOTS_IR),
                             ("Minors", led["minors"], SLOTS_MINORS)):
        if have < cap:
            note = f"{cap - have} OPEN"
        elif have == cap:
            note = "FULL"
        else:
            note = f"OVER by {have - cap} (verify in Fantrax)"
        print(f"   {label:<9} {have:>2}/{cap:<3} {note}")
    print(f"   {'TOTAL':<9} {led['total']:>2}/{ROSTER_TOTAL:<3} "
          + ("FULL -- every add costs a drop" if led["total"] >= ROSTER_TOTAL else "room"))
    print(f"   FAAB: max {MAX_CLAIMS_WEEK} claims/week.")

    il = needs["il_openings"]
    ir_blocked = led["ir"] >= SLOTS_IR and il
    if ir_blocked:
        cheap_ir = _cheap_ir_occupants(df_all, a.team, app)
        print(f"\n   ** IR IS FULL ({led['ir']}/{SLOTS_IR}). ** You CANNOT move "
              f"{', '.join(x['player'] for x in il)} to IR to free an active slot "
              f"until an IR spot opens.")
        if cheap_ir:
            print("   Cheapest IR occupants to release first: "
                  + ", ".join(f"{n} (val {v:.0f})" for n, v in cheap_ir))

    def has_team(f):
        t = str(f.get("team")).strip().lower()
        return t and "n/a" not in t and t not in ("nan", "none")

    unfilled_elig = {s["eligible"] for s in needs["unfilled"]}
    for f in fa:
        f["_base"], f["_boost"] = add_value(f, app)
        f["_val"] = f["_base"] + f["_boost"]

    # ---- MOVES: every recommendation is a real transaction with a MEASURED effect ----
    # Shortlist first (simulating the optimizer across thousands of FAs would be waste),
    # then measure each candidate's ACTUAL lineup gain by re-running the optimizer with
    # him in the pool. That answers "how does this add make us better?" with a number
    # instead of asserting a player is good.
    cand = [f for f in fa if has_team(f) and f["_val"] > 0]
    short = dedupe(sorted(cand, key=lambda x: -x["_val"])[:25]
                   + sorted([f for f in cand if f["ewp"] > 0
                             and any(fa_fits(f, e) for e in unfilled_elig)],
                            key=lambda x: -x["ewp"])[:15])
    for f in short:
        f["_impact"] = add_impact(players, base_total, f)

    drops = drop_candidates(df_all, a.team, app, 6, started | {x["player"] for x in il})
    drop_txt = (f"drop {drops[0][0]} (val {drops[0][1]:.0f}, lowest-value spare)"
                if drops else "no easy cut -- free a spot by trade")

    # Adds are chosen GREEDILY and SEQUENTIALLY: after each pick, the optimizer is
    # re-run with that player already on the roster, so the next candidate's number is
    # its MARGINAL gain. Without this, four relievers each "worth +13" would all be
    # filling the same two empty slots and the plan would promise ~4x what it can
    # deliver. The loop stops on its own once nobody adds real points.
    pool, cur, chosen = list(players), base_total, []
    ranked = sorted(short, key=lambda x: -x["_impact"])[:20]
    while len(chosen) < min(a.n, MAX_CLAIMS_WEEK):
        best, best_gain = None, 0.0
        for f in ranked:
            if any(f is c for c, _ in chosen):
                continue
            g = lineup_total(pool + [f]) - cur
            if g > best_gain:
                best, best_gain = f, g
        if best is None or best_gain <= 0.5:
            break
        chosen.append((best, best_gain))
        pool.append(best)
        cur += best_gain
    helpers = chosen

    # ---- ORDERED MOVE PLAN: dependencies first, then adds. Execute top-down. -------
    print("\n=== RECOMMENDED MOVE PLAN (execute in order) ===")
    step = 0
    open_slots = max(0, ROSTER_TOTAL - led["total"])
    ir_free = max(0, SLOTS_IR - led["ir"])
    holds = [x for x in il if x["hold"]]

    # Structural moves first: clearing IR is what unlocks parking an injured stud,
    # which is the cheapest way to open an active slot (no useful player is cut).
    if holds and ir_free == 0:
        for name, val in _cheap_ir_occupants(df_all, a.team, app, len(holds)):
            step += 1
            print(f"\n {step}. DROP {name}  (currently on IR)          confidence: HIGH")
            print(f"      WHY    : val {val:.0f} -- the least valuable player you own, "
                  f"and he's occupying a scarce IR slot you need.")
            print(f"      ENABLES: an IR slot for {holds[0]['player'] if holds else 'an injured hold'}.")
            ir_free += 1
            open_slots += 1
    for h in holds[:ir_free]:
        step += 1
        print(f"\n {step}. MOVE {h['player']} to IR                    confidence: HIGH")
        print(f"      WHY    : MLB-IL but sitting in an active slot, so he scores 0 for "
              f"you. He's a HOLD (win {h['win_now']:.0f}/dyn {h['dynasty']:.0f}) -- park "
              f"him, don't cut him.")
        print(f"      EFFECT : frees an active roster spot at no cost.")
        open_slots += 1

    if not helpers:
        print("\n   No available FA cracks your optimal 18 -- your startable core "
              "already beats the wire. Spend claims on future value instead.")
    claims, running = 0, base_total
    for f, gain in helpers:
        if claims >= MAX_CLAIMS_WEEK:
            break
        step += 1
        claims += 1
        lvl, cwhy = move_confidence(f)
        fills = [e for e in unfilled_elig if fa_fits(f, e)]
        why = (f"fills your empty {fills[0]} slot (0 pts there today)" if fills
               else "outproduces your weakest startable at his slot")
        extra = []
        if f["_boost"] > 0.5:
            extra.append(f"hot: {_f(f.get('recent_fpg'), 0):.0f} recent vs "
                         f"{_f(f.get('season_fpg'), 0):.0f} season")
        if keeper_quality(f):
            extra.append(f"also a keeper ({int(_f(f.get('age'), 0))}yo, "
                         f"fut {_f(f.get('dynasty'), 0):.0f})")
        if ol.norm_name(f["player"]) in returning:
            extra.append("returning from IL")
        if open_slots > 0:
            cost = f"uses one of the {open_slots} spot(s) you just freed -- no cut needed"
            open_slots -= 1
        else:
            cost = f"roster is full, so {drop_txt}"
        print(f"\n {step}. ADD {f['player']}  ({f['team']} {f['pos']})"
              f"        confidence: {lvl}")
        print(f"      WHY    : {why}; {f['detail']}."
              + ("  " + "; ".join(extra) + "." if extra else ""))
        print(f"      LINEUP : {running:.0f} -> {running + gain:.0f} EWP "
              f"(+{gain:.1f} MARGINAL, i.e. on top of the moves above)")
        running += gain
        print(f"      COST   : {cost}. Claim {claims} of {MAX_CLAIMS_WEEK}.")
        if cwhy:
            print(f"      CAVEAT : {'; '.join(cwhy)}.")

    print("\n   Tell me which of these you actually execute and I'll record them, so "
          "/lineups reflects the new roster before the next /refresh.")

    # Future-value adds that do NOT help this week -- honest about the tradeoff.
    future = [f for f in short if f.get("_impact", 0) <= 0.5 and keeper_quality(f)]
    future = sorted(future, key=lambda x: -x["_val"])[:3]
    if future:
        print("\n--- FUTURE-VALUE ADDS (won't crack this week's 18) ---")
        for f in future:
            print(f"   {f['player']:<21} {str(f['team']):<4} {f['pos']:<9} "
                  f"val {f['_val']:>4.0f} (now {_f(f.get('win_now'), 0):.0f}/"
                  f"fut {_f(f.get('dynasty'), 0):.0f})  {int(_f(f.get('age'), 0))}yo")
        print("   Each costs a drop for ZERO points this week -- only worth it if you "
              "rate him above the guy you'd cut.")


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
        if il:
            holds = [x["player"] + (" (on rehab -- back soon)"
                                    if ol.norm_name(x["player"]) in returning else "")
                     for x in il if x["hold"]]
            cuttable = [x["player"] for x in il if not x["hold"]]
            if ir_blocked:
                print(f"   NOTE: IR is {led['ir']}/{SLOTS_IR} FULL, so you canNOT park "
                      f"an injured player there to dodge a cut -- clear an IR slot first "
                      f"(see the cheapest occupants above).")
            else:
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
