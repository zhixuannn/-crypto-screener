/* 績效：資金曲線、回撤、拆解、策略健康度（真實下單／紙上驗證／綜合） */
'use strict';

NAV.splice(NAV.findIndex(([k]) => k === 'analytics') + 1, 0, ['perf', '績效']);
ICONS.perf = '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-7"/><path d="M16 7h4v4"/>';

state.pf = { mode: lsGet('pf_mode', 'real'), range: lsGet('pf_range', 'all'), from: '', to: '', tab: 'asset', group: lsGet('pf_group', 'setup') };
state.paper = null; state.paperRisk = 10; state.paperLoading = false;

const PF_MODES = [['real', '真實下單'], ['all', '綜合模式'], ['paper', '紙上驗證']];
const PF_RANGES = [['week', '本週'], ['month', '本月'], ['30', '近 30 天'], ['90', '近 90 天'], ['all', '全部'], ['custom', '自訂']];
const PF_TABS = [['asset', '資產表現'], ['side', '多空比較'], ['wd', '星期別表現'], ['ses', '時段表現'], ['month', '月報酬熱力圖']];
const fmtMoney = (n, d = 2) => !fin(n) ? '—' : (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtMoneyS = (n, d = 2) => !fin(n) ? '—' : (n > 0 ? '+' : n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPctS = (n, d = 2) => !fin(n) ? '—' : (n > 0 ? '+' : n < 0 ? '-' : '') + Math.abs(n).toFixed(d) + '%';

async function loadPaper(force) {
  if (state.paperLoading || (state.paper && !force)) return;
  state.paperLoading = true;
  try { const d = await api('GET', '/paper'); state.paper = d.trades || []; state.paperRisk = d.risk || 10; }
  catch (e) { toast('紙上單載入失敗：' + e.message); state.paper = state.paper || []; }
  state.paperLoading = false;
  if (state.route.page === 'perf') render();
}

function pfRange(st) {
  const now = Date.now();
  if (st.range === 'week') { const p = tw(new Date().toISOString()); const mon = keyToMs(p.key) - ((p.dow + 6) % 7) * 864e5; return [mon, Infinity]; }
  if (st.range === 'custom') return [st.from ? keyToMs(st.from) : -Infinity, st.to ? keyToMs(st.to) + 864e5 : Infinity];
  if (st.range === '30' || st.range === '90') return [now - Number(st.range) * 864e5, Infinity];
  return periodRange(st.range);
}
const pfShow = (list) => { const real = list.filter((t) => t.source !== 'paper'); if (real.length) showTrades(real); else toast('紙上單沒有個別紀錄頁，可以看下面的「持倉中的紙上單」'); };
const closeMs = (t) => calc(t).c?.ms ?? calc(t).o?.ms;
const tp1Hit = (t) => {
  if (t.source === 'paper') return (t.raw || {}).exit_reason === 'tp';
  const k = calc(t); const tp1 = k.tps[0];
  return fin(tp1) && fin(k.exit) ? k.dir * (k.exit - tp1) >= 0 : null;
};

PAGES.perf = (page) => {
  const st = state.pf;
  const needPaper = st.mode !== 'real';
  if (needPaper && !state.paper) loadPaper();
  const real = live().filter((t) => t.source !== 'paper');
  const paperAll = (state.paper || []).filter((t) => !t.deleted_at);
  const pool = st.mode === 'real' ? real : st.mode === 'paper' ? paperAll : real.concat(paperAll);
  const closedAll = byClose(pool.filter((t) => calc(t).closed && fin(calc(t).pnl)));
  const rng = pfRange(st);
  const inR = closedAll.filter((t) => { const ms = closeMs(t); return ms != null && ms >= rng[0] && ms < rng[1]; });
  const capital = num(state.settings.capital) || 1000;
  const startEq = capital + closedAll.filter((t) => closeMs(t) < rng[0]).reduce((a, t) => a + calc(t).pnl, 0);

  // ---- 頁首
  page.append(h('div', { class: 'ph' },
    h('div', {}, h('div', { class: 'eyebrow' }, 'Performance'), h('h1', {}, '績效分析'),
      h('div', { class: 'sub' }, '總結 → 曲線 → 拆解 → 健康')),
    st.mode !== 'real' ? h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: async (e) => {
      e.currentTarget.disabled = true;
      try { const r = await api('POST', '/paper/settle'); await loadPaper(true); toast(r.closed ? `結算了 ${r.closed} 筆紙上單` : '目前沒有新碰到止盈／停損的紙上單'); } catch (er) { toast(er.message); }
    } }, icon('sync', 18), '立即結算紙上單')) : null));

  page.append(h('nav', { class: 'tabs pf-modes', 'aria-label': '資料模式' }, PF_MODES.map(([k, l]) => h('button', { type: 'button', 'aria-selected': String(st.mode === k), onclick: () => { st.mode = k; lsSet('pf_mode', k); render(); } }, l))));
  const modeNote = {
    real: '你在 BingX 的真實成交（自動同步）加上手動／匯入的交易。',
    paper: `掃描網站和 TradingView 警報的 XUAN 3+1 訊號，假設每筆都有下單：每筆固定風險 ${fmt(state.paperRisk)}U，碰到止盈 +1R、停損 −1R（同一根 K 棒都碰到算停損），已扣手續費。`,
    all: '真實下單＋紙上驗證加在一起看。紙上單的盈虧是假設的，判斷時記得分開看。',
  }[st.mode];

  const rangeBar = h('div', { class: 'pf-range' },
    h('span', { class: 'lbl' }, '時間區段'),
    h('div', { class: 'seg boxed' }, PF_RANGES.map(([k, l]) => h('button', { type: 'button', 'aria-pressed': String(st.range === k), onclick: () => { st.range = k; lsSet('pf_range', k); render(); } }, l))),
    st.range === 'custom' ? h('span', { class: 'pf-dates' },
      h('input', { type: 'date', class: 'sm', value: st.from, 'aria-label': '開始日期', onchange: (e) => { st.from = e.target.value; render(); } }), '～',
      h('input', { type: 'date', class: 'sm', value: st.to, 'aria-label': '結束日期', onchange: (e) => { st.to = e.target.value; render(); } })) : null);
  const openPaper = paperAll.filter((t) => t.status === 'open').length;
  const first = inR[0], last = inR[inR.length - 1];
  const span = first ? `${tw(first.close_time || first.open_time).m}/${tw(first.close_time || first.open_time).d} – ${tw(last.close_time || last.open_time).m}/${tw(last.close_time || last.open_time).d}` : '這段期間';
  const a = agg(inR);
  rangeBar.append(h('span', { class: 'pf-sum' }, `${span} · ${inR.length} 筆已結算`,
    st.mode !== 'paper' && a.n ? ` · R 資料 ${a.nR}/${a.n}` : '', st.mode !== 'real' ? ` · 紙上持倉中 ${openPaper} 筆` : ''));
  page.append(h('p', { class: 'pf-note' }, modeNote), rangeBar);

  if (needPaper && !state.paper) { page.append(h('div', { class: 'loading' }, '載入紙上單…')); return; }
  if (!inR.length) {
    page.append(h('div', { class: 'empty' }, h('strong', {}, st.mode === 'paper' && !paperAll.length ? '還沒有紙上單' : '這段期間還沒有已結算的交易'),
      h('span', {}, st.mode === 'paper' && !paperAll.length ? '掃描網站或 TradingView 警報抓到 XUAN 3+1 訊號後，這裡會自動出現，碰到止盈或停損就結算。' : '換個時間區段看看。')));
    if (st.mode === 'paper' && openPaper) page.append(pfOpenList(paperAll.filter((t) => t.status === 'open')));
    return;
  }

  // ---- 權益序列
  let eq = startEq, peak = startEq, mdd = 0, mddAt = 0, hiV = startEq, hiAt = 0;
  const pts = [{ x: '區間起點', y: startEq, dd: 0 }];
  for (const t of inR) {
    const k = calc(t); eq += k.pnl; peak = Math.max(peak, eq);
    const dd = peak > 0 ? (eq - peak) / peak * 100 : 0;
    pts.push({ x: `${fmtDT(t.close_time || t.open_time)} ${baseOf(t.symbol)}`, y: eq, dd, note: fmtMoneyS(k.pnl) });
    if (dd < mdd) { mdd = dd; mddAt = pts.length - 1; }
    if (eq > hiV) { hiV = eq; hiAt = pts.length - 1; }
  }
  const ret = startEq ? (eq - startEq) / startEq * 100 : null;

  // ---- 六張數字卡
  page.append(h('div', { class: 'pf-kpis' },
    pfKpi('報酬率（此區間）', fmtPctS(ret), cls(ret)),
    pfKpi(`勝率（${a.wins} 勝 / ${a.losses} 敗）`, fmtPct(a.win), ''),
    pfKpi('平均 R', a.nR ? fmtR(a.avgR, 4) : '—', cls(a.avgR)),
    pfKpi('R 合計', a.nR ? fmtR(a.totalR) : '—', cls(a.totalR)),
    pfKpi('最大回撤 MDD', fmtPctS(mdd), mdd < 0 ? 'loss' : ''),
    pfKpi('區間結束權益', fmtMoney(eq), '')));

  // ---- 資金與回撤
  const sec = h('section', { class: 'card pf-curve' },
    h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '資金與回撤 ', h('small', { class: 'pf-en' }, 'EQUITY · DRAWDOWN')))));
  sec.append(pfEquityChart(pts, startEq, hiAt, hiV),
    h('div', { class: 'pf-legend' }, h('span', { class: 'ln eq' }), '資金曲線', h('span', { class: 'ln base' }), '區間起始基準',
      h('span', { class: 'muted' }, `最高點 ${fmtMoney(hiV)} · 期末 ${fmtMoney(eq)}（${fmtPctS(ret)}）`)));
  sec.append(h('div', { class: 'pf-ddhead' }, h('span', {}, h('strong', {}, '最大回撤'), h('small', { class: 'pf-en' }, ' MDD · 此區間最深')), h('strong', { class: 'loss mono' }, fmtPctS(mdd))),
    pfDDChart(pts, mdd, mddAt),
    h('div', { class: 'pf-legend' }, h('span', { class: 'ln dd' }), '從最高點往下掉多少（0% 在上，越往下越深）', h('span', { class: 'muted' }, '回撤＝當下權益相對最高點的跌幅')));
  page.append(sec);

  // ---- 績效拆解
  const tab = st.tab;
  const bd = h('section', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '績效拆解 ', h('small', { class: 'pf-en' }, 'BREAKDOWN')))),
    h('nav', { class: 'tabs', 'aria-label': '拆解分頁' }, PF_TABS.map(([k, l]) => h('button', { type: 'button', 'aria-selected': String(tab === k), onclick: () => { st.tab = k; render(); } }, l))));
  const body = h('div', { class: 'pf-bd' });
  if (tab === 'asset') body.append(pfTable('幣別', groupBy(inR, (t) => baseOf(t.symbol)).sort((x, y) => y.n - x.n || y.totalU - x.totalU), true));
  if (tab === 'side') body.append(pfSide(inR));
  if (tab === 'wd') { const order = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']; body.append(pfTable('星期', groupBy(inR, (t) => { const o = calc(t).o; return o ? '週' + WD[o.dow] : null; }).sort((x, y) => order.indexOf(x.k) - order.indexOf(y.k)))); }
  if (tab === 'ses') body.append(pfTable('時段', groupBy(inR, (t) => { const k = calc(t); return k.ses == null ? null : SESSIONS[k.ses].name; }).sort((x, y) => SESSIONS.findIndex((S) => S.name === x.k) - SESSIONS.findIndex((S) => S.name === y.k)), false, (k) => `${k}（${SESSIONS.find((S) => S.name === k).range}）`));
  if (tab === 'month') body.append(pfHeat(closedAll, capital));
  bd.append(body);
  page.append(bd);

  // ---- 策略健康度
  page.append(pfHealth(inR, st));
  if (st.mode !== 'real' && openPaper) page.append(pfOpenList(paperAll.filter((t) => t.status === 'open')));
};

function pfKpi(label, value, c) { return h('div', { class: 'pf-kpi' }, h('div', { class: 'k' }, label), h('div', { class: 'v mono ' + (c || '') }, value)); }

// ---------------------------------------------------------------- 圖：資金曲線
function pfEquityChart(pts, base, hiAt, hiV) {
  const W = 760, H = 250, P = { l: 66, r: 14, t: 18, b: 10 };
  const ys = pts.map((p) => p.y).concat([base]);
  let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const n = pts.length; const X = (i) => P.l + (n === 1 ? 0 : i / (n - 1)) * (W - P.l - P.r); const Y = (v) => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const box = h('div', { class: 'chart-box' });
  const svg = s('svg', { class: 'chart pf-svg', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', height: H, role: 'img', 'aria-label': '資金曲線' },
    s('defs', {}, s('linearGradient', { id: 'pfEq', x1: 0, x2: 0, y1: 0, y2: 1 }, s('stop', { offset: '0%', 'stop-color': 'var(--pf-eq)', 'stop-opacity': 0.28 }), s('stop', { offset: '100%', 'stop-color': 'var(--pf-eq)', 'stop-opacity': 0.02 }))));
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(v), y2: Y(v), stroke: 'var(--line)' }), s('text', { x: P.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, Math.round(v).toLocaleString('en-US'))); }
  svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(base), y2: Y(base), stroke: 'var(--muted)', 'stroke-dasharray': '4 5' }),
    s('text', { x: W - P.r, y: Y(base) - 6, 'text-anchor': 'end', class: 'pf-lbl' }, `區間起始 ${Math.round(base).toLocaleString('en-US')}`));
  const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`);
  svg.append(s('path', { d: `M${line.join('L')}L${X(n - 1)},${H - P.b}L${X(0)},${H - P.b}Z`, fill: 'url(#pfEq)' }),
    s('path', { d: 'M' + line.join('L'), fill: 'none', stroke: 'var(--pf-eq)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke' }),
    s('circle', { cx: X(n - 1), cy: Y(pts[n - 1].y), r: 4, fill: 'var(--pf-eq)' }));
  if (hiAt > 0) svg.append(s('text', { x: X(hiAt), y: Y(hiV) - 7, 'text-anchor': hiAt > n * 0.8 ? 'end' : 'middle', class: 'pf-lbl' }, `最高 ${Math.round(hiV).toLocaleString('en-US')}`));
  pfHover(svg, box, pts, X, Y, W, (p) => [p.x, h('div', { class: 'mono' }, fmtMoney(p.y)), p.note ? h('div', { class: 'muted' }, `這筆 ${p.note}`) : null]);
  box.prepend(svg);
  return box;
}

// ---------------------------------------------------------------- 圖：回撤（0% 在上）
function pfDDChart(pts, mdd, mddAt) {
  const W = 760, H = 130, P = { l: 66, r: 14, t: 10, b: 10 };
  const lo = Math.min(mdd, -0.5) * 1.12;
  const n = pts.length; const X = (i) => P.l + (n === 1 ? 0 : i / (n - 1)) * (W - P.l - P.r); const Y = (v) => P.t + (0 - v) / (0 - lo) * (H - P.t - P.b);
  const box = h('div', { class: 'chart-box' });
  const svg = s('svg', { class: 'chart pf-svg', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', height: H, role: 'img', 'aria-label': '回撤圖' });
  svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(0), y2: Y(0), stroke: 'var(--line)' }), s('text', { x: P.l - 8, y: Y(0) + 4, 'text-anchor': 'end' }, '0%'),
    s('line', { x1: P.l, x2: W - P.r, y1: Y(mdd), y2: Y(mdd), stroke: 'var(--line)', 'stroke-dasharray': '3 4' }), s('text', { x: P.l - 8, y: Y(mdd) + 4, 'text-anchor': 'end' }, fmtPctS(mdd, 1)));
  const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p.dd).toFixed(1)}`);
  svg.append(s('path', { d: `M${X(0)},${Y(0)}L${line.join('L')}L${X(n - 1)},${Y(0)}Z`, fill: 'var(--loss)', 'fill-opacity': 0.16 }),
    s('path', { d: 'M' + line.join('L'), fill: 'none', stroke: 'var(--loss)', 'stroke-width': 1.6, 'vector-effect': 'non-scaling-stroke' }));
  if (mdd < 0) svg.append(s('circle', { cx: X(mddAt), cy: Y(mdd), r: 3.5, fill: 'var(--loss)' }),
    s('text', { x: X(mddAt), y: Math.min(Y(mdd) + 16, H - 2), 'text-anchor': mddAt > n * 0.8 ? 'end' : 'middle', class: 'pf-lbl loss' }, `最深 ${fmtPctS(mdd)}`));
  pfHover(svg, box, pts, X, Y, W, (p) => [p.x, h('div', { class: 'mono loss' }, fmtPctS(p.dd))], 'dd');
  box.prepend(svg);
  return box;
}

function pfHover(svg, box, pts, X, Y, W, content, key = 'y') {
  const cross = s('line', { y1: 0, y2: 400, stroke: 'var(--muted)', 'stroke-dasharray': '2 3', visibility: 'hidden' });
  const dot = s('circle', { r: 4.5, fill: 'var(--surface)', stroke: 'var(--muted)', 'stroke-width': 2, visibility: 'hidden' });
  svg.append(cross, dot);
  const tip = h('div', { class: 'tip', hidden: true });
  svg.addEventListener('pointermove', (e) => {
    const r = svg.getBoundingClientRect(); const x = (e.clientX - r.left) / r.width * W;
    let i = 0, best = 1e9; for (let j = 0; j < pts.length; j++) { const d = Math.abs(X(j) - x); if (d < best) { best = d; i = j; } }
    const p = pts[i];
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(p[key])); dot.setAttribute('visibility', 'visible');
    tip.hidden = false; tip.replaceChildren(...content(p).filter(Boolean).map((c) => c instanceof Node ? c : h('div', {}, c)));
    const px = X(i) / W * r.width; tip.style.left = Math.min(Math.max(px - 70, 0), r.width - 170) + 'px'; tip.style.top = '-8px';
  });
  svg.addEventListener('pointerleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
  box.append(tip);
}

// ---------------------------------------------------------------- 拆解
function pfTable(label, groups, withCoin, nameFn) {
  if (!groups.length) return h('p', { class: 'muted' }, '沒有資料');
  const maxAbs = Math.max(...groups.map((g) => Math.abs(g.totalU)), 1e-9);
  return h('div', { class: 'tbl-wrap' }, h('table', { class: 't pf-t' },
    h('thead', {}, h('tr', {}, h('th', {}, label), ['筆數', '勝率', '平均 R', '淨損益'].map((x) => h('th', { class: 'n' }, x)), h('th', { class: 'pf-contrib-h' }, '貢獻'))),
    h('tbody', {}, groups.map((g) => {
      const w = Math.abs(g.totalU) / maxAbs * 50;
      return h('tr', { class: 'clickable', onclick: () => pfShow(g.list), title: '查看這些交易' },
        h('td', {}, withCoin ? h('span', { class: 'pf-sym' }, coin(g.k), g.k) : (nameFn ? nameFn(g.k) : g.k)),
        h('td', { class: 'n mono' }, g.n), h('td', { class: 'n mono' }, fmtPct(g.win)),
        h('td', { class: 'n mono ' + cls(g.avgR) }, g.nR ? fmtR(g.avgR) : '—'),
        h('td', { class: 'n mono ' + cls(g.totalU) }, fmtMoneyS(g.totalU)),
        h('td', { class: 'pf-contrib' }, h('span', { class: 'mid' }), h('span', { class: 'bar ' + (g.totalU >= 0 ? 'pos' : 'neg'), style: g.totalU >= 0 ? `left:50%;width:${w}%` : `right:50%;width:${w}%` })));
    }))));
}
function pfSide(rows) {
  const card = (name, list) => {
    const g = agg(list);
    return h('div', { class: 'pf-sidecard' }, h('h3', {}, name, h('small', { class: 'muted' }, ` ${g.n} 筆`)),
      g.n ? h('div', { class: 'metrics one' },
        h('div', {}, h('span', {}, '勝率'), h('span', {}, fmtPct(g.win), h('small', {}, `${g.wins}W ${g.losses}L`))),
        h('div', {}, h('span', {}, '平均 R'), h('span', { class: cls(g.avgR) }, g.nR ? fmtR(g.avgR) : '—')),
        h('div', {}, h('span', {}, 'R 合計'), h('span', { class: cls(g.totalR) }, g.nR ? fmtR(g.totalR) : '—')),
        h('div', {}, h('span', {}, '淨損益'), h('span', { class: cls(g.totalU) }, fmtMoneyS(g.totalU))),
        h('div', {}, h('span', {}, 'Profit Factor'), h('span', {}, fmtPF(g.pfU)))) : h('p', { class: 'muted' }, '這段期間沒有'));
  };
  return h('div', { class: 'grid2' }, card('做多', rows.filter((t) => t.side !== 'short')), card('做空', rows.filter((t) => t.side === 'short')));
}
function pfHeat(closedAll, capital) {
  const byMonth = new Map(); let eq = capital; const startEqOf = new Map();
  for (const t of closedAll) {
    const c = tw(t.close_time || t.open_time); if (!c) continue;
    if (!startEqOf.has(c.mkey)) startEqOf.set(c.mkey, eq);
    byMonth.set(c.mkey, (byMonth.get(c.mkey) || 0) + calc(t).pnl); eq += calc(t).pnl;
  }
  if (!byMonth.size) return h('p', { class: 'muted' }, '沒有資料');
  const years = [...new Set([...byMonth.keys()].map((k) => k.slice(0, 4)))].sort();
  const pct = (k) => byMonth.has(k) ? byMonth.get(k) / startEqOf.get(k) * 100 : null;
  const maxAbs = Math.max(...[...byMonth.keys()].map((k) => Math.abs(pct(k))), 0.01);
  const grid = h('div', { class: 'pf-heat' }, h('span', {}), Array.from({ length: 12 }, (_, i) => h('span', { class: 'hd' }, `${i + 1}月`)), h('span', { class: 'hd' }, '全年'));
  for (const y of years) {
    grid.append(h('span', { class: 'rl' }, y));
    let yr = 0, yrStart = null;
    for (let m = 1; m <= 12; m++) {
      const k = `${y}-${pad(m)}`; const v = pct(k);
      if (v != null) { yr += byMonth.get(k); if (yrStart == null) yrStart = startEqOf.get(k); }
      const a = v == null ? 0 : Math.min(Math.abs(v) / maxAbs, 1);
      grid.append(h('span', { class: 'c', style: v == null ? '' : `background:color-mix(in srgb, ${v >= 0 ? 'var(--gain)' : 'var(--loss)'} ${Math.round(12 + a * 50)}%, var(--surface))`, title: v == null ? '' : `${y}/${m} 盈虧 ${fmtMoneyS(byMonth.get(k))}` },
        v == null ? '' : fmtPctS(v, 1)));
    }
    const yp = yrStart ? yr / yrStart * 100 : null;
    grid.append(h('span', { class: 'c yr mono ' + cls(yp) }, yp == null ? '' : fmtPctS(yp, 1)));
  }
  return h('div', {}, h('div', { class: 'tbl-wrap' }, grid), h('p', { class: 'muted pf-small' }, '每格＝當月盈虧 ÷ 月初權益。顏色越深，賺或賠越多。'));
}

// ---------------------------------------------------------------- 策略健康度
function pfStatus(g) {
  if (g.n < 10) return ['樣本不足', 'few', '此區間樣本少於 10 筆，數字容易被單筆左右，先別下結論。'];
  const avg = g.nR ? g.avgR : null;
  const tpRate = g.tpN ? g.tpHit / g.tpN : null;
  if (avg != null && avg <= -0.1 || (avg == null && g.totalU < 0)) return ['警示', 'bad', '平均每筆在虧錢。先縮小部位或暫停，回頭檢查進場條件和停損位置。'];
  if (tpRate != null && tpRate >= 0.5 && avg != null && avg < 0.2) return ['觀察中', 'watch', 'TP1 觸及率高但平均 R 低，通常代表跑太早，讓單子多跑一點看看。'];
  if (avg != null && avg >= 0.2 && g.totalR > 0) return ['良好', 'good', '目前有正期望值，照計畫繼續做，同時留意樣本會不會變差。'];
  return ['觀察中', 'watch', '還看不出明顯優勢，再多累積幾筆看看。'];
}
function pfHealth(rows, st) {
  const keyFn = st.group === 'setup' ? (t) => t.setup || '未分類策略' : (t) => (t.conditions || []).length ? t.conditions : '未填進場條件';
  const groups = groupBy(rows, keyFn).map((g) => {
    let tpN = 0, tpHit = 0; for (const t of g.list) { const x = tp1Hit(t); if (x != null) { tpN++; if (x) tpHit++; } }
    return Object.assign(g, { tpN, tpHit });
  }).sort((a, b) => b.n - a.n);
  const sec = h('section', { class: 'card' }, h('div', { class: 'card-h' },
    h('div', {}, h('h2', {}, '策略健康度 ', h('small', { class: 'pf-en' }, 'TRADE QUALITY')), h('div', { class: 'desc' }, '依你選的時間區段重算')),
    h('div', { class: 'seg boxed' }, [['setup', '用策略分組'], ['cond', '用進場條件分組']].map(([k, l]) => h('button', { type: 'button', 'aria-pressed': String(st.group === k), onclick: () => { st.group = k; lsSet('pf_group', k); render(); } }, l)))));
  if (!groups.length) { sec.append(h('p', { class: 'muted' }, '沒有資料')); return sec; }
  sec.append(h('div', { class: 'pf-health' }, groups.map((g) => {
    const [label, tone, hint] = pfStatus(g);
    return h('div', { class: 'pf-hc ' + tone },
      h('div', { class: 'pf-hc-h' }, h('div', {}, h('strong', {}, g.k), h('div', { class: 'muted pf-small' }, `${g.n} 筆已結算 · 淨損益 `, h('span', { class: cls(g.totalU) }, fmtMoneyS(g.totalU)))), h('span', { class: 'pf-badge ' + tone }, label)),
      h('div', { class: 'pf-hc-m' },
        pfMini('勝率', fmtPct(g.win)), pfMini('平均 R', g.nR ? fmtR(g.avgR, 3) : '—', cls(g.avgR)), pfMini('R 合計', g.nR ? fmtR(g.totalR) : '—', cls(g.totalR)),
        pfMini('TP1 觸及率', g.tpN ? fmtPct(g.tpHit / g.tpN * 100, 0) : '—', '', g.tpN ? `${g.tpN} 筆有 TP1` : '沒設 TP1')),
      h('p', { class: 'pf-hint' }, hint),
      g.list.some((t) => t.source !== 'paper') ? h('button', { class: 'linkbtn', type: 'button', onclick: () => pfShow(g.list) }, '查看這些交易 →') : null);
  })));
  return sec;
}
function pfMini(k, v, c, sub) { return h('div', {}, h('div', { class: 'k' }, k), h('div', { class: 'v mono ' + (c || '') }, v), sub ? h('div', { class: 'muted pf-small' }, sub) : null); }

function pfOpenList(list) {
  const sorted = list.slice().sort((a, b) => (calc(b).o?.ms || 0) - (calc(a).o?.ms || 0));
  return h('section', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, `持倉中的紙上單 `, h('small', { class: 'muted' }, `${list.length} 筆`)), h('div', { class: 'desc' }, '每 5 分鐘自動檢查一次，碰到止盈或停損就結算'))),
    h('div', { class: 'tbl-wrap' }, h('table', { class: 't pf-t' },
      h('thead', {}, h('tr', {}, ['幣別', '方向', '來源', '進場時間', '進場', '停損', '止盈'].map((x, i) => h('th', { class: i > 3 ? 'n' : '' }, x)))),
      h('tbody', {}, sorted.slice(0, 50).map((t) => h('tr', {},
        h('td', {}, h('span', { class: 'pf-sym' }, coin(t.symbol), baseOf(t.symbol))),
        h('td', { class: t.side === 'short' ? 'loss' : 'gain' }, t.side === 'short' ? '做空' : '做多'),
        h('td', {}, (t.setup || '').replace('XUAN 3+1 · ', '')), h('td', { class: 'mono' }, fmtDT(t.open_time)),
        h('td', { class: 'n mono' }, fmt(num(t.entry), 6)), h('td', { class: 'n mono' }, fmt(num(t.sl), 6)), h('td', { class: 'n mono' }, fmt(num((t.tps || [])[0]), 6))))))));
}
