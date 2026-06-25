---
description: Trade tooling — outbound finder, inbound inquiry eval, offer grading
allowed-tools: Bash, Read
---
Three modes of scripts/trade_finder.py. Read my request and pick the mode:

OUTBOUND (default — "find me trades", "who should I deal with"):
  python scripts/trade_finder.py outbound
  Scans the league for contenders whose holes our win-now surplus fills.

INQUIRY ("X asked about my guy", "is anyone on Y's team worth trading Z for"):
  python scripts/trade_finder.py inquiry --partner <owner> --send "<my player>"
  Sets the bar at our player's value to US, lists which of their players clear it,
  tags each as gettable (depth) vs core (won't move), and vets the headline 1-for-1.
  It is allowed to answer "nothing here clears the bar" — present that honestly,
  don't manufacture a target.

OFFER ("they offered me A for B", grade a concrete package):
  python scripts/trade_finder.py offer --partner <owner> --send "<my player(s)>" --get "<their player(s)>"
  Grades it by OUR posture (fair = a value gain for us), runs the gauntlet (cover,
  positional fit on what we receive, roster-drop flag, injuries), and shows what it
  looks like from THEIR side too.

Player names are partial-match (e.g. "Arozarena", "Basallo"); comma-separate multiples.
Posture defaults to our standings-derived rebuild; override with --posture if it's shifted.

When presenting results:
- Lead with the verdict the script computed; don't soften a DECLINE or invent a yes.
- The fair bar is OUR posture (dynasty-weighted in a rebuild). The "gettability" and
  "to THEM" lines are THEIR posture — use them to judge realism, not fairness to us.
- Surface the UNKNOWABLES the script flags (their true valuation, willingness) as mine
  to verify — never assert them solved.
- On an inquiry, the right counsel is almost always: let THEM open, and hold the bar.
- On a roster-drop flag, name the suggested cut as MY decision, not the script's.
- Confirm the received player's fit with our OBP/contact/SB scoring before any accept —
  the dynasty score is league-agnostic; our league isn't.
