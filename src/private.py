"""持有人私訊版：持股權重、集中度、損益與離支撐距離。只 push 給 LINE_OWNER_ID，
不進群發、不進 Dashboard、不寫進 repo。

GitHub Secrets
  HOLDINGS       代號:張數[:成本]，逗號分隔。例：3034:2:520,2395:1,0050:5:75.3
                 零股用小數張數（0.3 = 300 股）；成本可省略（省略就不算損益）
  LINE_OWNER_ID  你自己的 LINE user ID（官方帳號 Basic settings → Your user ID）
"""
CONC_WARN = 0.40  # 單一持股超過 40% 提醒


def parse_holdings(s: str | None) -> dict[str, tuple[float, float | None]]:
    out = {}
    for part in (s or "").replace("\n", ",").split(","):
        f = [x.strip() for x in part.split(":")]
        if len(f) < 2 or not f[0]:
            continue
        try:
            lots = float(f[1])
            cost = float(f[2]) if len(f) > 2 and f[2] else None
        except ValueError:
            print(f"[warn] HOLDINGS 格式看不懂：{part}")
            continue
        out[f[0]] = (lots, cost)
    return out


MOCK_HOLDINGS = "3034:3:520,2395:1:600,0050:2,9999:1"


def owner_text(results: list[dict], holdings: dict[str, tuple[float, float | None]]) -> str | None:
    if not holdings:
        return None
    by_id = {r["id"]: r for r in results}
    rows, missing = [], []
    for sid, (lots, cost) in holdings.items():
        r = by_id.get(sid)
        if not r:
            missing.append(sid)
            continue
        rows.append((r, lots, cost, lots * 1000 * r["close"]))
    if not rows:
        return None
    total = sum(v for *_, v in rows)
    rows.sort(key=lambda x: -x[3])
    date = rows[0][0]["date"][5:].replace("-", "/")
    lines = [f"🔒 持股私訊 {date}（只有你收到）", f"市值 {total / 1e4:,.1f} 萬"]
    pnl_total, cost_total = 0.0, 0.0
    for r, lots, cost, v in rows:
        a = r.get("advice") or {}
        w = v / total
        seg = [f"{r['name']} {w * 100:.0f}%"]
        if cost:
            pnl = (r["close"] / cost - 1) * 100
            seg.append(f"損益 {pnl:+.1f}%")
            pnl_total += (r["close"] - cost) * lots * 1000
            cost_total += cost * lots * 1000
        sup = a.get("support")
        if sup:
            gap = (r["close"] / sup - 1) * 100
            seg.append(f"離支撐 {gap:.1f}%" + ("（已跌破）" if gap < 0 else ""))
        st = a.get("stance")
        if st:
            seg.append(st)
        lines.append("・" + "｜".join(seg))
    if cost_total:
        lines.append(f"有成本的部位合計損益 {pnl_total / 1e4:+,.1f} 萬（{pnl_total / cost_total * 100:+.1f}%）")
    top = rows[0]
    if top[3] / total > CONC_WARN:
        lines.append(f"⚠️ 集中度：{top[0]['name']} 佔 {top[3] / total * 100:.0f}%，單一持股超過 {CONC_WARN * 100:.0f}%，"
                     f"它的判斷是「{(top[0].get('advice') or {}).get('stance', '—')}」")
    bears = [r["name"] for r, *_ in rows if (r.get("advice") or {}).get("stance") == "偏空"]
    if bears:
        lines.append("🔻 偏空的持股：" + "、".join(bears))
    if missing:
        lines.append("（不在追蹤清單、沒有報價：" + "、".join(missing) + "）")
    return "\n".join(lines)
