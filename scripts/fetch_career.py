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


# Fantrax -> MLB Stats API abbreviation aliases (for the team-disambiguation join)
TEAM_ALIAS = {"CHW": "CWS", "OAK": "ATH", "AZ": "ARI", "WAS": "WSH"}


def id_index(seasons):
    """Build a team-aware id index from the last few seasons' aggregates, so
    same-name players (e.g. the two Mason Millers) can be told apart by team.
    Returns (by_name_team, by_name_unique):
      by_name_team    : {(norm_name, mlb_team_abbrev): id}
      by_name_unique  : {norm_name: id}  only when the name maps to ONE id
    """
    by_nt, seen = {}, {}
    for season in seasons:
        for group in ("hitting", "pitching"):
            url = (f"{API}/stats?stats=season&group={group}&season={season}"
                   f"&sportId=1&gameType=R&limit=5000")
            for sp in fr._get(url).get("stats", [{}])[0].get("splits", []):
                pid = sp.get("player", {}).get("id")
                nm = fr.norm_name(sp.get("player", {}).get("fullName", ""))
                team = sp.get("team", {}).get("abbreviation")
                if not (pid and nm):
                    continue
                if team:
                    by_nt.setdefault((nm, team), pid)
                seen.setdefault(nm, set()).add(pid)
    by_name_unique = {nm: next(iter(ids)) for nm, ids in seen.items() if len(ids) == 1}
    return by_nt, by_name_unique


def resolve_id(name, team, by_nt, by_name_unique):
    """Team-first resolution: (name, team) -> id; fall back to a unique name;
    ambiguous name with no team match -> None (flagged for review)."""
    nm = fr.norm_name(name)
    t = str(team).strip()
    t = TEAM_ALIAS.get(t, t)
    if (nm, t) in by_nt:
        return by_nt[(nm, t)]
    return by_name_unique.get(nm)   # None if the name is ambiguous and team missed


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


def groups_for(position, role):
    """Which MLB stat groups to fetch. A two-way player carries BOTH a hitting and
    a pitching eligibility token (e.g. Ohtani 'UT,SP') -> fetch both; everyone else
    gets their single group. year_by_year returns empty for a group a player never
    played, so the only cost of a false two-way is one wasted call (the asset model
    then drops a thin second half via MIN_SECONDARY_GAMES)."""
    toks = [t.strip().upper() for t in str(position).split(",") if t.strip()]
    pit = {"SP", "RP", "P"}
    has_pit = any(t in pit for t in toks)
    has_hit = any(t not in pit for t in toks)   # C/1B/.../OF/UT/DH all count as hitting
    groups = []
    if has_hit:
        groups.append("hitting")
    if has_pit:
        groups.append("pitching")
    if not groups:                               # no usable position -> fall back to role
        groups = ["pitching"] if str(role) != "H" else ["hitting"]
    return groups


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
    by_nt, by_name = id_index(seasons)

    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.join(a.outdir, "career_stats.csv")
    n_players, n_rows, misses = 0, 0, []
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["mlb_id", "name", "team", "group", "season", "games", "fpts", "fpg"])
        for _, r in df.iterrows():
            nm = r["player"]
            pid = resolve_id(nm, r.get("team", ""), by_nt, by_name)
            if not pid:
                misses.append(nm); continue
            wrote = False
            for group in groups_for(r.get("position", ""), r.get("role", "H")):
                rows = year_by_year(pid, group)
                for row in rows:
                    w.writerow([pid, nm, r.get("team", ""), group, row["season"],
                                row["games"], row["fpts"], row["fpg"]])
                if rows:
                    n_rows += len(rows); wrote = True
            if wrote:
                n_players += 1

    print(f"[career] {n_players} players, {n_rows} player-seasons -> {out}")
    if misses:
        print(f"[career] {len(misses)} unmatched (no current-season MLB id): "
              f"{', '.join(misses[:8])}{' ...' if len(misses) > 8 else ''}")


if __name__ == "__main__":
    main()
