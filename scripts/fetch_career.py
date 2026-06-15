#!/usr/bin/env python3
"""
fetch_career.py - multi-year career history for the dynasty asset layer.

Pulls each rostered player's season-by-season MLB stats and scores them on the
league's exact rules (reusing the recency fetcher's verified converters), writing
a per player-season history cache:

  data/career/career_stats.csv
    mlb_id, name, group, season, games, fpts, fpg

The engine builds the weighted career baseline + aging projection ON TOP of this;
this script is purely the data layer (pull + score + cache), mirroring how
fetch_recency feeds the recency layer.

Historical quality starts: the season aggregate carries `qualityStarts` when MLB
provides it; otherwise we estimate it as gamesStarted * QS_RATE_EST so a starter's
history isn't undervalued. (Approximate by design - the baseline is a relative
asset signal, not a box score.)

DESKTOP-ONLY: MLB API 403s in the cloud. Stdlib only; imports fetch_recency.
"""
import argparse, csv, os, sys
import pandas as pd
import fetch_recency as fr   # reuse fp_hitter / fp_pitch / parse_ip / norm_name / _get

API = fr.API
QS_RATE_EST = 0.45   # est. quality-start rate per start when MLB omits qualityStarts


def season_fp(stat, group):
    if group == "hitting":
        return fr.fp_hitter(stat)
    gs = float(stat.get("gamesStarted", 0) or 0)
    qs = stat.get("qualityStarts")
    qs = float(qs) if qs not in (None, "") else gs * QS_RATE_EST
    return fr.fp_pitch(stat, qs)


def id_map(seasons):
    """name(normalized) -> mlb_id, from the last few seasons' aggregates (both
    groups), so a player who missed the current year still resolves an id."""
    out = {}
    for season in seasons:
        for group in ("hitting", "pitching"):
            url = (f"{API}/stats?stats=season&group={group}&season={season}"
                   f"&sportId=1&gameType=R&limit=5000")
            for sp in fr._get(url).get("stats", [{}])[0].get("splits", []):
                pid = sp.get("player", {}).get("id")
                nm = sp.get("player", {}).get("fullName", "")
                if pid and nm:
                    out.setdefault(fr.norm_name(nm), pid)   # any season's id is fine
    return out


def year_by_year(pid, group):
    url = f"{API}/people/{pid}/stats?stats=yearByYear&group={group}&gameType=R"
    try:
        splits = fr._get(url)["stats"][0]["splits"]
    except Exception:
        return []
    rows = []
    for sp in splits:
        if sp.get("sport", {}).get("id") != 1:    # MLB only (skip minors)
            continue
        st = sp.get("stat", {})
        games = float(st.get("gamesPlayed", 0) or 0)
        fp = round(season_fp(st, group), 1)
        rows.append({"season": sp.get("season"), "games": games, "fpts": fp,
                     "fpg": round(fp / games, 2) if games else 0.0})
    # Traded-player seasons: yearByYear returns per-team splits PLUS a season
    # total. Keep the total (its games == sum of the stints); if there's no
    # total row, sum the stints into one season line.
    from collections import defaultdict
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season"]].append(r)
    clean = []
    for season, rs in by_season.items():
        if len(rs) == 1:
            clean.append(rs[0]); continue
        rs_sorted = sorted(rs, key=lambda r: -r["games"])
        top, rest = rs_sorted[0], rs_sorted[1:]
        if abs(top["games"] - sum(r["games"] for r in rest)) < 1.0:
            clean.append(top)                                # top is the total
        else:
            g = sum(r["games"] for r in rs)
            fp = round(sum(r["fpts"] for r in rs), 1)
            clean.append({"season": season, "games": g, "fpts": fp,
                          "fpg": round(fp / g, 2) if g else 0.0})
    return sorted(clean, key=lambda r: r["season"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", required=True, help="current_player_ratings.csv (for names+roles)")
    ap.add_argument("--season", default="2026")
    ap.add_argument("--rostered-only", action="store_true", default=True,
                    help="only players on a team (skip the FA pool)")
    ap.add_argument("--team", default=None, help="limit to one owner handle (e.g. Kipp)")
    ap.add_argument("--outdir", default="data/career")
    a = ap.parse_args()

    df = pd.read_csv(a.ratings, encoding="utf-8")
    if a.team:
        df = df[df["owner_status"].astype(str).str.fullmatch(a.team, case=False, na=False)]
    elif a.rostered_only:
        df = df[~df["owner_status"].astype(str).isin(["FA", "nan", ""])]
    df = df[df["roster_status"].astype(str).str.lower() != "minors"]   # MLB history only

    seasons = [str(int(a.season) - k) for k in range(3)]   # current + 2 prior
    print(f"[career] resolving ids across seasons {seasons} ...")
    ids = id_map(seasons)

    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.join(a.outdir, "career_stats.csv")
    n_players, n_rows, misses = 0, 0, []
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["mlb_id", "name", "group", "season", "games", "fpts", "fpg"])
        for _, r in df.iterrows():
            nm = r["player"]
            pid = ids.get(fr.norm_name(nm))
            if not pid:
                misses.append(nm); continue
            group = "pitching" if str(r.get("role", "H")) != "H" else "hitting"
            rows = year_by_year(pid, group)
            for row in rows:
                w.writerow([pid, nm, group, row["season"], row["games"],
                            row["fpts"], row["fpg"]])
            if rows:
                n_players += 1; n_rows += len(rows)

    print(f"[career] {n_players} players, {n_rows} player-seasons -> {out}")
    if misses:
        print(f"[career] {len(misses)} unmatched (no current-season MLB id): "
              f"{', '.join(misses[:8])}{' ...' if len(misses) > 8 else ''}")


if __name__ == "__main__":
    main()
