---
description: Contend/retool/rebuild posture + now/future strength
allowed-tools: Bash, Read
---
Run scripts/franchise_outlook.py against the current ratings. Show me my ACTUAL record,
future-rank, and the posture call in one or two sentences -- not a wall.

Present strength now comes from the real standings (data/standings/standings.csv via
scripts/standings.py), not roster inference -- the record is ground truth for who is
contending. Report my actual W-L / place / GB, not the roster proxy.

Caveats that still apply:
- FUTURE rank is still roster-derived (standings say nothing about future value).
- The roster now-proxy is biased UP for injury-heavy rosters (IL'd stars read at full
  rate) -- relevant only for the owners with no standings mapping.
- Owners whose franchise name isn't mapped (and any flagged PROVISIONAL) fall back to
  roster inference; say so rather than treating their window as known.
