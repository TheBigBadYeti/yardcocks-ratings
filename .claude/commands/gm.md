---
description: List every Yardcocks GM command and the weekly pattern to run them in
---
Show this list verbatim:

```
YARDCOCKS & BEYOND — GM commands
================================

WEEKLY PATTERN  (in order — each step feeds the next)
  1. /refresh   New Fantrax exports -> fresh ratings + caches -> published to GitHub.
                SIX files in TWO drops (cloud caps uploads at 5):
                  drop 1 = the 5 engine inputs (rostered H/P, FA H/P, Team-Roster)
                  drop 2 = Fantrax-Standings (drives /posture + trade appetite)
                Runs anywhere -- cloud, phone, or desktop. The MLB caches
                (recency/schedule/injuries) are refreshed DAILY by a GitHub Action
                (.github/workflows/refresh-caches.yml), so they're current no matter
                where you refresh from. A cloud VM still can't fetch them itself (its
                egress allowlist blocks general internet, not MLB) -- it doesn't need to.
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
  /recheck    Re-pull live MLB data (injuries, minors status, schedule, recent form)
              mid-week without a full refresh. (They also auto-refresh daily.)
  /moves      Record roster moves I made in Fantrax so /lineups + /waivers match my
              real roster before the next /refresh. Tell it in plain English.
  /ratings    Explain any player's score (follow the command with a name).
  /audit      q-tier mis-tier sanity check. Monthly, or when a score looks wrong.
  /log-trade  Record what a negotiation revealed about an owner (front-office memory;
              /trades surfaces this history automatically next time).
  /gm         Show this list.

You only ever type a /command — never python or gh; the command runs those for you.
All state lives in git, so a cloud/phone /sync sees exactly what the desktop does.

WHO WRITES WHAT
  Writers: /refresh, /moves, /log-trade, /recheck. One writer at a time, never two.
  Everything else reads what was published. /sync is the reader's pull.

ON THE ROAD
  Phone/cloud: /sync, then any decision command.
  /refresh works from the cloud too -- a daily GitHub Action keeps the MLB caches fresh,
  so cloud and desktop read identical data. ONE CATCH: a cloud session can only push to
  its own branch (the git proxy enforces this -- you cannot tell it to push to main), so
  a cloud /refresh is NOT live until you MERGE ITS PR. Desktop pushes straight to main
  and needs no PR.
```
