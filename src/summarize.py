"""Claude API: turn each stock's news headlines into a 1–2 line takeaway."""
import json

import requests

API = "https://api.anthropic.com/v1/messages"

PROMPT = """你是台股研究助理。以下是投資人持股的最新新聞標題（只有標題，沒有內文）。
請為「有新聞」的每一檔股票寫一則重點，規則：
- 用繁體中文，每檔最多 2 句、60 字內
- 只根據標題內容，不要編造標題裡沒有的數字或事實
- 判斷新聞對股價的傾向：偏多、偏空或中性
- 標題彼此重複或無實質內容（例如單純股價漲跌描述）就合併或略過

只輸出 JSON，格式：
{"items": [{"id": "股票代號", "tone": "偏多|偏空|中性", "summary": "重點"}]}

新聞資料：
"""


def summarize_news(news: dict[str, dict], api_key: str | None, model: str) -> dict[str, dict]:
    """news: {stock_id: {"name": ..., "items": [{title, source, date}]}} → {stock_id: {tone, summary}}"""
    payload = {sid: {"name": v["name"], "titles": [n["title"] for n in v["items"]]}
               for sid, v in news.items() if v["items"]}
    if not payload:
        return {}
    if not api_key:
        # 沒有 API key：退回成直接列前兩則標題
        return {sid: {"tone": "", "summary": "；".join(v["titles"][:2])} for sid, v in payload.items()}

    r = requests.post(
        API,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 1500,
              "messages": [{"role": "user", "content": PROMPT + json.dumps(payload, ensure_ascii=False)}]},
        timeout=60,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    text = text[text.find("{"): text.rfind("}") + 1]
    items = json.loads(text)["items"]
    return {str(i["id"]): {"tone": i.get("tone", ""), "summary": i["summary"]} for i in items}
