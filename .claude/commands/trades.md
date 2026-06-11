Evaluate a trade or waiver decision. For waivers: read current_player_ratings.csv,
find the best available (owner_status = Free Agent) at the position I ask about,
and compare win_now_score / dynasty_score against my droppable bench pieces from
kipp_current_player_values.csv. For trades: compare the two sides on both
win_now_score and dynasty_score totals, note the win-now vs dynasty tradeoff, and
factor scarcity and age. Be direct about whether it's worth it; don't default to
"depends." FAAB 100, 7 claims/week, trade deadline Aug 12.

## News checks — required before every verdict

Web-search recent news for every player named in the trade or waiver decision before
delivering a verdict. Look for: injuries, IL moves, role changes, call-ups/demotions,
batting-order changes, return timelines. Surface findings as a `[NEWS: ...]` flag on
each player's line.

For trades especially: explicitly check whether the other side is acting on information.
A player being offered may be secretly hurt or demoted; a player being asked for may be
about to break out or return from injury. Check both directions.

If news materially conflicts with the engine score, say so plainly: state what the score
says, what the news says, and which to trust and why. Never silently adjust the score —
flag the conflict and let the owner decide.
