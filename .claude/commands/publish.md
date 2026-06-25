---
description: Review and publish the latest ratings to main for cloud to read
allowed-tools: Bash
---
This publishes desktop's freshly-built ratings as the source of truth cloud reads.
Generate and publish are deliberately separate -- run /refresh first, eyeball the
output, THEN publish. Do not auto-run this as part of refresh.

Steps:
1. Show me what changed before committing anything:
   git status --short
   git diff --stat
   Print Randy Arozarena's row from data/processed/current_player_ratings.csv as a
   sanity check that the file is real and current, not empty or stale.
2. Confirm the ratings file actually has rows (fail loud if it's empty -- an empty
   or missing CSV means the refresh failed and must NOT be published).
3. Only if it looks sane, commit and push:
   git add data/processed/current_player_ratings.csv data/snapshots/
   git commit -m "weekly ratings publish"
   git push origin main
4. Confirm the new HEAD hash so I can verify cloud matches it.

If anything looks off -- empty file, unexpected diff, a player score that swung wildly
-- STOP and tell me instead of publishing. Better to skip a week than push garbage to
the file cloud trusts.
