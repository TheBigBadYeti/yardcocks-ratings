#!/usr/bin/env python3
"""
shortlist.py - weekly trade + waiver shortlists for the managed team.
=====================================================================

Reads current_player_ratings.csv and produces four actionable lists, tilted by
the team's competitive POSTURE (from franchise_outlook):

  SELL    - players on YOUR roster to shop (rebuild: aging now>future vets you
            can convert to youth/picks; contend: surplus/blocked youth & depth).
  BUY     - undervalued players on OTHER rosters to target in trade.
  ADD     - free agents who help you NOW (startable this week).
  STASH   - free agents worth a dynasty roster spot (young upside).

Robust to schema: it uses whatever signal columns the ratings file carries
(dynasty_signal / dynasty_gap from the consensus layer, ros_vor / forward_fpg
from the forward lens, ros_pct + rkov as market context) and prints which
signals it found. It fails LOUDLY only if a genuinely required column is absent.

Reads the ratings file only - no network. Desktop or cloud both fine.
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

# the 14 owner handles as they appear in the Status column (SYSTEM_SPEC s2)
OWNERS = {"CLANK", "Coop", "GoldTY", "Greenbet", "Hutch", "JMerkle", "Jpanner",
          "KRetiree", "Kipp", "Sasso", "Sethmc44", "joeybats", "kyfaess", "zyoung51"}

REQUIRED = ["player", "win_now_score", "dynasty_score", "owner_status"]

# posture knobs: youth ceiling for buy/stash, vet floor for sell
YOUNG = 25
VET = 29


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.Series(
        np.nan, index=df.index)


def _str(df, c):
    return df[c].astype(str) if c in df.columns else pd.Series("", index=df.index)


def _not_minors(df):
    rs = _str(df, "roster_status").str.lower()
    return ~rs.str.contains("minor", na=False)


def _is_minors(df):
    return _str(df, "roster_status").str.lower().str.contains("minor", na=False)


def _fmt(df, cols, n):
    cols = [c for c in cols if c in df.columns]
    if df.empty:
        return "   (none)"
    return df[cols].head(n).to_string(index=False)


def load(path):
    if not os.path.exists(path):
        sys.exit(f"[shortlist] ratings file not found: {path}")
    df = pd.read_csv(path, encoding="utf-8")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        sys.exit(f"[shortlist] ratings file is missing required column(s): "
                 f"{missing}. Re-run the engine to regenerate it.")
    df["win_now_score"] = _num(df, "win_now_score")
    df["dynasty_score"] = _num(df, "dynasty_score")
    df["age"] = _num(df, "age")
    df["_owned"] = _str(df, "owner_status").isin(OWNERS)
    # surface available signals so the user knows what drove the picks
    signals = [c for c in ["dynasty_signal", "dynasty_gap", "ros_vor", "forward_fpg",
                           "ros_pct", "rkov", "dynasty_minus_win_now", "asset_value",
                           "two_way"] if c in df.columns]
    sig_msg = ", ".join(signals) or ("BASE ONLY (win_now/dynasty) - no consensus "
                                      "or forward lens in this file")
    print(f"[shortlist] signals available: {sig_msg}")
    return df, signals


def now_minus_future(df):
    if "dynasty_minus_win_now" in df.columns:
        # dynasty_minus_win_now = dynasty - win_now; flip so + = more NOW than future
        return -_num(df, "dynasty_minus_win_now")
    return df["win_now_score"] - df["dynasty_score"]


def build(df, team, posture):
    mine = df[_str(df, "owner_status") == team].copy()
    others = df[df["_owned"] & (_str(df, "owner_status") != team)].copy()
    avail = df[~df["_owned"]].copy()
    nf = now_minus_future(df)
    df["_nowfut"] = nf

    out = {}
    if posture == "contend":
        # SELL surplus: blocked/depth youth & prospects you can spare for win-now
        s = mine[_str(mine, "owner_status") == team].copy()
        s["_nowfut"] = now_minus_future(s)
        sell = s[(s["age"] <= YOUNG) | (_is_minors(s))].sort_values(
            "dynasty_score", ascending=False)
        # BUY win-now upgrades on other rosters
        buy = others[others["win_now_score"] >= others["win_now_score"].median()] \
            .sort_values("win_now_score", ascending=False)
        # ADD: best startable FA right now
        add = avail[_not_minors(avail)].sort_values("win_now_score", ascending=False)
        stash = avail[(avail["age"] <= YOUNG) | _is_minors(avail)].sort_values(
            "dynasty_score", ascending=False)
    else:  # rebuild (default) / retool
        s = mine.copy()
        s["_nowfut"] = now_minus_future(s)
        # SELL: own players whose value is NOW > FUTURE (sell while market pays),
        # leaning to vets. Keep young studs (where now ~ future).
        sell = s[_not_minors(s) & (s["_nowfut"] > 5) & (
            (s["age"] >= VET) | (s["_nowfut"] > 12))].sort_values(
            "win_now_score", ascending=False)
        # BUY-LOW: young, high-dynasty players on other rosters; prefer an explicit
        # BUY_LOW consensus signal if the file has one.
        b = others[(others["age"] <= YOUNG + 1) | _is_minors(others)].copy()
        if "dynasty_signal" in b.columns:
            b["_pri"] = (_str(b, "dynasty_signal") == "BUY_LOW").astype(int)
            buy = b.sort_values(["_pri", "dynasty_score"], ascending=[False, False])
        else:
            buy = b.sort_values("dynasty_score", ascending=False)
        # ADD: FA who help now (tread water / trade bait), startable
        add = avail[_not_minors(avail)].sort_values("win_now_score", ascending=False)
        # STASH: young / prospect FA with dynasty upside - the rebuild priority
        stash = avail[(avail["age"] <= YOUNG) | _is_minors(avail)].sort_values(
            "dynasty_score", ascending=False)
    out["sell"], out["buy"], out["add"], out["stash"] = sell, buy, add, stash
    return out


def main():
    ap = argparse.ArgumentParser(description="trade + waiver shortlists")
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--posture", default="rebuild",
                    choices=["rebuild", "retool", "contend"])
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--outdir", default="data/processed")
    a = ap.parse_args()

    df, signals = load(a.ratings)
    if not (_str(df, "owner_status") == a.team).any():
        sys.exit(f"[shortlist] no rows with owner_status == {a.team!r}; "
                 f"check the handle (owners seen: "
                 f"{sorted(set(_str(df, 'owner_status')) & OWNERS)})")
    lists = build(df, a.team, a.posture)

    show = ["player", "team", "position", "role", "age", "win_now_score",
            "dynasty_score", "_nowfut", "dynasty_signal", "dynasty_gap",
            "ros_vor", "ros_pct", "rkov", "owner_status", "two_way"]
    titles = {
        "sell": ("SELL - shop these ("
                 + ("vets, value peaks now" if a.posture != "contend"
                    else "surplus youth/depth") + ")"),
        "buy": "BUY - target on other rosters (undervalued upside)",
        "add": "ADD - free agents who help NOW (startable)",
        "stash": "STASH - free-agent dynasty upside (young)",
    }
    os.makedirs(a.outdir, exist_ok=True)
    print(f"\n=== {a.team} shortlists | posture={a.posture} ===")
    for key in ["sell", "buy", "add", "stash"]:
        lst = lists[key]
        print(f"\n--- {titles[key]} ---")
        print(_fmt(lst, show, a.n))
        path = os.path.join(a.outdir, f"shortlist_{key}.csv")
        keep = [c for c in show if c in lst.columns]
        lst[keep].head(a.n).to_csv(path, index=False)
    print(f"\n[shortlist] wrote shortlist_{{sell,buy,add,stash}}.csv -> {a.outdir}")
    print("[shortlist] reminder: BUY/SELL are model reads - cross-check injury "
          "status and the owner's posture before making an offer.")


if __name__ == "__main__":
    main()
