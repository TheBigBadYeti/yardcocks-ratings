#!/usr/bin/env python3
"""
standings.py - the ACTUAL record axis (W/L, GB, points for/against) from the Fantrax
standings export, keyed to owner handles.

WHY THIS EXISTS: franchise_outlook and trade_finder both INFER competitive posture from
roster strength, and that inference misfires badly. Measured against the real table:
JMerkle ranks 8th by roster but sits 2nd at 11-4 on an 8-game win streak -- the model
priced him a 0.40 retooler when he's a desperate buyer. Appetite drives trade pricing,
so a wrong read means a mispriced offer. Actual record is ground truth for who is
buying and who is selling.

The standings export keys teams by FRANCHISE NAME; the ratings key by OWNER HANDLE, so
a map is required. Unmapped franchises are REPORTED, never guessed -- a wrong mapping
is worse than no mapping (it would invert a partner's buy/sell posture).
"""
import csv
import os

PATH = "data/standings/standings.csv"

# franchise name (standings export) -> owner handle (ratings 'owner_status').
# All 14 CONFIRMED by the owner (Hutch = Tommy Hustle by elimination once the other 13
# were named). Note: a roster-based guess had kyfaess = Tommy Hustle (he rosters Tommy
# Edman) and it was WRONG -- kyfaess is Former Players II. Name puns are not evidence;
# confirm new franchises rather than inferring them.
TEAM_MAP = {
    "zyoung510": "zyoung51",
    "Merkle x Owen": "JMerkle",
    "Former Players II": "kyfaess",
    "Clankas": "CLANK",
    "Tommy Hustle": "Hutch",
    "Kenny's Retirement Home": "KRetiree",
    "Backyard Buntsmokers": "GoldTY",
    "joeybats5": "joeybats",
    "Tucker? I hardly know her": "Coop",
    "Seth x Simon": "Sethmc44",
    "Dirtbags": "Sasso",
    "Sandlot Sluggers": "Jpanner",
    "Greenbeto_20": "Greenbet",
    "The Hot Tub Whalers": "Kipp",
}

# No unconfirmed mappings remain. If the league renames a franchise, add it here --
# an unmapped team silently falls back to roster inference (and is reported).
PROVISIONAL = {}


def load(path=PATH):
    """franchise -> record dict. Parses the standings block only; the export also
    carries recent scoring-period matchups, which we skip."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 10 or not row[0].strip().isdigit():
                continue
            try:
                out[row[1].strip()] = {
                    "rank": int(row[0]), "w": int(row[2]), "l": int(row[3]),
                    "pct": float(row[5]),
                    "gb": float(row[6]) if row[6].strip() not in ("", "-") else 0.0,
                    "fpts_for": float(row[7].replace(",", "")),
                    "fpts_against": float(row[8].replace(",", "")),
                    "streak": row[9].strip(),
                }
            except ValueError:
                continue
    return out


def by_owner(path=PATH):
    """Return (owner->record, provisional_handles, unmapped_franchises)."""
    mapped, prov, unmapped = {}, {}, []
    for fr, rec in load(path).items():
        if fr in TEAM_MAP:
            mapped[TEAM_MAP[fr]] = dict(rec, franchise=fr, provisional=False)
        elif fr in PROVISIONAL:
            h = PROVISIONAL[fr]
            mapped[h] = dict(rec, franchise=fr, provisional=True)
            prov[h] = fr
        else:
            unmapped.append(fr)
    return mapped, prov, unmapped


def record_appetite(rec, n=14):
    """Win-now appetite from ACTUAL record: contenders buy, cellar teams sell.
    Blends winning pct with standings position, clipped to the same 0.15-0.90 range
    the roster inference uses so it substitutes cleanly."""
    pos = 1 - (rec["rank"] - 1) / max(n - 1, 1)        # 1.0 = first place
    blend = 0.5 * rec["pct"] + 0.5 * pos
    return round(min(0.90, max(0.15, 0.15 + 0.75 * blend)), 2)


def summary_line(rec):
    return (f"{rec['w']}-{rec['l']} ({rec['pct']:.3f}), #{rec['rank']} of 14, "
            f"{rec['gb']:.0f} GB, {rec['fpts_for']:.0f} for / "
            f"{rec['fpts_against']:.0f} against, streak {rec['streak']}")


if __name__ == "__main__":
    mapped, prov, unmapped = by_owner()
    print(f"{'OWNER':<10} {'FRANCHISE':<28} RECORD")
    for h, r in sorted(mapped.items(), key=lambda kv: kv[1]["rank"]):
        flag = "  [PROVISIONAL]" if r["provisional"] else ""
        print(f"{h:<10} {r['franchise']:<28} {summary_line(r)}{flag}")
    if prov:
        print(f"\nprovisional (confirm these): "
              + ", ".join(f"{h} = {f}" for h, f in prov.items()))
    if unmapped:
        print(f"UNMAPPED franchises (no handle): {', '.join(unmapped)}")
