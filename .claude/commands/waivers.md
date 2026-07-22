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
- STEP 4 BENCH UPGRADES -- straight 1-for-1 value swaps: cut a dead bench spot, add a
  better asset. Neither player starts, so lineup-impact scoring misses these entirely,
  but they cost no roster spot and no lineup points. In a rebuild these usually matter
  MORE than the streaming above -- a young asset compounds, a streamed reliever in a
  lost week does not. Say so when the posture is rebuild.
- FUTURE-VALUE ADDS -- players who will NOT help this week, shown separately and
  honestly: each costs a drop for zero present points.
- RETURNING FROM INJURY, and DROP CANDIDATES.

STANDING ROSTER POLICY (mine, not the model's): run the farm FULL at 10, and keep MLB
Reserve/bench spots for players who can actually play. A prospect sitting on Reserve
with 0 GP is a wasted MLB spot -- demote him into a farm slot vacated by the weakest
prospect. The tool surfaces this in STEP 1; treat it as a real move, not an aside, and
flag that minors eligibility has to be confirmed in Fantrax.

AFTER I ACT: when I tell you which moves I actually made in Fantrax, record each one --
  python scripts/pending_moves.py add|drop|ir "<player>"
That overlay makes /lineups and /waivers agree with my real roster immediately, instead
of optimizing a team I no longer have. The export won't show the moves until the next
/refresh, which clears the overlay. Record ONLY what I confirm I did -- never what was
merely recommended.

When presenting:
- Lead with the roster blockers -- a recommendation you can't legally execute is worse
  than none. If IR is full, say that before naming any add.
- The plan is ORDERED with dependencies first, and each add's gain is MARGINAL (on top
  of the moves above it), not standalone -- present it that way.
- Give the MEASURED lineup delta for each move. Never say a player "would help"
  without the number.
- Flag THIN SAMPLE adds as gambles, not recommendations.
- Name each drop as MY decision. It never suggests a current starter, a young keeper,
  or a >60-value player -- if nothing is cuttable it says so and points to trade.
- Confirm Fantrax slot eligibility before committing (export position tokens can lag).
