# stock-brief

每天早上自動分析台股 watchlist：GitHub Actions 抓 FinMind 資料 → 算技術指標與法人籌碼訊號 → 推 Telegram 摘要 + 更新 GitHub Pages dashboard。

## 架構

```
config.yaml          watchlist 與規則參數
main.py              進入點
src/fetch.py         FinMind API（與 mock 資料）
src/analyze.py       MA / RSI / MACD / 量比 + 訊號規則
src/report.py        Telegram 文字 + Plotly dashboard
src/notify.py        Telegram 推播
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
3. **Telegram bot**：
   - 找 `@BotFather` → `/newbot` → 拿到 bot token
   - 對你的 bot 隨便傳一則訊息
   - 打開 `https://api.telegram.org/bot<TOKEN>/getUpdates`，找 `"chat":{"id":...}` 就是 chat ID
4. **Secrets**：repo → Settings → Secrets and variables → Actions，新增 `FINMIND_TOKEN`、`TG_TOKEN`、`TG_CHAT_ID`。
5. **開 Pages**：repo → Settings → Pages → Source 選 **GitHub Actions**。
6. **手動跑一次**：Actions 分頁 → Daily Stock Brief → Run workflow。成功後手機就會收到訊息。

## 注意

- Public repo 的 Pages 任何人都能看到；不想公開持股就把 repo 設 private（Pages 需付費方案），或改部署到 Cloudflare Pages + Access。
- GitHub Actions cron 可能延遲數分鐘到半小時。
- 技術指標僅供參考，規則上線前先回測。
