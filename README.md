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


## Board UX (P0 layer)

- **Hero first**: "Most appealing props" sits above the games. Secondary sections (DvP, injuries) start collapsed; the Show/Hide choice is remembered.
- **Freshness**: a bar at the top shows when the board, lines and injuries last updated, the sources (ESPN, Action Network, Kalshi) and any source warnings from `status.json` (`errors`). Data older than 90 minutes is flagged late/stale.
- **Loading**: skeleton cards replace "Loading…"; a section that never loads shows a reload prompt after 20 s.
- **Filters** (Best props toolbar): Favorites, 30+ min (NBA), DvP spot, Edge 5+ pts (drives the Prop Edge Finder minimum edge; default is 2+), position (NFL), sort by best prop / minutes / sample size, Clear, Copy link. Settings persist in `localStorage`.
- **Favorites**: tap the star on a Best-prop or Edge card. Saved by player name in `localStorage` (`pb-favs`). The table's own watchlist star is separate for now.
- **Trust**: sample size is shown on every card (e.g. 3/3); samples under 3 games are flagged "small sample". "How these are picked" explains the ranking, edge and DvP. Most head-to-head samples are only 2-4 games and are noisy.
- **Game cards** show up to three top edges from the Edge Finder model.
- **Phones (<768 px)**: player rows become cards and player detail opens as a bottom sheet (Close button, Esc, tap outside).
- **Deep links**: `?sport=nfl`, `?date=YYYY-MM-DD` (NBA), `?player=Name`, `?game=LAL-DEN`. The URL updates as you navigate.
- **Keyboard**: `/` focuses search, left/right arrows change day (NBA) or week (NFL).

No JSON contracts changed. The page reads the existing `status.json` `errors` list.

### Not done yet / trade-offs
- Multi-book line shopping view (needs per-book prices in `props.json`).
- Filters for position (NBA), home/away, rest days and hit-rate window need those fields on the player objects.
- Compact sticky "locks strip" was skipped to keep the pinned header short.
- Service worker / lazy loading of season logs.
