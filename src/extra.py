"""Fundamental & news data: monthly revenue, stock news (FinMind), commodity prices (Yahoo)."""
import datetime as dt
import zlib

import numpy as np
import pandas as pd
import requests

from .fetch import _get


# ---------- 月營收 ----------
def fetch_revenue(stock_id: str, token: str | None) -> pd.DataFrame:
    start = (dt.date.today() - dt.timedelta(days=500)).isoformat()
    df = _get("TaiwanStockMonthRevenue", stock_id, start, token)
    if df.empty:
        return df
    return df[["revenue_year", "revenue_month", "revenue"]].sort_values(["revenue_year", "revenue_month"]).reset_index(drop=True)


def revenue_summary(df: pd.DataFrame) -> dict | None:
    """最新一個月的營收、YoY、MoM。"""
    if df is None or len(df) < 2:
        return None
    t = df.iloc[-1]
    prev = df.iloc[-2]
    ly = df[(df.revenue_year == t.revenue_year - 1) & (df.revenue_month == t.revenue_month)]
    yoy = (t.revenue / ly.revenue.iloc[0] - 1) * 100 if not ly.empty and ly.revenue.iloc[0] else None
    mom = (t.revenue / prev.revenue - 1) * 100 if prev.revenue else None
    return {"month": int(t.revenue_month), "revenue_e8": t.revenue / 1e8, "yoy": yoy, "mom": mom}


# ---------- 個股新聞 ----------
def fetch_news(stock_id: str, days: int, token: str | None) -> list[dict]:
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    df = _get("TaiwanStockNews", stock_id, start, token)
    if df.empty:
        return []
    df = df.drop_duplicates(subset="title").sort_values("date", ascending=False)
    return df[["date", "source", "title", "link"]].head(15).to_dict("records")


# ---------- 原物料 ----------
def fetch_commodity(symbol: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, params={"range": "3mo", "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    df = pd.DataFrame({
        "date": pd.to_datetime(res["timestamp"], unit="s").normalize(),
        "close": res["indicators"]["quote"][0]["close"],
    })
    return df.dropna().reset_index(drop=True)


def commodity_summary(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 21:
        return None
    c = df["close"]
    return {
        "date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": float(c.iloc[-1]),
        "d1": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
        "d5": float((c.iloc[-1] / c.iloc[-6] - 1) * 100),
        "d20": float((c.iloc[-1] / c.iloc[-21] - 1) * 100),
        "series": df.tail(60),
    }


# ---------- mock ----------
def mock_revenue(stock_id: str) -> pd.DataFrame:
    rng = np.random.default_rng(zlib.crc32(stock_id.encode()) + 7)
    rows, base = [], rng.uniform(5e8, 2e10)
    today = dt.date.today()
    for i in range(15, 0, -1):
        m = (today.month - 1 - i) % 12 + 1
        y = today.year + (today.month - 1 - i) // 12
        base *= 1 + rng.normal(0.01, 0.08)
        rows.append({"revenue_year": y, "revenue_month": m, "revenue": round(base)})
    return pd.DataFrame(rows)


def mock_news(stock_id: str, name: str) -> list[dict]:
    rng = np.random.default_rng(zlib.crc32(stock_id.encode()) + 9)
    pool = [f"{name}法說會釋出展望，第四季營運看法曝光", f"外資調整{name}目標價",
            f"{name}9月營收出爐", f"{name}新產品線進度更新", f"{name}股價強勢，成交量放大"]
    n = int(rng.integers(0, 4))
    d = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    return [{"date": d, "source": "mock", "title": t, "link": "https://example.com"} for t in pool[:n]]


def mock_commodity(symbol: str) -> pd.DataFrame:
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=65)
    close = 4.5 * np.exp(np.cumsum(rng.normal(0, 0.012, 65)))
    return pd.DataFrame({"date": dates, "close": close})
