# Weekly Runbook — Yardcocks & Beyond

The operating manual: what to run, in what order, how often, and how to read the
output without trusting it blindly. Run from the repo root on the **desktop**
(network-enabled) surface. `SYSTEM_SPEC.md` is the source of truth for the engine;
this is the source of truth for the *workflow*.

---

## Cadence

| Cadence | Steps | Why |
|---|---|---|
| **Weekly** (before lineup lock) | 1 export → 2 identify → 3 recency+schedule → 5 engine → 6 snapshot → 7 lineup → 8 shortlists → 9 posture | game state, schedule, and FP/G drift change every week |
| **Monthly-ish** | 4 career + prospect + consensus refresh | these lists move slowly |
| **As needed** | re-run 5–9 after any roster move | keeps the ratings current |

Lineups lock **weekly at first pitch of the week's first game** — run the full
sequence with enough margin to verify the borderline calls before lock.

---

## Weekly sequence

**1. Export from Fantrax.** Pull the player exports. The four hitter/pitcher
**SPLIT** files are the ones that matter (they carry IP + component stats); also
grab the **Team-Roster** export (only reliable per-ID IP for your roster) and
**Standings**. Drop them in `data/raw\`.

**2. Identify the exports by HEADER, never by `__N_` suffix** (the suffix is just
download order and is not stable):
```
python scripts\identify_exports.py data\raw
```
Map each engine flag to the file whose header signature matches (SYSTEM_SPEC §3).

**3. Refresh the weekly caches** (network):
```
python scripts\fetch_recency.py   ...   # recent-form FP/G  (see --help for args)
python scripts\fetch_schedule.py  ...   # this week's games + probables
```
`optimize_lineup` needs a **fresh schedule cache** for the week, or it misfires on
game counts. (Recency is fetched but is **not yet blended into forward_fpg** — see
Known limits.)

**5. Run the engine** → `current_player_ratings.csv` + `kipp_current_player_values.csv`:
```
python inseason_ratings_engine.py ^
  --rostered-hitters  <rostered-hitters file> ^
  --rostered-pitchers <rostered-pitchers file> ^
  --fa-hitters        <fa-hitters file> ^
  --fa-pitchers       <fa-pitchers file> ^
  --team-roster       data\raw\team_roster_real.csv ^
  --outdir data\processed --mode faithful --team Kipp
```

**6. Snapshot** (immutable dated copy for the forward-validation loop):
```
python scripts\snapshot.py --ratings data\processed\current_player_ratings.csv
```

**7. Lineup** (the 18-man, under the 12-start cap):
```
python scripts\optimize_lineup.py --ratings data\processed\current_player_ratings.csv  ...
```
**Fill the 12 starts.** Unused starts = forfeited points in this IP×3 format.
Verify any projected-2nd-start arms on a 10-day forecaster before locking.

**8. Shortlists** (trade + waiver):
```
python scripts\shortlist.py --ratings data\processed\current_player_ratings.csv --team Kipp --posture rebuild
```

**9. Posture** (frames every call above):
```
python scripts\franchise_outlook.py --ratings data\processed\current_player_ratings.csv
```

**Commit** the regenerated `data\processed` + `data\snapshots` if you want the
week banked.

---

## Periodic refresh (monthly-ish)
```
python scripts\fetch_career.py --ratings data\processed\current_player_ratings.csv --season 2026 --outdir data\career
# prospects: rebuild prospect_ranks.csv from MLB Pipeline (SYSTEM_SPEC §7)
# consensus: drop a fresh FantasyPros MLB-dynasty CSV at data\consensus\consensus_ranks.csv
```
`fetch_career` now pulls BOTH stat groups for two-way players (Ohtani).

---

## Reading the output — what to trust, what to verify

- **win_now_score** = season-to-date production value (start/sit, trade-now).
- **dynasty_score** = long-horizon value (keep/trade/stash). Folds in the career
  asset model (aging + quality-modulated attrition) up to 60% by confidence.
- **forward_fpg / ros_vor** = rest-of-season RATE value; injury-neutral, so an IL'd
  star reads as a strong asset, not dead. Feeds lineup + posture.
- **shortlist** SELL/BUY/ADD/STASH, tilted by posture; `_contested` marks a pick
  whose consensus signal contradicts the list (don't lead with those).

### Standing caveats (the model can't see these — you supply the judgment)
1. **Start-cap floor.** The SELL list will hand you your whole rotation because
   aging arms are value-peaks. Don't sell below the bodies needed to fill 12
   starts/week — sell oldest-first and demand arms back.
2. **`SELL_HIGH` ≠ "market overrates."** It means our model rates him *below*
   generic ECR. For an injury-wiped arm that's the model under-rating a returnee
   (Strider pattern) — often a HOLD. Cross-check health.
3. **`BUY_LOW` may be scoring mismatch.** Often our +BB/−K/+SB scoring disagreeing
   with generic ranks — a real edge only if the other owner prices off generic ranks.
4. **Cross-team now-strength is biased UP for injury-heavy rosters** (forward value
   credits IL'd stars at full rate; availability term not yet built). Trust your own
   REBUILD read; sanity-check others' now-ranks by hand.
5. **Pitcher durability is tier-flat** — the model can't tell a durable ace from the
   attrition-prone field; credit known durability manually.
6. **Two-way win-now is still single-role.** Ohtani's *dynasty* value is correct
   (summed halves) but his *win-now* reflects one role — relevant for start/sit.
7. **forward_fpg is not yet recency-weighted** — a genuinely declining (not injured)
   player still reads at his fuller-season rate until the recency blend lands.
