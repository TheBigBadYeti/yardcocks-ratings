---
description: Regenerate ratings from new Fantrax exports (identify -> fetch -> engine -> snapshot)
allowed-tools: Bash, Read
disable-model-invocation: true
---
Run the weekly data refresh. New Fantrax exports are in data/raw.

1. Run scripts/identify_exports.py on data/raw and show me the file->flag mapping.
   STOP and wait for my confirmation before running anything else -- a mis-mapped
   export silently corrupts the entire run, so this is the one manual checkpoint.
2. After I confirm: fetch the recency and schedule caches (fetch_recency.py,
   fetch_schedule.py).
3. Run inseason_ratings_engine.py with the confirmed flags to regenerate
   data/processed/current_player_ratings.csv.
4. Run scripts/snapshot.py to bank a dated copy.

Report only the mapping, then one line confirming the engine ran and how many
players are in the new ratings file. Do not dump the ratings or run the consumers --
those are /lineup, /trades, /waivers, /posture.
