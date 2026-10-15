"""LINE Messaging API push. Without credentials it just prints."""
import html
import re

import requests


def html_to_plain(text: str) -> str:
    """報告文字 → 純文字（LINE 不支援格式）。連結轉成「文字：URL」。"""
    text = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2：\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def send_line(text: str, token: str | None, user_id: str | None) -> None:
    plain = html_to_plain(text)[:5000]  # LINE 單則上限 5000 字
    if not token or not user_id:
        print("[notify] LINE_TOKEN / LINE_USER_ID 未設定，改印出訊息：\n")
        print(plain)
        return
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {token}"},
        json={"to": user_id, "messages": [{"type": "text", "text": plain}]},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"LINE push failed {r.status_code}: {r.text}")
    print("[notify] LINE 已送出")
