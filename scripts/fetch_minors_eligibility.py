#!/usr/bin/env python3
"""
fetch_minors_eligibility.py - who on the managed roster can legally occupy a Minors slot.

League rule (docs/league_rules.md): Minors eligibility is "Simple - only real Minor
League players" -- a player must be CURRENTLY assigned to a real-life MiLB team to sit
in a Minors slot. That is exactly what the MLB Stats API's current-team + sport level
tells us: sportId 1 = MLB (NOT minors-eligible); 11/12/13/14/16 = AAA/AA/A+/A/Rookie
(eligible). This is the authoritative signal -- it replaces the old "0 GP" guess that
couldn't tell a rostered-in-MLB rookie (House, Crews) from a real minor leaguer (Sirota).

It is VOLATILE (players move up and down daily), so the daily GitHub Action refreshes it
and commits the result; a Claude cloud VM can't reach the API but reads what's committed.

Output: data/roster/minors_eligible.csv
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 20
OUT = "data/roster/minors_eligible.csv"


def _get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return json.load(r)


def resolve_current_team(name):
    """(person_id, team_id, team_name, n_matches) for a player name, or (None,...)."""
    q = urllib.parse.quote(name)
    ppl = _get(f"{API}/people/search?names={q}").get("people", [])
    if not ppl:
        return None, None, None, 0
    exact = [p for p in ppl if p.get("fullName", "").lower() == name.lower()]
    p = (exact or ppl)[0]
    d = _get(f"{API}/people/{p['id']}?hydrate=currentTeam")
    ct = (d["people"][0].get("currentTeam") or {})
    return p["id"], ct.get("id"), ct.get("name"), len(ppl)


def team_sport(team_id, cache):
    if team_id in cache:
        return cache[team_id]
    t = _get(f"{API}/teams/{team_id}")["teams"][0]
    sp = t.get("sport") or {}
    cache[team_id] = (sp.get("id"), sp.get("name"))
    return cache[team_id]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default="data/processed/current_player_ratings.csv")
    ap.add_argument("--team", default="Kipp")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    import pandas as pd
    df = pd.read_csv(a.ratings, encoding="utf-8")
    mine = df[df["owner_status"].astype(str).str.fullmatch(a.team, case=False, na=False)]

    rows, cache, miss = [], {}, []
    for nm in mine["player"]:
        try:
            pid, tid, tname, n = resolve_current_team(nm)
            if not tid:
                rows.append({"player": nm, "mlbam_id": pid or "",
                             "current_team": tname or "(no current team)",
                             "level": "?", "eligible": ""})
                miss.append(nm)
                continue
            sid, sname = team_sport(tid, cache)
            elig = sid is not None and sid != 1        # any non-MLB affiliated level
            rows.append({"player": nm, "mlbam_id": pid, "current_team": tname,
                         "level": sname or "?", "eligible": elig})
            if n > 1:                                   # ambiguous name search
                miss.append(f"{nm}(ambiguous)")
        except Exception as e:
            rows.append({"player": nm, "mlbam_id": "", "current_team": f"ERR {e}",
                         "level": "?", "eligible": ""})
            miss.append(nm)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    cols = ["player", "mlbam_id", "current_team", "level", "eligible"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (str(x["eligible"]) != "True", x["player"])):
            w.writerow(r)
    n_elig = sum(1 for r in rows if r["eligible"] is True)
    print(f"[minors] wrote {len(rows)} players ({n_elig} minors-eligible) to {a.out}")
    if miss:
        print(f"[minors] verify manually (not found / ambiguous): {', '.join(miss)}",
              file=sys.stderr)


# ---- shared reader ------------------------------------------------------------
def load_eligible(path=OUT):
    """player name -> {'eligible': True/False/None, 'level': str}. Keyed on the exact
    ratings-file player name (both this file and the tools read that same name), so no
    fuzzy matching. None = unknown (not found / draftee not yet assigned)."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = str(r.get("eligible", "")).strip().lower()
            out[r["player"]] = {
                "eligible": True if v == "true" else False if v == "false" else None,
                "level": r.get("level", "?"),
                "team": r.get("current_team", ""),
            }
    return out


if __name__ == "__main__":
    main()
