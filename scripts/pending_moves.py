#!/usr/bin/env python3
"""
pending_moves.py - roster moves you've executed in Fantrax but that the ratings file
doesn't know about yet.

THE GAP THIS FILLS: current_player_ratings.csv is built from Fantrax exports. When you
make a waiver move, the export won't reflect it until the next /refresh -- so /lineups
would keep optimizing a roster you no longer have, and /waivers would keep recommending
a player you already added. This records the moves as an OVERLAY that both commands
apply, so they agree with reality immediately.

It is deliberately dumb and temporary: /refresh clears it, because at that point the
fresh exports ARE reality and a stale overlay would double-count.

    python scripts/pending_moves.py add  "Brent Headrick"
    python scripts/pending_moves.py drop "Tony Santillan"
    python scripts/pending_moves.py ir   "Max Meyer"
    python scripts/pending_moves.py show
    python scripts/pending_moves.py clear

File: data/pending/moves.json (committed, so cloud/phone sessions see it too).
"""
import argparse
import datetime as dt
import json
import os

PATH = "data/pending/moves.json"
KINDS = ("add", "drop", "ir")


def load(path=PATH):
    if not os.path.exists(path):
        return {"updated": None, "add": [], "drop": [], "ir": []}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {"updated": None, "add": [], "drop": [], "ir": []}
    for k in KINDS:
        d.setdefault(k, [])
    return d


def save(d, path=PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d["updated"] = dt.date.today().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def describe(d):
    if not any(d.get(k) for k in KINDS):
        return "no pending moves (roster file is current)"
    bits = [f"{k}: {', '.join(d[k])}" for k in KINDS if d.get(k)]
    return f"pending as of {d.get('updated')} -- " + " | ".join(bits)


def main():
    ap = argparse.ArgumentParser(description="record roster moves made in Fantrax that "
                                             "the ratings export doesn't show yet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for k in KINDS:
        p = sub.add_parser(k, help=f"record a {k}")
        p.add_argument("player", help="player name as it appears in the ratings file")
    sub.add_parser("show", help="print pending moves")
    sub.add_parser("clear", help="wipe pending moves (/refresh does this for you)")
    a = ap.parse_args()

    d = load()
    if a.cmd == "show":
        print(f"[pending] {describe(d)}")
        return
    if a.cmd == "clear":
        save({"updated": None, "add": [], "drop": [], "ir": []})
        print("[pending] cleared -- the ratings file is now the source of truth.")
        return
    if a.player not in d[a.cmd]:
        d[a.cmd].append(a.player)
    save(d)
    print(f"[pending] recorded {a.cmd}: {a.player}")
    print(f"[pending] {describe(d)}")
    print("[pending] /lineups and /waivers will apply this until the next /refresh.")


if __name__ == "__main__":
    main()
