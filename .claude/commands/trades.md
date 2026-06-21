---
description: Buy/sell trade board with realistic-value framing
allowed-tools: Bash, Read
---
Run scripts/shortlist.py against the current ratings (team Kipp, posture rebuild).

Show me ONLY the SELL and BUY lists, then add the trade-value judgment the raw lists
can't:
- Flag any SELL name the market is LOW on (BUY_LOW signal) or whose low score is
  injury-driven (SELL_HIGH on a hurt player) -- those are HOLDS, not sells.
- Reality-check return: aging vets with near-zero dynasty are low-return RENTALS and
  fetch mid prospects, not cornerstones. Name my single best trade chip (high win-now
  AND real residual dynasty) and which BUY targets it could realistically land.
- Note which owner holds the most of my BUY targets (likely trade partner).

Skip ADD/STASH (that's /waivers) and the lineup.
