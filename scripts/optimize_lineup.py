#!/usr/bin/env python3
"""
optimize_lineup.py - schedule-aware weekly lineup optimizer (Yardcocks & Beyond)

Recommends the active 18-man lineup that maximizes expected points for the week,
under the 12-start cap, AND emits a structured NEEDS report that /waivers consumes.

Slots: C,1B,2B,3B,SS,OF,OF,OF,UT (9 hitters), 6x SP, 3x RP.
Eligible pool = roster_status in {Active, Reserve}; Inj Res / Minors excluded.

Hitters are assigned by OPTIMAL max-weight matching over multi-position eligibility
(a 2B/SS/OF plays wherever he adds the most total points), not a greedy first-fill.

Value model (expected weekly points, EWP):
  hitter : forward_fpg * games_this_week * play_rate
  SP     : forward_fpg * expected_starts        (1, or a projected 2)
  RP     : forward_fpg * expected_appearances   (~games * 0.45)

Start inference: confirmed probables drive the count; where a pitcher has one
confirmed early-week start, we project a 2nd start one rotation turn (5d) later
IF the team has a game in that window within the week. Projected starts are LABELED.

The NEEDS report (data/processed/lineup_needs.json) is the handoff to /waivers:
per-slot "bar to beat" EWP, unfilled slots, thin roles, IL-driven openings, start-cap
room, and roster fullness (for drop math). /waivers fills the holes it names.

DESKTOP/cloud both fine - reads committed caches only, no network.
"""
import argparse, csv, json, os, re, sys, unicodedata
import datetime as dt
import pandas as pd
import numpy as np

# ordered hitter slots for optimal matching; UT accepts any hitter
HIT_SLOTS = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UT"]
SP_SLOTS, RP_SLOTS, START_CAP, TURN = 6, 3, 12, 5
ELIGIBLE_STATUS = {"active", "reserve"}
RP_APPEAR_RATE = 0.45   # relievers appear in ~45% of team games (rough)
ROSTER_LIMIT = 40       # Fantrax dynasty roster cap; at/above => an add needs a drop

# Fantrax -> MLB Stats API abbreviation aliases. Extend from the miss report.
TEAM_ALIAS = {"CHW": "CWS", "OAK": "ATH", "AZ": "ARI", "WAS": "WSH", "TBR": "TB",
              "KCR": "KC", "SDP": "SD", "SFG": "SF", "WSN": "WSH", "CHW ": "CWS"}


def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(pos):
    return [t.strip().upper() for t in str(pos).split(",") if t.strip()]


def load_schedule(path):
    df = pd.read_csv(path, dtype=str).fillna("")
    games, dates = {}, {}
    week_end = None
    for _, r in df.iterrows():
        t = r["team"].strip()
        games[t] = int(float(r["games_this_week"] or 0))
        dates[t] = [d for d in r.get("game_dates", "").split(";") if d]
        if r.get("week_end"):
            week_end = dt.date.fromisoformat(r["week_end"])
    return games, dates, week_end


def load_probables(path):
    if not path or not os.path.exists(path):
        return {}
    df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
    out = {}
    for _, r in df.iterrows():
        out[norm_name(r["pitcher"])] = {
            "team": r["team"].strip(),
            "dates": [d for d in r.get("start_dates", "").split(";") if d],
            "n": int(float(r["starts_this_week"] or 0)),
        }
    return out


def resolve_team(ft, sched_games):
    ft = str(ft).strip()
    if ft in sched_games:
        return ft, True
    al = TEAM_ALIAS.get(ft)
    if al and al in sched_games:
        return al, True
    return ft, False


def infer_starts(name, sched_team, games, dates, week_end, probables):
    """Return (expected_starts, label)."""
    rec = probables.get(norm_name(name))
    if rec and rec["n"] >= 2:
        return rec["n"], "confirmed"
    if rec and rec["n"] == 1 and week_end is not None:
        try:
            d0 = min(dt.date.fromisoformat(d) for d in rec["dates"])
        except ValueError:
            return 1, "confirmed"
        turn = d0 + dt.timedelta(days=TURN)
        tg = []
        for x in dates.get(sched_team, []):
            try:
                tg.append(dt.date.fromisoformat(x))
            except ValueError:
                pass
        if turn <= week_end and any(abs((turn - g).days) <= 1 for g in tg):
            return 2, "projected"
        return 1, "confirmed"
    return (1 if games.get(sched_team, 0) > 0 else 0), "assumed"


def make_rec(r, games, dates, week_end, probables):
    """Build one player's lineup record (EWP + detail). Shared by the roster pool
    build and the /waivers FA pool build, so both value players identically."""
    sched_team, ok = resolve_team(r.get("team", ""), games)
    gw = games.get(sched_team, 0)
    ffpg = float(r.get("forward_fpg") or 0) if pd.notna(r.get("forward_fpg")) else 0.0
    pr = float(r.get("play_rate") or 1.0) if pd.notna(r.get("play_rate")) else 1.0
    role = str(r.get("role", "H"))
    rec = {"player": r["player"], "team": r.get("team", ""), "sched_team": sched_team,
           "sched_ok": ok, "pos": r.get("position", ""),
           "tok": tokens(r.get("position", "")), "role": role, "ffpg": ffpg,
           "play_rate": pr, "games": gw, "status": r.get("roster_status", ""),
           "age": r.get("age", ""), "dynasty": r.get("dynasty_score", ""),
           "win_now": r.get("win_now_score", ""), "fpts": r.get("fpts", ""),
           "ros_vor": r.get("ros_vor", "")}
    if role == "H":
        rec["ewp"] = ffpg * gw * pr
        rec["detail"] = f"{gw} games"
    elif role in ("SP", "SP/RP"):
        st, lab = infer_starts(r["player"], sched_team, games, dates, week_end, probables)
        rec["starts"], rec["start_label"] = st, lab
        rec["ewp"] = ffpg * st
        rec["detail"] = f"{st} start{'s' if st != 1 else ''} ({lab})"
    else:  # RP
        ap = round(gw * RP_APPEAR_RATE)
        rec["ewp"] = ffpg * ap
        rec["detail"] = f"~{ap} apps"
    return rec, ok


def _numv(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_pool(df_all, games, dates, week_end, probables, team):
    """Return (players, misses, il_excluded) for one team's startable pool.
    il_excluded = players dropped by the health layer (MLB IL), each carrying their
    asset value + a HOLD flag so a stud (Meyer) reads as 'IR and hold', not 'replace'."""
    from health import apply_health
    df = df_all[df_all["owner_status"].astype(str).str.fullmatch(team, case=False, na=False)]
    df = df[df["roster_status"].astype(str).str.lower().isin(ELIGIBLE_STATUS)].copy()
    df = apply_health(df)
    il_excluded = [{"player": r["player"], "win_now": _numv(r.get("win_now_score")),
                    "dynasty": _numv(r.get("dynasty_score")),
                    "hold": _numv(r.get("win_now_score")) >= 60
                            or _numv(r.get("dynasty_score")) >= 55}
                   for _, r in df[df["health_excluded"]].iterrows()]
    df = df[~df["health_excluded"]].copy()

    players, misses = [], []
    for _, r in df.iterrows():
        rec, ok = make_rec(r, games, dates, week_end, probables)
        if not ok:
            misses.append((r["player"], r.get("team", "")))
        players.append(rec)
    return players, misses, il_excluded


# ------------------------------------------------------------------ assignment
def optimal_hitters(hitters, slots=HIT_SLOTS):
    """Max-weight assignment of hitters to slots respecting multi-position
    eligibility. Exact (DP over ordered slots + used-player bitmask), capped to a
    realistic candidate set so it stays instant. Returns list of (slot, rec|None)."""
    order = sorted(range(len(hitters)), key=lambda i: -hitters[i]["ewp"])
    cand = order[:min(len(order), len(slots) + 5)]   # only plausible starters
    bit = {p: b for b, p in enumerate(cand)}

    def eligible(pi, slot):
        return slot == "UT" or slot in hitters[pi]["tok"]

    memo = {}

    def solve(si, used):
        if si == len(slots):
            return 0.0, []
        key = (si, used)
        if key in memo:
            return memo[key]
        best_v, best_a = solve(si + 1, used)          # leave this slot empty
        best_a = [(slots[si], None)] + best_a
        for pi in cand:
            b = 1 << bit[pi]
            if (used & b) or not eligible(pi, slots[si]):
                continue
            v, a = solve(si + 1, used | b)
            v += hitters[pi]["ewp"]
            if v > best_v:
                best_v, best_a = v, [(slots[si], pi)] + a
        memo[key] = (best_v, best_a)
        return memo[key]

    _, assign = solve(0, 0)
    return [(slot, hitters[pi] if pi is not None else None) for slot, pi in assign]


def assign_pitchers(players):
    sp = sorted([p for p in players if p["role"] in ("SP", "SP/RP")],
                key=lambda p: -p["ewp"])
    sp_lineup, starts_used, sp_used = [], 0, set()
    for p in sp:
        if len(sp_lineup) >= SP_SLOTS:
            break
        st = p.get("starts", 1)
        if starts_used + st > START_CAP:
            continue
        sp_lineup.append(("SP", p)); starts_used += st; sp_used.add(p["player"])
    rp_cands = sorted([p for p in players if p["role"] == "RP"
                       or (p["role"] == "SP/RP" and p["player"] not in sp_used)],
                      key=lambda p: -p["ewp"])
    rp_lineup = [("RP", p) for p in rp_cands[:RP_SLOTS]]
    return sp_lineup, rp_lineup, starts_used


# --------------------------------------------------------------------- needs
def _startable(players, roles):
    return sum(1 for p in players if p["role"] in roles)


def diagnose_needs(hit_lineup, sp_lineup, rp_lineup, players, week_end,
                   il_excluded, roster_count):
    """Structured needs report -> the /waivers handoff. Each slot carries the
    'bar to beat' (current starter EWP; 0 if empty) and the eligibility an FA needs."""
    slots = []
    for slot, rec in hit_lineup:
        elig = "H" if slot == "UT" else slot        # UT = any hitter
        slots.append({"slot": slot, "role": "H", "eligible": elig,
                      "filled": rec is not None,
                      "player": rec["player"] if rec else None,
                      "bar_ewp": round(rec["ewp"], 1) if rec else 0.0})
    for i in range(SP_SLOTS):
        rec = sp_lineup[i][1] if i < len(sp_lineup) else None
        slots.append({"slot": "SP", "role": "SP", "eligible": "SP",
                      "filled": rec is not None,
                      "player": rec["player"] if rec else None,
                      "bar_ewp": round(rec["ewp"], 1) if rec else 0.0})
    for i in range(RP_SLOTS):
        rec = rp_lineup[i][1] if i < len(rp_lineup) else None
        slots.append({"slot": "RP", "role": "RP", "eligible": "RP",
                      "filled": rec is not None,
                      "player": rec["player"] if rec else None,
                      "bar_ewp": round(rec["ewp"], 1) if rec else 0.0})

    thin = []
    for role_name, roles, n in (("H", {"H"}, 9), ("SP", {"SP", "SP/RP"}, SP_SLOTS),
                                ("RP", {"RP", "SP/RP"}, RP_SLOTS)):
        have = _startable(players, roles)
        if have <= n:
            thin.append({"role": role_name, "startable": have, "slots": n})

    starts_used = sum(p.get("starts", 0) for _, p in sp_lineup)
    return {
        "team": None, "week_end": str(week_end),
        "slots": slots,
        "unfilled": [s for s in slots if not s["filled"]],
        "thin_roles": thin,
        "il_openings": il_excluded,
        "start_cap": {"used": starts_used, "cap": START_CAP,
                      "room": max(0, START_CAP - starts_used)},
        "roster_count": roster_count, "roster_limit": ROSTER_LIMIT,
        "roster_full": roster_count >= ROSTER_LIMIT,
    }


def roster_view(df_all, team, players, started, il_lag):
    """Print the WHOLE 40-man roster grouped by slot type, with each player's Fantrax
    position eligibility. Covers the parts the lineup optimizer drops: reserves, the
    IL-lag guys to move to IR, Fantrax Inj Res, and the minor-league farm."""
    kipp = df_all[df_all["owner_status"].astype(str)
                  .str.fullmatch(team, case=False, na=False)].copy()
    rs = kipp["roster_status"].astype(str).str.lower()
    n_act = int((rs == "active").sum())
    n_res = int((rs == "reserve").sum())
    inj = kipp[rs.str.contains("inj", na=False)]
    minors = kipp[rs.str.contains("minor", na=False)]

    print(f"\n=== FULL ROSTER ({len(kipp)})  -  Active {n_act} · Reserve {n_res} · "
          f"Inj Res {len(inj)} · Minors {len(minors)}   (ELIG = Fantrax-eligible slots) ===")

    bench = sorted([p for p in players if p["player"] not in started],
                   key=lambda x: -x["ewp"])
    if bench:
        print("RESERVE / BENCH (startable, not in the optimal 18):")
        for p in bench:
            print(f"   {p['player']:<22} {str(p['pos']):<9} {p['detail']:<18} "
                  f"EWP {p['ewp']:>5.1f}")

    if il_lag:
        print("MLB IL but active on Fantrax -> MOVE TO IR (frees a startable slot):")
        for x in sorted(il_lag, key=lambda z: -z["win_now"]):
            tag = "HOLD" if x["hold"] else "low value"
            print(f"   {x['player']:<22} win {x['win_now']:.0f}/dyn {x['dynasty']:.0f}"
                  f"  ({tag})")

    def _line(r):
        return (f"   {r['player']:<22} {str(r.get('position', '')):<9} "
                f"dyn {_numv(r.get('dynasty_score')):>4.0f}  win {_numv(r.get('win_now_score')):>4.0f}"
                f"  {int(_numv(r.get('age')))}yo")
    if len(inj):
        print("INJURED RESERVE (Fantrax Inj Res -- IL slot, not startable):")
        for _, r in inj.sort_values("dynasty_score", ascending=False).iterrows():
            print(_line(r))
    if len(minors):
        print(f"MINORS / FARM ({len(minors)}):")
        for _, r in minors.sort_values("dynasty_score", ascending=False).iterrows():
            print(_line(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--schedule", default="data/schedule/team_schedule.csv")
    ap.add_argument("--probables", default="data/schedule/probable_starts.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--outdir", default="data/processed")
    a = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    games, dates, week_end = load_schedule(a.schedule)
    probables = load_probables(a.probables)
    df_all = pd.read_csv(a.ratings)
    roster_count = int((df_all["owner_status"].astype(str)
                        .str.fullmatch(a.team, case=False, na=False)).sum())
    players, misses, il_excluded = build_pool(df_all, games, dates, week_end,
                                              probables, a.team)

    hitters = [p for p in players if p["role"] == "H"]
    hit_lineup = optimal_hitters(hitters)
    sp_lineup, rp_lineup, _ = assign_pitchers(players)
    starts_used = sum(p.get("starts", 0) for _, p in (sp_lineup + rp_lineup))

    full = [(s, r) for s, r in hit_lineup if r] + sp_lineup + rp_lineup
    started = {p["player"] for _, p in full}
    total = sum(p["ewp"] for _, p in full)

    print(f"\n=== {a.team} - schedule-aware lineup, week ending {week_end} ===")
    print(f"{'SLOT':<5} {'PLAYER':<22} {'TEAM':<4} {'ELIG':<9} {'THIS WEEK':<20} {'EWP':>6}")
    print("-" * 68)
    def _row(slot, rec, empty):
        if rec:
            print(f"{slot:<5} {rec['player']:<22} {str(rec['team']):<4} "
                  f"{str(rec['pos']):<9} {rec['detail']:<20} {rec['ewp']:>6.1f}")
        else:
            print(f"{slot:<5} {'-- UNFILLED --':<22} {'':<4} {'':<9} {empty:<20} {0.0:>6.1f}")
    for slot, rec in hit_lineup:
        _row(slot, rec, "no eligible hitter")
    for slot, p in sp_lineup:
        _row(slot, p, "")
    for _ in range(len(sp_lineup), SP_SLOTS):
        _row("SP", None, "no eligible starter")
    for slot, p in rp_lineup:
        _row(slot, p, "")
    for _ in range(len(rp_lineup), RP_SLOTS):
        _row("RP", None, "no eligible reliever")
    print("-" * 68)
    print(f"{'TOTAL expected weekly points':<55}{total:>9.1f}")
    print(f"projected SP starts: {starts_used} / {START_CAP} cap", end="")
    print(f"   ({START_CAP - starts_used} under)" if starts_used < START_CAP else "")

    needs = diagnose_needs(hit_lineup, sp_lineup, rp_lineup, players, week_end,
                           il_excluded, roster_count)
    needs["team"] = a.team

    print("\n=== LINEUP NEEDS (what /waivers should fill) ===")
    unfilled = needs["unfilled"]
    if unfilled:
        print("OPENINGS (unfilled = 0 pts, must fill regardless of posture):")
        for s in unfilled:
            print(f"   {s['slot']:<4} needs a {s['eligible']} -- currently 0 EWP")
    else:
        print("No unfilled slots -- lineup is fully fielded.")
    if needs["thin_roles"]:
        print("THIN (one injury from an unfillable slot):")
        for t in needs["thin_roles"]:
            print(f"   {t['role']}: {t['startable']} startable for {t['slots']} slots")
    if il_excluded:
        print("IL (your injured players -- IR them; the slot streams until they RETURN, "
              "you don't permanently replace a hold):")
        for x in sorted(il_excluded, key=lambda z: -z["win_now"]):
            note = ("HOLD -- top asset, returns to this slot; do NOT drop"
                    if x["hold"] else "low value -- droppable if you need the spot")
            print(f"   {x['player']:<20} win {x['win_now']:.0f}/dyn {x['dynasty']:.0f}"
                  f"  -- {note}")
    room = needs["start_cap"]["room"]
    if room:
        print(f"CAP ROOM: {room} of {START_CAP} SP starts unused -- room to stream "
              f"{room} more start(s).")
    print(f"ROSTER: {roster_count}/{ROSTER_LIMIT}"
          + (" (FULL -- every add needs a drop)" if needs["roster_full"]
             else f" ({ROSTER_LIMIT - roster_count} open spot(s))"))

    roster_view(df_all, a.team, players, started, il_excluded)

    proj = [p for _, p in sp_lineup if p.get("start_label") == "projected"]
    if proj:
        print("\nVERIFY ON ESPN (projected 2nd start - not yet posted):")
        for p in proj:
            print(f"   {p['player']} ({p['team']}) - projected 2 starts")
    if misses:
        print("\nUNMATCHED TEAMS (add to TEAM_ALIAS):")
        for nm, tc in misses:
            print(f"   {nm}: team code '{tc}' not in schedule cache")

    os.makedirs(a.outdir, exist_ok=True)
    outpath = os.path.join(a.outdir, "lineup_recommendation.csv")
    with open(outpath, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slot", "player", "team", "this_week", "ewp"])
        for slot, p in full:
            w.writerow([slot, p["player"], p["team"], p["detail"], round(p["ewp"], 1)])
    needs_path = os.path.join(a.outdir, "lineup_needs.json")
    with open(needs_path, "w", encoding="utf-8") as fh:
        json.dump(needs, fh, indent=2)
    print(f"\n[ok] wrote {outpath}")
    print(f"[ok] wrote {needs_path}  (the /waivers handoff)")


if __name__ == "__main__":
    main()
