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


def fetch_margin_total(start: str, token: str | None) -> dict | None:
    """上市融資餘額（FinMind TaiwanStockTotalMarginPurchaseShortSale，不帶 data_id）。
    取 name = MarginPurchaseMoney（融資金額）的 TodayBalance − YesBalance。
    單位：證交所公布為「仟元」；保險起見依量級判斷（> 5e9 視為元）。回傳億元。"""
    df = _get("TaiwanStockTotalMarginPurchaseShortSale", "", start, token)
    if df.empty or "name" not in df:
        return None
    m = df[df["name"] == "MarginPurchaseMoney"].sort_values("date")
    if m.empty:
        return None
    t = m.iloc[-1]
    today, yes = float(t["TodayBalance"]), float(t["YesBalance"])
    to_e8 = 1e8 if today > 5e9 else 1e5   # 元 → 億：/1e8；仟元 → 億：/1e5
    return {"date": str(t["date"])[:10], "balance_e8": today / to_e8, "change_e8": (today - yes) / to_e8}


def fetch_futures_foreign(start: str, token: str | None) -> dict | None:
    """外資台指期（大台 TX）未平倉淨口數 = 多方未平倉口數 − 空方未平倉口數，以及較前一交易日的變化。"""
    df = _get("TaiwanFuturesInstitutionalInvestors", "TX", start, token)
    if df.empty:
        return None
    f = df[df["institutional_investors"].astype(str).str.contains("外資")].copy()
    if f.empty:
        return None
    f["net"] = f["long_open_interest_balance_volume"].astype(float) - f["short_open_interest_balance_volume"].astype(float)
    f = f.groupby("date", as_index=False)["net"].sum().sort_values("date")
    net = float(f["net"].iloc[-1])
    prev = float(f["net"].iloc[-2]) if len(f) >= 2 else None
    return {"date": str(f["date"].iloc[-1])[:10], "net": net, "change": None if prev is None else net - prev}


def mock_margin_total() -> dict:
    return {"date": dt.date.today().isoformat(), "balance_e8": 3124.5, "change_e8": -236.8}


def mock_futures_foreign() -> dict:
    return {"date": dt.date.today().isoformat(), "net": -32145.0, "change": -1203.0}


def mock_total_inst() -> dict:
    return {"date": dt.date.today().isoformat(), "foreign": -523.4, "trust": 31.2, "dealer": -48.7}


def mock_taiex(n: int = 80) -> pd.DataFrame:
    g = np.random.default_rng(zlib.crc32(b"TAIEX"))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=n)
    return pd.DataFrame({"date": dates, "close": 22000 * np.exp(np.cumsum(g.normal(0, 0.01, n)))})
