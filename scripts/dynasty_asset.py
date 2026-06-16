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
TEAM_ALIAS = {"CHW": "CWS", "OAK": "ATH", "AZ": "ARI", "WAS": "WSH"}
GAP_THRESH = 15   # |dynasty_gap| (0-100 pts) to flag a model-vs-consensus disagreement

# aging multipliers vs peak=1.0, linearly interpolated between anchors
HIT_ANCHORS = [(21, 0.85), (25, 0.98), (27, 1.00), (30, 0.96), (32, 0.90),
               (34, 0.80), (37, 0.60), (40, 0.38), (43, 0.15), (45, 0.00)]
PIT_ANCHORS = [(22, 0.87), (24, 0.96), (26, 1.00), (29, 0.96), (31, 0.90),
               (33, 0.81), (35, 0.66), (38, 0.40), (41, 0.15), (44, 0.00)]


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


def raw_baseline(seasons):
    """seasons: list of (season, games, fpg). Weighted last-3 true-talent FP/G."""
    last3 = sorted(seasons, key=lambda x: x[0], reverse=True)[:3]
    num = den = 0.0
    total_games = 0.0
    for i, (_, g, fpg) in enumerate(last3):
        w = RECENCY_W[i] * g
        num += w * fpg
        den += w
        total_games += g
    return (num / den if den else 0.0), total_games


def project(base, age, is_pitcher, horizon=HORIZON, discount=DISCOUNT):
    cm = curve(age, is_pitcher) or 0.5
    stream, total = [], 0.0
    for y in range(horizon):
        proj = base * curve(age + y, is_pitcher) / cm
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
    hist = {}
    for k, g in cr.groupby("k"):
        hist[k] = list(zip(g["season"].astype(int), g["games"].astype(float),
                           g["fpg"].astype(float)))

    rows = []
    for _, r in rt.iterrows():
        team = str(r.get("team", "")).strip()
        k = norm_name(r["player"]) + "|" + TEAM_ALIAS.get(team, team)
        k2 = norm_name(r["player"]) + "|" + team
        seasons = hist.get(k) or hist.get(k2)
        if not seasons:
            continue   # prospect / no MLB history -> prospect layer
        role = str(r.get("role", "H"))
        raw, tg = raw_baseline(seasons)
        rows.append({"player": r["player"], "team": team, "role": role,
                     "age": r.get("age"), "raw_base": raw, "games": tg,
                     "is_p": role != "H"})

    df = pd.DataFrame(rows)
    if df.empty:
        if verbose:
            print("[asset] no career matches - check the career cache join")
        return df

    # regress raw baseline toward role median for thin samples
    role_med = df.groupby("role")["raw_base"].median().to_dict()
    base_reg, asset_raw, stream0, conf0 = [], [], [], []
    for _, r in df.iterrows():
        thin = THIN_GAMES.get(r["role"], 200)
        conf = min(r["games"] / thin, 1.0)
        b = r["raw_base"] * conf + role_med.get(r["role"], 0.0) * (1 - conf)
        base_reg.append(round(b, 2))
        conf0.append(round(conf, 2))
        age = r["age"] if pd.notna(r["age"]) else 28
        tot, stream = project(b, float(age), r["is_p"], horizon, discount)
        asset_raw.append(round(tot * GAMES_YR.get(r["role"], 120), 0))
        stream0.append(stream)
    df["career_baseline"] = base_reg
    df["asset_raw"] = asset_raw
    df["dynasty_asset_value"] = pct_rank(asset_raw)
    df["proj_stream"] = [";".join(map(str, s)) for s in stream0]

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
    df[["player", "team", "role", "age", "career_baseline", "recent_games",
        "baseline_confidence", "confidence", "asset_raw", "dynasty_asset_value",
        "proj_stream", "consensus_rank", "consensus_value", "dynasty_gap",
        "dynasty_signal"]].to_csv(out, index=False)
    print(f"[asset] valued {len(df)} players with MLB history -> {out}")
    print(f"[asset] horizon={a.horizon}y discount={a.discount}")
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
