---
description: List every Yardcocks GM command and the weekly pattern to run them in
---
Show this list verbatim:

```
YARDCOCKS & BEYOND — GM commands
================================

WEEKLY PATTERN  (in order — each step feeds the next)
  1. /refresh   New Fantrax exports -> fresh ratings + caches -> published to GitHub.
                Run on the LAPTOP/desktop: the MLB API is blocked from cloud VMs, so
                only an open-network machine can refresh recency/schedule/injuries.
  2. /posture   Sets the lens. Reads your ACTUAL record from the standings export.
                /waivers and /trades both price off this — run it before them.
  3. /lineups   Optimal 18-man lineup (multi-position matching, 12-start cap) PLUS a
                NEEDS report naming the holes: unfilled slots, thin roles, IL openings.
  4. /waivers   Fills the holes /lineups just named. Ranks adds by value NOW + FUTURE
                (not one-week streaming), flags breakouts and injury returns, and names
                the drop each add costs.
  5. /trades    Outbound finder / inbound inquiry / offer grading. Partner appetite
                comes from ACTUAL standings, so you court real buyers.
  6. /lineups   Re-run after adds and trades land, then lock the lineup.

AS NEEDED
  /sync       Pull the latest published ratings + caches. FIRST thing in any cloud or
              phone session — read-only, never writes.
  /ratings    Explain any player's score (follow the command with a name).
  /audit      q-tier mis-tier sanity check. Monthly, or when a score looks wrong.
  /log-trade  Record what a negotiation revealed about an owner (front-office memory;
              /trades surfaces this history automatically next time).
  /gm         Show this list.

WHO WRITES WHAT
  /refresh is the ONLY writer — one writer at a time, never two at once.
  Everything else reads what /refresh published. /sync is the reader's pull.

ON THE ROAD
  Phone/cloud: /sync, then any decision command.
  Refresh needs the laptop (MLB API is blocked from cloud VMs); a cloud /refresh still
  publishes fresh RATINGS but leaves schedule/injury caches stale.
```
