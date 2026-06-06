#!/usr/bin/env python3
"""
紫光股份风格的技术分析脚本 - 通用版
当 .so 模块不可用时的手动 fallback。

用法（在 Hermes execute_code 中 import 后调用）:
    from tech_analysis import fetch_klines, compute_indicators, find_gaps
    klines = fetch_klines("sz000938", days=120)
    result = compute_indicators(klines)
    gaps = find_gaps(klines, lookback=60)

依赖: numpy, pandas (pip install numpy pandas)
"""

import os
import sys
import numpy as np

# 加载 TDXClient
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'trade-audit', 'scripts'))
sys.path.insert(0, os.path.expanduser('~/.hermes/local'))  # 私有工具库
from tdx_client import TDXClient

_tdx = TDXClient()


def fetch_realtime(code: str) -> dict:
    """获取实时行情（TDX）。code: sz000938 / sh600000 / 6位纯数字"""
    q = _tdx.quote(code)
    if q is None:
        return None
    price = q['price']
    prev_close = q['prev_close']
    return {
        "name": q.get('code', ''),
        "open": q['open'], "prev_close": prev_close,
        "price": price, "high": q['high'], "low": q['low'],
        "volume": q['volume'], "amount": q.get('amount', 0),
        "date": "", "time": "",
        "change": round(price - prev_close, 2),
        "change_pct": round(q.get('change_pct', 0) or 0, 2),
    }


def fetch_klines(code: str, days: int = 120) -> list:
    """获取日K线（TDX）。code: sz000938 / sh600000 / 6位纯数字"""
    rows = _tdx.kline_day(code, count=days)
    result = []
    for r in rows:
        result.append({
            "day": str(r['time'])[:10],
            "open": r['open'], "high": r['high'],
            "low": r['low'], "close": r['close'],
            "volume": r['volume'],
        })
    return result


def _sma(arr, n):
    """简单移动平均"""
    result = np.full_like(arr, np.nan, dtype=float)
    for i in range(n - 1, len(arr)):
        result[i] = np.mean(arr[i - n + 1 : i + 1])
    return result


def compute_indicators(klines: list) -> dict:
    """
    计算 MA/MACD/RSI/支撑压力位/成交量比。
    输入: fetch_klines() 返回的列表
    返回: dict 含所有指标
    """
    closes = np.array([float(k["close"]) for k in klines])
    opens = np.array([float(k["open"]) for k in klines])
    highs = np.array([float(k["high"]) for k in klines])
    lows = np.array([float(k["low"]) for k in klines])
    volumes = np.array([float(k["volume"]) for k in klines])
    dates = [k["day"] for k in klines]

    # MA
    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)

    # MACD
    ema12 = np.zeros(len(closes))
    ema26 = np.zeros(len(closes))
    ema12[0] = closes[0]
    ema26[0] = closes[0]
    for i in range(1, len(closes)):
        ema12[i] = ema12[i - 1] * 11 / 12 + closes[i] * 1 / 12
        ema26[i] = ema26[i - 1] * 25 / 26 + closes[i] * 1 / 26
    dif = ema12 - ema26
    dea = np.zeros_like(dif)
    dea[0] = dif[0]
    for i in range(1, len(dif)):
        dea[i] = dea[i - 1] * 8 / 10 + dif[i] * 2 / 10
    macd_bar = 2 * (dif - dea)

    # MACD 信号判断
    if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
        macd_signal = "金叉（刚形成）"
    elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
        macd_signal = "死叉（刚形成）"
    elif dif[-1] > dea[-1]:
        macd_signal = "DIF在DEA上方（多头）"
    else:
        macd_signal = "DIF在DEA下方（空头）"

    # RSI(14)
    deltas = np.diff(closes, prepend=closes[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.zeros(len(closes))
    avg_loss = np.full(len(closes), 1e-6)
    avg_gain[14] = np.mean(gains[1:15])
    avg_loss[14] = max(np.mean(losses[1:15]), 1e-6)
    for i in range(15, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * 13 + gains[i]) / 14
        avg_loss[i] = (avg_loss[i - 1] * 13 + losses[i]) / 14
    rsi = np.full(len(closes), np.nan)
    for i in range(14, len(closes)):
        rsi[i] = 100 - 100 / (1 + avg_gain[i] / avg_loss[i])

    # 均线排列
    c = closes[-1]
    if c > ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]:
        arrangement = "多头排列"
    elif c < ma5[-1] < ma10[-1] < ma20[-1] < ma60[-1]:
        arrangement = "空头排列"
    else:
        arrangement = "缠绕/交叉"

    # 量比
    vol_ma5 = _sma(volumes, 5)
    vol_ratio = volumes[-1] / vol_ma5[-1] if not np.isnan(vol_ma5[-1]) else 1.0

    return {
        "dates": dates,
        "closes": closes,
        "ma": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60},
        "macd": {"dif": dif, "dea": dea, "bar": macd_bar, "signal": macd_signal},
        "rsi": rsi,
        "rsi_status": "超买" if rsi[-1] > 70 else "超卖" if rsi[-1] < 30 else "中性",
        "arrangement": arrangement,
        "key_levels": {
            "ma5": round(ma5[-1], 2), "ma10": round(ma10[-1], 2),
            "ma20": round(ma20[-1], 2), "ma60": round(ma60[-1], 2),
            "high_20": round(float(np.max(highs[-20:])), 2),
            "low_20": round(float(np.min(lows[-20:])), 2),
            "high_60": round(float(np.max(highs[-60:])), 2),
            "low_60": round(float(np.min(lows[-60:])), 2),
        },
        "volume_ratio_5": round(float(vol_ratio), 2),
    }


def find_gaps(klines: list, lookback: int = 60) -> list:
    """识别近 N 日的缺口（向上/向下）"""
    gaps = []
    start = max(0, len(klines) - lookback)
    for i in range(start + 1, len(klines)):
        prev_h = float(klines[i - 1]["high"])
        prev_l = float(klines[i - 1]["low"])
        curr_h = float(klines[i]["high"])
        curr_l = float(klines[i]["low"])

        if curr_l > prev_h:
            later_lows = [float(k["low"]) for k in klines[i + 1 :]]
            filled = any(l <= prev_h for l in later_lows)
            gaps.append({
                "date": klines[i]["day"], "type": "向上缺口",
                "size": round(curr_l - prev_h, 2),
                "filled": filled, "lower": prev_h, "upper": curr_l,
            })
        elif curr_h < prev_l:
            later_highs = [float(k["high"]) for k in klines[i + 1 :]]
            filled = any(h >= prev_l for h in later_highs)
            gaps.append({
                "date": klines[i]["day"], "type": "向下缺口",
                "size": round(prev_l - curr_h, 2),
                "filled": filled, "lower": curr_h, "upper": prev_l,
            })
    return gaps
