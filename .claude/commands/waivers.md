---
description: Waiver adds that fill the exact holes /lineups found, + drops (posture-aware)
allowed-tools: Bash, Read
---
Run scripts/waiver_targets.py against data/processed/current_player_ratings.csv. It
computes this week's lineup needs internally (same engine as /lineups), so it works
standalone. Default posture is our standings-derived rebuild; override with --posture.
--churn defaults to "keeper": fill empty slots always, upgrade weak slots only with
young/upside keeper-quality adds (not a 32-yo streamer for 3 points).

An add is a ROSTER COMMITMENT, not a one-week rental, so the headline ranks by total
value (season production NOW + FUTURE), posture-weighted -- NOT this-week projected
starts. Recent hot form is a capped BALANCE on top, not the driver.

Show me the sections it prints:
- BEST ADDS -- the headline: best FAs by value now + future (posture-weighted, same
  dual valuation as trades), with a capped breakout boost. Each tagged with what it
  also does ([fills opening], [breakout], [returning], [keeper]). A "breakout watch"
  sub-line surfaces the hottest young risers whose season value hasn't caught up.
- STREAM TO FILL THIS WEEK'S OPENINGS -- SECONDARY, explicitly short-term: this-week
  points for empty slots only. Pitching openings = streaming STARTERS (SP/RP), not
  relievers (IP-heavy format).
- RETURNING FROM INJURY -- available FAs on an MLB rehab assignment (value-floored, so
  real assets), grab before activation.
- DROP CANDIDATES -- what an add costs at the 40-man cap.

When presenting:
- Lead with BEST ADDS -- the value plays that help now AND the future. Streaming is
  only if you just need to plug a slot this week.
- Breakouts are small-sample judgment calls, not sure things -- flag them as such.
- IR the IL guys FIRST -- that frees slots without a cut. The tool flags injured
  studs as HOLD (a top asset returns to his slot; never a drop) vs low-value IL you
  could cut. Never surface a current starter, a young keeper, or a >60-value player
  as a drop -- if there's "no easy cut," say so; the move is a trade, not a drop.
- Name each drop as MY decision, not the script's.
- Confirm Fantrax slot eligibility + injury news before committing -- the position
  tokens in the export can lag actual Fantrax eligibility, and recent-form joins on
  name (collisions possible).
- Flag any 2-start "projected" streamer to verify on ESPN's forecaster.

For a hitter's SELL/BUY trade context, that's /trades, not this.
