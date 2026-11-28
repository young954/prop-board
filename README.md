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

## Edge Finder model (Nov 17, 2026 upgrade)

- **Backtested calibration (NBA).** The projection is re-weighed by a logistic model fitted on 12,708 graded props
  from this season (Oct 20 - Nov 16): market price, projection gap, season and last-10 hit rate at the line, median vs line,
  minutes trend, home, points-type stat. Out of sample (trained to Nov 7, tested Nov 8-16) it beat the books' own no-vig
  price (Brier 0.2434 vs 0.2438) and is well calibrated. What it learned: Overs cash ~47% at real books, hot streaks are
  already priced in (lean Under), and the median game matters more than the average. Coefficients: `CAL` in index.html.
- **Line shopping.** Each pick uses the best price at the same line among DK/FD/MGM/CZR and lists every book.
- **Hit-rate strip** on every card: L5 / L10 / Season at the posted line, for the side picked.
- **Model record** above the cards: picks with EV +5% or more, graded on finished games using only box scores known before tip
  (live since Nov 17, plus an in-sample replay).
- **Honest prices.** Consensus-only lines (no book posted the price) sink to the bottom. Kalshi rows now use tradable prices
  (ask / 1 - bid) instead of the mid, and a Kalshi row is dropped when a sportsbook already lists that player and stat
  (names are matched without accents, e.g. Dončić = Doncic).
- Refit `CAL` every few weeks as more games are graded. NFL still uses the projection model without the backtest step.

### Not done yet / trade-offs
- Multi-book line shopping view (needs per-book prices in `props.json`).
- Filters for position (NBA), home/away, rest days and hit-rate window need those fields on the player objects.
- Compact sticky "locks strip" was skipped to keep the pinned header short.
- Service worker / lazy loading of season logs.

## Parlay Lab (Nov 28, 2026)

`parlay_lab.js` (Node, no packages) runs in the robot after the NBA/NFL updates. It reuses the Edge Finder model straight out of
`index.html`, so the parlays always match what users see.

- **Daily card**: locked once a day after 10 AM ET (or 3 h before the first game) once 12+ priced legs exist. Four 4-leg parlays:
  Steady (most likely legs, one per game), Sharp (every leg 57%+ and +EV), Same game (long shot, payout cut 20%),
  Mixed (2 NBA + 2 NFL on NFL days, otherwise 4 Unders). Never changed after it is locked.
- **Grading**: legs graded from box scores (NBA `games.json`, NFL `nfl_teams.json` logs). DNP = void, exact line = push. Mock $10 stake.
- **Learning**: every eligible leg of every card is logged to `archive/parlay_legs.json` and graded. Per league/side/stat group, the gap
  between how often legs cashed and what the model said is added to the next day's chances (shrunk by sample size, capped at 8 pts NBA / 10 NFL).
- **Backtest**: `node parlay_lab.js --replay` rebuilds every past NBA day and finished NFL week using only data known before each game.
  Nov 28 backtest: Steady 13-22 +49%, Sharp 9-26 +75%, Same game 7-32 -25%, Mixed 7-28 +8% (all 36-108, +25% on $10 stakes).
- **Site**: the Parlay Lab panel under the NBA/NFL tabs fetches `parlays.json` (~130 KB) only when opened.
