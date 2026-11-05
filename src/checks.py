"""送進 LLM 之前的資料檢查。檢查沒過的股票標「資料異常」，不交給 AI 判斷，也不寫進判斷紀錄。

檢查項目
  1. 漲跌幅超過 ±10%：台股（上市櫃普通股與 ETF）有 10% 漲跌幅限制，超過代表資料有問題
     （例外：除權息、減資後恢復交易首日等，以參考價計算會超過；這種情況寧可當天不判斷）。
  2. 資料日期不是最新交易日：個股最後一筆日期比加權指數的最後一筆舊（停牌或資料未更新）。
  3. 收盤價和昨天存的紀錄對不起來：今天抓到的「前一交易日收盤」與 data/advice_history.csv
     裡同一天記錄的收盤價相差超過 0.5%。
另有全市場檢查：加權指數最後一筆日期早於「今天之前最近的平日」→ 可能資料尚未更新（遇到國定假日會誤報，僅提示）。
"""
import datetime as dt

import pandas as pd

LIMIT_PCT = 10.0
CLOSE_TOL = 0.005  # 0.5%


def stock_issues(r: dict, df: pd.DataFrame, hist: pd.DataFrame | None, market_last: dt.date | None) -> list[str]:
    issues = []
    if abs(r["change_pct"]) > LIMIT_PCT + 0.05:  # 0.05 容忍四捨五入
        issues.append(f"漲跌幅 {r['change_pct']:+.1f}% 超過漲跌停限制")
    d = dt.date.fromisoformat(r["date"])
    if market_last and d < market_last:
        issues.append(f"資料日 {d:%m/%d} 不是最新交易日 {market_last:%m/%d}")
    if hist is not None and not hist.empty and len(df) >= 2:
        prev_date = df["date"].iloc[-2].strftime("%Y-%m-%d")
        rec = hist[(hist["id"].astype(str) == r["id"]) & (hist["date"] == prev_date)]
        if not rec.empty:
            saved, now = float(rec["close"].iloc[-1]), float(df["close"].iloc[-2])
            if saved and abs(now / saved - 1) > CLOSE_TOL:
                issues.append(f"{prev_date[5:].replace('-', '/')} 收盤 {now:g} 與紀錄 {saved:g} 不符")
    return issues


def market_issue(market_last: dt.date | None, today: dt.date) -> str | None:
    if market_last is None:
        return "抓不到加權指數，無法確認資料日期"
    expect = today - dt.timedelta(days=1)
    while expect.weekday() >= 5:
        expect -= dt.timedelta(days=1)
    if market_last < expect:
        return f"大盤資料停在 {market_last:%m/%d}（預期 {expect:%m/%d}），可能尚未更新或遇假日"
    return None


def run(results: list[dict], frames: dict, hist: pd.DataFrame | None, market_last: dt.date | None) -> dict[str, list[str]]:
    out = {}
    for r in results:
        try:
            iss = stock_issues(r, frames[r["id"]][0], hist, market_last)
        except Exception as e:  # 檢查本身出錯不擋主流程
            print(f"[warn] check {r['id']}: {e}")
            iss = []
        if iss:
            out[r["id"]] = iss
            print(f"[check] {r['id']} {r['name']}: " + "；".join(iss))
    return out
