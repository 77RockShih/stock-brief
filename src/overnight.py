"""盤前資訊：昨夜美股（Yahoo Finance）與台指期夜盤（期交所 OpenAPI）。"""
import datetime as dt
import zlib

import numpy as np
import pandas as pd
import requests

from .extra import fetch_commodity as fetch_yahoo  # 同一支 Yahoo chart API

TAIFEX_FUT = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------- 美股 ----------
def us_summary(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 2:
        return None
    c = df["close"]
    return {"date": df["date"].iloc[-1].strftime("%Y-%m-%d"), "close": float(c.iloc[-1]),
            "d1": float((c.iloc[-1] / c.iloc[-2] - 1) * 100)}


def adr_premium(tsm_close: float, usdtwd: float, tw2330_close: float) -> float:
    """台積電 ADR 1 單位 = 5 股普通股。"""
    return (tsm_close * usdtwd / 5 / tw2330_close - 1) * 100


# ---------- 台指期夜盤 ----------
def _front(rows: list[dict]) -> dict | None:
    """近月合約：排除價差（含 /）與週選（含 W），取成交量最大者。"""
    rows = [r for r in rows if r.get("ContractMonth(Week)") and "/" not in r["ContractMonth(Week)"]
            and "W" not in r["ContractMonth(Week)"].upper()]
    rows.sort(key=lambda r: (_num(r.get("Volume")) or 0), reverse=True)
    return rows[0] if rows else None


def fetch_night_session(contract: str = "TX") -> dict | None:
    r = requests.get(TAIFEX_FUT, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    r.raise_for_status()
    rows = [x for x in r.json() if str(x.get("Contract", "")).strip().upper() == contract]
    night = _front([x for x in rows if str(x.get("TradingSession", "")).strip() == "盤後"])
    day = _front([x for x in rows if str(x.get("TradingSession", "")).strip() in ("一般", "")])
    if not night:
        return None
    last, chg = _num(night.get("Last")), _num(night.get("Change"))
    out = {"date": str(night.get("Date", "")), "month": night.get("ContractMonth(Week)"), "last": last, "change": chg,
           "pct": _num(str(night.get("%", "")).replace("%", "")), "day_last": _num(day.get("Last")) if day else None}
    if out["pct"] is None and last and chg is not None and last != chg:
        out["pct"] = chg / (last - chg) * 100
    return out


# ---------- 整合 ----------
def collect(cfg_items: list[dict], tw2330_close: float | None, mock: bool) -> dict:
    us, fx = [], None
    for it in cfg_items:
        try:
            df = mock_yahoo(it["symbol"]) if mock else fetch_yahoo(it["symbol"])
            s = us_summary(df)
            if s:
                us.append({**it, **s})
        except Exception as e:
            print(f"[warn] overnight {it['symbol']}: {e}")
    try:
        fx = us_summary(mock_yahoo("TWD=X", 32) if mock else fetch_yahoo("TWD=X"))
    except Exception as e:
        print(f"[warn] USD/TWD: {e}")
    for u in us:
        if u["symbol"] == "TSM" and fx and tw2330_close:
            u["premium"] = adr_premium(u["close"], fx["close"], tw2330_close)
    night = None
    try:
        night = mock_night() if mock else fetch_night_session()
    except Exception as e:
        print(f"[warn] night session: {e}")
    return {"us": us, "fx": fx, "night": night}


# ---------- mock ----------
def mock_yahoo(symbol: str, base: float = 100) -> pd.DataFrame:
    g = np.random.default_rng(zlib.crc32(symbol.encode()))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=5)
    return pd.DataFrame({"date": dates, "close": base * np.exp(np.cumsum(g.normal(0, 0.012, 5)))})


def mock_night() -> dict:
    return {"date": dt.date.today().strftime("%Y%m%d"), "month": "202611", "last": 23456.0, "change": 120.0,
            "pct": 0.51, "day_last": 23336.0}
