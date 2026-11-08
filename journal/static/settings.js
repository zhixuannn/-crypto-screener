/* 設定、API 串接、CSV 匯入、啟動 */
'use strict';

// ================================================================ 設定
PAGES.settings = (page) => {
  const st = state.settings;
  const S = state._set || (state._set = JSON.parse(JSON.stringify({ displayName: st.displayName, tagline: st.tagline, capital: st.capital, defaultRisk: st.defaultRisk, makerFee: st.makerFee, takerFee: st.takerFee, colorMode: st.colorMode, requireShot: st.requireShot !== false,
    setups: st.setups || [], conditions: condList(), emotions: emoList(), mistakes: st.mistakes || [], benchmarks: st.benchmarks || [] })));
  const dirty = () => { saveBtn.disabled = false; };
  const txt = (key, attrs = {}) => { const el = h('input', { type: 'text', value: S[key] ?? '', ...attrs }); el.addEventListener('input', () => { S[key] = attrs.inputmode ? num(el.value) : el.value; dirty(); }); return el; };
  page.append(pageHead('Settings', '設定', { actions: [] }));

  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '基本')), h('div', { class: 'grid2' },
    h('label', { class: 'f' }, '顯示名稱（總覽的打招呼）', txt('displayName')), h('label', { class: 'f' }, '提醒自己的一句話', txt('tagline')),
    h('label', { class: 'f' }, '本金 U', txt('capital', { inputmode: 'decimal' })), h('label', { class: 'f' }, '每筆預設風險金額 U（手動新增和建議倉位用）', txt('defaultRisk', { inputmode: 'decimal' })),
    h('label', { class: 'f' }, '掛單手續費 %（BingX 一般 0.02）', txt('makerFee', { inputmode: 'decimal' })), h('label', { class: 'f' }, '市價手續費 %（BingX 一般 0.05）', txt('takerFee', { inputmode: 'decimal' })))));

  const theme = lsGet('theme', 'auto');
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '外觀與待補規則')), h('div', { class: 'grid2' },
    h('label', { class: 'f' }, '深淺色（只影響這台裝置）', h('select', { onchange: (e) => { lsSet('theme', e.target.value); applyAppearance(); } }, [['auto', '跟著系統'], ['light', '淺色'], ['dark', '深色（藏青）']].map(([v, l]) => h('option', { value: v, selected: theme === v || null }, l)))),
    h('label', { class: 'f' }, '漲跌顏色', h('select', { onchange: (e) => { S.colorMode = e.target.value; document.documentElement.dataset.updown = e.target.value === 'redUp' ? 'red' : 'green'; dirty(); } }, [['greenUp', '綠漲紅跌（跟 BingX 一樣）'], ['redUp', '紅漲綠跌（跟台股一樣）']].map(([v, l]) => h('option', { value: v, selected: S.colorMode === v || null }, l)))),
    h('label', { class: 'f', style: 'grid-column:1/-1;display:flex;gap:10px;align-items:center' }, h('input', { type: 'checkbox', checked: S.requireShot, style: 'width:20px;height:20px;accent-color:var(--accent)', onchange: (e) => { S.requireShot = e.target.checked; dirty(); } }), '沒有盤面截圖（或 TradingView 連結）的交易算「待補完」')),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:8px' }, '「待補完」＝少了止損（算不出 R）、進場條件，或盤面截圖。')));

  // 進場條件、情緒、犯錯、策略：可新增、刪除、改名、拖曳或上下箭頭排序（排序就是新增交易時的顯示順序）
  page.append(tagEditor(S, 'conditions', { kind: 'cond', title: '進場條件', desc: '整理你的進場訊號，讓新增交易與後續分析更清楚。「偏做多」的條件在做空單會被鎖住，反過來也一樣。', dirty }));
  page.append(tagEditor(S, 'emotions', { kind: 'emo', title: '開單時的狀態', desc: '「正面」的情緒會算進雷達圖的情緒穩定度。', dirty }));
  page.append(h('div', { class: 'grid2' }, tagEditor(S, 'mistakes', { kind: 'plain', title: '犯錯標籤', dirty }), tagEditor(S, 'setups', { kind: 'plain', title: '策略', dirty })));

  const bmBox = h('div', { class: 'edlist' });
  const drawBm = () => bmBox.replaceChildren(...S.benchmarks.map((b, i) => h('div', { class: 'edrow' },
    (() => { const el = h('input', { type: 'text', value: b.setup, 'aria-label': '策略名稱' }); el.addEventListener('input', () => { b.setup = el.value; dirty(); }); return el; })(),
    (() => { const el = h('input', { type: 'text', inputmode: 'decimal', value: b.win, 'aria-label': '勝率', placeholder: '勝率%' }); el.addEventListener('input', () => { b.win = num(el.value) ?? 0; dirty(); }); return el; })(),
    (() => { const el = h('input', { type: 'text', inputmode: 'decimal', value: b.pf, 'aria-label': 'PF', placeholder: 'PF' }); el.addEventListener('input', () => { b.pf = num(el.value) ?? 0; dirty(); }); return el; })(),
    h('button', { class: 'iconbtn', type: 'button', 'aria-label': '刪除', onclick: () => { S.benchmarks.splice(i, 1); drawBm(); dirty(); } }, icon('x', 16)))));
  drawBm();
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '回測預期'), h('div', { class: 'desc' }, '策略名稱、勝率 %、PF。用在分析頁的「實盤 vs 回測」。'))), bmBox,
    h('button', { class: 'btn sm', type: 'button', style: 'margin-top:10px', onclick: () => { S.benchmarks.push({ setup: '', win: 50, pf: 1 }); drawBm(); dirty(); } }, '＋ 新增')));

  page.append(csvCard());
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '帳號')), h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, h('a', { class: 'btn', href: '/journal/api/export.csv' }, '匯出全部紀錄（CSV）'), h('a', { class: 'btn', href: '/journal/logout' }, '登出')),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:10px' }, state.store === 'supabase' ? '資料存在 Supabase。' : '⚠ 目前沒有連上 Supabase，資料只存在伺服器記憶體，重新部署就會不見。請到 Render 設定 SUPABASE_URL 和 SUPABASE_SERVICE_KEY。')));

  const saveBtn = h('button', { class: 'btn primary', type: 'button', disabled: true }, '儲存設定');
  saveBtn.addEventListener('click', async () => {
    const body = { ...S, conditions: S.conditions.filter((c) => c.name.trim()).map((c) => ({ ...c, name: c.name.trim() })), emotions: S.emotions.filter((e) => e.name.trim()), mistakes: S.mistakes.map((x) => x.trim()).filter(Boolean),
      setups: S.setups.map((x) => x.trim()).filter(Boolean), benchmarks: S.benchmarks.filter((b) => b.setup.trim()) };
    saveBtn.disabled = true;
    try { state.settings = await api('PUT', '/settings', body); state._set = null; toast('已儲存設定'); render(); } catch (e) { toast(e.message); saveBtn.disabled = false; }
  });
  page.append(h('div', { class: 'stickybar' }, h('button', { class: 'btn', type: 'button', onclick: () => { state._set = null; render(); } }, '還原'), saveBtn));
};

// ================================================================ 標籤清單編輯器
const TONE_COLOR = { good: 'green', warn: 'yellow', bad: 'red' };
const DIR_OPTS = [['short', '偏做空'], ['long', '偏做多'], ['both', '多空都可']];
const TONE_OPTS = [['good', '正面'], ['warn', '普通'], ['bad', '負面']];
function tagEditor(S, key, { kind, title, desc, dirty }) {
  const list = S[key];
  const defs = (state.defaults || {})[key] || [];
  const nameOf = (it) => kind === 'plain' ? it : it.name;
  const setName = (i, v) => { if (kind === 'plain') list[i] = v; else list[i].name = v; };
  const colorOf = (it) => kind === 'cond' ? (it.color || 'gray') : kind === 'emo' ? TONE_COLOR[it.tone] || 'gray' : null;
  const badge = (it) => {
    const d = defs.find((x) => (typeof x === 'string' ? x : x.name) === nameOf(it));
    if (!d) return ['使用者自訂', ''];
    const same = kind === 'plain' || (kind === 'cond' ? d.dir === it.dir && d.color === it.color : d.tone === it.tone);
    return same ? ['系統預設', 'sys'] : ['已自訂', ''];
  };
  const count = h('span', { class: 'pill-badge' });
  const box = h('div', { class: 'trlist' });
  let dragFrom = null;
  const move = (from, to) => { if (to < 0 || to >= list.length || from === to) return; const [it] = list.splice(from, 1); list.splice(to, 0, it); draw(); dirty(); };
  const sel = (opts, cur, label, onch) => h('select', { 'aria-label': label, onchange: (e) => { onch(e.target.value); draw(); dirty(); } }, opts.map(([v, l]) => h('option', { value: v, selected: cur === v || null }, l)));
  function draw() {
    count.textContent = `${list.length} 項`;
    box.replaceChildren(...list.map((it, i) => {
      const color = colorOf(it); const [btxt, bcls] = badge(it);
      const nm = h('input', { type: 'text', class: 'nm', value: nameOf(it), 'aria-label': '名稱' });
      nm.addEventListener('input', () => { setName(i, nm.value); dirty(); });
      nm.addEventListener('change', () => draw());
      const handle = h('span', { class: 'handle', title: '拖曳排序', 'aria-hidden': 'true' }, '⠿');
      const row = h('div', { class: 'trw', style: color ? `--tc:${COLOR_VAR[color]}` : '' },
        handle, color ? h('i', { class: 'dot', style: `background:${COLOR_VAR[color]}` }) : h('i', { class: 'dot', style: 'background:var(--line)' }), nm,
        h('div', { class: 'meta' },
          kind === 'cond' ? sel(DIR_OPTS, it.dir, '方向', (v) => { it.dir = v; }) : null,
          kind === 'cond' ? sel(Object.entries(COLOR_NAMES).map(([v, l]) => [v, l + '色']), it.color, '顏色', (v) => { it.color = v; }) : null,
          kind === 'emo' ? sel(TONE_OPTS, it.tone, '性質', (v) => { it.tone = v; }) : null,
          h('span', { class: 'pill-badge ' + bcls }, btxt)),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': `把「${nameOf(it)}」往上移`, disabled: i === 0 || null, onclick: () => move(i, i - 1) }, icon('up', 18)),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': `把「${nameOf(it)}」往下移`, disabled: i === list.length - 1 || null, onclick: () => move(i, i + 1) }, icon('down', 18)),
        h('button', { class: 'iconbtn', type: 'button', 'aria-label': `刪除「${nameOf(it)}」`, onclick: () => { list.splice(i, 1); draw(); dirty(); } }, icon('trash', 17)));
      // 用 pointer 事件自己做拖曳，滑鼠和手機觸控都能用
      row.dataset.idx = i;
      handle.style.touchAction = 'none';
      handle.addEventListener('pointerdown', (e) => {
        e.preventDefault(); handle.setPointerCapture(e.pointerId); dragFrom = i; row.classList.add('dragging');
        let target = null;
        const clear = () => box.querySelectorAll('.drop-before,.drop-after').forEach((x) => x.classList.remove('drop-before', 'drop-after'));
        const onMove = (ev) => {
          const rows = [...box.children]; clear(); target = null;
          for (const r of rows) { const bb = r.getBoundingClientRect(); if (ev.clientY < bb.top + bb.height / 2) { target = +r.dataset.idx; r.classList.add('drop-before'); return; } }
          target = rows.length; rows[rows.length - 1]?.classList.add('drop-after');
        };
        const onUp = () => {
          handle.removeEventListener('pointermove', onMove); handle.removeEventListener('pointerup', onUp); handle.removeEventListener('pointercancel', onUp);
          row.classList.remove('dragging'); clear();
          const from = dragFrom; dragFrom = null;
          if (target == null || from == null) return;
          const to = target > from ? target - 1 : target;
          move(from, to);
        };
        handle.addEventListener('pointermove', onMove); handle.addEventListener('pointerup', onUp); handle.addEventListener('pointercancel', onUp);
      });
      return row;
    }));
  }
  draw();
  // 新增
  const nIn = h('input', { type: 'text', placeholder: kind === 'cond' ? '新增條件，例如 4H流動性獵取' : '新增一項', 'aria-label': `新增${title}` });
  let nDir = 'both', nColor = 'blue', nTone = 'warn';
  const nDirSel = kind === 'cond' ? h('select', { 'aria-label': '方向', onchange: (e) => { nDir = e.target.value; nColor = nDir === 'short' ? 'red' : nDir === 'long' ? 'green' : 'blue'; nColSel.value = nColor; } }, DIR_OPTS.map(([v, l]) => h('option', { value: v, selected: v === 'both' || null }, l))) : null;
  const nColSel = kind === 'cond' ? h('select', { 'aria-label': '顏色', onchange: (e) => { nColor = e.target.value; } }, Object.entries(COLOR_NAMES).map(([v, l]) => h('option', { value: v, selected: v === 'blue' || null }, l + '色'))) : null;
  const nToneSel = kind === 'emo' ? h('select', { 'aria-label': '性質', onchange: (e) => { nTone = e.target.value; } }, TONE_OPTS.map(([v, l]) => h('option', { value: v, selected: v === 'warn' || null }, l))) : null;
  const add = () => {
    const v = nIn.value.trim(); if (!v) return;
    if (list.some((it) => nameOf(it) === v)) return toast('已經有這一項了');
    list.push(kind === 'cond' ? { name: v, dir: nDir, color: nColor } : kind === 'emo' ? { name: v, tone: nTone } : v);
    nIn.value = ''; draw(); dirty(); nIn.focus();
  };
  nIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  return h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('div', { class: 'eyebrow', style: 'font-size:12px;letter-spacing:.16em;font-weight:700;color:var(--muted)' }, 'SETTINGS'), h('h2', { style: 'font-size:19px;letter-spacing:0' }, title), desc ? h('div', { class: 'desc', style: 'font-size:14.5px' }, desc) : null), count),
    box, h('div', { class: 'addrow', style: 'margin-top:12px' }, nIn, nDirSel, nColSel, nToneSel, h('button', { class: 'btn sm primary', type: 'button', onclick: add }, '＋ 新增')));
}

// ================================================================ CSV 匯入
const IMP_FIELDS = [
  ['open_time', '開倉時間', ['開倉時間', 'open time', 'opening time', 'create time', '建立時間', '時間', 'time', 'date']],
  ['close_time', '平倉時間', ['平倉時間', 'close time', 'closing time', 'update time', '成交時間']],
  ['symbol', '幣種', ['交易對', '合約', 'symbol', 'pair', '幣種']],
  ['side', '方向', ['方向', '倉位方向', 'side', 'direction', 'position side', '持倉方向']],
  ['entry', '開倉均價', ['開倉均價', '開倉價格', 'avg. open price', 'entry price', 'open price', '開倉價']],
  ['exit', '平倉均價', ['平倉均價', '平倉價格', 'avg. close price', 'close price', 'exit price', '平倉價']],
  ['qty', '數量（顆）', ['數量', '平倉數量', 'qty', 'quantity', 'amount', 'size']],
  ['pnl', '實際盈虧', ['已實現盈虧', '已實現損益', '收益', 'realized pnl', 'realized profit', 'pnl', 'profit', '盈虧']],
  ['fee', '手續費', ['手續費', 'fee', 'fees', 'commission', 'trading fee']],
];
function parseCSV(text) {
  text = text.replace(/^﻿/, ''); const first = text.split(/\r?\n/)[0] || '';
  const delim = (first.match(/;/g) || []).length > (first.match(/,/g) || []).length ? ';' : (first.includes('\t') ? '\t' : ',');
  const out = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch; }
    else if (ch === '"') q = true; else if (ch === delim) { row.push(cur); cur = ''; }
    else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i++; row.push(cur); out.push(row); row = []; cur = ''; }
    else cur += ch;
  }
  if (cur !== '' || row.length) { row.push(cur); out.push(row); }
  return out.filter((r) => r.some((c) => c.trim() !== ''));
}
function csvTime(v) {
  if (!v) return null; v = String(v).trim();
  if (/^\d{10,13}$/.test(v)) return new Date(v.length === 13 ? +v : +v * 1000).toISOString();
  const m = v.replace(/\//g, '-').match(/(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?/);
  return m ? new Date(`${m[1]}-${pad(m[2])}-${pad(m[3])}T${pad(m[4])}:${m[5]}:${m[6] || '00'}+08:00`).toISOString() : null;
}
function csvCard() {
  const C = state._csv || (state._csv = { headers: [], rows: [], map: {}, name: '' });
  const file = h('input', { type: 'file', accept: '.csv,text/csv,text/plain', 'aria-label': '選擇 CSV 檔' });
  file.addEventListener('change', () => {
    const f = file.files[0]; if (!f) return; const rd = new FileReader();
    rd.onload = () => { const rows = parseCSV(String(rd.result)); if (rows.length < 2) return toast('檔案裡找不到資料'); C.headers = rows[0]; C.rows = rows.slice(1); C.name = f.name;
      const low = C.headers.map((x) => x.trim().toLowerCase());
      for (const [key, , alts] of IMP_FIELDS) { let i = low.findIndex((hd) => alts.some((a) => hd === a.toLowerCase())); if (i < 0) i = low.findIndex((hd) => alts.some((a) => hd.includes(a.toLowerCase()))); C.map[key] = i; }
      render(); };
    rd.readAsText(f);
  });
  const card = h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '匯入 CSV'), h('div', { class: 'desc' }, '有接 API 就不用這個。適合匯入很久以前的紀錄或其他交易所的匯出檔。'))), file);
  if (!C.rows.length) return card;
  const mapRow = (r) => { const g = (k) => C.map[k] >= 0 ? r[C.map[k]] : null; const sideRaw = String(g('side') || '').toLowerCase();
    return { symbol: String(g('symbol') || '').replace(/[-_/]/g, '').toUpperCase(), side: /short|sell|空/.test(sideRaw) ? 'short' : 'long', status: 'closed', open_time: csvTime(g('open_time')), close_time: csvTime(g('close_time')) || csvTime(g('open_time')),
      entry: num(g('entry')), exit: num(g('exit')), qty: num(g('qty')) != null ? Math.abs(num(g('qty'))) : null, pnl: num(g('pnl')), fee: num(g('fee')) != null ? Math.abs(num(g('fee'))) : null, source: 'csv' }; };
  const grid = h('div', { class: 'grid3', style: 'margin-top:14px' }, IMP_FIELDS.map(([key, label]) => h('label', { class: 'f' }, label,
    h('select', { onchange: (e) => { C.map[key] = +e.target.value; render(); } }, h('option', { value: -1 }, '（沒有）'), C.headers.map((hd, i) => h('option', { value: i, selected: C.map[key] === i || null }, hd))))));
  const prev = C.rows.slice(0, 5).map(mapRow);
  const go_ = h('button', { class: 'btn primary', type: 'button' }, `匯入 ${C.rows.length} 筆`);
  go_.addEventListener('click', async () => {
    const seen = new Set(state.trades.map((t) => `${t.symbol}|${t.open_time}|${t.side}`));
    const list = C.rows.map(mapRow).filter((t) => t.symbol && t.open_time && !seen.has(`${t.symbol}|${t.open_time}|${t.side}`));
    go_.disabled = true;
    try { const r = await api('POST', '/trades/bulk', { trades: list }); toast(`匯入 ${r.created} 筆，略過 ${C.rows.length - r.created} 筆（重複或缺資料）`); state._csv = null; await reload(); } catch (e) { toast(e.message); go_.disabled = false; }
  });
  card.append(h('div', { class: 'muted', style: 'margin-top:12px' }, `${C.name}，共 ${C.rows.length} 列，請確認欄位對應：`), grid,
    h('div', { class: 'tbl-wrap', style: 'margin-top:14px' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['開倉', '幣種', '方向', '開倉價', '平倉價', '數量', '盈虧', '手續費'].map((x) => h('th', {}, x)))),
      h('tbody', {}, prev.map((p) => h('tr', {}, h('td', {}, fmtDT(p.open_time)), h('td', {}, p.symbol), h('td', {}, p.side === 'short' ? '空' : '多'), h('td', { class: 'n' }, fmt(p.entry, 6)), h('td', { class: 'n' }, fmt(p.exit, 6)), h('td', { class: 'n' }, fmt(p.qty, 6)), h('td', { class: 'n ' + cls(p.pnl) }, fmtS(p.pnl)), h('td', { class: 'n' }, fmt(p.fee, 4))))))),
    h('div', { style: 'display:flex;gap:10px;margin-top:14px' }, go_, h('button', { class: 'btn', type: 'button', onclick: () => { state._csv = null; render(); } }, '取消')),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:8px' }, '同幣種、同開倉時間、同方向的交易會自動略過。匯入的單沒有止損，之後點進去補。'));
  return card;
}

// ================================================================ API 串接
PAGES.api = (page) => {
  const st = state.sync;
  page.append(pageHead('API', 'API 串接', { sub: 'BingX 永續合約 · 只讀取成交紀錄，不會下單', actions: [syncButton()] }));
  const dot = (ok) => h('span', { class: 'status-dot', style: `background:${ok ? 'var(--up)' : 'var(--amber)'}` });
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, 'BingX 帳戶')),
    h('div', { class: 'kv' },
      h('div', {}, h('span', {}, 'API 金鑰'), h('span', {}, dot(st.has_keys), st.has_keys ? '已設定（存在 Render，不會顯示在這裡）' : '尚未設定')),
      h('div', {}, h('span', {}, '資料庫'), h('span', {}, dot(state.store === 'supabase'), state.store === 'supabase' ? 'Supabase' : '記憶體（重開會不見）')),
      kvRow('自動同步', st.has_keys ? `每 ${st.interval_minutes || 5} 分鐘` : '—'),
      kvRow('上次同步', st.finished_at ? fmtDTY(st.finished_at) : '還沒同步過'),
      h('div', {}, h('span', {}, '結果'), h('span', { class: st.error ? 'loss' : '' }, st.running ? '同步中…' : st.error ? '失敗' : st.finished_at ? `成功：新增 ${st.added || 0}、更新 ${st.updated || 0}` : '—')),
      st.symbols ? kvRow('這次查過的幣種', (st.symbols || []).join('、') || '—') : null,
      st.open_count != null ? kvRow('目前持倉', `${st.open_count} 筆`) : null,
      st.seconds != null ? kvRow('耗時', `${st.seconds} 秒`) : null),
    st.error ? h('div', { class: 'banner err', style: 'margin-top:12px;font-family:var(--mono);font-size:13px' }, st.error) : null,
    h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;margin-top:16px' },
      h('button', { class: 'btn primary', type: 'button', disabled: !st.has_keys || st.running || null, onclick: () => doSync(false) }, '立即同步'),
      h('button', { class: 'btn', type: 'button', disabled: !st.has_keys || st.running || null, onclick: (e) => confirmClick(e.currentTarget, `再按一次重抓 ${st.backfill_days || 90} 天`, () => doSync(true)) }, `重新抓過去 ${st.backfill_days || 90} 天`)),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:10px' }, '重抓不會蓋掉你補過的止損、條件、截圖和心得，只會更新交易所的欄位。')));
  page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '怎麼設定')),
    h('ol', { class: 'steps' },
      h('li', {}, '到 BingX → 帳戶 → API 管理，建立新的 API。權限只勾「讀取」，不要開交易和提幣。'),
      h('li', {}, '如果 BingX 要求綁 IP，填 Render 服務的對外 IP（Render 後台 → 你的服務 → Connect → Outbound 可以看到）。'),
      h('li', {}, '到 Render → 你的服務 → Environment，新增 ', h('code', {}, 'BINGX_API_KEY'), ' 和 ', h('code', {}, 'BINGX_API_SECRET'), '，存檔後服務會自動重新部署。'),
      h('li', {}, '回到這頁按「立即同步」。第一次會往回抓 90 天，可能要一兩分鐘。'))));
  if (st.sample) page.append(h('details', { class: 'card more' }, h('summary', {}, '最近一筆交易所原始資料（除錯用）'), h('div', {}, h('pre', { class: 'raw' }, JSON.stringify(st.sample, null, 2)))));
};

// ================================================================ 啟動
state.route = parseRoute();
render();
reload().catch((e) => { const page = $('.page'); if (page) page.replaceChildren(h('div', { class: 'banner err' }, '載入失敗：' + e.message)); });
setInterval(() => { if (!document.hidden && !state.sync.running && state.loaded && !state.drawer && !['edit', 'new', 'settings'].includes(state.route.page)) reload().catch(() => { }); }, 5 * 60 * 1000);
