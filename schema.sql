-- 交易日誌資料表：到 Supabase → SQL Editor → New query，整段貼上後按 Run（只要跑一次）

create extension if not exists pgcrypto;

create table if not exists journal_trades (
  id            uuid primary key default gen_random_uuid(),
  source        text not null default 'manual',      -- 'api' = BingX 自動匯入, 'manual' = 手動, 'csv' = 匯入
  external_id   text unique,                          -- BingX positionId（手動單是 null）
  symbol        text not null,
  side          text not null,                        -- 'long' / 'short'
  status        text not null default 'closed',       -- 'open' / 'closed'
  open_time     timestamptz,
  close_time    timestamptz,
  entry         double precision,
  exit          double precision,
  qty           double precision,                     -- 數量（顆）
  leverage      double precision,
  pnl           double precision,                     -- 實際盈虧（已扣手續費）
  gross_pnl     double precision,
  fee           double precision,
  funding       double precision,
  sl            double precision,                     -- 原始止損價
  tps           jsonb not null default '[]'::jsonb,   -- 止盈目標 TP1~TP5
  risk_amount   double precision,                     -- 風險金額（選填）
  setup         text,
  order_type    text,                                 -- 'limit' / 'market'
  conditions    jsonb not null default '[]'::jsonb,
  emotions      jsonb not null default '[]'::jsonb,
  mistakes      jsonb not null default '[]'::jsonb,
  followed_rules boolean,
  rule_note     text,
  reason        text,
  note          text,
  shots         jsonb not null default '[]'::jsonb,   -- 截圖在 Storage 的路徑
  tv_links      jsonb not null default '[]'::jsonb,
  raw           jsonb,                                -- 交易所原始資料
  deleted_at    timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists journal_trades_open_time_idx on journal_trades (open_time desc);

create table if not exists journal_reviews (
  day        date primary key,
  note       text not null default '',
  updated_at timestamptz not null default now()
);

create table if not exists journal_kv (
  key        text primary key,
  value      jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- 開啟 RLS 而且不給任何規則：只有伺服器用 service_role 金鑰才讀寫得到，別人拿到網址也讀不到
alter table journal_trades  enable row level security;
alter table journal_reviews enable row level security;
alter table journal_kv      enable row level security;

-- 截圖用的私人儲存空間
insert into storage.buckets (id, name, public)
values ('journal-shots', 'journal-shots', false)
on conflict (id) do nothing;
