"""Claude API: turn each stock's news headlines into a 1–2 line takeaway.

用 tool use + JSON schema 取得結構化輸出（不設 tool_choice，見 claude_api.py），避免標題裡的引號等字元弄壞 JSON。
"""
import json
import re

from .claude_api import call_tool

PROMPT = """你是台股研究助理。以下是投資人持股的最新新聞標題（只有標題，沒有內文）。
請為「有新聞」的每一檔股票寫一則重點，並呼叫 report_news 工具回報。規則：
- 用繁體中文，每檔最多 2 句、60 字內
- 只根據標題內容，不要編造標題裡沒有的數字或事實
- 判斷新聞對股價的傾向：偏多、偏空或中性
- 標題彼此重複或無實質內容（例如單純股價漲跌描述）就合併或略過

新聞資料：
"""

TOOL = {
    "name": "report_news",
    "description": "回報每檔股票的新聞重點",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "股票代號"},
                        "tone": {"type": "string", "enum": ["偏多", "偏空", "中性"]},
                        "summary": {"type": "string", "description": "重點，60 字內"},
                    },
                    "required": ["id", "tone", "summary"],
                },
            }
        },
        "required": ["items"],
    },
}

_SUFFIX = re.compile(r"\s+[-–|｜]\s+[^-–|｜]{1,30}$")  # 去掉「 - CMoney」「 - 自由財經」這類來源後綴


def clean_title(title: str) -> str:
    t = title.strip()
    for _ in range(2):  # 有些標題有兩層後綴：「- 股市爆料同學會 - CMoney」
        t = _SUFFIX.sub("", t)
    return t


def _dedupe(titles: list[str]) -> list[str]:
    out, seen = [], set()
    for t in map(clean_title, titles):
        key = re.sub(r"\W", "", t)[:20]
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def summarize_news(news: dict[str, dict], api_key: str | None, model: str) -> dict[str, dict]:
    """news: {stock_id: {"name": ..., "items": [{title, ...}]}} → {stock_id: {tone, summary}}"""
    payload = {sid: {"name": v["name"], "titles": _dedupe([n["title"] for n in v["items"]])}
               for sid, v in news.items() if v["items"]}
    payload = {k: v for k, v in payload.items() if v["titles"]}
    if not payload:
        return {}
    if not api_key:
        # 沒有 API key 或 API 失敗：退回成直接列前兩則（已清理）標題
        return {sid: {"tone": "", "summary": "；".join(v["titles"][:2])} for sid, v in payload.items()}

    data = call_tool(api_key, model, PROMPT + json.dumps(payload, ensure_ascii=False), TOOL,
                     max_tokens=2000, timeout=60, label="summarize")
    if data is None:
        raise RuntimeError("no tool_use in response")
    return {str(i["id"]): {"tone": i.get("tone", ""), "summary": i["summary"]} for i in data.get("items", [])}
