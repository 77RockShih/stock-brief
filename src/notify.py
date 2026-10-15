"""Telegram push. Without token/chat id it just prints."""
import requests


def send_telegram(text: str, token: str | None, chat_id: str | None) -> None:
    if not token or not chat_id:
        print("[notify] TG_TOKEN / TG_CHAT_ID 未設定，改印出訊息：\n")
        print(text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()
    print("[notify] Telegram 已送出")
