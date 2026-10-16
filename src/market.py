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


def fetch_total_inst(start: str, token: str | None) -> dict | None:
    """全市場三大法人買賣超（FinMind TaiwanStockTotalInstitutionalInvestors，單位：新台幣元）。
    欄位：date, name, buy, sell；name 有 Foreign_Investor / Foreign_Dealer_Self / Investment_Trust /
    Dealer_self / Dealer_Hedging。回傳最新一天的金額（億元）。"""
    df = _get("TaiwanStockTotalInstitutionalInvestors", "", start, token)
    if df.empty:
        return None
    last = df[df["date"] == df["date"].max()].copy()
    last["net"] = (last["buy"] - last["sell"]) / 1e8
    g = lambda names: float(last.loc[last["name"].isin(names), "net"].sum())
    return {"date": str(last["date"].iloc[0]),
            "foreign": g(["Foreign_Investor", "Foreign_Dealer_Self"]),
            "trust": g(["Investment_Trust"]),
            "dealer": g(["Dealer_self", "Dealer_Hedging", "Dealer"])}


def mock_total_inst() -> dict:
    return {"date": dt.date.today().isoformat(), "foreign": -523.4, "trust": 31.2, "dealer": -48.7}


def mock_taiex(n: int = 80) -> pd.DataFrame:
    g = np.random.default_rng(zlib.crc32(b"TAIEX"))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=n)
    return pd.DataFrame({"date": dates, "close": 22000 * np.exp(np.cumsum(g.normal(0, 0.01, n)))})
