# Yardcocks & Beyond — League Rules (2026)

Authoritative rules summary from Fantrax (League ID `nlvnbyxamlg1fjiz`, commissioner
`kyfaessler` / Former Players II). Committed as reference so every session reasons from
the real rules, not inference. Source of truth for roster/scoring/eligibility mechanics;
`SYSTEM_SPEC.md` remains source of truth for the ratings *engine*.

## Format
- **Dynasty, Head-to-Head Points**, 14 teams (16 max), Fantrax.
- Season **Mar 25 – Sep 27, 2026**. First 2 scoring periods merged.
- **Playoffs: top 4 teams**, start Scoring Period 22 (**Aug 31**), 4 rounds, reseeded.
- **Trade deadline: Aug 12, 2026** (11:59 PM EDT). Trading all year until then; picks
  tradeable; no trade vote.
- Standings tiebreak: (1) most fantasy points, (2) H2H vs tied teams, (3) random.

## Roster (Max 40 total)
| Bucket | Max | Counts toward roster limit? |
|---|---|---|
| Active | 18 | yes |
| Reserve (bench) | 8 | yes |
| Injured Reserve | 4 | **No** |
| Minors | 10 | **No** |

- **Active + Reserve = 26 MLB-roster spots** — this is the pool an MLB add consumes.
  IR (4) and Minors (10) are separate buckets with their own caps; 26+4+10 = 40.
- "Prevent any transaction that would make a roster illegal: Always" — Fantrax blocks
  over-cap moves, so an add when full requires a drop/move first.
- **Only players on the MLB Injured List may go to IR.** Suspended / bye-week players
  cannot. IR is enforcement type None but the MLB-IL gate is real.
- Active positional maxes: C1, 1B1, 2B1, 3B1, SS1, OF3, UT1, SP6, RP3 = 18.

## Minor League Eligibility  ← the rule we needed
- **Minors slot eligibility type: "Simple — only real Minor League players allowed in
  Minors roster slots."** This is Fantrax's own "is this currently a real minor leaguer"
  determination (prospect / not yet graduated), NOT a custom AB/IP formula in the league
  settings. So the authoritative answer is Fantrax's flag; the best automatable proxy is
  MLB rookie-eligibility (has NOT exceeded ~130 AB / 50 IP / 45 days service).
- Minors enforcement: makes roster illegal (0 periods grace). Moving OUT of minors is
  never prevented.

## Lineups & pitching cap
- **Lineups lock weekly, every Monday** (0:00 before first game). Set once for the week.
- **Games Started cap: 12 per scoring period.** IMPORTANT: exceeding a pitching max
  makes **ALL pitchers (SP *and* RP) stop accumulating** for the rest of the period —
  so blowing past 12 starts is costly, not just wasted. Prorated by period length.

## Position eligibility (drives lineup slots; Fantrax computes it into the export)
- Hitter at a position: **40 games last season OR 16 this season**.
- SP: **5 starts last season OR 3 this season**. RP: **8 relief app last OR 5 this**.
- Fantrax default positions are NOT added on top; fallback is most-played position last
  season. (So the `position` column in exports already reflects these thresholds.)

## Transactions
- **Claims: max 7 per week** (Mon reset), unlimited per season. FAAB **$100**, min bid
  $0, $1 increments, earliest-bid tiebreak. FA bids process daily 3:00 AM EDT.
- Waivers: 2-day period, bidding, churn prevention ON.
- All fees $0 (entry $100). Can't-drop list: Fantrax default.

## Scoring (matches SYSTEM_SPEC §, confirmed)
Hitting: 1B +1, 2B +2, 3B +3, HR +4, R +1, RBI +1, BB +1, SB +2, HBP +1, CS −1,
GIDP −1, SO −0.5.
Pitching: IP **+3**, W +4, QS +3, SV +5, HLD +3, K +1, ER −3, H −1, BB −1, HB −1.
(IP at +3/inning dominates pitcher value — bulk innings are gold.)

## Strategic reads that fall out of these rules
- **Kipp is 3-12, 14th of 14.** Playoffs are top 4; realistically eliminated. Full
  rebuild is correct, and the **Aug 12 deadline** is the window to convert win-now vets
  into youth/picks before it closes.
- Picks ARE tradeable (28 rounds, 0 future years) — another sell-side chip.
- The 12-start cap punishing ALL pitching means lineup start-count discipline matters.
