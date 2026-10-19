"""共用的 Claude API 工具呼叫。

不使用 tool_choice 強制呼叫（部分模型不支援 type "tool"／"any"，會回 400），改用預設的 auto，
並在 prompt 裡要求呼叫工具。若回應中沒有 tool_use，追加一輪 user 訊息要求呼叫，最多重試一次；
仍然沒有就回傳 None，並在 log 印出模型回的文字前 200 字，由呼叫端退回規則或簡化版本。
"""
import requests

API = "https://api.anthropic.com/v1/messages"


def _text(content: list) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()


def call_tool(api_key: str, model: str, prompt: str, tool: dict, *, system: str | None = None,
              max_tokens: int = 2000, timeout: int = 120, retries: int = 1, label: str = "") -> dict | None:
    """回傳指定工具的 input（dict）；拿不到就回傳 None。HTTP 錯誤會 raise。"""
    messages = [{"role": "user", "content": prompt}]
    body = {"model": model, "max_tokens": max_tokens, "tools": [tool]}
    if system:
        body["system"] = system
    for attempt in range(retries + 1):
        r = requests.post(API, timeout=timeout, json={**body, "messages": messages},
                          headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"Claude API {r.status_code}: {r.text[:300]}")
        content = r.json().get("content", [])
        block = next((b for b in content if b.get("type") == "tool_use" and b.get("name") == tool["name"]), None)
        if block:
            return block.get("input") or {}
        if attempt < retries:
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": f"請呼叫 {tool['name']} 工具回報結果，不要只用文字回答。"}]
    print(f"[warn] {label or tool['name']}: 模型沒有呼叫工具，回覆前 200 字：{_text(content)[:200]!r}")
    return None
