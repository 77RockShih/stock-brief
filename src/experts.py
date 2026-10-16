"""專家看法：用 Claude API 的 web search，找每檔股票近期的券商／分析師／知名投資人觀點。

防止編造的設計：
  - 只能回報搜尋結果裡真的出現過的網址；網址不在搜尋結果中的看法一律丟掉
  - 要求標出是誰（機構或人名）、日期，找不到就回傳空清單
"""
import datetime as dt
from urllib.parse import urlsplit

import requests

API = "https://api.anthropic.com/v1/messages"

PROMPT = """你是台股研究助理。請用網路搜尋，找出「{name}（{sid}）」最近 {days} 天內，專業人士對這檔股票的看法。

建議的搜尋關鍵字（擇優使用）：「{name} 目標價」、「{name} {sid} 評等」、「{name} 投顧 報告」、「{name} 外資 目標價」。

優先順序：
1. 券商／投顧研究報告：評等、目標價調整（例如「某券商調升目標價至 X 元」）
2. 外資券商（如摩根士丹利、高盛、美銀等）的評等或目標價
3. 知名分析師、基金經理人、產業研究機構的具名評論
不要收：只描述股價漲跌的新聞、沒有具名來源的「市場人士」、論壇或社群貼文、公司自己的經營層說法（那屬於公司新聞，不是外部看法）。

找完後呼叫 report_views 回報，規則：
- 每則看法都要有具名的「who」（機構或人名，10 字內，不要加括號說明；外資未具名就寫「美系外資」「歐系外資」）與該看法的來源網址 url，url 必須是你搜尋結果中的網址
- view 用繁體中文、50 字內，寫出理由（不只是結論）
- 日期無法確定就填空字串；沒有目標價就填 null
- 最多 3 則，挑最新、最具體的；真的找不到就回報空清單，不要編造
"""

TOOL = {
    "name": "report_views",
    "description": "回報專業人士對該股票的看法",
    "input_schema": {
        "type": "object",
        "properties": {"views": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "who": {"type": "string", "description": "機構或人名，例如：凱基投顧、摩根士丹利"},
                "stance": {"type": "string", "enum": ["看多", "看空", "中性"]},
                "target_price": {"type": ["number", "null"]},
                "view": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "url": {"type": "string"},
            },
            "required": ["who", "stance", "target_price", "view", "date", "url"],
        }}},
        "required": ["views"],
    },
}


def _call(api_key: str, model: str, messages: list) -> dict:
    r = requests.post(
        API,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 2000, "messages": messages,
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4,
                         "user_location": {"type": "approximate", "country": "TW", "timezone": "Asia/Taipei"}},
                        TOOL]},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    return r.json()


def _norm(url: str) -> str:
    """比對用的網址正規化：忽略 http/https、子網域、查詢參數與結尾斜線；網域主體與路徑必須相同。"""
    u = urlsplit(url.strip())
    labels = u.netloc.lower().split(":")[0].split(".")
    # 只取主網域（news.cnyes.com、m.cnyes.com → cnyes.com；money.udn.com.tw → udn.com.tw），路徑仍須完全相同
    keep = 3 if len(labels) >= 3 and labels[-2] in {"com", "org", "net", "gov", "edu"} and len(labels[-1]) == 2 else 2
    return ".".join(labels[-keep:]) + u.path.rstrip("/")


def stock_views(sid: str, name: str, api_key: str, model: str, days: int = 14) -> list[dict]:
    messages = [{"role": "user", "content": PROMPT.format(name=name, sid=sid, days=days)}]
    seen_urls: set[str] = set()
    for _ in range(4):  # 搜尋可能分好幾輪（pause_turn）
        resp = _call(api_key, model, messages)
        for b in resp["content"]:
            if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
                seen_urls.update(x.get("url", "") for x in b["content"])
        report = next((b for b in resp["content"] if b.get("type") == "tool_use" and b.get("name") == "report_views"), None)
        if report:
            views = report["input"].get("views", [])
            # 只保留網址真的來自搜尋結果的看法（正規化後比對）
            seen = {_norm(u) for u in seen_urls if u}
            kept = [v for v in views if _norm(v.get("url", "")) in seen]
            dropped = len(views) - len(kept)
            if dropped:
                print(f"[info] views {sid}: 回報 {len(views)} 則，{dropped} 則網址不在搜尋結果中已丟棄")
            if not views:
                print(f"[info] views {sid}: 搜尋 {len(seen_urls)} 個結果，沒有符合條件的專家看法")
            return kept[:3]
        if resp.get("stop_reason") != "pause_turn":
            # 模型沒呼叫工具就結束了：提醒它用工具回報
            messages += [{"role": "assistant", "content": resp["content"]},
                         {"role": "user", "content": "請呼叫 report_views 回報結果（找不到就回報空清單）。"}]
        else:
            messages += [{"role": "assistant", "content": resp["content"]}]
    return []


def all_views(results: list[dict], api_key: str | None, model: str, days: int = 14) -> dict[str, list[dict]]:
    if not api_key:
        return {}
    out = {}
    for r in results:
        if r["id"].startswith("00"):  # ETF 略過
            continue
        try:
            out[r["id"]] = stock_views(r["id"], r["name"], api_key, model, days)
            print(f"[ok] views {r['id']}: {len(out[r['id']])}")
        except Exception as e:
            print(f"[warn] views {r['id']}: {e}")
    return out


def mock_views(results: list[dict]) -> dict[str, list[dict]]:
    d = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    return {
        "3034": [{"who": "某投顧", "stance": "看多", "target_price": 620, "date": d, "url": "https://example.com/a",
                  "view": "驅動 IC 庫存去化完成，SoC 新品帶動第四季毛利率回升。"}],
        "3008": [{"who": "某外資券商", "stance": "看空", "target_price": 5800, "date": d, "url": "https://example.com/b",
                  "view": "高階鏡頭規格升級趨緩，明年出貨成長有限。"}],
    }
