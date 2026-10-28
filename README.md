# Prop Board

NBA prop board that updates itself. A GitHub Actions robot runs `update.py`
every 30 minutes (10 AM to 2 AM Eastern), pulls ESPN scores, box scores,
odds, injuries, game logs and DraftKings props, saves them to `data/`, and
republishes the site.

- Site: `index.html` (reads `data/*.json`)
- Robot: `.github/workflows/update.yml`
- Run it by hand: Actions tab → Update Prop Board → Run workflow
- Last run's status and any errors: `data/status.json` (also shown at the top of the site)

The NFL tab shows the data it was set up with; only the NBA side auto-updates.
