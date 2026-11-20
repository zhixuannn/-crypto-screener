-- 訊號網站的紀錄備份（訊號、TradingView 警報）：到 Supabase → SQL Editor → New query，整段貼上後按 Run（只要跑一次）
-- 為什麼要：Render 免費方案重新部署會把 signals.db 清空，所以每筆紀錄都另外存一份到這裡，網站開機時再抓回來。

create table if not exists screener_records (
  kind       text not null,                       -- 'signal' = 訊號, 'tv_alert' = TradingView 警報
  uid        text not null,                       -- 這筆的唯一代號（幣種|方向|K棒時間）
  data       jsonb not null,                      -- 整筆內容
  updated_at timestamptz not null default now(),
  primary key (kind, uid)
);

-- 開啟 RLS 而且不給任何規則：只有伺服器用 service_role 金鑰才讀寫得到
alter table screener_records enable row level security;
