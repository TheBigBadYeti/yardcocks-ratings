#!/usr/bin/env python3
"""
fetch_schedule.py - MLB schedule layer for schedule-aware lineups.

Pulls the MLB Stats API schedule and writes two caches that the lineup optimizer
and the forward-value layer consume:

  data/schedule/team_schedule.csv
      one row per MLB team: games_this_week, remaining_games_season
  data/schedule/probable_starts.csv
      one row per probable starter: starts_this_week + the dates

DESKTOP-ONLY: the MLB Stats API is blocked (403) from the cloud VM, exactly like
fetch_recency.py. Run this on the desktop (open network), commit the caches, and
the cloud/phone read them. Stdlib only - no extra deps.
"""
import csv, json, os, sys, argparse, datetime as dt
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API = "https://statsapi.mlb.com/api/v1/schedule"
SEASON_END = dt.date(2026, 9, 27)     # Yardcocks & Beyond regular-season end
WEEK_START_DOW = 0                     # 0 = Monday (lineups lock weekly)
OUTDIR = "data/schedule"
SKIP_STATUS = {"Postponed", "Cancelled", "Canceled", "Suspended"}


def _get(url):
    req = Request(url, headers={"User-Agent": "yardcocks-schedule/1.0"})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def week_bounds(target, start_dow=WEEK_START_DOW):
    delta = (target.weekday() - start_dow) % 7
    start = target - dt.timedelta(days=delta)
    return start, start + dt.timedelta(days=6)


def fetch_range(start, end, probables=False):
    # Always hydrate `team` so every game keys by abbreviation consistently
    # across both the week pull and the rest-of-season pull. Add probablePitcher
    # only for the week pull (where we need start assignments); skipping it on the
    # months-long rest pull keeps that response light.
    hyd = "probablePitcher,team" if probables else "team"
    url = (f"{API}?sportId=1&startDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}"
           f"&gameType=R&hydrate={hyd}")
    return _get(url)


def parse(sched):
    """Return (team_games, probables) over whatever range `sched` covers.
       team_games: {abbrev: game_count}
       team_dates: {abbrev: [date,...]}
       probables:  {mlb_id: {"name","team","dates":[...]}}"""
    team_games, team_dates, probables = {}, {}, {}
    for day in sched.get("dates", []):
        date = day.get("date")
        for g in day.get("games", []):
            if g.get("status", {}).get("detailedState", "") in SKIP_STATUS:
                continue
            for side in ("home", "away"):
                t = g["teams"][side]["team"]
                ab = t.get("abbreviation") or t.get("name")
                team_games[ab] = team_games.get(ab, 0) + 1
                team_dates.setdefault(ab, []).append(date)
                pp = g["teams"][side].get("probablePitcher")
                if pp and pp.get("id"):
                    pid = str(pp["id"])
                    rec = probables.setdefault(
                        pid, {"name": pp.get("fullName", ""), "team": ab, "dates": []})
                    rec["dates"].append(date)
    return team_games, team_dates, probables


def write_caches(outdir, wk_start, wk_end, season_end, wk_games, wk_dates, rest_games, probables):
    os.makedirs(outdir, exist_ok=True)
    teams = sorted(set(wk_games) | set(rest_games))
    tpath = os.path.join(outdir, "team_schedule.csv")
    with open(tpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "games_this_week", "remaining_games_season",
                    "game_dates", "week_start", "week_end", "season_end"])
        for t in teams:
            dates = ";".join(sorted(set(wk_dates.get(t, []))))
            w.writerow([t, wk_games.get(t, 0), rest_games.get(t, 0),
                        dates, wk_start, wk_end, season_end])
    ppath = os.path.join(outdir, "probable_starts.csv")
    with open(ppath, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["mlb_id", "pitcher", "team", "starts_this_week", "start_dates"])
        for pid, rec in sorted(probables.items(), key=lambda kv: -len(kv[1]["dates"])):
            w.writerow([pid, rec["name"], rec["team"], len(rec["dates"]),
                        ";".join(rec["dates"])])
    return tpath, ppath, teams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--season-end", default=SEASON_END.isoformat())
    ap.add_argument("--outdir", default=OUTDIR)
    a = ap.parse_args()
    target = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    season_end = dt.date.fromisoformat(a.season_end)
    wk_start, wk_end = week_bounds(target)

    try:
        week_sched = fetch_range(wk_start, wk_end, probables=True)
        rest_sched = fetch_range(target, season_end, probables=False)  # team-keyed counts
    except (URLError, HTTPError) as e:
        sys.exit(f"[schedule] fetch failed ({getattr(e,'code','')} {e}). Run this on "
                 f"the DESKTOP - the MLB API 403s from the cloud VM.")

    wk_games, wk_dates, probables = parse(week_sched)
    rest_games, _, _ = parse(rest_sched)
    tpath, ppath, teams = write_caches(a.outdir, wk_start, wk_end, season_end,
                                       wk_games, wk_dates, rest_games, probables)

    n2 = sum(1 for r in probables.values() if len(r["dates"]) >= 2)
    print(f"[schedule] week {wk_start}..{wk_end}: {len(teams)} teams, "
          f"{sum(wk_games.values())//2} games this week")
    if len(teams) != 30:
        print(f"[schedule] WARNING: expected 30 teams, got {len(teams)} - likely a "
              f"team-name/abbreviation keying mismatch; check the hydrate params.")
    print(f"[schedule] probables: {len(probables)} starters, {n2} with 2 starts")
    print(f"[schedule] wrote {tpath}")
    print(f"[schedule] wrote {ppath}")


if __name__ == "__main__":
    main()
