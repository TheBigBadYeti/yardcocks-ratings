---
description: Record roster moves I made in Fantrax so /lineups and /waivers match my real roster
allowed-tools: Bash
---
After I make moves in Fantrax, I'll tell you in plain English what I did — e.g. "dropped
Gorman, added Durbin, IR'd Meyer, sent Sirota to minors." Record each one so the tools
optimize the roster I actually have, not last week's export.

Map my words to scripts/pending_moves.py:
- added / claimed / picked up  -> `add`
- dropped / cut / released      -> `drop`
- IR'd / to injured reserve     -> `ir`
- demoted / sent to minors      -> `drop` the outgoing prospect if one was cut; a
  demotion itself doesn't need recording unless it changes who's startable — ask me if
  unsure rather than guessing.

Run: `python scripts/pending_moves.py add|drop|ir "<player name>"` for each, using the
exact name as it appears in the ratings file.

Rules:
- Record ONLY what I confirm I actually did — never what was merely recommended.
- This overlay is temporary; the next /refresh clears it (fresh exports become reality).
- After recording, confirm the new pending state and note that /lineups now reflects it.
- On the phone/cloud this writes data/pending/moves.json; it applies to THIS session's
  /lineups and /waivers immediately. To persist it to other sessions it has to reach
  main — commit and (cloud) merge the PR, same as any write. Say so if it matters.
