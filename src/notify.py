"""LINE Messaging API push. Without credentials it just prints."""
import html
import re

import requests


def html_to_plain(text: str) -> str:
    """報告文字 → 純文字（LINE 不支援格式）。連結轉成「文字：URL」。"""
    text = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2：\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def split_text(text: str, limit: int = 4800, max_parts: int = 5) -> list[str]:
    """LINE 單則文字上限 5000 字；超過就在段落間切開，同一次推播最多 5 則（額度仍只算 1 則）。"""
    parts, cur = [], ""
    for para in text.split("\n\n"):
        add = para if not cur else cur + "\n\n" + para
        if len(add) <= limit:
            cur = add
        else:
            if cur:
                parts.append(cur)
            cur = para[:limit]
    if cur:
        parts.append(cur)
    return parts[:max_parts]


def send_line(text: str, token: str | None, user_ids: str | None) -> None:
    """user_ids：
      - 單一 ID              → push
      - 逗號分隔多個 ID      → multicast（上限 500 人）
      - "broadcast"          → 推給官方帳號所有好友
    每個收件人各算 1 則額度。"""
    plain = html_to_plain(text)
    ids = [i.strip() for i in (user_ids or "").split(",") if i.strip()]
    if not token or not ids:
        print("[notify] LINE_TOKEN / LINE_USER_ID 未設定，改印出訊息：\n")
        print(plain)
        return
    messages = [{"type": "text", "text": c} for c in split_text(plain)]
    if ids == ["broadcast"]:
        r = requests.post("https://api.line.me/v2/bot/message/broadcast",
                          headers={"Authorization": f"Bearer {token}"}, json={"messages": messages}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"LINE broadcast failed {r.status_code}: {r.text}")
        print("[notify] LINE 已群發給所有好友")
        return
    if len(ids) == 1:
        url, body = "https://api.line.me/v2/bot/message/push", {"to": ids[0], "messages": messages}
    else:
        url, body = "https://api.line.me/v2/bot/message/multicast", {"to": ids[:500], "messages": messages}
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"LINE send failed {r.status_code}: {r.text}")
    print(f"[notify] LINE 已送出（{len(ids)} 人）")
