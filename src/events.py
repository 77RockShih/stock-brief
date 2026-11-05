"""事件行事曆：未來 7 天的除權息（TWSE OpenAPI）、月營收公布期限（規則），
加上專家搜尋時順便找到的法說會／股東會（experts.EVENTS，網址與日期已驗證）。

TWSE OpenAPI /exchangeReport/TWT48U_ALL 是「除權除息預告表」（只涵蓋上市股票；上櫃股票不在其中）。
欄位名稱與日期格式（民國年）以程式容錯解析，抓不到或格式不符就略過。
"""
import datetime as dt
import re

import requests

TWT48U = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"


def _roc_date(v) -> dt.date | None:
    """支援 1151110、115/11/10、2026-11-10、20261110。"""
    s = re.sub(r"[^0-9]", "", str(v or ""))
    try:
        if len(s) == 7:   # 民國 YYYMMDD
            return dt.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
        if len(s) == 8:
            return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None
    return None


def _pick(row: dict, keys: tuple[str, ...]):
    for k in row:
        if any(x.lower() in k.lower() for x in keys):
            return row[k]
    return None


def parse_exdividend(rows: list[dict], ids: set[str], today: dt.date, days: int = 7) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        code = str(_pick(row, ("Code", "代號")) or "").strip()
        d = _roc_date(_pick(row, ("Date", "日期")))
        if code in ids and d and today <= d <= today + dt.timedelta(days=days):
            kind = str(_pick(row, ("Exdividend", "權/息", "除權息")) or "").strip()
            label = "除息" if kind == "息" else "除權" if kind == "權" else "除權息"
            out.setdefault(code, []).append({"type": label, "date": d.isoformat(), "source": "twse"})
    return out


def fetch_exdividend(ids: set[str], today: dt.date) -> dict[str, list[dict]]:
    r = requests.get(TWT48U, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    r.raise_for_status()
    return parse_exdividend(r.json(), ids, today)


def revenue_note(today: dt.date) -> str | None:
    """上市櫃公司須於每月 10 日前公布上月營收。"""
    deadline = today.replace(day=10)
    if today <= deadline <= today + dt.timedelta(days=7):
        last_month = (today.replace(day=1) - dt.timedelta(days=1)).month
        return f"{last_month}月營收 {deadline.month}/10 前公布"
    return None


def merge(*sources: dict[str, list[dict]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for src in sources:
        for sid, evs in (src or {}).items():
            for e in evs:
                if not any(x["date"] == e["date"] and x["type"] == e["type"] for x in out.get(sid, [])):
                    out.setdefault(sid, []).append(e)
    for evs in out.values():
        evs.sort(key=lambda e: e["date"])
    return out


def mock_exdividend(today: dt.date) -> dict[str, list[dict]]:
    return {"1904": [{"type": "除息", "date": (today + dt.timedelta(days=4)).isoformat(), "source": "twse"}]}
