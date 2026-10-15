"""Daily stock brief: fetch → analyze → dashboard + Telegram.

Usage:
  python main.py            # 正式執行（需要 FINMIND_TOKEN）
  python main.py --mock     # 用模擬資料測試，不連網
  python main.py --no-notify
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import yaml

from src import analyze, fetch, notify, report

ROOT = Path(__file__).parent
OUT = ROOT / "site"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use synthetic data")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    token = os.getenv("FINMIND_TOKEN")
    start = (dt.date.today() - dt.timedelta(days=int(cfg["lookback_days"] * 1.5))).isoformat()

    results, frames, failed = [], {}, []
    for sid, name in cfg["watchlist"].items():
        sid = str(sid)
        try:
            if args.mock:
                price = fetch.mock_price(sid, cfg["lookback_days"])
                inst = fetch.mock_institutional(sid, cfg["lookback_days"])
            else:
                price = fetch.fetch_price(sid, start, token)
                inst = fetch.fetch_institutional(sid, start, token)
                time.sleep(0.5)  # 對 API 客氣一點
            if len(price) < 60:
                raise ValueError(f"資料只有 {len(price)} 筆，不足以計算指標")
            df = analyze.add_indicators(price)
            r = analyze.evaluate(df, inst, cfg["rules"])
            r.update(id=sid, name=name)
            results.append(r)
            frames[sid] = (df, inst)
            print(f"[ok] {sid} {name}: {len(r['signals'])} signals")
        except Exception as e:  # 單檔失敗不影響其他
            failed.append(sid)
            print(f"[fail] {sid} {name}: {e}", file=sys.stderr)

    if not results:
        print("全部失敗，結束", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(report.dashboard_html(results, frames, cfg["chart_days"]), encoding="utf-8")
    (OUT / "manifest.json").write_text(report.MANIFEST, encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] dashboard → {OUT / 'index.html'}")

    text = report.telegram_text(results, os.getenv("DASHBOARD_URL"))
    if failed:
        text += f"\n⚠️ 抓取失敗：{', '.join(failed)}"
    if not args.no_notify:
        notify.send_all(text, os.environ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
