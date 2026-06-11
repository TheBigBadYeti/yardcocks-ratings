Read data/processed/current_player_ratings.csv and data/processed/kipp_current_player_values.csv
and answer season-level roster questions — not day-to-day start/sit calls. Interpret existing
win_now_score and dynasty_score values per SYSTEM_SPEC.md; do not re-derive formulas.

Answer whichever of the five lenses below the user asks about. If no specific lens is named,
run all five and present them as labeled sections.

---

**1. Contender vs. Rebuild**
Sum win_now_score across Kipp's 18 Active slots (from kipp_current_player_values.csv,
status = Active). Compare that aggregate to the league median and top-3 rosters implied
by standings position (if standings data is available) or to the full-roster win_now
distribution in current_player_ratings.csv. Return: contender / fringe / rebuild verdict
with a one-line rationale. Then sum dynasty_score across the full 40-man and compare to
the same benchmark. Flag if the win-now and dynasty reads point in opposite directions
(e.g., high win-now / low dynasty = sell-high window; low win-now / high dynasty = buy-low
or rebuild).

**2. Positional Depth Map**
For each of the 9 active position slots (C, 1B, 2B, 3B, SS, OF, UT, SP, RP), list Kipp's
rostered players eligible at that slot ranked by win_now_score. Identify:
- **Surplus**: 3+ viable starters (win_now ≥ 55) at a slot — potential trade chips.
- **Hole**: fewer than 2 viable starters at a slot, or the top option's win_now < 45.
- **Thin bench**: only 1 reserve behind the starter at a multi-start slot (SP, RP).
Use roster slot counts from SYSTEM_SPEC.md (C×1, 1B×1, 2B×1, 3B×1, SS×1, OF×3, UT×1,
SP×6, RP×3; 8 Bench/Reserve, 4 Inj Res, 10 Minors).

**3. Keep / Cut Calls — 40-Man Review**
Surface Kipp's weakest dynasty assets as drop candidates. From kipp_current_player_values.csv,
sort ascending by dynasty_score. Flag the bottom 5–8 players where dynasty_score < 35 and
win_now_score < 40, noting why each scores low (age curve, status penalty, no prospect bonus,
weak FPts). Cross-check: do not recommend dropping anyone in the top 12 of their position
by win_now_score (they may be a positional fill). Present as a ranked cut list with a
one-line case for each.

**4. Trade Deadline Posture (buy / sell / hold)**
Trade deadline is Aug 12, 2026. Today's date is provided in context. Using the win-now
aggregate from lens 1 and current standings position (if provided):
- **Buy** if win_now aggregate is top-5 in the league and dynasty_score total is ≥ 60% of
  win-now total (sustainable enough to mortgage some prospect depth).
- **Sell** if win_now aggregate is bottom-5 or dynasty_score total exceeds win-now total by
  > 15 pts/player on average (better future than present — flip veterans for prospects).
- **Hold** otherwise.
List 2–3 specific sell chips (surplus position + high win-now, lower dynasty) and 1–2 buy
targets by position hole identified in lens 2. Be direct; do not default to "it depends."

**5. Minor-League Pipeline Health**
From kipp_current_player_values.csv, filter status = Minors. Sort by dynasty_score descending.
Report:
- Top prospects (dynasty_score ≥ 55): names, positions, dynasty score, and whether they
  appear in prospect_ranks.csv (overall_rank or org_rank present).
- Mid-tier (35–54): names and scores — watch list or depth only?
- Pipeline depth score: count of Minors players with dynasty_score ≥ 45, as a rough
  "prospect units" total. Compare: ≥ 5 = deep, 3–4 = adequate, < 3 = thin.
Flag any Minors player with a status penalty (Inj Res) eating into their dynasty score.
