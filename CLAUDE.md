# CLAUDE.md — Yardcocks & Beyond ratings engine

Operational brief, auto-loaded every session. **For the full formula spec, read
`SYSTEM_SPEC.md` before touching any scoring logic.** This file is the short
version: what to do, what not to break.

## Working style
Be a rigorous, honest collaborator. Challenge weak ideas, flag risks and flawed assumptions,
and suggest better alternatives — do not default to agreement or soften real problems. When
you push back, say why and propose the better move.

## What this is
A dynasty fantasy-baseball decision system for the managed team **`Kipp`** (owner
Ryan Kipp, team 12) in a 14-owner Fantrax H2H-points league. It ingests Fantrax
CSV exports and produces `win_now_score` and `dynasty_score` (0–100) per player.
Clean-room rebuild of an older tool ("Codex") on a DLP-locked work machine.

## Hard rules — do not violate
- **Never ingest Codex file contents** (including via photos). The only legitimate
  channel from Codex is a plain-text description of design/behavior.
- **Identify Fantrax exports by header content, never by filename suffix.** The
  `__N_` suffix is download-order only and shifts between batches. Run
  `python3 scripts/identify_exports.py` to map files → engine flags each refresh.
- **Do not "fix" these faithful design choices** (each verified against Codex):
  - Pitcher IP weight stays **0.0** — volume rides through FPts, not a direct IP
    term (a naive IP term craters high-leverage relievers).
  - Catcher scarcity token stays **+4** — Codex uses the identical value; the
    occasional Witt/Langeliers inversion is data-snapshot drift, not miscalibration.
  - Prospect ranks use the **live** MLB Pipeline list (graduates removed).
- **Commit after any change to the engine, spec, or prospect ranks.** Git is the
  single source of truth; uncommitted edits are how cross-session drift starts.

## Standard run (weekly)
1. Drop the 8 fresh Fantrax CSV exports + the Team-Roster export into `data/raw/`.
2. `python3 scripts/identify_exports.py` → prints the verified run command.
3. Run that command; engine writes `current_player_ratings.csv` and
   `kipp_current_player_values.csv` to `data/processed/`.
4. (Monthly) refresh prospects — see `.claude/commands/refresh.md`.
5. Commit.

## Layout
- `inseason_ratings_engine.py` — core engine (config-driven; all tunables in `CONFIG`).
- `SYSTEM_SPEC.md` — full formula spec + data conventions. Source of truth.
- `data/prospects/prospect_ranks.csv` — durable; refresh ~monthly (committed).
- `data/raw/` — weekly Fantrax exports (gitignored, volatile).
- `data/processed/` — engine outputs (gitignored, regenerated each run).
- `docs/` — league rules PDF.
- `.claude/commands/` — the workflow steps (refresh, ratings, lineups, trades).

## Workflow steps
The old "5 chats" are now slash commands in `.claude/commands/`, run in order:
`/refresh` (produces the CSVs) → `/ratings` → `/lineups` → `/trades`.
