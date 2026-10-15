"""Push channels: Telegram and/or LINE. Sends to whichever has credentials set."""
import html
import re

import requests


def html_to_plain(text: str) -> str:
    """Telegram HTML → 純文字（LINE 不支援格式）。連結轉成「文字：URL」。"""
    text = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2：\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def send_telegram(text: str, token: str, chat_id: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()
    print("[notify] Telegram 已送出")


def send_line(text: str, token: str, user_id: str) -> None:
    """LINE Messaging API push message。單則上限 5000 字。"""
    plain = html_to_plain(text)[:5000]
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {token}"},
        json={"to": user_id, "messages": [{"type": "text", "text": plain}]},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"LINE push failed {r.status_code}: {r.text}")
    print("[notify] LINE 已送出")


def send_all(text: str, env: dict) -> None:
    sent = False
    if env.get("TG_TOKEN") and env.get("TG_CHAT_ID"):
        send_telegram(text, env["TG_TOKEN"], env["TG_CHAT_ID"])
        sent = True
    if env.get("LINE_TOKEN") and env.get("LINE_USER_ID"):
        send_line(text, env["LINE_TOKEN"], env["LINE_USER_ID"])
        sent = True
    if not sent:
        print("[notify] 沒有設定任何推播管道，改印出訊息：\n")
        print(html_to_plain(text))
