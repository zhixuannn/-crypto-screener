/* 交易分析：總覽、行為、商品與時段、時段與組合、風險與可信度 */
'use strict';

const AN_TABS = [['overview', '總覽'], ['behavior', '行為'], ['market', '商品與時段'], ['combo', '時段與組合'], ['risk', '風險與可信度']];
const AN_PERIODS = [['30', '近 1 個月'], ['90', '近 3 個月'], ['180', '近 6 個月'], ['ytd', '今年'], ['all', '全部']];
const uName = () => state.unit === 'R' ? 'R' : 'U';
const perN = (v) => fin(v) ? h('span', { class: cls(v) }, fmtV(v), h('small', { style: 'color:var(--muted);font-size:12px' }, '/筆')) : h('span', { class: 'muted' }, '—');
const smallTag = (n, min = 5) => n < min ? h('span', { class: 'small-tag' }, '小樣本') : null;
const sesOf = (t) => { const k = calc(t); return k.ses == null ? null : SESSIONS[k.ses]; };
const dimKey = {
  cond: (t) => t.conditions || [], emo: (t) => t.emotions || [], setup: (t) => t.setup || null,
  wd: (t) => { const o = calc(t).o; return o ? '週' + WD[o.dow] : null; },
  ses: (t) => sesOf(t)?.name || null, side: (t) => t.side === 'short' ? '做空' : '做多', sym: (t) => t.symbol,
};
function showTrades(list) { state._onlyIds = list.map((t) => t.id); go('#/trades/ids'); }

PAGES.analytics = (page, params) => {
  const tab = AN_TABS.some(([k]) => k === params[0]) ? params[0] : 'overview';
  const pk = state.an.period; const rng = periodRange(pk);
  const rows = live().filter((t) => inRange(t, rng));
  const closed = closedOf(rows); const a = agg(rows);
  const noR = closed.filter((t) => calc(t).R == null).length;
  page.append(h('div', { class: 'ph anh' },
    h('div', {}, h('div', { class: 'eyebrow' }, 'Analytics'), h('h1', {}, '交易分析'),
      h('div', { class: 'sub' }, `${AN_PERIODS.find(([k]) => k === pk)[1]} · ${closed.length} 筆已平倉 · R 資料 ${a.nR}/${a.n}`),
      noR ? h('div', { class: 'warn' }, `${noR} 筆尚未填 R，R 相關分析未納入　`, h('a', { href: '#/trades/pending', class: 'amber', style: 'text-decoration:underline' }, '補完 →')) : null),
    h('div', { class: 'actions' }, h('select', { class: 'sm', style: 'width:auto', 'aria-label': '期間', onchange: (e) => { state.an.period = e.target.value; render(); } }, AN_PERIODS.map(([v, l]) => h('option', { value: v, selected: pk === v || null }, l))), unitSeg())));
  page.append(h('nav', { class: 'tabs', 'aria-label': '分析分頁' }, AN_TABS.map(([k, l]) => h('a', { href: `#/analytics/${k}`, 'aria-current': tab === k ? 'page' : null }, l))));
  if (!closed.length) { page.append(h('div', { class: 'empty' }, h('strong', {}, '這段期間還沒有已平倉的交易'), h('span', {}, '換個期間，或先同步／新增交易。'))); return; }
  ({ overview: anOverview, behavior: anBehavior, market: anMarket, combo: anCombo, risk: anRisk })[tab](page, rows, rng, a);
};

// ---------------------------------------------------------------- 共用計算
function ddStats(rows, unit = state.unit) {
  let cum = 0, peak = 0, maxDD = 0, peakMs = null, longest = 0, cw = 0, cl = 0, mw = 0, ml = 0, first = null;
  for (const t of byClose(closedOf(rows))) {
    const k = calc(t); const v = val(k, unit); const ms = k.c?.ms || k.o?.ms;
    if (first == null) { first = ms; peakMs = ms; }
    if (k.pnl > 0) { cw++; cl = 0; mw = Math.max(mw, cw); } else if (k.pnl < 0) { cl++; cw = 0; ml = Math.max(ml, cl); }
    if (!fin(v)) continue;
    cum += v;
    if (cum > peak) { longest = Math.max(longest, (ms - peakMs) / 864e5); peak = cum; peakMs = ms; }
    maxDD = Math.min(maxDD, cum - peak);
  }
  if (peakMs != null) longest = Math.max(longest, (Date.now() - peakMs) / 864e5);
  return { maxDD, curDD: cum - peak, longest: Math.round(longest), mw, ml };
}
function findings(rows) {
  const u = state.unit; const out = [];
  const consider = (dim, label) => {
    const gs = groupBy(rows, dimKey[dim]);
    for (const g of gs) {
      const rest = agg(rows.filter((t) => ![].concat(dimKey[dim](t)).includes(g.k)));
      const gn = u === 'R' ? g.nR : g.n, rn = u === 'R' ? rest.nR : rest.n;
      if (gn < 5 || rn < 5) continue;
      const diff = g.avg(u) - rest.avg(u);
      if (!fin(diff)) continue;
      out.push({ dim, k: g.k, label: label(g.k), g, rest, diff, n: gn, w: diff * Math.min(gn / 15, 1) });
    }
  };
  consider('cond', (k) => `「${k}」`); consider('emo', (k) => `「${k}」`); consider('setup', (k) => `「${k}」`);
  consider('wd', (k) => k); consider('ses', (k) => k); consider('side', (k) => `「${k}」`); consider('sym', (k) => k);
  const tag = ['cond', 'emo', 'setup'];
  const important = out.filter((x) => tag.includes(x.dim)).sort((a, b) => Math.abs(b.w) - Math.abs(a.w))[0];
  const strength = out.filter((x) => x.diff > 0 && x !== important).sort((a, b) => b.w - a.w)[0];
  const leak = out.filter((x) => x.diff < 0 && x !== important).sort((a, b) => a.w - b.w)[0];
  return { important, strength, leak };
}
function findBlock(title, f, periodLabel) {
  if (!f) return h('div', { class: 'find' }, h('div', { class: 'k' }, title), h('div', { class: 'm' }, '樣本還不夠，至少要有 5 筆同類交易才會比較。'));
  const u = state.unit;
  return h('div', { class: 'find' + (f.diff < 0 ? ' neg' : '') }, h('div', { class: 'k' }, title),
    h('div', { class: 't' }, `${f.label} 的每筆期望值${f.diff >= 0 ? '高於' : '低於'}其他交易 ${fmt(Math.abs(f.diff), 2)}${u === 'R' ? 'R' : ' U'}`),
    h('div', { class: 'm' }, `基於 ${f.n} 筆 · ${periodLabel} · ${f.label} ${fmtV(f.g.avg(u))}/筆，其他 ${fmtV(f.rest.avg(u))}/筆${f.n < 15 ? ' · 樣本有限' : ''}`),
    h('button', { class: 'linkbtn', type: 'button', style: 'justify-self:start', onclick: () => showTrades(f.g.list) }, '查看這些交易 →'));
}
function lrowList(groups, opts = {}) {
  const u = state.unit; const minN = opts.minN || 15;
  const sorted = groups.slice().sort((a, b) => (b.avg(u) ?? -1e9) * Math.min((u === 'R' ? b.nR : b.n) / minN, 1) - (a.avg(u) ?? -1e9) * Math.min((u === 'R' ? a.nR : a.n) / minN, 1));
  return h('div', { class: 'lrows' }, sorted.map((g) => h('div', { class: 'lrow' },
    h('div', { style: opts.icon ? 'display:flex;align-items:center;flex-wrap:wrap' : '' }, opts.icon ? opts.icon(g.k) : null, h('span', { style: opts.icon ? 'margin-left:10px' : '' }, g.k), h('span', { class: 'n' }, `N=${g.n}`), smallTag(g.n), u === 'R' && g.nR < g.n ? h('span', { class: 'small-tag' }, 'R 樣本不完整') : null),
    h('span', { class: 'w' }, `${fmtPct(g.win)}（${g.wins}W ${g.losses}L）`),
    h('span', { class: 'r' }, perN(g.avg(u))))));
}
function contribLine(groups) {
  const u = state.unit; const vs = groups.filter((g) => fin(g.total(u)));
  if (!vs.length) return null;
  const best = vs.slice().sort((a, b) => b.total(u) - a.total(u))[0], worst = vs.slice().sort((a, b) => a.total(u) - b.total(u))[0];
  return h('div', { class: 'contrib' }, '貢獻最多：', h('span', { class: 'gain' }, `${best.k} ${fmtV(best.total(u))}`), '　·　拖累最多：', h('span', { class: 'loss' }, `${worst.k} ${fmtV(worst.total(u))}`));
}
const rankNote = '可靠度降權排序（期望值 × min(N/15, 1)），非統計顯著性';

// ---------------------------------------------------------------- 總覽
function anOverview(page, rows, rng, a) {
  const u = state.unit; const pLabel = AN_PERIODS.find(([k]) => k === state.an.period)[1];
  const prev = prevRange(rng); const prows = prev ? live().filter((t) => inRange(t, prev)) : [];
  const pa = agg(prows);
  const days = new Set(closedOf(rows).map((t) => calc(t).c?.key || calc(t).o?.key)).size;
  const series = cumSeries(rows); const pseries = prev ? cumSeries(prows).map((p) => p.y) : null;
  const sorted = byClose(closedOf(rows));
  const dd = ddStats(rows);
  const vsPrev = prev && pa.n ? (a.total(u) ?? 0) - (pa.total(u) ?? 0) : null;
  const left = h('div', { class: 'sec' },
    h('div', { class: 'eyebrow', style: 'font-weight:700;font-size:13.5px;color:var(--ink-2)' }, u === 'R' ? '期間合計 R（已實現）' : '期間合計盈虧（已實現）'),
    h('div', { class: 'bignum ' + cls(a.total(u)), style: 'font-size:clamp(32px,4vw,40px)' }, fmtV(a.total(u))),
    h('div', { class: 'muted' }, `${a.n} 筆 · ${days} 個交易日`, vsPrev != null ? [' · vs 前期 ', h('b', { class: 'mono ' + cls(vsPrev) }, fmtV(vsPrev))] : null),
    lineChart(series, { height: 240, prev: pseries, label: '期間累計', fmt: (v) => fmtV(v), labels: [sorted.length ? fmtDT(sorted[0].close_time).split(' ')[0] : '', sorted.length ? fmtDT(sorted[sorted.length - 1].close_time).split(' ')[0] : ''] }),
    prev ? h('div', { class: 'muted', style: 'font-size:12.5px' }, '灰線 = 前期（等長）') : null);
  const fd = findings(rows);
  const right = h('div', { class: 'sec', style: 'gap:26px' }, findBlock('最重要發現', fd.important, pLabel), findBlock('最強優勢', fd.strength, pLabel), findBlock('最大漏洞', fd.leak, pLabel));
  page.append(h('div', { class: 'split' }, left, right));
  const cov = coverage(rows);
  page.append(h('div', { class: 'divider' }), h('div', { class: 'metrics' },
    h('div', {}, h('span', {}, '每筆期望值'), h('span', { class: cls(a.avg(u)) }, fmtV(a.avg(u)), h('small', {}, `/筆 · ${u === 'R' ? a.nR : a.n} 筆`))),
    h('div', {}, h('span', {}, '勝率'), h('span', {}, fmtPct(a.win), h('small', {}, `${a.wins}W ${a.losses}L`))),
    h('div', {}, h('span', {}, 'Profit Factor'), h('span', {}, fmtPF(a.pf(u)))),
    h('div', {}, h('span', {}, '最大回撤'), h('span', { class: 'loss' }, fmtV(dd.maxDD))),
    h('div', {}, h('span', {}, '平均獲利 / 虧損'), h('span', {}, u === 'R' ? `${fmt(a.avgWinR, 2)} / ${fmt(Math.abs(a.avgLossR ?? NaN), 2)}` : `${fmt(a.avgWinU, 2)} / ${fmt(Math.abs(a.avgLossU ?? NaN), 2)}`)),
    h('div', {}, h('span', {}, '平均 R'), h('span', { class: cls(a.avgR) }, fmtR(a.avgR), h('small', {}, `${a.nR} 筆計 R`)))),
    h('div', { class: 'muted', style: 'font-size:14px' }, `資料可信度：R ${fmtPct(cov.r, 0)} · 情緒 ${fmtPct(cov.emo, 0)} · 條件 ${fmtPct(cov.cond, 0)}　`, h('a', { href: '#/analytics/risk' }, '詳情 →')));
  page.append(radarCard(rows, a));
  page.append(h('div', { class: 'grid2' }, ruleCard(rows), benchCard(rows)));
  page.append(aiCard(rows, a, dd));
}
function coverage(rows) {
  const c = closedOf(rows); const n = c.length || 1;
  return { n: c.length, r: c.filter((t) => calc(t).R != null).length / n * 100, emo: c.filter((t) => (t.emotions || []).length).length / n * 100, cond: c.filter((t) => (t.conditions || []).length).length / n * 100,
    nR: c.filter((t) => calc(t).R != null).length, nEmo: c.filter((t) => (t.emotions || []).length).length, nCond: c.filter((t) => (t.conditions || []).length).length, pnl: c.length };
}
function radarCard(rows, a) {
  const c = byClose(closedOf(rows)); const axes = [];
  // 勝率穩定度
  if (c.length >= 20) {
    const wr = []; for (let i = 0; i + 10 <= c.length; i += 10) { const ch = c.slice(i, i + 10).map(calc); const w = ch.filter((k) => k.pnl > 0).length, l = ch.filter((k) => k.pnl < 0).length; if (w + l) wr.push(w / (w + l) * 100); }
    const m = wr.reduce((x, y) => x + y, 0) / wr.length; const sd = Math.sqrt(wr.reduce((x, y) => x + (y - m) ** 2, 0) / wr.length);
    axes.push({ name: '勝率穩定度', score: clamp(100 - sd * 2, 0, 100), n: c.length });
  } else axes.push({ name: '勝率穩定度', need: 20 - c.length });
  axes.push(a.nR >= 10 ? { name: '平均 R', score: clamp(50 + (a.avgR || 0) * 50, 0, 100), n: a.nR } : { name: '平均 R', need: 10 - a.nR });
  axes.push(a.nR >= 10 && a.avgLossR ? { name: '風險報酬', score: clamp((a.avgWinR || 0) / Math.abs(a.avgLossR) / 2 * 100, 0, 100), n: a.nR } : { name: '風險報酬', need: Math.max(1, 10 - a.nR) });
  axes.push(c.length >= 10 ? { name: '復盤完成率', score: c.filter((t) => !calc(t).pending).length / c.length * 100, n: c.length } : { name: '復盤完成率', need: 10 - c.length });
  const tagged = c.filter((t) => (t.emotions || []).length); const good = GOOD_EMO();
  axes.push(tagged.length >= 10 ? { name: '情緒穩定度', score: tagged.filter((t) => t.emotions.some((e) => good.has(e))).length / tagged.length * 100, n: tagged.length } : { name: '情緒穩定度', need: 10 - tagged.length });
  if (c.length >= 20) { const cnt = [0, 0, 0, 0, 0]; c.forEach((t) => { const k = calc(t); if (k.ses != null) cnt[k.ses]++; }); const top2 = cnt.slice().sort((x, y) => y - x).slice(0, 2).reduce((x, y) => x + y, 0); axes.push({ name: '時段一致性', score: top2 / c.length * 100, n: c.length }); }
  else axes.push({ name: '時段一致性', need: 20 - c.length });
  const W = 420, H = 380, cx = W / 2, cy = H / 2 + 6, R = 130;
  const pt = (i, r) => [cx + r * Math.sin(i / 6 * Math.PI * 2), cy - r * Math.cos(i / 6 * Math.PI * 2)];
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', style: 'max-width:460px;display:block;margin:auto', role: 'img', 'aria-label': '交易能力輪廓雷達圖' });
  for (let lv = 1; lv <= 4; lv++) svg.append(s('polygon', { points: [0, 1, 2, 3, 4, 5].map((i) => pt(i, R * lv / 4).join(',')).join(' '), fill: 'none', stroke: 'var(--line)' }));
  for (let i = 0; i < 6; i++) { const [x, y] = pt(i, R); svg.append(s('line', { x1: cx, y1: cy, x2: x, y2: y, stroke: 'var(--line)' })); const [lx, ly] = pt(i, R + 26); svg.append(s('text', { x: lx, y: ly + 5, 'text-anchor': 'middle', style: 'font-family:var(--font);font-size:14px;fill:var(--ink)' }, axes[i].name)); }
  const ev = axes.map((ax, i) => ({ ax, i })).filter((x) => x.ax.score != null);
  if (ev.length >= 2) svg.append(s('polygon', { points: ev.map(({ ax, i }) => pt(i, R * ax.score / 100).join(',')).join(' '), fill: 'color-mix(in srgb, var(--accent) 12%, transparent)', stroke: 'var(--accent)', 'stroke-width': 2 }));
  axes.forEach((ax, i) => { if (ax.score != null) { const [x, y] = pt(i, R * ax.score / 100); svg.append(s('circle', { cx: x, cy: y, r: 5, fill: 'var(--accent)' })); } else { const [x, y] = pt(i, R); svg.append(s('circle', { cx: x, cy: y, r: 6, fill: 'none', stroke: 'var(--muted)', 'stroke-dasharray': '2 2' })); } });
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '交易能力輪廓'), h('div', { class: 'desc' }, '這是輔助參考的輪廓，分數是用你的紀錄自動算的，不是正式評分。'),
    axes.some((x) => x.score == null) ? h('div', { class: 'hint' }, '目前只能建立部分輪廓；未評估的軸不納入面積。') : null), h('span', { class: 'badge amber' }, '輔助參考')),
    h('div', { class: 'radarwrap' }, svg, h('div', { class: 'axes' }, axes.map((ax) => h('div', { class: 'ax' }, h('b', {}, ax.name), ax.score != null ? h('span', {}, `${ax.score.toFixed(1)}/100 · N=${ax.n}`) : h('span', { class: 'na' }, `未評估 · 尚差 ${ax.need} 筆`))))));
}
function ruleCard(rows) {
  const gs = groupBy(rows, (t) => t.followed_rules === false ? '沒照規則' : t.followed_rules === true ? '照規則' : '沒標記');
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '照規則 vs 沒照規則'), h('div', { class: 'desc' }, '「沒照規則」明顯比較差，就代表規則是有用的。'))), gs.length ? lrowList(gs, { minN: 10 }) : h('div', { class: 'muted' }, '在編輯頁標記「這筆有照規則嗎」後就會出現。'));
}
function benchCard(rows) {
  const bm = state.settings.benchmarks || []; const u = state.unit;
  const items = bm.map((b) => ({ b, a: agg(rows.filter((t) => t.setup === b.setup)) })).filter((x) => x.a.n);
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '實盤 vs 回測'), h('div', { class: 'desc' }, '回測數字可以在「設定」修改；累積 30 筆以上比較才有意義。'))),
    items.length ? h('div', { class: 'tbl-wrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, h('th', {}, '策略'), h('th', { class: 'n' }, '筆數'), h('th', { class: 'n' }, '勝率 實盤/回測'), h('th', { class: 'n' }, 'PF 實盤/回測'))),
      h('tbody', {}, items.map(({ b, a }) => h('tr', {}, h('td', {}, b.setup), h('td', { class: 'n' }, a.n), h('td', { class: 'n' }, `${fmtPct(a.win)} / ${fmtPct(b.win)}`), h('td', { class: 'n ' + ((a.pf(u) ?? 0) >= b.pf ? 'gain' : 'loss') }, `${fmtPF(a.pf(u))} / ${fmtPF(b.pf)}`)))))) : h('div', { class: 'muted' }, '在交易裡選擇策略（例如「雙訂單塊 掛單回踩」）後就會出現。'));
}
function aiCard(rows, a, dd) {
  const card = h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, 'AI 復盤'), h('div', { class: 'desc' }, '把這段期間最近 60 筆已平倉交易交給 AI，用簡單的話告訴你哪裡做得好、哪裡要改。'))));
  if (!state.ai) { card.append(h('div', { class: 'muted' }, '到 Render 的 Environment 加上 ANTHROPIC_API_KEY 之後就能使用。')); return card; }
  const out = h('div', { class: 'ai-out', hidden: !state._aiText }, state._aiText || '');
  const btn = h('button', { class: 'btn primary', type: 'button' }, icon('spark', 18), state._aiText ? '重新分析' : '請 AI 幫我復盤');
  btn.addEventListener('click', async () => {
    const recent = byClose(closedOf(rows)).slice(-60).map((t) => { const k = calc(t); return { 時間: fmtDT(t.open_time), 幣: t.symbol, 方向: t.side === 'short' ? '空' : '多', 策略: t.setup, 停損pct: k.stopPct && +k.stopPct.toFixed(2), R: k.R != null ? +k.R.toFixed(2) : null, 盈虧U: +k.pnl.toFixed(2), 持倉分: k.holdMin != null ? Math.round(k.holdMin) : null, 條件: t.conditions, 情緒: t.emotions, 犯錯: t.mistakes, 照規則: t.followed_rules, 理由: (t.reason || '').slice(0, 120), 心得: (t.note || '').slice(0, 160) }; });
    const summary = { 筆數: a.n, 勝率: a.win && +a.win.toFixed(1), PF_R: fin(a.pfR) ? +a.pfR.toFixed(2) : null, 總R: a.totalR != null ? +a.totalR.toFixed(2) : null, 淨盈虧U: +a.totalU.toFixed(2), 最大回撤: +dd.maxDD.toFixed(2), 最多連虧: dd.ml };
    const prompt = `你是一位交易教練，請幫一位做加密貨幣合約日內交易的大學生復盤。他用 SMC 的 3+1 進場（CHoCH＋FVG＋BOS＋訂單塊），停損放在前一個訂單塊外面，每筆固定風險，目標勝率 50% 以上、PF 1.2 以上。

請用繁體中文、很口語、小學生也聽得懂的方式回答。不要用 Markdown 符號（不要用 #、*、表格）。用以下段落標題各寫幾句：
整體表現：
做得好的地方：
最常犯的錯：（引用具體筆數或數字）
下次可以改的三件事：（具體、可以照做）
只根據下面的資料，資料不夠就直接說資料不夠。

整體統計：${JSON.stringify(summary)}
最近的交易：${JSON.stringify(recent)}`;
    btn.disabled = true; out.hidden = false; out.textContent = '分析中，大約要 20～60 秒…';
    try { const r = await api('POST', '/ai', { prompt }); state._aiText = r.text; out.textContent = r.text; btn.lastChild.textContent = '重新分析'; }
    catch (e) { out.textContent = e.message; }
    btn.disabled = false;
  });
  card.append(h('div', {}, btn), out);
  return card;
}

// ---------------------------------------------------------------- 行為
function anBehavior(page, rows) {
  const u = state.unit;
  const cg = groupBy(rows, dimKey.cond);
  page.append(h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('h2', {}, '進場條件'), h('span', { class: 'muted', style: 'font-size:12.5px' }, rankNote)),
    h('div', { class: 'desc muted', style: 'font-size:13.5px;margin-top:-6px' }, '條件可多選：同一筆交易會同時算進多個條件，各列不互斥，合計不能直接相加。'),
    cg.length ? [contribLine(cg), lrowList(cg)] : h('div', { class: 'muted' }, '還沒有勾選進場條件的交易。')));
  // 開單狀態 + 連勝連虧後
  const eg = groupBy(rows, dimKey.emo);
  const cov = coverage(rows);
  const seq = byClose(closedOf(rows)); const buckets = {};
  let lw = 0, ll = 0;
  for (const t of seq) {
    const k = calc(t);
    for (const n of [2, 3]) { if (ll >= n) (buckets[`連 ${n} 虧後`] ||= []).push(t); if (lw >= n) (buckets[`連 ${n} 勝後`] ||= []).push(t); }
    if (k.pnl > 0) { lw++; ll = 0; } else if (k.pnl < 0) { ll++; lw = 0; }
  }
  const streakRows = ['連 2 虧後', '連 3 虧後', '連 2 勝後', '連 3 勝後'].map((key) => {
    const list = buckets[key] || []; const g = agg(list); const risks = list.map((t) => calc(t).risk).filter(fin);
    const avgRisk = risks.length ? risks.reduce((x, y) => x + y, 0) / risks.length : null;
    return h('div', { class: 'lrow' }, h('div', {}, h('b', { style: 'font-weight:500' }, key), h('span', { class: 'n' }, `N=${list.length}`), smallTag(list.length)),
      h('span', { class: 'w', style: 'font-family:var(--font)' }, list.length ? `勝率 ${fmtPct(g.win)} · 平均風險 ${fmt(avgRisk, 2)}U（${risks.length} 筆）` : '—'),
      h('span', { class: 'r' }, g.n ? perN(g.avg(u)) : '—'));
  });
  page.append(h('div', { class: 'divider' }), h('div', { class: 'grid2', style: 'gap:40px' },
    h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('h2', {}, '開單狀態'), h('span', { class: 'muted', style: 'font-size:12px' }, '可靠度降權排序')),
      eg.length ? [contribLine(eg), lrowList(eg, { minN: 10 })] : h('div', { class: 'muted' }, '還沒有標記情緒的交易。'),
      h('div', { class: 'muted', style: 'font-size:14px' }, `未標記情緒：約 ${cov.n - cov.nEmo} 筆（情緒覆蓋 ${fmtPct(cov.emo, 0)}）　`, h('a', { href: '#/trades/pending', class: 'amber' }, '補完 →'))),
    h('section', { class: 'sec' }, h('h2', {}, '連勝連虧後的行為'), h('div', { class: 'desc muted', style: 'font-size:13px;margin-top:-6px' }, '「下一筆」＝連續結果確認（平倉）後才新開的交易；平均風險可以看你是不是加碼了（相關不代表因果）。'), h('div', { class: 'lrows' }, streakRows))));
  // 交易頻率
  const perDay = new Map(); for (const t of closedOf(rows)) { const key = calc(t).o?.key; if (!key) continue; if (!perDay.has(key)) perDay.set(key, []); perDay.get(key).push(t); }
  const bins = [['1-2 筆/日', 1, 2], ['3-5 筆/日', 3, 5], ['6-9 筆/日', 6, 9], ['10+ 筆/日', 10, 1e9]];
  page.append(h('div', { class: 'divider' }), h('section', { class: 'sec' }, h('h2', {}, '交易頻率（OVERTRADING）'), h('div', { class: 'desc muted', style: 'font-size:13px;margin-top:-6px' }, '依單日進場筆數分組；筆數少時僅供參考（相關非因果）。'),
    h('div', { class: 'lrows' }, bins.map(([l, lo, hi]) => { const days = [...perDay.values()].filter((v) => v.length >= lo && v.length <= hi); const list = days.flat(); const g = agg(list);
      return h('div', { class: 'lrow', style: list.length ? '' : 'opacity:.45' }, h('div', {}, h('span', {}, l), h('span', { class: 'n', style: 'margin-left:40px' }, `${list.length} 筆 / ${days.length} 天`)), h('span', {}), h('span', { class: 'r' }, g.n ? perN(g.avg(u)) : '—')); }))));
  // 犯錯
  const mg = groupBy(rows, (t) => t.mistakes || []);
  if (mg.length) page.append(h('div', { class: 'divider' }), h('section', { class: 'sec' }, h('h2', {}, '犯錯標籤'), contribLine(mg), lrowList(mg, { minN: 10 })));
  // 持倉時間泡泡圖
  page.append(bubbleCard(rows));
}
function bubbleCard(rows) {
  const u = state.unit;
  const pts = closedOf(rows).map((t) => ({ t, k: calc(t) })).filter((x) => fin(x.k.holdMin) && fin(val(x.k)));
  const card = h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '持倉時間與績效關聯'), h('div', { class: 'desc' }, `每顆泡泡是一筆已平倉交易；縱軸跟著上方 R／盈虧切換。`)), h('span', { class: 'badge' }, `大小：|${u === 'R' ? 'realized R' : '盈虧'}|`)));
  if (pts.length < 3) { card.append(h('div', { class: 'muted' }, '至少要 3 筆有開平倉時間的交易。')); return card; }
  const W = 900, H = 420, P = { l: 70, r: 20, t: 36, b: 44 };
  const holds = pts.map((p) => p.k.holdMin).sort((a, b) => a - b); const p95 = holds[Math.floor(holds.length * 0.95)] || holds[holds.length - 1];
  const xmax = Math.max(60, Math.ceil(Math.max(p95, 60) / 120) * 120);
  const vs = pts.map((p) => val(p.k)); let lo = Math.min(...vs, 0), hi = Math.max(...vs, 0); const pd = (hi - lo) * 0.12 || 1; lo -= pd; hi += pd;
  const mx = Math.max(...vs.map(Math.abs), 1e-9);
  const X = (m) => P.l + Math.min(m, xmax) / xmax * (W - P.l - P.r), Y = (v) => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '持倉時間與績效泡泡圖' });
  svg.append(s('text', { x: P.l + 4, y: 20, style: 'font-family:var(--font);font-size:14px;fill:var(--ink-2)' }, `Y 軸：已實現 ${u === 'R' ? 'R' : '盈虧'}`));
  for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4; svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(v), y2: Y(v), stroke: 'var(--line)' }), s('text', { x: P.l - 10, y: Y(v) + 4, 'text-anchor': 'end' }, u === 'R' ? fmt(v, 1) + 'R' : fmt(v, 1))); }
  for (let i = 0; i <= 4; i++) { const m = xmax * i / 4; svg.append(s('line', { x1: X(m), x2: X(m), y1: P.t, y2: H - P.b, stroke: 'var(--line)' }), s('text', { x: X(m), y: H - 16, 'text-anchor': 'middle' }, `${Math.round(m)} 分`)); }
  const tip = h('div', { class: 'tip', hidden: true });
  for (const p of pts.sort((a, b) => Math.abs(val(b.k)) - Math.abs(val(a.k)))) {
    const v = val(p.k); const r = 5 + Math.abs(v) / mx * 26;
    const c = s('circle', { cx: X(p.k.holdMin), cy: Y(v), r, fill: v > 0 ? 'var(--gain)' : v < 0 ? 'var(--loss)' : 'var(--muted)', 'fill-opacity': 0.72, stroke: 'var(--surface)', 'stroke-width': 1, style: 'cursor:pointer',
      onclick: () => openDrawer(p.t.id, pts.map((x) => x.t.id)) });
    c.addEventListener('pointerenter', () => { tip.hidden = false; tip.replaceChildren(h('div', {}, `${p.t.symbol} · ${fmtDT(p.t.open_time)}`), h('div', { class: 'mono ' + cls(v) }, fmtV(v)), h('div', { class: 'muted' }, `持倉 ${fmtHold(p.k.holdMin)}`)); const rr = svg.getBoundingClientRect(); tip.style.left = Math.min(X(p.k.holdMin) / W * rr.width, rr.width - 170) + 'px'; tip.style.top = Math.max(0, Y(v) / H * rr.height - 70) + 'px'; });
    c.addEventListener('pointerleave', () => { tip.hidden = true; });
    svg.append(c);
  }
  card.append(h('div', { class: 'chart-box' }, svg, tip));
  return card;
}

// ---------------------------------------------------------------- 商品與時段
function metricToggle() {
  return h('div', { class: 'seg boxed', role: 'group', 'aria-label': '指標' }, [['avg', '平均盈虧'], ['win', '勝率']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(state.an.metric === v), onclick: () => { state.an.metric = v; render(); } }, l)));
}
const mVal = (g) => state.an.metric === 'win' ? g.win : g.avg();
const mFmt = (g) => state.an.metric === 'win' ? fmtPct(g.win) : fmtV(g.avg());
const mCls = (g) => state.an.metric === 'win' ? (g.win >= 50 ? 'gain' : 'loss') : cls(g.avg());
function anMarket(page, rows) {
  const closed = closedOf(rows);
  const wd = groupBy(rows, (t) => { const o = calc(t).o; return o ? o.dow : null; });
  const ses = groupBy(rows, (t) => calc(t).ses);
  const valid = (g) => fin(mVal(g));
  const bestW = wd.filter(valid).sort((a, b) => mVal(b) - mVal(a))[0], bestS = ses.filter(valid).sort((a, b) => mVal(b) - mVal(a))[0];
  const worst = [...wd.map((g) => ({ ...g, label: WD[g.k] })), ...ses.map((g) => ({ ...g, label: SESSIONS[g.k].name }))].filter(valid).sort((a, b) => mVal(a) - mVal(b))[0];
  const sc = (k, t, g) => h('div', { class: 'sc' }, h('span', { class: 'k' }, k), h('span', { class: 't' }, t || '—'), g ? h('span', { class: 'v ' + mCls(g) }, mFmt(g)) : h('span', { class: 'v' }, '—'), g ? h('span', { class: 'm' }, `N=${g.n}`, smallTag(g.n)) : null);
  page.append(h('div', { class: 'card soft' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '分析洞察總覽'), h('div', { class: 'desc' }, state.an.metric === 'win' ? '勝率' : `平均盈虧（${uName()}）`)), metricToggle()),
    h('div', { class: 'statcards grid4' }, sc('最佳星期', bestW ? WD[bestW.k] : null, bestW), sc('最佳時段', bestS ? SESSIONS[bestS.k].name : null, bestS), sc('最弱表現', worst?.label, worst),
      h('div', { class: 'sc' }, h('span', { class: 'k' }, '樣本數'), h('span', { class: 't' }, uName() === 'R' ? 'R' : 'PnL'), h('span', { class: 'v' }, uName() === 'R' ? agg(rows).nR : closed.length), h('span', { class: 'm' }, uName() === 'R' ? 'R samples' : 'PnL samples')))));
  page.append(timeScatter(rows));
  const order = [0, 1, 2, 3, 4, 5, 6];
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '星期分析'), h('div', { class: 'desc' }, '依進場時間 · Asia/Taipei')), metricToggle()),
    h('div', { class: 'statcards grid7' }, order.map((d) => { const g = wd.find((x) => x.k === d); return h('div', { class: 'sc' + (g ? '' : ' dim') }, h('span', { class: 't' }, WD[d]), h('span', { class: 'v ' + (g ? mCls(g) : '') }, g ? mFmt(g) : '—'), h('span', { class: 'm' }, g ? `N=${g.n} · ${g.wins}W ${g.losses}L` : 'N=0')); }))));
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '交易時段分析'), h('div', { class: 'desc' }, '依進場時間 · Asia/Taipei')), metricToggle()),
    h('div', { class: 'statcards grid5' }, SESSIONS.map((S) => { const g = ses.find((x) => x.k === S.k); return h('div', { class: 'sc' + (g ? '' : ' dim') }, h('span', { class: 't' }, S.name), h('span', { class: 'm mono' }, S.range), h('span', { class: 'v ' + (g ? mCls(g) : ''), style: 'margin-top:10px' }, g ? mFmt(g) : '—'), h('span', { class: 'm' }, g ? `N=${g.n} · ${g.wins}W ${g.losses}L` : 'N=0 · 0W 0L')); }))));
  // 熱力圖
  const cells = {}; for (const t of rows) { const k = calc(t); if (!k.closed || !k.o) continue; const key = `${k.o.dow}-${k.ses}`; (cells[key] ||= []).push(t); }
  const cg = Object.fromEntries(Object.entries(cells).map(([k, v]) => [k, agg(v)]));
  const mxAbs = Math.max(...Object.values(cg).map((g) => Math.abs(state.an.metric === 'win' ? (g.win ?? 50) - 50 : g.avg() ?? 0)), 1e-9);
  const heat = h('div', { class: 'heat' }, h('span', {}), SESSIONS.map((S) => h('span', { class: 'hd' }, S.short)));
  for (const d of order) {
    heat.append(h('span', { class: 'rl' }, WD[d]));
    for (const S of SESSIONS) {
      const g = cg[`${d}-${S.k}`];
      if (!g || !fin(mVal(g))) { heat.append(h('div', { class: 'c' }, '—', h('small', {}, `N=${g ? g.n : 0}`))); continue; }
      const x = state.an.metric === 'win' ? (g.win - 50) : g.avg(); const a = Math.min(Math.abs(x) / mxAbs, 1);
      heat.append(h('div', { class: 'c', style: `background:color-mix(in srgb, ${x >= 0 ? 'var(--gain)' : 'var(--loss)'} ${Math.round(10 + a * 40)}%, var(--surface))` }, mFmt(g), h('small', {}, `N=${g.n}`)));
    }
  }
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '星期 × 時段'), h('div', { class: 'desc' }, '依進場時間 · Asia/Taipei')), metricToggle()), heat,
    h('div', { class: 'legend', style: 'justify-content:space-between;margin-top:10px' }, h('span', {}, '虧損較多'), h('span', {}, '色深表示差異較大；N=0 無資料'), h('span', {}, '獲利較多'))));
  // 商品、多空、準備度
  const sg = groupBy(rows, dimKey.sym);
  page.append(h('div', { class: 'divider' }), h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('h2', {}, '商品'), h('span', { class: 'muted', style: 'font-size:12.5px' }, rankNote)), contribLine(sg), lrowList(sg, { icon: (k) => coin(k) })));
  const side = groupBy(rows, dimKey.side); const L = side.find((g) => g.k === '做多'), S_ = side.find((g) => g.k === '做空');
  const cov = coverage(rows); const a = agg(rows);
  const diffTxt = L && S_ && fin(L.avg()) && fin(S_.avg()) ? (() => { const better = L.avg() >= S_.avg() ? L : S_; const d = Math.abs(L.avg() - S_.avg()); return h('div', { class: 'muted', style: 'font-size:14px;padding-top:10px' }, `「${better.k}」每筆期望值高 `, h('b', { class: 'mono gain' }, fmtS(d) + (uName() === 'R' ? 'R' : ' U')), `（${L.n} vs ${S_.n} 筆）`); })() : null;
  page.append(h('div', { class: 'divider' }), h('div', { class: 'grid2', style: 'gap:40px' },
    h('section', { class: 'sec' }, h('h2', {}, '做多 vs 做空'), h('div', { class: 'lrows' }, [L, S_].filter(Boolean).map((g) => h('div', { class: 'lrow' }, h('div', {}, g.k, h('span', { class: 'n', style: 'margin-left:40px' }, `N=${g.n}`), h('span', { class: 'n' }, `${fmtPct(g.win)}（${g.wins}W ${g.losses}L）`)), h('span', {}), h('span', { class: 'r' }, perN(g.avg()))))), diffTxt),
    h('section', { class: 'sec' }, h('h2', {}, '洞察準備度'), h('div', { class: 'kv' },
      kvRow('交易樣本', `${cov.n} / 15`, cov.n >= 15 ? 'gain' : 'amber'), kvRow('R 資料', `${cov.nR} / ${cov.n}`, cov.nR === cov.n ? 'gain' : 'amber'), kvRow('情緒資料', `${cov.nEmo} / ${cov.n}`, cov.nEmo === cov.n ? 'gain' : 'amber'), kvRow('條件資料', `${cov.nCond} / ${cov.n}`, cov.nCond === cov.n ? 'gain' : 'amber')),
      h('div', { class: 'muted', style: 'font-size:13px' }, '實際洞察取決於條件、情緒與資料完整度'),
      (() => { const gaps = [['R', cov.n - cov.nR, '止損'], ['情緒', cov.n - cov.nEmo, '情緒'], ['條件', cov.n - cov.nCond, '條件']].sort((x, y) => y[1] - x[1]); return gaps[0][1] ? h('div', {}, `優先補完 ${gaps[0][1]} 筆${gaps[0][2]}資料，之後的比較會更準。`) : h('div', {}, '資料都補齊了，很棒。'); })(),
      h('a', { href: '#/trades/pending' }, '去補完 →'))));
}
function timeScatter(rows) {
  const u = state.unit;
  const pts = closedOf(rows).map((t) => ({ t, k: calc(t) })).filter((p) => p.k.o && fin(val(p.k)));
  const a = agg(rows); const n = a.n;
  const card = h('div', { class: 'card soft' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', { style: 'font-size:24px;letter-spacing:0' }, '時區勝率分布圖'), h('div', { class: 'desc' }, 'Trade Outcome Distribution by Time of Day'), h('div', { class: 'desc' }, `X 軸為進場時間（台北）；Y 軸為已實現 ${u === 'R' ? 'R' : '盈虧'}。`)), h('span', { class: 'badge' }, 'Asia/Taipei')),
    h('div', { class: 'statcards grid3', style: 'max-width:720px;margin-bottom:16px' },
      h('div', { class: 'sc lb-gain' }, h('span', { class: 'k' }, '獲利交易'), h('span', { class: 'v gain' }, a.wins, h('small', { style: 'font-size:13px;color:var(--muted);margin-left:8px' }, fmtPct(n ? a.wins / n * 100 : null)))),
      h('div', { class: 'sc lb-loss' }, h('span', { class: 'k' }, '虧損交易'), h('span', { class: 'v loss' }, a.losses, h('small', { style: 'font-size:13px;color:var(--muted);margin-left:8px' }, fmtPct(n ? a.losses / n * 100 : null)))),
      h('div', { class: 'sc' }, h('span', { class: 'k' }, '總交易數'), h('span', { class: 'v' }, n, h('small', { style: 'font-size:13px;color:var(--muted);margin-left:8px' }, '全部已實現')))));
  if (pts.length < 2) { card.append(h('div', { class: 'muted' }, '資料還不夠。')); return card; }
  // 找最佳 3 小時區間
  let best = null;
  for (let st = 0; st < 24; st++) {
    const inW = pts.filter((p) => { const hh = p.k.o.hh; return st + 3 <= 24 ? hh >= st && hh < st + 3 : hh >= st || hh < (st + 3) % 24; });
    if (inW.length < 3) continue; const g = agg(inW.map((p) => p.t)); const m = g.avg(u);
    if (fin(m) && (!best || m > best.m)) best = { st, g, m };
  }
  const W = 1000, H = 440, P = { l: 70, r: 20, t: 20, b: 36 };
  const vs = pts.map((p) => val(p.k)); let lo = Math.min(...vs, 0), hi = Math.max(...vs, 0); const pd = (hi - lo) * 0.15 || 1; lo -= pd; hi += pd;
  const X = (m) => P.l + m / 1440 * (W - P.l - P.r), Y = (v) => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '進場時間與盈虧散點圖' });
  for (let hh = 0; hh <= 24; hh += 3) svg.append(s('line', { x1: X(hh * 60), x2: X(hh * 60), y1: P.t, y2: H - P.b, stroke: 'rgba(255,255,255,.06)' }), s('text', { x: X(hh * 60), y: H - 10, 'text-anchor': 'middle' }, `${pad(hh)}:00`));
  for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4; svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(v), y2: Y(v), stroke: 'rgba(255,255,255,.06)' }), s('text', { x: P.l - 10, y: Y(v) + 4, 'text-anchor': 'end' }, u === 'R' ? fmt(v, 1) + 'R' : '$' + fmt(v, 0))); }
  svg.append(s('line', { x1: P.l, x2: W - P.r, y1: Y(0), y2: Y(0), stroke: 'rgba(255,255,255,.45)', 'stroke-dasharray': '5 5' }));
  if (best && best.st + 3 <= 24) svg.append(s('rect', { x: X(best.st * 60), y: P.t, width: X((best.st + 3) * 60) - X(best.st * 60), height: H - P.t - P.b, fill: 'rgba(45,212,191,.10)', stroke: 'rgba(45,212,191,.35)', 'stroke-dasharray': '4 4' }));
  for (const p of pts) { const v = val(p.k); svg.append(s('circle', { cx: X(p.k.o.mins), cy: Y(v), r: 4, fill: v > 0 ? '#2dd4bf' : v < 0 ? '#f19aa6' : '#9fb6c9', style: 'cursor:pointer', onclick: () => openDrawer(p.t.id, pts.map((x) => x.t.id)) }, s('title', {}, `${p.t.symbol} ${fmtDT(p.t.open_time)} ${fmtV(v)}`))); }
  const panel = h('div', { class: 'darkplot' }, svg);
  if (best) panel.append(h('div', { class: 'bestbox' }, h('span', { class: 'k' }, '最佳時段'), h('span', { class: 'v' }, `${pad(best.st)}:00 - ${pad((best.st + 3) % 24)}:00`), h('span', { class: 's' }, '勝率'), h('b', { class: 'mono' }, fmtPct(best.g.win)), h('span', { class: 's' }, u === 'R' ? '平均 R' : '平均 PnL'), h('b', { class: 'mono', style: 'color:#0f766e' }, fmtV(best.m)), h('span', { class: 's' }, '樣本'), h('b', { class: 'mono' }, `N=${best.g.n}`)));
  card.append(panel);
  return card;
}

// ---------------------------------------------------------------- 時段與組合
const COMBOS = [
  { title: '交易時段', min: 15, key: (t) => { const S = sesOf(t); return S ? `${S.name}｜${S.range}` : null; } },
  { title: '進場條件', min: 10, key: (t) => t.conditions || [] },
  { title: '開單情緒', min: 10, key: (t) => t.emotions || [] },
  { title: '時段＋進場條件', min: 8, key: (t) => { const S = sesOf(t); return S ? (t.conditions || []).map((c) => `${S.short}時段＋${c}`) : []; } },
  { title: '時段＋開單情緒', min: 8, key: (t) => { const S = sesOf(t); return S ? (t.emotions || []).map((e) => `${S.short}時段＋${e}`) : []; } },
  { title: '時段＋進場條件＋開單情緒', min: 5, key: (t) => { const S = sesOf(t); if (!S) return []; const out = []; for (const c of t.conditions || []) for (const e of t.emotions || []) out.push(`${S.short}＋${c}＋${e}`); return out; } },
];
function anCombo(page, rows) {
  const u = state.unit;
  const sg = SESSIONS.map((S) => ({ S, a: agg(rows.filter((t) => calc(t).ses === S.k)) }));
  page.append(h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('div', {}, h('h2', {}, '交易時段表現'), h('div', { class: 'desc' }, '依進場時間歸類 · 台北時間 · UTC+8')), h('span', { class: 'muted', style: 'font-size:13px' }, '打平計入交易筆數，不計入勝率分母')),
    h('div', { class: 'tbl-wrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['時段', '交易筆數', '勝率', '獲利／虧損／打平', '平均 R', '總 R', '平均盈虧', '總盈虧'].map((x, i) => h('th', { class: i ? 'n' : '' }, x)))),
      h('tbody', {}, sg.map(({ S, a }) => h('tr', {}, h('td', {}, S.name, h('small', {}, S.range)), h('td', { class: 'n' }, a.n), h('td', { class: 'n' }, a.n ? fmtPct(a.win) : '—'), h('td', { class: 'n' }, `${a.wins}／${a.losses}／${a.be}`),
        h('td', { class: 'n ' + cls(a.avgR) }, a.n ? fmtR(a.avgR) : '—'), h('td', { class: 'n ' + cls(a.totalR) }, fmtR(a.totalR ?? 0)), h('td', { class: 'n ' + cls(a.avgU) }, a.n ? fmtU(a.avgU) : '—'), h('td', { class: 'n ' + cls(a.totalU) }, fmtU(a.totalU ?? 0)))))))));
  const cov = coverage(rows);
  page.append(h('div', { class: 'divider' }), h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('div', {}, h('h2', {}, '分析總結'), h('div', { class: 'desc' }, '勝率與平均 R 分開排名，沒達到樣本門檻的組別只顯示資料、不進重點摘要。')), h('span', { class: 'muted', style: 'font-size:12.5px' }, `條件填寫率 ${fmtPct(cov.cond, 0)} · 情緒填寫率 ${fmtPct(cov.emo, 0)}`)),
    h('div', { class: 'notebox' }, '群組不互斥，群組筆數合計可能大於總交易數。多選條件與多選情緒會各自計入對應群組；沒填寫的交易不進條件或情緒排名。'),
    h('div', { class: 'grid2' }, COMBOS.map((c) => rankCard(c, groupBy(rows, c.key))))));
  // 交叉分析
  const sortBy = state.an.crossSort || 'avg';
  const sorter = (a, b) => sortBy === 'win' ? (b.win ?? -1) - (a.win ?? -1) : sortBy === 'n' ? b.n - a.n : (b.avg(u) ?? -1e9) - (a.avg(u) ?? -1e9);
  const col = (title, min, gs) => h('div', { class: 'colx' }, h('div', { class: 'colh' }, title, h('small', {}, `摘要門檻 ≥${min}`)),
    gs.sort(sorter).map((g) => h('div', { class: 'ci' }, h('div', { class: 'a' }, h('span', {}, g.k), h('b', { class: cls(g.avg(u)) }, g.n < min ? h('span', { class: 'small-tag', style: 'margin-right:6px' }, '小樣本') : null, fmtV(g.avg(u)))),
      h('div', { class: 'm' }, `N=${g.n}　勝率 ${fmtPct(g.win)}　R 覆蓋 ${fmtPct(g.covR, 0)}`))));
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '時段 × 條件 × 情緒交叉分析'), h('div', { class: 'desc' }, '同一筆交易可能同時歸入多個標籤，所以各分類筆數不能直接相加。'))),
    h('div', { class: 'chips', style: 'margin-bottom:14px' }, h('span', { class: 'muted', style: 'margin-right:10px' }, '排序：'), h('div', { class: 'seg boxed' }, [['avg', u === 'R' ? '平均 R' : '平均盈虧'], ['win', '勝率'], ['n', '交易筆數']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(sortBy === v), onclick: () => { state.an.crossSort = v; render(); } }, l)))),
    h('div', { class: 'cross' }, col('交易時段', 15, groupBy(rows, (t) => { const S = sesOf(t); return S ? `${S.name}｜${S.range}` : null; })), col('進場條件', 10, groupBy(rows, dimKey.cond)), col('開單情緒', 10, groupBy(rows, dimKey.emo)))));
}
function rankCard(c, groups) {
  const u = state.unit; const valid = groups.filter((g) => g.n >= c.min);
  const na = h('div', { class: 'it na' }, h('div', { class: 't' }, '目前樣本不足'), h('div', { class: 'm', style: 'font-family:var(--font)' }, '至少需要 2 個達到樣本門檻的群組才能比較'));
  const item = (label, g, metric) => h('div', { class: 'it' }, h('div', { class: 'k' }, h('span', {}, label), h('b', { class: metric === 'win' ? '' : cls(g.avg(u)) }, metric === 'win' ? fmtPct(g.win) : fmtV(g.avg(u)))), h('div', { class: 't' }, g.k),
    h('div', { class: 'm' }, `${g.n} 筆 · ${g.wins} 獲利／${g.losses} 虧損／${g.be} 打平` + (metric === 'win' ? '' : ` · 總 ${fmtV(g.total(u))} · 勝率 ${fmtPct(g.win)}`)));
  let winCol, perfCol;
  if (valid.length >= 2) {
    const byWin = valid.filter((g) => fin(g.win)).sort((a, b) => b.win - a.win); const byPerf = valid.filter((g) => fin(g.avg(u))).sort((a, b) => b.avg(u) - a.avg(u));
    winCol = [item('勝率最高', byWin[0], 'win'), item('勝率最低', byWin[byWin.length - 1], 'win')];
    perfCol = [item('綜合績效最佳', byPerf[0], 'perf'), item('綜合績效最差', byPerf[byPerf.length - 1], 'perf')];
  } else { winCol = [na.cloneNode(true), na.cloneNode(true)]; perfCol = [na.cloneNode(true), na.cloneNode(true)]; }
  return h('div', { class: 'card' }, h('div', { class: 'card-h', style: 'margin-bottom:10px' }, h('div', {}, h('h2', { style: 'font-size:17px;letter-spacing:0' }, c.title), h('div', { class: 'desc' }, `最低樣本：${c.min} 筆有效交易`)), valid.length < 2 && groups.length ? h('span', { class: 'amber', style: 'font-size:12.5px' }, '樣本偏少') : null),
    h('div', { class: 'rank' }, h('div', { class: 'col' }, h('div', { class: 'h' }, '勝率排名'), winCol), h('div', { class: 'col' }, h('div', { class: 'h' }, '綜合績效排名'), perfCol)),
    groups.length ? h('details', { class: 'more', style: 'margin-top:14px' }, h('summary', { style: 'color:var(--accent)' }, `查看全部 ${groups.length} 個群組（含未達門檻）`), h('div', {}, lrowList(groups, { minN: c.min }))) : null);
}

// ---------------------------------------------------------------- 風險與可信度
function anRisk(page, rows) {
  const u = state.unit; const dd = ddStats(rows);
  const c = closedOf(rows).map((t) => ({ t, k: calc(t) })).filter((x) => fin(val(x.k)));
  const best = c.slice().sort((a, b) => val(b.k) - val(a.k))[0], worst = c.slice().sort((a, b) => val(a.k) - val(b.k))[0];
  const cov = coverage(rows); const all = closedOf(rows);
  const api_ = all.filter((t) => t.source === 'api'); const fees = api_.reduce((x, t) => x + (num(t.fee) || 0), 0);
  const pend = live().filter((t) => calc(t).pending).length;
  const pct = (n, d) => h('span', {}, h('b', { class: n === d ? 'gain' : 'amber', style: 'font-weight:700' }, fmtPct(d ? n / d * 100 : 0, 0)), h('small', { class: 'muted', style: 'margin-left:6px' }, `${n}/${d}`));
  page.append(h('div', { class: 'grid2', style: 'gap:48px' },
    h('section', { class: 'sec' }, h('div', {}, h('h2', {}, '回撤（已實現損益曲線）'), h('div', { class: 'desc' }, '依平倉時間順序累計，不是逐分鐘淨值。')),
      h('div', { class: 'metrics' }, h('div', {}, h('span', {}, '最大回撤'), h('span', { class: 'loss' }, fmtV(dd.maxDD))), h('div', {}, h('span', {}, '目前回撤（距前高）'), h('span', { class: dd.curDD < 0 ? 'loss' : '' }, fmtV(dd.curDD))),
        h('div', {}, h('span', {}, '最長未創新高'), h('span', {}, `${dd.longest} 天`)), h('div', {}, h('span', {}, '最大連勝／連虧'), h('span', {}, `${dd.mw} / ${dd.ml}`))),
      h('h2', { style: 'margin-top:12px' }, '單筆極值'),
      h('div', { class: 'kv' }, best ? kvRow(`最佳：${best.t.symbol}`, `${fmtR(best.k.R)} ${fmtU(best.k.pnl)}`, 'gain') : null, worst ? kvRow(`最差：${worst.t.symbol}`, `${fmtR(worst.k.R)} ${fmtU(worst.k.pnl)}`, 'loss') : null)),
    h('section', { class: 'sec' }, h('div', {}, h('h2', {}, '分析覆蓋率'), h('div', { class: 'desc' }, `分母一律是本期已平倉筆數（${cov.n} 筆，依平倉時間歸屬）`)),
      h('div', { class: 'kv' }, h('div', {}, h('span', {}, 'R 涵蓋（可計 R）'), pct(cov.nR, cov.n)), h('div', {}, h('span', {}, 'PnL 涵蓋（有盈虧值）'), pct(cov.pnl, cov.n)),
        h('div', {}, h('span', {}, '情緒覆蓋'), pct(cov.nEmo, cov.n)), h('div', {}, h('span', {}, '條件覆蓋'), pct(cov.nCond, cov.n)),
        kvRow('來源比例', `API ${api_.length} · 手動 ${all.filter((t) => t.source !== 'api').length}`), kvRow('手續費合計（僅 API 單）', `${fmt(fees, 2)} U`)),
      h('h2', { style: 'margin-top:12px' }, '待處理資料'), h('div', { class: 'hint' }, '這裡是操作清單，可能包含還沒平倉的交易（跟上面的覆蓋率不是同一群）。'),
      h('div', { class: 'kv' }, h('div', {}, h('span', {}, '待補完'), h('span', { class: 'amber' }, `${pend} 筆`))), h('a', { href: '#/trades/pending', class: 'amber' }, `補完 ${pend} 筆 →`),
      h('div', { class: 'muted', style: 'font-size:13.5px;line-height:1.8;margin-top:10px' }, '口徑說明：API 單的盈虧 = 交易所已實現淨盈虧（含手續費）；手動單的盈虧 = R × 風險金額（不含手續費），除非你自己填了實際盈虧。', h('br'),
        'R 看的是標準化後的交易效率；盈虧看的是真實資金結果。盈虧分析會受到每筆倉位和風險金額影響，不能直接解讀成策略好壞。'))));
}
