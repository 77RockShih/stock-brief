# stock-brief

每天早上自動分析台股 watchlist：GitHub Actions 抓 FinMind 資料 → 算技術指標、法人籌碼、月營收 → 抓個股新聞由 Claude 摘要、搜尋專家看法、追蹤原物料與大盤 → 推 LINE 摘要 + 更新 GitHub Pages dashboard。

## 架構

```
config.yaml          watchlist 與規則參數
main.py              進入點
src/fetch.py         FinMind API（與 mock 資料）
src/analyze.py       MA / RSI / MACD / 量比 + 訊號規則
src/extra.py         月營收、個股新聞（FinMind）、原物料（Yahoo）
src/summarize.py     Claude API 新聞摘要
src/market.py        加權指數、相對大盤強弱
src/overnight.py     盤前：昨夜美股（Yahoo）、台積電 ADR 溢價、台指期夜盤（期交所 OpenAPI）
src/experts.py       專家看法：Claude web search 找券商／分析師對各檔的觀點
src/advisor.py       每檔今日操作傾向（Claude，一次打包）；支撐／壓力由程式計算
src/history.py       判斷紀錄 data/advice_history.csv 與事後驗證（Dashboard「AI 判斷追蹤」）
src/checks.py        送進 AI 前的資料檢查（漲跌幅超限、資料日期、收盤與紀錄不符 → 資料異常）
src/events.py        7 日內事件：除權息（證交所 TWT48U）、月營收公布期限；法說會由 experts.py 搜尋
src/private.py       持有人私訊版（持股權重、集中度、損益），只推給 LINE_OWNER_ID
src/claude_api.py    Claude tool use 共用呼叫（含重試）
tools/intraday.py    盤中破支撐提醒（證交所 MIS 即時報價）
tools/backtest.py    回測各 stance 在 1／5／20 日後的相對大盤報酬與勝率
tools/get_user_id.py 一次性工具：本機接收 LINE webhook 取得 user ID
src/report.py        LINE 訊息 + Plotly dashboard
src/notify.py        LINE 推播
.github/workflows/daily.yml     週一到五 06:37（台北）執行、commit 判斷紀錄、部署 Pages；同一資料日只推一次
.github/workflows/intraday.yml  週一到五 10:27、12:27 盤中破支撐提醒（只推給你）
```

## 本機測試

```bash
pip install -r requirements.txt
python main.py --mock            # 模擬資料，不連網
open site/index.html
FINMIND_TOKEN=xxx python main.py --no-notify   # 真實資料
```

## 判斷紀錄與回測

- 每天的判斷會 append 到 `data/advice_history.csv`，由 workflow commit 回 repo（所以本機改 code 前請先 `git pull`）。
- 回測：`FINMIND_TOKEN=xxx python tools/backtest.py`（`--source all|rule` 可對照規則判斷；`--mock` 不連網測試）。
- 每週一晨報最後一行是上週 AI 判斷的隔日命中率。週五的判斷要等週一收盤才能驗證，會算在下一次。

## 準時送達：外部觸發（建議）

GitHub 的 schedule 常延遲 1～5 小時（實測 08:42～11:42 才送到），改 cron 時間無法解決。做法是讓外部排程服務準時呼叫 GitHub API，GitHub 自己的 schedule 留著當備援；`data/last_sent.txt` 會記錄已推過的資料日，晚到的那次會自動略過、不重複推播、不多花 API 費。

1. GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate：
   Repository access 只選 `stock-brief`；Permissions → **Actions: Read and write**。複製 token（只貼在 cron-job.org，不要貼到 repo 或聊天）。
2. cron-job.org 註冊 → Create cronjob：
   - URL：`https://api.github.com/repos/77RockShih/stock-brief/actions/workflows/daily.yml/dispatches`
   - Schedule：週一到週五 06:40，時區 Asia/Taipei
   - Advanced → Request method **POST**；Headers：`Authorization: Bearer <token>`、`Accept: application/vnd.github+json`
   - Request body：`{"ref":"main","inputs":{"skip_if_sent":"true"}}`
3. 盤中提醒同理，可另建兩個 job 打 `.../workflows/intraday.yml/dispatches`（body `{"ref":"main"}`），時間 10:30、12:30。

## 部署步驟

1. **建 repo**：GitHub 上新增 repo（例如 `stock-brief`），把這個資料夾 push 上去。
2. **FinMind token**：到 finmindtrade.com 註冊，在會員頁複製 API token。
3. **LINE**（Messaging API）：
   - 到 LINE Official Account Manager 建一個官方帳號，在設定裡啟用 Messaging API
   - 到 LINE Developers Console 打開該 channel：
     - Messaging API 分頁最下方 → 發行 **Channel access token (long-lived)** → 這是 `LINE_TOKEN`
     - Basic settings 分頁最下方 **Your user ID**（U 開頭）→ 這是 `LINE_USER_ID`
   - 用手機掃 Messaging API 分頁的 QR code，把 bot 加為好友
   - 建議在官方帳號設定裡關掉「自動回應訊息」，避免它回你罐頭訊息

4. **Secrets**：repo → Settings → Secrets and variables → Actions，新增 `FINMIND_TOKEN`、`LINE_TOKEN`、`LINE_USER_ID`、`ANTHROPIC_API_KEY`（console.anthropic.com 申請；沒設的話新聞只列標題）。
   `LINE_USER_ID` 可填單一 ID、逗號分隔多個 ID，或 `broadcast`（推給所有好友）。
   選填（私訊版與盤中提醒，只推給你）：
   - `LINE_OWNER_ID`：你自己的 user ID（Basic settings → Your user ID），只能一個
   - `HOLDINGS`：`代號:張數[:成本]`，逗號分隔，例如 `3034:2:520,2395:1,0050:5:75.3`（零股用小數張數）
5. **開 Pages**：repo → Settings → Pages → Source 選 **GitHub Actions**。
6. **手動跑一次**：Actions 分頁 → Daily Stock Brief → Run workflow。成功後手機就會收到訊息。

## 注意

- Public repo 的 Pages 任何人都能看到；不想公開持股就把 repo 設 private（Pages 需付費方案），或改部署到 Cloudflare Pages + Access。
- GitHub Actions cron 可能延遲數分鐘到一兩小時（已避開整點／半點）。
- LINE 免費方案每月 200 則，**按收件人數計算**：群發給 N 個好友每天算 N 則。
  每月約 22 個交易日：晨報 22×N ＋ 私訊版 22 ＋ 盤中提醒（有跌破才推）最多 44。
  例：好友 5 人 → 110＋22＋44 = 176，在額度內；好友 7 人以上就要關掉盤中提醒或私訊版。
- 專家看法：每檔最多 4 次網路搜尋（每 1,000 次 10 美元），只保留網址確實出自搜尋結果的看法；細節在 Dashboard。
- AI 摘要只根據新聞標題，可能遺漏內文細節。
- 技術指標僅供參考，規則上線前先回測。
