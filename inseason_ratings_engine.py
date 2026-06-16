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
    # --- career asset fold-in (dynasty_asset.py) ---------------------------
    # For non-minor players WITH MLB history, the career+aging asset value is a
    # richer estimate of future value than the win_now/age_curve backbone, so it
    # progressively REPLACES that backbone. Weight = baseline_confidence *
    # asset_max_weight, so a thin/injury-wiped sample leans back on the old core
    # instead of overriding it (capped, never 100%, since ros/rank carry real
    # market signal). Prospects (no career) and minors are untouched.
    "asset_fold": {
        "enabled": True,
        "asset_max_weight": 0.60,   # cap on how much asset value can replace the core
        "career_path": "data/career/career_stats.csv",
        "consensus_path": "data/consensus/consensus_ranks.csv",
        "horizon": 7, "discount": 0.97,
    },
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

    # --- age curve: step thresholds (additive), separate H / P -------------
    #     (age <= threshold -> adjustment); missing age -> 0
    "age_curve_hitter": [(21, 17), (24, 12), (27, 6), (31, 0), (34, -5), (999, -12)],
    "age_curve_pitcher": [(22, 14), (25, 10), (28, 5), (31, 0), (34, -6), (999, -13)],

    "managed_team": "Kipp",   # owner handle in the Status column

    # --- Fork 1: direct pitcher innings (available league-wide via the
    #     hitter/pitcher split exports). 0.0 = faithful (volume only via FPts);
    #     >0 blends an IP-percentile term into pitcher win-now.  # CALIBRATE
    "pitcher_ip_pct_weight": 0.0,
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


def attach_asset_values(pool):
    """Compute career+aging asset values (scripts/dynasty_asset.py) and merge
    dynasty_asset_value / baseline_confidence / dynasty_gap onto the pool so
    compute_dynasty can fold them into dynasty_score. Degrades gracefully: any
    failure (no career cache, import error) leaves the columns absent and
    dynasty_score falls back to the base formula."""
    af = CONFIG.get("asset_fold", {})
    c = CONFIG["cols"]
    if not af.get("enabled"):
        return pool
    try:
        import sys as _sys
        sd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
        if sd not in _sys.path:
            _sys.path.insert(0, sd)
        import dynasty_asset as _da
        rt = pd.DataFrame({"player": pool[c["player"]], "team": pool[c["team"]],
                           "role": pool["role"], "age": pool["age_num"]})
        adf = _da.compute_asset_values(rt, af.get("career_path"),
                                       af.get("consensus_path"),
                                       af.get("horizon", 7), af.get("discount", 0.97),
                                       verbose=True)
        if adf is None or adf.empty:
            print("[asset-fold] no asset values produced; using base dynasty formula")
            return pool
        adf["_mk"] = adf["player"].astype(str) + "|" + adf["team"].astype(str)
        mk = pool[c["player"]].astype(str) + "|" + pool[c["team"]].astype(str)
        for src, dst in [("dynasty_asset_value", "dynasty_asset_value"),
                         ("baseline_confidence", "baseline_confidence"),
                         ("confidence", "asset_confidence"),
                         ("career_baseline", "career_baseline"),
                         ("recent_games", "recent_games"),
                         ("dynasty_gap", "dynasty_gap"),
                         ("dynasty_signal", "dynasty_signal")]:
            if src in adf.columns:
                pool[dst] = mk.map(dict(zip(adf["_mk"], adf[src])))
        n = int(pd.to_numeric(pool["dynasty_asset_value"], errors="coerce").notna().sum())
        print(f"[asset-fold] merged asset value onto {n} players with MLB history")
    except Exception as e:
        print(f"[asset-fold] skipped ({type(e).__name__}: {e}); base dynasty formula")
    return pool


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

    # Future-value backbone (win-now + market + crude age curve). The career
    # asset value is a richer estimate of this same thing, so for non-minor
    # players WITH MLB history it progressively REPLACES the backbone, weighted
    # by baseline confidence (thin/injury-wiped samples lean back on the backbone
    # rather than overriding it). av is a percentile within the established-player
    # pool; blending it with the backbone is an approximate but monotonic mix.
    old_core = (nm["win_now"] * pool["win_now_score"] + nm["ros"] * ros
                + nm["rank"] * rank_pct + age_adj)
    af = CONFIG.get("asset_fold", {})
    alpha = np.zeros(len(pool))
    if af.get("enabled") and "dynasty_asset_value" in pool.columns:
        av = pd.to_numeric(pool["dynasty_asset_value"], errors="coerce")
        cf = pd.to_numeric(pool.get("baseline_confidence"), errors="coerce")
        alpha = (cf.fillna(0.0) * af.get("asset_max_weight", 0.60)).where(
            av.notna(), 0.0).to_numpy()
        core = alpha * av.fillna(0.0).to_numpy() + (1 - alpha) * old_core
    else:
        core = old_core
    non_minor = core + prospect + dyn_pen
    minor = (mn["base"] + mn["win_now"] * np.clip(pool["win_now_score"], 0, None)
             + mn["ros"] * ros + mn["rank"] * rank_pct + age_adj + prospect + dyn_pen)

    pool["dynasty_score"] = np.clip(np.where(is_minors, minor, non_minor), 0, 100)
    pool["dynasty_minus_win_now"] = pool["dynasty_score"] - pool["win_now_score"]
    pool["asset_blend_alpha"] = np.round(alpha, 3)
    pool["age_curve_val"] = age_adj
    pool["prospect_bonus"] = prospect
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
    pool = attach_asset_values(pool)
    pool = compute_dynasty(pool)

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

    # career asset fold-in diagnostics (present only when the fold-in ran)
    for src, dst in [("dynasty_asset_value", "asset_value"),
                     ("asset_confidence", "asset_confidence"),
                     ("baseline_confidence", "asset_conf_num"),
                     ("career_baseline", "career_baseline"),
                     ("asset_blend_alpha", "asset_blend_alpha"),
                     ("dynasty_gap", "dynasty_gap"),
                     ("dynasty_signal", "dynasty_signal")]:
        if src in pool.columns:
            out[dst] = pool[src]

    if mode == "split":   # Fork 2: surface the market read separately
        out["market_ros"] = pool["_ros_market"].round(1)
        out["market_rank_pct"] = pool["rank_pct_val"].round(1)
        out["market_plusminus"] = pool["plusminus_num"]

    for col in ["fpg_regressed", "win_now_score", "dynasty_score", "dynasty_minus_win_now",
                "sample_confidence", "estimated_games", "ip", "ip_pct", "whip", "k_per_9", "qs_rate"]:
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
