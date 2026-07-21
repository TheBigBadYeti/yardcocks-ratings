---
description: Waiver adds that fill the exact holes /lineups found, + drops (posture-aware)
allowed-tools: Bash, Read
---
Run scripts/waiver_targets.py against data/processed/current_player_ratings.csv. It
computes this week's lineup needs internally (same engine as /lineups), so it works
standalone. Default posture is our standings-derived rebuild; override with --posture.
--churn defaults to "keeper": fill empty slots always, upgrade weak slots only with
young/upside keeper-quality adds (not a 32-yo streamer for 3 points).

Show me the sections it prints:
- FILL THESE OPENINGS -- unfilled slots (0 pts). In this IP-heavy league, pitching
  openings are filled by STREAMING STARTERS (SP/RP who start this week), not relievers.
- UPGRADES -- keeper-quality FAs who beat a weak starter's slot (posture-gated).
- HOT / RECENT FORM -- FAs whose RECENT per-game beats their season rate (call-ups &
  heaters the win_now/dynasty model still fades). Small-sample by nature -- judgment
  bets, not sure things.
- STASH -- young dynasty upside, not tied to a hole.
- DROP CANDIDATES -- what an add costs at the 40-man cap.

When presenting:
- Lead with the OPENINGS -- those are free points and a fieldable lineup.
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
