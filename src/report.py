"""Build LINE message text and the HTML dashboard."""
import datetime as dt
import html
import json

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ICON = {"bull": "🔴", "bear": "🟢", "info": "🟡"}  # 台股慣例：紅＝偏多、綠＝偏空
UP, DOWN = "#d9363e", "#1a9850"  # 台股慣例：紅漲綠跌


TONE = {"偏多": "🔴", "偏空": "🟢", "中性": "⚪"}
STANCE = {"看多": "🔴", "看空": "🟢", "中性": "⚪"}


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def _rev_text(rev: dict | None) -> str | None:
    if not rev:
        return None
    e8 = rev["revenue_e8"]
    amount = f"{e8:,.1f} 億" if e8 >= 1 else f"{e8 * 100:,.1f} 百萬"  # 小型股不到 1 億改用百萬元
    return f"{rev['month']}月營收 {amount}｜YoY {_pct(rev['yoy'])}・MoM {_pct(rev['mom'])}"


def amt_text(v: float) -> str:
    """億元金額，依大小調整小數位。"""
    a = abs(v)
    return f"{v:+,.0f} 億" if a >= 10 else f"{v:+.1f} 億" if a >= 1 else f"{v:+.2f} 億"


def inst_text(r: dict) -> str | None:
    """外資／投信買賣超：金額（億，用收盤價估算的近似值）為主，括號保留張數。"""
    if r.get("foreign") is None or r.get("foreign_amt") is None:
        return None
    if str(r.get("id", "")).startswith("00"):  # ETF 的法人買賣超受申贖與造市影響，參考價值低
        return None
    return (f"外資 {amt_text(r['foreign_amt'])}（{r['foreign']:+,.0f} 張）・"
            f"投信 {amt_text(r['trust_amt'])}（{r['trust']:+,.0f} 張）")


def fx_text(fx: dict) -> str:
    """USD/TWD 上升 = 台幣貶值；用「台幣升／貶」表達比 ± 直觀。"""
    d = fx["d1"]
    if abs(d) < 0.05:
        return "台幣持平"
    return f"台幣{'貶' if d > 0 else '升'} {abs(d):.1f}%"


def night_text(n: dict, short: bool = False) -> str:
    """夜盤一行文字：一定標出「哪一晚」，漲跌參考點是前一日一般時段結算價（不和加權現貨比）。"""
    sd = n.get("session_date")
    label = f"{sd.month}/{sd.day} 夜盤" if sd else "夜盤（日期不明）"
    if n.get("in_progress"):
        label += "（進行中）"
    pct = f"{n['pct']:+.1f}%" if n.get("pct") is not None else ""
    if short:
        s = f"{label} {pct}"
    else:
        chg = f"{n['change']:+,.0f}" if n.get("change") is not None else ""
        s = f"🌃 台指期{label} {n['last']:,.0f}｜{chg}（{pct}）vs 前日一般時段結算"
    if n.get("stale"):
        s += "⚠️非昨晚資料"
    return s


def _events(r: dict) -> list[tuple[int, str]]:
    """個股的重點事件與權重（給 TL;DR 挑選用）。"""
    ev = []
    for kind, text in r.get("signals", []):
        t = text.replace(" ", "")
        if "新高" in t or "新低" in t:
            ev.append((3, t))
        elif "爆量" in t:
            ev.append((1, t.split("倍")[0] + "倍"))
    fs = r.get("foreign_streak") or 0
    if abs(fs) >= 5 and not str(r.get("id", "")).startswith("00"):
        ev.append((2, f"外資連{abs(fs)}{'買' if fs > 0 else '賣'}"))
    return ev


def tldr_lines(results: list[dict], market: dict | None, night: dict | None, limit: int = 3) -> list[str]:
    """推播預覽只看得到開頭：用規則挑今天最重要的 2–3 件事。"""
    out = []
    head = []
    n = (night or {}).get("night")
    if n and n.get("pct") is not None:
        head.append(night_text(n, short=True))
    if market and abs(market.get("d1", 0)) >= 2:
        head.append(f"加權{'大漲' if market['d1'] > 0 else '重挫'} {abs(market['d1']):.1f}%")
    if head:
        out.append("｜".join(head))
    ranked = sorted(((sum(w for w, _ in _events(r)), r) for r in results), key=lambda x: -x[0])
    for w, r in ranked:
        if w <= 0 or len(out) >= limit:
            break
        evs = [t for _, t in sorted(_events(r), key=lambda x: -x[0])][:2]
        out.append(f"{r['name']}：{'、'.join(evs)}")
    return out[:limit]


def _stale_mark(date_str: str, days: int = 30) -> str:
    """專家看法超過 30 天標 ⏳。"""
    try:
        d = dt.date.fromisoformat(date_str[:10])
    except ValueError:
        return ""
    return " ⏳" if (dt.date.today() - d).days > days else ""


def _rel_line(r: dict) -> str | None:
    if r.get("rel20") is None:
        return None
    return f"　📐 相對大盤：今日 {r['rel1']:+.1f}%・20 日 {r['rel20']:+.1f}%"


STANCE_ICON = {"偏多": "🔴", "觀望": "⚪", "偏空": "🟢"}
STANCE_ORDER = {"偏多": 0, "觀望": 1, "偏空": 2}
CONF_ORDER = {"高": 0, "中": 1, "低": 2}
SHORT_NAME = {"^SOX": "費半"}


def px(v: float | None) -> str:
    """價格顯示：高價股取整數，其餘最多兩位小數（去掉尾端 0）。"""
    if v is None:
        return "—"
    return f"{v:,.0f}" if v >= 500 else f"{v:,.2f}".rstrip("0").rstrip(".")


def _advice_sort_key(r: dict):
    a = r.get("advice") or {}
    return (STANCE_ORDER.get(a.get("stance"), 1), CONF_ORDER.get(a.get("confidence"), 2), -abs(r.get("score", 0)))


def levels_text(a: dict) -> str:
    res = "創高中" if a.get("new_high") else px(a.get("resistance"))
    return f"支撐 {px(a.get('support'))}・壓力 {res}"


def message_text(results: list[dict], dashboard_url: str | None, commodities: list[dict] | None = None,
                 market: dict | None = None, views: dict[str, list[dict]] | None = None,
                 night: dict | None = None, extra_lines: list[str] | None = None) -> str:
    """LINE 精簡版：只放結論。細節（法人張數、營收、技術訊號、新聞、專家原文）都在 Dashboard。"""
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    lines = [f"📈 台股晨報 {today.month}/{today.day}"]

    pre = []
    n = (night or {}).get("night")
    if n and n.get("pct") is not None:
        pre.append(night_text(n, short=True))
    for u in (night or {}).get("us", []):
        if u["symbol"] in SHORT_NAME:
            pre.append(f"{SHORT_NAME[u['symbol']]} {_pct(u['d1'])}")
    fx = (night or {}).get("fx")
    if fx:
        pre.append(fx_text(fx))
    if pre:
        lines.append("🌃 " + "｜".join(pre))

    if market:
        m = f"🏛 加權 {market['close']:,.0f} {market['d1']:+.1f}%"
        mi = market.get("inst")
        if mi:
            m += f"｜外資{'買超' if mi['foreign'] >= 0 else '賣超'} {abs(mi['foreign']):,.0f} 億"
        lines.append(m)

    hl = tldr_lines(results, None, None, limit=2)
    if hl:
        lines.append("📌 今日重點：" + "；".join(hl))
    lines.append("")

    for r in sorted(results, key=_advice_sort_key):
        a = r.get("advice") or {}
        arrow = "▲" if r["change_pct"] >= 0 else "▼"
        tag = f"{a.get('stance', '觀望')}・{a.get('confidence', '低')}" + ("（規則判斷）" if a.get("source") == "rule" else "")
        lines.append(f"{STANCE_ICON.get(a.get('stance'), '⚪')} {r['name']} {px(r['close'])} {arrow}{abs(r['change_pct']):.1f}%｜{tag}")
        if a.get("reason"):
            lines.append(f"　{a['reason']}")
        if a.get("risk"):
            lines.append(f"　⚠ {a['risk']}")
        if a.get("support") is not None:
            lines.append(f"　{levels_text(a)}")
    lines.append("")
    for x in extra_lines or []:
        lines.append(x)
    if dashboard_url:
        lines.append(f"🔗 完整數據與專家看法：{dashboard_url}")
    lines.append(f"AI 判斷僅供參考，非投資建議｜產生於 {today:%m/%d %H:%M}")
    return "\n".join(lines)


def _figure(df: pd.DataFrame, inst: pd.DataFrame, title: str) -> go.Figure:
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.5, 0.15, 0.15, 0.2])
    x = df["date"].dt.strftime("%Y-%m-%d")
    fig.add_trace(go.Candlestick(x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                                 increasing_line_color=UP, decreasing_line_color=DOWN, name="K"), 1, 1)
    for n, color in ((5, "#e69f00"), (20, "#0072b2"), (60, "#9467bd")):
        fig.add_trace(go.Scatter(x=x, y=df[f"ma{n}"], name=f"MA{n}", line=dict(width=1.2, color=color)), 1, 1)

    vcolor = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=x, y=df["volume"], marker_color=vcolor, name="成交量(張)", showlegend=False), 2, 1)

    if not inst.empty:
        m = inst.merge(df[["date"]], on="date", how="right").fillna(0)
        fig.add_trace(go.Bar(x=m["date"].dt.strftime("%Y-%m-%d"), y=m["foreign"],
                             marker_color=[UP if v >= 0 else DOWN for v in m["foreign"]],
                             name="外資(張)", showlegend=False), 3, 1)

    fig.add_trace(go.Scatter(x=x, y=df["rsi"], name="RSI", line=dict(color="#555", width=1.2), showlegend=False), 4, 1)
    for lv in (30, 70):
        fig.add_hline(y=lv, line_dash="dot", line_color="#aaa", row=4, col=1)

    fig.update_layout(title=title, height=640, margin=dict(l=40, r=10, t=50, b=20),
                      xaxis_rangeslider_visible=False, template="plotly_white",
                      legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom"),
                      hovermode="x unified")
    fig.update_xaxes(type="category", nticks=8)
    fig.update_yaxes(title_text="量", row=2, col=1)
    fig.update_yaxes(title_text="外資", row=3, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=4, col=1)
    return fig


def _detail_html(r: dict, views: list[dict]) -> str:
    """每檔卡片最上方：操作傾向、價位，接著是原本放在 LINE 的細節。"""
    a = r.get("advice") or {}
    st = a.get("stance", "觀望")
    cls = {"偏多": "bull", "偏空": "bear"}.get(st, "neutral")
    src = "（規則判斷）" if a.get("source") == "rule" else "（AI）"
    parts = [f'<div class="advice {cls}"><b>{STANCE_ICON.get(st, "⚪")} {st}・{a.get("confidence", "低")}</b>'
             f'<span class="muted">{src}</span><div>{html.escape(a.get("reason", ""))}</div>'
             + (f'<div>⚠ {html.escape(a["risk"])}</div>' if a.get("risk") else "")
             + (f'<div class="muted">{levels_text(a)}</div>' if a.get("support") is not None else "") + "</div>"]
    facts = [x for x in (inst_text(r), _rev_text(r.get("revenue")), (_rel_line(r) or "").strip()) if x]
    if facts:
        parts.append("<ul class='facts'>" + "".join(f"<li>{html.escape(x)}</li>" for x in facts) + "</ul>")
    if r.get("signals"):
        parts.append("".join(f'<span class="tag {k}">{html.escape(t)}</span>' for k, t in r["signals"]))
    d = r.get("digest")
    if d:
        parts.append(f'<p>📰 {TONE.get(d.get("tone"), "")} {html.escape(d["summary"])}</p>')
    for v in views:
        tp = ""
        if v.get("target_price"):
            tp = f"｜目標價 {v['target_price']:,.0f}（距現價 {(v['target_price'] / r['close'] - 1) * 100:+.0f}%）"
        date = f"（{v['date']}{_stale_mark(v['date'])}）" if v.get("date") else ""
        icon = STANCE.get(v.get("stance"), "🔴" if "多" in str(v.get("stance")) else "🟢" if "空" in str(v.get("stance")) else "⚪")
        parts.append(f'<p>👤 {icon} <b>{html.escape(v["who"])}</b>{tp}{date}<br>{html.escape(v["view"])} '
                     f'<a href="{html.escape(v["url"])}" target="_blank" rel="noopener">來源</a></p>')
    return '<div class="detail">' + "".join(parts) + "</div>"


def dashboard_html(results: list[dict], frames: dict, chart_days: int, commodities: list[dict] | None = None,
                   market: dict | None = None, views: dict | None = None, night: dict | None = None) -> str:
    date = results[0]["date"] if results else ""
    rows, charts = [], []
    for r in sorted(results, key=_advice_sort_key):
        df, inst = frames[r["id"]]
        a = r.get("advice") or {}
        stance = f'{STANCE_ICON.get(a.get("stance"), "⚪")} {a.get("stance", "—")}<div class="muted">信心{a.get("confidence", "")}</div>'

        cls = "up" if r["change_pct"] >= 0 else "down"
        sig = "".join(f'<span class="tag {k}">{html.escape(t)}</span>' for k, t in r["signals"]) or '<span class="muted">—</span>'
        foreign = (f"{amt_text(r['foreign_amt'])}<div class=\"muted\">{r['foreign']:+,.0f} 張</div>"
                   if r.get("foreign_amt") is not None else "—")
        rv = r.get("revenue")
        yoy = '<span class="muted">—</span>' if not rv or rv["yoy"] is None else \
            f'<span class="{"up" if rv["yoy"] >= 0 else "down"}">{rv["yoy"]:+.1f}%</span><div class="muted">{rv["month"]}月</div>'
        rel = '<span class="muted">—</span>' if r.get("rel20") is None else \
            f'<span class="{"up" if r["rel20"] >= 0 else "down"}">{r["rel20"]:+.1f}%</span>'
        news_html = "".join(
            f'<li><a href="{html.escape(n["link"])}" target="_blank" rel="noopener">{html.escape(n["title"])}</a>'
            f' <span class="muted">{html.escape(str(n["source"]))}・{html.escape(str(n["date"])[:10])}</span></li>'
            for n in r.get("news", [])[:6])
        rows.append(
            f'<tr><td class="nw"><a href="#s{r["id"]}">{html.escape(r["name"])}</a><div class="muted">{r["id"]}</div></td><td class="nw">{stance}</td>'
            f'<td class="num">{r["close"]:.2f}</td><td class="num {cls}">{r["change_pct"]:+.2f}%</td>'
            f'<td class="num">{r["rsi"]:.0f}</td><td class="num">{foreign}</td><td class="num">{rel}</td><td class="num">{yoy}</td><td>{sig}</td></tr>'
        )
        fig = _figure(df.tail(chart_days), inst, f'{r["name"]} {r["id"]}')
        charts.append(f'<section id="s{r["id"]}"><h3>{html.escape(r["name"])} {r["id"]}</h3>'
                      + _detail_html(r, (views or {}).get(r["id"], [])) + fig.to_html(full_html=False, include_plotlyjs=False,
                                                                 config={"displayModeBar": False})
                      + (f'<div class="news"><div class="muted">相關新聞</div><ul>{news_html}</ul></div>' if news_html else "")
                      + "</section>")

    pre = ""
    if night and (night.get("us") or night.get("night") or night.get("fx")):
        items = [f'{html.escape(u["name"])} {u["close"]:,.2f}｜{_pct(u["d1"])}'
                 + (f'｜ADR 溢價 {u["premium"]:+.1f}%' if u.get("premium") is not None else "") for u in night.get("us", [])]
        if night.get("fx"):
            items.append(f'美元/台幣 {night["fx"]["close"]:.3f}｜{fx_text(night["fx"])}')
        if night.get("night"):
            items.append(html.escape(night_text(night["night"])))
        pre = '<h2>盤前</h2><div class="card"><ul class="facts">' + "".join(f"<li>{x}</li>" for x in items) + "</ul></div>"
    mk = ""
    if market:
        mk = (f'<div class="muted">加權指數 {market["close"]:,.0f}｜今日 '
              f'<span class="{"up" if market["d1"] >= 0 else "down"}">{market["d1"]:+.2f}%</span>・20 日 '
              f'<span class="{"up" if market["d20"] >= 0 else "down"}">{market["d20"]:+.1f}%</span>'
              + (f'｜三大法人：外資 {amt_text(market["inst"]["foreign"])}・投信 {amt_text(market["inst"]["trust"])}'
                 f'・自營商 {amt_text(market["inst"]["dealer"])}' if market.get("inst") else "") + '</div>')
    comm = ""
    if commodities:
        crow = "".join(
            f'<tr><td>{html.escape(c["name"])}<div class="muted">{html.escape(c["symbol"])}</div></td>'
            f'<td class="num">{c["close"]:.3f}</td>'
            + "".join(f'<td class="num {"up" if c[k] >= 0 else "down"}">{c[k]:+.1f}%</td>' for k in ("d1", "d5", "d20"))
            + f'<td>{"、".join(html.escape(str(x)) for x in c.get("related", []))}</td></tr>'
            for c in commodities)
        comm = ('<h2>原物料</h2><div class="card"><table><thead><tr><th>品項</th><th class="num">價格</th>'
                '<th class="num">日</th><th class="num">週</th><th class="num">月</th><th>相關持股</th></tr></thead>'
                f'<tbody>{crow}</tbody></table></div>')

    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>台股晨報</title>
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root {{ --bg:#fafafa; --card:#fff; --fg:#1a1a1a; --muted:#888; --line:#e5e5e5; --up:{UP}; --down:{DOWN}; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,"PingFang TC","Noto Sans TC",sans-serif }}
main {{ max-width:960px; margin:0 auto; padding:16px }}
h1 {{ font-size:22px; margin:8px 0 2px }}
.muted {{ color:var(--muted); font-size:12px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:4px; margin:16px 0; overflow-x:auto }}
table {{ width:100%; border-collapse:collapse }}
th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top }}
th {{ font-size:12px; color:var(--muted); font-weight:500 }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }}
.up {{ color:var(--up) }} .down {{ color:var(--down) }}
a {{ color:inherit }}
.tag {{ display:inline-block; font-size:12px; padding:1px 7px; border-radius:99px; margin:1px 3px 1px 0; white-space:nowrap }}
.tag.bull {{ background:#fde8e8; color:#a4161a }} .tag.bear {{ background:#e3f4e8; color:#11643a }} .tag.info {{ background:#fff4d6; color:#7a5a00 }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; margin:16px 0; padding:4px }}
footer {{ color:var(--muted); font-size:12px; margin:24px 0 }}
h2 {{ font-size:16px; margin:20px 0 4px }}
h3 {{ font-size:17px; margin:10px 12px 4px }}
.detail {{ padding:0 12px 6px; font-size:14px }} .detail p {{ margin:6px 0 }}
.advice {{ border-left:4px solid #bbb; background:#f6f6f6; padding:8px 10px; border-radius:6px; margin:4px 0 8px }}
.advice.bull {{ border-color:var(--up); background:#fdf0f0 }} .advice.bear {{ border-color:var(--down); background:#eef8f1 }}
.facts {{ margin:4px 0; padding-left:18px }}
.nw {{ white-space:nowrap }}
.news {{ padding:4px 12px 10px }} .news ul {{ margin:4px 0; padding-left:18px }} .news li {{ margin:3px 0; font-size:14px }}
</style></head><body><main>
<h1>台股晨報</h1><div class="muted">資料日 {date}・依今日傾向排序</div>
{mk}
{pre}
<div class="card"><table>
<thead><tr><th>股票</th><th>今日傾向</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num">RSI</th><th class="num">外資</th><th class="num">相對大盤20日</th><th class="num">營收YoY</th><th>訊號</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
{comm}
{''.join(charts)}
<footer>AI 判斷、技術指標與專家看法僅供參考，非投資建議。資料來源：FinMind、Yahoo Finance。</footer>
</main></body></html>"""


MANIFEST = json.dumps({
    "name": "台股晨報", "short_name": "晨報", "start_url": ".", "display": "standalone",
    "background_color": "#ffffff", "theme_color": "#ffffff", "icons": [],
}, ensure_ascii=False, indent=2)
