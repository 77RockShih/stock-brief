"""Technical indicators + rule-based signals."""
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    for n in (5, 20, 60):
        df[f"ma{n}"] = c.rolling(n).mean()

    # RSI(14), Wilder smoothing
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)

    # MACD(12, 26, 9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


def _streak(series: pd.Series) -> int:
    """最近連續同號天數：正數 = 連買，負數 = 連賣。"""
    s = series.dropna()
    if s.empty or s.iloc[-1] == 0:
        return 0
    sign = 1 if s.iloc[-1] > 0 else -1
    n = 0
    for v in reversed(s.tolist()):
        if v * sign > 0:
            n += 1
        else:
            break
    return sign * n


def evaluate(df: pd.DataFrame, inst: pd.DataFrame, rules: dict) -> dict:
    t, y = df.iloc[-1], df.iloc[-2]
    signals: list[tuple[str, str]] = []  # (bull/bear/info, text)

    if y["ma5"] <= y["ma20"] and t["ma5"] > t["ma20"]:
        signals.append(("bull", "MA5 黃金交叉 MA20"))
    if y["ma5"] >= y["ma20"] and t["ma5"] < t["ma20"]:
        signals.append(("bear", "MA5 死亡交叉 MA20"))
    if y["close"] <= y["ma20"] and t["close"] > t["ma20"]:
        signals.append(("bull", "收盤站上 MA20"))
    if y["close"] >= y["ma20"] and t["close"] < t["ma20"]:
        signals.append(("bear", "收盤跌破 MA20"))

    if t["rsi"] >= rules["rsi_overbought"]:
        signals.append(("bear", f"RSI {t['rsi']:.0f} 過熱"))
    elif t["rsi"] <= rules["rsi_oversold"]:
        signals.append(("bull", f"RSI {t['rsi']:.0f} 超賣"))

    if y["macd_hist"] <= 0 < t["macd_hist"]:
        signals.append(("bull", "MACD 柱翻正"))
    if y["macd_hist"] >= 0 > t["macd_hist"]:
        signals.append(("bear", "MACD 柱翻負"))

    vr = t["volume"] / t["vol_ma20"] if t["vol_ma20"] else 0
    if vr >= rules["volume_spike_ratio"]:
        up = t["close"] >= y["close"]  # 爆量要看方向：價漲量增偏多、價跌量增偏空
        signals.append(("bull" if up else "bear", f"爆量{'上漲' if up else '下跌'} {vr:.1f} 倍均量"))

    w = rules["new_high_window"]
    if t["close"] >= df["close"].iloc[-w:].max():
        signals.append(("bull", f"創 {w} 日新高"))
    elif t["close"] <= df["close"].iloc[-w:].min():
        signals.append(("bear", f"創 {w} 日新低"))

    streak = _streak(inst["foreign"]) if not inst.empty else 0
    n = rules["inst_consecutive_days"]
    if streak >= n:
        signals.append(("bull", f"外資連 {streak} 日買超"))
    elif streak <= -n:
        signals.append(("bear", f"外資連 {-streak} 日賣超"))

    last_inst = inst.iloc[-1] if not inst.empty else None
    score = sum(1 if k == "bull" else -1 if k == "bear" else 0 for k, _ in signals)
    return {
        "date": t["date"].strftime("%Y-%m-%d"),
        "close": float(t["close"]),
        "change_pct": float((t["close"] / y["close"] - 1) * 100),
        "rsi": float(t["rsi"]),
        "vol_ratio": float(vr),
        "foreign": float(last_inst["foreign"]) if last_inst is not None else None,
        "trust": float(last_inst["trust"]) if last_inst is not None else None,
        "foreign_streak": streak,
        "trust_streak": _streak(inst["trust"]) if not inst.empty else 0,
        # 金額（億元）為近似值：淨張數 × 1000 股 × 當日收盤價。實際成交均價不同，僅供跨股比較規模。
        "foreign_amt": float(last_inst["foreign"]) * 1000 * float(t["close"]) / 1e8 if last_inst is not None else None,
        "trust_amt": float(last_inst["trust"]) * 1000 * float(t["close"]) / 1e8 if last_inst is not None else None,
        "signals": signals,
        "score": score,
    }
