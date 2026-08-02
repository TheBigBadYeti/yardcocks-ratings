---
description: Re-pull live MLB data (injuries, minors status, schedule, recent form) without a full refresh
allowed-tools: Bash
---
Refresh the MLB-derived caches WITHOUT needing new Fantrax exports. Use this mid-week
when something changed in real life — a player got called up or optioned (minors
eligibility), landed on the IL, started a rehab, or the probable-starts posted — and you
want /lineups and /waivers current before tomorrow's automatic run.

The caches (recency, schedule, injuries, minors-eligibility) already refresh DAILY on
their own via the GitHub Action, so this is only for an on-demand nudge.

The MLB API is only reachable from GitHub's runners (a cloud VM 403s, a desktop is fine),
so the clean, works-from-anywhere path is to trigger the Action, which fetches and
commits straight to main — no PR, no exports:

1. Trigger it:  `gh workflow run refresh-caches.yml`
2. Tell me it's running and that it commits to `main` on its own in ~1 minute.
3. When it's done, run `/sync` to pull the fresh caches.

If `gh` can't dispatch it from this environment, say so and fall back:
- Desktop: run fetch_recency.py, fetch_schedule.py, fetch_injuries.py,
  fetch_minors_eligibility.py, then commit + push (this is a writer action).
- Otherwise: nothing to do — the daily Action will refresh everything by ~8am ET.

Do NOT run a full /refresh for this — that needs new Fantrax exports and regenerates the
whole ratings file. This is caches only.
