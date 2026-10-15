"""專家看法：用 Claude API 的 web search，找每檔股票近期的券商／分析師／知名投資人觀點。

防止編造的設計：
  - 只能回報搜尋結果裡真的出現過的網址；網址不在搜尋結果中的看法一律丟掉
  - 要求標出是誰（機構或人名）、日期，找不到就回傳空清單
"""
import datetime as dt
import json

import requests

API = "https://api.anthropic.com/v1/messages"

PROMPT = """你是台股研究助理。請用網路搜尋，找出「{name}（{sid}）」最近 {days} 天內，專業人士對這檔股票的看法。

優先順序：
1. 券商／投顧研究報告：評等、目標價調整（例如「某券商調升目標價至 X 元」）
2. 外資券商（如摩根士丹利、高盛、美銀等）的評等或目標價
3. 知名分析師、基金經理人、產業研究機構的具名評論
不要收：只描述股價漲跌的新聞、沒有具名來源的「市場人士」、論壇或社群貼文。

找完後呼叫 report_views 回報，規則：
- 每則看法都要有具名的「who」（機構或人名）與該看法的來源網址 url，url 必須是你搜尋結果中的網址
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
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
                         "user_location": {"type": "approximate", "country": "TW", "timezone": "Asia/Taipei"}},
                        TOOL]},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    return r.json()


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
            # 只保留網址真的來自搜尋結果的看法
            return [v for v in views if v.get("url") in seen_urls][:3]
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
