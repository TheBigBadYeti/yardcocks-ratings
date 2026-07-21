#!/usr/bin/env python3
"""
fetch_injuries.py - snapshot the CURRENT MLB injured list and write it keyed by
MLBAM player id, so the optimizer can exclude genuinely-injured players whose
Fantrax status hasn't caught up yet.

WHY ROSTER STATUS, NOT TRANSACTIONS:
"on the IL right now" is a STATE. The /transactions endpoint is an event log -- to
get current state from it you must pair every placement with its activation and
reconcile, which is error-prone (you'll flag players who already returned). The team
roster endpoint carries each player's LIVE status, so it IS the state. 30 simple
calls, each independently correct.

WHY KEYED BY ID:
Downstream joins on MLBAM id (already resolved during identify->confirm-mapping),
NOT on a fresh name match against every player in MLB. A name false-match here would
sit a healthy star or start an injured one -- the exact failure we're fixing.

This script ONLY records injuries. It does NOT touch scoring. Status override at the
engine/scoring layer would crater a player's win_now (-22) and therefore his
trade value over a routine 10-day stint -- injury is a lineup fact, not an asset fact.
Output: data/injuries/il_status.csv  (gitignored, regenerated each run)
"""
import csv
import datetime as dt
import json
import os
import sys
import urllib.request

API = "https://statsapi.mlb.com/api/v1"
OUT = "data/injuries/il_status.csv"
OUT_RET = "data/injuries/returning.csv"      # rehab-assignment = about to be activated
TIMEOUT = 15


def _get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return json.load(r)


def norm_name(s):
    """Mirror the schedule fetcher's normalization so name is a usable fallback key.
    (ID is the primary join key; this is only for readability / last-resort match.)"""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", "").replace("'", "").split())


def team_ids():
    data = _get(f"{API}/teams?sportId=1")
    return [(t["id"], t.get("abbreviation", "")) for t in data.get("teams", [])]


# MLB Stats API status codes for genuine IL placements (benched by the health layer).
IL_CODES = {"D7", "D10", "D15", "D60", "ILF"}
# RA (rehab assignment) = about to be activated. NOT benched -- captured separately as
# a RETURNING signal so /waivers can flag a good player to grab before he's back.
RETURNING_CODES = {"RA"}


def notable_from_roster(team_id, today):
    """Return (il_rows, returning_rows) for one team, keyed on status.code.
    Codes confirmed from live API: D7/D10/D15/D60 day ILs, ILF full season, RA rehab."""
    url = f"{API}/teams/{team_id}/roster?rosterType=fullRoster&date={today}"
    il_rows, ret_rows = [], []
    for e in _get(url).get("roster", []):
        s = e.get("status", {}) or {}
        code = (s.get("code", "") or "").strip().upper()
        desc = (s.get("description", "") or "").strip()
        if code not in IL_CODES and code not in RETURNING_CODES:
            continue
        person = e.get("person", {})
        if code == "ILF":
            il_type = "full-season"
        elif code == "RA":
            il_type = "rehab"
        elif code.startswith("D") and code[1:].isdigit():
            il_type = f"{code[1:]}-day"
        else:
            il_type = code.lower()
        row = {
            "mlbam_id": person.get("id", ""),
            "name": person.get("fullName", ""),
            "norm_name": norm_name(person.get("fullName", "")),
            "il_type": il_type,
            "status_code": code,
            "status_desc": desc,
        }
        (ret_rows if code in RETURNING_CODES else il_rows).append(row)
    return il_rows, ret_rows


def main():
    today = dt.date.today().isoformat()
    try:
        teams = team_ids()
    except Exception as e:
        sys.exit(f"[injuries] could not list teams ({e}); aborting, leaving prior file")

    all_rows, ret_rows, failed = [], [], []
    for tid, abbr in teams:
        try:
            il, ret = notable_from_roster(tid, today)
            for r in il:
                r["mlb_team"] = abbr; all_rows.append(r)
            for r in ret:
                r["mlb_team"] = abbr; ret_rows.append(r)
        except Exception as e:
            failed.append(abbr or str(tid))   # fail soft: skip team, keep going

    if failed:
        # partial data is dangerous (a missed team looks 'healthy'). Warn loudly.
        print(f"[injuries] WARNING: {len(failed)} teams failed to fetch: "
              f"{', '.join(failed)}. IL list is INCOMPLETE this run -- "
              f"hand-check players on those teams.", file=sys.stderr)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cols = ["mlbam_id", "name", "norm_name", "mlb_team", "il_type",
            "status_code", "status_desc"]
    for path, rows in ((OUT, all_rows), (OUT_RET, ret_rows)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in sorted(rows, key=lambda x: x["name"]):
                w.writerow(r)
    print(f"[injuries] wrote {len(all_rows)} IL designations to {OUT} and "
          f"{len(ret_rows)} rehab/returning to {OUT_RET} "
          f"({len(teams) - len(failed)}/{len(teams)} teams ok)")


# ---- shared reader, imported by optimize_lineup.py ----------------------------
def read_il(path=OUT):
    """Return (by_id, by_name) lookups. Optimizer joins on id first, name as
    last resort. Missing file -> empty dicts + a flag so the optimizer can fall
    back to Fantrax status instead of silently benching nobody/ everybody."""
    if not os.path.exists(path):
        return {}, {}, False
    by_id, by_name = {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("mlbam_id"):
                by_id[str(r["mlbam_id"])] = r
            if r.get("norm_name"):
                by_name[r["norm_name"]] = r
    return by_id, by_name, True


if __name__ == "__main__":
    main()
