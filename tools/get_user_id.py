"""一次性工具：在本機接收 LINE webhook，印出傳訊者／加好友者的 user ID。

用法：
  LINE_CHANNEL_SECRET=你的channel_secret python tools/get_user_id.py
  另開一個終端機：cloudflared tunnel --url http://localhost:8000
  把 cloudflared 給的 https://xxxx.trycloudflare.com 加上 /callback 填到 LINE 的 Webhook URL

安全設計：
  - 驗證 X-Line-Signature（HMAC-SHA256），不是 LINE 發的請求一律拒絕
  - 只印出事件類型與 user ID，不記錄訊息內容，也不寫入任何檔案
  - 只綁定 127.0.0.1，外部只能經由你自己開的 tunnel 連進來；用完 Ctrl+C 關掉即可
"""
import base64
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").encode()
PORT = int(os.environ.get("PORT", "8000"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        sig = self.headers.get("X-Line-Signature", "")
        expected = base64.b64encode(hmac.new(SECRET, body, hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(sig, expected):
            print("[拒絕] 簽章不符，不是來自 LINE 的請求")
            self.send_response(403)
            self.end_headers()
            return
        for ev in json.loads(body or b"{}").get("events", []):
            uid = ev.get("source", {}).get("userId")
            if uid:
                print(f"[{ev.get('type')}] user ID：{uid}")
        self.send_response(200)  # LINE 要求回 200
        self.end_headers()

    def log_message(self, *args):  # 關掉預設的存取紀錄
        pass


if __name__ == "__main__":
    if not SECRET:
        sys.exit("請先設定環境變數 LINE_CHANNEL_SECRET")
    print(f"等待 LINE webhook… http://127.0.0.1:{PORT}/callback （Ctrl+C 結束）")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
