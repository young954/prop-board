# Prop Board

NBA prop board that updates itself. A GitHub Actions robot runs `update.py` and `nfl_update.py`
every 30 minutes (10 AM to 2 AM Eastern), pulls ESPN scores, box scores,
odds, injuries and game logs, plus player props from Action Network (DraftKings, FanDuel, BetMGM, Caesars, then its consensus line; code in `anprops.py`) with Kalshi (`kalshi.py`) filling any gaps, saves them as the .json files in this repo, and
republishes the site.

- Site: `index.html` (reads the .json files)
- Robot: `.github/workflows/update.yml`
- Run it by hand: Actions tab → Update Prop Board → Run workflow
- Last run's status and any errors: `status.json` (also shown at the top of the site)

The NFL side (`nfl_update.py`) runs right after: weekly box scores into player logs, this week's
slate, lines, injuries, Action Network and Kalshi props, head-to-head vs this week's opponent and defense vs position.
