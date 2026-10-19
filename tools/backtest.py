"""回測 AI 判斷：各 stance 在 1、5、20 個交易日後的平均相對大盤報酬與勝率，並依 confidence 分組。

用法（在 repo 根目錄）：
  FINMIND_TOKEN=xxx python tools/backtest.py              # 讀 data/advice_history.csv，只算 AI 判斷
  python tools/backtest.py --source all                   # 連規則判斷一起算
  python tools/backtest.py --source rule                  # 只看規則判斷（和 AI 對照）
  python tools/backtest.py --mock                         # 用模擬價格與模擬紀錄測試，不連網

說明：
  - 相對報酬 = 個股 N 日報酬 − 加權指數 N 日報酬（%），基準是紀錄中的資料日收盤價。
  - 偏多勝率 = 相對報酬 > 0 的比例；偏空勝率 = 相對報酬 < 0 的比例；觀望只看平均值。
  - 剛記錄的判斷還沒有 N 日後的價格，該格會是空的；樣本數（n_）很小時結論不可靠。
"""
import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import fetch, history, market  # noqa: E402


def _series(df: pd.DataFrame) -> pd.Series:
    return df.set_index(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"))["close"].astype(float)


def mock_history(closes: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for i, d in enumerate(list(closes[next(iter(closes))].index)[-45:-1]):
        for k, (sid, s) in enumerate(closes.items()):
            st = ["偏多", "觀望", "偏空"][(i + k) % 3]
            rows.append({"date": d, "id": sid, "name": sid, "stance": st, "confidence": ["高", "中", "低"][(i // 3 + k) % 3],
                         "source": "ai", "close": s[d]})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(ROOT / "data" / "advice_history.csv"))
    ap.add_argument("--source", choices=["ai", "rule", "all"], default="ai")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    if args.mock:
        ids = ["3034", "3008", "2395", "1904"]
        closes = {sid: _series(fetch.mock_price(sid, 200)) for sid in ids}
        mser = _series(market.mock_taiex(200))
        hist = mock_history(closes)
    else:
        hist = history.load(Path(args.history))
        if hist.empty:
            print("沒有紀錄可以回測（data/advice_history.csv 不存在或是空的）")
            return 1
        token = os.getenv("FINMIND_TOKEN")
        start = (pd.to_datetime(hist["date"]).min() - pd.Timedelta(days=7)).date().isoformat()
        closes = {}
        for sid in sorted(hist["id"].astype(str).unique()):
            try:
                closes[sid] = _series(fetch.fetch_price(sid, start, token))
            except Exception as e:
                print(f"[warn] {sid}: {e}")
        mser = _series(market.fetch_taiex(start, token))

    if args.source != "all":
        hist = hist[hist["source"] == args.source]
    if hist.empty:
        print(f"沒有 source={args.source} 的紀錄")
        return 1

    fr = history.forward_returns(hist, closes, mser)
    table = history.summarize(fr)
    pd.set_option("display.width", 200)
    print(f"紀錄期間 {hist['date'].min()} ～ {hist['date'].max()}，共 {len(hist)} 筆（source={args.source}）")
    print("avg_Nd = 平均相對大盤報酬（%）；win_Nd = 勝率（%）；n_Nd = 已可驗證的樣本數\n")
    print(table.to_string(index=False))
    hc = history.hit_counts(fr, "rel_1d")
    print("\n隔日命中：" + "、".join(f"{k} {h}/{n}" for k, (h, n) in hc.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
