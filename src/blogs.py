"""大神文章：從 RSS 抓最近一次晨報之後的新文章。"""
import datetime as dt
import html
import re

import feedparser
import requests

TPE = dt.timezone(dt.timedelta(hours=8))


def _lookback_hours(now: dt.datetime) -> int:
    """週一要涵蓋整個週末；其他天抓過去一天多一點，避免同一篇重複出現。"""
    return 80 if now.astimezone(TPE).weekday() == 0 else 30


def _plain(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _entry_time(e) -> dt.datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    return dt.datetime(*t[:6], tzinfo=dt.timezone.utc) if t else None


def fetch_posts(sources: list[dict], results: list[dict], max_posts: int = 5,
                now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(hours=_lookback_hours(now))
    keys = [r["name"] for r in results] + [r["id"] for r in results]
    posts = []
    for src in sources:
        try:
            r = requests.get(src["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0 stock-brief"})
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            print(f"[warn] blog {src.get('name')}: {e}")
            continue
        for e in feed.entries:
            t = _entry_time(e)
            if not t or t < since:
                continue
            body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
            text = _plain(body)[:3000]
            title = _plain(e.get("title", ""))
            if src.get("only_related") and not any(k in title or k in text for k in keys):
                continue
            posts.append({"source": src["name"], "note": src.get("note", ""), "title": title,
                          "link": e.get("link", ""), "text": text, "time": t})
    posts.sort(key=lambda p: p["time"], reverse=True)
    return posts[:max_posts]


def mock_posts() -> list[dict]:
    t = dt.datetime.now(dt.timezone.utc)
    return [
        {"source": "Damodaran", "note": "估值", "title": "Stock Prices, Earnings and Cashflows: The AI Effect plays through!",
         "link": "https://aswathdamodaran.blogspot.com/", "time": t,
         "text": "AI spending is showing up in earnings for chip makers while software valuations remain stretched..."},
        {"source": "股感 StockFeel", "note": "法說會", "title": "聯詠 3034 法說會重點：驅動 IC 庫存去化完成",
         "link": "https://www.stockfeel.com.tw/", "time": t,
         "text": "聯詠表示第四季面板驅動 IC 需求回穩，SoC 產品線受惠電視與車用..."},
    ]
