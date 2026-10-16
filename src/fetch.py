"""Data fetching: FinMind API (real) or synthetic data (mock, for offline testing)."""
import datetime as dt
import zlib

import numpy as np
import pandas as pd
import requests

API = "https://api.finmindtrade.com/api/v4/data"


def _get(dataset: str, stock_id: str, start: str, token: str | None) -> pd.DataFrame:
    params = {"dataset": dataset, "start_date": start}
    if stock_id:  # 全市場型 dataset（如 TaiwanStockTotalInstitutionalInvestors）不帶 data_id
        params["data_id"] = stock_id
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(API, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} {stock_id}: {j.get('msg')}")
    return pd.DataFrame(j["data"])


def fetch_price(stock_id: str, start: str, token: str | None) -> pd.DataFrame:
    df = _get("TaiwanStockPrice", stock_id, start, token)
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df["volume"] = df["volume"] / 1000  # 股 → 張
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)


def fetch_institutional(stock_id: str, start: str, token: str | None) -> pd.DataFrame:
    """三大法人買賣超（張）。"""
    df = _get("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start, token)
    if df.empty:
        return pd.DataFrame(columns=["date", "foreign", "trust", "dealer"])
    df["net"] = (df["buy"] - df["sell"]) / 1000
    group = {
        "Foreign_Investor": "foreign", "Foreign_Dealer_Self": "foreign",
        "Investment_Trust": "trust",
        "Dealer_self": "dealer", "Dealer_Hedging": "dealer",
    }
    df["who"] = df["name"].map(group)
    out = df.dropna(subset=["who"]).pivot_table(index="date", columns="who", values="net", aggfunc="sum").fillna(0)
    out = out.reindex(columns=["foreign", "trust", "dealer"], fill_value=0).reset_index()
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


# ---------- mock ----------
def mock_price(stock_id: str, days: int) -> pd.DataFrame:
    rng = np.random.default_rng(zlib.crc32(stock_id.encode()))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=days)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.018, days)))
    open_ = close * (1 + rng.normal(0, 0.006, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, days)))
    vol = rng.lognormal(9, 0.4, days)
    vol[-1] *= rng.choice([1, 2.5])
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}).round(2)
    df.insert(0, "date", dates)
    return df


def mock_institutional(stock_id: str, days: int) -> pd.DataFrame:
    rng = np.random.default_rng(zlib.crc32(stock_id.encode()) + 1)
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=days)
    return pd.DataFrame({
        "date": dates,
        "foreign": rng.normal(200, 3000, days).round(),
        "trust": rng.normal(0, 500, days).round(),
        "dealer": rng.normal(0, 400, days).round(),
    })
