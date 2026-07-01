---
description: Record a trade negotiation to the front-office memory
allowed-tools: Bash
---
Log a negotiation so the next talk with this owner starts informed. Parse my
description into scripts/trade_log.py:

  python scripts/trade_log.py add --partner <owner> --sent "<players>" \
      --received "<players>" --outcome <opened|countered|accepted|declined|stalled> \
      --note "<the READ: what it revealed about them>"

Rules for a good entry:
- The --note is the load-bearing field, and it's MY read, not yours to invent. Capture
  what the negotiation revealed about the owner: what they want, what they value, what
  they refused to move, where their anchor sat. If I didn't say, ask me one short
  question rather than fabricating an interpretation.
- Map the outcome honestly: "opened" = they made first contact, "countered" = an offer
  went back and forth, "declined"/"stalled" = it died, "accepted" = it closed.
- After logging, remind me to commit it: it's real memory, not regenerated data, so it
  belongs in git. Prefer logging from desktop (the one writer); it's append-only so
  conflict risk is low.

To review history: python scripts/trade_log.py show [--partner <owner>]
The inquiry and offer trade modes already surface a partner's history automatically --
this command is only for WRITING new entries.
