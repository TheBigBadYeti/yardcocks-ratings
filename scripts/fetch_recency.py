#!/usr/bin/env python3
"""
fetch_recency.py  --  trailing-window fantasy production from the MLB Stats API
==============================================================================

Builds the recency layer: each MLB player's fantasy points over a recent window
(default: last 30 days), scored with THIS league's exact rules, cached to
data/recency/recent_fpg.csv for the engine to read (parallel to prospect_ranks).

WHY THIS EXISTS
  The Fantrax exports carry only SEASON totals -- no trailing split. Recency is
  what lets value become forward-looking instead of backward-looking, which is
  what stops the engine from libeling injured stars (a returning Lindor reads
  dead on season-to-date but alive on his last 30 days).

WHAT IS ALREADY PROVEN
  The fantasy-point converter below (fp_hitter / fp_pitcher) was validated
  against the Fantrax season exports: applied to season component stats it
  reproduces Fantrax's reported FPts for all 288 hitters and 244 pitchers with
  ZERO error, IP thirds included. So the conversion is exact; only the live pull
  is environment-dependent.

WHAT TO CONFIRM ON FIRST RUN (live JSON field names)
  The MLB Stats API stat field names below are the standard ones, but verify
  against a live response the first time. The `.get(field, 0)` pattern means a
  missing field degrades gracefully (e.g. if qualityStarts/holds aren't in the
  aggregate it just under-counts those modest terms; IP/K/ER -- the dominant
  pitcher terms -- are always present and exact).

USAGE
  python3 scripts/fetch_recency.py                 # last 30 days, today as end
  python3 scripts/fetch_recency.py --days 14
  python3 scripts/fetch_recency.py --start 2026-05-12 --end 2026-06-11
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import unicodedata
import urllib.request

API = "https://statsapi.mlb.com/api/v1/stats"

# --- league scoring (identical to SYSTEM_SPEC; converter verified vs Fantrax) --
def parse_ip(x):
    """'45.1' -> 45 + 1/3 ; '45.2' -> 45 + 2/3 ; plain decimals pass through."""
    try:
        whole = float(x)
    except (TypeError, ValueError):
        return 0.0
    base = int(whole)
    frac = round(whole - base, 1)
    return base + (1 / 3 if frac == 0.1 else 2 / 3 if frac == 0.2 else frac)


def fp_hitter(s):
    g = lambda k: float(s.get(k, 0) or 0)
    singles = g("hits") - g("doubles") - g("triples") - g("homeRuns")
    return (1 * singles + 2 * g("doubles") + 3 * g("triples") + 4 * g("homeRuns")
            + 1 * g("runs") + 1 * g("rbi") + 1 * g("baseOnBalls") + 2 * g("stolenBases")
            + 1 * g("hitByPitch") - 1 * g("caughtStealing")
            - 1 * g("groundIntoDoublePlay") - 0.5 * g("strikeOuts"))


def fp_pitcher(s):
    g = lambda k: float(s.get(k, 0) or 0)
    return (3 * parse_ip(s.get("inningsPitched", 0)) + 4 * g("wins") + 3 * g("qualityStarts")
            + 5 * g("saves") + 3 * g("holds") + 1 * g("strikeOuts")
            - 3 * g("earnedRuns") - 1 * g("hits") - 1 * g("baseOnBalls") - 1 * g("hitByPitch"))


def norm_name(s):
    """Match the engine's join key: strip accents/suffixes/punct, lowercase."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_group(group, start, end, season):
    url = (f"{API}?stats=byDateRange&group={group}&startDate={start}&endDate={end}"
           f"&sportId=1&season={season}&gameType=R&limit=5000&playerPool=ALL")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    stats = data.get("stats", [])
    return stats[0].get("splits", []) if stats else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--out", default="data/recency/recent_fpg.csv")
    a = ap.parse_args()

    end = a.end or dt.date.today().isoformat()
    start = a.start or (dt.date.fromisoformat(end) - dt.timedelta(days=a.days)).isoformat()
    season = dt.date.fromisoformat(end).year

    rows = {}   # norm_name -> record (keep the higher-FPts row if a name collides)
    for group, fp in [("hitting", fp_hitter), ("pitching", fp_pitcher)]:
        try:
            splits = fetch_group(group, start, end, season)
        except Exception as e:
            print(f"[recency] {group} fetch failed: {e}", file=sys.stderr)
            continue
        for sp in splits:
            player = sp.get("player", {})
            stat = sp.get("stat", {})
            name = player.get("fullName", "")
            if not name:
                continue
            g = stat.get("gamesPlayed", 0) or 0
            pts = round(fp(stat), 1)
            rec = {"name": name, "mlb_id": player.get("id", ""),
                   "recent_games": g, "recent_fpts": pts,
                   "recent_fpg": round(pts / g, 2) if g else 0.0,
                   "group": group}
            k = norm_name(name)
            if k not in rows or pts > rows[k]["recent_fpts"]:
                rows[k] = rec

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "mlb_id", "recent_games",
                                           "recent_fpts", "recent_fpg", "group"])
        w.writeheader()
        for r in sorted(rows.values(), key=lambda x: -x["recent_fpts"]):
            w.writerow(r)
    print(f"[recency] window {start}..{end}  players={len(rows)}  wrote {a.out}")
    top = sorted(rows.values(), key=lambda x: -x["recent_fpts"])[:5]
    print("[recency] hottest:", ", ".join(f"{r['name']}({r['recent_fpts']:.0f})" for r in top))


if __name__ == "__main__":
    main()
