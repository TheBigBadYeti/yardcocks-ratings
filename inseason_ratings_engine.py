#!/usr/bin/env python3
"""
In-season ratings engine  (Yardcocks & Beyond dynasty league)
==============================================================

Clean-room rebuild of the CURRENT in-season ratings layer.

What it does:
  raw Fantrax exports
    -> normalize + de-dup into one player pool
    -> derive primary role (Hitter / SP / RP / SP-RP)
    -> regressed FP/G (raw FP/G pulled toward role median by sample confidence)
    -> percentiles inside SEPARATE hitter / pitcher pools
    -> win-now score (0-100)
    -> dynasty score (0-100)
    -> current_player_ratings.csv  (+ a filtered file for the managed team)

It does NOT yet build the trade board, free-agent watchlist, or news/minors
revalue layer. Those sit ON TOP of these scores and come next, after the core
numbers are validated against the old current_player_ratings.csv.

Two kinds of constant live in CONFIG below:
  KNOWN     - recovered from the old design (win-now weights 46/25/13/8/8,
              sample caps ~45 H / ~11 SP / ~24 RP). Treat as faithful.
  CALIBRATE - the old design described these only qualitatively (role/SP-RP
              bonuses, age curve, scarcity, status penalties). The numbers here
              are reasoned DEFAULTS, not recovered values. Tune them until the
              ranking matches the old output.  <-- marked  # CALIBRATE

MODE:
  "faithful"  win-now uses the original weights incl. Ros (13%) + RkOv (8%)
              -> use this to validate against the old file.
  "split"     Fork 2: Ros/RkOv come OUT of the production score and are carried
              as separate market columns; remaining weights renormalized.
"""

import argparse
import os
import re
import sys
import pandas as pd
import numpy as np

# --------------------------------------------------------------------------
# CONFIG  (Fork 3: everything tunable lives here, not buried in the code)
# --------------------------------------------------------------------------
CONFIG = {
    "mode": "faithful",            # "faithful" | "split"

    # --- exact Fantrax column names, per Codex's schema dump ---------------
    # If a live export header differs, change it HERE only.
    "cols": {
        "id": "ID",
        "player": "Player",
        "team": "Team",
        "position": "Position",
        "rkov": "RkOv",
        "status": "Status",            # owner / FA state
        "roster_status": "Roster Status",  # Active/Reserve/IR/Minors (rostered export only)
        "age": "Age",
        "fpts": "FPts",
        "fpg": "FP/G",
        "ros": "Ros",                  # roster %
        "plusminus": "+/-",
    },

    # team-roster export (multi-section) column names
    "tr_cols": {
        "id": "ID", "pos": "Pos", "player": "Player", "team": "Team",
        "eligible": "Eligible", "status": "Status", "age": "Age",
        "fpts": "Fantasy Points", "fpg": "Average Fantasy Points per Game",
        "ip": "IP",
    },
    "tr_section_markers": ["Hitting", "Pitching"],

    # --- sample-confidence caps (estimated games), by primary role ---------
    #     SP/RP uses the RP/other-pitcher cap of 24, NOT the SP cap of 11.
    "sample_caps": {"H": 45, "SP": 11, "RP": 24, "SP/RP": 24},

    # --- win-now component weights -----------------------------------------
    "win_now_weights": {
        "fpg_pct": 0.46,     # percentile of regressed FP/G within H or P pool
        "pts_pct": 0.25,     # percentile of total FPts within H or P pool
        "ros_pct": 0.13,     # raw Ros value (already 0-100); 0 in "split" mode
        "rank_pct": 0.08,    # RkOv-derived rank score;        0 in "split" mode
        "scarcity": 0.08,    # weight on (50 + 5 * scarcity_bonus)
    },

    # --- comparison pools: separate hitter / pitcher, exclude minors -------
    #   hitter:  non-pitcher, not Minors, (FPts > 25 or Ros >= 20)
    #   pitcher: pitcher,     not Minors, (FPts > 20 or Ros >= 20)
    "pool_hitter_min_fpts": 25.0,
    "pool_pitcher_min_fpts": 20.0,
    "pool_min_ros": 20.0,

    # --- positional scarcity: ADDITIVE by eligibility token ----------------
    "scarcity_bonus": {"C": 4, "SS": 2, "3B": 2, "2B": 1, "1B": 0, "OF": 0,
                       "SP": 2, "RP": 1},
    "scarcity_pure_ut": -1,   # eligible at UT only

    # --- role / SP-RP production bonuses (added to the score) --------------
    "role_bonus_sp_fpg": 10.0, "role_bonus_sp": 3.0,   # SP & reg FP/G >= 10 -> +3
    "role_bonus_rp_fpg": 4.0,  "role_bonus_rp": 3.0,   # RP & reg FP/G >= 4  -> +3
    "sprp_bonus_hi_fpg": 7.0,  "sprp_bonus_hi": 7.0,   # SP/RP reg >= 7      -> +7
    "sprp_bonus_lo_fpg": 4.0,  "sprp_bonus_lo": 3.0,   # SP/RP 4 <= reg < 7  -> +3

    # --- win-now status penalty (added; values are negative) ---------------
    "status_penalty_win_now": {
        "Active": 0, "Reserve": -4, "Inj Res": -22, "Injured": -22,
        "IL": -22, "Out": -22, "Minors": -30, "Not On Team": -30,
        "Free Agent": 0,
    },
    # --- dynasty status penalty: a SEPARATE function, not a scaled win-now -
    "status_penalty_dynasty": {
        "Active": 0, "Reserve": 0, "Inj Res": -7, "Injured": -7,
        "IL": -7, "Out": -7, "Minors": 0, "Not On Team": -24,
        "Free Agent": 0,
    },
    "serious_injury_extra": -5,
    "serious_injury_keywords": ["elbow", "shoulder", "forearm", "ucl",
                                "surgery", "60-day", "60 day"],

    # --- dynasty build -----------------------------------------------------
    "dynasty_non_minor": {"win_now": 0.54, "ros": 0.18, "rank": 0.10},
    "dynasty_minor": {"base": 24.0, "win_now": 0.15, "ros": 0.22, "rank": 0.10},
    # minors prospect bonus when no external rank: ros/100*15 + age*0.7, clip 2..18
    "prospect_fallback": {"ros_mult": 15.0, "age_mult": 0.7, "lo": 2.0, "hi": 18.0},
    # external MLB-Pipeline ranks (mlb.com/prospects). overall tiers, then org tiers.
    # grade term = (grade-50)/2 clip[-4,8]; +4 flat when any actual rank bonus applies.
    "prospect_rank": {
        "overall": [(20, 28), (50, 22), (100, 15)],   # overall_rank <= k -> bonus
        "org":     [(5, 11), (15, 7), (30, 4)],        # org_rank <= k -> bonus
        "grade_lo": -4.0, "grade_hi": 8.0, "matched_flat": 4.0,
    },
    "prospect_ranks_path": "prospect_ranks.csv",   # cache; refresh ~monthly
    "recency_path": "recent_fpg.csv",              # trailing-window cache; refresh ~weekly

    # --- age curve: step thresholds (additive), separate H / P -------------
    #     (age <= threshold -> adjustment); missing age -> 0
    "age_curve_hitter": [(21, 17), (24, 12), (27, 6), (31, 0), (34, -5), (999, -12)],
    "age_curve_pitcher": [(22, 14), (25, 10), (28, 5), (31, 0), (34, -6), (999, -13)],

    "managed_team": "Kipp",   # owner handle in the Status column

    # --- Fork 1: direct pitcher innings (available league-wide via the
    #     hitter/pitcher split exports). 0.0 = faithful (volume only via FPts);
    #     >0 blends an IP-percentile term into pitcher win-now.  # CALIBRATE
    "pitcher_ip_pct_weight": 0.0,

    # --- value over replacement (VOR) --------------------------------------
    #   League startable slots by position: 14 teams x lineup
    #   (C,1B,2B,3B,SS,3xOF,UT,6xSP,3xRP). Replacement level at a position =
    #   the season FPts of the player ranked (slots+1) among non-Minors players
    #   eligible there. VOR is season-to-date (volume embedded, so hitters and
    #   pitchers stay comparable). It is a PARALLEL value lens for now -- it does
    #   not modify win_now/dynasty. Rest-of-season refinement arrives with the
    #   recency layer. UT demand is folded into the position slots, not modeled
    #   separately yet.  # CALIBRATE (slot counts are league structure, not Codex)
    "vor_startable_slots": {"C": 14, "1B": 14, "2B": 14, "3B": 14, "SS": 14,
                            "OF": 42, "SP": 84, "RP": 42},

    # --- forward-looking value (rest-of-season projection) ------------------
    #   Blend recent form with season rate, project over games remaining, then
    #   VOR on the projection. Fixes the injured-star problem (value a player on
    #   his rate going forward, not his depressed season-to-date total). Parallel
    #   lens; does not modify win_now/dynasty/VOR. Constants are reasoned defaults
    #   refined later by the schedule (remaining games) and news (injury) layers.
    "forward_value": {                                    # CALIBRATE
        "recent_full_games": 20,    # recent games at which recency earns full weight
        "recent_max_weight": 0.5,   # recency never exceeds half the blended rate
        "season_games": 162,
        "fulltime_hitter_rate": 0.92,    # healthy regular's share of remaining team games
        "starts_per_team_games": 0.20,   # ~1 start per 5 team games
        "rp_appear_rate": 0.45,          # reliever appearances per remaining team game
        # forward VOR measures ROS value AT FULL HEALTH; current-injury risk is the
        # news layer's job (an overlay), not a crude flat haircut baked in here.
    },

    # --- production-vs-market gap (the edge-finder) -------------------------
    #   Contrast forward value (ros_vor) against the market's price (roster% +
    #   overall rank). Positive gap = field prices a player below his forward
    #   value (buy/claim); negative = above (sell). Uses ros_vor so it's
    #   forward-vs-forward -- else every injured star reads as a false sell.
    "market_gap": {                                       # CALIBRATE
        "ros_weight": 0.6, "rank_weight": 0.4,   # market-price composite (roster% / rank)
        "min_fpts": 25.0,        # real-production floor to be judged at all
        "signal_threshold": 20,  # |gap| (percentile points) for a BUY/SELL flag
        "buy_max_ros": 60.0,     # a buy must be reasonably available
        "sell_min_ros": 75.0,    # a sell must be genuinely well-rostered
    },
}

MISSING_TOKENS = {"", "-", "--", "nan", "none", "n/a", "na"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def clean_numeric(x):
    """Strip commas / % , treat '', '-', '--' as missing, return float or NaN."""
    if x is None:
        return np.nan
    s = str(x).strip()
    if s.lower() in MISSING_TOKENS:
        return np.nan
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def pct_rank(series):
    """Percentile rank 0-1 within the non-null values of a series."""
    return series.rank(pct=True)


def derive_role(position_str):
    """Hitter / SP / RP / SP/RP from a comma-separated Position string."""
    if position_str is None or (isinstance(position_str, float) and np.isnan(position_str)):
        return "H"
    tokens = [t.strip().upper() for t in str(position_str).split(",")]
    has_sp = "SP" in tokens
    has_rp = "RP" in tokens
    is_pitcher = has_sp or has_rp or "P" in tokens
    if not is_pitcher:
        return "H"
    if has_sp and has_rp:
        return "SP/RP"
    if has_sp:
        return "SP"
    if has_rp:
        return "RP"
    return "SP"  # bare "P" -> treat as starter by default


def age_curve(age, is_pitcher):
    """Step age adjustment (additive). Separate hitter / pitcher tables."""
    if pd.isna(age):
        return 0.0
    table = CONFIG["age_curve_pitcher"] if is_pitcher else CONFIG["age_curve_hitter"]
    for thr, adj in table:
        if age <= thr:
            return float(adj)
    return float(table[-1][1])


def scarcity_bonus_for(position_str):
    """Additive positional scarcity by eligibility token; pure UT -> -1."""
    if pd.isna(position_str):
        return 0
    tokens = [t.strip().upper() for t in str(position_str).split(",") if t.strip()]
    if tokens == ["UT"]:
        return CONFIG["scarcity_pure_ut"]
    sb = CONFIG["scarcity_bonus"]
    return sum(sb.get(t, 0) for t in tokens)


def rank_pct_from_rkov(rkov):
    """RkOv-derived rank score: 100*(1-((RkOv-1)/500)), clipped 0-100; else 0."""
    if pd.isna(rkov):
        return 0.0
    return float(np.clip(100.0 * (1.0 - ((rkov - 1.0) / 500.0)), 0.0, 100.0))


def midpoint_percentile(values, reference):
    """Percentile (0-100) of each value vs a reference distribution, midpoint
    ties: (count_below + 0.5*count_equal) / pool_size * 100."""
    ref = np.asarray(reference, dtype=float)
    ref = np.sort(ref[~np.isnan(ref)])
    n = len(ref)
    vals = np.asarray(values, dtype=float)
    if n == 0:
        return np.full(vals.shape, np.nan)
    below = np.searchsorted(ref, vals, side="left")
    equal = np.searchsorted(ref, vals, side="right") - below
    pct = (below + 0.5 * equal) / n * 100.0
    pct[np.isnan(vals)] = np.nan
    return pct


def dynasty_status_penalty(status_norm, status_text=""):
    """Separate dynasty penalty (NOT a scaled win-now penalty)."""
    pen = CONFIG["status_penalty_dynasty"].get(status_norm, 0)
    txt = str(status_text).lower()
    if any(k in txt for k in CONFIG["serious_injury_keywords"]):
        pen += CONFIG["serious_injury_extra"]
    return pen


# --------------------------------------------------------------------------
# load + normalize the player pool (rostered/taken first, then FA if unseen)
# --------------------------------------------------------------------------
def load_player_pool(rostered_path, fa_path):
    c = CONFIG["cols"]
    rost = pd.read_csv(rostered_path, dtype=str)
    fa = pd.read_csv(fa_path, dtype=str)

    # FA export has no "Roster Status" -> default to Free Agent (per design)
    if c["roster_status"] not in fa.columns:
        fa[c["roster_status"]] = "Free Agent"

    rost["_source"] = "rostered_taken"
    fa["_source"] = "free_agent_pool"

    # de-dup: keep rostered rows, add FA rows only if their ID is unseen
    seen = set(rost[c["id"]].dropna().astype(str))
    fa_new = fa[~fa[c["id"]].astype(str).isin(seen)].copy()
    pool = pd.concat([rost, fa_new], ignore_index=True, sort=False)

    # numeric helpers
    pool["fpts_num"] = pool[c["fpts"]].map(clean_numeric)
    pool["fpg_raw"] = pool[c["fpg"]].map(clean_numeric)
    pool["ros_num"] = pool[c["ros"]].map(clean_numeric)
    pool["rkov_num"] = pool[c["rkov"]].map(clean_numeric)
    pool["age_num"] = pool[c["age"]].map(clean_numeric)
    if c["plusminus"] in pool.columns:
        pool["plusminus_num"] = pool[c["plusminus"]].map(clean_numeric)
    else:
        pool["plusminus_num"] = np.nan

    pool["role"] = pool[c["position"]].map(derive_role)
    pool["is_pitcher"] = pool["role"] != "H"
    pool["roster_status_norm"] = (
        pool[c["roster_status"]].fillna("Free Agent").replace("", "Free Agent")
    )
    return pool


def _prep_pool_frame(pool):
    """Shared numeric + role derivation for any assembled player pool."""
    c = CONFIG["cols"]
    pool["fpts_num"] = pool[c["fpts"]].map(clean_numeric)
    pool["fpg_raw"] = pool[c["fpg"]].map(clean_numeric)
    pool["ros_num"] = pool[c["ros"]].map(clean_numeric)
    pool["rkov_num"] = pool[c["rkov"]].map(clean_numeric)
    pool["age_num"] = pool[c["age"]].map(clean_numeric)
    pool["plusminus_num"] = (
        pool[c["plusminus"]].map(clean_numeric) if c["plusminus"] in pool.columns else np.nan
    )
    pool["ip_num"] = pool["IP"].map(clean_numeric) if "IP" in pool.columns else np.nan
    # derived rate stats where the component columns exist (pitchers)
    if {"H", "BB"}.issubset(pool.columns) and "IP" in pool.columns:
        ip = pool["ip_num"].replace(0, np.nan)
        pool["whip"] = (pool["H"].map(clean_numeric) + pool["BB"].map(clean_numeric)) / ip
        if "K" in pool.columns:
            pool["k_per_9"] = pool["K"].map(clean_numeric) / ip * 9
        if "QS" in pool.columns and "GP" in pool.columns:
            gp = pool["GP"].map(clean_numeric).replace(0, np.nan)
            pool["qs_rate"] = pool["QS"].map(clean_numeric) / gp
    pool["role"] = pool[c["position"]].map(derive_role)
    pool["is_pitcher"] = pool["role"] != "H"
    # scrub HTML cruft that can leak into Status (e.g. "W <small>(Wed)</small>")
    pool[c["status"]] = pool[c["status"]].astype(str).str.replace(
        r"<[^>]+>", "", regex=True).str.strip()
    if c["roster_status"] not in pool.columns:
        pool[c["roster_status"]] = "Free Agent"
    pool["roster_status_norm"] = (
        pool[c["roster_status"]].fillna("Free Agent").replace("", "Free Agent")
    )
    return pool


def _coalesce_name_team(pool):
    """Collapse multi-eligible / phantom duplicate rows that share name+team.
    Unions position tokens (so scarcity sees full eligibility) and keeps the
    producing row. Guard: if >1 row carries a *different* positive FPts total,
    treat them as genuinely different same-name players and keep them separate
    (e.g. the two Luis Garcias on one MLB club)."""
    c = CONFIG["cols"]
    pool = pool.copy()
    nm = pool[c["player"]].fillna("").str.lower().str.strip()
    tm = pool[c["team"]].fillna("").astype(str).str.strip()
    pool["_nt"] = nm + " | " + tm
    pool["_fp"] = pool[c["fpts"]].map(clean_numeric).fillna(0.0)
    keep, merged_pos = [], {}
    for nt, g in pool.groupby("_nt", sort=False):
        if nt.startswith(" | ") or len(g) == 1:        # blank name or unique
            keep.extend(g.index.tolist()); continue
        if g.loc[g["_fp"] > 0, "_fp"].round(1).nunique() > 1:   # distinct people
            keep.extend(g.index.tolist()); continue
        primary = g.sort_values("_fp", ascending=False).index[0]
        toks = []
        for p in g[c["position"]].dropna():
            for t in str(p).replace(";", ",").split(","):
                t = t.strip()
                if t and t not in toks:
                    toks.append(t)
        if toks:
            merged_pos[primary] = ",".join(toks)
        keep.append(primary)
    out = pool.loc[sorted(set(keep))].copy()
    for idx, pos in merged_pos.items():
        out.at[idx, c["position"]] = pos
    return out.drop(columns=["_nt", "_fp"])


def load_split_pool(rostered_hitters, rostered_pitchers, fa_hitters, fa_pitchers):
    """Assemble the full pool from the four hitter/pitcher split exports.

    Rostered files carry Roster Status + owner handle in Status and full stats
    (incl IP for pitchers). FA files carry the same minus Roster Status.
    The two families are disjoint (owned vs free agent), so a plain stack +
    de-dup-by-ID is safe.
    """
    c = CONFIG["cols"]
    frames = []
    for path, src in [
        (rostered_hitters, "rostered_hitters"),
        (rostered_pitchers, "rostered_pitchers"),
        (fa_hitters, "fa_hitters"),
        (fa_pitchers, "fa_pitchers"),
    ]:
        if path and os.path.exists(path):
            df = pd.read_csv(path, dtype=str)
            df["_source"] = src
            if c["roster_status"] not in df.columns:
                df[c["roster_status"]] = "Free Agent"
            frames.append(df)
    pool = pd.concat(frames, ignore_index=True, sort=False)
    pool = pool.drop_duplicates(subset=[c["id"]], keep="first")  # rostered listed first
    pool = _coalesce_name_team(pool)        # collapse multi-eligible / phantom dup rows
    return _prep_pool_frame(pool)


# --------------------------------------------------------------------------
# team-roster export: multi-section parse -> IP per player ID (our roster)
# --------------------------------------------------------------------------
def parse_team_roster_ip(team_roster_path):
    """Return {player_id: IP} from the pitching section. IP only lives here."""
    if not team_roster_path or not os.path.exists(team_roster_path):
        return {}
    import csv as _csv
    tr = CONFIG["tr_cols"]
    markers = set(m.lower() for m in CONFIG["tr_section_markers"])
    with open(team_roster_path, newline="") as fh:
        rows = list(_csv.reader(fh))
    ip_map = {}
    section, header = None, None
    for raw in rows:
        cells = [str(x).strip() for x in raw]
        if not cells:
            continue
        nonempty = [x for x in cells if x]
        # Fantrax writes section markers as ["", "Pitching"], so read the marker
        # from the single non-empty cell, not cells[0] (which is the blank).
        if len(nonempty) == 1 and nonempty[0].lower() in markers:   # section marker
            section, header = nonempty[0].lower(), None
            continue
        if section and header is None and tr["id"] in cells:   # header row
            header = cells
            continue
        if section == "pitching" and header:
            rec = dict(zip(header, cells))
            pid = rec.get(tr["id"], "").strip()
            ip = clean_numeric(rec.get(tr["ip"], ""))
            if pid and not pd.isna(ip):
                ip_map[pid] = ip
    return ip_map


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def compute_regressed_fpg(pool):
    caps = CONFIG["sample_caps"]
    pool["pool_group"] = np.where(pool["is_pitcher"], "P", "H")

    # estimated games = FPts / FP/G  (0 if FP/G zero or missing)
    fpg = pool["fpg_raw"]
    est = pool["fpts_num"] / fpg.replace(0, np.nan)
    pool["estimated_games"] = est.where(fpg.notna() & (fpg != 0), 0.0).fillna(0.0)

    # linear confidence, no exponent; SP/RP uses the 24 cap (handled in caps)
    cap = pool["role"].map(lambda r: caps.get(r, caps["H"]))
    pool["sample_confidence"] = np.clip(pool["estimated_games"] / cap, 0.0, 1.0)

    # regress toward the median raw FP/G of all HITTERS (or PITCHERS) with
    # positive FP/G -- hitter vs pitcher, NOT by individual position
    med = {}
    for g in ["H", "P"]:
        vals = pool.loc[(pool["pool_group"] == g) & (pool["fpg_raw"] > 0), "fpg_raw"]
        med[g] = float(vals.median()) if len(vals) else 0.0
    pool["role_median_fpg"] = pool["pool_group"].map(med)

    conf = pool["sample_confidence"]
    raw = pool["fpg_raw"].fillna(0.0)
    pool["fpg_regressed"] = raw * conf + pool["role_median_fpg"] * (1 - conf)
    return pool


def _not_minors(pool):
    return ~pool["roster_status_norm"].str.contains("Minor", case=False, na=False)


def hitter_pool_mask(pool):
    return (pool["pool_group"] == "H") & _not_minors(pool) & (
        (pool["fpts_num"].fillna(0) > CONFIG["pool_hitter_min_fpts"])
        | (pool["ros_num"].fillna(0) >= CONFIG["pool_min_ros"])
    )


def pitcher_pool_mask(pool):
    return (pool["pool_group"] == "P") & _not_minors(pool) & (
        (pool["fpts_num"].fillna(0) > CONFIG["pool_pitcher_min_fpts"])
        | (pool["ros_num"].fillna(0) >= CONFIG["pool_min_ros"])
    )


def compute_win_now(pool):
    w = CONFIG["win_now_weights"]
    split = CONFIG["mode"] == "split"
    c = CONFIG["cols"]

    hmask = hitter_pool_mask(pool)
    pmask = pitcher_pool_mask(pool)
    pool["_inpool"] = hmask | pmask

    # percentiles measured AGAINST the filtered pool (outsiders still scored)
    pool["fpg_pct"] = np.nan
    pool["pts_pct"] = np.nan
    for grp, m in [("H", hmask), ("P", pmask)]:
        gsel = pool["pool_group"] == grp
        ref_fpg = pool.loc[m, "fpg_regressed"].values
        ref_pts = pool.loc[m, "fpts_num"].values
        pool.loc[gsel, "fpg_pct"] = midpoint_percentile(
            pool.loc[gsel, "fpg_regressed"].values, ref_fpg)
        pool.loc[gsel, "pts_pct"] = midpoint_percentile(
            pool.loc[gsel, "fpts_num"].values, ref_pts)

    ros_pct = pool["ros_num"].clip(0, 100).fillna(0.0)          # raw Ros, 0-100
    rank_pct = pool["rkov_num"].map(rank_pct_from_rkov)
    scarcity_bonus = pool[c["position"]].map(scarcity_bonus_for)
    scarcity_component = 50 + 5 * scarcity_bonus

    w_ros = 0.0 if split else w["ros_pct"]
    w_rank = 0.0 if split else w["rank_pct"]

    base = (
        w["fpg_pct"] * pool["fpg_pct"].fillna(0)
        + w["pts_pct"] * pool["pts_pct"].fillna(0)
        + w_ros * ros_pct
        + w_rank * rank_pct
        + w["scarcity"] * scarcity_component
    )

    # role / SP-RP production bonuses on regressed FP/G (mutually exclusive)
    reg = pool["fpg_regressed"]
    role = pool["role"]
    role_bonus = np.zeros(len(pool))
    role_bonus = np.where((role == "SP") & (reg >= CONFIG["role_bonus_sp_fpg"]),
                          CONFIG["role_bonus_sp"], role_bonus)
    role_bonus = np.where((role == "RP") & (reg >= CONFIG["role_bonus_rp_fpg"]),
                          CONFIG["role_bonus_rp"], role_bonus)
    sprp = np.zeros(len(pool))
    sprp = np.where((role == "SP/RP") & (reg >= CONFIG["sprp_bonus_hi_fpg"]),
                    CONFIG["sprp_bonus_hi"], sprp)
    sprp = np.where((role == "SP/RP") & (reg >= CONFIG["sprp_bonus_lo_fpg"])
                    & (reg < CONFIG["sprp_bonus_hi_fpg"]), CONFIG["sprp_bonus_lo"], sprp)

    pen = pool["roster_status_norm"].map(
        lambda s: CONFIG["status_penalty_win_now"].get(s, 0)).fillna(0)

    pool["win_now_score"] = np.clip(base + role_bonus + sprp + pen, 0, 100)
    pool["scarcity_bonus_val"] = scarcity_bonus
    pool["rank_pct_val"] = rank_pct
    pool["_ros_market"] = ros_pct

    # Fork 1 (OFF by default): naive IP term double-counts FPts volume and
    # tanks high-leverage relievers, so faithful keeps this at 0. Rate columns
    # (whip / k_per_9 / qs_rate) are surfaced separately for context.
    w_ip = CONFIG.get("pitcher_ip_pct_weight", 0.0)
    pool["ip_pct"] = np.nan
    if "ip_num" in pool.columns:
        psel = pool["pool_group"] == "P"
        pool.loc[psel, "ip_pct"] = midpoint_percentile(
            pool.loc[psel, "ip_num"].values, pool.loc[pmask, "ip_num"].values)
        if w_ip > 0:
            blended = (1 - w_ip) * pool["win_now_score"] + w_ip * pool["ip_pct"].fillna(0)
            pool["win_now_score"] = np.where(psel, np.clip(blended, 0, 100),
                                             pool["win_now_score"])
    return pool


def _norm_name(s):
    import unicodedata, re
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def attach_prospect_ranks(pool, path=None, misses_path=None):
    """Join external MLB-Pipeline ranks (mlb.com/prospects) by normalized name.
    Adds 'overall_rank_pro' / 'org_rank_pro' (NaN when unmatched)."""
    import os
    path = path or CONFIG.get("prospect_ranks_path")
    # resolve either the repo layout (data/prospects/) or a flat working dir
    if not (path and os.path.exists(path)):
        for cand in ("data/prospects/prospect_ranks.csv", "prospect_ranks.csv"):
            if os.path.exists(cand):
                path = cand
                break
    pool["overall_rank_pro"] = np.nan
    pool["org_rank_pro"] = np.nan
    if not path or not os.path.exists(path):
        print(f"[prospect] no rank file at {path!r}; fallback-only")
        return pool
    pr = pd.read_csv(path)
    pr["k"] = pr["name"].map(_norm_name)
    pr = pr.drop_duplicates("k", keep="first")
    o = dict(zip(pr["k"], pd.to_numeric(pr["overall_rank"], errors="coerce")))
    g = (dict(zip(pr["k"], pd.to_numeric(pr["org_rank"], errors="coerce")))
         if "org_rank" in pr.columns else {})
    keys = pool[CONFIG["cols"]["player"]].map(_norm_name)
    pool["overall_rank_pro"] = keys.map(o)
    pool["org_rank_pro"] = keys.map(g)
    matched = pool["overall_rank_pro"].notna() | pool["org_rank_pro"].notna()
    miss = pr[~pr["k"].isin(set(keys))][["name", "overall_rank", "org_rank"]] \
        if "org_rank" in pr.columns else pr[~pr["k"].isin(set(keys))][["name", "overall_rank"]]
    if misses_path:
        miss.to_csv(misses_path, index=False)
    print(f"[prospect] ranks={len(pr)}  pool-matched={int(matched.sum())}  "
          f"unmatched-in-file={len(miss)}")
    return pool


def attach_recency(pool, path=None):
    """Join trailing-window production (fetch_recency.py cache) by normalized name.

    Adds recent_games, recent_fpts, recent_fpg, and hot_cold (recent FP/G minus
    season FP/G; positive = trending up). This is a forward-looking SIGNAL only --
    it does NOT modify win_now/dynasty here. It surfaces hot/cold context and is
    the input the projection layer (next build) will use to make value
    forward-looking. Missing cache -> columns stay NaN and the engine still runs.
    """
    import os
    c = CONFIG["cols"]
    path = path or CONFIG.get("recency_path")
    if not (path and os.path.exists(path)):       # repo layout or flat working dir
        for cand in ("data/recency/recent_fpg.csv", "recent_fpg.csv"):
            if os.path.exists(cand):
                path = cand
                break
    for col in ["recent_games", "recent_fpts", "recent_fpg", "hot_cold"]:
        pool[col] = np.nan
    if not path or not os.path.exists(path):
        print(f"[recency] no cache at {path!r}; recency columns blank")
        return pool
    rec = pd.read_csv(path)
    rec["k"] = rec["name"].map(_norm_name)
    rec = rec.drop_duplicates("k", keep="first")
    keys = pool[c["player"]].map(_norm_name)
    for src in ["recent_games", "recent_fpts", "recent_fpg"]:
        if src in rec.columns:
            pool[src] = keys.map(dict(zip(rec["k"], pd.to_numeric(rec[src], errors="coerce"))))
    pool["hot_cold"] = (pool["recent_fpg"] - pool["fpg_raw"]).round(2)
    print(f"[recency] cache={len(rec)}  pool-matched={int(pool['recent_fpg'].notna().sum())}")
    return pool


def _prospect_bonus_row(overall, org, grade, is_minor, ros, age_adj):
    pr = CONFIG["prospect_rank"]; pf = CONFIG["prospect_fallback"]
    bonus, matched = 0.0, False
    if overall == overall and overall > 0:            # overall_rank present (not NaN)
        for k, b in pr["overall"]:
            if overall <= k:
                bonus, matched = b, True; break
    elif org == org and org > 0:                      # else org_rank present
        for k, b in pr["org"]:
            if org <= k:
                bonus, matched = b, True; break
    if matched:
        if grade == grade:                            # optional grade term (none today)
            bonus += float(np.clip((grade - 50) / 2.0, pr["grade_lo"], pr["grade_hi"]))
        return bonus + pr["matched_flat"]
    if is_minor:                                      # no external rank -> minors fallback
        return float(np.clip(ros / 100 * pf["ros_mult"] + age_adj * pf["age_mult"],
                             pf["lo"], pf["hi"]))
    return 0.0


def compute_dynasty(pool):
    nm = CONFIG["dynasty_non_minor"]
    mn = CONFIG["dynasty_minor"]
    pf = CONFIG["prospect_fallback"]
    c = CONFIG["cols"]

    is_minors = pool["roster_status_norm"].str.contains("Minor", case=False, na=False)
    age_adj = np.array([age_curve(a, p)
                        for a, p in zip(pool["age_num"], pool["is_pitcher"])])
    ros = pool["ros_num"].clip(0, 100).fillna(0.0)
    rank_pct = pool["rank_pct_val"] if "rank_pct_val" in pool.columns \
        else pool["rkov_num"].map(rank_pct_from_rkov)
    dyn_pen = np.array([dynasty_status_penalty(s, t)
                        for s, t in zip(pool["roster_status_norm"], pool[c["status"]])])

    # Prospect bonus from external MLB-Pipeline ranks (attach_prospect_ranks),
    # falling back to ros/age for minors with no rank. Grade term off (no feed).
    overall = pool["overall_rank_pro"] if "overall_rank_pro" in pool.columns \
        else pd.Series(np.nan, index=pool.index)
    org = pool["org_rank_pro"] if "org_rank_pro" in pool.columns \
        else pd.Series(np.nan, index=pool.index)
    grade = pool["fv_grade_pro"] if "fv_grade_pro" in pool.columns \
        else pd.Series(np.nan, index=pool.index)
    prospect = np.array([
        _prospect_bonus_row(ov, og, gr, mi, r, a)
        for ov, og, gr, mi, r, a in zip(overall, org, grade, is_minors, ros, age_adj)
    ])

    non_minor = (nm["win_now"] * pool["win_now_score"] + nm["ros"] * ros
                 + nm["rank"] * rank_pct + age_adj + prospect + dyn_pen)
    minor = (mn["base"] + mn["win_now"] * np.clip(pool["win_now_score"], 0, None)
             + mn["ros"] * ros + mn["rank"] * rank_pct + age_adj + prospect + dyn_pen)

    pool["dynasty_score"] = np.clip(np.where(is_minors, minor, non_minor), 0, 100)
    pool["dynasty_minus_win_now"] = pool["dynasty_score"] - pool["win_now_score"]
    pool["age_curve_val"] = age_adj
    pool["prospect_bonus"] = prospect
    return pool


# --------------------------------------------------------------------------
# value over replacement (VOR)  -- season-total points above the startable line
# --------------------------------------------------------------------------
def compute_vor(pool):
    """Value over replacement in SEASON-TOTAL fantasy points.

    Replacement level at a position = the season FPts of the player ranked just
    below the league's startable depth there (slots + 1), among non-Minors
    players eligible at that position. A player's VOR = his total FPts minus the
    replacement level at his best-eligible position (the one giving the highest
    VOR). Using season totals (not a per-game rate) keeps hitters and pitchers on
    a comparable scale, since totals embed playing-time volume.

    This is a PARALLEL value lens: it does not modify win_now or dynasty. It is
    left blank for Minors (no MLB production to measure) and for players with no
    eligible scoring position. Returns (pool, replacement_levels_dict).
    """
    c = CONFIG["cols"]
    slots = CONFIG["vor_startable_slots"]
    not_minors = ~pool["roster_status_norm"].str.contains("Minor", case=False, na=False)

    def _toks(s):
        return [t.strip().upper() for t in str(s).split(",") if t.strip()]

    repl = {}
    for pos, s in slots.items():
        elig = pool[not_minors & pool[c["position"]].map(lambda x: pos in _toks(x))]
        vals = np.sort(elig["fpts_num"].dropna().values)[::-1]
        if len(vals) > s:
            repl[pos] = float(vals[s])
        elif len(vals):
            repl[pos] = float(vals[-1])
        else:
            repl[pos] = np.nan

    def _vor(row):
        if pd.isna(row["fpts_num"]):
            return np.nan, ""
        ts = [t for t in _toks(row[c["position"]]) if t in repl and not pd.isna(repl[t])]
        if not ts:
            return np.nan, ""
        best = max(ts, key=lambda t: row["fpts_num"] - repl[t])
        return row["fpts_num"] - repl[best], best

    res = pool.apply(_vor, axis=1)
    pool["vor"] = [r[0] for r in res]
    pool["vor_pos"] = [r[1] for r in res]
    pool.loc[~not_minors, "vor"] = np.nan          # VOR is a current-MLB-value metric
    pool.loc[~not_minors, "vor_pos"] = ""
    return pool, repl


def compute_forward_vor(pool):
    """Forward-looking value: project a blended (recent + season) rate over the
    games remaining, then run VOR on that projection. A player is valued on his
    rate GOING FORWARD, not his depressed season-to-date total -- which is what
    un-breaks injured/returning stars. Parallel lens; does not modify
    win_now/dynasty/season-VOR. Blank for Minors. Remaining-games and the injury
    haircut are league estimates refined later by the schedule / news layers.
    Returns (pool, replacement_dict, team_games_remaining).
    """
    c = CONFIG["cols"]
    fv = CONFIG["forward_value"]
    slots = CONFIG["vor_startable_slots"]
    not_minors = ~pool["roster_status_norm"].str.contains("Minor", case=False, na=False)

    def _toks(s):
        return [t.strip().upper() for t in str(s).split(",") if t.strip()]

    # --- forward rate: blend recent_fpg with the engine's (regressed) season rate
    season_rate = pool["fpg_regressed"].fillna(0.0)
    if "recent_fpg" in pool.columns:
        rg = pool["recent_games"].fillna(0.0)
        w = fv["recent_max_weight"] * np.clip(rg / fv["recent_full_games"], 0.0, 1.0)
        w = np.where(pool["recent_fpg"].notna(), w, 0.0)     # no recent data -> season only
        forward = w * pool["recent_fpg"].fillna(0.0) + (1 - w) * season_rate
    else:
        forward = season_rate
    pool["forward_fpg"] = np.round(forward, 2)

    # --- remaining games: calendar x role factor (ROS value at full health) ----
    #   team games played ~ the most-played relevant hitter; use the in-pool set so
    #   the thousands of zero-game free agents don't drag the estimate down.
    inpool_h = pool["_inpool"] & (pool["pool_group"] == "H") if "_inpool" in pool.columns \
        else (pool["pool_group"] == "H")
    hg = pool.loc[inpool_h & not_minors, "estimated_games"]
    team_played = float(np.nanpercentile(hg, 95)) if len(hg.dropna()) else 0.0
    team_remaining = max(fv["season_games"] - team_played, 0.0)

    def role_remaining(role):
        if role == "H":
            return team_remaining * fv["fulltime_hitter_rate"]
        if role == "RP":
            return team_remaining * fv["rp_appear_rate"]
        return team_remaining * fv["starts_per_team_games"]     # SP and SP/RP

    pool["remaining_games"] = np.round(pool["role"].map(role_remaining), 1)
    pool["ros_proj"] = np.round(pool["forward_fpg"] * pool["remaining_games"], 1)

    # --- VOR on the projection (same replacement logic, fed projected points) --
    repl = {}
    for pos, k in slots.items():
        elig = pool[not_minors & pool[c["position"]].map(lambda x: pos in _toks(x))]
        vals = np.sort(elig["ros_proj"].dropna().values)[::-1]
        repl[pos] = float(vals[k]) if len(vals) > k else (float(vals[-1]) if len(vals) else np.nan)

    def _rv(row):
        if pd.isna(row["ros_proj"]):
            return np.nan
        ts = [t for t in _toks(row[c["position"]]) if t in repl and not pd.isna(repl[t])]
        if not ts:
            return np.nan
        return row["ros_proj"] - min(repl[t] for t in ts)       # best (scarcest) position
    pool["ros_vor"] = pool.apply(_rv, axis=1).round(1)
    for col in ["forward_fpg", "remaining_games", "ros_proj", "ros_vor"]:
        pool.loc[~not_minors, col] = np.nan
    return pool, repl, team_remaining


def compute_market_gap(pool):
    """Production-vs-market: contrast forward value (ros_vor) with the market's
    price (roster% + overall rank). market_gap > 0 -> the field prices a player
    BELOW his forward value (buy / claim); < 0 -> above (sell). Forward-vs-forward
    by design -- the market prices in injury return, so value must too, or every
    hurt star reads as a false sell. A real-production floor keeps phantom
    high-roster%/zero-production rows out. Parallel lens; modifies no score.
    market_signal gates the raw gap into BUY / SELL / '' so below-replacement
    noise is never called a buy. (Two-way players are mis-valued upstream -- the
    engine picks one role -- so their signal is unreliable; read with care.)
    """
    mg = CONFIG["market_gap"]
    pool["market_gap"] = np.nan
    pool["market_signal"] = ""
    inpool = pool["_inpool"] if "_inpool" in pool.columns else pd.Series(True, index=pool.index)
    pop = inpool & pool["ros_vor"].notna() & (pool["fpts_num"].fillna(0) >= mg["min_fpts"])
    sub = pool[pop]
    if not len(sub):
        return pool
    value_pct = sub["ros_vor"].rank(pct=True) * 100
    rankpct = sub["rkov_num"].map(rank_pct_from_rkov)
    market_raw = mg["ros_weight"] * sub["ros_num"].fillna(0) + mg["rank_weight"] * rankpct
    market_pct = market_raw.rank(pct=True) * 100
    gap = (value_pct - market_pct).round(0)
    pool.loc[pop, "market_gap"] = gap.values

    ros = sub["ros_num"].fillna(0)
    # Label the MISPRICING DIRECTION, not an action. UNDERVALUED + available = a
    # claim; UNDERVALUED + rostered = a buy-low target. OVERVALUED + you own him =
    # sell-high candidate; OVERVALUED you don't = don't acquire. A rostered star
    # flagged OVERVALUED may still be a buy-low if recency/news shows a rebound --
    # the gap is current production vs market price, not a verdict.
    sig = np.where((gap >= mg["signal_threshold"]) & (sub["ros_vor"] > 0)
                   & (ros < mg["buy_max_ros"]), "UNDERVALUED",
          np.where((gap <= -mg["signal_threshold"]) & (ros >= mg["sell_min_ros"]),
                   "OVERVALUED", ""))
    pool.loc[pop, "market_signal"] = sig
    return pool


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run(outdir, mode, managed_team, split=None, rostered=None, fa=None, team_roster=""):
    CONFIG["mode"] = mode
    CONFIG["managed_team"] = managed_team
    c = CONFIG["cols"]

    if split:
        pool = load_split_pool(split["rostered_hitters"], split["rostered_pitchers"],
                               split["fa_hitters"], split["fa_pitchers"])
    else:
        pool = load_player_pool(rostered, fa)
        pool["ip_num"] = np.nan

    if team_roster and os.path.exists(team_roster):
        ip_map = parse_team_roster_ip(team_roster)
        pool["ip_team_roster"] = pool[c["id"]].astype(str).map(ip_map)
        pool["ip_num"] = pool["ip_num"].fillna(pool["ip_team_roster"])

    pool = compute_regressed_fpg(pool)
    pool = compute_win_now(pool)
    os.makedirs(outdir, exist_ok=True)
    pool = attach_prospect_ranks(pool,
                                 misses_path=os.path.join(outdir, "prospect_match_misses.csv"))
    pool = attach_recency(pool)
    pool = compute_dynasty(pool)
    pool, vor_repl = compute_vor(pool)
    print("[vor] replacement FPts by position: " + ", ".join(
        f"{k}={vor_repl[k]:.0f}" for k in CONFIG["vor_startable_slots"]
        if k in vor_repl and not pd.isna(vor_repl[k])))
    pool, fvor_repl, team_rem = compute_forward_vor(pool)
    print(f"[forward] team games remaining~{team_rem:.0f}; projected-VOR replacement: " + ", ".join(
        f"{k}={fvor_repl[k]:.0f}" for k in CONFIG["vor_startable_slots"]
        if k in fvor_repl and not pd.isna(fvor_repl[k])))
    pool = compute_market_gap(pool)
    _sig = pool["market_signal"].value_counts()
    print(f"[market] undervalued={_sig.get('UNDERVALUED', 0)}  overvalued={_sig.get('OVERVALUED', 0)}")

    out_cols = {
        c["player"]: "player", c["team"]: "team", c["position"]: "position",
        "role": "role", c["status"]: "owner_status",
        "roster_status_norm": "roster_status", "age_num": "age",
        "fpts_num": "fpts", "fpg_raw": "fpg_raw", "fpg_regressed": "fpg_regressed",
        "ros_num": "ros_pct", "rkov_num": "rkov", "estimated_games": "estimated_games",
        "sample_confidence": "sample_confidence",
        "win_now_score": "win_now_score", "dynasty_score": "dynasty_score",
        "dynasty_minus_win_now": "dynasty_minus_win_now",
    }
    out = pool[list(out_cols.keys())].rename(columns=out_cols)

    # pitcher-volume / rate columns where available (from the split exports)
    for src, dst in [("ip_num", "ip"), ("ip_pct", "ip_pct"), ("whip", "whip"),
                     ("k_per_9", "k_per_9"), ("qs_rate", "qs_rate")]:
        if src in pool.columns:
            out[dst] = pool[src]

    for src, dst in [("prospect_bonus", "prospect_bonus"), ("age_curve_val", "age_curve"),
                     ("overall_rank_pro", "mlb_overall_rank"), ("org_rank_pro", "mlb_org_rank")]:
        if src in pool.columns:
            out[dst] = pool[src]

    for src, dst in [("vor", "vor"), ("vor_pos", "vor_pos")]:   # value over replacement
        if src in pool.columns:
            out[dst] = pool[src]

    for src, dst in [("recent_fpg", "recent_fpg"), ("recent_games", "recent_games"),
                     ("hot_cold", "hot_cold")]:    # trailing-window form (forward signal)
        if src in pool.columns:
            out[dst] = pool[src]

    for src, dst in [("forward_fpg", "forward_fpg"), ("remaining_games", "remaining_games"),
                     ("ros_proj", "ros_proj"), ("ros_vor", "ros_vor")]:   # forward-looking value
        if src in pool.columns:
            out[dst] = pool[src]

    for src, dst in [("market_gap", "market_gap"), ("market_signal", "market_signal")]:
        if src in pool.columns:
            out[dst] = pool[src]

    if mode == "split":   # Fork 2: surface the market read separately
        out["market_ros"] = pool["_ros_market"].round(1)
        out["market_rank_pct"] = pool["rank_pct_val"].round(1)
        out["market_plusminus"] = pool["plusminus_num"]

    for col in ["fpg_regressed", "win_now_score", "dynasty_score", "dynasty_minus_win_now",
                "sample_confidence", "estimated_games", "ip", "ip_pct", "whip", "k_per_9", "qs_rate",
                "vor", "recent_fpg", "hot_cold", "forward_fpg", "ros_proj", "ros_vor"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("win_now_score", ascending=False)
    os.makedirs(outdir, exist_ok=True)
    ratings_path = os.path.join(outdir, "current_player_ratings.csv")
    out.to_csv(ratings_path, index=False)

    mine = out[out["owner_status"].astype(str).str.fullmatch(managed_team, case=False, na=False)]
    team_path = os.path.join(outdir, f"{managed_team.lower()}_current_player_values.csv")
    mine.to_csv(team_path, index=False)

    print(f"[ok] mode={mode} ip_weight={CONFIG.get('pitcher_ip_pct_weight')} "
          f"players={len(out)} managed({managed_team})={len(mine)}")
    print(f"[ok] wrote {ratings_path}")
    print(f"[ok] wrote {team_path}")
    return out


def main():
    ap = argparse.ArgumentParser(description="In-season ratings engine")
    ap.add_argument("--rostered-hitters"); ap.add_argument("--rostered-pitchers")
    ap.add_argument("--fa-hitters"); ap.add_argument("--fa-pitchers")
    ap.add_argument("--rostered", help="combined rostered/taken (no-stats fallback)")
    ap.add_argument("--fa", help="combined FA pool (no-stats fallback)")
    ap.add_argument("--team-roster", default="")
    ap.add_argument("--outdir", default="./outputs")
    ap.add_argument("--mode", default="faithful", choices=["faithful", "split"])
    ap.add_argument("--ip-weight", type=float, default=None, help="Fork 1 pitcher IP term")
    ap.add_argument("--team", default=CONFIG["managed_team"])
    a = ap.parse_args()
    if a.ip_weight is not None:
        CONFIG["pitcher_ip_pct_weight"] = a.ip_weight
    if a.rostered_hitters:
        split = {"rostered_hitters": a.rostered_hitters, "rostered_pitchers": a.rostered_pitchers,
                 "fa_hitters": a.fa_hitters, "fa_pitchers": a.fa_pitchers}
        run(a.outdir, a.mode, a.team, split=split, team_roster=a.team_roster)
    else:
        run(a.outdir, a.mode, a.team, rostered=a.rostered, fa=a.fa, team_roster=a.team_roster)


if __name__ == "__main__":
    main()
