---
description: Pull the latest published ratings + caches (read-only; readers never write)
allowed-tools: Bash
---
Bring this environment up to date with the source of truth on origin/main, and make
sure it can actually run the decision commands. This is READ-ONLY -- it fetches and
resets to match the remote, and must never commit or push. Whoever ran /refresh last
is the writer; this session only reads.

Steps:
1. **Ensure Python deps** (a fresh cloud VM ships without pandas/numpy; this is a
   no-op on desktop where they're already installed):
   try importing pandas + numpy; if that fails, `pip install -r requirements.txt`.
   Without this, /lineups and /trades error out with ModuleNotFoundError.
2. git fetch origin
3. git reset --hard origin/main
4. Confirm the result so I know it worked:
   git rev-parse HEAD
   Print Randy Arozarena's row from data/processed/current_player_ratings.csv as a
   freshness check (rows + win_now + dynasty).

If the ratings file is missing or empty after sync, say so -- it means no one has
published yet, not that sync failed.
