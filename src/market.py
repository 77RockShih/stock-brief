"""大盤脈絡：加權指數（FinMind TAIEX，失敗時改用 Yahoo ^TWII）。"""
import datetime as dt
import zlib

import numpy as np
import pandas as pd

from .fetch import _get


def fetch_taiex(start: str, token: str | None) -> pd.DataFrame:
    try:
        df = _get("TaiwanStockPrice", "TAIEX", start, token)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            return df[["date", "close"]].sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"[warn] FinMind TAIEX: {e}, fallback to Yahoo")
    from .extra import fetch_commodity
    return fetch_commodity("^TWII")


def market_summary(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 21:
        return None
    c = df["close"]
    return {"date": df["date"].iloc[-1].strftime("%Y-%m-%d"), "close": float(c.iloc[-1]),
            "d1": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
            "d20": float((c.iloc[-1] / c.iloc[-21] - 1) * 100)}


def mock_taiex(n: int = 80) -> pd.DataFrame:
    g = np.random.default_rng(zlib.crc32(b"TAIEX"))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=n)
    return pd.DataFrame({"date": dates, "close": 22000 * np.exp(np.cumsum(g.normal(0, 0.01, n)))})
