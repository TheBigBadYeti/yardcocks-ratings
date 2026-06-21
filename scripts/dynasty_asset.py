#!/usr/bin/env python3
"""
dynasty_asset.py - multi-year dynasty asset valuation.

Turns the cached career history into a forward-looking asset value, so players
are valued as the multi-year assets they are in a dynasty league - not on this
season alone.

Pipeline (per player WITH MLB career history):
  career baseline   weighted last-3-season true-talent FP/G (recency 3/2/1,
                    games as confidence, regressed toward role median for thin
                    samples)
  aging projection  project that baseline across a 5-year hold window using
                    position aging curves (hitters peak ~27, pitchers ~26 with
                    steeper late attrition)
  asset value       discounted sum of projected FP/G over the window, then a
                    0-100 percentile within the career-player pool

Players with no MLB history (prospects) are left to the prospect layer - the two
partition cleanly. Reads committed caches only; no network.

CONFIG (all tunable):
  HORIZON   5      hold-window years projected
  DISCOUNT  0.97   light - a REBUILD keeps out-year value (a contender lowers it)
"""
import argparse, os, re, unicodedata
import pandas as pd
import numpy as np

HORIZON = 7
DISCOUNT = 0.97
RECENCY_W = [3, 2, 1]
THIN_GAMES = {"H": 250, "SP": 60, "RP": 150, "SP/RP": 100}   # games for full confidence
GAMES_YR = {"H": 150, "SP": 30, "RP": 65, "SP/RP": 45}        # season games/appearances by role
MIN_SECONDARY_GAMES = 20   # a two-way player's 2nd career must clear this to count
TEAM_ALIAS = {"CHW": "CWS", "OAK": "ATH", "AZ": "ARI", "WAS": "WSH"}
GAP_THRESH = 15   # |dynasty_gap| (0-100 pts) to flag a model-vs-consensus disagreement

# aging multipliers vs peak=1.0, linearly interpolated between anchors. These are
# SKILL-decline curves (rate among players still playing) -- validated against the
# cohort backtest's survivor retention, so they are NOT changed to chase population
# numbers. Population decline = skill * survival; survival lives separately below.
HIT_ANCHORS = [(21, 0.85), (25, 0.98), (27, 1.00), (30, 0.96), (32, 0.90),
               (34, 0.80), (37, 0.60), (40, 0.38), (43, 0.15), (45, 0.00)]
PIT_ANCHORS = [(22, 0.87), (24, 0.96), (26, 1.00), (29, 0.96), (31, 0.90),
               (33, 0.81), (35, 0.66), (38, 0.40), (41, 0.15), (44, 0.00)]

# ATTRITION: annual P(a rostered REGULAR at this age is still one next year),
# calibrated from the cohort backtest's 5-year survival (regular-floor, COVID-clean).
# Split by role -- pitchers attrit far harder and earlier (47% 5y survival at 23
# vs 86% for hitters). The asset model was missing this term entirely; aging stars
# lose dynasty value mostly because they STOP PLAYING, not because their rate craters.
ATTRITION_ENABLED = True
HIT_SURVIVE_ANCHORS = [(22, 0.98), (26, 0.95), (29, 0.91), (32, 0.80), (35, 0.69),
                       (38, 0.60), (41, 0.47), (44, 0.30), (47, 0.15)]
PIT_SURVIVE_ANCHORS = [(22, 0.86), (26, 0.85), (29, 0.82), (32, 0.79), (35, 0.66),
                       (38, 0.51), (41, 0.35), (44, 0.18), (47, 0.08)]

# Durability premium: ELITE producers survive dramatically better, and the gap
# widens with age (hitters: +39pp at 31-33, ~0 when young). So the hazard is
# modulated by the player's production tier q (0-1 percentile within role): a
# top-tier bat carries far less attrition than the median regular. (start, slope,
# max) of the per-year survival gain; pitchers ~half the hitter premium (the
# cohort showed +11-15pp, and the young inversion was small-sample noise).
QUALITY_GAIN = {"H": (26, 0.085, 0.65), "P": (26, 0.045, 0.35)}
Q_CLIP = (0.15, 0.85)          # don't extrapolate past the measured tiers
SURVIVE_CLIP = (0.30, 0.97)


def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def curve(age, is_pitcher):
    anchors = PIT_ANCHORS if is_pitcher else HIT_ANCHORS
    if age <= anchors[0][0]:
        return anchors[0][1]
    if age >= anchors[-1][0]:
        return anchors[-1][1]
    for (a0, m0), (a1, m1) in zip(anchors, anchors[1:]):
        if a0 <= age <= a1:
            return m0 + (m1 - m0) * (age - a0) / (a1 - a0)
    return anchors[-1][1]


def _interp(anchors, x):
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (a0, v0), (a1, v1) in zip(anchors, anchors[1:]):
        if a0 <= x <= a1:
            return v0 + (v1 - v0) * (x - a0) / (a1 - a0)
    return anchors[-1][1]


def survive_annual(age, is_pitcher, q=0.5):
    """Annual survival, modulated by production tier q (0-1 within role). q=0.5 is
    the median regular (population hazard); elite producers (high q) carry a much
    lower hazard, the gap widening with age."""
    base = _interp(PIT_SURVIVE_ANCHORS if is_pitcher else HIT_SURVIVE_ANCHORS, age)
    start, slope, gmax = QUALITY_GAIN["P" if is_pitcher else "H"]
    g = min(max(slope * (age - start), 0.0), gmax)
    qc = min(max(q, Q_CLIP[0]), Q_CLIP[1])
    s = base * (1.0 + g * (qc - 0.5))
    return min(max(s, SURVIVE_CLIP[0]), SURVIVE_CLIP[1])


def raw_baseline(seasons, current_season=None):
    """seasons: list of (season, games, fpg). Weighted last-3 true-talent FP/G.

    The in-progress CURRENT season is down-weighted by its completeness so a noisy
    ~70-game midseason partial doesn't drag a vet's baseline (or, symmetrically,
    inflate a hot start). Completeness = current games / the player's OWN prior
    full-season level (role-agnostic: a starter's 32 and a reliever's 65 both
    calibrate themselves). Extra weight factor = (g / full)^1, on top of the usual
    games weighting, so a 20-game April sample is nearly ignored, a 70-game June
    sample is roughly halved, and a finished 150-game season is back to full weight.
    Past injury-shortened seasons are untouched (only season == current_season)."""
    ordered = sorted(seasons, key=lambda x: x[0], reverse=True)
    last3 = ordered[:3]
    prior_full = max((g for s, g, _ in ordered[1:] if g > 0), default=0.0)
    num = den = 0.0
    total_games = 0.0
    for i, (s, g, fpg) in enumerate(last3):
        w = RECENCY_W[i] * g
        if current_season is not None and s == current_season and prior_full > 0:
            w *= min(g / prior_full, 1.0)      # de-weight the in-progress partial
        num += w * fpg
        den += w
        total_games += g
    return (num / den if den else 0.0), total_games


def project(base, age, is_pitcher, q=0.5, horizon=HORIZON, discount=DISCOUNT):
    """Expected value stream = skill-decline (curve) * cumulative survival
    (attrition, quality-modulated) * time discount."""
    cm = curve(age, is_pitcher) or 0.5
    stream, total, surv_cum = [], 0.0, 1.0
    for y in range(horizon):
        if ATTRITION_ENABLED and y > 0:
            surv_cum *= survive_annual(age + y - 1, is_pitcher, q)
        proj = base * curve(age + y, is_pitcher) / cm * surv_cum
        stream.append(round(proj, 2))
        total += (discount ** y) * proj
    return round(total, 2), stream


def pct_rank(values):
    v = np.asarray(values, dtype=float)
    order = v.argsort().argsort()
    return np.round(order / max(len(v) - 1, 1) * 100, 1)

def compute_asset_values(rt, career_path, consensus_path=None,
                         horizon=HORIZON, discount=DISCOUNT, verbose=False):
    """Core asset valuation, importable by the engine.

    rt: a ratings DataFrame carrying at least player / team / role / age.
    Returns a DataFrame (one row per player WITH MLB-career history) with
    career_baseline, recent_games, baseline_confidence + confidence label,
    asset_raw, dynasty_asset_value, proj_stream, and -- if a consensus file is
    given -- consensus_rank/value + dynasty_gap/dynasty_signal. Players with no
    career match are dropped here (they belong to the prospect layer)."""
    if not career_path or not os.path.exists(career_path):
        if verbose:
            print(f"[asset] no career cache at {career_path!r}")
        return pd.DataFrame()
    cr = pd.read_csv(career_path, encoding="utf-8")
    cr["k"] = cr["name"].map(norm_name) + "|" + cr["team"].astype(str).str.strip()
    # history keyed by (k, GROUP) so a two-way player's hitting and pitching
    # seasons stay separate -- blending a 3.5 hit rate with a 14 pit rate into one
    # baseline is nonsense. (Latent until the cache carries both groups; the
    # two-way fetch in fetch_career.py now does.)
    if "group" not in cr.columns:
        cr["group"] = "hitting"
    # the in-progress season (max in the cache) is de-weighted in raw_baseline by
    # its completeness so a noisy midseason partial doesn't drag/inflate baselines
    current_season = int(cr["season"].max()) if len(cr) else None
    histg = {}
    for (k, grp), g in cr.groupby(["k", "group"]):
        histg[(k, grp)] = list(zip(g["season"].astype(int), g["games"].astype(float),
                                   g["fpg"].astype(float)))

    def _seasons(k, k2, grp):
        return histg.get((k, grp)) or histg.get((k2, grp))

    # one "half" per (player, group) with MLB history; a two-way player gets two,
    # each valued on its own curve / attrition / quality tier / games-per-year.
    # The PRIMARY half (by role) is always kept (preserves single-role behavior);
    # a SECONDARY half must clear MIN_SECONDARY_GAMES so a position player's
    # mop-up inning (or a pitcher's token PA) doesn't fabricate a second career.
    rt_rows = list(rt.iterrows())
    halves = []
    for i, (_, r) in enumerate(rt_rows):
        team = str(r.get("team", "")).strip()
        k = norm_name(r["player"]) + "|" + TEAM_ALIAS.get(team, team)
        k2 = norm_name(r["player"]) + "|" + team
        role = str(r.get("role", "H"))
        primary = "P" if role != "H" else "H"
        prl = role if role in ("SP", "RP", "SP/RP") else "SP"
        for grp, seasons, is_p, games_role in (
            ("H", _seasons(k, k2, "hitting"), False, "H"),
            ("P", _seasons(k, k2, "pitching"), True, prl),
        ):
            if not seasons:
                continue
            raw, tg = raw_baseline(seasons, current_season)
            if grp != primary and tg < MIN_SECONDARY_GAMES:
                continue   # not a real second career -> ignore
            halves.append({"pidx": i, "grp": grp, "games_role": games_role,
                           "is_p": is_p, "raw_base": raw, "games": tg})

    hv = pd.DataFrame(halves)
    if hv.empty:
        if verbose:
            print("[asset] no career matches - check the career cache join")
        return pd.DataFrame()

    # regress each half toward the median of its games_role; quality tier is a
    # percentile WITHIN group (hitter vs pitcher scales differ), so a two-way
    # player's bat and arm are tiered against their own peers.
    role_med = hv.groupby("games_role")["raw_base"].median().to_dict()
    hv["q_tier"] = hv.groupby("grp")["raw_base"].rank(pct=True).fillna(0.5)

    h_raw, h_conf, h_base, h_stream = [], [], [], []
    for _, h in hv.iterrows():
        thin = THIN_GAMES.get(h["games_role"], 200)
        conf = min(h["games"] / thin, 1.0)
        b = h["raw_base"] * conf + role_med.get(h["games_role"], 0.0) * (1 - conf)
        rr = rt_rows[int(h["pidx"])][1]
        age = rr.get("age") if pd.notna(rr.get("age")) else 28
        tot, stream = project(b, float(age), h["is_p"], h["q_tier"], horizon, discount)
        h_raw.append(tot * GAMES_YR.get(h["games_role"], 120))
        h_conf.append(conf); h_base.append(round(b, 2)); h_stream.append(stream)
    hv["asset_raw_half"] = h_raw
    hv["half_conf"] = h_conf
    hv["half_base"] = h_base
    hv["half_stream"] = h_stream

    # aggregate halves -> one row per player; SUM the asset streams (the two-way
    # fix). Single-role players are unchanged (one half == old behavior).
    rows, conf0 = [], []
    for pidx, grp in hv.groupby("pidx"):
        rr = rt_rows[int(pidx)][1]
        role = str(rr.get("role", "H"))
        g_tot = float(grp["games"].sum())
        cw = float((grp["half_conf"] * grp["games"]).sum() / g_tot) if g_tot else 0.0
        hit_half = grp[grp["grp"] == "H"]
        prim = hit_half if len(hit_half) else grp   # display the bat for two-way
        rows.append({
            "player": rr["player"], "team": str(rr.get("team", "")).strip(),
            "role": role, "age": rr.get("age"), "is_p": role != "H",
            "games": g_tot, "career_baseline": float(prim["half_base"].iloc[0]),
            "asset_raw": round(float(grp["asset_raw_half"].sum()), 0),
            "proj_stream": ";".join(map(str, prim["half_stream"].iloc[0])),
            "two_way": len(grp) > 1,
            "baseline_detail": "+".join(f"{x['grp']}:{x['half_base']}"
                                        for _, x in grp.iterrows()),
        })
        conf0.append(round(cw, 2))

    df = pd.DataFrame(rows)
    df["dynasty_asset_value"] = pct_rank(df["asset_raw"])

    # baseline confidence: how much real recent sample backs the baseline vs how
    # much is median-regression filler. INFORMATIONAL -- a LOW means "trust this
    # number less," in EITHER direction (thin-sample rookie reads high, injury-
    # wiped vet reads low; both are soft). Deliberately not a discount.
    df["recent_games"] = df["games"].round(0)
    df["baseline_confidence"] = conf0
    df["confidence"] = pd.cut(df["baseline_confidence"], [-0.01, 0.35, 0.70, 1.01],
                              labels=["LOW", "MED", "HIGH"]).astype(str)

    # --- consensus anchor: contrast OUR asset value vs external dynasty ECR ----
    df["consensus_rank"] = np.nan
    df["consensus_value"] = np.nan
    df["dynasty_gap"] = np.nan
    df["dynasty_signal"] = "NO_CONSENSUS"
    if consensus_path and os.path.exists(consensus_path):
        cs = pd.read_csv(consensus_path, encoding="utf-8")
        rcol = next((c for c in cs.columns
                     if c.strip().lower() in ("consensus_rank", "rank", "rk", "ecr")), None)
        ncol = next((c for c in cs.columns
                     if c.strip().lower() == "name" or "player" in c.strip().lower()), None)
        if rcol and ncol:
            cs["k"] = (cs[ncol].astype(str).str.replace(r"\s*\(.*\)\s*$", "", regex=True)
                       .map(norm_name))
            cs[rcol] = pd.to_numeric(cs[rcol], errors="coerce")
            cs = (cs.dropna(subset=[rcol]).sort_values(rcol)
                    .drop_duplicates("k", keep="first"))   # dup names -> best rank
            n = max(len(cs), 1)
            df["consensus_rank"] = df["player"].map(norm_name).map(
                dict(zip(cs["k"], cs[rcol])))
            df["consensus_value"] = (100.0 * (1.0 - (df["consensus_rank"] - 1.0)
                                              / max(n - 1, 1))).clip(0, 100).round(1)
            df["dynasty_gap"] = (df["dynasty_asset_value"] - df["consensus_value"]).round(1)

            def _sig(g):
                if pd.isna(g):
                    return "NO_CONSENSUS"
                if g >= GAP_THRESH:
                    return "BUY_LOW"     # we rate him well ABOVE market
                if g <= -GAP_THRESH:
                    return "SELL_HIGH"   # market rates him well above us
                return "ALIGNED"
            df["dynasty_signal"] = df["dynasty_gap"].map(_sig)
            if verbose:
                matched = int(df["consensus_rank"].notna().sum())
                print(f"[asset] consensus matched {matched}/{len(df)} vs {n}-player "
                      f"ECR (gap thresh +/-{GAP_THRESH})")
        elif verbose:
            print("[asset] consensus file present but no name/rank columns; skipping gap")
    elif verbose:
        print(f"[asset] no consensus file at {consensus_path!r}; dynasty_gap blank "
              "(drop a FantasyPros MLB-dynasty CSV there to enable)")

    return df.sort_values("dynasty_asset_value", ascending=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--career", default="data/career/career_stats.csv")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--discount", type=float, default=DISCOUNT)
    ap.add_argument("--outdir", default="data/processed")
    ap.add_argument("--consensus", default="data/consensus/consensus_ranks.csv")
    a = ap.parse_args()

    rt = pd.read_csv(a.ratings, encoding="utf-8")
    df = compute_asset_values(rt, a.career, a.consensus, a.horizon, a.discount,
                              verbose=True)
    if df.empty:
        return
    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.join(a.outdir, "dynasty_asset_values.csv")
    df[["player", "team", "role", "age", "two_way", "baseline_detail",
        "career_baseline", "recent_games",
        "baseline_confidence", "confidence", "asset_raw", "dynasty_asset_value",
        "proj_stream", "consensus_rank", "consensus_value", "dynasty_gap",
        "dynasty_signal"]].to_csv(out, index=False)
    print(f"[asset] valued {len(df)} players with MLB history -> {out}")
    print(f"[asset] horizon={a.horizon}y discount={a.discount}")
    tw = df[df["two_way"]]
    if len(tw):
        print(f"[asset] two-way (summed hitting+pitching): "
              f"{', '.join(tw['player'] + ' [' + tw['baseline_detail'] + ']')}")
    print("\nTop 12 dynasty assets:")
    print(df.head(12)[["player", "team", "role", "age", "career_baseline",
                       "confidence", "dynasty_asset_value"]].to_string(index=False))

    flagged = df[df["dynasty_signal"].isin(["BUY_LOW", "SELL_HIGH"])]
    if len(flagged):
        flagged = flagged.reindex(flagged["dynasty_gap"].abs().sort_values(
            ascending=False).index)
        print("\nBiggest model-vs-consensus disagreements:")
        print(flagged.head(15)[["player", "team", "age", "dynasty_asset_value",
                                "confidence", "consensus_rank", "dynasty_gap",
                                "dynasty_signal"]].to_string(index=False))


if __name__ == "__main__":
    main()
