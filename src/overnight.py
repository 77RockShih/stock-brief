"""盤前資訊：昨夜美股（Yahoo Finance）與台指期夜盤。

台指期夜盤（盤後交易時段）的日期歸屬規則 —— 改這段程式前務必先讀：
  - 期交所規定：盤後時段（15:00～次日 05:00）的交易歸屬「次一交易日」，
    並與次一交易日的一般時段一起結算、一起公布。
  - 所以官方 OpenAPI `DailyMarketReportFut` 在 D 日早上 06:41 只會有 D-1 的報表，
    裡面 TradingSession=「盤後」的那幾列，是 D-2 晚上的夜盤，不是昨晚（D-1 晚上）的！
    例：10/16 06:41 抓到的「盤後」列，是 10/14 晚上的夜盤（報表 Date=10/15）。
  - 因此優先使用期交所行情網站 mis.taifex.com.tw 的即時報價（非官方 API）取得昨晚到今晨
    05:00 的最後成交價；拿不到才退回 OpenAPI，並在訊息中明確標示是「哪一晚」的夜盤。
  - 漲跌的參考點是「前一個一般時段的結算價」（MIS 的 CRefPrice）。期貨與加權現貨之間
    有基差，不能拿夜盤和加權指數收盤相減。
"""
import datetime as dt
import json
import zlib

import numpy as np
import pandas as pd
import requests

from .extra import fetch_commodity as fetch_yahoo  # 同一支 Yahoo chart API

TAIFEX_FUT = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
MIS_QUOTES = "https://mis.taifex.com.tw/futures/api/getQuoteList"
TPE = dt.timezone(dt.timedelta(hours=8))


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
    """OpenAPI 近月合約：排除價差（含 /）與週契約（含 W），取成交量最大者。"""
    rows = [r for r in rows if r.get("ContractMonth(Week)") and "/" not in r["ContractMonth(Week)"]
            and "W" not in r["ContractMonth(Week)"].upper()]
    rows.sort(key=lambda r: (_num(r.get("Volume")) or 0), reverse=True)
    return rows[0] if rows else None


def _prev_trading_day(d: dt.date, trading_dates: list[dt.date]) -> dt.date:
    earlier = [x for x in trading_dates if x < d]
    if earlier:
        return max(earlier)
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def fetch_night_mis(timeout: int = 10) -> dict | None:
    """期交所行情網站（非官方）：盤後時段 TXF 即時報價。回傳近月（成交量最大）的最後成交價與參考價。"""
    payload = {"MarketType": "1", "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "",
               "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}
    r = requests.post(MIS_QUOTES, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=timeout,
                      headers={"Content-Type": "application/json;charset=UTF-8", "User-Agent": "Mozilla/5.0",
                               "Origin": "https://mis.taifex.com.tw", "Referer": "https://mis.taifex.com.tw/futures/"})
    r.raise_for_status()
    j = r.json()
    if str(j.get("RtCode")) != "0":
        raise RuntimeError(f"MIS RtCode={j.get('RtCode')} {j.get('RtMsg', '')}")
    quotes = [q for q in j.get("RtData", {}).get("QuoteList", [])
              if str(q.get("SymbolID", "")).startswith("TXF") and "/" not in str(q.get("SymbolID", ""))
              and (_num(q.get("CLastPrice")) or 0) > 0 and (_num(q.get("CRefPrice")) or 0) > 0]
    night = [q for q in quotes if str(q.get("SymbolID", "")).endswith("-M")] or quotes  # 盤後時段代號結尾為 -M
    if not night:
        return None
    q = max(night, key=lambda x: _num(x.get("CTotalVolume")) or 0)
    last, ref = _num(q["CLastPrice"]), _num(q["CRefPrice"])
    return {"source": "mis", "symbol": q.get("SymbolID"), "last": last, "ref": ref,
            "change": last - ref, "pct": (last / ref - 1) * 100, "time": str(q.get("CTime", ""))}


def fetch_night_openapi(contract: str = "TX") -> dict | None:
    """官方 OpenAPI（退回用）。注意：盤後列的 Date 是「歸屬交易日」，實際交易在前一交易日晚上。"""
    r = requests.get(TAIFEX_FUT, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    r.raise_for_status()
    rows = [x for x in r.json() if str(x.get("Contract", "")).strip().upper() == contract]
    night = _front([x for x in rows if str(x.get("TradingSession", "")).strip() == "盤後"])
    if not night:
        return None
    last, chg = _num(night.get("Last")), _num(night.get("Change"))
    pct = _num(str(night.get("%", "")).replace("%", ""))
    if pct is None and last and chg is not None and last != chg:
        pct = chg / (last - chg) * 100
    return {"source": "openapi", "attributed": str(night.get("Date", "")), "last": last, "change": chg, "pct": pct}


def night_session(last_close: dt.date | None, trading_dates: list[dt.date], mock: bool = False,
                  now: dt.datetime | None = None) -> dict | None:
    """回傳夜盤資料並標上「哪一晚」：session_date = 該夜盤開始的那個交易日（15:00 開盤）。"""
    now = (now or dt.datetime.now(TPE)).astimezone(TPE)
    if mock:
        n = mock_night()
    else:
        n = None
        try:
            n = fetch_night_mis()
        except Exception as e:
            print(f"[warn] night session (MIS): {e}")
        if n is None:
            try:
                n = fetch_night_openapi()
            except Exception as e:
                print(f"[warn] night session (OpenAPI): {e}")
    if not n or not n.get("last"):
        return None
    if n["source"] == "openapi":
        try:
            attributed = dt.datetime.strptime(n["attributed"][:10].replace("/", "").replace("-", ""), "%Y%m%d").date()
            n["session_date"] = _prev_trading_day(attributed, trading_dates)
        except ValueError:
            n["session_date"] = None
    else:
        n["session_date"] = last_close
    sd = n.get("session_date")
    # 夜盤 15:00 開盤、次日 05:00 收盤；執行時間落在這段期間就標示「進行中」
    n["in_progress"] = bool(sd) and (
        (now.date() == sd and now.hour >= 15) or (now.date() == sd + dt.timedelta(days=1) and now.hour < 5))
    # 不是最近一個交易日晚上的夜盤 → 標示過期
    n["stale"] = bool(sd and last_close and sd < last_close)
    return n


# ---------- 整合 ----------
def collect(cfg_items: list[dict], tw2330_close: float | None, mock: bool,
            last_close: dt.date | None = None, trading_dates: list[dt.date] | None = None) -> dict:
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
        night = night_session(last_close, trading_dates or [], mock)
    except Exception as e:
        print(f"[warn] night session: {e}")
    return {"us": us, "fx": fx, "night": night}


# ---------- mock ----------
def mock_yahoo(symbol: str, base: float = 100) -> pd.DataFrame:
    g = np.random.default_rng(zlib.crc32(symbol.encode()))
    dates = pd.bdate_range(end=dt.date.today() - dt.timedelta(days=1), periods=5)
    return pd.DataFrame({"date": dates, "close": base * np.exp(np.cumsum(g.normal(0, 0.012, 5)))})


def mock_night() -> dict:
    return {"source": "mis", "symbol": "TXFK6-M", "last": 23456.0, "ref": 23736.0,
            "change": -280.0, "pct": -1.18, "time": "045959"}
