"""每檔股票的「今日操作傾向」：Claude 根據已抓到的資料做短線判讀；觀察價位由程式計算。

設計原則
  - 所有股票打包成一次 API call，用 tool use 強制結構化輸出。
  - LLM 只能引用輸入中的資料，不得產生任何價格數字；支撐／壓力由 levels() 計算。
  - 回應若含指令式用語（買進、賣出…）或格式不符，該檔改用規則判斷。
  - API 失敗時全部退回規則：score ≥ 2 偏多、≤ -2 偏空、其餘觀望，並標示「（規則判斷）」。
"""
import json
import re

import pandas as pd
from .claude_api import call_tool

STANCES = ["偏多", "觀望", "偏空"]
CONFIDENCE = ["高", "中", "低"]
BANNED = ["買進", "賣出", "加碼", "減碼", "停損", "停利", "進場", "出場", "布局", "抄底", "放空"]

SYSTEM = """你是台股短線研究助理，為投資人整理每檔追蹤股票的「今日盤中到數日」觀察傾向。

規則：
1. 這是短線觀察，不是長期投資建議，也不是交易指令。
2. 禁止使用指令式用語：買進、賣出、加碼、減碼、停損、停利、進場、出場、布局、抄底、放空。
3. 只能根據輸入 JSON 中的資料判斷，不得引用任何輸入以外的資訊（包括你自己知道的公司或產業消息）。
4. 不得自行產生任何價格數字（目標價、支撐、壓力等）。可以引用輸入中已有的數值，例如「外資連7日買超」「RSI 72」。
5. 訊號互相矛盾或資料不足時，給「觀望」＋「低」信心，不要硬給方向。
6. reason：繁體中文 30 字內，必須引用輸入中具體的資料點（例如「外資連7日買超＋站穩MA20」）。
7. risk：繁體中文 20 字內，指出最大的反向風險（例如「外資目標價已低於現價」「RSI過熱」）。
8. 每一檔都要回報，id 必須和輸入相同。

必須呼叫 report_advice 工具一次回報所有股票，不要只用文字回答。"""

TOOL = {
    "name": "report_advice",
    "description": "回報每檔股票的今日短線觀察傾向",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "stance": {"type": "string", "enum": STANCES},
                "confidence": {"type": "string", "enum": CONFIDENCE},
                "reason": {"type": "string", "description": "30 字內，引用輸入中的具體資料點"},
                "risk": {"type": "string", "description": "20 字內，最大的反向風險"},
            },
            "required": ["id", "stance", "confidence", "reason", "risk"],
        }}},
        "required": ["items"],
    },
}


# ---------- 觀察價位（程式計算，不交給 LLM） ----------
def levels(df: pd.DataFrame) -> dict:
    """支撐 = MA20 與近 20 日低點中，位於現價下方且較接近現價者；壓力 = 近 60 日高點（已創高則為「創高中」）。"""
    t = df.iloc[-1]
    close = float(t["close"])
    low20 = float(df["low"].iloc[-20:].min())
    high60 = float(df["high"].iloc[-60:].max())
    cands = [v for v in (float(t["ma20"]), low20) if v == v and v <= close]  # v == v 排除 NaN
    support = max(cands) if cands else low20
    new_high = close >= float(df["close"].iloc[-60:].max())
    return {"support": support, "resistance": None if new_high else high60, "new_high": new_high}


# ---------- 輸入整理 ----------
def _r(v, n=2):
    return None if v is None or v != v else round(float(v), n)


def build_input(results: list[dict], frames: dict, views: dict, night: dict, market: dict | None) -> dict:
    us = (night or {}).get("us", [])
    stocks = []
    for r in results:
        df = frames[r["id"]][0]
        t = df.iloc[-1]
        rev = r.get("revenue") or {}
        d = r.get("digest") or {}
        stocks.append({
            "id": r["id"], "name": r["name"],
            "close": _r(r["close"]), "change_pct": _r(r["change_pct"]),
            "vs_market_today_pct": _r(r.get("rel1")), "vs_market_20d_pct": _r(r.get("rel20")),
            "close_vs_ma5": "above" if t["close"] >= t["ma5"] else "below",
            "close_vs_ma20": "above" if t["close"] >= t["ma20"] else "below",
            "close_vs_ma60": "above" if t["close"] >= t["ma60"] else "below",
            "rsi": _r(r["rsi"], 0), "volume_ratio_vs_20d": _r(r["vol_ratio"], 1),
            "foreign_net_e8": None if r["id"].startswith("00") else _r(r.get("foreign_amt")),
            "foreign_streak_days": None if r["id"].startswith("00") else r.get("foreign_streak"),
            "trust_net_e8": None if r["id"].startswith("00") else _r(r.get("trust_amt")),
            "trust_streak_days": None if r["id"].startswith("00") else r.get("trust_streak"),
            "revenue_yoy_pct": _r(rev.get("yoy"), 1), "revenue_mom_pct": _r(rev.get("mom"), 1),
            "technical_signals": [text for _, text in r.get("signals", [])],
            "news": {"tone": d.get("tone"), "summary": d.get("summary")} if d else None,
            "experts": [{"who": v["who"], "stance": v.get("stance"), "target_price": v.get("target_price"),
                         "target_vs_close_pct": _r((v["target_price"] / r["close"] - 1) * 100, 0) if v.get("target_price") else None,
                         "date": v.get("date")} for v in (views or {}).get(r["id"], [])],
            "related_us_overnight": [{"name": u["name"], "change_pct": _r(u["d1"])} for u in us if r["id"] in u.get("related", [])],
        })
    n = (night or {}).get("night") or {}
    fx = (night or {}).get("fx") or {}
    ctx = {
        "taiex_change_pct": _r((market or {}).get("d1")), "taiex_20d_pct": _r((market or {}).get("d20")),
        "market_foreign_net_e8": _r(((market or {}).get("inst") or {}).get("foreign"), 0),
        "night_futures_change_pct": _r(n.get("pct")) if n and not n.get("stale") else None,
        "usd_twd_change_pct": _r(fx.get("d1")),
    }
    return {"market": ctx, "stocks": stocks}


# ---------- 判斷 ----------
def rule_advice(r: dict) -> dict:
    s = r.get("score", 0)
    stance = "偏多" if s >= 2 else "偏空" if s <= -2 else "觀望"
    sig = "、".join(text.replace(" ", "") for _, text in r.get("signals", [])[:2]) or "無明顯訊號"
    return {"stance": stance, "confidence": "低", "reason": sig[:30], "risk": "", "source": "rule"}


def _valid(it: dict) -> bool:
    text = f"{it.get('reason', '')}{it.get('risk', '')}"
    return (it.get("stance") in STANCES and it.get("confidence") in CONFIDENCE
            and it.get("reason") and not any(w in text for w in BANNED))


def advise(results: list[dict], frames: dict, views: dict, night: dict, market: dict | None,
           api_key: str | None, model: str) -> dict[str, dict]:
    out = {r["id"]: rule_advice(r) for r in results}
    if api_key:
        try:
            payload = build_input(results, frames, views, night, market)
            data = call_tool(api_key, model, json.dumps(payload, ensure_ascii=False), TOOL, system=SYSTEM,
                             max_tokens=3000, label="advisor")
            if data is None:
                raise RuntimeError("no tool_use in response")
            block = {"input": data}
            for it in block["input"].get("items", []):
                sid = str(it.get("id"))
                if sid in out and _valid(it):
                    out[sid] = {"stance": it["stance"], "confidence": it["confidence"],
                                "reason": it["reason"][:34], "risk": it.get("risk", "")[:24], "source": "ai"}
                elif sid in out:
                    print(f"[warn] advisor {sid}: invalid item, using rule fallback")
        except Exception as e:
            print(f"[warn] advisor failed, rule fallback: {e}")
    for r in results:
        out[r["id"]].update(levels(frames[r["id"]][0]))
    return out


def mock_advise(results: list[dict], frames: dict) -> dict[str, dict]:
    """--mock：依訊號方向給出看起來像 AI 的結果；ETF 那檔走規則退回，讓兩種顯示都看得到。"""
    out = {}
    for r in results:
        if r["id"].startswith("00"):
            out[r["id"]] = rule_advice(r)
        else:
            kinds = {k for k, _ in r.get("signals", [])}
            stance = ("偏多" if "bull" in kinds and "bear" not in kinds else
                      "偏空" if "bear" in kinds and "bull" not in kinds else "觀望")
            conf = "低" if stance == "觀望" else "中"
            sig = "＋".join(re.sub(r"\s", "", t) for _, t in r.get("signals", [])[:2]) or "無明顯訊號，量價平淡"
            out[r["id"]] = {"stance": stance, "confidence": conf, "reason": sig[:30],
                            "risk": {"偏多": "大盤轉弱拖累", "偏空": "跌深反彈"}.get(stance, "多空訊號分歧"),
                            "source": "ai"}
        out[r["id"]].update(levels(frames[r["id"]][0]))
    return out
