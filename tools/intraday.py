"""盤中破支撐提醒：讀今天晨報算好的支撐（data/advice_history.csv 最新一天），
抓證交所即時報價（MIS），現價跌破支撐就 push 給 LINE_OWNER_ID（只有你）。

  python tools/intraday.py               # 正式：盤中才會跑，有跌破才推
  python tools/intraday.py --mock        # 模擬報價，只印出不推
  python tools/intraday.py --force       # 不檢查是否在盤中（測試用）

同一檔同一天只提醒一次：已提醒的代號寫在 data/intraday_sent.txt（workflow 用 cache 帶到下一次執行，不 commit）。
LINE 額度：沒跌破就不推；有跌破時一次執行只推 1 則給 1 人。
"""
import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import history, notify  # noqa: E402

TPE = dt.timezone(dt.timedelta(hours=8))
HISTORY = ROOT / "data" / "advice_history.csv"
SENT = ROOT / "data" / "intraday_sent.txt"
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def latest_levels(hist: pd.DataFrame, today: dt.date) -> pd.DataFrame:
    if hist.empty:
        return hist
    last = hist["date"].max()
    if (today - dt.date.fromisoformat(last)).days > 5:  # 晨報好幾天沒跑，支撐太舊不用
        print(f"[intraday] 最新紀錄 {last} 太舊，略過")
        return hist.iloc[0:0]
    d = hist[(hist["date"] == last) & hist["support"].notna()]
    return d.drop_duplicates("id", keep="last")


def fetch_quotes(ids: list[str]) -> dict[str, dict]:
    """上市／上櫃不確定，兩種前綴都問，MIS 只回存在的。"""
    ch = "|".join(f"{ex}_{i}.tw" for i in ids for ex in ("tse", "otc"))
    r = requests.get(MIS, params={"ex_ch": ch, "json": "1", "delay": "0"},
                     headers={"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"},
                     timeout=20)
    r.raise_for_status()
    out = {}
    for m in r.json().get("msgArray", []):
        px = _num(m.get("z")) or _num((m.get("b") or "").split("_")[0])  # 沒成交就用最佳買價
        if px:
            out[m["c"]] = {"price": px, "low": _num(m.get("l")), "date": m.get("d"), "time": m.get("t")}
    return out


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def mock_quotes(levels: pd.DataFrame, today: dt.date) -> dict[str, dict]:
    out = {}
    for i, row in enumerate(levels.itertuples()):
        px = row.support * (0.98 if i % 3 == 0 else 1.03)  # 每三檔有一檔跌破
        out[str(row.id)] = {"price": round(px, 2), "low": round(px * 0.995, 2), "date": f"{today:%Y%m%d}", "time": "10:30:00"}
    return out


def alert_text(levels: pd.DataFrame, quotes: dict, already: set[str], today: dt.date) -> tuple[str | None, list[str]]:
    hits = []
    for row in levels.itertuples():
        sid = str(row.id)
        q = quotes.get(sid)
        if not q or sid in already or q["date"] != f"{today:%Y%m%d}":
            continue
        if q["price"] < row.support:
            gap = (q["price"] / row.support - 1) * 100
            hits.append((sid, f"・{row.name} {q['price']:g} 跌破支撐 {row.support:g}（{gap:.1f}%）｜晨報判斷：{row.stance}"))
    if not hits:
        return None, []
    t = max(quotes[s]["time"] for s, _ in hits)[:5]
    lines = [f"⚠️ 盤中破支撐 {today:%m/%d} {t}"] + [h for _, h in hits] + ["（只是提醒，不是賣出建議；收盤前可能拉回）"]
    return "\n".join(lines), [s for s, _ in hits]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--force", action="store_true", help="不檢查盤中時間")
    args = ap.parse_args()

    now = dt.datetime.now(TPE)
    today = now.date()
    if not args.force and not args.mock and (now.weekday() >= 5 or not (dt.time(9, 5) <= now.time() <= dt.time(13, 30))):
        print(f"[intraday] 現在 {now:%H:%M} 不在盤中，略過（GitHub 排程可能延遲）")
        return 0

    levels = latest_levels(history.load(HISTORY), today)
    if levels.empty:
        print("[intraday] 沒有可用的支撐")
        return 0
    try:
        already = set(SENT.read_text().split()[1:]) if SENT.exists() and SENT.read_text().startswith(f"{today}") else set()
    except Exception:
        already = set()

    try:
        quotes = mock_quotes(levels, today) if args.mock else fetch_quotes([str(i) for i in levels["id"]])
    except Exception as e:
        print(f"[warn] MIS 即時報價失敗：{e}")
        return 0
    if not quotes:
        print("[intraday] 抓不到報價（可能休市）")
        return 0

    text, sent = alert_text(levels, quotes, already, today)
    if not text:
        print(f"[intraday] {now:%H:%M} 沒有新的跌破")
        return 0
    owner = os.getenv("LINE_OWNER_ID")
    if args.mock or not owner or "broadcast" in owner or "," in owner:
        print("[intraday] 未推送（--mock 或 LINE_OWNER_ID 未設定／不是單一 ID）：\n" + text)
    else:
        notify.send_line(text, os.getenv("LINE_TOKEN"), owner)
    if not args.mock:
        SENT.parent.mkdir(parents=True, exist_ok=True)
        SENT.write_text(" ".join([str(today), *sorted(already | set(sent))]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
