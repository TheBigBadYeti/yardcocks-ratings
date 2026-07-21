---
description: Weekly ratings refresh — ingest exports, regenerate, publish to GitHub (run-from-anywhere)
allowed-tools: Bash, Read
disable-model-invocation: true
---
The ONE weekly writer command. Turns new Fantrax exports into fresh ratings and
publishes them to GitHub so every reader (`/sync` + all the decision commands) sees
them. Runs from any environment with git push access — desktop or cloud. There is
exactly ONE writer at a time; never run this in two places at once.

Two ways to supply this week's exports:
- ATTACHED to this session   -> the command swaps them into data/raw for you.
- ALREADY in data/raw        -> uploaded through the GitHub web UI and committed.

The only step that can't be automated is downloading the CSVs from Fantrax (behind
your login). Everything after that happens in the repo.

Run these steps IN ORDER. Do not reorder or skip.

1. **Sync to origin first** (never build on a stale base):
   `git fetch origin && git pull --ff-only`
   If the pull fails (history diverged), STOP and report it — do not force or reset.
   A diverged history means another writer pushed; resolve that before continuing.

2. **Ingest this week's exports — then PROVE they actually landed.**
   `data/raw/` ships pre-populated with LAST week's committed exports, and in a cloud
   session uploaded files land in a separate upload folder, NOT in `data/raw/`. So
   "files are in data/raw" does NOT mean they're this week's. Ingest explicitly:
   - If new CSVs are ATTACHED / uploaded to this session: `rm data/raw/*.csv` (leave
     `.gitkeep`), copy each uploaded file into `data/raw/`, and rename the Team-Roster
     export to `team_roster_real.csv`. Leave other filenames as-is (identify_exports
     reads headers, not names).
   - If exports were committed via the GitHub web UI: step 1's pull already brought
     them in; swap nothing.
   **HARD STOP GUARD:** run `git status --short data/raw/`. It MUST show changes
   (added/deleted/modified). If `data/raw/` shows NO changes, your new exports did NOT
   get ingested — you're about to score last week's data. Stop and fix the copy.

3. **Map exports to engine flags:** `python3 scripts/identify_exports.py`
   Show me the file->flag mapping. HARD STOP if any of the four splits (rostered-hitters,
   rostered-pitchers, fa-hitters, fa-pitchers) is missing, OR if two files map to the
   same flag (last week's + this week's both present). Say exactly what's wrong.

4. **Fetch the network caches:** fetch_recency.py, fetch_schedule.py, fetch_injuries.py.
   These hit the MLB Stats API. From a **cloud VM they will likely 403** (MLB blocks
   datacenter IPs; if your environment allowlists `statsapi.mlb.com` they may work —
   worth trying). A 403 here is NOT fatal: the scripts preserve the prior committed
   caches, and **the ratings file does not depend on them** — only `/lineups` and
   `/trades` do. If they fail, note it and continue; refresh the caches from DESKTOP
   for full freshness.

5. **Run the engine** command that identify_exports.py printed. It writes
   `data/processed/current_player_ratings.csv`.

6. **Sanity-gate the output.** HARD STOP and do NOT commit if:
   - Kipp roster count != 40, or
   - total players scored is far from ~10k, or
   - the regenerated ratings are byte-identical to the committed version (a real
     refresh moves some scores — identical output means you scored stale data; go
     back to step 2).
   Print Randy Arozarena's row (win_now + dynasty) as a live freshness check.

7. **Snapshot + publish** (only if step 6 passed):
   ```
   python3 scripts/snapshot.py --label weekly      # writes data/snapshots/ + manifest
   git add data/raw/ data/processed/current_player_ratings.csv data/snapshots/ \
           data/recency/ data/schedule/ data/injuries/il_status.csv
   git commit -m "data refresh YYYY-MM-DD"          # today's real date
   git push origin main
   ```
   The caches (recency/schedule/injuries) are committed too: a reader (cloud/phone)
   can't refetch them (MLB blocks cloud VMs), so `/lineups` relies on whatever the
   last MLB-capable writer committed. A cloud-only refresh will leave them stale —
   that's expected; only a desktop/laptop writer refreshes them.
   Report the new HEAD hash. **In a cloud session** the push may go to a session
   branch, not `main` (cloud guards `main`): if so, confirm the push to `main` when
   prompted, or merge the branch's PR — readers only see ratings once they're on
   `main`. If the push FAILS (no write auth), say so plainly: the ratings are built and
   committed locally but NOT published.

8. **Print the summary block:**
   ```
   -- Refresh complete --------------------------
   Exports mapped : <N>
   Players scored : <total>
   Kipp roster    : <count>
   Snapshot       : data/snapshots/ratings_YYYY-MM-DD.csv
   Published      : <HEAD hash> on <branch>  (pushed to main / branch / NOT pushed)
   ----------------------------------------------
   ```

This is the single writer command — it replaces the old /load and /publish (both
folded in). `/sync` is the read-only counterpart for reader sessions.
