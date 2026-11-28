#!/usr/bin/env node
/* Parlay Lab: builds four 4-leg mock parlays a day from the board's own Edge Finder model,
   grades them when games finish, and learns from every graded leg.
   Usage: node parlay_lab.js            daily run (lock today's card, grade finished days)
          node parlay_lab.js --replay   rebuild the backtest from all past days (only data known before each game)
   Output: parlays.json (read by the board). Kept small: no per-candidate data is shipped to users. */
"use strict";
const fs = require("fs"), path = require("path");
const ROOT = __dirname, OUT = path.join(ROOT, "parlays.json"), LEGS = path.join(ROOT, "archive", "parlay_legs.json");
const load = f => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, f + ".json"), "utf8")); } catch (e) { return {}; } };

/* ---- reuse the board's model exactly as users see it (index.html, Prop Edge Finder block) ---- */
function loadModel(){
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const a = html.indexOf("/* ---------- Prop Edge Finder");
  const s = html.indexOf("const norm =", a), e = html.indexOf("function build(){", s);
  if (a < 0 || s < 0 || e < 0) throw new Error("Edge Finder code not found in index.html");
  const code = html.slice(s, e) + "\nreturn {D, prep, evaluate, rowsOf, MODEL, dec, imp, norm, EV_MIN};";
  return new Function("fetch", "document", code)(null, null);
}
const M = loadModel(), D = M.D;
const FILES = ["props","games","h2h","dvp","injuries","slate","nfl_teams","nfl_dvp","nfl_slate","status"];
for (const f of FILES) D[f] = load(f);
// fold the monthly archives back in so past days can be replayed and graded
for (const f of fs.readdirSync(path.join(ROOT, "archive"))){
  const m = f.match(/^(props|dvp|injuries|market|nfl_slate|nfl_dvp)-(nfl-)?(\d{4}(-\d\d)?)\.json$/); if (!m) continue;
  const key = m[1] === "market" ? null : m[1]; if (!key) continue;
  D[key] = Object.assign({}, load("archive/" + f.slice(0, -5)), D[key]);
}
if (Object.keys(D.injuries).length === 0) D.injuries = {};
const NFL_TEAMS_FULL = D.nfl_teams;

/* ---- settings ---- */
const STAKE = 10;            // mock $10 per parlay
const SGP_HAIRCUT = 0.8;     // books pay same-game parlays less than the straight product; we pay ourselves 80% of it
const MIN_P = 0.5, MAX_JUICE = -300;
const ET = d => new Date(d).toLocaleDateString("en-CA", {timeZone: "America/New_York"});
const etHour = d => +new Date(d).toLocaleString("en-US", {timeZone: "America/New_York", hour: "numeric", hourCycle: "h23"});
const statGroup = k => /^(pts|pr|pa|pra)$/.test(k) ? "points" : /^(reb|ast|tp)$/.test(k) ? k : /^(pyd|cmp|ptd)$/.test(k) ? "passing" : /^(ryd|car)$/.test(k) ? "rushing" : "receiving";

/* ---- learning: how each kind of leg has really cashed vs what the model said ---- */
function learn(legLog){
  const g = {};
  for (const l of legLog){ if (l.r !== 1 && l.r !== 0) continue;
    for (const k of [l.lg + "|" + l.sd, l.lg + "|" + l.sd + "|" + l.g]){ const x = g[k] ||= {n:0, hit:0, p:0}; x.n++; x.hit += l.r; x.p += l.p; } }
  const adj = {};
  for (const [k, x] of Object.entries(g)){ const gap = (x.hit - x.p) / x.n; adj[k] = {n: x.n, hit: x.hit / x.n, p: x.p / x.n, a: gap * x.n / (x.n + (k.startsWith("nfl") ? 60 : 150))}; }
  return adj;
}
const adjP = (adj, lg, sd, grp, p) => {
  const a = (adj[lg + "|" + sd + "|" + grp] || adj[lg + "|" + sd] || {a: 0}).a;
  const cap = lg === "nfl" ? 0.1 : 0.08; return Math.min(0.95, Math.max(0.05, p + Math.max(-cap, Math.min(cap, a))));
};

/* ---- candidates for one day ---- */
function candidates(ids, slateOf, adj){
  const out = [];
  for (const id of ids){
    const doc = D.props[id], g = slateOf(id); if (!doc || !g) continue;
    for (const row of M.rowsOf(doc)){
      let r; try { r = M.evaluate(doc.lg, id, g, row); } catch (e) { continue; }
      if (!r || r.skip || r.noBook || r.price == null || r.price < MAX_JUICE) continue;
      const pa = adjP(adj, doc.lg, r.side, statGroup(r.key), r.pSide);
      out.push({id, lg: doc.lg, t: r.team, n: r.name, k: r.key, l: r.line, sd: r.side, o: r.price, bk: r.bestBk || r.src,
        p: +r.pSide.toFixed(4), pa: +pa.toFixed(4), ev: +(pa * M.dec(r.price) - 1).toFixed(4), pm: +r.pmSide.toFixed(4), gp: r.n, lbl: r.label, opp: r.opp});
    }
  }
  return out;
}

/* ---- the four parlays ---- */
const conflict = (a, b) => a.id === b.id && M.norm(a.n) === M.norm(b.n);   // one leg per player
function pickDistinct(list, n, okGame){
  const out = [], games = new Set();
  for (const c of list){ if (out.length === n) break;
    if (okGame && games.has(c.id)) continue; if (out.some(x => conflict(x, c))) continue;
    out.push(c); games.add(c.id); }
  return out.length === n ? out : null;
}
function build(cands){
  const ok = cands.filter(c => c.pa >= MIN_P);
  const P = [];
  const add = (name, why, legs, sgp) => { if (!legs) return;
    const price = legs.reduce((s, l) => s * M.dec(l.o), 1) * (sgp ? SGP_HAIRCUT : 1), p = legs.reduce((s, l) => s * l.pa, 1);
    P.push({name, why, sgp: !!sgp, legs: legs.map(l => ({id:l.id, lg:l.lg, t:l.t, n:l.n, k:l.k, lbl:l.lbl, l:l.l, sd:l.sd, o:l.o, bk:l.bk, p:l.pa, opp:l.opp})),
      dec: +price.toFixed(2), p: +p.toFixed(4), ev: +(p * price - 1).toFixed(3)}); };
  // 1. Steady: the four most likely legs, one per game
  add("Steady", "The 4 legs the model trusts most, one per game", pickDistinct([...ok].sort((a, b) => b.pa - a.pa), 4, true));
  // 2. Sharp: every leg 57%+ AND priced in our favor (best record across every test period)
  const steadyKeys = new Set((P[0] ? P[0].legs : []).map(l => l.id + l.n + l.k));
  let sharpList = ok.filter(c => c.pa >= 0.57 && c.ev > 0).sort((a, b) => b.pa - a.pa);
  let sharp = pickDistinct(sharpList, 4, true);
  if (sharp && sharp.every(l => steadyKeys.has(l.id + l.n + l.k))) sharp = pickDistinct(sharpList.slice(1), 4, true);
  let sharpWhy = "Every leg 57%+ and priced in our favor, one per game";
  if (!sharp){ sharpList = ok.filter(c => c.pa >= 0.54 && c.ev > 0).sort((a, b) => b.ev - a.ev);
    sharp = pickDistinct(sharpList.filter(c => !steadyKeys.has(c.id + c.n + c.k)), 4, true) || pickDistinct(sharpList, 4, true);
    sharpWhy = "Thin slate: fewer 57% legs today, so every leg 54%+ and priced in our favor"; }
  add("Sharp", sharpWhy, sharp);
  // 3. Same game: the game whose 4 best legs (different players) multiply to the highest chance
  let best = null;
  for (const id of new Set(ok.map(c => c.id))){
    const legs = pickDistinct(ok.filter(c => c.id === id).sort((a, b) => b.pa - a.pa), 4, false); if (!legs) continue;
    const p = legs.reduce((s, l) => s * l.pa, 1); if (!best || p > best.p) best = {legs, p};
  }
  add("Same game", "Long shot: 4 players from the one game the model likes most. Legs in one game move together, and books pay same-game parlays less (we cut the payout 20%)", best && best.legs, true);
  // 4. Mixed: NBA + NFL when both play today, otherwise four different stat types
  const nba = ok.filter(c => c.lg === "nba").sort((a, b) => b.pa - a.pa), nfl = ok.filter(c => c.lg === "nfl").sort((a, b) => b.pa - a.pa);
  const used = new Set(P.flatMap(x => x.legs.map(l => l.id + l.n + l.k)));
  const fresh = l => !used.has(l.id + l.n + l.k);
  if (nba.length >= 2 && nfl.length >= 2){
    const a = pickDistinct(nba.filter(fresh), 2, true) || pickDistinct(nba, 2, true), b = pickDistinct(nfl.filter(fresh), 2, true) || pickDistinct(nfl, 2, true);
    add("Mixed", "2 NBA + 2 NFL legs", a && b ? [...a, ...b] : null);
  } else {
    const legs = pickDistinct(ok.filter(c => c.sd === "UNDER" && fresh(c)).sort((a, b) => b.pa - a.pa), 4, true)
              || pickDistinct(ok.filter(c => c.sd === "UNDER").sort((a, b) => b.pa - a.pa), 4, true);
    add("Mixed", (nba.length < 2 ? "No NBA today" : "No NFL today") + ", so 4 Unders from 4 games (Unders have cashed more than Overs all season)", legs);
  }
  return P;
}

/* ---- grading ---- */
function legResult(l){
  if (l.lg === "nba"){
    const g = D.games[l.id]; if (!g || !g.players) return null;
    const s = (D.slate[l.id] || {}).status; if (s && s !== "final" && !g.final) { if (s === "scheduled" || s === "in") return null; }
    const pl = g.players.find(p => M.norm(p.n) === M.norm(l.n) && p.t === l.t);
    if (!pl || !(pl.min > 0)) return "void";
    const v = M.MODEL.nba.stats[l.k].f(pl); l.v = v;
    return v === l.l ? "push" : (v > l.l) === (l.sd === "OVER") ? "win" : "loss";
  }
  const wk = +l.id.slice(1, 3), tm = NFL_TEAMS_FULL[l.t]; if (!tm) return null;
  const sl = D.nfl_slate[l.id], done = sl ? sl.status === "final" : wk < (+(D.status || {}).nfl_week || 99);
  if (!done) return null;
  const p = Object.values(tm.players || {}).find(q => M.norm(q.n) === M.norm(l.n)); if (!p) return "void";
  const row = (p.logs || []).find(r => r[0] === wk && String(r[16]) === "2026");
  if (!row) return "void";
  const v = M.MODEL.nfl.stats[l.k].f(row); l.v = v;
  return v === l.l ? "push" : (v > l.l) === (l.sd === "OVER") ? "win" : "loss";
}
function grade(day){
  for (const P of day.parlays){
    if (P.res && P.res !== "open") continue;
    let open = false, lost = false, d = 1;
    for (const l of P.legs){ const r = legResult(l); l.r = r || "open"; if (!r) open = true; else if (r === "loss") lost = true; else if (r === "win") d *= M.dec(l.o); }
    if (lost){ P.res = "loss"; P.pl = -STAKE; }
    else if (!open){ const pay = d === 1 ? 1 : d * (P.sgp ? SGP_HAIRCUT : 1); P.res = d === 1 ? "push" : "win"; P.pl = +(STAKE * (pay - 1)).toFixed(2); }
    else P.res = "open";
  }
}
function gradeLegLog(log){ for (const l of log){ if (l.r === 1 || l.r === 0) continue; const r = legResult(l); l.r = r === "win" ? 1 : r === "loss" ? 0 : r ? -1 : null; delete l.v; } }

/* ---- days available ---- */
const nbaIds = d => Object.keys(D.props).filter(id => D.props[id].lg === "nba" && id.slice(0, 10) === d);
const nflIdsOn = d => Object.keys(D.props).filter(id => D.props[id].lg === "nfl" && D.nfl_slate[id] && D.nfl_slate[id].start && ET(D.nfl_slate[id].start) === d);
const nflSlate = id => D.nfl_slate[id] || (() => { const m = id.match(/^w\d+-(\w+)-(\w+)$/); return m ? {away: m[1], home: m[2]} : null; })();

/* ---- stats for the board ---- */
function summarize(days, legLog){
  const rec = {}, add = (k, P) => { const x = rec[k] ||= {w:0, l:0, push:0, pl:0, legs:0, legW:0}; if (P.res === "win") x.w++; else if (P.res === "loss") x.l++; else if (P.res === "push") x.push++; x.pl += P.pl || 0;
    for (const l of P.legs){ if (l.r === "win" || l.r === "loss"){ x.legs++; if (l.r === "win") x.legW++; } } };
  for (const d of Object.values(days)) for (const P of d.parlays){ if (P.res === "open" || !P.res) continue;
    add((d.replay ? "replay|" : "live|") + P.name, P); add((d.replay ? "replay|" : "live|") + "All", P); }
  for (const x of Object.values(rec)) x.pl = +x.pl.toFixed(2);
  const adj = learn(legLog), cal = {};
  for (const [k, v] of Object.entries(adj)) if (v.n >= 30) cal[k] = {n: v.n, hit: +v.hit.toFixed(3), p: +v.p.toFixed(3)};
  return {rec, cal};
}

/* ---- main ---- */
function run(replay){
  const prev = load("parlays");
  const prevLegs = (() => { try { return JSON.parse(fs.readFileSync(LEGS, "utf8")); } catch (e) { return []; } })();
  const liveDays = Object.keys(prev.days || {}).filter(k => !prev.days[k].replay);
  // a replay rebuilds the backtest but never touches live (locked) cards or their legs
  let days = replay ? {} : (prev.days || {}), legLog = replay ? prevLegs.filter(l => liveDays.includes(l.d)) : prevLegs;
  const today = ET(Date.now());
  if (replay){
    const allDays = [...new Set(Object.keys(D.props).filter(id => D.props[id].lg === "nba").map(id => id.slice(0, 10)))].filter(d => d < today).sort();
    const nflWeeks = [...new Set(Object.keys(D.props).filter(id => /^w\d+/.test(id)).map(id => +id.slice(1, 3)))].filter(w => w < (+(D.status || {}).nfl_week || 99)).sort((a, b) => a - b);
    const saveGames = D.games;
    // NBA: one card per day using only box scores from earlier days; learning adds each day after it finishes
    for (const d of allDays){
      const sub = {}; for (const [k, v] of Object.entries(saveGames)) if ((v.date || k.slice(0, 10)) < d) sub[k] = v;
      D.games = sub; M.prep(); const adj = learn(legLog.filter(l => l.d < d));
      const cands = candidates(nbaIds(d), id => D.slate[id], adj);
      D.games = saveGames;
      if (global.EXP) global.EXP(d, cands);
      days[d] = {replay: 1, parlays: build(cands)}; grade(days[d]);
      for (const c of cands) legLog.push({d, id: c.id, lg: c.lg, t: c.t, n: c.n, k: c.k, l: c.l, sd: c.sd, g: statGroup(c.k), p: c.p});
    }
    // NFL: one card per week (Sunday) using only earlier weeks' logs
    for (const w of nflWeeks){
      const cut = {}; for (const [t, td] of Object.entries(NFL_TEAMS_FULL)){ const pl = {};
        for (const [pid, p] of Object.entries(td.players || {})) pl[pid] = {...p, h2h: [], h2hOpp: null, logs: (p.logs || []).filter(r => String(r[16]) !== "2026" || r[0] < w)};
        cut[t] = {...td, players: pl}; }
      D.nfl_teams = cut; M.prep(); const adj = learn(legLog.filter(l => !liveDays.includes(l.d)));
      const ids = Object.keys(D.props).filter(id => id.startsWith("w" + String(w).padStart(2, "0") + "-"));
      const cands = candidates(ids, nflSlate, adj);
      D.nfl_teams = NFL_TEAMS_FULL;
      const key = "nfl-w" + String(w).padStart(2, "0");
      if (global.EXP) global.EXP(key, cands);
      const P = build(cands).filter(x => x.name !== "Mixed" || x.legs.every(l => l.lg === "nfl"));
      days[key] = {replay: 1, nfl: w, parlays: P}; grade(days[key]);
      for (const c of cands) legLog.push({d: key, id: c.id, lg: "nfl", t: c.t, n: c.n, k: c.k, l: c.l, sd: c.sd, g: statGroup(c.k), p: c.p});
    }
    M.prep();
    for (const k of liveDays) days[k] = prev.days[k];
    legLog.sort((a, b) => String(a.d).localeCompare(String(b.d)));
  }
  // grade everything still open
  for (const d of Object.values(days)) grade(d);
  gradeLegLog(legLog);
  // lock today's live card once: after 10 AM ET (or 3 h before the first game) with enough legs posted
  if (!replay && !(days[today] && !days[today].replay)){
    M.prep();
    const ids = nbaIds(today).filter(id => (D.slate[id] || {}).status === "scheduled"), nfl = nflIdsOn(today).filter(id => D.nfl_slate[id].status === "scheduled");
    const starts = [...ids.map(id => D.slate[id].start), ...nfl.map(id => D.nfl_slate[id].start)].filter(Boolean).map(Date.parse);
    const first = starts.length ? Math.min(...starts) : null, now = Date.now();
    if (first && first > now && (process.env.LAB_FORCE || etHour(now) >= 10 || first - now < 3 * 3600e3)){
      const adj = learn(legLog), cands = candidates([...ids, ...nfl], id => D.slate[id] || D.nfl_slate[id], adj).filter(c => {
        const g = D.slate[c.id] || D.nfl_slate[c.id]; return g && Date.parse(g.start) > now; });
      if (cands.length >= 12){
        const parlays = build(cands);
        if (parlays.length){ days[today] = {created: new Date(now).toISOString(), parlays};
          for (const c of cands) legLog.push({d: today, id: c.id, lg: c.lg, t: c.t, n: c.n, k: c.k, l: c.l, sd: c.sd, g: statGroup(c.k), p: c.p}); }
      }
    }
  }
  const {rec, cal} = summarize(days, legLog);
  const out = {updated: new Date().toISOString(), stake: STAKE, sgpHaircut: SGP_HAIRCUT, rec, cal, days};
  fs.writeFileSync(OUT, JSON.stringify(out));
  fs.writeFileSync(LEGS, JSON.stringify(legLog));
  return {...out, legLog};
}

if (require.main === module){
  const out = run(process.argv.includes("--replay"));
  const r = out.rec, f = k => r[k] ? `${r[k].w}-${r[k].l}${r[k].push ? "-" + r[k].push : ""}  legs ${r[k].legW}/${r[k].legs} (${(100 * r[k].legW / Math.max(1, r[k].legs)).toFixed(1)}%)  P/L $${r[k].pl}` : "-";
  for (const k of Object.keys(r).sort()) console.log(k.padEnd(22), f(k));
  console.log("cards:", Object.keys(out.days).length, "legs logged:", out.legLog.length, "size KB:", (fs.statSync(OUT).size / 1024).toFixed(0));
}
module.exports = {run, legResult, statGroup, dec: M.dec, norm: M.norm};
