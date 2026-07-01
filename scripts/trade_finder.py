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

try:                                    # negotiation memory is optional
    import trade_log
except Exception:
    trade_log = None


def _history(partner):
    if trade_log is None:
        return ""
    block = trade_log.context_block(partner)
    return ("\n" + block + "\n") if block else ""

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


def _max_sendable(mine, role):
    """How many at a role we can ship before dropping below our own slot floor."""
    return max(0, _startable(mine, role) - SLOTS[role])


def _build(targets, send_pool, my_app, p_app, cap_by_role):
    """Minimal package: take the fewest win-now pieces (largest-first) that make the
    partner fair by THEIR appetite, without exceeding our per-role send cap."""
    R = list(targets)
    r_them = sum(val(r, p_app) for r in R)
    S, s_them, used = [], 0.0, {"SP": 0, "RP": 0, "H": 0}
    for _, r in send_pool.iterrows():
        if s_them >= r_them:
            break
        role = _role_of(r)
        if used[role] >= cap_by_role.get(role, 99):
            continue                      # would gut our own roster at this role
        S.append(r); s_them += val(r, p_app); used[role] += 1
    if not S or s_them < r_them:
        return None                       # can't reach fair without gutting ourselves
    return {"R": R, "S": S, "r_them": r_them, "s_them": s_them,
            "r_me": sum(val(r, my_app) for r in R),
            "s_me": sum(val(r, my_app) for r in S)}


def find_packages(df, me, my_appetite, partner, p_app):
    """Generate several candidate constructions (anchor on 1 young piece, or 2) so a
    single greedy overshoot can't masquerade as 'no deal'. Returns a list; main vets
    each and surfaces the best SURVIVOR."""
    mine = df[df["owner_status"] == me].copy()
    theirs = df[df["owner_status"] == partner].copy()

    want = theirs[(_num(theirs, "age") <= 27) | ~_not_minors(theirs)]
    want = want.sort_values("dynasty_score", ascending=False).head(6)
    keep = (_num(mine, "age") < 29) & (mine["dynasty_score"] >= 60)
    send_pool = mine[_not_minors(mine) & ~keep & (
        mine["win_now_score"] > mine["dynasty_score"] + 5)]
    send_pool = send_pool.sort_values("win_now_score", ascending=False)
    if want.empty or send_pool.empty:
        return []

    cap = {role: _max_sendable(mine, role) for role in ("SP", "RP", "H")}
    cands, seen = [], set()
    for n in (1, 2):
        if len(want) < n:
            continue
        c = _build([want.iloc[i] for i in range(n)], send_pool, my_appetite, p_app, cap)
        if not c:
            continue
        key = (tuple(r["player"] for r in c["S"]), tuple(r["player"] for r in c["R"]))
        if key not in seen:
            seen.add(key); cands.append(c)
    return cands


def _startable(team_df, role):
    return int(_not_minors(team_df[team_df["role"].isin(ROLE_MEMBERS[role])]).sum())


def _marginal_starter(team_df, role, appetite):
    """Value of the partner's WEAKEST current starter at a role (their slot-th best,
    by their own posture weighting). If they roster fewer than slots at the role,
    they have a literal hole -> return 0 so anything decent reads as an upgrade.
    This is the honest 'need' signal: do they need an UPGRADE here, not how many
    bodies do they roster."""
    sub = team_df[team_df["role"].isin(ROLE_MEMBERS[role])].copy()
    sub = sub[_not_minors(sub)]
    if sub.empty:
        return 0.0
    v = (appetite * pd.to_numeric(sub["win_now_score"], errors="coerce")
         + (1 - appetite) * pd.to_numeric(sub["dynasty_score"], errors="coerce"))
    top = v.nlargest(SLOTS[role])
    return float(top.min()) if len(top) >= SLOTS[role] else 0.0


def _role_of(r):
    if r["role"] in ROLE_MEMBERS["SP"]:
        return "SP"
    return "RP" if r["role"] in ROLE_MEMBERS["RP"] else "H"


def vet_package(df, me, partner, p_app, S, R, r_me, s_me):
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

    # HARD 2 -- their need: would your guy UPGRADE their worst current starter?
    # (NOT "do they roster more arms than slots" -- every team does. Quality, not bodies.)
    for role in send_roles:
        sent_here = [r for r in S if _role_of(r) == role]
        best_sent = max(val(r, p_app) for r in sent_here)
        marginal = _marginal_starter(theirs, role, p_app)
        need = best_sent > marginal
        checks.append((f"their {role} need", True, need,
                       f"your best {role} ({best_sent:.0f}) vs their #{SLOTS[role]} "
                       f"starter ({marginal:.0f})"
                       + ("" if need else " -- no upgrade, won't value it")))

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

    # HARD 3 -- is this actually IN YOUR FAVOR? the entire point of the deal.
    # A package that's fair to them but flat/negative for you is not a deal you want.
    gain = r_me - s_me
    checks.append(("your value", True, gain > 0,
                   f"you {'gain' if gain > 0 else 'LOSE'} {gain:+.0f} by your own "
                   f"valuation" + ("" if gain > 0 else " -- works for them, not you")))
    return checks


# ---- shared helpers for the inbound (inquiry / offer) modes --------------------
HIT_SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1,
             "MI": 1, "CI": 1, "UT": 1}


def _resolve(df, name, owner=None):
    """Find one player row by case-insensitive substring; restrict to an owner if
    given. Fail loud on no-match or ambiguity rather than guess the wrong human."""
    sub = df[df["player"].str.contains(name, case=False, na=False)]
    if owner is not None:
        sub = sub[sub["owner_status"] == owner]
    if len(sub) == 0:
        sys.exit(f"[trade] no player matches '{name}'"
                 + (f" on {owner}" if owner else ""))
    if len(sub) > 1:
        exact = sub[sub["player"].str.lower() == name.lower()]
        if len(exact) == 1:
            return exact.iloc[0]
        sys.exit(f"[trade] '{name}' is ambiguous: {', '.join(sub['player'].head(6))}")
    return sub.iloc[0]


def _pos_tokens(s):
    return {p for p in str(s).replace(" ", "").split("/") if p}


def _positional_fit(mine, inc):
    """Does an INCOMING player slot somewhere usable, or pile onto a spot we're
    already deep at? Soft flag (multi-eligibility makes it fuzzy) -- never a kill."""
    inc_pos = _pos_tokens(inc.get("position", ""))
    if inc_pos & {"SP", "RP", "P"}:
        role = _role_of(inc)
        have = _startable(mine, role)
        deep = have > SLOTS[role] + 1
        return (not deep, f"you have {have} {role} (slots {SLOTS[role]})"
                + (" -- depth, not a need" if deep else " -- fills/usable"))
    mh = mine[_not_minors(mine)]
    have = sum(1 for _, r in mh.iterrows()
               if _pos_tokens(r.get("position", "")) & inc_pos)
    base = max((HIT_SLOTS.get(p, 1) for p in inc_pos), default=1)
    deep = have > base + 1
    ps = "/".join(sorted(inc_pos)) or "?"
    return (not deep, f"you have {have} at {ps} (slots ~{base})"
            + (" -- depth, not a need" if deep else " -- fills/usable"))


def _drop_candidates(mine, n, my_app):
    """The n lowest-value-to-us non-keepers -- surfaced for YOUR review, never an
    auto-cut. The tool flags that a drop is owed; which human to release is yours."""
    m = mine[_not_minors(mine)].copy()
    keep = (_num(m, "age") < 29) & (m["dynasty_score"] >= 60)
    pool = m[~keep].copy()
    if pool.empty:
        return "(no obvious cut -- everyone's a keeper; your call)"
    pool["v"] = pool.apply(lambda r: val(r, my_app), axis=1)
    return ", ".join(pool.nsmallest(n, "v")["player"].tolist())


def _gettability(theirs, row):
    """Read-only guess at whether THEY would part with a piece -- redundancy vs
    cornerstone. Unknowable in truth; this is a hint, flagged as such."""
    role = _role_of(row)
    if row["player"] in set(theirs.nlargest(3, "dynasty_score")["player"]):
        return "CORE (a top-3 dynasty piece for them) -- unlikely to move"
    if _startable(theirs, role) > SLOTS[role]:
        return f"has {role} depth -- more movable"
    return f"scarce at {role} for them -- may resist"


def vet_inbound(df, me, my_app, S, R):
    """Gauntlet for a deal where WE receive R and send S. Grades by OUR posture:
    fair = a value gain for us. Computable checks kill; judgment calls flag."""
    mine = df[df["owner_status"] == me]
    mine_after = mine[~mine["player"].isin({r["player"] for r in S})]
    checks, send_roles = [], {_role_of(r) for r in S}

    for role in ("SP", "RP", "H"):          # HARD -- don't gut your own roster
        if role in send_roles:
            left = _startable(mine_after, role)
            checks.append((f"your {role} cover", True, left >= SLOTS[role],
                           f"{left} startable {role} left vs {SLOTS[role]} slots"
                           + ("" if left >= SLOTS[role] else " -- this guts you")))

    s_me = sum(val(r, my_app) for r in S)   # HARD -- the fair bar: a gain for you
    r_me = sum(val(r, my_app) for r in R)
    checks.append(("fair value (your posture)", True, r_me > s_me,
                   f"you GET {r_me:.0f} for {s_me:.0f} given -> "
                   f"{'GAIN' if r_me > s_me else 'LOSS'} {r_me - s_me:+.0f}"
                   + ("" if r_me > s_me else " -- not a win for you")))

    for r in R:                             # SOFT -- positional fit on what you get
        ok, detail = _positional_fit(mine_after, r)
        checks.append((f"{r['player']} fit", False, ok, detail))

    net = len(R) - len(S)                   # SOFT -- roster-size / drop flag
    if net > 0:
        checks.append(("roster drop", False, False,
                       f"net +{net} player(s) -- you owe {net} drop(s). Bottom of your "
                       f"roster (YOUR call, not auto): {_drop_candidates(mine_after, net, my_app)}"))

    hurt = [r["player"] for r in (S + R)    # SOFT -- injuries change the math
            if any(k in str(r.get("roster_status", "")).lower()
                   for k in ("inj", "il", "60-day", "dl"))]
    checks.append(("injuries", False, not hurt,
                   "none flagged" if not hurt else f"{', '.join(hurt)} -- re-value"))
    return checks, r_me, s_me


def _print_vet(checks):
    hard_fail = [c for c in checks if c[1] and not c[2]]
    print("  VET:")
    for name, hard, ok, detail in checks:
        print(f"    [{'OK ' if ok else ('XX' if hard else '?? ')}] {name}: {detail}")
    return hard_fail


def mode_inquiry(df, me, my_app, partner, p_app, send_names):
    """They asked for YOUR player(s). What on THEIR roster clears the bar of a real
    value gain for you -- and is allowed to answer 'nothing here is worth it'."""
    S = [_resolve(df, nm, me) for nm in send_names]
    bar = sum(val(r, my_app) for r in S)
    sent = ", ".join(f"{r['player']} ({val(r, my_app):.0f} to you)" for r in S)
    print(f"=== INQUIRY: {partner} wants {sent} ===")
    print(f"Bar: a return must beat {bar:.0f} value-to-YOU ({me} posture) to be a gain.")
    print(f"{partner} posture read: appetite {p_app} "
          f"({'win-now' if p_app > 0.6 else 'rebuild' if p_app < 0.35 else 'middling'}).")
    print(_history(partner))

    theirs = df[df["owner_status"] == partner].copy()
    theirs["v_me"] = theirs.apply(lambda r: val(r, my_app), axis=1)
    theirs = theirs.sort_values("v_me", ascending=False)
    clears = theirs[theirs["v_me"] > bar]
    close = theirs[(theirs["v_me"] <= bar) & (theirs["v_me"] >= bar * 0.85)]

    if clears.empty:
        print("NOTHING on their roster beats the bar straight-up. Don't trade "
              f"{send_names[0]} here for a single piece -- hold, demand a sweetener "
              "(a clearing piece + an add-on), or walk and wait for a better buyer.")
        print("\nClosest they have (would need an add-on to clear):")
        for _, r in close.head(4).iterrows():
            print(f"  - {r['player']} ({int(r.age)}, {r.position}) "
                  f"v_me {r.v_me:.0f} | {_gettability(theirs, r)}")
    else:
        print("CLEARS THE BAR (a straight-up gain for you):")
        for _, r in clears.head(6).iterrows():
            print(f"  - {r['player']} ({int(r.age)}, {r.position}) "
                  f"v_me {r.v_me:.0f} (+{r.v_me - bar:.0f}) | {_gettability(theirs, r)}")
        best = clears.iloc[0]
        print(f"\nHeadline 1-for-1 vetted -- {S[0]['player']} for {best['player']}:")
        checks, r_me, s_me = vet_inbound(df, me, my_app, S, [best])
        hard = _print_vet(checks)
        print("  VERDICT: " + ("KILLED -- " + ", ".join(c[0] for c in hard)
              if hard else "passes; a real gain. Open by making HIM name the piece."))
        if len(close):
            print("\nNEEDS A SWEETENER (close but below the bar -- take only with an add-on):")
            for _, r in close.head(3).iterrows():
                print(f"  - {r['player']} ({int(r.age)}, {r.position}) v_me {r.v_me:.0f}")

    print("\n[trade] UNKNOWABLE (yours to verify): why he wants your guy, and whether "
          "he'll actually surrender the target. Let HIM open -- his bid prices your "
          "player better than the model can.")


def mode_offer(df, me, my_app, partner, p_app, send_names, get_names):
    """Grade a concrete package they put on the table: is it in YOUR favor and does
    it survive the gauntlet -- plus what it looks like from THEIR side, for realism."""
    S = [_resolve(df, nm, me) for nm in send_names]
    R = [_resolve(df, nm, partner) for nm in get_names]
    print(f"=== OFFER from {partner} ===")
    print(_history(partner), end="")
    print("  YOU SEND : " + ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                                       f"{int(r.dynasty_score)}dy)" for r in S))
    print("  YOU GET  : " + ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                                       f"{int(r.dynasty_score)}dy)" for r in R))
    checks, r_me, s_me = vet_inbound(df, me, my_app, S, R)
    s_them = sum(val(r, p_app) for r in S)
    r_them = sum(val(r, p_app) for r in R)
    print(f"  to YOU  ({me}): get {r_me:.0f} for {s_me:.0f} -> "
          f"{'GAIN' if r_me > s_me else 'LOSS'} {r_me - s_me:+.0f}")
    print(f"  to THEM ({partner}): get {s_them:.0f} for {r_them:.0f} -> "
          f"{'they gain' if s_them > r_them else 'they overpay'} {s_them - r_them:+.0f} "
          f"(if they're overpaying badly, ask what you're missing)")
    hard = _print_vet(checks)
    if hard:
        print("  VERDICT: DECLINE or COUNTER -- fails " + ", ".join(c[0] for c in hard))
    elif r_me - s_me < bar_margin(s_me):
        print("  VERDICT: COUNTER -- passes but the gain is thin; ask for a small add-on.")
    else:
        print("  VERDICT: ACCEPT-worthy -- a clear gain for you that survives the gauntlet. "
              "Confirm the received player's scoring fit, then pull the trigger.")
    print("\n[trade] computable checks vetted; their willingness is the only unknown left.")


def bar_margin(s_me):
    return max(3.0, 0.05 * s_me)            # "thin" gain threshold ~5% of what you give


def mode_outbound(df, a, my_app):
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

    any_survivor = False
    for _, p in partners.head(a.partners).iterrows():
        cands = find_packages(df, a.team, my_app, p["owner"], p["appetite"])
        print(f"\n{'-'*64}\n{p['owner']}  (appetite {p['appetite']}, "
              f"now #{int(p['now_rank'])})")
        if not cands:
            print("  no complementary package (no fit between your surplus and "
                  "their youth)")
            continue

        # vet every construction; separate survivors from killed
        vetted = []
        for c in cands:
            checks = vet_package(df, a.team, p["owner"], p["appetite"], c["S"], c["R"], c["r_me"], c["s_me"])
            hard_fail = [ck for ck in checks if ck[1] and not ck[2]]
            vetted.append((c, checks, hard_fail))
        survivors = [v for v in vetted if not v[2]]

        if survivors:
            any_survivor = True
            # best survivor = biggest win for us by our own appetite
            c, checks, _ = max(survivors, key=lambda v: v[0]["r_me"] - v[0]["s_me"])
            tag = f"  ({len(survivors)} of {len(cands)} constructions survived)"
        else:
            # show the least-bad killed one so you see WHY, honestly
            c, checks, _ = min(vetted, key=lambda v: len(v[2]))
            tag = "  (all constructions KILLED -- shown: closest to viable)"

        give = ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                         f"{int(r.dynasty_score)}dy)" for r in c["S"])
        get = ", ".join(f"{r['player']} ({int(r.win_now_score)}wn/"
                        f"{int(r.dynasty_score)}dy)" for r in c["R"])
        print(tag)
        print(f"  YOU SEND : {give}")
        print(f"  YOU GET  : {get}")
        print(f"  by THEIR appetite: they receive {c['s_them']:.0f} for "
              f"{c['r_them']:.0f} given  -> {'FAIR+' if c['s_them'] >= c['r_them'] else 'short'}")
        print(f"  by YOUR  appetite: you receive {c['r_me']:.0f} for "
              f"{c['s_me']:.0f} given  -> {'WIN' if c['r_me'] > c['s_me'] else 'flat'} "
              f"(+{c['r_me'] - c['s_me']:.0f})")
        margin = (c["s_them"] - c["r_them"]) / max(c["r_them"], 1)
        if 0 <= margin < 0.08:
            print(f"  value margin to them only +{margin*100:.0f}% -- barely fair; "
                  f"since your win-now is cheap, consider sweetening to seal it")

        hard_fail = [ck for ck in checks if ck[1] and not ck[2]]
        print("  VET:")
        for name, hard, ok, detail in checks:
            mark = "OK " if ok else ("XX" if hard else "?? ")
            print(f"    [{mark}] {name}: {detail}")
        if hard_fail:
            print(f"  VERDICT: KILLED -- fails {', '.join(ck[0] for ck in hard_fail)}. "
                  f"No viable construction with this partner.")
        else:
            print("  VERDICT: passes every computable check. RESIDUAL (unknowable, "
                  "verify yourself): does he value his guys as the model does, and "
                  "will he deal at all?")

    if not any_survivor:
        print(f"\n[trade] No partner in the top {a.partners} yielded a vetted package. "
              "Before concluding the market is closed: widen --partners, and remember "
              "the unmovable wall is real ONLY if their #N starters genuinely outscore "
              "your chips. A thin market means hold and wait for an injury to open a "
              "hole -- it does NOT mean force a lesser deal.")
    print("\n[trade] computable checks are vetted above; the counterparty's true "
          "valuation and willingness are NOT calculable -- they're flagged, not faked.")


def main():
    ap = argparse.ArgumentParser(description="Trade tooling: outbound finder, "
                                 "inbound inquiry evaluation, concrete offer grading.")
    ap.add_argument("mode", nargs="?", default="outbound",
                    choices=["outbound", "inquiry", "offer"])
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--posture", default="rebuild",
                    choices=["rebuild", "retool", "contend"])
    ap.add_argument("--partners", type=int, default=3, help="outbound: how many to workshop")
    ap.add_argument("--partner", help="inquiry/offer: the owner reaching out")
    ap.add_argument("--send", help="inquiry/offer: your player(s) to move, comma-separated")
    ap.add_argument("--get", help="offer: the player(s) they're offering, comma-separated")
    a = ap.parse_args()

    if not os.path.exists(a.ratings):
        sys.exit(f"[trade] ratings not found: {a.ratings}")
    df = pd.read_csv(a.ratings, encoding="utf-8")
    for c in ("win_now_score", "dynasty_score", "age"):
        df[c] = _num(df, c)
    my_app = APPETITE[a.posture]

    if a.mode == "outbound":
        mode_outbound(df, a, my_app)
        return

    # inbound modes need a counterparty + the player(s) you'd part with
    if not a.partner or not a.send:
        sys.exit(f"[trade] {a.mode} mode needs --partner and --send "
                 "(offer mode also needs --get)")
    if a.partner not in set(df["owner_status"]):
        sys.exit(f"[trade] owner {a.partner!r} not found")
    p_app = float(team_table(df).set_index("owner").loc[a.partner, "appetite"])
    send_names = [s.strip() for s in a.send.split(",") if s.strip()]

    if a.mode == "inquiry":
        mode_inquiry(df, a.team, my_app, a.partner, p_app, send_names)
    else:  # offer
        if not a.get:
            sys.exit("[trade] offer mode needs --get (what they're offering you)")
        get_names = [s.strip() for s in a.get.split(",") if s.strip()]
        mode_offer(df, a.team, my_app, a.partner, p_app, send_names, get_names)


if __name__ == "__main__":
    main()
