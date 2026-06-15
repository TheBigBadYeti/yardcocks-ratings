#!/usr/bin/env python3
"""
optimize_lineup.py - schedule-aware weekly lineup optimizer (Yardcocks & Beyond)

Recommends the active 18-man lineup that maximizes expected points for the week,
under the 12-start cap. Reads the ratings file + the schedule cache.

Slots: C,1B,2B,3B,SS,OF,OF,OF,UT (9 hitters), 6x SP, 3x RP.
Eligible pool = roster_status in {Active, Reserve}; Inj Res / Minors excluded.

Value model (expected weekly points, EWP):
  hitter : forward_fpg * games_this_week * play_rate
  SP     : forward_fpg * expected_starts        (1, or a projected 2)
  RP     : forward_fpg * expected_appearances   (~games * 0.45)

Start inference: confirmed probables drive the count; where a pitcher has one
confirmed early-week start, we project a 2nd start one rotation turn (5d) later
IF the team has a game in that window within the week. Projected starts are
LABELED - verify the borderline ones on ESPN's 10-day forecaster before locking.

DESKTOP/cloud both fine - reads committed caches only, no network.
"""
import argparse, csv, os, re, sys, unicodedata
import datetime as dt
import pandas as pd
import numpy as np

HIT_SCARCITY = ["C", "SS", "2B", "3B", "1B", "OF", "OF", "OF", "UT"]  # fill scarce first
SP_SLOTS, RP_SLOTS, START_CAP, TURN = 6, 3, 12, 5
ELIGIBLE_STATUS = {"active", "reserve"}
RP_APPEAR_RATE = 0.45   # relievers appear in ~45% of team games (rough)

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


def build_pool(ratings, games, dates, week_end, probables, team):
    df = pd.read_csv(ratings)
    df = df[df["owner_status"].astype(str).str.fullmatch(team, case=False, na=False)]
    df = df[df["roster_status"].astype(str).str.lower().isin(ELIGIBLE_STATUS)].copy()

    players, misses = [], []
    for _, r in df.iterrows():
        sched_team, ok = resolve_team(r.get("team", ""), games)
        if not ok:
            misses.append((r["player"], r.get("team", "")))
        gw = games.get(sched_team, 0)
        ffpg = float(r.get("forward_fpg") or 0) if pd.notna(r.get("forward_fpg")) else 0.0
        pr = float(r.get("play_rate") or 1.0) if pd.notna(r.get("play_rate")) else 1.0
        role = str(r.get("role", "H"))
        rec = {"player": r["player"], "team": r.get("team", ""), "sched_team": sched_team,
               "pos": r.get("position", ""), "tok": tokens(r.get("position", "")),
               "role": role, "ffpg": ffpg, "play_rate": pr, "games": gw,
               "status": r.get("roster_status", "")}
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
        players.append(rec)
    return players, misses


def assign_hitters(hitters):
    used, lineup = set(), []
    for slot in HIT_SCARCITY:
        best = None
        for h in hitters:
            if h["player"] in used:
                continue
            if slot == "UT" or slot in h["tok"]:
                if best is None or h["ewp"] > best["ewp"]:
                    best = h
        if best:
            used.add(best["player"])
            lineup.append((slot, best))
    # one improvement pass: swap a benched hitter in if it raises total for its slot
    improved = True
    while improved:
        improved = False
        for i, (slot, cur) in enumerate(lineup):
            for h in hitters:
                if h["player"] in used:
                    continue
                if (slot == "UT" or slot in h["tok"]) and h["ewp"] > cur["ewp"]:
                    used.discard(cur["player"]); used.add(h["player"])
                    lineup[i] = (slot, h); cur = h; improved = True
    return lineup, used


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--schedule", default="data/schedule/team_schedule.csv")
    ap.add_argument("--probables", default="data/schedule/probable_starts.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--outdir", default="data/processed")
    a = ap.parse_args()

    games, dates, week_end = load_schedule(a.schedule)
    probables = load_probables(a.probables)
    players, misses = build_pool(a.ratings, games, dates, week_end, probables, a.team)

    hitters = [p for p in players if p["role"] == "H"]
    hit_lineup, hit_used = assign_hitters(hitters)
    sp_lineup, rp_lineup, _ = assign_pitchers(players)
    starts_used = sum(p.get("starts", 0) for _, p in (sp_lineup + rp_lineup))

    full = hit_lineup + sp_lineup + rp_lineup
    started = {p["player"] for _, p in full}
    total = sum(p["ewp"] for _, p in full)

    print(f"\n=== {a.team} - schedule-aware lineup, week ending {week_end} ===")
    print(f"{'SLOT':<5} {'PLAYER':<22} {'TEAM':<5} {'THIS WEEK':<22} {'EWP':>7}")
    print("-" * 64)
    for slot, p in full:
        print(f"{slot:<5} {p['player']:<22} {str(p['team']):<5} {p['detail']:<22} {p['ewp']:>7.1f}")
    print("-" * 64)
    print(f"{'TOTAL expected weekly points':<55}{total:>9.1f}")
    print(f"projected SP starts: {starts_used} / {START_CAP} cap", end="")
    if starts_used < START_CAP:
        print(f"   ({START_CAP - starts_used} under - room to stream a 2-start arm)")
    else:
        print()

    bench = [p for p in players if p["player"] not in started]
    if bench:
        print("\nBENCH (eligible, not started):")
        for p in sorted(bench, key=lambda x: -x["ewp"]):
            print(f"   {p['player']:<22} {str(p['team']):<5} {p['detail']:<22} {p['ewp']:>7.1f}")

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
    print(f"\n[ok] wrote {outpath}")


if __name__ == "__main__":
    main()
