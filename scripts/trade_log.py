#!/usr/bin/env python3
"""
trade_log.py - a negotiation memory. Records what each trade conversation REVEALED,
so the next talk with an owner starts informed instead of amnesiac.

Design stance, consistent with the rest of the system:
- The MECHANICAL facts (who, when, players, outcome) are logged plainly.
- The INTERPRETATION ("wants an OF", "won't move Henderson") is a note YOU write --
  it's your read of a human negotiation, the exact unknowable the trade tools flag
  rather than fake. The log stores your read; it does not infer one.
- History is CONTEXT, never a constraint. Every entry is dated and old reads are
  marked stale, because "wouldn't move X in June" is worthless in August. Your bar
  comes from the current model, not from what didn't work last month.

Outcomes: opened | countered | accepted | declined | stalled
File: data/trade_log/negotiation_log.csv  (commit it -- it's real front-office memory,
not regenerated data, so it belongs in git unlike the ratings cache.)
"""
import argparse
import csv
import datetime as dt
import os
import sys

LOG_PATH = "data/trade_log/negotiation_log.csv"
COLS = ["date", "partner", "sent", "received", "outcome", "note"]
STALE_DAYS = 21


def _today():
    return dt.date.today().isoformat()


def append(partner, sent, received, outcome, note, path=LOG_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow({"date": _today(), "partner": partner, "sent": sent,
                    "received": received, "outcome": outcome, "note": note})


def read_log(partner=None, path=LOG_PATH):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if partner:
        rows = [r for r in rows if r.get("partner", "").lower() == partner.lower()]
    return sorted(rows, key=lambda r: r.get("date", ""), reverse=True)


def _age_days(datestr):
    try:
        return (dt.date.today() - dt.date.fromisoformat(datestr)).days
    except Exception:
        return None


def context_block(partner, path=LOG_PATH):
    """A short dated history block for a partner, for the trade modes to surface.
    Stale entries are flagged, not hidden -- they inform, they don't set your price."""
    rows = read_log(partner, path)
    if not rows:
        return ""
    lines = [f"PRIOR HISTORY with {partner} (context only -- not a constraint on your bar):"]
    for r in rows[:5]:
        age = _age_days(r["date"])
        tag = ""
        if age is not None and age > STALE_DAYS:
            tag = f"  [STALE {age}d -- treat as weak]"
        elif age is not None:
            tag = f"  [{age}d ago]"
        lines.append(f"  - {r['date']}: sent [{r['sent']}] / got [{r['received']}] "
                     f"-> {r['outcome']}{tag}")
        if r.get("note"):
            lines.append(f"      note: {r['note']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Record or review trade negotiations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="log a negotiation")
    a.add_argument("--partner", required=True)
    a.add_argument("--sent", default="", help="player(s) you offered/would send")
    a.add_argument("--received", default="", help="player(s) they offered/you'd get")
    a.add_argument("--outcome", required=True,
                   choices=["opened", "countered", "accepted", "declined", "stalled"])
    a.add_argument("--note", default="", help="YOUR read: what it revealed about them")

    s = sub.add_parser("show", help="review history")
    s.add_argument("--partner", help="filter to one owner")

    args = ap.parse_args()
    if args.cmd == "add":
        append(args.partner, args.sent, args.received, args.outcome, args.note)
        print(f"[log] recorded {args.outcome} with {args.partner} ({_today()})")
    else:
        rows = read_log(args.partner)
        if not rows:
            print("[log] no entries" + (f" for {args.partner}" if args.partner else ""))
            return
        for r in rows:
            age = _age_days(r["date"])
            stale = f"  [STALE {age}d]" if age and age > STALE_DAYS else ""
            print(f"{r['date']}  {r['partner']:10}  sent[{r['sent']}] got[{r['received']}]"
                  f"  -> {r['outcome']}{stale}")
            if r.get("note"):
                print(f"            note: {r['note']}")


if __name__ == "__main__":
    main()
