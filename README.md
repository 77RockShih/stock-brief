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
src/experts.py       專家看法：Claude web search 找券商／分析師對各檔的觀點
tools/get_user_id.py 一次性工具：本機接收 LINE webhook 取得 user ID
src/report.py        LINE 訊息 + Plotly dashboard
src/notify.py        LINE 推播
.github/workflows/daily.yml   週一到五 07:30（台北）執行並部署 Pages
```

## 本機測試

```bash
pip install -r requirements.txt
python main.py --mock            # 模擬資料，不連網
open site/index.html
FINMIND_TOKEN=xxx python main.py --no-notify   # 真實資料
```

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
5. **開 Pages**：repo → Settings → Pages → Source 選 **GitHub Actions**。
6. **手動跑一次**：Actions 分頁 → Daily Stock Brief → Run workflow。成功後手機就會收到訊息。

## 注意

- Public repo 的 Pages 任何人都能看到；不想公開持股就把 repo 設 private（Pages 需付費方案），或改部署到 Cloudflare Pages + Access。
- GitHub Actions cron 可能延遲數分鐘到半小時。
- LINE 免費方案每月推播則數有上限；每天 1 則在額度內，但不要拿它做盤中頻繁通知。
- 專家看法：每檔最多 3 次網路搜尋（每 1,000 次 10 美元），只保留網址確實出自搜尋結果的看法；只推到 LINE。
- AI 摘要只根據新聞標題，可能遺漏內文細節；摘要只推到 LINE，不放公開 dashboard。
- 技術指標僅供參考，規則上線前先回測。
