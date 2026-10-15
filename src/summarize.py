"""Claude API: turn each stock's news headlines into a 1–2 line takeaway.

用 tool use + JSON schema 強制結構化輸出，避免標題裡的引號等字元弄壞 JSON。
"""
import json
import re

import requests

API = "https://api.anthropic.com/v1/messages"

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

    r = requests.post(
        API,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 2000,
            "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": "report_news"},
            "messages": [{"role": "user", "content": PROMPT + json.dumps(payload, ensure_ascii=False)}],
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
    block = next(b for b in r.json()["content"] if b.get("type") == "tool_use")
    return {str(i["id"]): {"tone": i.get("tone", ""), "summary": i["summary"]} for i in block["input"]["items"]}


# ---------- 大神文章摘要 ----------
POST_PROMPT = """你是投資研究助理。以下是幾篇投資部落格／產業分析的新文章（可能是英文）。
請呼叫 report_posts 工具，為每一篇提供：
- title_zh：標題的繁體中文翻譯（原本就是中文則照抄）
- summary：作者的核心論點，繁體中文 2～3 句、90 字內；只根據提供的內容，不要補充文中沒有的數字或事實；
  若內容只有開頭片段，就摘要片段並在句末加「（僅摘要開頭）」
- related：若文章明確涉及下列追蹤股票或其產業，填股票名稱（多個用頓號）；沒有就留空字串
追蹤股票：{stocks}

文章：
"""

POST_TOOL = {
    "name": "report_posts",
    "description": "回報每篇文章的中文標題、重點與相關持股",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "title_zh": {"type": "string"},
                "summary": {"type": "string"},
                "related": {"type": "string"},
            },
            "required": ["index", "title_zh", "summary", "related"],
        }}},
        "required": ["items"],
    },
}


def summarize_posts(posts: list[dict], api_key: str | None, model: str, results: list[dict]) -> list[dict]:
    base = [{"source": p["source"], "title": p["title"], "link": p["link"], "summary": "", "related": ""} for p in posts]
    if not posts or not api_key:
        return base  # 沒有 key：只列標題與連結
    stocks = "、".join(f"{r['name']}({r['id']})" for r in results)
    payload = [{"index": i, "source": p["source"], "about": p.get("note", ""), "title": p["title"], "content": p["text"]}
               for i, p in enumerate(posts)]
    try:
        r = requests.post(
            API,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 2000, "tools": [POST_TOOL],
                  "tool_choice": {"type": "tool", "name": "report_posts"},
                  "messages": [{"role": "user", "content": POST_PROMPT.format(stocks=stocks)
                                + json.dumps(payload, ensure_ascii=False)}]},
            timeout=90,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
        block = next(b for b in r.json()["content"] if b.get("type") == "tool_use")
        for it in block["input"]["items"]:
            i = it.get("index")
            if isinstance(i, int) and 0 <= i < len(base):
                base[i].update(title=it.get("title_zh") or base[i]["title"],
                               summary=it.get("summary", ""), related=it.get("related", ""))
    except Exception as e:
        print(f"[warn] post summary failed, titles only: {e}")
    return base
