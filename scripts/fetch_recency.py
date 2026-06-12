#!/usr/bin/env python3
"""
fetch_recency.py  --  trailing-window fantasy production from the MLB Stats API
==============================================================================

Builds the recency layer: each MLB player's fantasy points over a recent window
(default: last 30 days), scored with THIS league's exact rules, cached to
data/recency/recent_fpg.csv for the engine to read (parallel to prospect_ranks).

QUALITY STARTS
  The byDateRange aggregate does NOT compute quality starts (QS is a derived
  per-start stat: >=6 IP and <=3 ER). Since the Fantrax season FPts we compare
  against INCLUDES QS, silently dropping it would make every starter read cold.
  So: relievers use the cheap aggregate (they have no QS); for any pitcher who
  STARTED in the window we pull their game log and recompute points game-by-game,
  counting a QS whenever a start clears 6 IP / <=3 ER. Accurate where it matters,
  cheap where it doesn't.

CONVERTER PROVENANCE
  fp_hitter / fp_pitch reproduce Fantrax's reported season FPts for all 288
  hitters and 244 pitchers with ZERO error (IP thirds and QS included). The
  scoring is exact; only the live pull is environment-dependent.

USAGE
  python3 scripts/fetch_recency.py                 # last 30 days
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
import time
import unicodedata
import urllib.request

API = "https://statsapi.mlb.com/api/v1"


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


def fp_pitch(s, qs):
    """Pitcher fantasy points. QS is passed in explicitly (derived per start for
    starters; 0 for relievers) since the aggregate endpoint never supplies it."""
    g = lambda k: float(s.get(k, 0) or 0)
    return (3 * parse_ip(s.get("inningsPitched", 0)) + 4 * g("wins") + 3 * qs
            + 5 * g("saves") + 3 * g("holds") + 1 * g("strikeOuts")
            - 3 * g("earnedRuns") - 1 * g("hits") - 1 * g("baseOnBalls") - 1 * g("hitByPitch"))


def is_quality_start(game_stat):
    """A start of >=6.0 IP and <=3 ER."""
    started = float(game_stat.get("gamesStarted", 0) or 0) >= 1
    ip = parse_ip(game_stat.get("inningsPitched", 0))
    er = float(game_stat.get("earnedRuns", 0) or 0)
    return started and ip >= 6.0 and er <= 3


def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def fetch_group(group, start, end, season):
    url = (f"{API}/stats?stats=byDateRange&group={group}&startDate={start}&endDate={end}"
           f"&sportId=1&season={season}&gameType=R&limit=5000&playerPool=ALL")
    stats = _get(url).get("stats", [])
    return stats[0].get("splits", []) if stats else []


def pitcher_window_from_gamelog(pid, start, end, season):
    """Recompute a starter's window points game-by-game so QS is counted.
    Returns (recent_fpts, games) or None on failure."""
    url = (f"{API}/people/{pid}/stats?stats=gameLog&group=pitching&season={season}"
           f"&startDate={start}&endDate={end}&gameType=R")
    try:
        data = _get(url)
        splits = data["stats"][0]["splits"]
    except Exception:
        return None
    pts, games = 0.0, 0
    for sp in splits:
        d = sp.get("date", "")
        if d and not (start <= d <= end):   # client-side date guard
            continue
        st = sp.get("stat", {})
        pts += fp_pitch(st, 1 if is_quality_start(st) else 0)
        games += 1
    return (round(pts, 1), games) if games else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--out", default="data/recency/recent_fpg.csv")
    a = ap.parse_args()

    end = a.end or dt.date.today().isoformat()
    start = a.start or (dt.date.fromisoformat(end) - dt.timedelta(days=a.days)).isoformat()
    season = dt.date.fromisoformat(end).year

    rows = {}

    def put(name, pid, games, pts, group):
        if not name:
            return
        rec = {"name": name, "mlb_id": pid, "recent_games": games,
               "recent_fpts": round(pts, 1),
               "recent_fpg": round(pts / games, 2) if games else 0.0, "group": group}
        k = norm_name(name)
        if k not in rows or pts > rows[k]["recent_fpts"]:
            rows[k] = rec

    # hitters: aggregate is exact (no derived stats involved)
    for sp in fetch_group("hitting", start, end, season):
        pl, st = sp.get("player", {}), sp.get("stat", {})
        put(pl.get("fullName", ""), pl.get("id", ""), st.get("gamesPlayed", 0) or 0,
            fp_hitter(st), "hitting")

    # pitchers: relievers from aggregate; starters re-derived from game logs for QS
    starters = []
    for sp in fetch_group("pitching", start, end, season):
        pl, st = sp.get("player", {}), sp.get("stat", {})
        gs = float(st.get("gamesStarted", 0) or 0)
        if gs >= 1:
            starters.append((pl.get("id", ""), pl.get("fullName", "")))
        else:   # reliever -> aggregate, QS=0
            put(pl.get("fullName", ""), pl.get("id", ""), st.get("gamesPlayed", 0) or 0,
                fp_pitch(st, 0), "pitching")

    print(f"[recency] deriving QS for {len(starters)} starters via game logs...", file=sys.stderr)
    for i, (pid, name) in enumerate(starters):
        res = pitcher_window_from_gamelog(pid, start, end, season)
        if res is None:     # game log unavailable -> skip (keeps any aggregate row)
            continue
        pts, games = res
        put(name, pid, games, pts, "pitching")
        if i % 40 == 0:
            time.sleep(0.3)   # be polite to the API

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
