---
description: Optimal 18-man lineup under the 12-start cap (real EWP optimizer)
allowed-tools: Bash, Read
---
Run scripts/optimize_lineup.py against data/processed/current_player_ratings.csv with
this week's schedule cache (same invocation as the weekly run). This replaces the old
win_now ranking -- it uses schedule-aware EWP and respects the 12-start cap.

Show me ONLY:
- the 18-man lineup (slot, player, games/starts, EWP) and the projected total,
- how many of the 12 SP starts are used, and
- flags: any UNFILLED starts (free points in this IP-heavy format -- name the best
  FA streamers to fill them, and whether 2-start arms are on waivers), plus any
  "assumed" (unconfirmed) starts to verify before lock.

Nothing else. If current_player_ratings.csv is more than ~4 days old, say so and
suggest /refresh first.
