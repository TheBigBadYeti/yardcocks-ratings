---
description: Optimal 18-man lineup + a NEEDS report the waiver step fills
allowed-tools: Bash, Read
---
Run scripts/optimize_lineup.py against data/processed/current_player_ratings.csv with
this week's schedule cache. It assigns hitters by OPTIMAL matching (a multi-position
player goes where he adds the most total points), respects the 12-start cap, and
applies the health layer (benches MLB-IL players Fantrax still shows active).

Show me:
- the 18-man lineup (slot, player, ELIG = Fantrax-eligible positions, games/starts, EWP)
  + projected total,
- SP starts used / 12,
- the LINEUP NEEDS block: unfilled slots (openings), THIN roles, IL openings to IR,
  cap room, and roster fullness,
- the FULL ROSTER breakdown -- all 40 grouped by slot type with eligibility:
  RESERVE/BENCH (startable, not in the optimal 18), MLB-IL-but-active (move to IR),
  Fantrax INJ RES, and MINORS/FARM. This is the roster-management view: who can move
  where, who's occupying an IL slot, and what's stashed in the farm.
- any "assumed"/"projected" starts to verify on ESPN's forecaster before lock.

Eligibility matters for manual overrides -- a 2B/SS/OF player can be moved between
those slots, so the ELIG column shows what each swap is legal.

PROJECTION: EWP does NOT run on the raw season rate. forward_fpg is a season average,
which misprices anyone whose season doesn't describe their present -- a player who
missed time to injury (short, stale sample), one who's gone cold, or one heating up. So
the projection blends RECENT form into the season rate, weighted by recent sample size
and capped at half, and the FORM column shows the adjustment (HOT/cold/even, recent vs
season) so a surprising start or sit is explainable. This is a LINEUP-layer correction
only -- exactly like the health layer. win_now/dynasty are deliberately slow-reacting
and are NOT touched. If the recency cache is missing it warns and falls back to season
rates. The recency cache is refreshed DAILY by a GitHub Action, so this should not
happen; if it warns, check that workflow rather than assuming you must be on a desktop.

Do NOT recommend specific free agents here -- that's /waivers, which reads the needs
this produces (data/processed/lineup_needs.json) and fills them. Here, just surface
the holes and the optimal lineup.

If current_player_ratings.csv is more than ~4 days old, say so and suggest /refresh.
