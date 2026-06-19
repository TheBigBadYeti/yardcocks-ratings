# Yardcocks & Beyond — Ratings System Spec & Project Instructions

This is the source of truth for the fantasy-baseball decision-support system. Any
chat in this Project should read this first. It documents the league, the data
inputs, the scoring engine, the exact formula constants, the prospect layer, and
the open roadmap. When a constant here disagrees with memory, **this file wins**.

---

## 1. Purpose

A decision-support system for a dynasty fantasy baseball team. It ingests Fantrax
exports and produces two ratings per player on a 0–100 scale:

- **win_now_score** — current value; drives waiver, lineup, and start/sit calls.
- **dynasty_score** — long-horizon value; drives keep/trade/prospect calls.

The system is a clean-room rebuild of an earlier tool ("Codex") that lives on a
work machine behind DLP controls. Codex's files cannot leave that machine; the
logic here was reconstructed from plain-text descriptions of Codex's behavior,
then validated against Codex's own anchor rankings. **Do not attempt to ingest
Codex file contents** (including via photos) — the only legitimate channel is a
plain-text description of design/behavior.

---

## 2. League context (Yardcocks & Beyond)

- Format: **Dynasty, head-to-head points**, on Fantrax. 14 active owners, 16-team max.
- Managed team handle in the data: **`Kipp`** (owner Ryan Kipp, team 12).
- Lineups lock **weekly** (first pitch of the week's first game).
- Pitching cap: **12 starts per week**.
- Season: Mar 25 – Sep 27, 2026. Trade deadline: Aug 12, 2026. FAAB: 100, max 7 claims/week.
- Roster: **40 players** — 18 Active (C, 1B, 2B, 3B, SS, 3×OF, UT, 6×SP, 3×RP),
  8 Bench/Reserve, 4 Injured Reserve, 10 Minors.

### Scoring (points per stat)

Hitters: 1B +1, 2B +2, 3B +3, HR +4, R +1, RBI +1, BB +1, SB +2, HBP +1,
CS −1, GIDP −1, K −0.5.

Pitchers: IP **+3**, W +4, QS +3, SV +5, HLD +3, K +1, ER −3, H −1, BB −1, HBP −1.

Note that **IP at +3/inning dominates pitcher scoring** — bulk innings are
extremely valuable in this format. (See §6 on why the engine still does not use IP
as a direct input.)

The 14 owner handles as they appear in the Fantrax `Status` column: `CLANK`,
`Coop`, `GoldTY`, `Greenbet`, `Hutch`, `JMerkle`, `Jpanner`, `KRetiree`, `Kipp`,
`Sasso`, `Sethmc44`, `joeybats`, `kyfaess`, `zyoung51`.

---

## 3. Data inputs (Fantrax exports)

Eight CSV exports. They fall into **two disjoint families** by design — FA-only
vs rostered-only — so a plain stack + de-dup is safe. **The hitter/pitcher SPLIT
exports are the preferred format**: they carry IP plus full component stats
(QS, SV, HLD, ER, K, W, ERA) league-wide, which the combined exports do not.

> **The `__N_` suffix is NOT a stable identifier.** It only reflects the order
> the files were downloaded, so the same content lands on different suffixes from
> one export batch to the next. **Always identify each file by its header
> signature, never by suffix.** (Confirmed: one batch had FA hitters on `__1_`;
> a later batch had them on `__4_`.)

Identify the four split files you need by these signatures:

| Role (engine flag) | `Roster Status` col? | `IP` col? | Stats populated? | Rows (approx) |
|---|---|---|---|---|
| `--rostered-hitters` | yes | no | yes | ~290 |
| `--rostered-pitchers` | yes | **yes** | yes | ~245 |
| `--fa-hitters` | no | no | yes | ~4,600 |
| `--fa-pitchers` | no | **yes** | yes | ~5,000 |

The two **combined** exports (one FA, one rostered) carry no component stats and
roughly double the rows of their split counterparts — ignore them for scoring.
The `Standings` and `Team-Roster` exports are separate (the latter is the only
reliable per-ID IP source for the managed roster).

Key facts:
- Within a family, IDs align; **across families (FA vs owned) they do not** — the
  two families are disjoint, so the same player never appears in both.
- Owner handle and Active/Reserve/Inj Res/Minors status live in the `Status` /
  `Roster Status` columns of the rostered exports. Scrub HTML cruft like
  `W <small>(Wed)</small>` from the status text.
- IP per player for the managed roster is parsed from the **Team-Roster** export's
  pitching section. Fantrax writes its section markers as `["", "Pitching"]`
  (leading blank cell), so the parser must read the marker from the single
  non-empty cell, not `cells[0]`.

### Standard run command

Map each flag to the file whose **header signature** matches (per the table
above) — do not hard-code suffixes.

```
python3 inseason_ratings_engine.py \
  --rostered-hitters  <rostered-hitters file> \
  --rostered-pitchers <rostered-pitchers file> \
  --fa-hitters        <fa-hitters file> \
  --fa-pitchers       <fa-pitchers file> \
  --team-roster       team_roster_real.csv \
  --outdir <dir> --mode faithful --team Kipp
```

Outputs: `current_player_ratings.csv` (all ~10.1k players, full diagnostics) and
`kipp_current_player_values.csv` (managed roster). Also writes
`prospect_match_misses.csv` for review.

---

## 4. The engine

`inseason_ratings_engine.py` — single config-driven file. All tunables live in the
`CONFIG` dict at the top; logic never hard-codes a constant. Two modes:
`faithful` (default, replicates Codex) and `split` (Fork 2: surfaces the market
read — Ros and rank — as separate columns instead of inside win-now).

Pipeline: load split pool → coalesce duplicate name+team rows → prep/normalize →
regressed FP/G → win-now → attach prospect ranks → dynasty.

---

## 5. Formula spec (exact constants)

All component percentiles use a **midpoint-tie percentile**:
`(below + 0.5·equal) / n · 100`, computed **within the filtered hitter or pitcher
pool**. Players outside the pool are still scored against it. Each component is
normalized **before** weighting.

### 5.1 Pool filters (separate hitter / pitcher pools)
- Hitter pool: non-pitcher, not Minors, and (FPts > 25 **or** Ros ≥ 20).
- Pitcher pool: pitcher, not Minors, and (FPts > 20 **or** Ros ≥ 20).

### 5.2 Regression (toward role median)
```
regressed_FPG = raw_FPG · conf + role_median · (1 − conf)
conf          = clip(estimated_games / cap, 0, 1)        # LINEAR, no exponent
estimated_games = FPts / FP_G                            # 0 if FP/G is 0/missing
role_median   = median raw FP/G of all HITTERS (or all PITCHERS) with FP/G > 0
```
`role_median` is hitter-vs-pitcher, **not** by individual position.
Caps: **H 45, SP 11, RP 24, SP/RP 24** (SP/RP uses 24, not the SP cap).

### 5.3 Win-now score (0–100, clipped)
```
0.46·fpg_pct + 0.25·pts_pct + 0.13·ros_pct + 0.08·rank_pct
  + 0.08·(50 + 5·scarcity_bonus) + role_bonus + sp_rp_bonus + status_penalty
```
- `fpg_pct` — percentile of regressed FP/G in pool. `pts_pct` — percentile of total FPts.
- `ros_pct` — raw Ros (0–100). In `split` mode, ros_pct and rank_pct weights are 0.
- `rank_pct` = `100·(1 − (RkOv − 1)/500)`, clipped 0–100; 0 if RkOv missing.

### 5.4 Positional scarcity (additive by eligibility token; multi-eligible sums)
C +4, SS +2, 3B +2, 2B +1, 1B +0, OF +0, SP +2, RP +1. Eligible at **UT only**: −1.

### 5.5 Role / SP-RP bonuses (added to the score; mutually exclusive groups)
- SP with regressed FP/G ≥ 10 → +3. RP with regressed FP/G ≥ 4 → +3.
- SP/RP-eligible: regressed ≥ 7 → +7; 4 ≤ regressed < 7 → +3; else 0.
  (An SP/RP player gets the SP/RP bonus, not the SP-only or RP-only bonus.)

### 5.6 Age curve (additive; dynasty only; missing age → 0)
- Hitter: ≤21 +17, ≤24 +12, ≤27 +6, ≤31 0, ≤34 −5, >34 −12.
- Pitcher: ≤22 +14, ≤25 +10, ≤28 +5, ≤31 0, ≤34 −6, >34 −13.

### 5.7 Status penalties (two separate functions)
- **Win-now**: Active 0, Reserve −4, Inj Res/Injured/IL/Out −22, Minors −30,
  Not On Team −30, Free Agent 0.
- **Dynasty** (separate, not a scaled win-now): Not On Team −24,
  Injured/IL/Out/Inj Res −7, plus an extra −5 if the status text contains a
  serious-injury keyword (elbow, shoulder, forearm, UCL, surgery, 60-day);
  Minors / Reserve / Free Agent / Active 0.

### 5.8 Dynasty score (0–100, clipped)
The non-minor score is no longer the bare weighted backbone — it is a
**confidence-weighted blend** of that backbone with the career **asset value**
(§5.10–5.11). Minors are untouched by the asset layer (their formula is unchanged).
```
old_core   = 0.54·win_now + 0.18·ros + 0.10·rank_pct + age_curve
alpha      = clip(baseline_confidence · 0.60, 0, 0.60)   # 0 for minors / no career
core       = alpha·asset_value + (1 − alpha)·old_core
non-minor: core + prospect_bonus·prospect_phase + dynasty_status_penalty + manual_tag
minor:     24.0 + 0.15·max(win_now, 0) + 0.22·ros + 0.10·rank_pct
             + age_curve + prospect_bonus + dynasty_status_penalty
```
`asset_max_weight = 0.60`: even a full-confidence career sample only *replaces* up
to 60% of the backbone, so win-now production always anchors the score. A
thin/injury-wiped sample (low `baseline_confidence`) leans back toward `old_core`.
`prospect_phase` is the prospect↔asset handoff (§5.11). `manual_tag` is an optional
hand override (default 0).

### 5.9 Prospect bonus (from external MLB Pipeline ranks; see §7)
- By overall rank: ≤20 → +28, ≤50 → +22, ≤100 → +15.
- Else by org rank: ≤5 → +11, ≤15 → +7, ≤30 → +4.
- Grade term `(grade − 50)/2`, clipped [−4, +8] — **currently 0** (no public grade feed).
- **+4 flat** whenever any rank-based bonus applies.
- Minors with no external rank — fallback `clip(Ros/100·15 + age_curve·0.7, 2, 18)`.

### 5.10 Dynasty asset model (`scripts/dynasty_asset.py`)
A career-history projection that values a player by his **expected remaining
production stream**, not just his current line. Computed separately from the
engine and folded into dynasty_score (§5.11). Pipeline per player:

1. **Career baseline** — recency-weighted true-talent FP/G over the last 3 seasons,
   weights `RECENCY_W = [3, 2, 1]` × games. Regressed toward the role median for
   thin samples: `conf = min(career_games / THIN, 1)`,
   `THIN_GAMES = {H 250, SP 60, RP 150, SP/RP 100}`. This `conf` is surfaced as
   `baseline_confidence` (§5.13) and also drives the fold-in alpha.
2. **Skill curve** (age-decline of *rate*, separate from survival). Anchors
   (multiplicative, peak 1.00), interpolated:
   - Hitter: (21,.85)(25,.98)(27,1.0)(30,.96)(32,.90)(34,.80)(37,.60)(40,.38)(43,.15)(45,0)
   - Pitcher: (22,.87)(24,.96)(26,1.0)(29,.96)(31,.90)(33,.81)(35,.66)(38,.40)(41,.15)(44,0)
   These are a **validated skill curve** — the cohort backtest confirmed surviving
   players retain rate almost exactly along this shape through the early 30s. Do
   **not** steepen them to absorb attrition (see §5.12 and §6).
3. **Attrition** (survival) — §5.12. Each future year is multiplied by cumulative
   survival probability, modulated by the player's production tier.
4. **Asset raw** — `Σ_y discount^y · baseline · skill(age+y)/skill(age) ·
   survival_cum(y) · GAMES_YR[role]`, with `HORIZON = 7`, `DISCOUNT = 0.97`,
   `GAMES_YR = {H 150, SP 30, RP 65, SP/RP 45}`. The 7-year horizon deliberately
   penalizes aging stars for a rebuild context.
5. **`dynasty_asset_value`** — 0–100 percentile of asset_raw within the
   established-player pool. This is the `asset_value` blended in §5.8.

Team-aware join `(norm_name, team)`; `TEAM_ALIAS = {CHW→CWS, OAK→ATH, AZ→ARI,
WAS→WSH}`. Reads a committed career cache (`data/career/career_stats.csv`); makes
**zero API calls** at engine time.

### 5.11 Fold-in & prospect↔asset handoff
- `alpha = baseline_confidence · asset_max_weight` (cap 0.60), forced to 0 for
  minors and for anyone with no career match → those fall back to pure `old_core`.
- **Double-count taper:** a NON-minor who now carries a career asset (a graduating
  call-up in an Active/Reserve/IR slot) would otherwise collect both the prospect
  bonus *and* the asset blend. `prospect_phase = (1 − baseline_confidence)` for
  such players (full bonus while the sample is thin, fading to 0 as MLB time
  accrues); minors keep `prospect_phase = 1.0`. Diagnostic cols: `asset_blend_alpha`,
  `prospect_phase`, `prospect_bonus_applied`.

### 5.12 Attrition / survival curve (the term the model was missing)
Aging stars lose dynasty value mostly because they **stop playing**, not because
their rate craters. Survival is a **separate** term from the skill curve, both
role-split and quality-modulated. Annual-survival anchors (interp), calibrated
from an unbiased forward cohort backtest (regular-floor, COVID-clean):
- Hitter: (22,.98)(26,.95)(29,.91)(32,.80)(35,.69)(38,.60)(41,.47)(44,.30)(47,.15)
- Pitcher: (22,.86)(26,.85)(29,.82)(32,.79)(35,.66)(38,.51)(41,.35)(44,.18)(47,.08)

Pitchers attrit far harder and earlier (≈47% 5-yr survival at 23 vs 86% for
hitters); they only converge with hitters around 31–33.

**Quality modulation.** Elite producers survive dramatically better, and the gap
widens with age (hitters: **+39pp at 31–33** — 52% elite vs 13% rest). So the
hazard is modulated by the player's production tier `q` (0–1 percentile of career
baseline within role): `survive = base · (1 + g(age)·(q − 0.5))`, with
`g = clip(slope·(age − 26), 0, max)`, `QUALITY_GAIN = {H (slope .085, max .65),
P (slope .045, max .35)}`. `q` clipped to [0.15, 0.85] (no extrapolation past the
measured tiers); final survival clipped to [0.30, 0.97]. Validated: median 32yo
hitter 5-yr survival 0.20 (cohort 0.21), elite 0.53 (cohort 0.52). The pitcher
premium is intentionally ~half (cohort showed only +11–15pp; the young-pitcher
inversion was small-sample noise). **Calibration caveat:** the hitter premium is
pinned at 31–33; 34–36 and 37+ are smooth extrapolations, not measured points —
refine if the cohort elite-vs-rest table for those buckets is pulled.

### 5.13 Baseline confidence (informational)
`baseline_confidence` (0–1) = the regression `conf` from §5.10 step 1 — how much
real sample backs the baseline vs median-regression filler. Label
`confidence ∈ {LOW <0.35, MED 0.35–0.70, HIGH >0.70}` plus `recent_games`. It is
**informational, not a discount** — a discount would wrongly bury legitimate
injury returnees (e.g. Strider). It does double duty as the fold-in alpha and the
prospect_phase driver.

### 5.14 Consensus anchor (model-vs-market sanity check)
Contrast against FantasyPros **generic** dynasty ECR (manual CSV at
`data/consensus/consensus_ranks.csv`; auto-detects RK / PLAYER NAME, strips
trailing "(TEAM - POS)"). `dynasty_gap = dynasty_asset_value − consensus_value`
(rank→0–100); `dynasty_signal ∈ {BUY_LOW (we ≥ market + 15), SELL_HIGH (market ≥
us + 15), ALIGNED, NO_CONSENSUS}`, `GAP_THRESH = 15`. **Interpretation discipline:**
this is FantasyPros' *generic* scoring, so a BUY_LOW cluster of contact/OBP bats is
usually our league's +BB/−K scoring talking, not a true market error — a real edge
only if leaguemates price off generic ranks. Distinct from `market_gap` (Fantrax
Ros/rank, *this* league), which is the actual trade market. Use `dynasty_gap` as a
model-error check, `market_gap` for trades.

---

## 6. Key design decisions

- **Pitcher volume / IP (Fork 1):** the engine does **not** use IP or GS as a
  direct win-now input (`pitcher_ip_pct_weight = 0.0`). Codex derives pitcher
  volume through FPts / FP-G / estimated_games, not IP directly. A naive IP term
  double-counts FPts volume and craters high-leverage relievers (verified — Mason
  Miller / Cade Smith collapsed in an IP-aware test). IP-derived **rate** columns
  (WHIP, K/9, QS-rate) are surfaced as context only.
- **Multi-eligible / duplicate rows:** rows sharing name+team are coalesced —
  position tokens unioned (so scarcity sees full eligibility), the producing row
  kept, with a guard that two genuinely different same-name players stay separate.
- **Faithful vs current-state prospects:** the engine uses the **live** MLB
  Pipeline list, which removes graduates. This is deliberate: a graduated rookie
  should be valued on his MLB line, not handed a stale prospect bonus on top of it.
  (Codex's older preseason snapshot would double-count graduates.)
- **No paid data.** FanGraphs and any paid membership were rejected; the prospect
  layer uses only free, public MLB Pipeline data.
- **Skill curve ≠ attrition curve (the core aging insight).** Aging hurts dynasty
  value through two independent channels: rate decline (skill) and *ceasing to
  play* (survival). The model keeps them separate. The decomposition came from
  reconciling three backtests — an in-pool test (survivorship-biased: the career
  cache is the 2026 survivor universe, so it falsely showed the curve "too steep"),
  and a forward cohort test at two floors (a 20-game floor admits the September-
  callup fringe and falsely showed "too gentle"; a regular floor gives the truth).
  Key identity: `pop_ret = skill_retention × survival`, and survivor skill matched
  the existing rate curve almost exactly — so the curve was a correct *skill* curve
  that simply lacked a *survival* term. Steepening the rate anchors would have
  rebuilt the "Chris Sale produces 8% of his rate at 38" falsehood; the right fix
  was to add attrition (§5.12). This is also the correct Sale fix — he is killed by
  ~8% survival, not a fake rate collapse — and it preserves the youth growth premium.
- **Durable elites need quality-modulated, not flat, attrition.** A flat population
  hazard buried generational 33-year-olds (Judge, Ramírez) at ~rank 185, which
  would tell a rebuild to sell them for scraps. The +39pp elite survival premium at
  31–33 (§5.12) lifts proven top-tier producers back toward a defensible top-50–100
  while leaving marginal agers correctly buried — the modulation is age- *and*
  tier-selective (young elites barely move; old elites move a lot), which is the
  proof it is not a global softening.

---

## 7. Prospect data layer

- **Source:** MLB Pipeline, the exact ranker Codex used. Free and fetchable:
  - Overall Top 100 — `https://www.mlb.com/prospects/stats/top-prospects`
  - Team Top 30 — `https://www.mlb.com/prospects/stats?teamId=<108–158>`
  Both extract as clean tables (Rk, Player + MiLB id, Tm, Age, Level, stats).
- **Cache:** `prospect_ranks.csv` (name, overall_rank, org_rank, fv_grade).
  Refresh roughly **monthly** — the lists move slowly.
- **Join:** normalized name match (strip accents, suffixes Jr/Sr/II/III, and
  punctuation; lowercase). Proven against the roster: 6 of 10 managed minors hit
  the Top 100; accents resolve (Jesús Made → rank 1). Unmatched prospects are
  written to `prospect_match_misses.csv` for manual review.

### Open prospect items (data-refresh tasks, not code defects)
1. **5 unassigned Top-100 pitcher ranks** — slots 9, 12, 37, 59, 64. Root cause is
   now understood: the stats page only lists prospects with playing time, so a
   ranked pitcher with **0 IP** (injured / not yet debuted) has no row to scrape.
   Backfill these manually from the Pipeline rankings page if any become relevant.
2. **Org-rank tiers (+11/+7/+4)** — coded but inactive until the 30 team Top-30
   pages are pulled. They only affect sub-Top-100 prospects. Pull incrementally in
   the Data Refresh workflow.
3. **Grade term** — no public grade source; stays 0 unless one is added.

---

## 8. Roadmap & workflow chats

The engine is the shared tool; the workflow chats are its consumers. Open them
**after** this spec and the engine are in Project files, in dependency order —
**Data Refresh first**, since it produces the CSVs the others read.

Planned chats: **Data Refresh** → **Player Ratings / News** → **Lineups** →
**Trade / Waivers** → **Front Office**.

Later build-outs (deferred): trade-opportunity board, FA watchlist, news/minors
re-valuation, and a separate **pre-draft dynasty board** engine.

### Open issues status
- **Multi-eligible / duplicate rows — RESOLVED.** The split-export + name+team
  coalesce path yields 0 duplicate name+team rows and 0 dual-role rows on current
  data (was ~31 / ~16).
- **Scarcity calibration — RESOLVED (faithful; do NOT tune the catcher token).**
  Codex was checked directly. It ranks Witt **above** Langeliers (93.49 vs 93.00)
  using the *identical* scarcity table and the same `0.08·(50+5·scarcity)` term
  (catcher +1.6 over a neutral 1B/OF). Same token, same formula — so the catcher
  bonus is **not** the cause of the occasional Witt/Langeliers inversion in our
  output. Component decomposition confirms every non-scarcity term favors Witt
  except `fpg_pct`, where Langeliers' transiently higher FP/G (fewer games at a
  high rate) edges him in some data snapshots. The flip is a sub-0.25-pt near-tie
  riding day-to-day FP/G drift, not a miscalibration. On matching data the ordering
  matches Codex. Codex confirms the token is a hard-coded manual default (no
  external source of truth), so it is tunable — but the evidence says leave it.
- **Dynasty asset model + attrition — BUILT & VALIDATED (§5.10–5.14, §6).** Career
  baseline → validated skill curve → role-split, quality-modulated survival →
  7-yr asset stream, folded into dynasty_score at up to 60% by confidence. Survival
  calibrated against an unbiased forward cohort; quality premium pinned at the
  31–33 hitter anchor. Judge/Ramírez recovered from ~185 to ~80–98; marginal agers
  stay buried; pitchers take steeper, earlier attrition.

### Open items
1. **Two-way players (Ohtani) — OPEN, highest-impact bug.** The engine values only
   one half (hitting *or* pitching) and discards the other, floating Ohtani at
   ~rank 200. Fix = sum his hitting and pitching asset streams. This is the single
   most-wrong answer on the board and is a genuine bug, not a calibration.
2. **Attrition premium beyond 31–33 — extrapolated.** The hitter elite-vs-rest
   premium is measured only at 31–33; 34–36 and 37+ are smooth fits. Pull those
   cohort buckets to replace the extrapolation if Judge/Ramírez-class landings look
   off (`backtest_cohort.py --by-quality` already prints them).
3. **q-tier accuracy audit.** The whole modulation rides on each player's career
   baseline percentile. Spot-check that scoring-favored vets (high-SB/contact, e.g.
   Trea Turner) aren't mis-tiered to the population haircut by an injury-shortened
   recent season dragging the recency-weighted baseline down.
4. **Pitcher durability is tier-flat by design.** The +12pp pitcher premium can't
   distinguish a command-and-health ace from the attrition-prone field; credit
   exceptional veteran-arm durability by hand in trades.

---

## 9. File inventory

**In Project files (durable, shared):**
- `inseason_ratings_engine.py` — core logic (now folds in the asset layer).
- `scripts/dynasty_asset.py` — career→aging→attrition asset model (§5.10–5.14).
- `scripts/snapshot.py` — banks immutable dated ratings copies under `data/snapshots/`.
- `scripts/backtest_aging.py`, `scripts/fetch_cohort.py`, `scripts/backtest_cohort.py`
  — aging-curve validation harness (in-pool + unbiased forward cohort + quality split).
- Committed input caches: `data/career/` (career_stats.csv, cohort.csv),
  `data/consensus/consensus_ranks.csv`, `data/snapshots/` + manifest.
- `prospect_ranks.csv` — semi-durable; refresh monthly.
- League rules PDF.
- This spec (`SYSTEM_SPEC.md`).
- `data/processed/` is **gitignored** (regenerated each run); the engine reads
  caches only and makes zero API calls.

**Uploaded fresh each session (volatile — keep OUT of Project files):**
- The eight Fantrax CSV exports.
- Generated `current_player_ratings.csv`, `kipp_current_player_values.csv`.
- `prospect_match_misses.csv` (per-run review artifact).
