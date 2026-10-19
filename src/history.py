"""AI 判斷的歷史紀錄與事後驗證。

紀錄檔 data/advice_history.csv（commit 在 repo 裡，GitHub Actions 每天 append）：
  date        資料日（判斷依據的收盤日；判斷適用於之後的交易日）
  id, name    股票
  stance      偏多 / 觀望 / 偏空
  confidence  高 / 中 / 低
  source      ai / rule
  close       資料日收盤價（計算後續報酬的基準）
  support, resistance

驗證方式：報酬一律「相對大盤」= 個股報酬 − 加權指數同期報酬。
  偏多命中：相對報酬 > 0；偏空命中：相對報酬 < 0；觀望不算命中率，只看平均絕對值。
"""
from pathlib import Path

import pandas as pd

COLUMNS = ["date", "id", "name", "stance", "confidence", "source", "close", "support", "resistance"]


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path, dtype={"id": str, "date": str})


def append(path: Path, results: list[dict]) -> pd.DataFrame:
    """把今天每檔的判斷寫進紀錄；同一天重跑會覆蓋同一天的列，不會重複。"""
    rows = []
    for r in results:
        a = r.get("advice") or {}
        rows.append({"date": r["date"], "id": r["id"], "name": r["name"], "stance": a.get("stance"),
                     "confidence": a.get("confidence"), "source": a.get("source"), "close": round(r["close"], 2),
                     "support": round(a["support"], 2) if a.get("support") is not None else None,
                     "resistance": round(a["resistance"], 2) if a.get("resistance") is not None else None})
    new = pd.DataFrame(rows, columns=COLUMNS)
    old = load(path)
    merged = pd.concat([old, new], ignore_index=True).drop_duplicates(["date", "id"], keep="last")
    merged = merged.sort_values(["date", "id"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def forward_returns(hist: pd.DataFrame, closes: dict[str, pd.Series], market: pd.Series,
                    horizons=(1, 5, 20)) -> pd.DataFrame:
    """為每筆判斷計算 N 個交易日後的相對大盤報酬（%）。資料還不夠的格子為 NaN。
    closes：{id: 以日期（YYYY-MM-DD 字串）為 index 的收盤價 Series}；market：同格式的加權指數。"""
    out = hist.copy()
    for h in horizons:
        vals = []
        for _, row in hist.iterrows():
            s = closes.get(str(row["id"]))
            vals.append(_rel(s, market, row["date"], h))
        out[f"rel_{h}d"] = vals
    return out


def _rel(s: pd.Series | None, m: pd.Series, date: str, h: int) -> float | None:
    if s is None or date not in s.index or date not in m.index:
        return None
    i, j = s.index.get_loc(date), m.index.get_loc(date)
    if i + h >= len(s) or j + h >= len(m):
        return None
    return (s.iloc[i + h] / s.iloc[i] - m.iloc[j + h] / m.iloc[j]) * 100


def hit_counts(fr: pd.DataFrame, col: str = "rel_1d") -> dict[str, tuple[int, int]]:
    """偏多 / 偏空 的 (命中數, 已可驗證數)。"""
    out = {}
    for st, win in (("偏多", lambda x: x > 0), ("偏空", lambda x: x < 0)):
        sub = fr[(fr["stance"] == st) & fr[col].notna()]
        out[st] = (int(win(sub[col]).sum()), int(len(sub)))
    return out


def summarize(fr: pd.DataFrame, horizons=(1, 5, 20)) -> pd.DataFrame:
    """依 stance、stance×confidence 分組的樣本數、平均相對報酬與勝率。"""
    rows = []
    for keys, g in [((st,), fr[fr.stance == st]) for st in ("偏多", "觀望", "偏空")] + \
                   [((st, c), fr[(fr.stance == st) & (fr.confidence == c)])
                    for st in ("偏多", "觀望", "偏空") for c in ("高", "中", "低")]:
        if g.empty:
            continue
        row = {"stance": keys[0], "confidence": keys[1] if len(keys) > 1 else "全部"}
        for h in horizons:
            v = g[f"rel_{h}d"].dropna()
            row[f"n_{h}d"] = len(v)
            row[f"avg_{h}d"] = round(v.mean(), 2) if len(v) else None
            if keys[0] == "偏多":
                row[f"win_{h}d"] = round((v > 0).mean() * 100, 1) if len(v) else None
            elif keys[0] == "偏空":
                row[f"win_{h}d"] = round((v < 0).mean() * 100, 1) if len(v) else None
            else:
                row[f"win_{h}d"] = None
        rows.append(row)
    return pd.DataFrame(rows)


def last_week_line(hist: pd.DataFrame, closes: dict[str, pd.Series], market: pd.Series,
                   today: pd.Timestamp) -> str | None:
    """週一晨報用：上週（週一～週五資料日）AI 判斷，以隔一個交易日的相對大盤報酬驗證。"""
    if hist.empty:
        return None
    monday = (today - pd.Timedelta(days=today.weekday() + 7)).normalize()
    friday = monday + pd.Timedelta(days=4)
    d = pd.to_datetime(hist["date"])
    week = hist[(d >= monday) & (d <= friday) & (hist["source"] == "ai")]
    if week.empty:
        return None
    hc = hit_counts(forward_returns(week, closes, market, horizons=(1,)), "rel_1d")
    parts = [f"{st} {h}/{n}" for st, (h, n) in hc.items() if n]
    return "📊 上週 AI 判斷命中率（隔日相對大盤）：" + "、".join(parts) if parts else None
