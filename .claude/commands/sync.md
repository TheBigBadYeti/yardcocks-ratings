---
description: Pull desktop's latest published ratings (read-only; cloud never writes)
allowed-tools: Bash
---
Bring this environment up to date with the source of truth on origin/main. This is
READ-ONLY -- it fetches and resets to match the remote. It must never commit or push.
Cloud is a reader; desktop is the only writer.

Steps:
1. git fetch origin
2. git reset --hard origin/main
3. Confirm the result so I know it worked:
   git rev-parse HEAD
   Print Randy Arozarena's row from data/processed/current_player_ratings.csv as a
   freshness check (rows + win_now + dynasty).

If the ratings file is missing or empty after sync, say so -- it means desktop hasn't
published yet, not that sync failed.
