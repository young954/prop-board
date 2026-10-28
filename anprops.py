#!/usr/bin/env python3
"""Player props from Action Network's public odds API (no key needed). Standard library only.

One call per league returns every posted prop market for the day (NBA) or the week (NFL) from
several books at once. For each player and stat we take the first book that has a full
over/under pair, in this order: DraftKings, FanDuel, BetMGM, Caesars, then Action Network's
own consensus line. The "Open" book gives the opening line so the board can show how it moved.
Games that already started are skipped (their last pre-game line stays on the board).
"""
import urllib.parse

BASE = "https://api.actionnetwork.com/web/v2/scoreboard/{lg}/markets?{q}"
BOOKS = [(68, "DraftKings"), (69, "FanDuel"), (75, "BetMGM"), (123, "Caesars"), (15, "Action Network consensus")]
OPEN = 30  # Action Network's "Open" book: the opening line
HEADERS = {"Origin": "https://www.actionnetwork.com", "Referer": "https://www.actionnetwork.com/"}

TYPES = {
    "nba": {"core_bet_type_27_points": "pts", "core_bet_type_23_rebounds": "reb", "core_bet_type_26_assists": "ast",
            "core_bet_type_21_3fgm": "tp", "core_bet_type_86_points_rebounds": "pr", "core_bet_type_87_points_assists": "pa",
            "core_bet_type_85_points_rebounds_assists": "pra"},
    "nfl": {"core_bet_type_9_passing_yards": "pyd", "core_bet_type_10_pass_completions": "cmp",
            "core_bet_type_11_passing_tds": "ptd", "core_bet_type_12_rushing_yards": "ryd",
            "core_bet_type_18_rushing_attempts": "car", "core_bet_type_16_receiving_yards": "recyd",
            "core_bet_type_15_receptions": "rec", "core_bet_type_62_anytime_touchdown_scorer": "td"},
}
# Action Network team abbreviations -> the ones the board uses
TEAM_FIX = {"nba": {"SA": "SAS", "NO": "NOP", "GS": "GSW", "WSH": "WAS", "NY": "NYK", "UTAH": "UTA"},
            "nfl": {"JAC": "JAX", "WSH": "WAS", "LAR": "LA"}}


def url_for(lg, query):
    ids = [b for b, _ in BOOKS] + [OPEN]
    q = {"bookIds": ",".join(str(i) for i in ids), "customPickTypes": ",".join(TYPES[lg])}
    q.update(query)
    return BASE.format(lg=lg, q=urllib.parse.urlencode(q, safe=","))


def pull(lg, query, get):
    """Returns ({(away, home): {(team, name, stat): row}}, {book label: row count}).

    Each row is [team, name, stat, line, over odds, under odds, book, open line, open over, open under];
    the three "open" cells are None when the opening line isn't available.
    `get(url, headers=...)` fetches and parses JSON (raises on failure)."""
    j = get(url_for(lg, query), headers=HEADERS)
    fix, types = TEAM_FIX[lg], TYPES[lg]
    ab = lambda t: fix.get(t.get("abbr"), t.get("abbr"))
    ev, teams = {}, {}
    for g in j.get("games") or []:
        if g.get("status") != "scheduled":
            continue  # started or finished: books pull or change these lines
        a, h = g["away_team"], g["home_team"]
        ev[g["id"]] = (ab(a), ab(h))
        teams[a["id"]] = ab(a)
        teams[h["id"]] = ab(h)
    players = {p["id"]: (p.get("full_name"), p.get("team_id")) for p in j.get("players") or []}

    got = {}  # (event, player, stat) -> {book id: {"over": (line, odds), "under": (line, odds), "yes": odds}}
    for book, m in (j.get("markets") or {}).items():
        try:
            b = int(book)
        except ValueError:
            continue
        for typ, outs in ((m or {}).get("event") or {}).items():
            stat = types.get(typ)
            if not stat:
                continue
            for o in outs or []:
                if o.get("event_id") not in ev or o.get("is_live") or o.get("is_alt_market"):
                    continue
                pid, odds = o.get("player_id"), o.get("odds")
                if not pid or not odds:
                    continue
                d = got.setdefault((o["event_id"], pid, stat), {}).setdefault(b, {})
                side = o.get("side")
                if side in ("over", "under"):
                    d.setdefault(side, (o.get("value"), odds))
                elif side == "noside" and stat == "td":
                    d.setdefault("yes", odds)

    rows, used = {}, {}
    for (eid, pid, stat), by in got.items():
        name, tid = players.get(pid, (None, None))
        away, home = ev[eid]
        team = teams.get(tid)
        if not name or team not in (away, home):
            continue
        pick = None
        for b, label in BOOKS:
            d = by.get(b)
            if not d:
                continue
            if stat == "td":
                if "yes" in d:
                    pick = (label, 0.5, d["yes"], None)
                    break
            elif "over" in d and "under" in d and d["over"][0] == d["under"][0]:
                pick = (label, d["over"][0], d["over"][1], d["under"][1])
                break
        if not pick:
            continue
        label, line, oo, uo = pick
        op = by.get(OPEN) or {}
        first = [None, None, None]
        if stat == "td":
            if "yes" in op:
                first = [0.5, op["yes"], None]
        elif "over" in op and "under" in op and op["over"][0] == op["under"][0]:
            first = [op["over"][0], op["over"][1], op["under"][1]]
        rows.setdefault((away, home), {})[(team, name, stat)] = [team, name, stat, line, oo, uo, label] + first
        used[label] = used.get(label, 0) + 1
    return rows, used
