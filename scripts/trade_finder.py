#!/usr/bin/env python3
"""
trade_finder.py - propose trade packages with each plausible COUNTERPARTY that are
favorable to us AND rational for them.

The engine is dual valuation: a player is worth different amounts to different teams
depending on competitive POSTURE. A contender weights win-now; a rebuilder weights
dynasty. The structural edge for a rebuilder: our win-now surplus (aging vets) is
near-worthless to US but valuable to a contender, and their young surplus is
spendable to THEM but gold to us. A package "works for both" when, valued through
each side's own posture, each side comes out fair-or-ahead.

HARD LIMIT: we can't know a GM's private valuation. This proposes offers that are
rational by OBSERVABLE info (posture from standings, rosters from the export, model
values) -- "a rational GM in their seat should consider it," not "guaranteed yes."

Reads current_player_ratings.csv only. No network.
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

OWNERS = {"CLANK", "Coop", "GoldTY", "Greenbet", "Hutch", "JMerkle", "Jpanner",
          "KRetiree", "Kipp", "Sasso", "Sethmc44", "joeybats", "kyfaess", "zyoung51"}

# posture -> how much a team weights win-now vs dynasty when valuing a player.
# appetite 1.0 = pure win-now (all-in contender); 0.0 = pure future (deep rebuild).
APPETITE = {"contend": 0.80, "retool": 0.55, "rebuild": 0.20}
STARTERS = 18                      # top-N that define "now strength"
SLOTS = {"H": 9, "SP": 6, "RP": 3}
ROLE_MEMBERS = {"SP": {"SP", "SP/RP"}, "RP": {"RP", "SP/RP"}, "H": {"H"}}


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.Series(
        np.nan, index=df.index)


def _not_minors(df):
    return ~df.get("roster_status", pd.Series("", index=df.index)).astype(
        str).str.lower().str.contains("minor", na=False)


def team_table(df):
    """Per owner: now-strength (top-18 win_now), future-strength (top-18 dynasty),
    ranks, and an inferred win-now appetite."""
    df = df[df["owner_status"].isin(OWNERS)].copy()
    rows = []
    for owner, g in df.groupby("owner_status"):
        active = g[_not_minors(g)]
        now = active["win_now_score"].nlargest(STARTERS).sum()
        fut = g["dynasty_score"].nlargest(STARTERS).sum()
        rows.append({"owner": owner, "now": now, "fut": fut})
    t = pd.DataFrame(rows)
    t["now_rank"] = t["now"].rank(ascending=False).astype(int)
    t["fut_rank"] = t["fut"].rank(ascending=False).astype(int)
    n = len(t)
    # appetite: strong-now OR now-stronger-than-future -> wants to win now.
    # blends standing (top third = contender) with the now-vs-future tilt.
    now_pct = 1 - (t["now_rank"] - 1) / max(n - 1, 1)          # 1.0 = best now
    tilt = (t["fut_rank"] - t["now_rank"]) / max(n - 1, 1)      # +ve = better now than future
    t["appetite"] = (0.5 * now_pct + 0.5 * (0.5 + tilt)).clip(0.15, 0.9).round(2)
    return t.sort_values("now_rank").reset_index(drop=True)


def val(row, appetite):
    return appetite * row["win_now_score"] + (1 - appetite) * row["dynasty_score"]


def find_packages(df, me, my_appetite, partner, p_app, n_targets=2, max_send=3):
    """Build a balanced package: anchor on the young pieces we covet from the
    partner, then add our sheddable win-now until the partner comes out fair by
    THEIR appetite. Verify we come out ahead by OURS."""
    mine = df[df["owner_status"] == me].copy()
    theirs = df[df["owner_status"] == partner].copy()

    # what we'd want from them: young (<=27) high-dynasty pieces
    want = theirs[(_num(theirs, "age") <= 27) | ~_not_minors(theirs)]
    want = want.sort_values("dynasty_score", ascending=False).head(6)
    # what we'd send: our win-now surplus -- high win_now, NOT young keepers
    keep = (_num(mine, "age") < 29) & (mine["dynasty_score"] >= 60)
    send_pool = mine[_not_minors(mine) & ~keep & (
        mine["win_now_score"] > mine["dynasty_score"] + 5)]
    send_pool = send_pool.sort_values("win_now_score", ascending=False)
    if want.empty or send_pool.empty:
        return None

    # anchor on the single best young target, then add a 2nd if value allows
    target = want.iloc[0]
    R = [target]
    if len(want) > 1 and val(want.iloc[1], p_app) + val(target, p_app) < \
            send_pool.head(max_send).apply(lambda r: val(r, p_app), axis=1).sum():
        R.append(want.iloc[1])
    r_to_partner = sum(val(r, p_app) for r in R)

    # greedily add our pieces until the partner is fair-or-ahead by THEIR appetite
    S, s_to_partner = [], 0.0
    for _, r in send_pool.iterrows():
        if s_to_partner >= r_to_partner or len(S) >= max_send:
            break
        S.append(r)
        s_to_partner += val(r, p_app)
    if not S:
        return None

    return {
        "R": R, "S": S,
        "r_them": r_to_partner, "s_them": s_to_partner,
        "r_me": sum(val(r, my_appetite) for r in R),
        "s_me": sum(val(r, my_appetite) for r in S),
    }


def _startable(team_df, role):
    return int(_not_minors(team_df[team_df["role"].isin(ROLE_MEMBERS[role])]).sum())


def _role_of(r):
    if r["role"] in ROLE_MEMBERS["SP"]:
        return "SP"
    return "RP" if r["role"] in ROLE_MEMBERS["RP"] else "H"


def vet_package(df, me, partner, S, R):
    """Run a candidate package through every CHECK WE CAN COMPUTE. Returns a list of
    (name, hard, ok, detail). hard=True means a failure should KILL the package
    (guts your roster / they don't need it); hard=False is a flag to verify. The
    unknowable factors (their true valuation, willingness) are NOT here -- they are
    surfaced separately as residual risk, never scored."""
    mine, theirs = df[df["owner_status"] == me], df[df["owner_status"] == partner]
    send = {r["player"] for r in S}
    mine_after = mine[~mine["player"].isin(send)]
    checks, send_roles = [], {_role_of(r) for r in S}

    # HARD 1 -- your cover: don't trade into a roster you can't field
    for role in ("SP", "RP", "H"):
        if role in send_roles:
            left = _startable(mine_after, role)
            checks.append((f"your {role} cover", True, left >= SLOTS[role],
                           f"{left} startable {role} left vs {SLOTS[role]} slots"
                           + ("" if left >= SLOTS[role] else " -- this guts you")))

    # HARD 2 -- their need: are they already stacked where you're sending?
    for role in send_roles:
        cnt = _startable(theirs, role)
        need = cnt <= SLOTS[role] + 1
        checks.append((f"their {role} need", True, need,
                       f"they have {cnt} startable {role}"
                       + ("" if need else " -- STACKED, won't value it")))

    # SOFT -- is each target a redundancy (movable) or their scarce cornerstone?
    for r in R:
        role = _role_of(r)
        depth = _startable(theirs, role)
        checks.append((f"{r['player']} movable", False, depth > SLOTS[role],
                       f"they have {depth} at {role}"
                       + ("" if depth > SLOTS[role] else " -- scarce, may not move him")))

    # SOFT -- injuries in the package change the math
    hurt = [r["player"] for r in (S + R)
            if any(k in str(r.get("roster_status", "")).lower()
                   for k in ("inj", "il", "60-day", "dl"))]
    checks.append(("injuries", False, not hurt,
                   "none flagged" if not hurt else f"{', '.join(hurt)} -- re-value"))
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--posture", default="rebuild",
                    choices=["rebuild", "retool", "contend"])
    ap.add_argument("--partners", type=int, default=3, help="how many to workshop")
    a = ap.parse_args()

    if not os.path.exists(a.ratings):
        sys.exit(f"[trade] ratings not found: {a.ratings}")
    df = pd.read_csv(a.ratings, encoding="utf-8")
    for c in ("win_now_score", "dynasty_score", "age"):
        df[c] = _num(df, c)
    my_app = APPETITE[a.posture]

    t = team_table(df)
    me = t[t["owner"] == a.team]
    if me.empty:
        sys.exit(f"[trade] {a.team!r} not found among owners")
    print(f"=== {a.team}: now #{int(me.iloc[0].now_rank)} / future "
          f"#{int(me.iloc[0].fut_rank)}  (posture {a.posture}, appetite {my_app}) ===")

    # natural partners for a rebuilder = the hungriest win-now teams (high appetite)
    partners = t[(t["owner"] != a.team)].sort_values("appetite", ascending=False)
    print("\nMost natural partners (highest win-now appetite -> will pay youth for "
          "your win-now):")
    print(partners.head(a.partners)[["owner", "now_rank", "fut_rank",
                                     "appetite"]].to_string(index=False))

    for _, p in partners.head(a.partners).iterrows():
        pk = find_packages(df, a.team, my_app, p["owner"], p["appetite"])
        print(f"\n{'-'*64}\n{p['owner']}  (appetite {p['appetite']}, "
              f"now #{int(p['now_rank'])})")
        if not pk:
            print("  no complementary package (no fit between your surplus and "
                  "their youth)")
            continue
        give = ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                         f"{int(r.dynasty_score)}dy)" for r in pk["S"])
        get = ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                        f"{int(r.dynasty_score)}dy)" for r in pk["R"])
        print(f"  YOU SEND : {give}")
        print(f"  YOU GET  : {get}")
        print(f"  by THEIR appetite: they receive {pk['s_them']:.0f} for "
              f"{pk['r_them']:.0f} given  -> {'FAIR+' if pk['s_them'] >= pk['r_them'] else 'short'}")
        print(f"  by YOUR  appetite: you receive {pk['r_me']:.0f} for "
              f"{pk['s_me']:.0f} given  -> {'WIN' if pk['r_me'] > pk['s_me'] else 'flat'} "
              f"(+{pk['r_me'] - pk['s_me']:.0f})")
        # value margin: barely-fair to them is the FLOOR, not a yes
        margin = (pk["s_them"] - pk["r_them"]) / max(pk["r_them"], 1)
        if 0 <= margin < 0.08:
            print(f"  value margin to them only +{margin*100:.0f}% -- barely fair; "
                  f"since your win-now is cheap, consider sweetening to seal it")

        checks = vet_package(df, a.team, p["owner"], pk["S"], pk["R"])
        hard_fail = [c for c in checks if c[1] and not c[2]]
        print("  VET:")
        for name, hard, ok, detail in checks:
            mark = "OK " if ok else ("XX" if hard else "?? ")
            print(f"    [{mark}] {name}: {detail}")
        if hard_fail:
            print(f"  VERDICT: KILLED -- fails {', '.join(c[0] for c in hard_fail)}. "
                  f"Don't propose as-is.")
        else:
            print("  VERDICT: passes every computable check. RESIDUAL (unknowable, "
                  "verify yourself): does he value his guys as the model does, and "
                  "will he deal at all?")
    print("\n[trade] computable checks are vetted above; the counterparty's true "
          "valuation and willingness are NOT calculable -- they're flagged, not faked.")


if __name__ == "__main__":
    main()
