# System State & Decisions — read this after SYSTEM_SPEC.md

This is the living "why" behind the engine. SYSTEM_SPEC.md documents the original
Codex-faithful core; this file documents the value-layer stack built on top of it,
the design decisions behind each piece, what is deliberately unfinished, and the
lessons that shaped it. **Any session on any device should read this before
changing the engine or acting on its outputs.**

---

## 1. The value-layer stack (what each column means, and where it comes from)

All of these are PARALLEL lenses added on top of the faithful Codex scores. They
do NOT modify `win_now_score` or `dynasty_score` — those remain the validated
core. Each lens is additive and reversible.

- **`vor`, `vor_pos`** — Value Over Replacement, in SEASON-TOTAL fantasy points.
  Replacement level per position is computed from the actual free-agent/player
  pool (the player ranked just past the league's startable depth). This REPLACES
  the old flat scarcity tokens (C +4, etc.) with your league's real positional
  economics — catcher scarcity falls out of the math instead of being decreed.
  VOR is BANKED value: what a player has been worth. Blank for Minors.
  *(compute_vor)*

- **`recent_fpg`, `recent_games`, `hot_cold`** — trailing-window production from
  `scripts/fetch_recency.py` (MLB Stats API, scored with the league's exact
  rules; the converter is verified to reproduce Fantrax season totals with zero
  error, quality starts derived per-start from game logs). `hot_cold` = recent
  FP/G minus season FP/G. Pure SIGNAL — surfaces who's trending. *(attach_recency)*

- **`forward_fpg`, `play_rate`, `remaining_games`, `ros_proj`, `ros_vor`** —
  FORWARD value: a blended (recent + season) rate, projected over the games
  remaining, then VOR on that projection. `ros_vor` is the forward equivalent of
  `vor` — what a player is worth FROM HERE. This is the lens that values injured/
  returning stars correctly (on their rate over a full remainder, not their
  depressed season total). Blank for Minors. *(compute_forward_vor)*

- **`market_gap`, `market_signal`** — the edge-finder. Contrasts forward value
  (`ros_vor`) against the market's price (roster% + overall rank). Positive gap =
  the field prices a player BELOW his forward value; negative = above.
  `market_signal` is UNDERVALUED / OVERVALUED / blank. *(compute_market_gap)*

- **Franchise Outlook** (`scripts/franchise_outlook.py`) — team-level posture:
  ranks all 14 teams on present strength (top-18 `ros_vor`) and future strength
  (dynasty + young studs) and returns CONTEND / RETOOL / REBUILD / TEARDOWN /
  STUCK-IN-THE-MIDDLE. This is the frame every trade/waiver/lineup call runs
  through. (As of this writing, Kipp profiles as **REBUILD**.)

---

## 2. Design principles — DO NOT violate without cause

- **News/injury is an OVERLAY, never baked into a score.** `ros_vor` measures
  value AT FULL HEALTH; whether a player is currently hurt is surfaced by the
  news layer as context, not silently subtracted. This keeps scores traceable and
  avoids crude haircuts that re-bury returning stars.
- **Forward value uses RECENT play rate for play-time** (cuts platoon/part-time
  bats), because recent usage = current role. This deliberately spares
  returning-from-injury players (who show high recent play) and currently-injured
  players (no recent data → full-time assumption). Pitchers are exempt — a starter
  making his turns isn't "part-time."
- **The market-gap uses forward value, not banked value.** The market prices in
  injury return, so our value must too — else every injured star reads as a false
  sell. `market_signal` is a MISPRICING DIRECTION, not a trade order: UNDERVALUED +
  available = claim; OVERVALUED + you own him = sell-high candidate; but a star
  flagged OVERVALUED may be a buy-low if recency/news shows a rebound. The human
  decides the action.
- **The parallel lenses never overwrite `win_now`/`dynasty`.** Validate in the
  open before folding anything into the core scores.
- **No paid data.** Free public sources only (MLB Pipeline, MLB Stats API).

---

## 3. Known limitations — do NOT over-trust these

- **Two-way players (Ohtani) are mis-valued.** The engine assigns one role and
  ignores the other side, so their VOR/forward/market signals are unreliable.
- **No park/rate context.** A Coors-inflated bat (e.g., Moniak) projects on his
  raw rate; `forward_fpg` does not adjust for park or quality of competition.
- **No volatility/risk term.** Forward value treats a high-variance arm
  (injury history, wildness) the same as a stable one — a +100 `ros_vor` can be a
  boom/bust profile. A risk flag is on the roadmap.
- **Remaining-games are estimates**, not real schedule counts (≈1 start per 5
  team games, etc.). The schedule layer will replace them.
- **`vor`/`ros_vor`/`market_gap` are lenses, not yet folded into `win_now`/`dynasty`.**
- **Franchise Outlook present-strength needs recency-loaded ratings** (injured
  stars read dead otherwise), and its standings axis is NOT wired in (the standings
  export on hand is incomplete and keys teams by name, not owner handle).

---

## 4. Roadmap (priority order)

1. **Volatility/risk flag** — mark boom/bust arms from injury history (news layer)
   and rate variance, so forward VOR isn't read as a sure thing.
2. **Schedule-aware lineups** — optimize expected weekly points under the
   12-start cap; also replaces the estimated remaining-games constants with real
   schedule counts.
3. **Backtest** — the validation that matters: do these scores predict future
   production better than the market's rank? Weekly `/load` commits are
   accumulating the historical snapshots this needs.
4. **Standings into Franchise Outlook** — needs a clean standings export + a
   team-name → owner-handle map.
5. **Two-way and park/rate context** — later refinements.

---

## 5. Worked lesson — the Gausman/Arozarena trade

A real trade exposed how the lenses interact. Offer: send Gausman + Arozarena,
get Moniak + Arrighetti + Blaze Jordan.
- **Banked value (`vor`)** said reject — a steep current-value loss.
- **Forward value (`ros_vor`)** flipped it toward even, because Arrighetti's
  banked stats hid his forward value (he debuted late, low innings).
- BUT two un-haircut inflations distorted the "lean yes": Moniak's platoon role
  (fixed later by the play-rate adjustment) and Arrighetti's volatility (risk flag
  still pending). Applied properly, giving up Arozarena was an **overpay** —
  Codex's "no" was right.
- The owner's actual move kept Arozarena and sent Gausman + a prospect (Susana)
  instead — capturing Arrighetti's upside at the lower price. The synthesis was
  better than either lens alone.
**Lesson: haircut forward projections (play-rate ✓, risk flag pending) before any
verdict trusts them.**

---

## 6. File inventory & workflow

**Must be in the repo (the shared brain):**
- `inseason_ratings_engine.py` — core + all five lenses above.
- `scripts/fetch_recency.py`, `scripts/franchise_outlook.py`, `scripts/identify_exports.py`
- `data/prospects/prospect_ranks.csv`, `data/recency/recent_fpg.csv` (generated),
  `data/raw/` (weekly exports, tracked), `data/processed/` (committed ratings)
- `SYSTEM_SPEC.md`, this file, `docs/SYSTEM_AUDIT.md`, `README.md`, `requirements.txt`
- `.claude/commands/` — load, refresh, ratings, lineups, trades, gm

**Workflow across devices:**
- **Desktop** = where you RUN: weekly `/load` (fresh exports → engine → commit/push)
  and `/refresh` (news + recency always, prospects if stale).
- **Phone/cloud** = where you THINK: `/gm` reads the committed ratings and talks
  strategy. It consumes; it doesn't run the weekly pipeline.
- Because data and ratings are committed, any device that clones the repo has the
  full current picture.

---

## 7. Caching discipline — pull vs. rate

Expensive external pulls (recency, schedule, career, prospects) live in
standalone desktop fetch scripts that write committed CSV caches. The engine
(re-rating) READS those caches and makes zero API calls — re-rating is free and
never re-pulls. Cadences: recency every /refresh (daily); schedule weekly;
prospects and career monthly — career history is near-immutable, so
career_stats.csv is effectively pull-once. Career and prospect fetches stay OUT
of the frequent /refresh loop.
