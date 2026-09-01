# ROADMAP — an unbiased review and the plan to make this thing win

Written 2026-08-02 as a third-party review of everything built to date. Read this
before proposing model changes. It supersedes the roadmap sections in
`SYSTEM_STATE.md` §4 and `SYSTEM_SPEC.md` §8, which are stale.

---

## 0. The two findings that reframe everything

### Finding 1 — the core scores have NO predictive edge (measured, not opined)
`scripts/backtest_predictive.py` rank-correlates each score observed at snapshot *t*
against what players actually produced afterward. Longest clean window
(2026-06-16 → 08-02, n=611, ~7 weeks):

| predictor at t            | → future points | → future FP/G |
|---------------------------|:---------------:|:-------------:|
| **win_now_score**         | 0.593           | 0.406         |
| dynasty_score             | 0.604           | 0.330         |
| forward_fpg               | 0.307           | **0.472**     |
| fpts (naive: past points) | 0.596           | 0.363         |
| rkov (the MARKET's rank)  | 0.595           | 0.362         |
| **ros_pct (roster %)**    | **0.630**       | 0.372         |

Read it plainly:
- `win_now` (0.593) ≈ past points (0.596) ≈ market rank (0.595). All the percentile /
  scarcity / bonus machinery **adds nothing** beyond "who has the most points so far."
- The dumbest market signal, **roster %**, out-predicts the whole engine.
- `forward_fpg` is the best **rate** predictor (0.472 vs 0.406) — the one lens pointing
  the right way — but it ignores playing time, so it's poor at volume (0.307).
- **Pitchers are weak everywhere** (~0.36 vs ~0.65 for hitters). Different inputs needed.
- Root cause is architectural: the engine was built to **replicate Codex** ("faithful"
  mode). Faithfully replicating a tool with no edge reproduces no edge. Fidelity to an
  old tool was the objective; **out-of-sample prediction never was**.

What IS genuinely validated: the aging skill curve and the attrition/survival model
(§5.10–5.12 in the spec) were calibrated against real cohorts. That is real work and
should be kept. But it's a multi-year asset model — it can't win a week.

### Finding 2 — last place was mostly variance and rebuild, not the tools
From the standings export: Kipp PF 4066 (**11th** of 14), PA 4466 (**3rd-hardest**
schedule), pythagorean win% **.453 ≈ 7 wins** vs actual **.188 = 3 wins**. That is
~4 wins of pure H2H luck deficit on top of a bottom-third roster that was bottom-third
by design (win-now was sold for youth). Two corollaries:
- Don't read 3-12 as "the model is broken." Read it as: the model gave no edge, and
  variance was brutal.
- **Points-for is a better "true strength" signal than W-L.** Clankas is W-L #6 but
  PF #12 (lucky); Tommy Hustle W-L #7 but PF #2 (unlucky). Trade-partner appetite
  currently keys off W-L; it should key off PF (and PA). See P1-c.

### Also found
- The "edge-finder" lens `market_gap` / `market_signal` described in `SYSTEM_STATE.md`
  **is not in the ratings output** (only `dynasty_gap` vs FantasyPros exists). So there
  is currently no working edge-finder at all.
- Docs drift: SYSTEM_STATE/SPEC still say `/load`, "standings not wired," "processed is
  gitignored," "desktop runs / phone thinks." All false now. A system whose cloud
  sessions read the docs as their brain cannot have wrong docs.
- Data plumbing bugs surfaced this cycle (export disagreement on roster status, name-only
  joins with no MLB IDs, pending-overlay ambiguity, same-day snapshot mismatch). All
  patched, but symptomatic of no validation loop.

---

## 1. The strategic pivot

**Change the objective from Codex-fidelity to out-of-sample predictive accuracy.**
`backtest_predictive.py` is now the scoreboard. A model change ships only if it moves
the numbers in the table above. The target is explicit: **beat `ros_pct` and `rkov`**
on future points, and beat `forward_fpg` on future rate, for BOTH hitters and pitchers.

Where a real, durable edge comes from (in this order of leverage):

1. **League-specific scoring, computed exactly.** This league pays +1 BB, −0.5 K,
   +3 IP, +3 HLD, +2 SB. The market — generic rankings and roster % — prices players on
   generic value. We already reproduce Fantrax totals from components with zero error
   (the recency converter). A projection **in this league's points** where the market
   uses generic value is a structural mispricing the field cannot see. Cheapest edge
   available; the spec even noticed it (§5.14) and then filed it as noise.
2. **Expected stats over surface stats.** Baseball Savant publishes free CSVs (confirmed
   reachable: `leaderboard/expected_statistics?...&csv=true`, 641 rows): xwOBA, xBA,
   xSLG, barrel%, hard-hit% for hitters; K%, BB%, xERA for pitchers. Expected stats
   predict future performance better than actuals — that is their entire purpose. A
   true-talent rate built on them, regressed and recency-blended, is the projection core.
3. **Playing time.** Future *points* are mostly future *volume* (that's why every
   predictor scores ~0.6 on points). A role/games/starts/IP model (rotation spot,
   platoon, closer role, health) is worth more than any rate refinement.
4. **Pitchers as a separate problem.** K%, BB%, IP-per-start, role; the +3 IP means bulk
   innings dominate, and holds/saves are role facts. Current pitcher signal (~0.36) is
   the biggest single hole.
5. **Exploit variance, don't just suffer it.** H2H weekly is high-variance. Streaming for
   2-start weeks, the 12-start cap, and matchup-aware lineups are the only levers that
   turn projection into wins. The lineup layer is the most-improved part of the system;
   keep it the sharpest.

---

## 2. Prioritized plan

### P0 — this week (foundations; done or trivial)
- [x] **Predictive backtest harness** — `scripts/backtest_predictive.py`. Run it after
      every model change. Add to the daily Action so the scoreboard updates itself.
- [x] **Pin dependencies exactly** (`pandas==3.0.3`, `numpy==2.4.6`) so desktop, cloud
      VM, and the Action produce byte-identical ratings — the last "quality falloff."
- [ ] **Log outcomes for the feedback loop**: commit each week's recommended lineup,
      waiver adds, and trade verdicts next to what actually happened. Without this,
      lineups/waivers/trades can never be backtested.

### P1 — before the Aug 12 trade deadline (the season's only remaining lever)
- [ ] **a. Projection v1 in league points.** `scripts/fetch_xstats.py` (Savant hitters +
      pitchers, keyed by MLB ID) → `projection_v1`: expected-stat true-talent rate ×
      recency blend × playing-time estimate, scored in THIS league's points. Ship only if
      it beats `ros_pct`/`rkov` on the backtest.
- [ ] **b. Route decisions through the projection.** `/waivers` value, `/trades` dual
      valuation, and `/posture` currently run on `win_now`/`dynasty` (no edge). Switch
      the NOW half to projection_v1; keep the validated asset model as the FUTURE half.
- [ ] **c. Appetite from points-for, not W-L.** `standings.record_appetite` → blend PF
      rank (true strength) with W-L (what the owner *feels*). Real buyers = high PF.
- [ ] **d. Deadline sell plan.** Kipp is eliminated (8 GB, top-4 playoffs). Generate the
      list of every win-now piece, priced to each real buyer's need, with the youth /
      pick ask. Picks are tradeable (28 rounds) — model them as assets.
- [ ] **e. Fix the missing edge-finder.** Rebuild `market_gap` = projection_v1 − market
      price (roster% + rank), validate it on the backtest, and have `/waivers` surface
      UNDERVALUED-and-available as the headline add.

### P2 — rest of season (make the machine self-correcting)
- [ ] **Pitcher model** (K/BB/IP/role) — target the 0.36 up toward the hitter level.
- [ ] **Playing-time model** — games/starts/IP forward from role + health + platoon.
- [ ] **MLB IDs in the ratings file** — end name-only joins (recency, injuries, xstats
      all key on ID; collisions are silent errors today).
- [ ] **Docs reconciliation** — rewrite SYSTEM_STATE §3/§4/§6 and SPEC §8/§9 to match
      reality; retire `/load` references; note standings + eligibility are wired.
- [ ] **Backtest the lineup layer** once outcome logs exist: did the recommended 18
      outscore the alternatives? Did projected 2nd starts materialize?
- [ ] **Two-way win-now** (Ohtani) — still single-role for start/sit.

### P3 — offseason (where dynasty leagues are actually won)
- [ ] **Pre-draft dynasty board** engine (28-round draft) on projection_v1 + asset model.
- [ ] **Multi-year franchise plan view** — asset value over time, when the window opens,
      what the core is, which vets to flip and when.
- [ ] **Park / matchup context** and a **volatility/risk flag** (both in the old roadmap,
      both still real).

---

## 3. What stays true regardless
- Everything runs through git. Every input, cache, and output is committed; any device
  that clones has the full picture; the daily Action keeps MLB caches current so cloud
  reads what desktop reads. Only remaining cloud difference: writes land on a branch and
  need a PR merge (one tap).
- The user types only `/commands`. See `/gm`.
- Injury and current form are LINEUP facts, not asset facts (the health / form / optioned
  layers). Keep that boundary — it's correct.
- The aging skill curve and quality-modulated attrition are validated. Don't "fix" them.

## 4. Honest limits of this review
- Seven weeks of snapshots is one partial season. The correlations (~0.6, n≈600) are
  solid enough to say "no edge," not enough to fine-tune. Keep snapshotting; re-run
  every week.
- Beating the market is hard. The realistic goal is a consistent few-percent projection
  edge compounded over many decisions, plus the structural league-scoring edge, plus
  sharper variance management — not a magic number.
