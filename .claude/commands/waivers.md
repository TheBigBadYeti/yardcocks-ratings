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
- STASH -- young dynasty upside, not tied to a hole.
- DROP CANDIDATES -- what an add costs at the 40-man cap.

When presenting:
- Lead with the OPENINGS -- those are free points and a fieldable lineup.
- IR the IL guys FIRST -- that frees slots without a cut. Name each drop as MY
  decision, not the script's; it never suggests a current starter or a young keeper.
- Confirm Fantrax slot eligibility + injury news before committing -- the position
  tokens in the export can lag actual Fantrax eligibility.
- Flag any 2-start "projected" streamer to verify on ESPN's forecaster.

For a hitter's SELL/BUY trade context, that's /trades, not this.
