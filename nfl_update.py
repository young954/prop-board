#!/usr/bin/env python3
"""NFL side of the Prop Board updater (runs after update.py).

Keeps nfl_teams (player game logs, head-to-head, injury tags), nfl_slate, nfl_dvp and the
NFL docs in market / injuries / props current from ESPN and Action Network. Standard library only.
"""
import datetime as dt
import json
import os
import re

import update as U  # shared fetch / load / save helpers

get, soft, load, save, nk, dig, ival, fval, iso_z = U.get, U.soft, U.load, U.save, U.nk, U.dig, U.ival, U.fval, U.iso_z
ET = U.ET
errors, notes = [], []
API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
DK = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/88808/categories/{}/subcategories/{}"
DK_SUBS = [(1000, 9524, "pyd"), (1000, 9522, "cmp"), (1000, 9525, "ptd"), (1001, 9514, "ryd"), (1001, 9518, "car"),
           (1342, 14114, "recyd"), (1342, 14115, "rec"), (1003, 12438, "td")]
STAT_ORDER = ["pyd", "cmp", "ptd", "ryd", "car", "recyd", "rec", "td"]
TM = {"WSH": "WAS", "LAR": "LA"}
t_ = lambda a: TM.get(a, a)
ESPN = {"WAS": "wsh", "LA": "lar"}
TEAMS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
         "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS"]
SKILL = {"QB", "RB", "WR", "TE", "FB"}
NOW, TODAY, NOWISO, STAMP = U.NOW, U.TODAY, U.NOWISO, U.STAMP


def s_(url, what):
    r = soft(url, what)
    if r is None:
        errors.append(U.errors.pop())
    return r


def fp(r):
    # PPR: 0.04/pass yd, 4/pass TD, -2/INT, 0.1/rush or rec yd, 6/rush or rec TD, 1/catch
    return round(0.04 * r[5] + 4 * r[6] - 2 * r[7] + 0.1 * r[9] + 6 * r[10] + r[11] + 0.1 * r[13] + 6 * r[14], 1)


def tag_for(start_iso):
    d = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(ET)
    wd = d.weekday()  # Mon=0
    if wd == 3:
        return "TNF"
    if wd == 0:
        return "MNF"
    if wd == 6 and d.hour >= 20:
        return "SNF"
    if wd == 5:
        return "Saturday"
    return ""


def gid_of(week, ev):
    c = ev["competitions"][0]
    t = {x["homeAway"]: x for x in c["competitors"]}
    a, h = t_(t["away"]["team"]["abbreviation"]), t_(t["home"]["team"]["abbreviation"])
    return f"w{week:02d}-{a}-{h}", a, h, t


def sb_odds(c):
    o = (c.get("odds") or [None])[0]
    if not o:
        return None
    ml, ps, to = o.get("moneyline") or {}, o.get("pointSpread") or {}, o.get("total") or {}
    return {"mlA": ival(dig(ml, "away", "close", "odds")), "mlH": ival(dig(ml, "home", "close", "odds")),
            "ou": o.get("overUnder"), "sh": fval(dig(ps, "home", "close", "line")) if dig(ps, "home", "close", "line") else o.get("spread"),
            "shO": fval(dig(ps, "home", "open", "line")), "totO": fval(dig(to, "over", "open", "line"))}


# ------------------------------------------------------------------ rosters
def rosters(week):
    r = load("nfl_roster")
    if r.get("_week") == week and len(r.get("players", {})) > 800:
        return r
    out = {"_week": week, "players": {}}
    for t in TEAMS:
        d = s_(API + "teams/" + ESPN.get(t, t.lower()) + "/roster", f"NFL roster {t}")
        if not d:
            continue
        for g in d.get("athletes") or []:
            for a in g.get("items") or []:
                pos = (a.get("position") or {}).get("abbreviation", "")
                if pos in SKILL:
                    out["players"][a["id"]] = {"n": a["displayName"], "pos": pos, "team": t, "grp": g.get("position")}
    if len(out["players"]) > 300:
        save("nfl_roster", out)
        return out
    return r or out


# ------------------------------------------------------------------ box scores → logs
def parse_box(summary):
    """{team: {espn_id: {n, row-stats}}} from an NFL game summary."""
    out = {}
    for tp in dig(summary, "boxscore", "players") or []:
        team = t_(tp["team"]["abbreviation"])
        P = out.setdefault(team, {})
        for c in tp.get("statistics") or []:
            name, keys = c.get("name"), c.get("keys") or []
            if name not in ("passing", "rushing", "receiving", "fumbles"):
                continue
            for a in c.get("athletes") or []:
                s = dict(zip(keys, a.get("stats") or []))
                p = P.setdefault(a["athlete"]["id"], {"n": a["athlete"]["displayName"], "cmp": 0, "att": 0, "pyd": 0, "ptd": 0,
                                                       "int": 0, "car": 0, "ryd": 0, "rtd": 0, "rec": 0, "tgt": 0, "recyd": 0,
                                                       "rectd": 0, "fl": 0})
                if name == "passing":
                    ca = (str(s.get("completions/passingAttempts", "0/0")).split("/") + ["0"])[:2]
                    p["cmp"], p["att"] = ival(ca[0]) or 0, ival(ca[1]) or 0
                    p["pyd"], p["ptd"], p["int"] = ival(s.get("passingYards")) or 0, ival(s.get("passingTouchdowns")) or 0, ival(s.get("interceptions")) or 0
                elif name == "rushing":
                    p["car"], p["ryd"], p["rtd"] = ival(s.get("rushingAttempts")) or 0, ival(s.get("rushingYards")) or 0, ival(s.get("rushingTouchdowns")) or 0
                elif name == "receiving":
                    p["rec"], p["recyd"], p["rectd"] = ival(s.get("receptions")) or 0, ival(s.get("receivingYards")) or 0, ival(s.get("receivingTouchdowns")) or 0
                    p["tgt"] = ival(s.get("receivingTargets")) or 0
                elif name == "fumbles":
                    p["fl"] = ival(s.get("fumblesLost")) or 0
    return out


def find_player(team_doc, name, espn_id):
    pl = team_doc.setdefault("players", {})
    if "e" + espn_id in pl:
        return "e" + espn_id
    key = nk(name)
    for pid, p in pl.items():
        if p.get("espn") == espn_id or nk(p.get("n", "")) == key:
            return pid
    return None


def ingest(teams, roster, week, ev, summary):
    gid, a, h, t = gid_of(week, ev)
    box = parse_box(summary)
    added = 0
    for team, P in box.items():
        opp, home = (h, 0) if team == a else (a, 1)
        tdoc = teams.setdefault(team, {"team": team, "players": {}})
        for eid, s in P.items():
            pid = find_player(tdoc, s["n"], eid)
            info = roster["players"].get(eid) or {}
            if not pid:
                if info.get("pos") not in SKILL:
                    continue
                pid = "e" + eid
                tdoc["players"][pid] = {"n": s["n"], "pos": info["pos"], "logs": [], "h2h": []}
            p = tdoc["players"][pid]
            p["espn"] = eid
            if any(r[0] == week and str(r[16]) == "2026" for r in p.get("logs") or []):
                continue
            row = [week, opp, home, s["cmp"], s["att"], s["pyd"], s["ptd"], s["int"], s["car"], s["ryd"], s["rtd"],
                   s["rec"], s["tgt"], s["recyd"], s["rectd"], 0, "2026", team]
            row[15] = round(fp(row) - 2 * s["fl"], 1)
            p.setdefault("logs", []).append(row)
            p["logs"].sort(key=lambda r: (str(r[16]), r[0]))
            added += 1
    return added


def week_done(teams, ev, week):
    _, a, h, _ = gid_of(week, ev)
    for team in (a, h):
        if not any(r[0] == week and str(r[16]) == "2026" for p in (teams.get(team) or {}).get("players", {}).values()
                   for r in p.get("logs") or []):
            return False
    return True


# ------------------------------------------------------------------ 2025 logs for head-to-head
def logs_2025(cache, eid, team_hint):
    if eid in cache:
        return cache[eid]
    d = s_(f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{eid}/gamelog?season=2025",
           f"NFL 2025 log {eid}")
    if d is None:
        return None
    rows = []
    names = d.get("names") or []
    for st in d.get("seasonTypes") or []:
        if "Preseason" in (st.get("displayName") or ""):
            continue
        for c in st.get("categories") or []:
            for e in c.get("events") or []:
                ev = (d.get("events") or {}).get(e.get("eventId"))
                if not ev:
                    continue
                s = dict(zip(names, e.get("stats") or []))
                g = lambda k: ival(str(s.get(k, "0")).replace(",", "")) or 0
                opp = ev.get("opponent")
                opp = t_(opp.get("abbreviation") if isinstance(opp, dict) else opp or "")
                team = ev.get("team")
                team = t_(team.get("abbreviation") if isinstance(team, dict) else team or team_hint)
                row = [ev.get("week") or 0, opp, 1 if ev.get("atVs") == "vs" else 0, g("completions"), g("passingAttempts"),
                       g("passingYards"), g("passingTouchdowns"), g("interceptions"), g("rushingAttempts"), g("rushingYards"),
                       g("rushingTouchdowns"), g("receptions"), g("receivingTargets"), g("receivingYards"),
                       g("receivingTouchdowns"), 0, "2025", team]
                row[15] = fp(row)
                rows.append(row)
    cache[eid] = sorted(rows, key=lambda r: r[0])
    return cache[eid]


# ------------------------------------------------------------------ defense vs position
def dvp_rows(teams, gid, inj_status):
    _, a, h = gid.split("-")
    grp = lambda pos: "RB" if pos == "FB" else pos
    STATS = {"QB": [("PASS CMP", 3, 0), ("PASS YDs", 5, 0), ("PASS TDs", 6, 1), ("RUSH YDs", 9, 0), ("RUSH TDs", 10, 1)],
             "RB": [("RUSH YDs", 9, 0), ("RUSH TDs", 10, 1), ("REC", 11, 0), ("REC YDs", 13, 0), ("REC TDs", 14, 1)],
             "WR": [("REC", 11, 0), ("REC YDs", 13, 0), ("REC TDs", 14, 1)],
             "TE": [("REC", 11, 0), ("REC YDs", 13, 0), ("REC TDs", 14, 1)]}
    tot, weeks = {}, {}
    for team, d in teams.items():
        for p in (d.get("players") or {}).values():
            g = grp(p.get("pos"))
            if g not in STATS:
                continue
            for r in p.get("logs") or []:
                if str(r[16]) != "2026":
                    continue
                D = r[1]
                weeks.setdefault(D, set()).add(r[0])
                for lbl, i, _ in STATS[g]:
                    tot[(D, g, lbl)] = tot.get((D, g, lbl), 0) + r[i]
    gp = {D: len(w) for D, w in weeks.items()}
    pg = {k: v / gp[k[0]] for k, v in tot.items()}
    rank = {}
    for g, sts in STATS.items():
        for lbl, _, _ in sts:
            vals = {D: round(pg.get((D, g, lbl), 0), 3) for D in gp}
            for D in gp:
                rank[(D, g, lbl)] = 1 + sum(1 for x in vals.values() if x > vals[D])
    ordn = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
    plural = {"QB": "QBs", "RB": "RBs", "WR": "WRs", "TE": "TEs"}

    def last(n):
        w = n.split()
        return " ".join(w[-2:]) if len(w) > 2 and w[-1] in ("Jr.", "Sr.", "II", "III", "IV") else w[-1]

    def usage(p, g):
        L = [r for r in p.get("logs") or [] if str(r[16]) == "2026"]
        if not L:
            return 0
        if g == "QB":
            return sum(r[4] for r in L) / len(L) / 15
        if g == "RB":
            return sum(r[8] + r[12] for r in L) / len(L) / 6
        return sum(r[12] for r in L) / len(L) / (4 if g == "WR" else 3)

    rows = []
    for g in ("QB", "RB", "WR", "TE"):
        for D, O in ((h, a), (a, h)):
            if D not in gp:
                continue
            top = sorted((rank[(D, g, lbl)], lbl, tf) for lbl, _, tf in STATS[g] if rank.get((D, g, lbl), 99) <= 10)[:3]
            if not top:
                continue
            cands = []
            for pid, p in ((teams.get(O) or {}).get("players") or {}).items():
                if grp(p.get("pos")) != g:
                    continue
                st = (inj_status.get((O, nk(p["n"]))) or "")
                if st == "Out":
                    continue
                u = usage(p, g)
                if u >= 1:
                    cands.append((-u, p["n"], st))
            cands.sort()
            if g == "QB":
                cands = cands[:1]
            if not cands:
                continue
            fmt = lambda D, lbl, tf: (f"{int(tot.get((D, g, lbl), 0))} total" if tf else f"{pg.get((D, g, lbl), 0):.1f}/gm")
            txt = " · ".join((f"{ordn(r)} most {lbl} to {plural[g]} ({fmt(D, lbl, tf)})" if i == 0
                              else f"{ordn(r)} most {lbl} ({fmt(D, lbl, tf)})") for i, (r, lbl, tf) in enumerate(top))
            names = " / ".join(last(n) + (f" ({st[0]})" if st in ("Doubtful", "Questionable") else "") for _, n, st in cands[:4])
            rows.append([D, g, txt, names])
    return rows


# ------------------------------------------------------------------ main
def main():
    teams, slate = load("nfl_teams"), load("nfl_slate")
    market, injuries, props, dvp = load("market"), load("injuries"), load("props"), load("nfl_dvp")
    sb = s_(API + "scoreboard", "NFL scoreboard")
    if not sb:
        return finish(teams, slate, market, injuries, props, dvp, None)
    year = dig(sb, "season", "year") or NOW.year
    wk = dig(sb, "week", "number") or 1
    evs = sb.get("events") or []
    boards = {wk: sb}
    if wk > 1:
        prev = s_(API + f"scoreboard?seasontype=2&week={wk - 1}&dates={year}", "NFL last week's scoreboard")
        if prev:
            boards[wk - 1] = prev
    S = wk
    if evs and all(dig(e, "status", "type", "state") == "post" for e in evs) and wk < 18:
        nxt = s_(API + f"scoreboard?seasontype=2&week={wk + 1}&dates={year}", "NFL next week's scoreboard")
        if nxt and nxt.get("events"):
            boards[wk + 1] = nxt
            S = wk + 1
    roster = rosters(S)

    # 1. box scores for finished games not yet in the logs
    added = 0
    for w, b in sorted(boards.items()):
        for ev in b.get("events") or []:
            if dig(ev, "status", "type", "state") != "post" or week_done(teams, ev, w):
                continue
            s = s_(API + "summary?event=" + ev["id"], f"NFL game {ev.get('shortName', ev['id'])}")
            if s:
                added += ingest(teams, roster, w, ev, s)
    if added:
        notes.append(f"NFL: {added} player game logs added")

    # 2. this week's slate, lines, injuries
    inj_status = {}
    week_ids = []
    for ev in boards[S].get("events") or []:
        gid, a, h, t = gid_of(S, ev)
        week_ids.append(gid)
        c = ev["competitions"][0]
        state = dig(ev, "status", "type", "state")
        old = slate.get(gid, {})
        o = sb_odds(c) if state == "pre" else None
        sl = {"away": a, "home": h, "start": iso_z(ev["date"]), "week": S, "tag": tag_for(ev["date"]), "src": "am",
              "mlA": (o or {}).get("mlA", old.get("mlA")), "mlH": (o or {}).get("mlH", old.get("mlH")),
              "ou": (o or {}).get("ou", old.get("ou"))}
        if state == "post":
            sl.update(status="final", **{"as": ival(t["away"].get("score")), "hs": ival(t["home"].get("score"))})
        elif state == "in":
            sl.update(status="live", **{"as": ival(t["away"].get("score")), "hs": ival(t["home"].get("score"))})
        else:
            sl["status"] = "scheduled"
        slate[gid] = sl
        if o:
            prev = market.get(gid) or {}
            shO = prev.get("shO", o["shO"]) if prev.get("shO") is not None else o["shO"]
            totO = prev.get("totO", o["totO"]) if prev.get("totO") is not None else o["totO"]
            keep = prev.get("shO") == shO and prev.get("totO") == totO
            market[gid] = {"asof": NOWISO, "lg": "nfl", "mlA": o["mlA"], "mlH": o["mlH"], "sh": o["sh"], "shO": shO,
                           "tot": o["ou"], "totO": totO, "notes": prev.get("notes", []) if keep else [],
                           "splits": prev.get("splits", []) if keep else [], "src": f"DraftKings lines via ESPN ({STAMP})", "wpH": None}
        if state != "post":
            start = dt.datetime.fromisoformat(sl["start"].replace("Z", "+00:00"))
            soon = start - NOW.astimezone(dt.timezone.utc) < dt.timedelta(days=4)
            stale = (injuries.get(gid) or {}).get("asof", "")[:10] != NOWISO[:10]
            if soon or stale:
                s = s_(API + "summary?event=" + ev["id"], f"NFL injuries {gid}")
                if s:
                    rows = []
                    for ti in sorted(s.get("injuries") or [], key=lambda x: 0 if t_(x["team"]["abbreviation"]) == a else 1):
                        tm = t_(ti["team"]["abbreviation"])
                        for inj in ti.get("injuries") or []:
                            pos = (inj["athlete"].get("position") or {}).get("abbreviation", "")
                            if pos not in SKILL:
                                continue
                            det = inj.get("details") or {}
                            what = det.get("type") or ""
                            if det.get("detail") and det["detail"] != "Not Specified":
                                what += f" ({det['detail']})"
                            stt = inj.get("status") or ""
                            rd = det.get("returnDate")
                            note = f"Back ~{U.mdy(rd)}" if rd and rd[:10] > TODAY and stt in ("Out", "Injured Reserve") else ""
                            rows.append([tm, inj["athlete"]["displayName"], pos, what, stt, note])
                    injuries[gid] = {"asof": NOWISO, "lg": "nfl", "src": f"ESPN NFL injury report ({STAMP})", "rows": rows}
        for r in (injuries.get(gid) or {}).get("rows") or []:
            inj_status[(r[0], nk(r[1]))] = "Out" if r[4] in ("Injured Reserve", "Physically Unable to Perform", "Suspended") else r[4]

    # 3. team matchups, injury tags, head-to-head
    games_by_team = {}
    for gid in week_ids:
        _, a, h = gid.split("-")
        games_by_team[a] = (h, False, slate[gid]["start"])
        games_by_team[h] = (a, True, slate[gid]["start"])
    cache = load("nfl_2025")
    budget = 150
    order = sorted(TEAMS, key=lambda t: (games_by_team.get(t, (None, None, "9"))[2]))
    by_name = {(v["team"], nk(v["n"])): k for k, v in roster["players"].items()}
    for team in order:
        d = teams.setdefault(team, {"team": team, "players": {}})
        opp, home, start = games_by_team.get(team, (None, None, None))
        changed = d.get("opp") != opp
        d.update(team=team, opp=opp, home=home, start=start)
        for pid, p in (d.get("players") or {}).items():
            st = inj_status.get((team, nk(p["n"])))
            row = next((r for gid in week_ids for r in (injuries.get(gid) or {}).get("rows") or []
                        if r[0] == team and nk(r[1]) == nk(p["n"])), None)
            if row:
                p["inj"] = [st, row[3]]
            else:
                p.pop("inj", None)
            if not opp:
                if changed:
                    p["h2h"] = []
                continue
            eid = p.get("espn") or by_name.get((team, nk(p["n"])))
            if eid:
                p["espn"] = eid
            done = p.get("h2hOpp") == opp
            if done:
                continue
            L25 = cache.get(eid) if eid else None
            if eid and L25 is None and budget > 0:
                budget -= 1
                L25 = logs_2025(cache, eid, team)
            if L25 is None and eid:
                continue  # try again next run
            rows = [r for r in (L25 or []) if r[1] == opp]
            rows += [r for r in p.get("logs") or [] if str(r[16]) == "2026" and r[1] == opp]
            p["h2h"] = rows
            p["h2hOpp"] = opp
    save("nfl_2025", cache)

    # 4. props with opening lines
    rows_by, got = {}, False
    by_game, used = {}, {}
    try:
        import anprops
        by_game, used = anprops.pull("nfl", {"week": S}, get)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Action Network NFL props didn't load: {type(e).__name__} {str(e)[:80]}")
    try:  # second source fills anything Action Network lacks (or everything if it failed)
        import kalshi
        by_game, added, _tot, kerr = kalshi.merge("nfl", by_game, get)
        errors.extend(kerr)
        if added:
            used["Kalshi"] = added
    except Exception as e:  # noqa: BLE001
        errors.append(f"Kalshi NFL props didn't load: {type(e).__name__} {str(e)[:80]}")
    if by_game:
        got = True
        for gid in week_ids:
            parts = gid.split("-")
            rows_by[gid] = by_game.get((parts[1], parts[2]), {})
        if used:
            notes.append("NFL props: " + ", ".join(f"{k} {v}" for k, v in sorted(used.items())))
    nprops = 0
    if got:
        for gid in week_ids:
            old = props.get(gid) or {}
            old_rows = {(r[0], r[1], r[2]): r for r in old.get("rows") or []}
            new = rows_by.get(gid, {})
            out = []
            for key, r in new.items():
                prev = old_rows.get(key)
                if r[7] is None:  # no opening line from the feed: keep the first line seen
                    r = r[:7] + (prev[7:10] if prev and len(prev) >= 10 and prev[7] is not None else [r[3], r[4], r[5]])
                out.append(r)
            for key, prev in old_rows.items():
                if key not in new:
                    out.append(prev if len(prev) >= 10 else prev + [prev[3], prev[4], prev[5]])
            if out:
                out.sort(key=lambda r: (STAT_ORDER.index(r[2]) if r[2] in STAT_ORDER else 9, r[0], r[1]))
                props[gid] = {"asof": NOWISO if new else old.get("asof", NOWISO), "lg": "nfl", "rows": out}
                nprops += len(out)

    # 5. defense vs position for this week's games
    for gid in week_ids:
        dvp[gid] = {"src": "computed", "rows": dvp_rows(teams, gid, inj_status)}
    finish(teams, slate, market, injuries, props, dvp, S, nprops)


def finish(teams, slate, market, injuries, props, dvp, S, nprops=0):
    if S:
        keep = lambda k: not re.match(r"w\d+-", k) or int(k[1:3]) >= S
        for col, d in (("nfl_slate", slate), ("nfl_dvp", dvp)):
            for k in [k for k in d if re.match(r"w\d+-", k) and int(k[1:3]) != S]:
                a = load("archive/" + col + "-2026")
                a[k] = d.pop(k)
                save("archive/" + col + "-2026", a)
        for col, d in (("market", market), ("injuries", injuries), ("props", props)):
            for k in [k for k in d if not keep(k)]:
                a = load("archive/" + col + "-nfl-2026")
                a[k] = d.pop(k)
                save("archive/" + col + "-nfl-2026", a)
    for col, d in (("nfl_teams", teams), ("nfl_slate", slate), ("market", market), ("injuries", injuries),
                   ("props", props), ("nfl_dvp", dvp)):
        save(col, d)
    st = load("status")
    st.update(nfl_week=S, nfl_props=nprops, nfl_notes=notes)
    allerr = (st.get("errors") or []) + errors
    st["errors"] = allerr[:15] + ([f"...and {len(allerr) - 15} more"] if len(allerr) > 15 else [])
    save("status", st)
    print(json.dumps({"nfl_week": S, "nfl_props": nprops, "notes": notes, "errors": errors}, indent=1))


if __name__ == "__main__":
    main()
