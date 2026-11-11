/* 總覽、紀錄、交易詳情、編輯、日曆 */
'use strict';

// ================================================================ 總覽
const PERIOD_LIST = [['today', '本日'], ['7', '近7日'], ['30', '近30日'], ['month', '本月']];
const PERIOD_NAMES = Object.fromEntries(PERIOD_LIST);
PAGES.overview = (page) => {
  const hr = tw(new Date().toISOString()).hh;
  const greet = hr < 5 ? '晚安' : hr < 11 ? '早安' : hr < 18 ? '午安' : '晚安';
  const st = state.settings;
  page.append(h('div', { class: 'ph greet' },
    h('div', {}, h('h1', {}, `${greet}${st.displayName ? '，' + st.displayName : ''}`), h('div', { class: 'sub' }, st.tagline || '')),
    h('div', { class: 'actions' }, syncButton())));
  const pb = pendingBanner(); if (pb) page.append(pb);
  if (!live().length) { page.append(emptyStart()); return; }

  // 績效
  const pk = state.ov.period; const rng = periodRange(pk);
  const rows = live().filter((t) => inRange(t, rng));
  const a = agg(rows);
  const pendIn = rows.filter((t) => calc(t).pending).length;
  const total = a.n ? a.total() : 0;
  const other = state.unit === 'R' ? fmtU(a.totalU ?? 0) : fmtR(a.totalR ?? 0);
  const chips = h('div', { class: 'chips' }, h('span', { class: 'lbl' }, `${PERIOD_NAMES[pk]}績效`),
    h('div', { class: 'seg', role: 'group', 'aria-label': '期間' }, PERIOD_LIST.map(([k, l]) => h('button', { type: 'button', 'aria-pressed': String(pk === k), onclick: () => { state.ov.period = k; render(); } }, l))),
    h('span', { class: 'sep' }), unitSeg());
  const left = h('div', {},
    h('div', { class: 'bignum ' + cls(total) }, a.n ? fmtV(total).replace(' U', '') : '0.00', h('small', {}, state.unit === 'R' ? '' : ' U')),
    h('div', { class: 'subnum' }, a.n ? other : '—'),
    h('div', { class: 'statline' }, `${PERIOD_NAMES[pk]}共 ${a.n} 筆 · 獲利 ${a.wins} 筆 · 虧損 ${a.losses} 筆 · 勝率 ${fmtPct(a.win)} · 累計 `, h('b', {}, fmtR(a.totalR ?? 0))),
    h('div', { style: 'margin-top:10px;font-size:14px', class: 'amber' }, `R 涵蓋 ${fmtPct(a.n ? a.covR : 0, 0)} · `, h('a', { href: '#/trades/pending', class: 'amber', style: 'text-decoration:underline' }, `待補完 ${pendIn} 筆`)));
  const curve = lineChart(cumSeries(rows), { height: 150, smooth: true, label: '期間累計盈虧', fmt: (v) => fmtV(v),
    empty: a.n && state.unit === 'R' && !a.nR ? '這段期間的交易還沒填止損，算不出 R；切到「盈虧」可以看金額。' : '這段期間還沒有平倉交易' });
  const todayRows = live().filter((t) => calc(t).o?.key === todayKey() || calc(t).c?.key === todayKey());
  const ta = agg(todayRows);
  const allLive = live(); const doneCount = allLive.filter((t) => !calc(t).pending).length; const pendAll = allLive.length - doneCount;
  const today = h('div', { class: 'today' }, h('div', { class: 'k' }, '今日'),
    h('div', { class: 'v ' + cls(ta.n ? ta.total() : 0) }, ta.n ? fmtV(ta.total()) : '—'),
    h('div', { class: 'muted' }, `今日已記錄交易 ${todayRows.length} 筆 · 已補完 ${doneCount}/${allLive.length}`),
    h('div', { class: 'row' }, h('span', { class: 'amber' }, `${pendAll} 筆待補完`), h('a', { href: '#/trades/pending', style: 'color:var(--ink-2)' }, '查看 →')));
  page.append(h('section', { class: 'sec' }, chips, h('div', { class: 'perf' }, h('div', { class: 'perf-main' }, left, curve), today)));
  page.append(h('div', { class: 'divider' }));

  // 數據洞察 + 近期節奏
  const r90 = live().filter((t) => inRange(t, periodRange('90')));
  const c90 = closedOf(r90).length;
  const groups = groupBy(r90, (t) => t.conditions || []).filter((g) => g.nR >= 5).sort((x, y) => (y.avgR ?? -9) - (x.avgR ?? -9));
  const best = groups[0];
  const ins = h('div', { class: 'insight' + (best && best.avgR < 0 ? ' neg' : '') },
    best ? h('div', { class: 't' }, `「${best.k}」近 90 日平均 `, h('b', { class: cls(best.avgR) }, fmtR(best.avgR)), '／筆。')
      : h('div', { class: 't' }, '記錄並勾選進場條件後，這裡會告訴你哪個條件最好用。'),
    best ? h('div', { class: 'm' }, `基於 R 樣本 ${best.nR}/${best.n} · R 涵蓋 ${fmtPct(best.covR, 0)}　`, h('a', { href: `#/trades/cond/${encodeURIComponent(best.k)}` }, '查看相關交易 →')) : null,
    h('div', { style: 'margin-top:14px;display:flex;justify-content:space-between;font-size:14px' }, h('span', { class: 'muted' }, '樣本累積'), h('b', { class: 'mono' }, `${c90} / 100 筆`)),
    h('div', { class: 'progress' }, h('div', { style: `width:${clamp(c90, 0, 100)}%` }), ...[10, 30, 100].map((v) => h('span', { class: 'tick', style: `left:${v}%` }))),
    h('div', { class: 'ticks' }, ...[10, 30, 100].map((v) => h('span', { style: `left:${v === 100 ? 97 : v}%` }, v))),
    h('div', { class: 'muted', style: 'font-size:13.5px;margin-top:6px' }, c90 < 100 ? `樣本正在累積；再 ${100 - c90} 筆，讓復盤更有依據` : '樣本夠多了，結論比較有參考價值'),
    h('div', { class: 'muted', style: 'font-size:12px' }, '近 90 日已平倉交易'));
  const recent = live().slice().sort((x, y) => (calc(y).o?.ms || 0) - (calc(x).o?.ms || 0)).slice(0, 10);
  // 節奏圖只畫「已平倉」的單（持倉中的還沒有結果），由舊到新排，最新的在最右邊
  const rec = closedOf(live()).sort((x, y) => (calc(y).c?.ms || calc(y).o?.ms || 0) - (calc(x).c?.ms || calc(x).o?.ms || 0)).slice(0, 10).reverse();
  const mainOf = (k) => val(k);
  const mxMain = Math.max(...rec.map((t) => mainOf(calc(t))).filter(fin).map(Math.abs), 0.0001);
  const mxU = Math.max(...rec.map((t) => calc(t).pnl).filter(fin).map(Math.abs), 0.0001);
  const rhythm = h('div', { class: 'rhythm' }, rec.map((t) => {
    const k = calc(t); const v = mainOf(k);
    // R 算不出來（沒填停損）時，改用盈虧 U 畫淺色的柱子
    const useU = !fin(v) && fin(k.pnl);
    const sv = fin(v) ? v : useU ? k.pnl : null;
    const ht = sv == null ? 6 : Math.max(6, Math.abs(sv) / (useU ? mxU : mxMain) * 64);
    const col = sv == null ? 'var(--line)' : sv >= 0 ? 'var(--gain)' : 'var(--loss)';
    return h('button', { class: 'it', type: 'button', title: `${t.symbol} ${t.side === 'short' ? '做空' : '做多'} ${fmtDT(t.close_time || t.open_time)}`, onclick: () => openDrawer(t.id, rec.map((x) => x.id)) },
      h('span', { class: 'sym' }, baseOf(t.symbol)),
      h('span', { class: 'bar-wrap' }, h('span', { class: 'bar' + (useU ? ' soft' : ''), style: `height:${ht}px;background:${col}` })),
      h('span', { class: t.side === 'short' ? 'side-s' : 'side-l' }, t.side === 'short' ? '空' : '多'),
      h('span', { class: 'pl ' + cls(sv) }, sv == null ? '—' : fmtS(sv, useU || state.unit !== 'R' ? 0 : 1)));
  }));
  page.append(h('div', { class: 'split' },
    h('section', { class: 'sec' }, h('h2', {}, '數據洞察'), ins),
    h('section', { class: 'sec vline' }, h('div', { class: 'sec-h' }, h('h2', {}, '近期交易節奏'), h('span', { class: 'muted' }, `最近 ${rec.length} 筆 · ${state.unit === 'R' ? 'R' : 'U'}`)), rec.length ? rhythm : h('p', { class: 'muted' }, '還沒有已平倉的交易'),
      h('div', { class: 'legend' }, h('span', {}, h('i', { style: 'background:var(--gain)' }), '賺'), h('span', {}, h('i', { style: 'background:var(--loss)' }), '賠'), state.unit === 'R' ? h('span', {}, h('i', { style: 'background:var(--muted);opacity:.45' }), '淺色＝沒填停損，改用 U') : null, h('span', {}, '越高＝賺賠越多，最右邊是最新')))));
  page.append(h('div', { class: 'divider' }));

  // 最近交易 + 累計趨勢
  const list = h('div', {}, recent.slice(0, 6).map((t) => tradeRow(t, recent.map((x) => x.id), { compact: true })));
  page.append(h('div', { class: 'split' },
    h('section', { class: 'sec' }, h('div', { class: 'sec-h' }, h('h2', {}, '最近交易'), h('a', { href: '#/trades', style: 'color:var(--ink-2)' }, '全部 →')), list),
    h('section', { class: 'sec vline' }, h('h2', {}, '累計盈虧趨勢'), lineChart(cumSeries(live()), { height: 220, axis: true, fmt: (v) => fmtV(v), label: '全部累計盈虧' }))));
};
function emptyStart() {
  return h('div', { class: 'card empty' }, h('strong', {}, '還沒有交易紀錄'),
    h('span', {}, state.sync.has_keys ? '按「同步最新交易」把 BingX 的成交抓進來，或手動新增一筆。' : '到「API 串接」設定 BingX 金鑰就會自動同步，也可以先手動新增一筆。'),
    h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;justify-content:center' }, h('a', { class: 'btn primary', href: '#/new' }, '＋ 新增交易'), h('a', { class: 'btn', href: '#/api' }, 'API 串接')));
}

// ================================================================ 紀錄
function tradeRow(t, navIds, opt = {}) {
  const k = calc(t); const v = val(k);
  const sel = state.tr.select && !opt.compact;
  const status = k.isOpen ? '持倉中' : k.pending ? '已平倉 · 待補完' : '已平倉 · 已補完';
  const mid = t.setup || (t.conditions || []).slice(0, 3).join('、') || '—';
  const valEl = k.isOpen ? h('span', { class: 'tval ' + cls(k.pnl) }, fin(k.pnl) ? fmtU(k.pnl) : '持倉中')
    : fin(v) ? h('span', { class: 'tval ' + cls(v) }, fmtV(v)) : h('span', { class: 'tval na' }, state.unit === 'R' ? '未計 R' : '—');
  const row = h('div', { class: 'trow' + (sel ? ' sel-mode' : ''), role: 'button', tabindex: 0,
    onclick: (e) => { if (sel) { togglePick(t.id); return; } openDrawer(t.id, navIds); },
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); } } },
    sel ? h('input', { type: 'checkbox', class: 'chk', checked: state.tr.picked.has(t.id), 'aria-label': '選取', onclick: (e) => { e.stopPropagation(); togglePick(t.id); } }) : null,
    coin(t.symbol),
    h('div', { class: 'tmain' },
      h('div', { class: 'l1' }, h('span', { class: 'sym' + (k.pending ? '' : ' done') }, t.symbol), h('span', { class: t.side === 'short' ? 'side-s' : 'side-l' }, t.side === 'short' ? '做空' : '做多'),
        k.needShot ? h('span', { class: 'badge amber small' }, '待補快照') : null,
        t.followed_rules === false ? h('span', { class: 'badge small' }, '沒照規則') : null),
      h('div', { class: 'l2' }, `${fmtDT(t.open_time)} · ${t.source === 'api' ? 'API' : t.source === 'csv' ? 'CSV' : '手動'}`)),
    opt.compact ? null : h('div', { class: 'tmid' }, mid),
    h('div', { class: 'tstat' + (k.pending || k.isOpen ? ' pending' : '') }, status),
    valEl);
  return row;
}
function togglePick(id) { const p = state.tr.picked; p.has(id) ? p.delete(id) : p.add(id); render(); }

function tradeFilter(base, ignoreTab) {
  const f = state.tr; const rng = periodRange(f.range); const q = f.q.trim().toLowerCase();
  let rows = base.filter((t) => {
    if (f.range !== 'all' && !inRange(t, rng, 'open')) return false;
    if (f.setup && t.setup !== f.setup) return false;
    if (f.side && t.side !== f.side) return false;
    if (f.cond && !(t.conditions || []).includes(f.cond)) return false;
    if (f.emo && !(t.emotions || []).includes(f.emo)) return false;
    if (f.source && (t.source || 'manual') !== f.source) return false;
    if (f.only && !f.only.includes(t.id)) return false;
    if (q && !`${t.symbol} ${t.note || ''} ${t.reason || ''} ${t.setup || ''}`.toLowerCase().includes(q)) return false;
    return true;
  });
  if (!ignoreTab) {
    const tab = f.tab;
    rows = rows.filter((t) => { const k = calc(t); return tab === 'all' || (tab === 'open' && k.isOpen) || (tab === 'pending' && k.pending) || (tab === 'win' && k.win) || (tab === 'loss' && k.loss); });
  }
  const key = (t) => calc(t).o?.ms || 0;
  const sorters = { newest: (a, b) => key(b) - key(a), oldest: (a, b) => key(a) - key(b), best: (a, b) => (val(calc(b)) ?? -1e9) - (val(calc(a)) ?? -1e9), worst: (a, b) => (val(calc(a)) ?? 1e9) - (val(calc(b)) ?? 1e9) };
  return rows.sort(sorters[f.sort] || sorters.newest);
}

PAGES.trades = (page, params) => {
  const f = state.tr;
  if (params[0] === 'pending') { Object.assign(f, { tab: 'pending', deleted: false, only: null }); history.replaceState(null, '', '#/trades'); }
  if (params[0] === 'cond' && params[1]) { Object.assign(f, { tab: 'all', cond: params[1], showFilter: true, deleted: false, only: null }); history.replaceState(null, '', '#/trades'); }
  if (params[0] === 'ids' && state._onlyIds) { Object.assign(f, { tab: 'all', only: state._onlyIds, deleted: false }); history.replaceState(null, '', '#/trades'); }
  const base = f.deleted ? state.trades.filter((t) => t.deleted_at) : live();
  page.append(pageHead('Trades', f.deleted ? '已刪除紀錄' : '交易紀錄', { count: base.length, actions: [
    h('button', { class: 'btn', type: 'button', onclick: () => { f.deleted = !f.deleted; f.select = false; f.picked.clear(); render(); } }, f.deleted ? '回到交易紀錄' : '已刪除紀錄'),
    syncButton()] }));
  if (!f.deleted) { const pb = pendingBanner(); if (pb) page.append(pb); }
  if (f.only) page.append(h('div', { class: 'banner' }, `只顯示分析頁挑出的 ${f.only.length} 筆交易`, h('span', { class: 'spacer' }), h('button', { class: 'linkbtn', type: 'button', onclick: () => { f.only = null; render(); } }, '顯示全部')));

  if (!f.deleted) page.append(h('div', {}, h('button', { class: 'btn', type: 'button', onclick: () => { f.select = !f.select; f.picked.clear(); render(); } }, f.select ? '取消選取' : '選取')));
  const pre = tradeFilter(base, true);
  const cnt = { all: pre.length, open: 0, pending: 0, win: 0, loss: 0 };
  for (const t of pre) { const k = calc(t); if (k.isOpen) cnt.open++; if (k.pending) cnt.pending++; if (k.win) cnt.win++; if (k.loss) cnt.loss++; }
  if (!f.deleted) page.append(h('div', { class: 'tabs', role: 'tablist' }, [['all', '全部'], ['open', '持倉中'], ['pending', '待補完'], ['win', '獲利單'], ['loss', '虧損單']].map(([k, l]) =>
    h('button', { type: 'button', role: 'tab', 'aria-selected': String(f.tab === k), onclick: () => { f.tab = k; render(); } }, l, h('span', {}, cnt[k])))));

  const opt = (cur, list) => list.map(([v, l]) => h('option', { value: v, selected: cur === v || null }, l));
  const search = h('input', { type: 'search', class: 'search', placeholder: '搜尋幣種或備註', value: f.q, 'aria-label': '搜尋' });
  search.addEventListener('input', () => { f.q = search.value; clearTimeout(search._t); search._t = setTimeout(() => { render(); const el = $('.filters .search'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 250); });
  page.append(h('div', { class: 'filters' },
    h('select', { 'aria-label': '時間', onchange: (e) => { f.range = e.target.value; render(); } }, opt(f.range, [['all', '全部時間'], ['today', '今天'], ['7', '近 7 天'], ['30', '近 30 天'], ['month', '本月'], ['90', '近 3 個月']])),
    h('select', { 'aria-label': '排序', onchange: (e) => { f.sort = e.target.value; render(); } }, opt(f.sort, [['newest', '最新進場'], ['oldest', '最早進場'], ['best', '盈虧高到低'], ['worst', '盈虧低到高']])),
    h('span', { class: 'spacer' }), h('span', { class: 'muted', style: 'font-size:14px' }, '盈虧顯示'), unitSeg('boxed'), search,
    h('button', { class: 'btn', type: 'button', 'aria-expanded': String(f.showFilter), onclick: () => { f.showFilter = !f.showFilter; render(); } }, icon('filter', 18), '篩選')));
  if (f.showFilter) {
    const sel = (key, label, list) => h('select', { 'aria-label': label, onchange: (e) => { f[key] = e.target.value; render(); } }, h('option', { value: '' }, label), opt(f[key], list.map((x) => [x, x])));
    page.append(h('div', { class: 'filters' },
      sel('setup', '全部策略', [...new Set([...(state.settings.setups || []), ...live().map((t) => t.setup).filter(Boolean)])]),
      h('select', { 'aria-label': '方向', onchange: (e) => { f.side = e.target.value; render(); } }, opt(f.side, [['', '多空都看'], ['long', '只看做多'], ['short', '只看做空']])),
      sel('cond', '全部條件', condList().map((c) => c.name)),
      sel('emo', '全部情緒', emoList().map((e) => e.name)),
      h('select', { 'aria-label': '來源', onchange: (e) => { f.source = e.target.value; render(); } }, opt(f.source, [['', '全部來源'], ['api', 'API'], ['manual', '手動'], ['csv', 'CSV']])),
      h('button', { class: 'linkbtn', type: 'button', onclick: () => { Object.assign(f, { setup: '', side: '', cond: '', emo: '', source: '', q: '', range: 'all' }); render(); } }, '清除篩選')));
  }

  const rows = tradeFilter(base);
  if (!rows.length) { page.append(base.length ? h('div', { class: 'empty' }, h('strong', {}, '沒有符合的交易'), h('span', {}, '換個分頁或清除篩選試試看。')) : (f.deleted ? h('div', { class: 'empty' }, h('strong', {}, '沒有已刪除的紀錄')) : emptyStart())); return; }
  const navIds = rows.map((t) => t.id);
  if (f.deleted) {
    page.append(h('div', {}, rows.map((t) => h('div', { class: 'trow', style: 'grid-template-columns:auto minmax(0,1fr) auto auto' }, coin(t.symbol),
      h('div', { class: 'tmain' }, h('div', { class: 'l1' }, h('span', { class: 'sym done' }, t.symbol), h('span', { class: t.side === 'short' ? 'side-s' : 'side-l' }, t.side === 'short' ? '做空' : '做多')), h('div', { class: 'l2' }, `${fmtDT(t.open_time)} · 刪除於 ${fmtDT(t.deleted_at)}`)),
      h('button', { class: 'btn sm', type: 'button', onclick: async () => { try { replaceTrade(await api('POST', `/trades/${t.id}/restore`)); toast('已還原'); render(); } catch (e) { toast(e.message); } } }, '還原'),
      h('button', { class: 'btn sm danger', type: 'button', onclick: (e) => confirmClick(e.currentTarget, '再按一次永久刪除', async () => { await api('DELETE', `/trades/${t.id}?hard=1`); state.trades = state.trades.filter((x) => x.id !== t.id); render(); }) }, '永久刪除')))));
    return;
  }
  const groups = new Map();
  for (const t of rows) { const key = calc(t).o?.key || '未知日期'; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(t); }
  for (const [key, list] of groups) {
    const p = key.includes('-') ? tw(new Date(keyToMs(key) + 1).toISOString()) : null;
    const a = agg(list); const noR = list.filter((t) => calc(t).closed && calc(t).R == null).length;
    page.append(h('div', { class: 'daygrp' },
      h('div', { class: 'dayh' }, p ? `${p.m}月${p.d}日 週${WD[p.dow]}` : key, h('span', { class: 'm' }, `${list.length} 筆` + (noR ? ` · ${noR}筆未計 R` : (a.n && fin(a.total()) ? ` · ${fmtV(a.total())}` : '')))),
      list.map((t) => tradeRow(t, navIds))));
  }
  if (f.select) {
    const n = f.picked.size;
    const condSel = h('select', { 'aria-label': '加入條件' }, h('option', { value: '' }, '加入進場條件…'), condList().map((c) => h('option', { value: c.name }, c.name)));
    const setupSel = h('select', { 'aria-label': '設定策略' }, h('option', { value: '' }, '設定策略…'), (state.settings.setups || []).map((x) => h('option', { value: x }, x)));
    const run = async (body, msg) => { if (!n) return toast('先勾選交易'); try { const r = await api('POST', '/trades/batch', { ids: [...f.picked], ...body }); r.trades.forEach(replaceTrade); f.picked.clear(); toast(msg); render(); } catch (e) { toast(e.message); } };
    condSel.addEventListener('change', () => condSel.value && run({ action: 'add_tags', field: 'conditions', tags: [condSel.value] }, '已加入條件'));
    setupSel.addEventListener('change', () => setupSel.value && run({ action: 'set_setup', setup: setupSel.value }, '已設定策略'));
    page.append(h('div', { class: 'batchbar' }, h('span', {}, `已選 ${n} 筆`),
      h('button', { class: 'btn sm', type: 'button', onclick: () => { rows.forEach((t) => f.picked.add(t.id)); render(); } }, '全選'),
      condSel, setupSel,
      h('button', { class: 'btn sm danger', type: 'button', onclick: (e) => n ? confirmClick(e.currentTarget, `再按一次刪除 ${n} 筆`, () => run({ action: 'delete' }, '已移到已刪除紀錄')) : toast('先勾選交易') }, '刪除')));
  }
};
function confirmClick(btn, text, fn) {
  if (btn.dataset.armed) { delete btn.dataset.armed; fn(); return; }
  const old = btn.textContent; btn.dataset.armed = '1'; btn.textContent = text;
  setTimeout(() => { if (btn.dataset.armed) { delete btn.dataset.armed; btn.textContent = old; } }, 3500);
}

// ================================================================ 條件 / 情緒選擇器
function condPicker(selected, side, onChange, opts = {}) {
  const wrap = h('div', { class: 'dsec' });
  const all = condList();
  // 同方向的條件排前面，多空都可的排後面（各自照設定頁的順序）
  const ok = side ? [...all.filter((c) => c.dir === side), ...all.filter((c) => c.dir === 'both')] : all;
  const bad = all.filter((c) => !(c.dir === 'both' || c.dir === side || !side));
  const extra = selected.filter((n) => !all.some((c) => c.name === n));   // 舊資料裡、設定已刪掉的條件
  const q = opts.query || '';
  const tagBtn = (c, disabled) => h('button', { type: 'button', class: 'tag', disabled: disabled || null, 'aria-pressed': String(selected.includes(c.name)),
    onclick: () => { const set = new Set(selected); set.has(c.name) ? set.delete(c.name) : set.add(c.name); onChange([...set]); } },
    h('i', { style: `background:${COLOR_VAR[c.color] || COLOR_VAR.gray}` }), c.name);
  if (opts.search) {
    const inp = h('input', { type: 'search', placeholder: '搜尋進場條件', value: q, class: 'sm', 'aria-label': '搜尋進場條件' });
    inp.addEventListener('input', () => { opts.onQuery(inp.value); });
    wrap.append(inp);
  }
  const match = (c) => !q || c.name.toLowerCase().includes(q.toLowerCase());
  wrap.append(h('div', { class: 'tagbox' }, ok.filter(match).map((c) => tagBtn(c, false)), extra.map((n) => tagBtn({ name: n, color: 'gray' }, false))));
  if (bad.length) wrap.append(h('details', { class: 'locked' }, h('summary', {}, icon('lock', 16), h('b', {}, `方向不符條件（${bad.length}）`), h('span', { class: 'm' }, `目前為${side === 'short' ? '做空' : '做多'}，以下偏${side === 'short' ? '做多' : '做空'}條件不可選`), icon('down', 16)),
    h('div', { class: 'tagbox' }, bad.map((c) => tagBtn(c, true)))));
  wrap.append(addTagRow('cond', side, (name) => onChange([...new Set([...selected, name])])));
  return wrap;
}
function emoPicker(selected, onChange) {
  const max = 3;
  const wrap = h('div', { class: 'dsec' });
  wrap.append(h('div', { style: 'display:flex;justify-content:space-between;font-size:13px', class: 'muted' }, h('span', {}, '可複選'), h('span', {}, `已選 ${selected.length}/${max}`)));
  wrap.append(h('div', { class: 'tagbox' }, emoList().map((e) => h('button', { type: 'button', class: 'tag tone-' + (e.tone || 'none'), 'aria-pressed': String(selected.includes(e.name)),
    onclick: () => { const set = new Set(selected); if (set.has(e.name)) set.delete(e.name); else { if (set.size >= max) return toast(`最多選 ${max} 個`); set.add(e.name); } onChange([...set]); } }, e.name)),
    selected.filter((n) => !emoList().some((e) => e.name === n)).map((n) => h('button', { type: 'button', class: 'tag', 'aria-pressed': 'true', onclick: () => onChange(selected.filter((x) => x !== n)) }, n))));
  wrap.append(addTagRow('emo', null, (name) => { if (selected.length >= max) return; onChange([...selected, name]); }));
  return wrap;
}
function addTagRow(kind, side, onAdded) {
  const box = h('div', {});
  const btn = h('button', { type: 'button', class: 'tag add' }, kind === 'cond' ? '+ 新增進場條件' : '+ 新增情緒');
  btn.addEventListener('click', () => {
    const name = h('input', { type: 'text', placeholder: kind === 'cond' ? '條件名稱，例如 4H流動性獵取' : '情緒名稱', 'aria-label': '名稱' });
    const sel1 = kind === 'cond'
      ? h('select', { 'aria-label': '方向' }, [['both', '多空都可'], ['long', '偏做多'], ['short', '偏做空']].map(([v, l]) => h('option', { value: v, selected: v === (side || 'both') || null }, l)))
      : h('select', { 'aria-label': '性質' }, [['good', '正面'], ['warn', '普通'], ['bad', '負面']].map(([v, l]) => h('option', { value: v }, l)));
    const sel2 = kind === 'cond' ? h('select', { 'aria-label': '顏色' }, Object.entries(COLOR_NAMES).map(([v, l]) => h('option', { value: v, selected: v === (side === 'short' ? 'red' : side === 'long' ? 'green' : 'blue') || null }, l + '色'))) : null;
    const save = async () => {
      const n = name.value.trim(); if (!n) return;
      const st = state.settings;
      const next = kind === 'cond' ? { conditions: [...condList().filter((c) => c.name !== n), { name: n, dir: sel1.value, color: sel2.value }] }
        : { emotions: [...emoList().filter((e) => e.name !== n), { name: n, tone: sel1.value }] };
      try { state.settings = await api('PUT', '/settings', next); onAdded(n); toast('已新增，之後每筆都能選'); } catch (e) { toast(e.message); }
    };
    name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
    box.replaceChildren(h('div', { class: 'addrow' }, name, sel1, sel2, h('button', { class: 'btn sm primary', type: 'button', onclick: save }, '新增'), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => box.replaceChildren(btn) }, '取消')));
    name.focus();
  });
  box.append(btn);
  return box;
}

// ================================================================ 截圖
async function uploadFiles(files) {
  const out = [];
  for (const f of files) {
    if (!/^image\/(png|jpeg|webp|gif)$/.test(f.type)) continue;
    const fd = new FormData(); fd.append('file', f, f.name || 'paste.png');
    const r = await api('POST', '/upload', fd, true); out.push(r.path);
  }
  return out;
}
// ---------------------------------------------------------------- 盤面快照（照超人交易紀錄：小卡片＋「補上快照」視窗）
// 角色和備註附在每筆截圖／連結字串的 # 後面（瀏覽器不會把 # 後面送到伺服器，所以圖片照常顯示，也不用改資料庫）
ICONS.clip = '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 14l2 2 4-4"/>';
ICONS.ext = '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>';
const SHOT_ROLES = ['進場前規劃', '持倉中盤面', '出場盤面', '復盤結果', '其他'];
function shotMeta(str) {
  const s0 = String(str || ''); const i = s0.indexOf('#xj=');
  if (i < 0) return { base: s0, role: '', note: '' };
  const raw = s0.slice(i + 4);
  for (const txt of [raw, (() => { try { return decodeURIComponent(raw); } catch (_) { return ''; } })()]) {
    try { const m = JSON.parse(txt); return { base: s0.slice(0, i), role: m.r || '', note: m.n || '' }; } catch (_) { }
  }
  return { base: s0.slice(0, i), role: '', note: '' };
}
function withMeta(base, role, note) {
  const m = {}; if (role) m.r = role; if (note) m.n = String(note).slice(0, 120);
  return Object.keys(m).length ? `${base}#xj=${JSON.stringify(m)}` : base;   // 伺服器每筆最多存 500 字，備註限 120 字
}
const tvChartUrl = (sym) => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent('BINGX:' + String(sym || '').toUpperCase().replace(/[^A-Z0-9]/g, '') + '.P')}`;
const isTvUrl = (v) => /^https:\/\/([a-z0-9-]+\.)*tradingview\.com\//i.test(String(v || '').trim());

function shotEditor(shots, tvLinks, onChange, ctx = {}) {
  const wrap = h('div', { class: 'snapcard' });
  const items = [...shots.map((x) => ({ kind: 'img', raw: x })), ...tvLinks.map((x) => ({ kind: 'tv', raw: x }))];
  const remove = (it) => onChange(it.kind === 'img' ? shots.filter((x) => x !== it.raw) : shots, it.kind === 'tv' ? tvLinks.filter((x) => x !== it.raw) : tvLinks);
  const open = (files) => openShotSheet(ctx, (newShots, newTv) => onChange([...shots, ...newShots], [...new Set([...tvLinks, ...newTv])]), files);
  if (!items.length) {
    wrap.append(h('div', { class: 'snap-empty' }, '尚未附加盤面連結'), h('button', { class: 'btn primary snap-add', type: 'button', onclick: () => open() }, icon('plus', 18), '補上快照'));
  } else {
    wrap.append(h('div', { class: 'snap-list' }, items.map((it) => {
      const m = shotMeta(it.raw);
      const label = h('div', { class: 'snap-meta' }, h('span', { class: 'snap-role' }, m.role || '其他'), m.note ? h('span', { class: 'snap-note' }, m.note) : null);
      const del = h('button', { class: 'snap-del', type: 'button', 'aria-label': '移除', title: '移除', onclick: (e) => { e.stopPropagation(); confirmClick(e.currentTarget, '確定？', () => remove(it)); } }, '×');
      if (it.kind === 'img') return h('div', { class: 'snap-item' }, h('img', { src: `/journal/shot/${m.base}`, alt: '盤面截圖', loading: 'lazy', onclick: () => viewImg(`/journal/shot/${m.base}`) }), label, del);
      return h('div', { class: 'snap-item link' }, h('a', { href: m.base, target: '_blank', rel: 'noopener noreferrer', class: 'snap-tv' }, h('span', { class: 'badge small' }, 'TV'), m.base.replace(/^https:\/\/(www\.)?/, '')), label, del);
    })), h('button', { class: 'btn snap-add', type: 'button', onclick: () => open() }, icon('plus', 18), '再補一張'));
  }
  // 在詳情／編輯頁直接 Ctrl+V 截圖：自動打開視窗並放進去
  _pasteTarget = (files) => open(files);
  return wrap;
}
let _pasteTarget = null;
let _sheetPaste = null;
document.addEventListener('paste', (e) => {
  if (_sheetPaste) { _sheetPaste(e); return; }
  if (!_pasteTarget || !(state.drawer || state.route.page === 'edit' || state.route.page === 'new')) return;
  const files = [...(e.clipboardData?.items || [])].filter((it) => it.kind === 'file' && it.type.startsWith('image/')).map((it) => it.getAsFile());
  if (!files.length) return;
  e.preventDefault(); _pasteTarget(files);
});

function openShotSheet(ctx, onDone, initialFiles) {
  const S = { role: ctx.status === 'closed' ? '出場盤面' : '進場前規劃', note: '', imgs: [], links: [], busy: 0, manual: false };
  const side = ctx.side === 'short' ? 'SHORT' : 'LONG';
  const srcName = ctx.source === 'api' ? 'BingX' : ctx.source === 'csv' ? 'CSV 匯入' : '手動紀錄';
  const fileIn = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif', multiple: true, hidden: true });
  const body = h('div', { class: 'sheet-b' });
  const doneBtn = h('button', { class: 'btn primary sheet-done', type: 'button' }, '完成附加');
  const close = () => { _sheetPaste = null; wrapEl.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const addFiles = async (files) => {
    files = [...files].filter((f) => f && f.type && f.type.startsWith('image/'));
    if (!files.length) return;
    S.busy += files.length; draw();
    try { const paths = await uploadFiles(files); S.imgs.push(...paths); } catch (e) { toast('上傳失敗：' + e.message); }
    S.busy -= files.length; draw();
  };
  const addLink = (v) => { v = String(v || '').trim(); if (!v) return false; if (!isTvUrl(v)) { toast('請貼 tradingview.com 的連結'); return false; } if (!S.links.includes(v)) S.links.push(v); draw(); return true; };
  const pasteFromClipboard = async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.read) {
        const items = await navigator.clipboard.read(); const files = [];
        for (const it of items) { const t = it.types.find((x) => x.startsWith('image/')); if (t) files.push(new File([await it.getType(t)], 'clip.png', { type: t })); }
        if (files.length) { addFiles(files); return; }
      }
      const txt = navigator.clipboard && navigator.clipboard.readText ? await navigator.clipboard.readText() : '';
      if (txt && addLink(txt)) return;
      toast('剪貼簿裡沒有盤面連結或截圖');
    } catch (_) { toast('瀏覽器不讓網頁讀剪貼簿，請直接按 Ctrl+V（Mac ⌘+V）貼上'); }
  };
  fileIn.addEventListener('change', () => { addFiles(fileIn.files); fileIn.value = ''; });
  _sheetPaste = (e) => {
    const files = [...(e.clipboardData?.items || [])].filter((it) => it.kind === 'file' && it.type.startsWith('image/')).map((it) => it.getAsFile());
    if (files.length) { e.preventDefault(); addFiles(files); return; }
    const txt = e.clipboardData?.getData('text') || '';
    const tgt = e.target; if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA')) return;
    if (isTvUrl(txt)) { e.preventDefault(); addLink(txt); }
  };
  const manualIn = h('input', { type: 'text', inputmode: 'url', class: 'sm', placeholder: 'https://www.tradingview.com/x/…', 'aria-label': 'TradingView 快照連結' });
  manualIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (addLink(manualIn.value)) manualIn.value = ''; } });
  const noteIn = h('input', { type: 'text', class: 'sheet-note', maxlength: 120, placeholder: '最多 120 字', 'aria-label': '備註' });
  noteIn.addEventListener('input', () => { S.note = noteIn.value; });

  function draw() {
    const has = S.imgs.length + S.links.length;
    doneBtn.disabled = !has || S.busy > 0 || null;
    doneBtn.textContent = S.busy ? '上傳中…' : '完成附加';
    body.replaceChildren(
      h('div', { class: 'sheet-info mono' }, h('b', {}, ctx.symbol || ''), ` · ${side} · ${srcName} · ${ctx.status === 'closed' ? 'CLOSED' : 'OPEN'}`),
      h('div', { class: 'sheet-opts' },
        h('button', { type: 'button', class: 'sheet-opt', onclick: () => fileIn.click() }, icon('image', 22), h('span', {}, '從相簿選擇')),
        h('button', { type: 'button', class: 'sheet-opt', onclick: pasteFromClipboard }, icon('clip', 22), h('span', {}, '貼上已複製的盤面連結'))),
      h('div', { class: 'sheet-tv' }, h('span', {}, '將開啟對應的 BingX 永續合約盤面'),
        h('a', { href: tvChartUrl(ctx.symbol), target: '_blank', rel: 'noopener noreferrer' }, '開啟 TradingView ', icon('ext', 15))),
      S.manual ? h('div', { class: 'addrow' }, manualIn, h('button', { class: 'btn sm', type: 'button', onclick: () => { if (addLink(manualIn.value)) manualIn.value = ''; } }, '加入'))
        : h('button', { type: 'button', class: 'linkbtn sheet-manual', onclick: () => { S.manual = true; draw(); setTimeout(() => manualIn.focus(), 0); } }, '手動貼上 TradingView 快照連結'),
      has || S.busy ? h('div', { class: 'sheet-picked' },
        S.imgs.map((p) => h('div', { class: 'sheet-thumb' }, h('img', { src: `/journal/shot/${p}`, alt: '待附加的截圖' }), h('button', { type: 'button', 'aria-label': '移除', onclick: () => { S.imgs = S.imgs.filter((x) => x !== p); draw(); } }, '×'))),
        S.links.map((u) => h('div', { class: 'sheet-link' }, h('span', { class: 'badge small' }, 'TV'), h('span', { class: 'u' }, u.replace(/^https:\/\/(www\.)?/, '')), h('button', { type: 'button', 'aria-label': '移除', onclick: () => { S.links = S.links.filter((x) => x !== u); draw(); } }, '×'))),
        S.busy ? h('div', { class: 'sheet-thumb busy' }, '上傳中…') : null) : null,
      h('div', { class: 'sheet-lbl' }, '快照角色'),
      h('div', { class: 'sheet-roles' }, SHOT_ROLES.map((r) => h('button', { type: 'button', class: 'sheet-role', 'aria-pressed': String(S.role === r), onclick: () => { S.role = r; draw(); } }, r))),
      h('div', { class: 'sheet-lbl' }, '備註（選填）'), noteIn, fileIn);
  }
  doneBtn.addEventListener('click', () => {
    if (doneBtn.disabled) return;
    onDone(S.imgs.map((p) => withMeta(p, S.role, S.note)), S.links.map((u) => withMeta(u, S.role, S.note)));
    close();
  });
  const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': '補上盤面快照' },
    h('div', { class: 'sheet-grip' }),
    h('div', { class: 'sheet-h' }, h('div', {}, h('h2', {}, '補上盤面快照'), h('div', { class: 'sub' }, `${ctx.symbol || ''} · ${side}${ctx.open_time ? ' · ' + fmtSheetTime(ctx.open_time) : ''}`)),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': '關閉', onclick: close }, icon('x'))),
    body, h('div', { class: 'sheet-f' }, doneBtn));
  sheet.addEventListener('dragover', (e) => { e.preventDefault(); sheet.classList.add('over'); });
  sheet.addEventListener('dragleave', (e) => { if (e.target === sheet) sheet.classList.remove('over'); });
  sheet.addEventListener('drop', (e) => { e.preventDefault(); sheet.classList.remove('over'); addFiles(e.dataTransfer?.files || []); });
  const wrapEl = h('div', { class: 'sheet-wrap' }, h('div', { class: 'scrim', onclick: close }), sheet);
  document.body.append(wrapEl); document.addEventListener('keydown', onKey);
  draw();
  if (initialFiles && initialFiles.length) addFiles(initialFiles);
}
function fmtSheetTime(iso) { const p = tw(iso); if (!p) return ''; const ap = p.hh < 12 ? '上午' : '下午'; const h12 = p.hh % 12 || 12; return `${p.m}/${p.d} ${ap}${pad(h12)}:${pad(p.mm)}`; }
function viewImg(src) { const v = h('div', { class: 'viewer', role: 'dialog', 'aria-label': '截圖', onclick: () => v.remove() }, h('img', { src, alt: '盤面截圖' })); document.body.append(v); }

// ================================================================ 交易詳情（右側）
function openDrawer(id, navIds) {
  const t = state.trades.find((x) => x.id === id); if (!t) return;
  state.drawer = { id, nav: navIds || [id], d: pickUser(t), dirty: false, q: '' };
  renderDrawer();
}
function pickUser(t) { return { conditions: [...(t.conditions || [])], emotions: [...(t.emotions || [])], sl: t.sl ?? '', risk_amount: t.risk_amount ?? '', note: t.note || '' }; }
function closeDrawer() { state.drawer = null; _pasteTarget = null; $('#layer').replaceChildren(); }
function renderDrawer() {
  const D = state.drawer; if (!D) return;
  const t = state.trades.find((x) => x.id === D.id); if (!t) { closeDrawer(); return; }
  const k = calc(t); const d = D.d;
  const layer = $('#layer'); const keepScroll = layer.querySelector('.db')?.scrollTop || 0;
  const idx = D.nav.indexOf(D.id);
  const move = (dir) => { const nid = D.nav[idx + dir]; if (!nid) return; if (D.dirty && !confirm('這筆還沒儲存，要放棄修改嗎？')) return; openDrawer(nid, D.nav); };
  const mark = () => { D.dirty = true; saveBtn.disabled = false; };
  const re = () => { renderDrawer(); };
  const saveBtn = h('button', { class: 'btn primary', type: 'button', disabled: !D.dirty || null, style: 'width:100%' }, '儲存');
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    try { const nt = await api('PATCH', `/trades/${t.id}`, { ...d, sl: num(d.sl), risk_amount: num(d.risk_amount) }); replaceTrade(nt); D.dirty = false; D.d = pickUser(nt); toast('已儲存'); render(); renderDrawer(); }
    catch (e) { toast(e.message); saveBtn.disabled = false; }
  });
  const slIn = h('input', { type: 'text', inputmode: 'decimal', placeholder: '可先留白', value: d.sl, 'aria-label': '原始止損價' });
  slIn.addEventListener('input', () => { d.sl = slIn.value; mark(); });
  const riskIn = h('input', { type: 'text', inputmode: 'decimal', placeholder: '選填', value: d.risk_amount, 'aria-label': '風險金額' });
  riskIn.addEventListener('input', () => { d.risk_amount = riskIn.value; mark(); });
  const noteIn = h('textarea', { placeholder: '這筆學到什麼…', 'aria-label': '備註' }); noteIn.value = d.note;
  noteIn.addEventListener('input', () => { d.note = noteIn.value; mark(); });
  const saveShots = async (shots, tv) => { try { const nt = await api('PATCH', `/trades/${t.id}`, { shots, tv_links: tv }); replaceTrade(nt); render(); renderDrawer(); toast('截圖已儲存'); } catch (e) { toast(e.message); } };

  const raw = t.raw && t.raw.symbol ? `BingX raw: ${t.raw.symbol}` : (t.source === 'api' ? 'BingX' : t.source === 'csv' ? 'CSV 匯入' : '手動紀錄');
  const drawer = h('div', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${t.symbol} 交易詳情` },
    h('div', { class: 'dh' }, coin(t.symbol, true),
      h('div', { class: 't' }, h('div', { class: 'l1' }, h('b', {}, t.symbol), h('span', { class: t.side === 'short' ? 'side-s' : 'side-l' }, t.side === 'short' ? '做空' : '做多')),
        h('div', { class: 'st' + (k.pending ? '' : ' ok') }, `${k.isOpen ? '持倉中' : '已平倉'} · ${k.pending ? '待補完' : '已補完'}`), h('div', { class: 'raw' }, raw)),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': '上一筆', disabled: idx <= 0 || null, onclick: () => move(-1) }, icon('up')),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': '下一筆', disabled: idx < 0 || idx >= D.nav.length - 1 || null, onclick: () => move(1) }, icon('down')),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': '關閉', onclick: () => { if (D.dirty && !confirm('這筆還沒儲存，要放棄修改嗎？')) return; closeDrawer(); } }, icon('x'))),
    h('div', { class: 'db' },
      h('div', { class: 'card', style: 'padding:16px 18px;display:grid;gap:16px' },
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '盤面連結 / 圖表附件', h('span', { class: 'opt' }, k.hasShot ? '已補' : '待補')), null), shotEditor(t.shots || [], t.tv_links || [], saveShots, { symbol: t.symbol, side: t.side, open_time: t.open_time, status: t.status, source: t.source })),
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '進場條件', h('span', { class: 'opt' }, '選填'))),
          condPicker(d.conditions, t.side, (v) => { d.conditions = v; D.dirty = true; re(); }, { search: true, query: D.q, onQuery: (q) => { D.q = q; re(); setTimeout(() => { const el = $('.drawer input[type=search]'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0); } })),
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '開單時的狀態', h('span', { class: 'opt' }, '選填'))), emoPicker(d.emotions, (v) => { d.emotions = v; D.dirty = true; re(); })),
        h('label', { class: 'f' }, '原始止損價', slIn, h('span', { class: 'hint' }, '原始止損價用於計算 R。')),
        h('label', { class: 'f' }, '風險金額 U（選填）', riskIn, h('span', { class: 'hint' }, t.source === 'api' ? '沒填就用止損距離 × 數量自動算；真實盈虧仍以 BingX 為準。' : '手動單沒有數量，請填風險金額才能算 R。')),
        h('label', { class: 'f' }, '備註（選填）', noteIn),
        saveBtn),
      h('div', { class: 'dsec' }, h('div', { class: 'h' }, '資料'),
        h('div', { class: 'kv' },
          kvRow('來源', t.source === 'api' ? 'BingX 自動匯入' : t.source === 'csv' ? 'CSV 匯入' : '手動'),
          kvRow('開倉時間', fmtDTY(t.open_time)), kvRow('平倉時間', k.isOpen ? '持倉中' : fmtDTY(t.close_time)), kvRow('持倉時間', fmtHold(k.holdMin)),
          kvRow('進場價', fmt(k.entry, 8)), kvRow(k.isOpen ? '標記價格' : '出場價', fmt(k.exit, 8)), t.qty != null ? kvRow('數量', fmt(k.qty, 8)) : null,
          kvRow(k.isOpen ? '未實現盈虧' : '實際盈虧', fmtU(k.pnl, 4), cls(k.pnl)), kvRow('R', fmtR(k.R), cls(k.R)), kvRow('停損距離', fmtPct(k.stopPct, 2)),
          t.leverage != null ? kvRow('槓桿', `${fmt(k.lev)}x`) : null, t.fee != null ? kvRow('手續費', fmt(t.fee, 6)) : null, t.funding != null ? kvRow('資金費', fmt(t.funding, 6)) : null))),
    h('div', { class: 'df' }, h('a', { class: 'btn', href: `#/edit/${t.id}` }, icon('edit', 17), '編輯'), h('span', { class: 'spacer' }),
      h('button', { class: 'btn ghost danger', type: 'button', onclick: (e) => confirmClick(e.currentTarget, '再按一次刪除', async () => { try { replaceTrade(await api('DELETE', `/trades/${t.id}`)); toast('已移到已刪除紀錄'); closeDrawer(); render(); } catch (er) { toast(er.message); } }) }, icon('trash', 17), '刪除')));
  layer.replaceChildren(h('div', { class: 'scrim', onclick: () => { if (D.dirty && !confirm('這筆還沒儲存，要放棄修改嗎？')) return; closeDrawer(); } }), drawer);
  const db = drawer.querySelector('.db'); if (db) db.scrollTop = keepScroll;
}
function kvRow(k, v, c) { return h('div', {}, h('span', {}, k), h('span', { class: c || '' }, v)); }
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { const v = $('.viewer'); if (v) { v.remove(); return; } if (state.drawer && !state.drawer.dirty) closeDrawer(); }
});

// ================================================================ 編輯 / 新增
PAGES.new = (page) => PAGES.edit(page, [], true);
PAGES.edit = (page, params, isNew) => {
  const t = isNew ? null : state.trades.find((x) => x.id === params[0]);
  if (!isNew && !t) { page.append(h('div', { class: 'empty' }, h('strong', {}, '找不到這筆交易'), h('a', { href: '#/trades' }, '回到紀錄'))); return; }
  const api_ = t && t.source === 'api';
  const draftKey = 'draft_' + (t ? t.id : 'new');
  const blank = { symbol: 'BTCUSDT', side: 'long', status: 'closed', entry: '', sl: '', tps: [''], exit: '', risk_amount: state.settings.defaultRisk ?? '', qty: '', leverage: '', open_time: toInput(new Date().toISOString()), close_time: '', pnl: '', fee: '',
    order_type: 'limit', setup: (state.settings.setups || [])[0] || '', conditions: [], emotions: [], mistakes: [], followed_rules: true, rule_note: '', reason: '', note: '', shots: [], tv_links: [] };
  const fromTrade = (x) => ({ ...blank, ...Object.fromEntries(Object.entries(x).map(([k, v]) => [k, v ?? (Array.isArray(blank[k]) ? [] : '')])), tps: (x.tps && x.tps.length ? x.tps : ['']).map(String), open_time: toInput(x.open_time), close_time: toInput(x.close_time) });
  const E = state._edit && state._edit.key === draftKey ? state._edit : (state._edit = { key: draftKey, f: t ? fromTrade(t) : { ...blank }, q: '', draftAsked: false });
  const f = E.f;
  const draft = lsGet(draftKey, null);
  const persist = () => lsSet(draftKey, f);
  const re = () => { persist(); render(); };

  page.append(pageHead('Edit trade', isNew ? '新增交易' : '編輯交易', { sub: api_ ? null : (isNew ? '手動新增：盈虧 = R × 風險金額（不含手續費），也可以直接填實際盈虧。' : null) }));
  if (api_) page.append(h('div', { class: 'notice' }, '來源：BingX 自動匯入 — 商品、方向、進場價、時間與盈虧以交易所為準，不可修改'));
  if (draft && !E.draftAsked && JSON.stringify(draft) !== JSON.stringify(f)) {
    page.append(h('div', { class: 'banner' }, '回復上次未完成的紀錄？',
      h('button', { class: 'linkbtn', type: 'button', onclick: () => { E.f = draft; E.draftAsked = true; render(); } }, '回復'),
      h('button', { class: 'linkbtn', type: 'button', style: 'color:var(--ink-2)', onclick: () => { lsDel(draftKey); E.draftAsked = true; render(); } }, '捨棄')));
  }

  const inp = (key, attrs = {}) => { const el = h('input', { type: 'text', inputmode: 'decimal', value: f[key] ?? '', ...attrs }); el.addEventListener('input', () => { f[key] = el.value; persist(); updSum(); }); return el; };
  // 左欄
  const syms = [...new Set(state.trades.map((x) => x.symbol))];
  const symIn = h('input', { type: 'text', value: f.symbol, list: 'symlist', readonly: api_ || null, 'aria-label': '幣種', style: 'font-family:var(--mono);font-weight:700' });
  symIn.addEventListener('input', () => { f.symbol = symIn.value.toUpperCase(); persist(); });
  const sideBtn = (v, l, c) => h('button', { type: 'button', class: 'sidebtn ' + c, 'aria-pressed': String(f.side === v), disabled: api_ || null, onclick: () => { f.side = v; re(); } }, l);
  const tpRows = f.tps.map((v, i) => { const el = h('input', { type: 'text', inputmode: 'decimal', value: v, 'aria-label': `TP${i + 1}` }); el.addEventListener('input', () => { f.tps[i] = el.value; persist(); updSum(); });
    return h('div', { class: 'tpline' }, `TP${i + 1}`, el, i > 0 ? h('button', { class: 'iconbtn', type: 'button', 'aria-label': '移除', onclick: () => { f.tps.splice(i, 1); re(); } }, icon('x', 16)) : h('span', {})); });
  const left = h('div', { class: 'col' },
    h('div', { class: 'symrow' }, h('div', {}, symIn, h('datalist', { id: 'symlist' }, syms.map((x) => h('option', { value: x })))), sideBtn('long', '做多', 'l'), sideBtn('short', '做空', 's')),
    h('div', { class: 'g2' }, h('label', { class: 'f' }, '進場價', inp('entry', { readonly: api_ || null })), h('label', { class: 'f' }, '止損價', inp('sl'))),
    h('div', { class: 'dsec' }, h('div', { class: 'h', style: 'font-weight:400;color:var(--ink-2);font-size:14px' }, '止盈目標（選填）'), tpRows,
      f.tps.length < 5 ? h('button', { class: 'linkbtn', type: 'button', style: 'justify-self:start;color:var(--ink-2)', onclick: () => { f.tps.push(''); re(); } }, '＋ 新增目標（至 TP5）') : null),
    h('div', { class: 'divider' }));
  if (api_) {
    const k = calc(t);
    left.append(h('div', { class: 'dsec' }, h('div', { class: 'h' }, '交易所資料（唯讀）'), h('div', { class: 'kv' },
      kvRow('結果', k.isOpen ? '持倉中' : '已平倉'), kvRow('實際盈虧', fmtU(k.pnl, 4), cls(k.pnl)), kvRow('出場價', fmt(k.exit, 8)), kvRow('開倉時間', fmtDT(t.open_time)), kvRow('平倉時間', fmtDT(t.close_time)),
      kvRow('數量', fmt(k.qty, 8)), kvRow('槓桿', `${fmt(k.lev)}x`), kvRow('手續費', fmt(t.fee, 6)))));
  } else {
    left.append(
      h('div', { class: 'g2' }, h('label', { class: 'f' }, '出場價', inp('exit')), h('label', { class: 'f' }, '風險金額 U', inp('risk_amount'), h('span', { class: 'hint muted' }, '這筆最多願意虧多少'))),
      h('div', { class: 'g2' }, h('label', { class: 'f' }, '開倉時間', (() => { const el = h('input', { type: 'datetime-local', value: f.open_time }); el.addEventListener('input', () => { f.open_time = el.value; persist(); }); return el; })()),
        h('label', { class: 'f' }, '平倉時間', (() => { const el = h('input', { type: 'datetime-local', value: f.close_time }); el.addEventListener('input', () => { f.close_time = el.value; persist(); }); return el; })())),
      h('div', { class: 'g2' }, h('label', { class: 'f' }, '實際盈虧 U（選填，填了就以這個為準）', inp('pnl', { placeholder: '自動算' })), h('label', { class: 'f' }, '槓桿（選填）', inp('leverage'))),
      h('div', { class: 'g2' }, h('label', { class: 'f' }, '數量（顆，選填）', inp('qty')), h('label', { class: 'f' }, '手續費 U（選填）', inp('fee'))),
      h('div', { class: 'dsec' }, h('div', { class: 'seg boxed', role: 'group', 'aria-label': '狀態' }, [['closed', '已平倉'], ['open', '持倉中']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(f.status === v), onclick: () => { f.status = v; re(); } }, l)))));
  }

  // 右欄
  const sum = h('div', { class: 'kv' });
  function updSum() {
    const fake = { ...f, entry: num(f.entry), sl: num(f.sl), exit: num(f.exit), qty: num(f.qty), leverage: num(f.leverage), risk_amount: num(f.risk_amount), pnl: num(f.pnl), tps: f.tps.map(num).filter(fin), open_time: fromInput(f.open_time) || t?.open_time, close_time: fromInput(f.close_time) || t?.close_time };
    if (api_) Object.assign(fake, { entry: t.entry, exit: t.exit, qty: t.qty, leverage: t.leverage, pnl: t.pnl, status: t.status, source: 'api' });
    const k = calc(fake);
    sum.replaceChildren(
      kvRow('實際交易額', k.posValue ? fmtU(k.posValue).replace('+', '') : '尚未設定'),
      kvRow('預估保證金', k.margin ? fmtU(k.margin).replace('+', '') + (k.lev ? ` · ${fmt(k.lev)}x` : '') : (k.lev ? `— · ${fmt(k.lev)}x` : '—')),
      kvRow('實際風險', k.risk ? fmtU(-k.risk) : '—', k.risk ? 'loss' : ''),
      kvRow('停損距離', fmtPct(k.stopPct, 2)),
      kvRow('TP1 R:R', k.rr ? `1 : ${k.rr.toFixed(2)}` : '—'),
      kvRow('建議倉位（風險 ÷ 停損%）', k.sugPos ? fmtU(k.sugPos).replace('+', '') : '—'),
      kvRow('建議槓桿', k.sugLev ? `≤ ${k.sugLev}x（最高 ${k.maxLev}x）` : '—', k.lev && k.maxLev && k.lev > k.maxLev ? 'loss' : ''),
      !api_ && k.closed ? kvRow('這筆結果', `${fmtU(k.pnl)} · ${fmtR(k.R)}`, cls(k.pnl)) : null);
  }
  updSum();
  const reasonIn = h('textarea', { placeholder: '看到什麼才進場？' }); reasonIn.value = f.reason || ''; reasonIn.addEventListener('input', () => { f.reason = reasonIn.value; persist(); });
  const noteIn = h('textarea', { placeholder: '結果如何？下次一樣會這樣做嗎？' }); noteIn.value = f.note || ''; noteIn.addEventListener('input', () => { f.note = noteIn.value; persist(); });
  const ruleIn = h('input', { type: 'text', placeholder: '哪裡沒照規則？例如：還沒 BOS 就先進場', value: f.rule_note || '' }); ruleIn.addEventListener('input', () => { f.rule_note = ruleIn.value; persist(); });
  const right = h('div', { class: 'col' },
    h('div', { class: 'dsec' }, h('div', { class: 'h' }, '計算摘要'), sum, h('div', { class: 'muted', style: 'font-size:13px' }, '填好止損和風險金額（或數量）後，才會計算實際風險與建議倉位。')),
    h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '進場條件', h('span', { class: 'opt' }, '選填'))),
      condPicker(f.conditions, f.side, (v) => { f.conditions = v; re(); }, { search: true, query: E.q, onQuery: (q) => { E.q = q; render(); setTimeout(() => { const el = $('.edit input[type=search]'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0); } })),
    h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '開單時的狀態', h('span', { class: 'opt' }, '選填'))), emoPicker(f.emotions, (v) => { f.emotions = v; re(); })),
    h('details', { class: 'more', open: E.moreOpen || null, ontoggle: (e) => { E.moreOpen = e.target.open; } }, h('summary', {}, '更多選項'),
      h('div', {},
        h('div', { class: 'g2', style: 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px' },
          h('label', { class: 'f' }, '策略', h('select', { onchange: (e) => { f.setup = e.target.value; persist(); } }, h('option', { value: '' }, '未分類'), [...new Set([...(state.settings.setups || []), f.setup].filter(Boolean))].map((x) => h('option', { value: x, selected: f.setup === x || null }, x)))),
          h('label', { class: 'f' }, '下單方式', h('select', { onchange: (e) => { f.order_type = e.target.value; persist(); } }, [['limit', '掛單'], ['market', '市價']].map(([v, l]) => h('option', { value: v, selected: f.order_type === v || null }, l))))),
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, '盤面連結 / 圖表附件'), shotEditor(f.shots || [], f.tv_links || [], (sh, tv) => { f.shots = sh; f.tv_links = tv; re(); }, { symbol: f.symbol, side: f.side, open_time: f.open_time, status: f.status, source: f.source })),
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, '這筆有照規則嗎？'), h('div', { class: 'seg boxed', role: 'group' }, [[true, '有'], [false, '沒有']].map(([v, l]) => h('button', { type: 'button', 'aria-pressed': String(f.followed_rules === v), onclick: () => { f.followed_rules = v; re(); } }, l))), f.followed_rules === false ? ruleIn : null),
        h('div', { class: 'dsec' }, h('div', { class: 'h' }, h('span', {}, '犯了什麼錯', h('span', { class: 'opt' }, '沒有就不用選'))), h('div', { class: 'tagbox' }, (state.settings.mistakes || []).map((m) => h('button', { type: 'button', class: 'tag', 'aria-pressed': String((f.mistakes || []).includes(m)), onclick: () => { const st = new Set(f.mistakes || []); st.has(m) ? st.delete(m) : st.add(m); f.mistakes = [...st]; re(); } }, m)))),
        h('label', { class: 'f' }, '進場理由', reasonIn),
        h('label', { class: 'f' }, '心得／復盤', noteIn))));

  page.append(h('div', { class: 'edit' }, left, right));
  const save = async () => {
    const body = { sl: num(f.sl), tps: f.tps.map(num).filter(fin), risk_amount: num(f.risk_amount), setup: f.setup, order_type: f.order_type, conditions: f.conditions, emotions: f.emotions, mistakes: f.mistakes,
      followed_rules: f.followed_rules, rule_note: f.rule_note, reason: f.reason, note: f.note, shots: f.shots, tv_links: f.tv_links };
    if (!api_) {
      if (!f.symbol.trim()) return toast('請輸入幣種');
      if (num(f.entry) == null) return toast('請填進場價');
      Object.assign(body, { symbol: f.symbol.trim(), side: f.side, status: f.status, entry: num(f.entry), exit: num(f.exit), qty: num(f.qty), leverage: num(f.leverage), pnl: num(f.pnl), fee: num(f.fee),
        open_time: fromInput(f.open_time), close_time: f.status === 'open' ? null : fromInput(f.close_time) || fromInput(f.open_time) });
    }
    saveBtn.disabled = true;
    try {
      const nt = t ? await api('PATCH', `/trades/${t.id}`, body) : await api('POST', '/trades', body);
      replaceTrade(nt); lsDel(draftKey); state._edit = null; toast('已儲存');
      go('#/trades'); setTimeout(() => openDrawer(nt.id, [nt.id]), 50);
    } catch (e) { toast(e.message); saveBtn.disabled = false; }
  };
  const saveBtn = h('button', { class: 'btn primary', type: 'button', onclick: save }, isNew ? '新增這筆' : '儲存變更', h('kbd', {}, '⌘↵'));
  page.append(h('div', { class: 'stickybar' }, h('button', { class: 'btn', type: 'button', onclick: () => { state._edit = null; lsDel(draftKey); history.length > 1 ? history.back() : go('#/trades'); } }, '取消'), saveBtn));
  page.onkeydown = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); save(); } };
};

// ================================================================ 日曆
PAGES.calendar = (page) => {
  const now = tw(new Date().toISOString());
  if (!state.cal.month) state.cal.month = now.mkey;
  const [Y, M] = state.cal.month.split('-').map(Number);
  const shift = (n) => { const d = new Date(Date.UTC(Y, M - 1 + n, 1)); state.cal.month = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`; state.cal.day = null; render(); };
  page.append(pageHead('Calendar', '交易日曆', { sub: '每日總盈虧 · 帳號時區 Asia/Taipei', actions: [
    h('button', { class: 'btn', type: 'button', 'aria-label': '上個月', onclick: () => shift(-1) }, icon('left', 18)),
    h('span', { class: 'btn mono', style: 'cursor:default' }, `${Y} 年 ${pad(M)} 月`),
    h('button', { class: 'btn', type: 'button', 'aria-label': '下個月', onclick: () => shift(1) }, icon('right', 18)), unitSeg()] }));
  const byDay = {};
  for (const t of live()) {
    const k = calc(t); const key = (k.closed ? k.c?.key : null) || k.o?.key; if (!key) continue;
    const b = (byDay[key] ||= { v: 0, nv: 0, n: 0, pend: false, open: false, list: [] });
    b.list.push(t); b.n++; if (k.pending) b.pend = true; if (k.isOpen) b.open = true;
    const v = val(k); if (fin(v)) { b.v += v; b.nv++; }
  }
  const first = new Date(Date.UTC(Y, M - 1, 1)); const startDow = first.getUTCDay(); const days = new Date(Date.UTC(Y, M, 0)).getUTCDate();
  const cells = h('div', { class: 'cells' });
  for (let i = 0; i < startDow; i++) cells.append(h('div', { class: 'cell out', 'aria-hidden': 'true' }));
  for (let d = 1; d <= days; d++) {
    const key = `${Y}-${pad(M)}-${pad(d)}`; const b = byDay[key];
    cells.append(h('button', { type: 'button', class: 'cell' + (b ? ' has' : '') + (key === now.key ? ' today' : '') + (state.cal.day === key ? ' sel' : ''), onclick: () => { state.cal.day = state.cal.day === key ? null : key; render(); } },
      h('span', { class: 'd' }, d),
      b && b.nv ? h('span', { class: 'p ' + cls(b.v) }, fmtS(b.v, state.unit === 'R' ? 2 : 2)) : h('span', {}),
      b ? h('span', { class: 'n' }, `${b.n} 筆`, b.pend ? h('i', { title: '有待補完的交易' }) : null) : h('span', {}),
      h('span', {}),
      b ? h('span', { class: 'bar', style: `background:${b.open ? 'var(--accent)' : b.nv ? (b.v >= 0 ? 'var(--gain)' : 'var(--loss)') : 'var(--line)'}` }) : h('span', {})));
  }
  const rem = (startDow + days) % 7; if (rem) for (let i = rem; i < 7; i++) cells.append(h('div', { class: 'cell out', 'aria-hidden': 'true' }));
  const cal = h('div', { class: 'cal' }, h('div', { class: 'dows' }, WD.map((w) => h('span', {}, w))), cells);
  const legend = h('div', { class: 'legend', style: 'margin-top:10px' }, h('span', {}, h('i', { style: 'width:6px;height:6px;border-radius:50%;background:var(--amber)' }), '待補完'), h('span', {}, h('i', { style: 'background:var(--accent);width:3px;height:12px' }), '仍持有'), h('span', {}, h('i', { style: 'background:var(--gain)' }), '當日賺'), h('span', {}, h('i', { style: 'background:var(--loss)' }), '當日賠'));

  const mDays = Object.entries(byDay).filter(([k]) => k.startsWith(state.cal.month));
  const mRows = mDays.flatMap(([, b]) => b.list);
  const ma = agg(mRows);
  const dayVals = mDays.filter(([, b]) => b.nv).map(([k, b]) => [k, b.v]);
  const best = dayVals.slice().sort((a, b) => b[1] - a[1])[0]; const worst = dayVals.slice().sort((a, b) => a[1] - b[1])[0];
  const pend = mRows.filter((t) => calc(t).pending).length;
  const md = (k) => k ? k.slice(5).replace('-', '/') : '';
  const summ = h('div', { class: 'summ' }, h('div', { class: 'h' }, '本月摘要'), h('div', { class: 'muted', style: 'font-size:13px;margin-top:8px' }, '本月盈虧'),
    h('div', { class: 'big ' + cls(ma.n ? ma.total() : 0) }, ma.n ? fmtV(ma.total()) : '—'),
    h('div', { class: 'muted' }, `${mRows.length} 筆 · ${mDays.length} 個交易日`), h('div', { class: 'muted' }, `獲利 ${ma.wins} · `, h('span', { class: 'loss' }, `虧損 ${ma.losses}`)),
    h('div', { class: 'kv', style: 'margin-top:12px;border-top:1px solid var(--line)' },
      kvRow('最佳日', best && best[1] > 0 ? `${md(best[0])} · ${fmtV(best[1])}` : '—', 'gain'), kvRow('最差日', worst && worst[1] < 0 ? `${md(worst[0])} · ${fmtV(worst[1])}` : '—', 'loss'),
      h('div', {}, h('span', { class: 'amber' }, '待補完'), h('a', { href: '#/trades/pending', class: 'amber mono' }, `${pend} 筆 →`))));
  const leftCol = h('div', {}, cal, legend);
  if (state.cal.day) leftCol.append(dayPanel(state.cal.day, byDay[state.cal.day]));
  page.append(h('div', { class: 'calwrap' }, leftCol, summ));
};
function dayPanel(key, b) {
  const list = (b?.list || []).slice().sort((x, y) => (calc(x).o?.ms || 0) - (calc(y).o?.ms || 0));
  const ta = h('textarea', { placeholder: '今天的盤面怎麼走？哪一筆做得好、哪一筆不該做？明天要注意什麼？', rows: 5 }); ta.value = state.reviews[key] || '';
  const save = h('button', { class: 'btn primary', type: 'button' }, '儲存復盤');
  save.addEventListener('click', async () => { save.disabled = true; try { await api('PUT', `/reviews/${key}`, { note: ta.value }); state.reviews[key] = ta.value; toast('已儲存復盤'); } catch (e) { toast(e.message); } save.disabled = false; });
  const p = tw(new Date(keyToMs(key) + 1).toISOString());
  return h('div', { class: 'card', style: 'margin-top:20px;display:grid;gap:12px' },
    h('div', { class: 'sec-h' }, h('h2', {}, `${p.m}月${p.d}日 週${WD[p.dow]} 的復盤`), b && b.nv ? h('span', { class: 'mono ' + cls(b.v) }, fmtV(b.v)) : null),
    list.length ? h('div', {}, list.map((t) => tradeRow(t, list.map((x) => x.id), { compact: true }))) : h('div', { class: 'muted' }, '這天沒有交易，一樣可以寫盤面觀察。'),
    h('label', { class: 'f' }, '當天復盤心得', ta), h('div', {}, save));
}
