"""Build LINE message text and the HTML dashboard."""
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
    return f"{rev['month']}月營收 {rev['revenue_e8']:,.1f} 億｜YoY {_pct(rev['yoy'])}・MoM {_pct(rev['mom'])}"


def _rel_line(r: dict) -> str | None:
    if r.get("rel20") is None:
        return None
    return f"　📐 相對大盤：今日 {r['rel1']:+.1f}%・20 日 {r['rel20']:+.1f}%"


def message_text(results: list[dict], dashboard_url: str | None, commodities: list[dict] | None = None,
                 market: dict | None = None, views: dict[str, list[dict]] | None = None,
                 night: dict | None = None) -> str:
    date = results[0]["date"] if results else ""
    names = {r["id"]: r["name"] for r in results}
    lines = [f"<b>📈 台股晨報</b>（資料日 {date}）", ""]

    if night and (night.get("us") or night.get("night")):
        us = night.get("us", [])
        d = us[0]["date"][5:].replace("-", "/") if us else ""
        lines.append(f"<b>🌙 昨夜美股</b>（{d}）" if d else "<b>🌙 盤前</b>")
        for u in us:
            rel = "、".join(names.get(x, x) for x in u.get("related", []))
            extra_ = f"｜ADR 溢價 {u['premium']:+.1f}%" if u.get("premium") is not None else ""
            lines.append(f"　{u['name']} {u['close']:,.2f}｜{_pct(u['d1'])}{extra_}" + (f"（{rel}）" if rel else ""))
        fx = night.get("fx")
        if fx:
            lines.append(f"　美元/台幣 {fx['close']:.3f}｜{_pct(fx['d1'])}")
        n = night.get("night")
        if n and n.get("last"):
            chg = f"{n['change']:+,.0f}" if n.get("change") is not None else ""
            pct = f"（{n['pct']:+.2f}%）" if n.get("pct") is not None else ""
            vs = ""
            if market and market.get("close"):
                vs = f"｜比加權收盤 {n['last'] - market['close']:+,.0f} 點"
            lines.append(f"　🌃 台指期夜盤 {n['last']:,.0f} {chg}{pct}{vs}")
        lines.append("")

    if market:
        lines.append(f"<b>🏛 加權指數</b> {market['close']:,.0f}｜今日 {_pct(market['d1'])}・20 日 {_pct(market['d20'])}")
        lines.append("")

    if commodities:
        lines.append("<b>🔩 原物料</b>")
        for c in commodities:
            rel = "、".join(names.get(x, x) for x in c.get("related", []))
            lines.append(f"　{c['name']} {c['close']:.3f} {c.get('unit', '')}｜日 {_pct(c['d1'])}・週 {_pct(c['d5'])}・月 {_pct(c['d20'])}"
                         + (f"（{rel}）" if rel else ""))
        lines.append("")

    for r in sorted(results, key=lambda x: -x["score"]):
        arrow = "▲" if r["change_pct"] >= 0 else "▼"
        lines.append(
            f"<b>{html.escape(r['name'])} {r['id']}</b>  {r['close']:.2f} {arrow}{abs(r['change_pct']):.2f}%"
        )
        if r["foreign"] is not None:
            lines.append(f"　外資 {r['foreign']:+,.0f} 張・投信 {r['trust']:+,.0f} 張")
        rev = _rev_text(r.get("revenue"))
        if rev:
            lines.append(f"　📊 {rev}")
        rel = _rel_line(r)
        if rel:
            lines.append(rel)
        for kind, text in r["signals"]:
            lines.append(f"　{ICON[kind]} {html.escape(text)}")
        if not r["signals"]:
            lines.append("　⚪ 無技術訊號")
        d = r.get("digest")
        if d:
            lines.append(f"　📰 {TONE.get(d['tone'], '')}{html.escape(d['summary'])}")
        for v in (views or {}).get(r["id"], []):
            tp = f"｜目標價 {v['target_price']:,.0f}" if v.get("target_price") else ""
            date = f"（{v['date'][5:].replace('-', '/')}）" if v.get("date") else ""
            lines.append(f"　👤 {STANCE.get(v['stance'], '')}{html.escape(v['who'])}{tp}{date}")
            lines.append(f"　　{html.escape(v['view'])}")
            lines.append(f"　　{v['url']}")
        lines.append("")
    if dashboard_url:
        lines.append(f'<a href="{dashboard_url}">開啟 Dashboard</a>')
    lines.append("<i>🔴 偏多　🟢 偏空　⚪ 中性｜技術指標、AI 摘要與專家看法僅供參考，非投資建議。</i>")
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


def dashboard_html(results: list[dict], frames: dict, chart_days: int, commodities: list[dict] | None = None,
                   market: dict | None = None) -> str:
    date = results[0]["date"] if results else ""
    rows, charts = [], []
    for r in sorted(results, key=lambda x: -x["score"]):
        df, inst = frames[r["id"]]
        cls = "up" if r["change_pct"] >= 0 else "down"
        sig = "".join(f'<span class="tag {k}">{html.escape(t)}</span>' for k, t in r["signals"]) or '<span class="muted">—</span>'
        foreign = f"{r['foreign']:+,.0f}" if r["foreign"] is not None else "—"
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
            f'<tr><td><a href="#s{r["id"]}">{html.escape(r["name"])}</a><div class="muted">{r["id"]}</div></td>'
            f'<td class="num">{r["close"]:.2f}</td><td class="num {cls}">{r["change_pct"]:+.2f}%</td>'
            f'<td class="num">{r["rsi"]:.0f}</td><td class="num">{foreign}</td><td class="num">{rel}</td><td class="num">{yoy}</td><td>{sig}</td></tr>'
        )
        fig = _figure(df.tail(chart_days), inst, f'{r["name"]} {r["id"]}')
        charts.append(f'<section id="s{r["id"]}">' + fig.to_html(full_html=False, include_plotlyjs=False,
                                                                 config={"displayModeBar": False})
                      + (f'<div class="news"><div class="muted">相關新聞</div><ul>{news_html}</ul></div>' if news_html else "")
                      + "</section>")

    mk = ""
    if market:
        mk = (f'<div class="muted">加權指數 {market["close"]:,.0f}｜今日 '
              f'<span class="{"up" if market["d1"] >= 0 else "down"}">{market["d1"]:+.2f}%</span>・20 日 '
              f'<span class="{"up" if market["d20"] >= 0 else "down"}">{market["d20"]:+.1f}%</span></div>')
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
.news {{ padding:4px 12px 10px }} .news ul {{ margin:4px 0; padding-left:18px }} .news li {{ margin:3px 0; font-size:14px }}
</style></head><body><main>
<h1>台股晨報</h1><div class="muted">資料日 {date}・依訊號分數排序</div>
{mk}
<div class="card"><table>
<thead><tr><th>股票</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num">RSI</th><th class="num">外資(張)</th><th class="num">相對大盤20日</th><th class="num">營收YoY</th><th>訊號</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
{comm}
{''.join(charts)}
<footer>技術指標僅供參考，非投資建議。資料來源：FinMind、Yahoo Finance。</footer>
</main></body></html>"""


MANIFEST = json.dumps({
    "name": "台股晨報", "short_name": "晨報", "start_url": ".", "display": "standalone",
    "background_color": "#ffffff", "theme_color": "#ffffff", "icons": [],
}, ensure_ascii=False, indent=2)
