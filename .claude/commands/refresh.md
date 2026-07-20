---
description: Weekly ratings refresh — ingest exports, regenerate, publish to GitHub (run-from-anywhere)
allowed-tools: Bash, Read
disable-model-invocation: true
---
The ONE weekly writer command. Turns new Fantrax exports into fresh ratings and
publishes them to GitHub so every reader (`/sync` + all the decision commands) sees
them. Runs from any environment with git push access — desktop or cloud. There is
exactly ONE writer at a time; never run this in two places at once.

Two ways to supply this week's exports (auto-detect which applies):
- ATTACHED to this session   -> the command swaps them into data/raw for you.
- ALREADY in data/raw        -> e.g. uploaded through the GitHub web UI and pulled
  down; the command uses what's already there and swaps nothing.

The only step that can't be automated is downloading the CSVs from Fantrax (behind
your login). Everything after that happens in the repo.

Run these steps IN ORDER. Do not reorder or skip.

1. **Sync to origin first** (never build on a stale base):
   `git fetch origin && git pull --ff-only`
   If the pull fails (history diverged), STOP and report it — do not force or reset.
   A diverged history means another writer pushed; resolve that before continuing.

2. **Ingest this week's exports:**
   - If Fantrax CSVs are ATTACHED to this session: delete last week's raw CSVs
     (`rm data/raw/*.csv`, leave `.gitkeep`), copy each attachment into `data/raw/`,
     and rename the Team-Roster export to `team_roster_real.csv`. Leave the other
     filenames as-is — identify_exports reads headers, not names.
   - If NOTHING is attached: assume `data/raw/` already holds this week's set (web
     upload) and continue. Do NOT delete anything.

3. **Map exports to engine flags:** `python3 scripts/identify_exports.py`
   Show me the file->flag mapping. HARD STOP (do not continue) if any of the four
   splits (rostered-hitters, rostered-pitchers, fa-hitters, fa-pitchers) is missing,
   OR if two files map to the same flag (last week's + this week's both present).
   Say exactly what's wrong.

4. **Fetch the network caches:** fetch_recency.py, fetch_schedule.py, fetch_injuries.py.

5. **Run the engine** command that identify_exports.py printed. It writes
   `data/processed/current_player_ratings.csv`.

6. **Sanity-gate the output.** HARD STOP and do NOT commit if:
   - Kipp roster count != 40, or
   - total players scored is far from ~10k.
   Print Randy Arozarena's row (win_now + dynasty) as a live freshness check.

7. **Snapshot + publish** (only if step 6 passed). Use today's real date:
   ```
   cp data/processed/current_player_ratings.csv data/history/ratings_YYYY-MM-DD.csv
   git add data/raw/ data/processed/current_player_ratings.csv data/history/ratings_YYYY-MM-DD.csv
   git commit -m "data refresh YYYY-MM-DD"
   git push origin main
   ```
   Report the new HEAD hash. If the push FAILS (e.g. no write auth in this
   environment), say so plainly — the ratings are built and committed locally but NOT
   published, and no reader will see them until someone with push access pushes.

8. **Print the summary block:**
   ```
   -- Refresh complete --------------------------
   Exports mapped : <N>
   Players scored : <total>
   Kipp roster    : <count>
   Snapshot       : data/history/ratings_YYYY-MM-DD.csv
   Published      : <HEAD hash>  (pushed / NOT pushed -- <reason>)
   ----------------------------------------------
   ```

This is the single writer command — it replaces the old /load and /publish (both
folded in). `/sync` is the read-only counterpart for reader sessions.
