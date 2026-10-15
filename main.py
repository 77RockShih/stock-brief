"""Daily stock brief: fetch → analyze → dashboard + LINE.

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

from src import analyze, experts, extra, fetch, market as mkt, notify, overnight, report, summarize

ROOT = Path(__file__).parent
OUT = ROOT / "site"


def _fundamentals(sid: str, name: str, cfg: dict, token: str | None, mock: bool):
    """月營收摘要 + 新聞列表；失敗時回傳空值，不影響主流程。"""
    rev, news = None, []
    try:
        rdf = extra.mock_revenue(sid) if mock else extra.fetch_revenue(sid, token)
        rev = extra.revenue_summary(rdf)
    except Exception as e:
        print(f"[warn] revenue {sid}: {e}", file=sys.stderr)
    if sid.startswith("00"):  # ETF 沒有月營收、新聞也多半是雜訊
        return None, []
    try:
        news = extra.mock_news(sid, name) if mock else extra.fetch_news(sid, cfg.get("news_days", 2), token)
    except Exception as e:
        print(f"[warn] news {sid}: {e}", file=sys.stderr)
    if not mock:
        time.sleep(0.5)
    return rev, news


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
            r["revenue"], r["news"] = _fundamentals(sid, name, cfg, token, args.mock)
            r["ret20"] = float((df.close.iloc[-1] / df.close.iloc[-21] - 1) * 100)
            results.append(r)
            frames[sid] = (df, inst)
            print(f"[ok] {sid} {name}: {len(r['signals'])} signals")
        except Exception as e:  # 單檔失敗不影響其他
            failed.append(sid)
            print(f"[fail] {sid} {name}: {e}", file=sys.stderr)

    if not results:
        print("全部失敗，結束", file=sys.stderr)
        return 1

    # 大盤 + 相對強弱
    market = None
    try:
        mdf = mkt.mock_taiex() if args.mock else mkt.fetch_taiex(start, token)
        market = mkt.market_summary(mdf)
    except Exception as e:
        print(f"[warn] market: {e}", file=sys.stderr)
    for r in results:
        r["rel1"] = r["change_pct"] - market["d1"] if market else None
        r["rel20"] = r["ret20"] - market["d20"] if market else None

    # 盤前：昨夜美股 + 台指期夜盤
    tw2330 = None
    try:
        p = fetch.mock_price("2330", 30) if args.mock else fetch.fetch_price(
            "2330", (dt.date.today() - dt.timedelta(days=14)).isoformat(), token)
        tw2330 = float(p.close.iloc[-1])
    except Exception as e:
        print(f"[warn] 2330 close for ADR premium: {e}", file=sys.stderr)
    night = overnight.collect(cfg.get("overnight", []), tw2330, args.mock)

    # 原物料
    commodities = []
    for c in cfg.get("commodities", []):
        try:
            cdf = extra.mock_commodity(c["symbol"]) if args.mock else extra.fetch_commodity(c["symbol"])
            s = extra.commodity_summary(cdf)
            if s:
                commodities.append({**c, **s})
        except Exception as e:
            print(f"[fail] commodity {c['symbol']}: {e}", file=sys.stderr)

    # 新聞摘要（Claude API）
    news_in = {r["id"]: {"name": r["name"], "items": r["news"]} for r in results}
    try:
        digest = summarize.summarize_news(
            news_in, os.getenv("ANTHROPIC_API_KEY"), cfg.get("llm_model", "claude-haiku-5-5"))
    except Exception as e:  # key 過期或 API 錯誤 → 退回只列標題
        print(f"[warn] summarize failed, fallback to headlines: {e}", file=sys.stderr)
        digest = summarize.summarize_news(news_in, None, "")
    for r in results:
        r["digest"] = digest.get(r["id"])

    # 專家看法（Claude + web search）；只進 LINE，不放公開 dashboard
    views = experts.mock_views(results) if args.mock else experts.all_views(
        results, os.getenv("ANTHROPIC_API_KEY"), cfg.get("llm_model", "claude-haiku-5-5"), cfg.get("expert_days", 14))

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(report.dashboard_html(results, frames, cfg["chart_days"], commodities, market), encoding="utf-8")
    (OUT / "manifest.json").write_text(report.MANIFEST, encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[ok] dashboard → {OUT / 'index.html'}")

    text = report.message_text(results, os.getenv("DASHBOARD_URL"), commodities, market, views, night)
    if failed:
        text += f"\n⚠️ 抓取失敗：{', '.join(failed)}"
    if not args.no_notify:
        notify.send_line(text, os.getenv("LINE_TOKEN"), os.getenv("LINE_USER_ID"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
