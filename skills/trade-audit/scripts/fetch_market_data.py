#!/usr/bin/env python3
"""
交易复盘数据采集脚本
从新浪API获取个股K线、实时行情、行业板块、大盘指数等数据
用于事前视角(成交时刻快照)和事后视角(T+N验证)

用法:
  python fetch_market_data.py pre  --code 000887 --date 2026-06-01 --time 10:32
  python fetch_market_data.py post --code 000887 --buy-date 2026-06-01 --days 5
  python fetch_market_data.py kline --code 000887 --period 240 --count 30
  python fetch_market_data.py sector --keyword 汽车零部件
  python fetch_market_data.py index
"""

import argparse
import json
import math
import os
import re
import sys
import yaml
from datetime import datetime, timedelta
from typing import Optional

import requests
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "review_config.yaml")

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ========== 工具函数 ==========

def load_config(path=None):
    path = path or CONFIG_PATH
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def sina_code(code: str) -> str:
    """转新浪代码格式: 000887 -> sz000887, 600172 -> sh600172"""
    code = code.strip()
    if code.startswith(("sz", "sh", "bj")):
        return code
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "3")):
        return f"sz{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ========== K线数据 ==========

# ========== K线缓存(批量审计时同股票复用) ==========

_kline_cache = {}  # (code, period) -> list[dict]
_kline_cache_max = 500  # 最多缓存500个(code,period)组合

def clear_kline_cache():
    """清空K线缓存"""
    _kline_cache.clear()

# ========== K线获取 ==========

def _fetch_kline_tencent(code: str, period: str = "240", count: int = 30) -> list:
    """
    从腾讯财经获取K线数据(fallback源, WSL下新浪被封时使用)
    period: "240"=日K, "m60"=60分K, "m30"=30分K, "m5"=5分K
    返回格式与 fetch_kline 一致: [{date, open, high, low, close, volume}, ...]
    """
    try:
        market_prefix = "sz" if code.startswith(("0", "1", "2", "3")) else "sh"
        # 腾讯API: period映射
        period_map = {"240": "day", "60": "m60", "30": "m30", "5": "m5"}
        tencent_period = period_map.get(period, "day")

        url = (
            f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={market_prefix}{code},{tencent_period},,,{count},qfq"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode("gbk")
        data = json.loads(raw)

        d = data.get("data", {})
        if isinstance(d, list) and len(d) == 0:
            return []

        stock_key = f"{market_prefix}{code}"
        if stock_key not in d:
            return []

        kdata = d[stock_key]
        # 日K用qfqday, 分钟K用qfqm60等
        if tencent_period == "day":
            kkey = "qfqday" if "qfqday" in kdata else "day"
        else:
            kkey = f"qfq{tencent_period}" if f"qfq{tencent_period}" in kdata else tencent_period

        lines = kdata.get(kkey, [])
        if not lines:
            return []

        # 腾讯格式: [date, open, close, high, low, volume]
        # 转为统一格式: {date, open, high, low, close, volume}
        result = []
        for item in lines:
            if len(item) < 6:
                continue
            result.append({
                "date": item[0],
                "open": safe_float(item[1]),
                "close": safe_float(item[2]),
                "high": safe_float(item[3]),
                "low": safe_float(item[4]),
                "volume": safe_float(item[5]),
            })
        return result

    except Exception:
        return []


def fetch_kline(code: str, period: str = "240", count: int = 30) -> list:
    """
    获取K线数据(带缓存)
    period: 240=日K, 60=60分K, 30=30分K, 5=5分K
    count: 返回条数
    优先新浪API, 失败时fallback到腾讯财经
    """
    cache_key = (code, period, count)
    if cache_key in _kline_cache:
        return _kline_cache[cache_key]

    sc = sina_code(code)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": sc, "scale": period, "ma": "no", "datalen": count}

    result = []
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    result.append({
                        "date": item.get("day", ""),
                        "open": safe_float(item.get("open")),
                        "high": safe_float(item.get("high")),
                        "low": safe_float(item.get("low")),
                        "close": safe_float(item.get("close")),
                        "volume": safe_float(item.get("volume")),
                    })
    except Exception:
        pass

    # 新浪失败时fallback到腾讯
    if not result:
        result = _fetch_kline_tencent(code, period, count)

    # 写入缓存
    if result and len(_kline_cache) < _kline_cache_max:
        _kline_cache[cache_key] = result

    return result


# ========== 实时行情 ==========

def fetch_realtime(code: str) -> dict:
    """获取实时行情快照"""
    sc = sina_code(code)
    url = f"http://hq.sinajs.cn/list={sc}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return {}
    text = resp.text
    match = re.search(r'="([^"]*)"', text)
    if not match:
        return {}
    fields = match.group(1).split(",")
    if len(fields) < 32:
        return {}
    return {
        "name": fields[0],
        "open": safe_float(fields[1]),         # 今开
        "prev_close": safe_float(fields[2]),    # 昨收
        "price": safe_float(fields[3]),         # 现价
        "high": safe_float(fields[4]),          # 最高
        "low": safe_float(fields[5]),           # 最低
        "volume": safe_float(fields[8]),        # 成交量
        "amount": safe_float(fields[9]),        # 成交额
        "date": fields[30] if len(fields) > 30 else "",
        "time": fields[31] if len(fields) > 31 else "",
        # 计算指标
        "change_pct": round((safe_float(fields[3]) - safe_float(fields[2])) / safe_float(fields[2]) * 100, 2) if safe_float(fields[2]) > 0 else 0,
        "amplitude": round((safe_float(fields[4]) - safe_float(fields[5])) / safe_float(fields[2]) * 100, 2) if safe_float(fields[2]) > 0 else 0,
    }


def fetch_realtime_batch(codes: list) -> dict:
    """批量获取实时行情"""
    sc_list = [sina_code(c) for c in codes]
    url = f"http://hq.sinajs.cn/list={','.join(sc_list)}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return {}
    results = {}
    for line in resp.text.strip().split("\n"):
        match = re.search(r'hq_str_(\w+)="([^"]*)"', line)
        if not match:
            continue
        sc = match.group(1)
        fields = match.group(2).split(",")
        if len(fields) < 32:
            continue
        code = sc[2:]  # 去掉sh/sz前缀
        results[code] = {
            "name": fields[0],
            "open": safe_float(fields[1]),
            "prev_close": safe_float(fields[2]),
            "price": safe_float(fields[3]),
            "high": safe_float(fields[4]),
            "low": safe_float(fields[5]),
            "volume": safe_float(fields[8]),
            "amount": safe_float(fields[9]),
            "date": fields[30] if len(fields) > 30 else "",
            "time": fields[31] if len(fields) > 31 else "",
            "change_pct": round((safe_float(fields[3]) - safe_float(fields[2])) / safe_float(fields[2]) * 100, 2) if safe_float(fields[2]) > 0 else 0,
        }
    return results


# ========== 技术指标计算 ==========

def calc_ma(klines: list, period: int) -> list:
    """计算移动平均线"""
    closes = [k["close"] for k in klines]
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(closes[i-period+1:i+1]) / period, 3))
    return result


def calc_atr(klines: list, period: int = 14) -> list:
    """计算ATR"""
    trs = []
    for i in range(len(klines)):
        if i == 0:
            tr = klines[i]["high"] - klines[i]["low"]
        else:
            tr = max(
                klines[i]["high"] - klines[i]["low"],
                abs(klines[i]["high"] - klines[i-1]["close"]),
                abs(klines[i]["low"] - klines[i-1]["close"]),
            )
        trs.append(tr)
    # 简单移动平均
    result = []
    for i in range(len(trs)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(trs[i-period+1:i+1]) / period, 3))
    return result


def calc_macd(klines: list, fast=12, slow=26, signal=9) -> dict:
    """计算MACD"""
    closes = [k["close"] for k in klines]
    # EMA
    def ema(data, n):
        result = [data[0]]
        k = 2 / (n + 1)
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    macd_hist = [2 * (d - e) for d, e in zip(dif, dea)]

    return {
        "dif": [round(v, 3) for v in dif],
        "dea": [round(v, 3) for v in dea],
        "hist": [round(v, 3) for v in macd_hist],
    }


def calc_rsi(klines: list, period: int = 14) -> list:
    """计算RSI"""
    closes = [k["close"] for k in klines]
    result = []
    for i in range(len(closes)):
        if i < period:
            result.append(None)
        else:
            gains, losses = [], []
            for j in range(i - period + 1, i + 1):
                diff = closes[j] - closes[j-1]
                if diff > 0:
                    gains.append(diff)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(diff))
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                result.append(100)
            else:
                rs = avg_gain / avg_loss
                result.append(round(100 - 100 / (1 + rs), 2))
    return result


def calc_boll(klines: list, period: int = 20, nbdev: float = 2.0) -> dict:
    """计算布林带"""
    closes = [k["close"] for k in klines]
    mids, ups, lows = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            mids.append(None)
            ups.append(None)
            lows.append(None)
        else:
            mid = sum(closes[i-period+1:i+1]) / period
            std = math.sqrt(sum((c - mid) ** 2 for c in closes[i-period+1:i+1]) / period)
            mids.append(round(mid, 3))
            ups.append(round(mid + nbdev * std, 3))
            lows.append(round(mid - nbdev * std, 3))
    return {"mid": mids, "upper": ups, "lower": lows}


def calc_volume_ratio(klines: list, period: int = 5) -> list:
    """计算量比 = 当日成交量 / 前N日平均成交量"""
    vols = [k["volume"] for k in klines]
    result = []
    for i in range(len(vols)):
        if i < period:
            result.append(None)
        else:
            avg = sum(vols[i-period:i]) / period
            result.append(round(vols[i] / avg, 2) if avg > 0 else 0)
    return result


# ========== 行业板块 ==========

def fetch_sectors() -> list:
    """获取新浪行业板块涨跌排名(带缓存)"""
    import time
    now = time.time()
    if _sectors_cache and (now - _sectors_cache.get("_ts", 0)) < _cache_ttl:
        return _sectors_cache.get("data", [])

    sectors = []
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            match = re.search(r'=\s*(\{.*\})', resp.text, re.DOTALL)
            if match:
                raw = match.group(1)
                for item_match in re.finditer(r'"([^"]+)":\s*"([^"]*)"', raw):
                    key = item_match.group(1)
                    val = item_match.group(2)
                    parts = val.split(",")
                    if len(parts) >= 6:
                        sectors.append({
                            "code": key,
                            "name": parts[1] if len(parts) > 1 else "",
                            "count": safe_float(parts[2]) if len(parts) > 2 else 0,
                            "avg_price": safe_float(parts[3]) if len(parts) > 3 else 0,
                            "change_pct": safe_float(parts[4]) if len(parts) > 4 else 0,
                            "change_amount": safe_float(parts[5]) if len(parts) > 5 else 0,
                        })
                sectors.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    except Exception:
        pass

    if sectors:
        _sectors_cache.clear()
        _sectors_cache["data"] = sectors
        _sectors_cache["_ts"] = now

    return sectors


def find_sector_change(keyword: str) -> Optional[dict]:
    """按关键词查找行业板块涨跌"""
    sectors = fetch_sectors()
    keyword = keyword.strip()
    for s in sectors:
        if keyword in s.get("name", ""):
            return s
    # 模糊匹配
    for s in sectors:
        for char in keyword:
            if char in s.get("name", "") and len(keyword) >= 2:
                return s
    return None


# ========== 大盘指数 ==========

INDEX_CODES = {
    "上证": "sh000001",
    "深证": "sz399001",
    "创业板": "sz399006",
    "沪深300": "sh000300",
}


# ========== 行情缓存 ==========

_indices_cache = {}     # timestamp -> dict
_sectors_cache = {}     # timestamp -> list
_snapshot_cache = {}    # (code, trade_date) -> dict
_cache_ttl = 300        # 缓存5分钟

def fetch_indices() -> dict:
    """获取大盘指数实时行情(带缓存)"""
    import time
    now = time.time()
    if _indices_cache and (now - _indices_cache.get("_ts", 0)) < _cache_ttl:
        return {k: v for k, v in _indices_cache.items() if k != "_ts"}

    # 优先新浪
    results = {}
    codes = list(INDEX_CODES.values())
    try:
        url = f"http://hq.sinajs.cn/list={','.join(codes)}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            for line in resp.text.strip().split("\n"):
                match = re.search(r'hq_str_(\w+)="([^"]*)"', line)
                if not match:
                    continue
                sc = match.group(1)
                fields = match.group(2).split(",")
                if len(fields) < 32:
                    continue
                name = None
                for n, c in INDEX_CODES.items():
                    if c == sc:
                        name = n
                        break
                if name:
                    results[name] = {
                        "code": sc,
                        "name": name,
                        "open": safe_float(fields[1]),
                        "prev_close": safe_float(fields[2]),
                        "price": safe_float(fields[3]),
                        "high": safe_float(fields[4]),
                        "low": safe_float(fields[5]),
                        "volume": safe_float(fields[8]),
                        "amount": safe_float(fields[9]),
                        "change_pct": round((safe_float(fields[3]) - safe_float(fields[2])) / safe_float(fields[2]) * 100, 2) if safe_float(fields[2]) > 0 else 0,
                    }
    except Exception:
        pass

    # 新浪失败时用腾讯行情
    if not results:
        try:
            # 腾讯行情: 上证0000001, 深成1399001, 创业板1399006
            tencent_codes = {"sh000001": "sh", "sz399001": "sz", "sz399006": "cyb"}
            qs = ",".join(tencent_codes.keys())
            url = f"http://qt.gtimg.cn/q={qs}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            text = resp.read().decode("gbk")
            for line in text.strip().split(";"):
                if "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 35:
                    continue
                raw_code = parts[2]  # e.g. 0000001
                name_map = {"0000001": "sh", "399001": "sz", "399006": "cyb"}
                idx_name = name_map.get(raw_code)
                if idx_name:
                    prev_close = safe_float(parts[4])
                    price = safe_float(parts[3])
                    results[idx_name] = {
                        "code": raw_code,
                        "name": parts[1],
                        "price": price,
                        "prev_close": prev_close,
                        "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0,
                    }
        except Exception:
            pass

    # 写缓存
    if results:
        _indices_cache.clear()
        _indices_cache.update(results)
        _indices_cache["_ts"] = now

    return results


# ========== 综合事前快照 ==========

def fetch_pre_snapshot(code: str, trade_date: str, trade_time: str = None,
                       historical: bool = False) -> dict:
    """
    获取事前视角完整快照(带缓存)
    code: 股票代码
    trade_date: 成交日期 YYYY-MM-DD
    trade_time: 成交时间 HH:MM（可选，用于盘中快照）
    historical: True=历史交易模式(跳过实时行情,从日K线取追高/抄底判定)
    """
    # 快照缓存: 历史交易同一股票同一天复用
    cache_key = (code, trade_date, historical)
    if cache_key in _snapshot_cache:
        return _snapshot_cache[cache_key]

    result = {
        "code": code,
        "trade_date": trade_date,
        "trade_time": trade_time,
        "realtime": {},
        "kline_daily": [],
        "kline_60min": [],
        "indicators": {},
        "sector": {},
        "indices": {},
        "chase_detect": {},
    }

    # 1. 实时行情(历史交易时跳过,用日K线当天数据替代)
    if not historical:
        rt = fetch_realtime(code)
        result["realtime"] = rt
    else:
        rt = {}

    # 2. 日K线(取250条保证MA60/BOLL/MACD等指标计算)
    daily = fetch_kline(code, "240", 250)
    result["kline_daily"] = daily

    # 3. 60分K线
    k60 = fetch_kline(code, "60", 48)
    result["kline_60min"] = k60

    # 4. 技术指标(基于日K)
    if daily:
        ma5 = calc_ma(daily, 5)
        ma10 = calc_ma(daily, 10)
        ma20 = calc_ma(daily, 20)
        ma60 = calc_ma(daily, 60)
        atr14 = calc_atr(daily, 14)
        macd = calc_macd(daily)
        rsi14 = calc_rsi(daily, 14)
        boll = calc_boll(daily)
        vr = calc_volume_ratio(daily, 5)

        last = len(daily) - 1
        result["indicators"] = {
            "MA5": ma5[last],
            "MA10": ma10[last],
            "MA20": ma20[last],
            "MA60": ma60[last],
            "ATR14": atr14[last],
            "MACD_DIF": macd["dif"][last],
            "MACD_DEA": macd["dea"][last],
            "MACD_HIST": macd["hist"][last],
            "RSI14": rsi14[last],
            "BOLL_upper": boll["upper"][last],
            "BOLL_mid": boll["mid"][last],
            "BOLL_lower": boll["lower"][last],
            "volume_ratio": vr[last],
        }

    # 5. 行业板块
    if rt.get("name"):
        # 从股票名称推断行业(简化版，后续可接入行业映射)
        sectors = fetch_sectors()
        result["sector_list"] = sectors[:10]  # TOP10涨幅
        result["sector_count"] = len(sectors)

    # 6. 大盘指数
    result["indices"] = fetch_indices()

    # 7. 追高/抄底检测
    config = load_config()
    chase_threshold = config.get("chase_high_threshold", 0.05)
    chase_base = config.get("chase_high_base", "open")
    bottom_threshold = config.get("bottom_fishing_threshold", -0.03)

    if rt:
        # 实时行情模式(当日交易)
        base_price = rt.get("open") if chase_base == "open" else rt.get("prev_close")
        buy_price = rt.get("price", 0)

        is_chase = buy_price >= base_price * (1 + chase_threshold) if base_price > 0 else False
        change_pct = rt.get("change_pct", 0)
        is_bottom = change_pct <= bottom_threshold * 100

        day_range = rt.get("high", 0) - rt.get("low", 0)
        day_position = (buy_price - rt.get("low", 0)) / day_range * 100 if day_range > 0 else 50

        result["chase_detect"] = {
            "is_chase_high": is_chase,
            "chase_detail": f"买入{buy_price} vs {chase_base}价{base_price}, 阈值{chase_threshold*100}%",
            "is_bottom_fishing": is_bottom,
            "bottom_detail": f"涨跌幅{change_pct}%, 阈值{bottom_threshold*100}%",
            "day_position_pct": round(day_position, 1),
        }
    elif historical and daily:
        # 历史交易模式: 从日K线找trade_date当天数据
        trade_day_k = None
        for k in daily:
            if k.get("date") == trade_date:
                trade_day_k = k
                break
        if trade_day_k:
            base_price = trade_day_k.get("open", 0) if chase_base == "open" else trade_day_k.get("prev_close", trade_day_k.get("open", 0))
            close_price = trade_day_k.get("close", 0)
            is_chase = close_price >= base_price * (1 + chase_threshold) if base_price > 0 else False
            change_pct = trade_day_k.get("change_pct", 0) or ((close_price - base_price) / base_price * 100 if base_price > 0 else 0)
            is_bottom = change_pct <= bottom_threshold * 100

            day_high = trade_day_k.get("high", 0)
            day_low = trade_day_k.get("low", 0)
            day_range = day_high - day_low
            day_position = (close_price - day_low) / day_range * 100 if day_range > 0 else 50

            result["chase_detect"] = {
                "is_chase_high": is_chase,
                "chase_detail": f"[历史] 收盘{close_price} vs {chase_base}价{base_price}, 阈值{chase_threshold*100}%",
                "is_bottom_fishing": is_bottom,
                "bottom_detail": f"[历史] 涨跌幅{change_pct:.2f}%, 阈值{bottom_threshold*100}%",
                "day_position_pct": round(day_position, 1),
            }

    # 快照缓存写入(限制缓存大小)
    if len(_snapshot_cache) < 2000:
        _snapshot_cache[cache_key] = result

    return result


# ========== 事后验证数据 ==========

def fetch_post_validation(code: str, buy_date: str, buy_price: float, stop_price: float = 0, target_price: float = 0, days: int = 10, days_list: list = None, sell_price: float = 0, sell_date: str = None) -> dict:
    """
    获取事后验证数据 (V3扩展: 支持多天档 + sell_price + sell_date)
    buy_date: 买入日期 YYYY-MM-DD
    buy_price: 买入价格
    stop_price: 止损价
    target_price: 目标价
    days: 验证天数(V2旧参数, 默认10)
    days_list: V3多档验证 [5,10,20,60]，传此参数时忽略days
    sell_price: V3卖出价(用于sell_verdict判定)
    sell_date: V3卖出日期 YYYY-MM-DD(用于从卖出日起算T+N)
    """
    # V3: 如果传了 days_list，取最大天数
    if days_list:
        max_days = max(days_list)
    else:
        max_days = days

    # 取足够的日K线(从buy_date往前取, 确保覆盖持仓期+事后验证期)
    # 持仓期可能很长(buy_date→sell_date), 事后需max_days+余量
    if sell_date and sell_date > buy_date:
        # 粗估持仓天数(自然日), 需要的K线 = 持仓 + 事后 + 余量
        from datetime import datetime
        try:
            bd = datetime.strptime(buy_date, "%Y-%m-%d")
            sd = datetime.strptime(sell_date, "%Y-%m-%d")
            hold_cal_days = (sd - bd).days
        except ValueError:
            hold_cal_days = 120
        fetch_count = min(hold_cal_days + max_days + 30, 620)
    else:
        fetch_count = max(max_days + 20, 80)
    klines = fetch_kline(code, "240", fetch_count)
    if not klines:
        return {"error": "无法获取K线数据"}

    # V3: 事后验证基准日——有sell_date时从卖出日起算T+N，否则从buy_date
    base_date = sell_date or buy_date

    # 找到基准日之后的K线(事后)
    post_klines = []
    found = False
    for k in klines:
        if k["date"] >= base_date:
            found = True
        if found and k["date"] > base_date:
            post_klines.append(k)
        if len(post_klines) >= max_days + 10:
            break

    if not post_klines:
        return {"error": f"买入日{buy_date}之后尚无足够交易日数据(需要{max_days}天, 实际{len(post_klines)}天)"}

    # ---- V2兼容: 单days模式 ----
    if not days_list:
        days_list_mode = False
        actual_days = min(days, len(post_klines))
        used_klines = post_klines[:actual_days]

        highs = [k["high"] for k in used_klines]
        lows = [k["low"] for k in used_klines]
        max_high = max(highs)
        min_low = min(lows)
        final_close = used_klines[-1]["close"]

        max_profit_pct = (max_high - buy_price) / buy_price * 100 if buy_price > 0 else 0
        max_loss_pct = (min_low - buy_price) / buy_price * 100 if buy_price > 0 else 0
        final_pct = (final_close - buy_price) / buy_price * 100 if buy_price > 0 else 0

        stop_triggered = min_low <= stop_price if stop_price > 0 else None
        target_reached = max_high >= target_price if target_price > 0 else None

        if stop_price > 0 and buy_price > stop_price:
            risk = buy_price - stop_price
            reward = max_high - buy_price
            profit_ratio = round(reward / risk, 2) if risk > 0 else 0
        else:
            config = load_config()
            atr_val = None
            atr14 = calc_atr(klines, 14)
            for v in reversed(atr14):
                if v is not None:
                    atr_val = v
                    break
            if atr_val and atr_val > 0:
                risk = 2 * atr_val
                reward = max_high - buy_price
                profit_ratio = round(reward / risk, 2)
            else:
                profit_ratio = 0

        result = {
            "code": code,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "validate_days": len(used_klines),
            "max_high": max_high,
            "min_low": min_low,
            "final_close": final_close,
            "max_profit_pct": round(max_profit_pct, 2),
            "max_loss_pct": round(max_loss_pct, 2),
            "final_pct": round(final_pct, 2),
            "stop_triggered": stop_triggered,
            "target_reached": target_reached,
            "profit_ratio": profit_ratio,
            "post_klines": used_klines,
        }
        return result

    # ---- V3多档模式 ----
    result = {
        "code": code,
        "buy_date": buy_date,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "sell_date": sell_date,
    }

    # 涨跌幅基准价: 有sell_price时用sell_price(事后), 否则用buy_price(事前)
    chg_base = sell_price if sell_price > 0 else buy_price

    for d in days_list:
        if len(post_klines) >= d:
            dklines = post_klines[:d]
            d_close = dklines[-1]["close"]
            d_high = max(k["high"] for k in dklines)
            d_low = min(k["low"] for k in dklines)
            d_chg = (d_close - chg_base) / chg_base * 100 if chg_base > 0 else 0
            result[f"post{d}"] = {
                "close": d_close,
                "chg": round(d_chg, 2),
                "high": d_high,
                "low": d_low,
                "actual_days": len(dklines),
            }
        else:
            result[f"post{d}"] = None  # 数据不足

    # T+20额外: 检查卖出后20日内是否创新高
    # 持仓期间最高价: 需要从buy_date到sell_date之间的K线
    hold_max = buy_price
    if sell_date and sell_date > buy_date:
        # 从完整K线中取持仓期(buy_date到sell_date)
        for k in klines:
            if k["date"] > buy_date and k["date"] <= sell_date:
                hold_max = max(hold_max, k["high"])

    # post_new_high: 卖出后20日内最高价 > 持仓期间最高价
    post20_data = result.get("post20")
    if post20_data and sell_price > 0:
        post_new_high = post20_data["high"] > hold_max
        result["post_new_high"] = post_new_high
    else:
        result["post_new_high"] = None

    result["hold_period_max_price"] = round(hold_max, 3)
    result["post_klines"] = post_klines[:max(days_list)]
    return result


# ========== 主函数 ==========

def main():
    parser = argparse.ArgumentParser(description="交易复盘数据采集")
    sub = parser.add_subparsers(dest="command")

    # pre: 事前快照
    p_pre = sub.add_parser("pre", help="事前视角快照")
    p_pre.add_argument("--code", required=True, help="股票代码")
    p_pre.add_argument("--date", required=True, help="成交日期 YYYY-MM-DD")
    p_pre.add_argument("--time", default=None, help="成交时间 HH:MM")

    # post: 事后验证
    p_post = sub.add_parser("post", help="事后验证数据")
    p_post.add_argument("--code", required=True, help="股票代码")
    p_post.add_argument("--buy-date", required=True, help="买入日期")
    p_post.add_argument("--buy-price", type=float, required=True, help="买入价格")
    p_post.add_argument("--stop-price", type=float, default=0, help="止损价")
    p_post.add_argument("--target-price", type=float, default=0, help="目标价")
    p_post.add_argument("--days", type=int, default=10, help="验证天数")

    # kline: K线数据
    p_kline = sub.add_parser("kline", help="K线数据")
    p_kline.add_argument("--code", required=True, help="股票代码")
    p_kline.add_argument("--period", default="240", help="周期: 240/60/30/5")
    p_kline.add_argument("--count", type=int, default=30, help="条数")

    # sector: 行业板块
    p_sector = sub.add_parser("sector", help="行业板块涨跌")
    p_sector.add_argument("--keyword", default=None, help="搜索关键词")

    # index: 大盘指数
    sub.add_parser("index", help="大盘指数")

    # realtime: 实时行情
    p_rt = sub.add_parser("realtime", help="实时行情")
    p_rt.add_argument("--code", required=True, help="股票代码")

    args = parser.parse_args()

    if args.command == "pre":
        data = fetch_pre_snapshot(args.code, args.date, args.time)
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    elif args.command == "post":
        data = fetch_post_validation(args.code, args.buy_date, args.buy_price, args.stop_price, args.target_price, args.days)
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    elif args.command == "kline":
        data = fetch_kline(args.code, args.period, args.count)
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "sector":
        if args.keyword:
            data = find_sector_change(args.keyword)
            print(json.dumps(data, ensure_ascii=False, indent=2) if data else "未找到匹配板块")
        else:
            data = fetch_sectors()[:20]
            for i, s in enumerate(data, 1):
                print(f"{i:2d}. {s['name']:10s} {s['change_pct']:+.2f}%")

    elif args.command == "index":
        data = fetch_indices()
        for name, info in data.items():
            print(f"{name}: {info['price']:.2f} ({info['change_pct']:+.2f}%)")

    elif args.command == "realtime":
        data = fetch_realtime(args.code)
        print(json.dumps(data, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
