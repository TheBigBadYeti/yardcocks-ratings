Refresh the data layer, then regenerate ratings.

1. Refresh prospect ranks (do this ~monthly, skip if done recently):
   - Fetch the live MLB Pipeline Top 100 from
     https://www.mlb.com/prospects/stats/top-prospects?type=all&minPA=0
     using markdown extraction with a high token limit (~25000) so the pitcher
     table tail isn't truncated. Parse both batter and pitcher tables; the union
     of the Rk column is the overall Top 100.
   - For org ranks, loop the team pages https://www.mlb.com/prospects/stats?teamId=<108..158>
     (Rk there = team Top-30 rank). Pull in batches.
   - Rebuild data/prospects/prospect_ranks.csv (name, overall_rank, org_rank, fv_grade).
   - Note: ranked pitchers with 0 IP won't appear in the stats table; leave their
     overall_rank blank and backfill manually only if a rostered minor needs it.

2. Drop this week's 8 Fantrax exports + Team-Roster export into data/raw/.

3. Run scripts/identify_exports.py and execute the run command it prints.

4. Confirm: ~10k players scored, Kipp roster = 40, prospect match count sane.
   Commit prospect_ranks.csv if it changed.
