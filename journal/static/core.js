/* XUAN 交易日誌 — 共用工具、資料計算、圖表、路由 */
'use strict';

// ---------------------------------------------------------------- DOM helpers
// 原生 append/replaceChildren 會把 null 印成 "null"，這裡統一略過 null / false
for (const fn of ['append', 'replaceChildren']) {
  const orig = Element.prototype[fn];
  Element.prototype[fn] = function (...kids) { return orig.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };
}
const $ = (sel, root = document) => root.querySelector(sel);
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) { if (c == null || c === false) continue; el.append(c instanceof Node ? c : String(c)); }
  return el;
}
const SVGNS = 'http://www.w3.org/2000/svg';
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) { if (c == null) continue; el.append(c instanceof Node ? c : document.createTextNode(String(c))); }
  return el;
}
const ICONS = {
  overview: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  trades: '<path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="M13.5 6.5l3 3"/><path d="M4 4h7"/><path d="M4 8h4"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/><path d="M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01"/>',
  analytics: '<path d="M21 12a9 9 0 1 1-9-9v9z"/><path d="M13.5 3.1A9 9 0 0 1 20.9 10.5H13.5z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  api: '<path d="M7 17l-3 3"/><path d="M9.5 9.5L7 12l5 5 2.5-2.5"/><path d="M14.5 14.5L17 12l-5-5-2.5 2.5"/><path d="M17 7l3-3"/><path d="M12 7l1-1M17 12l1-1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  sync: '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12A9 9 0 0 1 18.5 5.8L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
  up: '<path d="M6 15l6-6 6 6"/>', down: '<path d="M6 9l6 6 6-6"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  edit: '<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>', filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>',
  left: '<path d="M15 18l-6-6 6-6"/>', right: '<path d="M9 18l6-6-6-6"/>', spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
};
function icon(name, size = 20) {
  const el = s('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
  el.innerHTML = ICONS[name] || '';
  return el;
}

// ---------------------------------------------------------------- formatting
const num = (v) => { if (v === '' || v == null) return null; const n = Number(String(v).replace(/,/g, '')); return Number.isFinite(n) ? n : null; };
const fin = (n) => n != null && Number.isFinite(n);
const fmt = (n, d = 2) => !fin(n) ? '—' : n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: d });
const fmtFix = (n, d = 2) => !fin(n) ? '—' : n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const sign = (n) => n > 0 ? '+' : n < 0 ? '-' : '';
const fmtS = (n, d = 2) => !fin(n) ? '—' : sign(n) + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtR = (n, d = 2) => !fin(n) ? '—' : (n === 0 ? '0.00' : fmtS(n, d)) + 'R';
const fmtU = (n, d = 2) => !fin(n) ? '—' : (n === 0 ? '0.00' : fmtS(n, d)) + ' U';
const fmtPct = (n, d = 1) => !fin(n) ? '—' : (+n.toFixed(d)).toString() + '%';
const fmtPF = (n) => n == null ? '—' : !Number.isFinite(n) ? '∞' : n.toFixed(2);
const cls = (n) => !fin(n) ? '' : n > 0 ? 'gain' : n < 0 ? 'loss' : '';
const pad = (n) => String(n).padStart(2, '0');
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const WD = ['日', '一', '二', '三', '四', '五', '六'];
const SESSIONS = [
  { k: 0, name: '凌晨時段', short: '凌晨', range: '00:00～08:00', from: 0, to: 8 },
  { k: 1, name: '上午時段', short: '上午', range: '08:00～12:00', from: 8, to: 12 },
  { k: 2, name: '下午時段', short: '下午', range: '12:00～16:00', from: 12, to: 16 },
  { k: 3, name: '晚間時段', short: '晚間', range: '16:00～20:00', from: 16, to: 20 },
  { k: 4, name: '深夜時段', short: '深夜', range: '20:00～24:00', from: 20, to: 24 },
];

// 台北時間（UTC+8，沒有日光節約）
const TZ_MS = 8 * 3600 * 1000;
function tw(iso) {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  const d = new Date(ms + TZ_MS);
  const y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, day = d.getUTCDate(), hh = d.getUTCHours(), mm = d.getUTCMinutes();
  return { ms, y, m, d: day, hh, mm, dow: d.getUTCDay(), key: `${y}-${pad(m)}-${pad(day)}`, mkey: `${y}-${pad(m)}`, mins: hh * 60 + mm };
}
const fmtDT = (iso) => { const p = tw(iso); return p ? `${p.m}/${p.d} ${pad(p.hh)}:${pad(p.mm)}` : '—'; };
const fmtDTY = (iso) => { const p = tw(iso); return p ? `${p.y}/${pad(p.m)}/${pad(p.d)} ${pad(p.hh)}:${pad(p.mm)}` : '—'; };
const toInput = (iso) => { const p = tw(iso); return p ? `${p.key}T${pad(p.hh)}:${pad(p.mm)}` : ''; };
const fromInput = (v) => v ? new Date(`${v}:00+08:00`).toISOString() : null;
const todayKey = () => tw(new Date().toISOString()).key;
const keyToMs = (key) => Date.parse(`${key}T00:00:00+08:00`);
function fmtHold(min) {
  if (!fin(min)) return '—';
  if (min < 60) return `${Math.round(min)} 分`;
  if (min < 60 * 48) return `${(min / 60).toFixed(1)} 小時`;
  return `${(min / 1440).toFixed(1)} 天`;
}

function toast(msg) { const t = h('div', { class: 'toast', role: 'status' }, msg); document.body.append(t); setTimeout(() => t.remove(), 2600); }

// ---------------------------------------------------------------- API
async function api(method, url, body, isForm) {
  const opt = { method, credentials: 'same-origin', headers: {} };
  if (body != null) {
    if (isForm) opt.body = body;
    else { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  }
  const r = await fetch('/journal/api' + url, opt);
  if (r.status === 401) { location.href = '/journal/login'; throw new Error('login'); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `伺服器錯誤 ${r.status}`);
  return data;
}

// ---------------------------------------------------------------- state
const state = {
  trades: [], reviews: {}, settings: {}, sync: {}, store: 'memory', ai: false, loaded: false,
  unit: lsGet('unit', 'R'),
  route: { page: 'overview', params: [] },
  tr: { tab: 'all', range: 'all', sort: 'newest', q: '', setup: '', side: '', cond: '', emo: '', source: '', showFilter: false, deleted: false, select: false, picked: new Set(), only: null },
  ov: { period: 'month' },
  cal: { month: null, day: null },
  an: { tab: 'overview', period: '90', metric: 'avg' },
  drawer: null,
};
function lsGet(k, d) { try { const v = localStorage.getItem('jr_' + k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } }
function lsSet(k, v) { try { localStorage.setItem('jr_' + k, JSON.stringify(v)); } catch (_) { } }
function lsDel(k) { try { localStorage.removeItem('jr_' + k); } catch (_) { } }

function setUnit(u) { state.unit = u; lsSet('unit', u); render(); }
function unitSeg(extraCls = '') {
  return h('div', { class: 'seg ' + extraCls, role: 'group', 'aria-label': '盈虧顯示' },
    [['R', 'R'], ['U', '盈虧']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(state.unit === v), onclick: () => setUnit(v) }, l)));
}

// ---------------------------------------------------------------- tags
const COLOR_VAR = { red: 'var(--c-red)', blue: 'var(--c-blue)', green: 'var(--c-green)', yellow: 'var(--c-yellow)', purple: 'var(--c-purple)', orange: 'var(--c-orange)', gray: 'var(--c-gray)' };
const COLOR_NAMES = { red: '紅', blue: '藍', green: '綠', yellow: '黃', purple: '紫', orange: '橘', gray: '灰' };
const condList = () => (state.settings.conditions || []).map((c) => typeof c === 'string' ? { name: c, dir: 'both', color: 'blue' } : c);
const emoList = () => (state.settings.emotions || []).map((e) => typeof e === 'string' ? { name: e, tone: '' } : e);
const condMeta = (name) => condList().find((c) => c.name === name) || { name, dir: 'both', color: 'gray' };
const GOOD_EMO = () => new Set(emoList().filter((e) => e.tone === 'good').map((e) => e.name));

// ---------------------------------------------------------------- coin icon
const COIN_COLORS = { BTC: '#f7931a', ETH: '#627eea', SOL: '#111827', BNB: '#f0b90b', XRP: '#23292f', DOGE: '#c2a633', ADA: '#0033ad', AVAX: '#e84142', LINK: '#2a5ada', TON: '#0098ea', SUI: '#4da2ff', TRX: '#ff060a', LTC: '#345d9d', DOT: '#e6007a' };
function baseOf(sym) { return String(sym || '').toUpperCase().replace(/(USDT|USDC|USD|PERP)$/, '') || '?'; }
function coin(sym, lg) {
  const b = baseOf(sym);
  let color = COIN_COLORS[b];
  if (!color) { let hsh = 0; for (const ch of b) hsh = (hsh * 31 + ch.charCodeAt(0)) % 360; color = `hsl(${hsh} 55% 45%)`; }
  return h('span', { class: 'coin' + (lg ? ' lg' : ''), style: `background:${color}`, 'aria-hidden': 'true' }, b.length > 4 ? b.slice(0, 2) : b.slice(0, 1));
}

// ---------------------------------------------------------------- trade math
const _calcCache = new WeakMap();
function calc(t) {
  const hit = _calcCache.get(t); if (hit) return hit;
  const st = state.settings;
  const dir = t.side === 'short' ? -1 : 1;
  const entry = num(t.entry), sl = num(t.sl), exit = num(t.exit), qty = num(t.qty), lev = num(t.leverage);
  const isOpen = t.status === 'open';
  const stopPct = entry && sl ? Math.abs(entry - sl) / entry * 100 : null;
  let risk = num(t.risk_amount);
  if (!risk && sl && qty && entry) risk = Math.abs(entry - sl) * qty;
  let pnl = num(t.pnl);
  if (pnl == null && !isOpen && t.source !== 'api' && entry && exit && sl && risk) {
    pnl = dir * (exit - entry) / Math.abs(entry - sl) * risk;   // 手動單：盈虧 = R × 風險金額（不含手續費）
  }
  const closed = !isOpen && pnl != null;
  const R = closed && risk ? pnl / risk : null;
  const tps = (t.tps || []).map(num).filter(fin);
  const rr = entry && sl && tps[0] ? Math.abs(tps[0] - entry) / Math.abs(entry - sl) : null;
  const posValue = qty && entry ? qty * entry : (risk && stopPct ? risk / (stopPct / 100) : null);
  const sugPos = (risk || st.defaultRisk) && stopPct ? (risk || st.defaultRisk) / (stopPct / 100) : null;
  const maxLev = stopPct ? Math.floor(100 / (stopPct + 0.5)) : null;
  const sugLev = maxLev ? Math.max(1, Math.floor(maxLev / 2)) : null;
  const margin = posValue && lev ? posValue / lev : null;
  const o = tw(t.open_time), c = tw(t.close_time);
  const holdMin = o && c ? (c.ms - o.ms) / 60000 : null;
  const hasShot = (t.shots || []).length > 0 || (t.tv_links || []).length > 0;
  const hasCond = (t.conditions || []).length > 0;
  const hasEmo = (t.emotions || []).length > 0;
  const needShot = st.requireShot !== false && !hasShot;
  const needR = !risk;
  const pending = !t.deleted_at && (needR || !hasCond || needShot);
  const ses = o ? SESSIONS.find((x) => o.hh >= x.from && o.hh < x.to).k : null;
  const out = { dir, entry, sl, exit, qty, lev, isOpen, closed, stopPct, risk, pnl, R, rr, tps, posValue, sugPos, maxLev, sugLev, margin, o, c, holdMin, hasShot, hasCond, hasEmo, needShot, needR, pending, ses,
    win: closed && pnl > 0, loss: closed && pnl < 0, be: closed && pnl === 0 };
  _calcCache.set(t, out);
  return out;
}
const val = (k, unit = state.unit) => unit === 'R' ? k.R : k.pnl;
const fmtV = (n, unit = state.unit, d = 2) => unit === 'R' ? fmtR(n, d) : fmtU(n, d);
const live = () => state.trades.filter((t) => !t.deleted_at);
const closedOf = (rows) => rows.filter((t) => calc(t).closed);
const byClose = (rows) => rows.slice().sort((a, b) => (calc(a).c?.ms || calc(a).o?.ms || 0) - (calc(b).c?.ms || calc(b).o?.ms || 0));

function agg(rows) {
  const ks = rows.map(calc).filter((k) => k.closed);
  const n = ks.length;
  const out = { n, wins: 0, losses: 0, be: 0, nR: 0 };
  if (!n) return out;
  let gw = 0, gl = 0, rw = 0, rl = 0, totalR = 0, nRw = 0, nRl = 0, totalU = 0;
  for (const k of ks) {
    totalU += k.pnl;
    if (k.pnl > 0) { out.wins++; gw += k.pnl; } else if (k.pnl < 0) { out.losses++; gl -= k.pnl; } else out.be++;
    if (k.R != null) { out.nR++; totalR += k.R; if (k.R > 0) { rw += k.R; nRw++; } else if (k.R < 0) { rl -= k.R; nRl++; } }
  }
  const dec = out.wins + out.losses;
  Object.assign(out, {
    win: dec ? out.wins / dec * 100 : null,
    totalU, avgU: totalU / n, avgWinU: out.wins ? gw / out.wins : null, avgLossU: out.losses ? -gl / out.losses : null,
    pfU: gl > 0 ? gw / gl : (gw > 0 ? Infinity : null),
    totalR: out.nR ? totalR : null, avgR: out.nR ? totalR / out.nR : null, avgWinR: nRw ? rw / nRw : null, avgLossR: nRl ? -rl / nRl : null,
    pfR: rl > 0 ? rw / rl : (rw > 0 ? Infinity : null),
    covR: out.nR / n * 100,
  });
  out.total = (u = state.unit) => u === 'R' ? out.totalR : out.totalU;
  out.avg = (u = state.unit) => u === 'R' ? out.avgR : out.avgU;
  out.pf = (u = state.unit) => u === 'R' ? out.pfR : out.pfU;
  return out;
}

// 依時間篩選
function periodRange(key) {
  const now = Date.now(); const t = todayKey(); const today0 = keyToMs(t);
  const p = tw(new Date().toISOString());
  switch (key) {
    case 'today': return [today0, Infinity];
    case '7': return [now - 7 * 864e5, Infinity];
    case '30': return [now - 30 * 864e5, Infinity];
    case '90': return [now - 90 * 864e5, Infinity];
    case '180': return [now - 180 * 864e5, Infinity];
    case 'month': return [keyToMs(`${p.y}-${pad(p.m)}-01`), Infinity];
    case 'ytd': return [keyToMs(`${p.y}-01-01`), Infinity];
    default: return [-Infinity, Infinity];
  }
}
function inRange(t, [a, b], field = 'close') {
  const k = calc(t); const ms = (field === 'open' ? k.o?.ms : (k.c?.ms ?? k.o?.ms));
  return ms != null && ms >= a && ms < b;
}
function prevRange([a, b]) { if (!Number.isFinite(a)) return null; const end = Number.isFinite(b) ? b : Date.now(); return [a - (end - a), a]; }

// 分組（多選標籤會同時算進多個組）
function groupBy(rows, keyFn) {
  const m = new Map();
  for (const t of rows) { for (const k of [].concat(keyFn(t)).filter((x) => x != null && x !== '')) { if (!m.has(k)) m.set(k, []); m.get(k).push(t); } }
  return [...m.entries()].map(([k, list]) => ({ k, list, ...agg(list) })).filter((g) => g.n > 0);
}
const rankScore = (g, minN = 15) => (g.avgR ?? 0) * Math.min(g.nR / minN, 1);

// ---------------------------------------------------------------- charts
function smoothPath(pts) {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}
let _gid = 0;
// series: [{x(label), y}], opts: {height, smooth, prev:[y...], baseline, labels:[first,last], fmt}
function lineChart(series, opts = {}) {
  const W = 760, H = opts.height || 240, P = { l: opts.axis ? 56 : 6, r: 10, t: 12, b: opts.labels ? 26 : 8 };
  const box = h('div', { class: 'chart-box' });
  if (series.length < 2) { box.append(h('p', { class: 'muted', style: 'font-size:13.5px' }, opts.empty || '資料還不夠畫曲線')); return box; }
  const ys = series.map((p) => p.y).concat(opts.prev || []).concat([opts.baseline ?? 0]);
  let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo -= 1; hi += 1; }
  const padY = (hi - lo) * 0.12; lo -= padY; hi += padY;
  const X = (i, n = series.length) => P.l + i / (n - 1) * (W - P.l - P.r), Y = (v) => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const last = series[series.length - 1].y; const base = opts.baseline ?? 0;
  const col = opts.color || (last >= base ? 'var(--gain)' : 'var(--loss)');
  const gid = 'g' + (++_gid);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', height: H, role: 'img', 'aria-label': opts.label || '曲線圖' },
    s('defs', {}, s('linearGradient', { id: gid, x1: 0, x2: 0, y1: 0, y2: 1 }, s('stop', { offset: '0%', 'stop-color': col, 'stop-opacity': 0.22 }), s('stop', { offset: '100%', 'stop-color': col, 'stop-opacity': 0 }))));
  if (opts.axis) for (let k = 0; k <= 3; k++) { const v = lo + (hi - lo) * k / 3; svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(v), y2: Y(v), stroke: 'var(--line)' }), s('text', { x: P.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, (opts.fmt || fmt)(v))); }
  svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(base), y2: Y(base), stroke: 'var(--muted)', 'stroke-dasharray': '4 5', opacity: 0.6 }));
  if (opts.prev && opts.prev.length > 1) {
    const pp = opts.prev.map((v, i) => [X(i, opts.prev.length), Y(v)]);
    svg.append(s('path', { d: opts.smooth ? smoothPath(pp) : 'M' + pp.map((p) => p.join(',')).join('L'), fill: 'none', stroke: 'var(--muted)', 'stroke-width': 1.5, opacity: 0.55, 'vector-effect': 'non-scaling-stroke' }));
  }
  const pts = series.map((p, i) => [X(i), Y(p.y)]);
  const d = opts.smooth ? smoothPath(pts) : 'M' + pts.map((p) => p.map((v) => v.toFixed(1)).join(',')).join('L');
  svg.append(s('path', { d: d + `L${X(series.length - 1)},${H - P.b}L${X(0)},${H - P.b}Z`, fill: `url(#${gid})` }),
    s('path', { d, fill: 'none', stroke: col, 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke' }),
    s('circle', { cx: X(series.length - 1), cy: Y(last), r: 4, fill: col }));
  if (opts.labels) svg.append(s('text', { x: P.l, y: H - 6 }, opts.labels[0]), s('text', { x: W - P.r, y: H - 6, 'text-anchor': 'end' }, opts.labels[1]));
  const cross = s('line', { y1: P.t, y2: H - P.b, stroke: 'var(--muted)', 'stroke-dasharray': '2 3', visibility: 'hidden' });
  const dot = s('circle', { r: 4.5, fill: 'var(--surface)', stroke: col, 'stroke-width': 2, visibility: 'hidden' });
  svg.append(cross, dot);
  const tip = h('div', { class: 'tip', hidden: true });
  svg.addEventListener('pointermove', (e) => {
    const r = svg.getBoundingClientRect(); const x = (e.clientX - r.left) / r.width * W;
    const i = clamp(Math.round((x - P.l) / (W - P.l - P.r) * (series.length - 1)), 0, series.length - 1);
    const p = series[i];
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(p.y)); dot.setAttribute('visibility', 'visible');
    tip.hidden = false; tip.replaceChildren(h('div', {}, p.x || ''), h('div', { class: 'mono ' + cls(p.y - base) }, (opts.fmt || fmt)(p.y)), p.note ? h('div', { class: 'muted' }, p.note) : null);
    const px = X(i) / W * r.width; tip.style.left = Math.min(Math.max(px - 60, 0), r.width - 160) + 'px'; tip.style.top = '-8px';
  });
  svg.addEventListener('pointerleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
  box.append(svg, tip);
  return box;
}
function cumSeries(rows, unit = state.unit) {
  let cum = 0; const out = [{ x: '起點', y: 0 }];
  for (const t of byClose(closedOf(rows))) { const k = calc(t); const v = val(k, unit); if (v == null) continue; cum += v; out.push({ x: `${fmtDT(t.close_time || t.open_time)} ${t.symbol}`, y: cum, note: fmtV(v, unit) }); }
  return out;
}

// ---------------------------------------------------------------- routing & shell
const NAV = [['overview', '總覽'], ['trades', '紀錄'], ['calendar', '日曆'], ['analytics', '分析'], ['settings', '設定'], ['api', 'API 串接']];
function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  const page = parts[0] || 'overview';
  return { page, params: parts.slice(1) };
}
function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }
function renderNav() {
  const nav = $('#nav'); nav.replaceChildren();
  const cur = state.route.page === 'edit' || state.route.page === 'new' ? 'trades' : state.route.page;
  for (const [k, l] of NAV) nav.append(h('a', { href: `#/${k}`, 'aria-current': cur === k ? 'page' : null }, icon(k === 'api' ? 'api' : k, 21), l));
  nav.append(h('a', { href: '#/new', class: 'new-btn' }, icon('plus', 18), '新增交易'));
  $('#meName').textContent = state.settings.displayName || '';
}
$('#menuBtn').addEventListener('click', () => { const sd = $('#side'); const open = sd.classList.toggle('open'); $('#menuBtn').setAttribute('aria-expanded', String(open)); });
window.addEventListener('hashchange', () => { $('#side').classList.remove('open'); state.route = parseRoute(); if (state.drawer && !['trades', 'overview', 'calendar', 'analytics'].includes(state.route.page)) closeDrawer(); render(); window.scrollTo(0, 0); });

const PAGES = {};
function render() {
  applyAppearance();
  renderNav();
  const main = $('#main');
  const page = h('div', { class: 'page' });
  if (!state.loaded) { page.append(h('div', { class: 'loading' }, '載入中…')); main.replaceChildren(page); return; }
  const fn = PAGES[state.route.page] || PAGES.overview;
  try { fn(page, state.route.params); } catch (e) { console.error(e); page.append(h('div', { class: 'banner err' }, '畫面出錯了：' + e.message)); }
  main.replaceChildren(page);
}
function applyAppearance() {
  const st = state.settings;
  document.documentElement.dataset.updown = st.colorMode === 'redUp' ? 'red' : 'green';
  const th = lsGet('theme', 'auto');
  if (th === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = th;
}

// 共用：頁首
function pageHead(eyebrow, title, opts = {}) {
  return h('div', { class: 'ph' },
    h('div', {}, eyebrow ? h('div', { class: 'eyebrow' }, eyebrow) : null, h('h1', {}, title, opts.count != null ? h('small', {}, opts.count) : null), opts.sub ? h('div', { class: 'sub' }, opts.sub) : null),
    opts.actions ? h('div', { class: 'actions' }, opts.actions) : null);
}
function syncButton() {
  const running = state.sync.running;
  const b = h('button', { class: 'btn', type: 'button', disabled: running || null, onclick: () => doSync(false) }, (() => { const i = icon('sync', 18); if (running) i.classList.add('spin'); return i; })(), running ? '同步中…' : '同步最新交易');
  if (!state.sync.has_keys) b.title = '還沒設定 BingX API 金鑰';
  return b;
}
async function doSync(full) {
  if (!state.sync.has_keys) { toast('還沒設定 BingX API 金鑰，請看「API 串接」頁'); go('#/api'); return; }
  try { state.sync = await api('POST', '/sync', { full }); render(); pollSync(); } catch (e) { toast(e.message); }
}
let _pollT = null;
function pollSync() {
  clearTimeout(_pollT);
  _pollT = setTimeout(async () => {
    try {
      const st = await api('GET', '/sync-status');
      const was = state.sync.running; state.sync = st;
      if (st.running) { render(); pollSync(); return; }
      if (was) { await reload(); toast(st.ok ? `同步完成：新增 ${st.added || 0} 筆、更新 ${st.updated || 0} 筆` : '同步失敗：' + (st.error || '')); }
    } catch (_) { }
  }, 2500);
}
async function reload() {
  const d = await api('GET', '/bootstrap');
  state.trades = d.trades; state.reviews = d.reviews; state.settings = d.settings; state.defaults = d.defaults || {}; state.sync = d.sync; state.store = d.store; state.ai = d.ai; state.loaded = true;
  render();
  if (state.drawer) renderDrawer();
  if (d.sync.running) pollSync();
}
function replaceTrade(t) {
  const i = state.trades.findIndex((x) => x.id === t.id);
  if (i >= 0) state.trades[i] = t; else state.trades.unshift(t);
}
function pendingBanner() {
  const pend = live().filter((t) => calc(t).pending);
  if (!pend.length) return null;
  const noShot = pend.filter((t) => calc(t).needShot);
  const first = (noShot[0] || pend[0]);
  const text = noShot.length ? `${noShot.length} 筆交易待補盤面快照` : `${pend.length} 筆交易待補完`;
  return h('div', { class: 'banner' }, h('span', {}, `${text} · ${first.symbol} · ${first.side === 'short' ? 'SHORT' : 'LONG'}`), h('span', { class: 'spacer' }),
    h('a', { href: '#/trades/pending' }, '查看待補交易'));
}
