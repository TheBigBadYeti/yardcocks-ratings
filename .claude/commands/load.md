Weekly data swap — replaces last week's raw exports and regenerates ratings.

Run these steps in order. Do not skip steps or reorder them.

1. **Collect the new exports.** The user has attached this week's Fantrax CSV
   files to the session. Identify them from the session context (they will be
   file paths or attachments, typically named like
   `Fantrax-Players-Yardcocks & Beyond (N).csv` and
   `Fantrax-Team-Roster-Yardcocks & Beyond.csv`).

2. **Delete last week's raw CSVs.**
   ```
   rm data/raw/*.csv
   ```
   Leave data/raw/.gitkeep untouched.

3. **Move this week's exports into data/raw/.**
   Copy or move each attached file into data/raw/. Rename the Team-Roster
   export to `team_roster_real.csv` — that is the filename the engine expects.
   Leave all other filenames as-is (the suffix doesn't matter; identify_exports.py
   reads headers, not names).

4. **Verify the file→flag mapping.**
   ```
   python3 scripts/identify_exports.py
   ```
   Confirm all four split exports are mapped (rostered-hitters, rostered-pitchers,
   fa-hitters, fa-pitchers) and the team-roster is found. If any are missing or
   misidentified, stop and tell the user what's wrong before continuing.

5. **Run the engine.**
   Execute the run command printed by identify_exports.py in step 4. It will
   look like:
   ```
   python3 inseason_ratings_engine.py \
     --rostered-hitters  <file> \
     --rostered-pitchers <file> \
     --fa-hitters        <file> \
     --fa-pitchers       <file> \
     --team-roster       data/raw/team_roster_real.csv \
     --outdir data/processed --mode faithful --team Kipp
   ```
   Confirm the output line shows ~10k players scored and Kipp roster = 40.
   If the counts are far off, stop and report before committing.

6. **Commit and push.**
   ```
   git add -A
   git commit -m "data refresh YYYY-MM-DD"
   git push
   ```
   Use today's actual date in the commit message. End state: GitHub has only
   this week's raw CSVs (last week's are gone) plus the fresh processed ratings.

7. **Print the load summary.** After a successful push, output exactly this block:

   ```
   ── Load complete ──────────────────────────
   CSVs swapped in : <N>
   Players scored  : <total>
   Kipp roster     : <count>
   Pushed to GitHub ✓
   ───────────────────────────────────────────
   ```

   Populate each value from the engine's output line (the `[ok]` line reports
   players and managed-roster count). Count the CSV files copied into data/raw/
   for "CSVs swapped in."

   **Hard stops — do not print the success summary if:**
   - Any of the four required split flags (rostered-hitters, rostered-pitchers,
     fa-hitters, fa-pitchers) was not found by identify_exports.py. Instead,
     print: `⚠ MISSING EXPORTS: <list of missing flags> — fix before committing.`
   - Kipp roster count ≠ 40. Instead, print:
     `⚠ ROSTER COUNT WRONG: engine reported <N>, expected 40 — do not trust these ratings.`
   - Either hard stop fires before the commit step: do not commit, do not push.
