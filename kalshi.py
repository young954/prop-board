#!/usr/bin/env python3
"""Second props source: Kalshi's public market API (no key). Standard library only.

Kalshi lists each player stat as a ladder of "N+" yes/no markets. We turn each ladder into one
over/under line: the rung whose yes price is closest to 50% becomes the line, and the yes/no
prices become over/under odds (American). Rows use the same 10-cell format as anprops.py, with
book = "Kalshi". Team props: full-game totals (KXNBATOTAL) come back as `totals`.
"""
import re

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={s}&status=open&limit=1000"
SERIES = {
    "nba": {"KXNBAPTS": "pts", "KXNBAREB": "reb", "KXNBAAST": "ast", "KXNBA3PT": "tp"},
    "nfl": {"KXNFLRSHYDS": "ryd", "KXNFLRECYDS": "recyd", "KXNFLREC": "rec"},
}
TOTAL = {"nba": "KXNBATOTAL"}
TEAM_FIX = {"nba": {"NOP": "NOP"}, "nfl": {"LAR": "LA", "JAC": "JAX"}}
EV = re.compile(r"^[A-Z0-9]+-\d{2}[A-Z]{3}\d{2}([A-Z]{4,8})$")


def american(p):
    p = min(max(p, 0.02), 0.98)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def _pages(get, series, limit_pages=5):
    cur, out = "", []
    for _ in range(limit_pages):
        j = get(BASE.format(s=series) + ("&cursor=" + cur if cur else ""))
        out += j.get("markets") or []
        cur = j.get("cursor") or ""
        if not cur:
            break
    return out


def _mid(m):
    try:
        b, a = float(m["yes_bid_dollars"]), float(m["yes_ask_dollars"])
    except (KeyError, ValueError, TypeError):
        return None
    if a <= 0 or b >= 1 or a < b or a - b > 0.15:
        return None  # no real two-sided market on this rung
    return (a + b) / 2


def _teams(lg, event_ticker):
    m = EV.match(event_ticker)
    if not m or len(m.group(1)) % 2:
        return None
    s = m.group(1)
    h = len(s) // 2
    fix = TEAM_FIX.get(lg, {})
    return fix.get(s[:h], s[:h]), fix.get(s[h:], s[h:])


def pull(lg, get):
    """Returns ({(away, home): {(team, name, stat): row}}, {(away, home): game total or None}, errors)."""
    ladders, errors = {}, []
    for series, stat in SERIES[lg].items():
        try:
            for m in _pages(get, series):
                if m.get("status") not in ("active", "open"):
                    continue
                g = _teams(lg, m.get("event_ticker", ""))
                p = _mid(m)
                name = (m.get("yes_sub_title") or "").split(":")[0].strip()
                strike = m.get("floor_strike")
                if not g or p is None or not name or strike is None:
                    continue
                seg = m["ticker"].split("-")[2] if m["ticker"].count("-") >= 3 else ""
                team = next((t for t in g if seg.startswith(t)), None)
                if not team:
                    continue
                ladders.setdefault((g, team, name, stat), []).append((strike, p))
        except Exception as e:  # one series failing shouldn't lose the others
            errors.append("Kalshi %s: %s" % (series, e))
    rows = {}
    for (g, team, name, stat), rungs in ladders.items():
        strike, p = min(rungs, key=lambda r: abs(r[1] - 0.5))
        if not 0.2 <= p <= 0.8:
            continue
        rows.setdefault(g, {})[(team, name, stat)] = [team, name, stat, strike, american(p), american(1 - p),
                                                       "Kalshi", None, None, None]
    totals = {}
    if lg in TOTAL:
        try:
            lad = {}
            for m in _pages(get, TOTAL[lg], 2):
                g = _teams(lg, m.get("event_ticker", ""))
                p = _mid(m)
                if g and p is not None and m.get("floor_strike") is not None:
                    lad.setdefault(g, []).append((m["floor_strike"], p))
            for g, rungs in lad.items():
                totals[g] = min(rungs, key=lambda r: abs(r[1] - 0.5))[0]
        except Exception as e:
            errors.append("Kalshi totals: %s" % e)
    return rows, totals, errors


def merge(lg, by_game, get):
    """Add Kalshi rows for any (team, player, stat) the primary source lacks.
    Returns (by_game, number added, game totals, errors)."""
    rows, totals, errors = pull(lg, get)
    added = 0
    for g, d in rows.items():
        cur = by_game.setdefault(g, {})
        for k, r in d.items():
            if k not in cur:
                cur[k] = r
                added += 1
    return by_game, added, totals, errors
