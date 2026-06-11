# Yardcocks & Beyond — Dynasty Ratings Engine

Decision-support system for the `Kipp` dynasty fantasy-baseball team (Fantrax,
14-owner H2H points). Produces `win_now_score` and `dynasty_score` (0–100) per
player from Fantrax exports + live MLB Pipeline prospect ranks.

See `SYSTEM_SPEC.md` for the full formula spec and `CLAUDE.md` for the operating
rules Claude Code follows.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Weekly run
1. Export the 8 Fantrax CSVs + the Team-Roster export; drop them in `data/raw/`.
2. Detect which file is which (suffixes are unstable — never assume):
   ```bash
   python3 scripts/identify_exports.py
   ```
   It prints a ready-to-paste run command with the correct `--flag file` mapping.
3. Run that command. Outputs land in `data/processed/`:
   - `current_player_ratings.csv` — all ~10k players, full diagnostics
   - `kipp_current_player_values.csv` — managed roster
   - `prospect_match_misses.csv` — prospects that didn't name-match, for review
4. Commit any changes to engine / spec / prospect ranks.

## Monthly
Refresh `data/prospects/prospect_ranks.csv` from the live MLB Pipeline list — ask
Claude Code to run `/refresh` (see `.claude/commands/refresh.md`).

## What's committed vs ignored
- Committed (durable): engine, spec, `prospect_ranks.csv`, league PDF, this README.
- Ignored (volatile): everything in `data/raw/` and `data/processed/`.
