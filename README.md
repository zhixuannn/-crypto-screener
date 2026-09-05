# XUAN 3+1 BingX 訊號掃描網站

自動掃描 BingX 上所有 USDT 永續合約，用 XUAN 3+1 邏輯 (CHoCH + FVG + BOS + 訂單塊)
判斷進場訊號，有新訊號就存進資料庫、並發送 Telegram 通知。

## 功能

- 每 5 分鐘（可調整）自動掃描一次 BingX 全市場永續合約
- 用 5 分鐘K線（可調整）判斷 XUAN 3+1 四條件進場訊號
- 偵測到新訊號時：
  - 存進 SQLite 資料庫
  - 發送 Telegram 通知（幣種、方向、進場價、止損價、止損距離%）
- 網頁首頁顯示最近 100 筆訊號歷史

## 本機測試

1. 安裝套件：
   ```
   pip install -r requirements.txt
   ```

2. 設定環境變數（Telegram 通知需要，沒設定的話程式會照常跑，只是不會發通知）：
   ```
   export TELEGRAM_BOT_TOKEN="你的Bot Token"
   export TELEGRAM_CHAT_ID="你的Chat ID"
   ```
   Windows PowerShell 用 `$env:TELEGRAM_BOT_TOKEN="..."` 這種寫法。

3. 啟動：
   ```
   python app.py
   ```
   啟動時會立刻跑一次掃描（第一次掃描全市場可能要花幾分鐘，請耐心等），
   之後每 5 分鐘自動重複。打開瀏覽器到 `http://localhost:5000` 看訊號列表。

## 部署到 Render

1. 把這個資料夾推上 GitHub（建一個新 repo，把這些檔案都放進去）
2. 到 [Render](https://render.com) 建立新的 **Web Service**，選擇你的 repo
3. Render 會自動讀到 `render.yaml` 的設定，但 `TELEGRAM_BOT_TOKEN` 跟
   `TELEGRAM_CHAT_ID` 這兩個因為是機密資訊，不會自動填，需要你自己到
   Render 後台的 **Environment** 分頁手動加上去
4. 部署完成後，Render 會給你一個網址（例如 `https://xuan-bingx-screener.onrender.com`），
   打開就能看到訊號列表

### 關於 Render 免費方案的限制

- 免費方案的服務**閒置一段時間會被自動休眠**，之後有人訪問網址時才會醒過來
  （醒來需要幾十秒）。如果休眠了，背景排程掃描也會跟著停止！
  **如果你需要24小時不間斷掃描，建議升級成付費的方案**（不會休眠），
  或是自己另外設定一個服務（例如 UptimeRobot）定期打你的網址讓它保持醒著，
  但這個方式不是100%可靠。
- `gunicorn` 設定成 `--workers 1`，**請不要調高**，因為背景排程是跑在
  同一個process裡面，如果開多個worker，掃描會被重複執行好幾次，
  也可能造成重複通知或對BingX發送過多請求。

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `app.py` | Flask主程式，包含排程掃描與網頁路由 |
| `strategy.py` | XUAN 3+1 策略邏輯 (Python版，忠實移植自Pine Script) |
| `exchange_client.py` | 跟BingX要K線資料、幣種清單 |
| `database.py` | SQLite資料庫，存訊號歷史、避免重複通知 |
| `notifier.py` | 發送Telegram通知 |
| `templates/index.html` | 網頁首頁 |

## 可調整的環境變數

| 變數 | 預設值 | 說明 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | (無) | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | (無) | 你的Telegram Chat ID |
| `SCAN_TIMEFRAME` | `5m` | 判斷訊號用的K線週期 |
| `SCAN_INTERVAL_MINUTES` | `5` | 幾分鐘掃描一次全市場 |
| `SWING_LENGTH` | `5` | 擺動高低點週期，對應指標的pivotLengthInput |
| `CANDLE_LIMIT` | `500` | 每個幣種抓幾根歷史K棒回來判斷 |
| `SCAN_MAX_WORKERS` | `5` | 同時併發抓幾個幣種的資料 (太高可能被BingX限流) |

## 已知限制 / 之後可以加強的地方

- 目前**沒有做風控/自動下單**，純粹是訊號提醒，實際進出場還是要你自己判斷
- 每次掃描都是**重新用歷史K棒完整跑一次演算法**來重建狀態（沒有跨掃描保存
  逐根K棒的即時狀態），所以只要抓的 `CANDLE_LIMIT` 夠長（預設500根），
  結果會跟指標在TradingView上顯示的一致
- 全市場掃描的幣種一多，單次掃描可能要跑一段時間，如果覺得太久，
  可以調整 `SCAN_MAX_WORKERS`（提高併發）或改成只掃自選清單（未來可加）
