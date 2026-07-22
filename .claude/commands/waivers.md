---
description: Roster-aware waiver MOVES with measured lineup impact and the drop each costs
allowed-tools: Bash, Read
---
Run scripts/waiver_targets.py against data/processed/current_player_ratings.csv. It
computes this week's lineup needs internally (same engine as /lineups), so it works
standalone. Posture defaults to our standings-derived rebuild; override with --posture.

This does NOT hand back a list of names to go research. Every recommendation is a
complete transaction with a measured effect and a stated cost.

Show me what it prints:
- ROSTER vs HARD LIMITS -- 40 total = 18 Active / 8 Reserve / 4 IR / 10 Minors, plus
  the FAAB cap (max 7 claims/week). Lead with any BLOCKER: most importantly, if IR is
  4/4 FULL we canNOT park an injured player there to dodge a cut -- an IR slot has to
  be cleared first, and it names the cheapest occupants to release.
- MOVES THAT IMPROVE THIS WEEK'S LINEUP -- each one is "ADD x <- drop y" with:
    WHY    the concrete reason (fills an empty slot / outproduces the weakest starter),
           plus hot form, keeper status, injury return, and a THIN SAMPLE warning when
           the projection rests on a small sample.
    LINEUP the MEASURED gain -- the optimizer is re-run with that player in the pool,
           so "+13.0 EWP" is computed, not asserted. A player who wouldn't crack the
           18 shows no gain and is not recommended as a lineup help.
    COST   the drop it forces at 40/40, and the weekly claim it spends.
- FUTURE-VALUE ADDS -- players who will NOT help this week, shown separately and
  honestly: each costs a drop for zero present points.
- RETURNING FROM INJURY, and DROP CANDIDATES.

When presenting:
- Lead with the roster blockers -- a recommendation you can't legally execute is worse
  than none. If IR is full, say that before naming any add.
- Give the MEASURED lineup delta for each move. Never say a player "would help"
  without the number.
- Flag THIN SAMPLE adds as gambles, not recommendations.
- Name each drop as MY decision. It never suggests a current starter, a young keeper,
  or a >60-value player -- if nothing is cuttable it says so and points to trade.
- Confirm Fantrax slot eligibility before committing (export position tokens can lag).
