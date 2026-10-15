"""Build Telegram text and the HTML dashboard."""
import html
import json

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ICON = {"bull": "🟢", "bear": "🔴", "info": "🟡"}
UP, DOWN = "#d9363e", "#1a9850"  # 台股慣例：紅漲綠跌


def telegram_text(results: list[dict], dashboard_url: str | None) -> str:
    date = results[0]["date"] if results else ""
    lines = [f"<b>📈 台股晨報</b>（資料日 {date}）", ""]
    for r in sorted(results, key=lambda x: -x["score"]):
        arrow = "▲" if r["change_pct"] >= 0 else "▼"
        lines.append(
            f"<b>{html.escape(r['name'])} {r['id']}</b>  {r['close']:.2f} {arrow}{abs(r['change_pct']):.2f}%"
        )
        if r["foreign"] is not None:
            lines.append(f"　外資 {r['foreign']:+,.0f} 張・投信 {r['trust']:+,.0f} 張")
        for kind, text in r["signals"]:
            lines.append(f"　{ICON[kind]} {html.escape(text)}")
        if not r["signals"]:
            lines.append("　⚪ 無特殊訊號")
        lines.append("")
    if dashboard_url:
        lines.append(f'<a href="{dashboard_url}">開啟 Dashboard</a>')
    lines.append("<i>技術指標僅供參考，非投資建議。</i>")
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


def dashboard_html(results: list[dict], frames: dict, chart_days: int) -> str:
    date = results[0]["date"] if results else ""
    rows, charts = [], []
    for r in sorted(results, key=lambda x: -x["score"]):
        df, inst = frames[r["id"]]
        cls = "up" if r["change_pct"] >= 0 else "down"
        sig = "".join(f'<span class="tag {k}">{html.escape(t)}</span>' for k, t in r["signals"]) or '<span class="muted">—</span>'
        foreign = f"{r['foreign']:+,.0f}" if r["foreign"] is not None else "—"
        rows.append(
            f'<tr><td><a href="#s{r["id"]}">{html.escape(r["name"])}</a><div class="muted">{r["id"]}</div></td>'
            f'<td class="num">{r["close"]:.2f}</td><td class="num {cls}">{r["change_pct"]:+.2f}%</td>'
            f'<td class="num">{r["rsi"]:.0f}</td><td class="num">{foreign}</td><td>{sig}</td></tr>'
        )
        fig = _figure(df.tail(chart_days), inst, f'{r["name"]} {r["id"]}')
        charts.append(f'<section id="s{r["id"]}">' + fig.to_html(full_html=False, include_plotlyjs=False,
                                                                 config={"displayModeBar": False}) + "</section>")

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
</style></head><body><main>
<h1>台股晨報</h1><div class="muted">資料日 {date}・依訊號分數排序</div>
<div class="card"><table>
<thead><tr><th>股票</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num">RSI</th><th class="num">外資(張)</th><th>訊號</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
{''.join(charts)}
<footer>技術指標僅供參考，非投資建議。資料來源：FinMind。</footer>
</main></body></html>"""


MANIFEST = json.dumps({
    "name": "台股晨報", "short_name": "晨報", "start_url": ".", "display": "standalone",
    "background_color": "#ffffff", "theme_color": "#ffffff", "icons": [],
}, ensure_ascii=False, indent=2)
