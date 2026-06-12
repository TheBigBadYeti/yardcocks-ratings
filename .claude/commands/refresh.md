Bring all external data current: news (always), recency (always), prospect ranks (if stale),
engine (if prospects changed). Run the steps in order.

---

## Step 1 — News (always run)

Fetch recent MLB transactions from the public MLB Stats API (no auth required):

```
https://statsapi.mlb.com/api/v1/transactions?startDate=<14 days ago>&endDate=<today>
```

Use today's date and 14 days prior in YYYY-MM-DD format.

The response is JSON. Each transaction has fields including: `date`, `player.fullName`,
`typeDesc` (e.g. "Placed on 10-Day Injured List", "Recalled From Minors",
"Designated for Assignment"), and `description`.

**Filter logic:**
1. Load the Kipp roster names from `data/processed/kipp_current_player_values.csv`
   (column: `player` or `name` — use whatever the engine writes).
2. Normalize names for matching: lowercase, strip accents, strip Jr/Sr/II/III/IV
   suffixes and punctuation (same normalization as the prospect join in SYSTEM_SPEC.md §7).
3. Keep any transaction where the normalized player name matches a Kipp roster player.
4. Also keep transactions for high-profile free agents (RkOv ≤ 100 in the FA pool from
   `current_player_ratings.csv`) — these are relevant to waiver decisions.

**Write** `data/news/recent_moves.csv` with columns:
`date, player, type, description, roster_flag`
where `roster_flag` = `kipp` if the player is on the Kipp roster, `fa` if a notable FA,
blank otherwise.

Add a comment row at the top: `# generated: <ISO timestamp>`.

---

## Step 2 — Recency (always run)

Run the recency fetcher to pull each player's trailing-30-day fantasy production:

```
python3 scripts/fetch_recency.py
```

This calls the MLB Stats API, scores each player's component stats with the exact league
rules (same conversion validated against Fantrax season exports — zero error), and writes
`data/recency/recent_fpg.csv` with columns:
`name, mlb_id, recent_games, recent_fpts, recent_fpg, group`

**Known limitation:** the `byDateRange` endpoint does not populate `qualityStarts`.
The script treats missing QS as 0, so SP recent_fpts are understated by 3 × actual_QS.
For a typical SP with 4 QS in 30 days that's ~12 FPts undercount — modest relative to
~100–140 FPts total, but flag it when discussing SP recency scores explicitly.
`holds` and all other fields populate correctly.

Note the player count printed (should be ~1,000+) and the top-5 hottest players. If the
count is below 500, something is wrong with the API call — investigate before continuing.

---

## Step 3 — Prospect ranks (only if stale or forced)

Check the modification date of `data/prospects/prospect_ranks.csv`.

- **If ≤ 21 days old** and the user did not say "force": skip the pull. Note the cache age
  in the summary and move to Step 4.
- **If > 21 days old** or the user said "force": re-pull.

**To re-pull prospect ranks:**
1. Fetch the MLB Pipeline Top 100:
   `https://www.mlb.com/prospects/stats/top-prospects?type=all&minPA=0`
   Use a high token limit (~25 000) so the pitcher table tail is not truncated.
   Parse both the batter and pitcher tables; the union of the Rk column is the Top 100.
2. Fetch team Top-30 pages in batches:
   `https://www.mlb.com/prospects/stats?teamId=<108..158>`
   Rk on those pages = org rank (team Top-30 position).
3. Rebuild `data/prospects/prospect_ranks.csv` (columns: name, overall_rank, org_rank,
   fv_grade). Preserve any manual backfills for ranked pitchers with 0 IP (they won't
   appear in the stats table — leave their overall_rank blank and carry forward any
   existing value from the old file).
4. Note how many rows changed vs. the previous file.

---

## Step 4 — Engine re-run (only if prospects changed)

- If prospect ranks were **skipped** in Step 3: do not re-run. News and recency are
  overlays and never change scores, so they alone do not trigger a re-run.
- If prospect ranks were **re-pulled and changed**: run the engine using the existing
  raw exports already in `data/raw/` (identified via `scripts/identify_exports.py`).
  Confirm ~10 k players scored and Kipp roster = 40.
- If prospect ranks were re-pulled but **no rows changed**: skip the re-run and say so.

---

## Step 5 — Commit and push

Stage whatever changed: `data/news/recent_moves.csv`, `data/recency/recent_fpg.csv`,
`data/prospects/prospect_ranks.csv` (if refreshed), `data/processed/*.csv` (if engine re-ran).

```
git add -A
git commit -m "refresh <YYYY-MM-DD>: <short summary of what ran>"
git push
```

Example messages:
- `refresh 2026-06-18: news + recency + prospects + engine`
- `refresh 2026-06-18: news + recency (prospects current, 8d old)`
- `refresh 2026-06-18: news + recency + prospects refreshed, no rank changes, engine skipped`

---

## Step 6 — Print summary

```
── Refresh complete ─────────────────────────────
News          : <N> moves in last 14 days
                <K> touch Kipp roster: <comma-separated player names>
Recency       : <N> players  window <start>..<end>
                top-5: <name(fpts), ...>
Prospects     : <refreshed (N rows changed) | skipped (Nd old, next due Nd)>
Engine        : <re-ran — 10123 players, Kipp=40 | skipped>
Pushed ✓
─────────────────────────────────────────────────
```

List the Kipp-touching moves by name so they are immediately visible. If no moves
touch the Kipp roster, say so explicitly — that is also useful information.

If the Kipp roster count ≠ 40 after an engine run, do not push: print
`⚠ ROSTER COUNT WRONG: engine reported <N> — investigate before pushing.`
