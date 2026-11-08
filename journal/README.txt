交易日誌更新包（第五批）

放到 GitHub repo 的根目錄（跟 app.py 同一層）：
  journal/        ← 整個資料夾（新的）
  app.py          ← 只多了 3 行（最下面 journal.init_app）
  render.yaml     ← 多了交易日誌用的環境變數

如果你的 app.py 跟這份不一樣，不用整份換，只要在 `_scheduler = start_scheduler()` 下面加：
    import journal
    journal.init_app(app, _scheduler)

Supabase：SQL Editor 貼上 journal/schema.sql 按 Run。
Render Environment：JOURNAL_PASSWORD、SUPABASE_URL、SUPABASE_SERVICE_KEY、BINGX_API_KEY、BINGX_API_SECRET
（選填：FLASK_SECRET_KEY、ANTHROPIC_API_KEY、JOURNAL_SYNC_MINUTES、JOURNAL_BACKFILL_DAYS）
網址：https://你的網站/journal
