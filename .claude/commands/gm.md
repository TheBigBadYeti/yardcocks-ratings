---
description: List every Yardcocks GM command and what it's for
---
Show this list verbatim:

```
YARDCOCKS & BEYOND — GM commands
================================

DATA · writer (needs git push access; ONE writer at a time)
  /refresh    Ingest new Fantrax exports -> regenerate ratings -> publish to GitHub.
              Run-from-anywhere. Supersedes the old /load + /publish. Run FIRST when
              you have new exports — attach them to the session, or upload them into
              data/raw via the GitHub web UI, then run this.

DATA · reader (read-only, never writes)
  /sync       Pull the latest published ratings from GitHub (reset to origin/main).
              Run this in a cloud or phone session before asking anything.

DECISIONS · read the published ratings
  /lineups    Optimal 18-man lineup for the week under the 12-start cap (EWP optimizer).
  /trades     Trade tooling — outbound finder, inbound inquiry eval, offer grading.
  /waivers    Free-agent adds that help now + dynasty stashes + breakout watch.
  /posture    Contend/retool/rebuild read + now-vs-future strength.
  /ratings    Explain any player's score (follow the command with a name).
  /audit      q-tier mis-tier sanity check (occasional).

MEMORY
  /log-trade  Record what a negotiation revealed about an owner (front-office memory).

  /gm         Show this list.

Typical week:  supply exports -> /refresh -> /lineups -> /trades -> /waivers
On the road :  /sync to read, or /refresh if you have new exports + push access
```
