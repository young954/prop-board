#!/usr/bin/env python3
"""Prop Board updater. Runs on a timer (GitHub Actions) and keeps data/*.json current.

Sources: ESPN public JSON (scores, box scores, odds via DraftKings, injuries, rosters,
game logs) and DraftKings player props. Only writes what the feeds return.
Python 3.9+ standard library only.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA = os.environ.get("PB_DATA") or os.path.dirname(os.path.abspath(__file__))  # data files sit next to this script
FIXTURES = os.environ.get("PB_FIXTURES")  # testing only: folders of saved responses
MAP = {"SA": "SAS", "NO": "NOP", "GS": "GSW", "WSH": "WAS", "NY": "NYK", "UTAH": "UTA"}
ESPN_ABBR = {"SAS": "sa", "NOP": "no", "GSW": "gs", "WAS": "wsh", "NYK": "ny", "UTA": "utah"}
ALL_TEAMS = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM",
             "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]
SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
DK = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/42648/categories/{}/subcategories/{}"
DK_SUBS = [(1215, 12488, "pts"), (1216, 12492, "reb"), (1217, 12495, "ast"), (1218, 12497, "tp"),
           (583, 9976, "pr"), (583, 9973, "pa"), (583, 5001, "pra")]
STAT_ORDER = ["pts", "reb", "ast", "tp", "pr", "pa", "pra"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

errors, notes = [], []
m = lambda a: MAP.get(a, a)


def now_et():
    o = os.environ.get("PB_NOW")
    return dt.datetime.fromisoformat(o).astimezone(ET) if o else dt.datetime.now(ET)


NOW = now_et()
NOW_UTC = NOW.astimezone(dt.timezone.utc).replace(microsecond=0)
NOWISO = NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = NOW.strftime("%Y-%m-%d")
STAMP = NOW.strftime("%b ") + str(NOW.day) + ", " + NOW.strftime("%I:%M %p").lstrip("0") + " ET"


# ---------------------------------------------------------------- fetching
def _fixture(url):
    name = re.sub(r"[^A-Za-z0-9]+", "_", url)[-120:] + ".json"
    for d in FIXTURES.split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return json.load(open(p))
    raise IOError("no fixture for " + url)


def get(url, tries=2):
    if FIXTURES:
        return _fixture(url)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + i * 3)
    raise last


def soft(url, what):
    try:
        return get(url)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{what} didn't load: {type(e).__name__} {str(e)[:80]}")
        return None


# ---------------------------------------------------------------- data files
def load(col):
    p = os.path.join(DATA, col + ".json")
    return json.load(open(p)) if os.path.exists(p) else {}


def save(col, d):
    p = os.path.join(DATA, col + ".json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, p)


# ---------------------------------------------------------------- helpers
def nk(n):
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z ]", "", n)
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def et_date(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")


def iso_z(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ival(x):
    try:
        return int(str(x).replace("−", "-").replace("+", ""))
    except (TypeError, ValueError):
        return None


def fval(x):
    try:
        return float(str(x).lstrip("ou"))
    except (TypeError, ValueError):
        return None


def dig(d, *ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def game_id(ev):
    c = ev["competitions"][0]
    t = {x["homeAway"]: x for x in c["competitors"]}
    a, h = m(t["away"]["team"]["abbreviation"]), m(t["home"]["team"]["abbreviation"])
    return f"{et_date(ev['date'])}-{a}-{h}", a, h, t


def odds(summary):
    pc = (summary.get("pickcenter") or [None])[0]
    if not pc:
        return None
    ml, ps, to = pc.get("moneyline") or {}, pc.get("pointSpread") or {}, pc.get("total") or {}
    mlA = ival(dig(ml, "away", "close", "odds")) if dig(ml, "away", "close", "odds") else dig(pc, "awayTeamOdds", "moneyLine")
    mlH = ival(dig(ml, "home", "close", "odds")) if dig(ml, "home", "close", "odds") else dig(pc, "homeTeamOdds", "moneyLine")
    sh = fval(dig(ps, "home", "close", "line")) if dig(ps, "home", "close", "line") else pc.get("spread")
    return {"mlA": mlA, "mlH": mlH, "ou": pc.get("overUnder"), "sh": sh,
            "shO": fval(dig(ps, "home", "open", "line")), "totO": fval(dig(to, "over", "open", "line"))}


KEYMAP = {"minutes": "min", "points": "pts", "rebounds": "reb", "assists": "ast", "steals": "stl",
          "blocks": "blk", "turnovers": "tov", "fouls": "pf"}
PAIRS = {"fieldGoalsMade-fieldGoalsAttempted": ("fg", "fga"),
         "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("tp", "tpa"),
         "freeThrowsMade-freeThrowsAttempted": ("ft", "fta")}


def box(summary, away, home):
    players, dnp, inact = [], [], {away: [], home: []}
    for bp in dig(summary, "boxscore", "players") or []:
        t = m(bp["team"]["abbreviation"])
        st = (bp.get("statistics") or [{}])[0]
        keys = st.get("keys") or []
        for a in st.get("athletes") or []:
            n = a["athlete"]["displayName"]
            if a.get("stats"):
                r = {"n": n, "t": t}
                for k, v in zip(keys, a["stats"]):
                    if k in KEYMAP:
                        try:
                            x = float(v) if k == "minutes" else int(v)
                        except (TypeError, ValueError):
                            x = 0
                        if k == "minutes" and x == int(x):
                            x = int(x)
                        r[KEYMAP[k]] = x
                    elif k in PAIRS:
                        p = (str(v).split("-") + ["0"])[:2]
                        r[PAIRS[k][0]], r[PAIRS[k][1]] = ival(p[0]) or 0, ival(p[1]) or 0
                players.append(r)
            elif "COACH" in (a.get("reason") or "").upper():
                dnp.append({"n": n, "r": "Coach's Decision", "t": t})
            else:
                inact.setdefault(t, []).append(n)
    seen = {p["n"] for p in players} | {x["n"] for x in dnp}
    for ti in summary.get("injuries") or []:
        t = m(ti["team"]["abbreviation"])
        for i in ti.get("injuries") or []:
            n = i["athlete"]["displayName"]
            if n not in seen and n not in inact.setdefault(t, []):
                inact[t].append(n)
    return players, dnp, inact


def mdy(ds):
    x = dt.date.fromisoformat(ds[:10])
    return x.strftime("%b ") + str(x.day) + (x.strftime(" '%y") if x.year > NOW.year else "")


ORDER = {"Out": 0, "Doubtful": 1, "Questionable": 2, "Day-to-day": 3, "Probable": 4}


def injury_rows(summary, away):
    rows = []
    teams = sorted(summary.get("injuries") or [], key=lambda x: 0 if m(x["team"]["abbreviation"]) == away else 1)
    for ti in teams:
        t, tr = m(ti["team"]["abbreviation"]), []
        for inj in ti.get("injuries") or []:
            det = inj.get("details") or {}
            typ = det.get("type") or ""
            dl = det.get("detail")
            if dl and dl != "Not Specified":
                typ += f" ({dl})"
            stt = inj.get("status") or ""
            if stt.lower() == "day-to-day":
                stt = "Day-to-day"
            rd = det.get("returnDate")
            if rd and rd[:10] <= TODAY:
                note = "Out tonight" if stt == "Out" else "Game-time call"
            elif rd:
                note = "Back ~" + mdy(rd)
            else:
                note = "Out tonight" if stt == "Out" else "Game-time call"
            pos = (inj["athlete"].get("position") or {}).get("abbreviation", "")
            tr.append([t, inj["athlete"]["displayName"], pos, typ, stt, note])
        rows += sorted(tr, key=lambda r: ORDER.get(r[4], 5))
    return rows


# ---------------------------------------------------------------- steps
def step_games_and_slate(games, slate, market, injuries):
    """Box scores for finished games (with catch-up), tonight's slate, lines and injuries."""
    last = max([g["date"] for g in games.values()] or [TODAY])
    start = dt.date.fromisoformat(last)
    lo = dt.date.fromisoformat(TODAY) - dt.timedelta(days=7)
    day, dates = max(start, lo), []
    while day <= dt.date.fromisoformat(TODAY):
        dates.append(day.strftime("%Y%m%d"))
        day += dt.timedelta(days=1)
    added, tonight = 0, []
    for ymd in dates:
        sb = soft(SB + "scoreboard?dates=" + ymd, f"Scoreboard {ymd}")
        if not sb:
            continue
        for ev in sb.get("events") or []:
            gid, a, h, t = game_id(ev)
            d = gid[:10]
            state = dig(ev, "status", "type", "state")
            is_today = d == TODAY
            yday = (dt.date.fromisoformat(TODAY) - dt.timedelta(days=1)).isoformat()
            need_box = state == "post" and (gid not in games or (d >= yday and not any(games[gid].get("inactive", {}).values())))
            if not (is_today or need_box):
                continue
            s = soft(SB + "summary?event=" + ev["id"], f"Game {gid}")
            if not s:
                continue
            o = odds(s)
            sl = {"away": a, "awayName": t["away"]["team"].get("shortDisplayName", ""), "home": h,
                  "homeName": t["home"]["team"].get("shortDisplayName", ""), "start": iso_z(ev["date"]), "src": "am"}
            old = slate.get(gid, {})
            for k in ("mlA", "mlH", "ou"):
                if o and o.get(k) is not None:
                    sl[k] = o[k]
                elif k in old:
                    sl[k] = old[k]
            if state == "post":
                sl.update(status="final", **{"as": int(t["away"]["score"]), "hs": int(t["home"]["score"])})
            elif state == "in":
                sl.update(status="live", clock=dig(ev, "status", "type", "shortDetail") or "",
                          **{"as": int(t["away"].get("score") or 0), "hs": int(t["home"].get("score") or 0)})
            else:
                sl["status"] = "scheduled"
            if not is_today and old:  # past game: keep its morning odds/source, only finish it
                keep = dict(old)
                keep.update({k: sl[k] for k in ("status", "as", "hs") if k in sl})
                keep.pop("clock", None)
                sl = keep
            slate[gid] = sl
            if need_box:
                pl, dn, ina = box(s, a, h)
                ok = True
                for tm, sc in ((a, sl.get("as")), (h, sl.get("hs"))):
                    tot = sum(p.get("pts", 0) for p in pl if p["t"] == tm)
                    if tot != sc:
                        ok = False
                        errors.append(f"Box score {gid} {tm}: players add to {tot}, final is {sc}")
                if pl and (ok or gid not in games):
                    if gid not in games:
                        added += 1
                    games[gid] = {"as": sl["as"], "hs": sl["hs"], "away": a, "home": h, "date": d,
                                  "players": pl, "dnp": dn, "inactive": ina}
            if is_today:
                tonight.append(gid)
                if o:
                    prev = market.get(gid) or {}
                    shO = prev.get("shO", o["shO"]) if prev else o["shO"]
                    totO = prev.get("totO", o["totO"]) if prev else o["totO"]
                    keep = prev and prev.get("shO") == shO and prev.get("totO") == totO
                    market[gid] = {"asof": NOWISO, "lg": "nba", "mlA": o["mlA"], "mlH": o["mlH"], "sh": o["sh"],
                                   "shO": shO, "tot": o["ou"], "totO": totO,
                                   "notes": prev.get("notes", []) if keep else [],
                                   "splits": prev.get("splits", []) if keep else [],
                                   "src": f"DraftKings lines via ESPN ({STAMP})", "wpH": None}
                injuries[gid] = {"asof": NOWISO, "lg": "nba", "src": f"ESPN NBA injury report ({STAMP})",
                                 "rows": injury_rows(s, a)}
    if added:
        notes.append(f"{added} box scores added")
    return tonight


def step_props(props, tonight):
    rows_by = {}
    got_any = False
    for cat, sub, stat in DK_SUBS:
        d = soft(DK.format(cat, sub), f"DraftKings {stat} props")
        if not d:
            continue
        got_any = True
        ev = {}
        for e in d.get("events") or []:
            ps = {p.get("venueRole"): m(dig(p, "metadata", "shortName") or "") for p in e.get("participants") or []}
            if ps.get("Away") and ps.get("Home"):
                ev[str(e["id"])] = ps
        mk = {str(x["id"]): x for x in d.get("markets") or []}
        by = {}
        for s in d.get("selections") or []:
            by.setdefault(str(s.get("marketId")), []).append(s)
        for mid, sels in by.items():
            mm = mk.get(mid)
            if not mm or mm.get("subcategoryId") != sub:
                continue
            ps = ev.get(str(mm.get("eventId")))
            if not ps:
                continue
            gid = f"{TODAY}-{ps['Away']}-{ps['Home']}"
            if gid not in tonight:
                continue
            ov = [x for x in sels if x.get("label") == "Over"]
            un = [x for x in sels if x.get("label") == "Under"]
            if not ov or not un:
                continue
            o, u = ov[0], un[0]
            p = (o.get("participants") or [{}])[0]
            team = ps["Home"] if p.get("venueRole") == "HomePlayer" else ps["Away"]
            oo, uo = ival(dig(o, "displayOdds", "american")), ival(dig(u, "displayOdds", "american"))
            key = (team, p.get("name"), stat)
            rows_by.setdefault(gid, {}).setdefault(key, [team, p.get("name"), stat, o.get("points"), oo, uo, "DraftKings"])
    if not got_any:
        return 0
    total = 0
    for gid in tonight:
        old = props.get(gid) or {}
        old_rows = {(r[0], r[1], r[2]): r for r in old.get("rows") or []}
        new = rows_by.get(gid, {})
        out = []
        for key, r in new.items():
            prev = old_rows.get(key)
            if prev and len(prev) >= 10 and prev[7] is not None:
                r = r + prev[7:10]  # keep the first line seen today
            else:
                r = r + [r[3], r[4], r[5]]
            out.append(r)
        for key, prev in old_rows.items():  # pulled props (game started): keep last known row
            if key not in new:
                out.append(prev if len(prev) >= 10 else prev + [prev[3], prev[4], prev[5]])
        if not out:
            continue
        out.sort(key=lambda r: (STAT_ORDER.index(r[2]) if r[2] in STAT_ORDER else 9, r[0], r[1]))
        props[gid] = {"asof": NOWISO if new else old.get("asof", NOWISO), "lg": "nba", "rows": out}
        total += len(out)
    return total


def roster(team):
    d = soft(SB + "teams/" + ESPN_ABBR.get(team, team.lower()) + "/roster", f"Roster {team}")
    if not d:
        return []
    ath = d.get("athletes") or []
    if ath and isinstance(ath[0], dict) and "items" in ath[0]:
        ath = [x for g in ath for x in g["items"]]
    return [(a["displayName"], a["id"], (a.get("position") or {}).get("abbreviation", "")) for a in ath]


def step_positions(meta):
    pos = load("positions")
    if pos.get("_date") == TODAY and len(pos) > 300:
        return pos
    out = {"_date": TODAY}
    for t in ALL_TEAMS:
        for n, i, p in roster(t):
            out[n] = {"pos": p, "id": i, "team": t}
    if len(out) > 300:
        save("positions", out)
        return out
    return pos or out


def step_h2h(h2h, tonight, slate, games, props, positions):
    teams = {}
    for gid in tonight:
        a, h = gid.split("-")[3:5]
        teams[a] = (h, gid)
        teams[h] = (a, gid)
    redo = [t for t, (o, gid) in teams.items() if (h2h.get(t) or {}).get("opp") != o
            or (h2h.get(t) or {}).get("start") != slate[gid]["start"]]
    if not redo:
        return 0
    propn = {(r[0], r[1]) for gid in tonight for r in (props.get(gid) or {}).get("rows") or []}
    mins = {}
    for g in games.values():
        for p in g["players"]:
            mins.setdefault((p["t"], p["n"]), []).append(p.get("min", 0))
    seasons = ["2026"] + (["2027"] if TODAY >= "2026-11-01" else [])
    done = 0
    for t in redo:
        opp, gid = teams[t]
        cands = []
        for n, info in positions.items():
            if n == "_date" or info.get("team") != t:
                continue
            hp, ms = (t, n) in propn, mins.get((t, n))
            if not hp and not ms:
                continue
            cands.append((0 if hp else 1, -(sum(ms) / len(ms) if ms else 0), n, info["id"]))
        cands.sort()
        players = {}
        for _, _, n, pid in cands[:14]:
            rows = {}
            for season in seasons:
                d = soft(f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{pid}/gamelog?season={season}",
                         f"Game log {n}")
                if not d or not d.get("names"):
                    continue
                names = d["names"]
                for stype in d.get("seasonTypes") or []:
                    if "Preseason" in (stype.get("displayName") or ""):
                        continue
                    label = "25-26" if season == "2026" else "26-27"
                    for c in stype.get("categories") or []:
                        for e in c.get("events") or []:
                            ev = (d.get("events") or {}).get(e.get("eventId"))
                            if not ev or m(dig(ev, "opponent", "abbreviation") or "") != opp:
                                continue
                            s = dict(zip(names, e.get("stats") or []))
                            try:
                                fg = [int(x) for x in s["fieldGoalsMade-fieldGoalsAttempted"].split("-")]
                                tp = [int(x) for x in s["threePointFieldGoalsMade-threePointFieldGoalsAttempted"].split("-")]
                                mn = float(s["minutes"])
                                mn = int(mn) if mn == int(mn) else mn
                                date = et_date(ev["gameDate"])
                                rows[date] = [date, m(dig(ev, "team", "abbreviation") or t), mn, int(s["points"]),
                                              int(s["totalRebounds"]), int(s["assists"]), tp[0], int(s["steals"]),
                                              int(s["blocks"]), int(s["turnovers"]), fg[0], fg[1], tp[1], int(s["fouls"]), label]
                            except (KeyError, ValueError):
                                continue
            for g in games.values():
                for p in g["players"]:
                    if nk(p["n"]) == nk(n):
                        o = g["home"] if p["t"] == g["away"] else g["away"]
                        if o == opp:
                            rows[g["date"]] = [g["date"], p["t"], p.get("min", 0), p["pts"], p["reb"], p["ast"], p["tp"],
                                               p["stl"], p["blk"], p["tov"], p["fg"], p["fga"], p["tpa"], p["pf"], "26-27"]
            if rows:
                players[n] = [rows[k] for k in sorted(rows)]
        h2h[t] = {"team": t, "opp": opp, "start": slate[gid]["start"], "guessRoster": False, "players": players}
        done += 1
    return done


def step_dvp(dvp, tonight, games, positions):
    P1 = {nk(k): v["pos"] for k, v in positions.items() if k != "_date"}
    DISP = {nk(k): k for k in positions if k != "_date"}
    grp = lambda n: {"G": "G", "F": "F", "C": "C"}.get((P1.get(nk(n)) or " ")[0])
    season = [g for g in games.values() if g["date"] >= "2026-10-01"]
    STATS = ["PTS", "REB", "AST", "3PM", "STL+BLK"]
    val = lambda p: {"PTS": p["pts"], "REB": p["reb"], "AST": p["ast"], "3PM": p["tp"], "STL+BLK": p["stl"] + p["blk"]}
    tot, gp = {}, {}
    for g in season:
        for d, o in ((g["home"], g["away"]), (g["away"], g["home"])):
            gp[d] = gp.get(d, 0) + 1
            for p in g["players"]:
                ps = grp(p["n"]) if p["t"] == o else None
                if not ps:
                    continue
                for s, v in val(p).items():
                    tot[(d, ps, s)] = tot.get((d, ps, s), 0) + v
    pg = {k: v / gp[k[0]] for k, v in tot.items()}
    rank = {}
    for ps in "GFC":
        for s in STATS:
            vals = {t: round(pg.get((t, ps, s), 0), 3) for t in gp}
            for t in gp:  # ties share a rank
                rank[(t, ps, s)] = 1 + sum(1 for x in vals.values() if x > vals[t])
    mins = {}
    for g in season:
        for p in g["players"]:
            mins.setdefault((p["t"], DISP.get(nk(p["n"]), p["n"])), []).append(p.get("min", 0))
    avg = {k: sum(v) / len(v) for k, v in mins.items()}
    ordn = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
    word = {"G": "guards", "F": "forwards", "C": "centers"}
    last = lambda n: [x for x in n.split() if x not in ("Jr.", "Sr.", "II", "III", "IV")][-1]
    for gid in tonight:
        a, h = gid.split("-")[3:5]
        rows = []
        for ps in "GFC":
            for d, o in ((h, a), (a, h)):
                if d not in gp:
                    continue
                top = sorted((rank[(d, ps, s)], s) for s in STATS if rank.get((d, ps, s), 99) <= 10)[:2]
                if not top:
                    continue
                pl = sorted((-v, n) for (t, n), v in avg.items() if t == o and v >= 20 and grp(n) == ps)
                if not pl:
                    continue
                names = [n for _, n in pl]
                txt = " · ".join((f"{ordn(r)} most {s} to {word[ps]} ({pg[(d, ps, s)]:.1f}/gm)" if i == 0
                                  else f"{ordn(r)} most {s} ({pg[(d, ps, s)]:.1f}/gm)") for i, (r, s) in enumerate(top))
                rows.append([d, ps, txt, " / ".join(last(n) for n in names), names])
        dvp[gid] = {"src": "computed", "rows": rows}


def main():
    games, slate, market = load("games"), load("slate"), load("market")
    injuries, props, h2h, dvp = load("injuries"), load("props"), load("h2h"), load("dvp")
    tonight = step_games_and_slate(games, slate, market, injuries)
    nprops = step_props(props, tonight) if tonight else 0
    positions = step_positions({}) if tonight else {}
    nh = 0
    if tonight and positions:
        try:
            nh = step_h2h(h2h, tonight, slate, games, props, positions)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Head-to-head failed: {e}")
        try:
            step_dvp(dvp, tonight, games, positions)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Defense vs position failed: {e}")
    # keep the daily files small: move NBA days older than a week into monthly archive files
    cutoff = (dt.date.fromisoformat(TODAY) - dt.timedelta(days=7)).isoformat()
    os.makedirs(os.path.join(DATA, "archive"), exist_ok=True)
    for col, d in (("market", market), ("injuries", injuries), ("props", props), ("dvp", dvp)):
        old = [k for k in d if re.match(r"\d{4}-\d{2}-\d{2}-", k) and k[:10] < cutoff]
        for k in old:
            arch = "archive/" + col + "-" + k[:7]
            a = load(arch)
            a[k] = d.pop(k)
            save(arch, a)
    for col, d in (("games", games), ("slate", slate), ("market", market), ("injuries", injuries),
                   ("props", props), ("h2h", h2h), ("dvp", dvp)):
        save(col, d)
    status = {"updated_at": NOWISO, "updated_et": STAMP, "games_tonight": len(tonight), "props": nprops,
              "h2h_rebuilt": nh, "box_scores": len(games), "notes": notes, "errors": errors}
    save("status", status)
    print(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
    sys.exit(0)
