#!/usr/bin/env python3
"""
health.py - the LINEUP-LAYER injury adjustment. Imported by optimize_lineup.py.

Joins the current IL snapshot (from fetch_injuries.py) onto the rated player pool by
MLBAM id (name only as last resort), marks genuinely-injured players so the optimizer
can drop them from this week's startable pool, and -- crucially -- does NOT overwrite
Fantrax status. Instead it surfaces the two DISAGREEMENTS that are the actionable
output:
  (A) MLB says IL, Fantrax still Active  -> SIT him (the lag this whole thing fixes)
  (B) Fantrax still Inj Res, MLB shows active -> maybe activate (flag, don't auto-start;
      the Fantrax IL slot is your roster decision, not ours to override)

Fail-safe: no IL file, or an unmatched player -> fall back to Fantrax status and warn.
A silent false-bench is worse than the lag, because you never see why you lost points.
"""
import sys
from fetch_injuries import read_il, norm_name


def apply_health(df, id_col=None, verbose=True):
    """Adds boolean column 'health_excluded'. id_col = the ratings column holding the
    MLBAM id, if present (preferred join). Returns df unchanged in scoring."""
    by_id, by_name, ok = read_il()
    if not ok:
        if verbose:
            print("[health] no IL snapshot found -- using Fantrax status only. "
                  "Run fetch_injuries.py in /refresh to enable IL lag correction.",
                  file=sys.stderr)
        df["health_excluded"] = False
        return df

    def matched_il(row):
        if id_col and str(row.get(id_col, "")) in by_id:
            return True
        # name fallback ONLY when we have no id to join on
        if not (id_col and str(row.get(id_col, ""))):
            return norm_name(row.get("player", "")) in by_name
        return False

    df = df.copy()
    df["_api_il"] = df.apply(matched_il, axis=1)
    df["health_excluded"] = df["_api_il"]

    if verbose:
        _report_conflicts(df)
    return df.drop(columns=["_api_il"], errors="ignore")


def _is_fantrax_il(s):
    return str(s).strip().lower() in {"inj res", "il", "injured reserve", "injured list"}


def _report_conflicts(df):
    rs = df.get("roster_status", "")
    fantrax_il = df["roster_status"].apply(_is_fantrax_il) if "roster_status" in df else False

    # (A) the lag we fix: MLB IL but Fantrax hasn't moved him
    a = df[df["_api_il"] & ~fantrax_il]
    # (B) reverse: Fantrax IL but MLB shows active -- candidate to re-activate
    b = df[~df["_api_il"] & fantrax_il]

    if len(a):
        print("\n[health] MLB IL but Fantrax still active -- SIT these (or your "
              "optimizer will start an injured player):")
        for _, r in a.iterrows():
            print(f"    - {r.get('player','?')} ({r.get('roster_status','?')} on Fantrax)")
    if len(b):
        print("\n[health] Fantrax still has these on IL, but MLB shows them ACTIVE -- "
              "check if you can activate (flag only; not auto-started):")
        for _, r in b.iterrows():
            print(f"    - {r.get('player','?')}")
    if not len(a) and not len(b):
        print("[health] Fantrax and MLB IL agree -- no health conflicts this run.")
