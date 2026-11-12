/* 設定、API 串接、CSV 匯入、啟動 */
'use strict';

// ================================================================ 設定（照超人：一行一行的清單，點進去才編輯）
Object.assign(ICONS, {
  st_trade: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  st_cond: '<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="M13.5 6.5l3 3"/>',
  st_emo: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3"/><path d="M6.5 18.5a6 6 0 0 1 11 0"/>',
  st_tag: '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
  st_bench: '<path d="M4 19h16"/><path d="M7 15l3-4 3 2 4-6"/>',
  st_api: '<circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3"/><path d="M17 6l3 3"/><path d="M15 8l2 2"/>',
  st_import: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6"/><path d="M9 14l3 3 3-3"/>',
  st_bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  st_palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.6-.8 1.6-1.6 0-.5-.2-.8-.5-1.1-.3-.3-.5-.7-.5-1.1 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4.3-4-7.6-9-7.6z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  st_export: '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
  st_shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  st_info: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
});

function setDraft() {
  const st = state.settings;
  return state._set || (state._set = JSON.parse(JSON.stringify({ displayName: st.displayName, tagline: st.tagline, capital: st.capital, defaultRisk: st.defaultRisk, makerFee: st.makerFee, takerFee: st.takerFee, colorMode: st.colorMode, requireShot: st.requireShot !== false,
    setups: st.setups || [], conditions: condList(), emotions: emoList(), mistakes: st.mistakes || [], benchmarks: st.benchmarks || [] })));
}
function curTheme() {
  const th = lsGet('theme', 'auto');
  if (th !== 'auto') return th;
  return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function themeToggle() {
  const cur = curTheme();
  const b = (v, ic, l) => h('button', { type: 'button', 'aria-pressed': String(cur === v), onclick: (e) => { e.stopPropagation(); lsSet('theme', v); applyAppearance(); render(); } }, icon(ic, 17), l);
  return h('div', { class: 'seg boxed st-theme', role: 'group', 'aria-label': '外觀模式' }, b('light', 'sun', '淺色'), b('dark', 'moon', '深色'));
}
const NOTIFY_KEYS = [['review_on', '每日復盤'], ['pending_on', '待補完'], ['paper_on', '紙上驗證'], ['sync_on', '同步出問題']];

PAGES.settings = (page, params = []) => {
  const sec = params[0];
  if (sec && SETTINGS_SUB[sec]) return SETTINGS_SUB[sec](page);
  const st = state.settings;
  const n = state.notify || {};
  const onCount = NOTIFY_KEYS.filter(([k]) => n[k]).length;
  page.append(pageHead('Settings', '設定', { sub: '本金、條件、通知、備份和帳號安全' }));
  const row = (ic, title, sub, right, href) => h(href ? 'a' : 'div', { class: 'st-row', href: href || null },
    h('span', { class: 'st-ic' }, icon(ic, 21)),
    h('span', { class: 'st-tx' }, h('b', {}, title), h('small', {}, sub)),
    h('span', { class: 'st-val' }, right), href ? h('span', { class: 'st-chev' }, icon('right', 18)) : null);
  page.append(h('div', { class: 'st-list' },
    row('st_trade', '交易設定', '本金與交易偏好', `${fmt(num(st.capital))} U`, '#/settings/trade'),
    row('st_cond', '進場條件', '新增交易時使用的條件', `${condList().length} 項`, '#/settings/conditions'),
    row('st_emo', '開單狀態管理', '交易當下的心理狀態', `${emoList().length} 項`, '#/settings/emotions'),
    row('st_tag', '犯錯標籤與策略', '檢討用的標籤、策略分類', `${(st.mistakes || []).length} / ${(st.setups || []).length} 項`, '#/settings/tags'),
    row('st_bench', '回測預期', '分析頁的「實盤 vs 回測」', `${(st.benchmarks || []).length} 個策略`, '#/settings/bench'),
    row('st_api', 'API 串接', 'BingX 唯讀同步', state.sync.has_keys ? '已連線' : '前往', '#/api'),
    row('st_import', '資料匯入', 'BingX CSV 歷史交易', '先預覽再匯入', '#/settings/import'),
    row('st_bell', '通知設定', '復盤、待補完、紙上驗證與同步提醒', onCount ? `已開 ${onCount} 項` : '尚未開啟', '#/settings/notify'),
    row('st_palette', '外觀模式', '深色 / 淺色', themeToggle(), null),
    row('st_export', '資料匯出', 'CSV 與 Email 備份', '可使用', '#/settings/export'),
    row('st_shield', '安全設定', '密碼與登入方式', '查看', '#/settings/security'),
    row('st_info', '關於我們', '版本與更新', (state.about || {}).version || '—', '#/settings/about')));
};

// 子頁共用：上面有「← 設定」
function subHead(page, title, sub) {
  page.append(h('a', { class: 'st-back', href: '#/settings' }, icon('left', 18), '設定'));
  page.append(pageHead(null, title, { sub }));
}
// 交易設定／條件／狀態／標籤／回測：共用一份草稿，按「儲存設定」才送出
function draftBar(page) {
  const S = setDraft();
  const saveBtn = h('button', { class: 'btn primary', type: 'button', disabled: !state._setDirty || null }, '儲存設定');
  const dirty = () => { state._setDirty = true; saveBtn.disabled = false; };
  saveBtn.addEventListener('click', async () => {
    const body = { ...S, conditions: S.conditions.filter((c) => c.name.trim()).map((c) => ({ ...c, name: c.name.trim() })), emotions: S.emotions.filter((e) => e.name.trim()), mistakes: S.mistakes.map((x) => x.trim()).filter(Boolean),
      setups: S.setups.map((x) => x.trim()).filter(Boolean), benchmarks: S.benchmarks.filter((b) => b.setup.trim()) };
    saveBtn.disabled = true;
    try { state.settings = await api('PUT', '/settings', body); state._set = null; state._setDirty = false; toast('已儲存設定'); render(); } catch (e) { toast(e.message); saveBtn.disabled = false; }
  });
  return { S, dirty, bar: () => page.append(h('div', { class: 'stickybar' }, h('button', { class: 'btn', type: 'button', onclick: () => { state._set = null; state._setDirty = false; render(); } }, '還原'), saveBtn)) };
}

const SETTINGS_SUB = {
  trade(page) {
    subHead(page, '交易設定', '本金與交易偏好');
    const { S, dirty, bar } = draftBar(page);
    const txt = (key, attrs = {}) => { const el = h('input', { type: 'text', value: S[key] ?? '', ...attrs }); el.addEventListener('input', () => { S[key] = attrs.inputmode ? num(el.value) : el.value; dirty(); }); return el; };
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '本金與風險')), h('div', { class: 'grid2' },
      h('label', { class: 'f' }, '本金 U', txt('capital', { inputmode: 'decimal' })), h('label', { class: 'f' }, '每筆預設風險金額 U（手動新增和建議倉位用）', txt('defaultRisk', { inputmode: 'decimal' })),
      h('label', { class: 'f' }, '掛單手續費 %（BingX 一般 0.02）', txt('makerFee', { inputmode: 'decimal' })), h('label', { class: 'f' }, '市價手續費 %（BingX 一般 0.05）', txt('takerFee', { inputmode: 'decimal' })))));
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '偏好')), h('div', { class: 'grid2' },
      h('label', { class: 'f' }, '顯示名稱（總覽的打招呼）', txt('displayName')), h('label', { class: 'f' }, '提醒自己的一句話', txt('tagline')),
      h('label', { class: 'f' }, '漲跌顏色', h('select', { onchange: (e) => { S.colorMode = e.target.value; document.documentElement.dataset.updown = e.target.value === 'redUp' ? 'red' : 'green'; dirty(); } }, [['greenUp', '綠漲紅跌（跟 BingX 一樣）'], ['redUp', '紅漲綠跌（跟台股一樣）']].map(([v, l]) => h('option', { value: v, selected: S.colorMode === v || null }, l)))),
      h('label', { class: 'f', style: 'grid-column:1/-1;display:flex;gap:10px;align-items:center' }, h('input', { type: 'checkbox', checked: S.requireShot, style: 'width:20px;height:20px;accent-color:var(--accent)', onchange: (e) => { S.requireShot = e.target.checked; dirty(); } }), '沒有盤面截圖（或 TradingView 連結）的交易算「待補完」')),
      h('div', { class: 'muted', style: 'font-size:13px;margin-top:8px' }, '「待補完」＝少了止損（算不出 R）、進場條件，或盤面截圖。')));
    bar();
  },
  conditions(page) {
    subHead(page, '進場條件', '新增交易時使用的條件');
    const { S, dirty, bar } = draftBar(page);
    page.append(tagEditor(S, 'conditions', { kind: 'cond', title: '進場條件', desc: '整理你的進場訊號，讓新增交易與後續分析更清楚。「偏做多」的條件在做空單會被鎖住，反過來也一樣。', dirty }));
    bar();
  },
  emotions(page) {
    subHead(page, '開單狀態管理', '交易當下的心理狀態');
    const { S, dirty, bar } = draftBar(page);
    page.append(tagEditor(S, 'emotions', { kind: 'emo', title: '開單時的狀態', desc: '「正面」的情緒會算進雷達圖的情緒穩定度。', dirty }));
    bar();
  },
  tags(page) {
    subHead(page, '犯錯標籤與策略', '檢討用的標籤、策略分類');
    const { S, dirty, bar } = draftBar(page);
    page.append(h('div', { class: 'grid2' }, tagEditor(S, 'mistakes', { kind: 'plain', title: '犯錯標籤', dirty }), tagEditor(S, 'setups', { kind: 'plain', title: '策略', dirty })));
    bar();
  },
  bench(page) {
    subHead(page, '回測預期', '策略名稱、勝率 %、PF。用在分析頁的「實盤 vs 回測」。');
    const { S, dirty, bar } = draftBar(page);
    const bmBox = h('div', { class: 'edlist' });
    const inp = (b, key, attrs) => { const el = h('input', { type: 'text', value: b[key], ...attrs }); el.addEventListener('input', () => { b[key] = attrs.inputmode ? (num(el.value) ?? 0) : el.value; dirty(); }); return el; };
    const drawBm = () => bmBox.replaceChildren(...S.benchmarks.map((b, i) => h('div', { class: 'edrow' },
      inp(b, 'setup', { 'aria-label': '策略名稱' }), inp(b, 'win', { inputmode: 'decimal', 'aria-label': '勝率', placeholder: '勝率%' }), inp(b, 'pf', { inputmode: 'decimal', 'aria-label': 'PF', placeholder: 'PF' }),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': '刪除', onclick: () => { S.benchmarks.splice(i, 1); drawBm(); dirty(); } }, icon('x', 16)))));
    drawBm();
    page.append(h('div', { class: 'card' }, bmBox, h('button', { class: 'btn sm', type: 'button', style: 'margin-top:10px', onclick: () => { S.benchmarks.push({ setup: '', win: 50, pf: 1 }); drawBm(); dirty(); } }, '＋ 新增')));
    bar();
  },
  import(page) {
    subHead(page, '資料匯入', 'BingX CSV 歷史交易，先預覽、確認欄位再匯入');
    page.append(csvCard());
  },
  notify(page) {
    subHead(page, '通知設定', '用你掃描網站的同一個 Telegram 機器人發送，訊息開頭會標「【日誌】」');
    const N = state._notify || (state._notify = JSON.parse(JSON.stringify(state.notify || {})));
    const saveBtn = h('button', { class: 'btn primary', type: 'button', disabled: !state._notifyDirty || null }, '儲存通知設定');
    const dirty = () => { state._notifyDirty = true; saveBtn.disabled = false; };
    const sw = (key) => h('label', { class: 'switch' }, h('input', { type: 'checkbox', role: 'switch', checked: !!N[key], onchange: (e) => { N[key] = e.target.checked; dirty(); render(); } }), h('span', {}));
    const item = (key, title, desc, extra) => h('div', { class: 'nt-row' }, h('div', { class: 'nt-tx' }, h('b', {}, title), h('small', {}, desc), N[key] && extra ? h('div', { class: 'nt-extra' }, extra) : null), sw(key));
    const timeIn = h('input', { type: 'time', value: N.review_time || '23:00', 'aria-label': '提醒時間', onchange: (e) => { N.review_time = e.target.value || '23:00'; dirty(); } });
    const minIn = h('input', { type: 'number', min: 1, max: 500, value: N.pending_min || 5, style: 'width:90px;height:36px', 'aria-label': '幾筆以上提醒', oninput: (e) => { N.pending_min = num(e.target.value) || 5; dirty(); } });
    page.append(h('div', { class: 'card' },
      !N.telegram_ready ? h('div', { class: 'banner err', style: 'margin-bottom:12px' }, '伺服器還沒設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，通知發不出去。') : null,
      item('review_on', '每日復盤提醒', '每天固定時間提醒你寫復盤；當天已經寫了就不會吵你。', h('span', {}, '每天 ', timeIn, '（台灣時間）')),
      item('pending_on', '待補完提醒', '沒補完的單（止損、進場條件、盤面快照）太多時提醒你，一天最多一次。', h('span', {}, '超過 ', minIn, ' 筆就提醒（跟復盤提醒同一個時間檢查）')),
      item('paper_on', '紙上驗證結算', '紙上單打到止盈或止損時，告訴你結果是幾 R。'),
      item('sync_on', '同步出問題', 'BingX 同步失敗時通知你，三小時內最多一次。'),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;margin-top:16px' },
        h('button', { class: 'btn', type: 'button', disabled: !N.telegram_ready || null, onclick: async (e) => { const b = e.currentTarget; b.disabled = true; try { await api('POST', '/notify/test', {}); toast('已送出測試通知，去 Telegram 看看'); } catch (er) { toast(er.message); } b.disabled = false; } }, '傳送測試通知'))));
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      try { state.notify = await api('PUT', '/notify', N); state._notify = null; state._notifyDirty = false; toast('已儲存通知設定'); render(); } catch (e) { toast(e.message); saveBtn.disabled = false; }
    });
    page.append(h('div', { class: 'stickybar' }, h('button', { class: 'btn', type: 'button', onclick: () => { state._notify = null; state._notifyDirty = false; render(); } }, '還原'), saveBtn));
  },
  export(page) {
    subHead(page, '資料匯出', 'CSV 與 Email 備份');
    const n = state.notify || {};
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '下載 CSV'), h('div', { class: 'desc' }, `全部 ${live().length} 筆真實交易（不含紙上單），可以用 Excel 打開。`))),
      h('a', { class: 'btn primary', href: '/journal/api/export.csv' }, icon('st_export', 18), '下載 CSV')));
    const toIn = h('input', { type: 'email', value: n.email_to || '', placeholder: 'you@example.com', 'aria-label': '收件信箱', style: 'flex:1;min-width:200px' });
    const lb = state.lastBackup;
    const sendBtn = h('button', { class: 'btn primary', type: 'button', disabled: !n.email_ready || null }, '立即寄一份');
    sendBtn.addEventListener('click', async () => {
      sendBtn.disabled = true; sendBtn.textContent = '寄送中…';
      try { const r = await api('POST', '/backup-email', { to: toIn.value.trim() }); state.lastBackup = r.last_backup; state.notify = { ...state.notify, email_to: toIn.value.trim() }; toast(r.message); render(); }
      catch (e) { toast(e.message); sendBtn.disabled = false; sendBtn.textContent = '立即寄一份'; }
    });
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, 'Email 備份'), h('div', { class: 'desc' }, '把交易 CSV、設定和每日復盤寄到你的信箱，手動按才會寄。'))),
      h('div', { class: 'addrow' }, toIn, sendBtn),
      h('div', { class: 'muted', style: 'font-size:13px;margin-top:10px' }, lb ? `上次備份：${fmtDTY(lb.at)}，${lb.n} 筆，寄到 ${lb.to}` : '還沒寄過備份。'),
      !n.email_ready ? h('div', { class: 'banner', style: 'margin-top:14px' }, h('b', {}, '要先設定寄信服務才能用（只要做一次）'),
        h('ol', { class: 'steps', style: 'margin-top:8px' },
          h('li', {}, '免費版的 Render 不能用一般方式寄信，所以改用免費的寄信服務 Resend（每月 3000 封）。'),
          h('li', {}, '到 resend.com 用你的 Email 註冊 → 左邊 API Keys → Create API Key，權限選「Sending access」。'),
          h('li', {}, '到 Render → 你的服務 → Environment，新增 ', h('code', {}, 'RESEND_API_KEY'), '，值貼上剛剛的金鑰，存檔後會自動重新部署。'),
          h('li', {}, '回來這頁，收件信箱填你註冊 Resend 用的那個 Email（還沒綁自己網域前，只能寄到這個信箱）。'))) : null));
  },
  security(page) {
    subHead(page, '安全設定', '密碼與登入方式');
    const a = state.auth || {};
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, '目前的登入方式')),
      h('div', { class: 'kv' }, kvRow('登入方式', '密碼'), kvRow('密碼來源', a.custom ? `網站上改過（${fmtDTY(a.changed_at)}）` : 'Render 的 JOURNAL_PASSWORD'), kvRow('保持登入', '30 天'))));
    const f = { old: h('input', { type: 'password', autocomplete: 'current-password' }), nw: h('input', { type: 'password', autocomplete: 'new-password' }), nw2: h('input', { type: 'password', autocomplete: 'new-password' }) };
    const msg = h('div', { class: 'muted', style: 'font-size:13px;min-height:18px' });
    const btn = h('button', { class: 'btn primary', type: 'submit' }, '更改密碼');
    const form = h('form', { class: 'grid2', autocomplete: 'on' },
      h('label', { class: 'f', style: 'grid-column:1/-1' }, '目前的密碼', f.old), h('label', { class: 'f' }, '新密碼（至少 8 個字）', f.nw), h('label', { class: 'f' }, '再輸入一次新密碼', f.nw2),
      h('div', { style: 'grid-column:1/-1;display:flex;gap:12px;align-items:center;flex-wrap:wrap' }, btn, msg));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (f.nw.value.length < 8) { msg.textContent = '新密碼至少要 8 個字'; return; }
      if (f.nw.value !== f.nw2.value) { msg.textContent = '兩次輸入的新密碼不一樣'; return; }
      btn.disabled = true; msg.textContent = '';
      try { const r = await api('POST', '/password', { old: f.old.value, new: f.nw.value }); state.auth = r.auth; toast('密碼已更改，其他裝置需要重新登入'); render(); }
      catch (er) { msg.textContent = er.message; btn.disabled = false; }
    });
    page.append(h('div', { class: 'card' }, h('div', { class: 'card-h' }, h('div', {}, h('h2', {}, '更改密碼'), h('div', { class: 'desc' }, '改完後這台會保持登入，其他裝置都要重新登入。密碼會加密後存起來，沒有人看得到原本的密碼。'))), form,
      h('div', { class: 'muted', style: 'font-size:13px;margin-top:12px' }, '忘記密碼：到 Render → Environment 把 JOURNAL_PASSWORD 改成新的，網站就會改回用那組。')));
    page.append(h('div', { class: 'card' }, h('div', { style: 'display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap' }, h('div', {}, h('h2', {}, '登出'), h('div', { class: 'desc' }, '登出這台裝置。')), h('a', { class: 'btn', href: '/journal/logout' }, '登出'))));
  },
  about(page) {
    subHead(page, '關於我們', '版本與更新');
    const ab = state.about || {};
    page.append(h('div', { class: 'card' }, h('div', { class: 'kv' },
      kvRow('名稱', 'XUAN 交易日誌'), kvRow('版本', ab.version || '—'), kvRow('程式版本', ab.commit || '—'), kvRow('最後更新', ab.updated ? fmtDTY(ab.updated) : '—'),
      kvRow('資料庫', ab.store === 'supabase' ? 'Supabase' : '記憶體（重開會不見）'), kvRow('交易所', 'BingX 永續合約（唯讀）'), kvRow('介面參考', '超人交易紀錄')),
      state.store !== 'supabase' ? h('div', { class: 'banner err', style: 'margin-top:12px' }, '⚠ 目前沒有連上 Supabase，資料只存在伺服器記憶體，重新部署就會不見。請到 Render 設定 SUPABASE_URL 和 SUPABASE_SERVICE_KEY。') : null));
  },
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
