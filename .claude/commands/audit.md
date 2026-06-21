---
description: q-tier mis-tier sanity check (occasional)
allowed-tools: Bash, Read
argument-hint: [optional "Name One" "Name Two" to spotlight]
---
Run scripts/audit_qtier.py --career data/career/career_stats.csv $ARGUMENTS

Show the hitting drag + slipped tables and any watchlist names. Distinguish REAL
decline (big drag from FULL recent seasons -- leave it) from ARTIFACTS (big drag from
a SHORT recent partial -- under-tiered). Flag only names that look genuinely
mis-tiered, with the season detail as evidence.
