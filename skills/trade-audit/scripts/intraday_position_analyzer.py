#!/usr/bin/env python3
"""
15分钟K线买卖位置分析器 (Intraday Trade Position Analyzer)

基于15分钟K线精确定位买卖时点，分析入场/出场的分时位置、BOLL位置、
趋势状态、成交量异动等8个维度，写入trade_audit。

算法:
  - 多级匹配: exact(价格在K线范围内) → boundary(<1%误差) → approximate(<15%容差,复权偏差) → failed
  - 15分BOLL: 用前20根15分K线计算MA/BOLL
  - 分时趋势: 买入前5根K线方向判定
  - 成交量比: 当前K线量/前5根均量

数据源: TDX Client 15分K线 (通过NAS Docker API, 数据完整)
覆盖率: 87% (2025-02-19之后的939/1079笔)

依赖: pymysql, pyyaml, numpy
"""

import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRADE_AUDIT_DIR = os.path.dirname(_SCRIPT_DIR)
_CONFIG_PATH = os.path.join(_TRADE_AUDIT_DIR, "config", "review_config.yaml")
sys.path.insert(0, _SCRIPT_DIR)

# ── MySQL ──

def _load_mysql_config() -> dict:
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    mysql_cfg = cfg.get("mysql", {})
    env_pwd = os.environ.get("MYSQL_PWD", "")
    return {
        "host": mysql_cfg.get("host", "192.168.123.104"),
        "port": mysql_cfg.get("port", 3306),
        "user": mysql_cfg.get("user", "root"),
        "password": env_pwd or mysql_cfg.get("password", ""),
        "database": mysql_cfg.get("database", "hermes"),
        "charset": "utf8mb4",
    }


@contextmanager
def get_conn(config: dict = None):
    import pymysql
    cfg = config or _load_mysql_config()
    conn = pymysql.connect(**cfg)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── 15分钟K线获取 (带MySQL缓存) ──

def _load_kline_from_db(code: str, conn=None) -> List[Dict]:
    """从 kline_15min 表加载缓存，返回格式同 fetch_15min_kline"""
    import pymysql
    own_conn = conn is None
    if own_conn:
        conn = pymysql.connect(**_load_mysql_config())
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT kline_date, open, high, low, close_price, volume
            FROM kline_15min
            WHERE stock_code = %s
            ORDER BY kline_date
        """, (code,))
        rows = cur.fetchall()
    finally:
        if own_conn:
            conn.close()

    if not rows:
        return []

    result = []
    for r in rows:
        dt = r[0]
        if hasattr(dt, "strftime"):
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            date_str = str(dt)
        result.append({
            "date": date_str,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        })
    return result


def _save_kline_to_db(code: str, klines: List[Dict], conn=None) -> int:
    """将15分K线批量写入 kline_15min 表，返回新插入行数"""
    import pymysql
    if not klines:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = pymysql.connect(**_load_mysql_config())

    try:
        cur = conn.cursor()
        # 用 INSERT IGNORE 跳过已存在记录(uk_stock_date)
        sql = """
            INSERT IGNORE INTO kline_15min
                (stock_code, kline_date, open, high, low, close_price, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        batch = []
        for k in klines:
            dt_str = k["date"]
            # 转为 datetime
            if isinstance(dt_str, str):
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
            else:
                dt = dt_str
            batch.append((
                code, dt,
                round(k["open"], 3), round(k["high"], 3),
                round(k["low"], 3), round(k["close"], 3),
                int(k["volume"]),
            ))

        inserted = 0
        if batch:
            inserted = cur.executemany(sql, batch)
        conn.commit()
        return inserted
    finally:
        if own_conn:
            conn.close()


def _fetch_kline_from_tdx(code: str) -> List[Dict]:
    """
    通过TDX Client获取15分钟K线数据
    返回: [{date, day, open, high, low, close, volume}, ...] 按时间正序
    """
sys.path.insert(0, os.path.expanduser('~/.hermes/local'))  # 私有工具库
    from tdx_client import TDXClient
    tdx = TDXClient()
    tdx_code = TDXClient.code_to_tdx(code)

    try:
        raw = tdx.kline_15m(tdx_code)
    except Exception as e:
        print(f"  [WARN] {code} TDX 15分K线获取失败: {e}")
        return []

    if not raw:
        return []

    result = []
    for item in raw:
        t = item.get("time", "")
        # TDXClient返回time字段, 取前10位作为day字段
        day = t[:10] if len(t) >= 10 else ""
        try:
            result.append({
                "date": t,
                "day": day,
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": float(item.get("volume", 0)),
            })
        except (ValueError, TypeError):
            continue
    return result


# DEPRECATED: 保留旧函数签名以防外部调用, 内部已不使用
def _fetch_kline_from_pytdx(code: str, start_date: str, end_date: str) -> List[Dict]:
    """[DEPRECATED] 已由TDXClient替代, 返回空列表"""
    return []


def fetch_15min_kline(code: str, force_refresh: bool = False) -> List[Dict]:
    """
    获取15分钟K线数据(带MySQL缓存)

    流程:
      1. 查 kline_15min 表 → 有数据且非force → 直接返回
      2. 调TDX Client API → 写入 kline_15min → 返回

    Args:
        code: 股票代码(6位纯数字)
        force_refresh: 强制从API重新拉取并覆盖缓存
    """
    # Step 1: 查缓存
    if not force_refresh:
        cached = _load_kline_from_db(code)
        if cached:
            return cached

    # Step 2: 调TDX Client
    klines = _fetch_kline_from_tdx(code)

    if not klines:
        # API失败时，再试一次缓存(可能之前有旧数据)
        if not force_refresh:
            return _load_kline_from_db(code)
        return []

    # Step 3: 写入缓存
    inserted = _save_kline_to_db(code, klines)
    if inserted:
        print(f"  [{code}] 缓存写入{inserted}条(TDX)", end=" ", flush=True)

    return klines


# DEPRECATED: _merge_klines 不再需要(TDX Client数据源单一, 无需合并)


# ── 15分钟BOLL计算 ──

def calc_boll_15m(klines: List[Dict], index: int, period: int = 20) -> Optional[float]:
    """
    计算第index根K线处的15分BOLL %B
    %B = (close - lower) / (upper - lower)
    需要至少 period 根前置K线
    """
    if index < period:
        return None
    closes = [klines[i]["close"] for i in range(index - period, index + 1)]
    ma = np.mean(closes)
    std = np.std(closes, ddof=0)
    if std < 1e-6:
        return 0.5  # 标准差为0时%B=0.5
    upper = ma + 2 * std
    lower = ma - 2 * std
    price = klines[index]["close"]
    pb = (price - lower) / (upper - lower) if (upper - lower) > 1e-6 else 0.5
    return round(pb * 100, 2)  # 返回0-100的%B


# ── 时间段分类 ──

# 15分K线时间段映射 (A股每天16根15分K线)
# 0: 09:30, 1: 09:45, 2: 10:00, 3: 10:15, 4: 10:30, 5: 10:45,
# 6: 11:00, 7: 11:15, 8: 11:30, 9: 13:00, 10: 13:15, 11: 13:30,
# 12: 13:45, 13: 14:00, 14: 14:15, 15: 14:30, (16: 14:45, 17: 15:00)

_TIME_SLOT_MAP = {
    (0, 1, 2): "morning_early",      # 9:30-10:00
    (3, 4, 5): "morning_mid",         # 10:00-10:45
    (6, 7, 8): "morning_late",        # 10:45-11:30
    (9, 10, 11): "afternoon_early",   # 13:00-13:30
    (12, 13, 14): "afternoon_mid",    # 13:30-14:15
    (15, 16, 17): "afternoon_late",   # 14:15-15:00
}

# 反向映射
_SLOT_LOOKUP = {}
for indices, slot in _TIME_SLOT_MAP.items():
    for i in indices:
        _SLOT_LOOKUP[i] = slot


def get_time_slot_from_kline(kline: Dict) -> str:
    """从15分K线的时间戳提取时间段"""
    dt_str = kline.get("date", "")
    if not dt_str:
        return "unknown"
    try:
        parts = dt_str.split(" ")
        if len(parts) < 2:
            return "unknown"
        time_part = parts[1][:5]  # HH:MM
        hh, mm = int(time_part[:2]), int(time_part[3:5])
        # 映射到索引
        # 上午: 9:30=0, 9:45=1, 10:00=2, 10:15=3, 10:30=4, 10:45=5,
        #       11:00=6, 11:15=7, 11:30=8
        # 下午: 13:00=9, 13:15=10, 13:30=11, 13:45=12, 14:00=13,
        #       14:15=14, 14:30=15, 14:45=16, 15:00=17
        if hh < 12:  # 上午
            total_min = (hh - 9) * 60 + mm - 30  # 9:30=0
            idx = total_min // 15
        else:  # 下午
            total_min = (hh - 13) * 60 + mm
            idx = 9 + total_min // 15
        return _SLOT_LOOKUP.get(idx, "unknown")
    except (ValueError, IndexError):
        return "unknown"


# ── 多级买卖点匹配 ──

def locate_trade_position(
    klines: List[Dict],
    trade_price: float,
    trade_date: str,
    is_buy: bool = True
) -> Dict:
    """
    在15分K线中定位交易点（多级匹配策略）

    优先级:
      1. exact: 价格在 [low, high] 范围内 → 选成交量最大的
      2. boundary: 价格接近边界(<1%误差) → 选最近的
      3. failed: 无法匹配

    返回: {
        kline_index, time_slot, boll_15m, trend_15m,
        vol_ratio, price_position, match_method
    }
    """
    # 筛选交易日的K线
    day_klines = []
    for i, k in enumerate(klines):
        if k["date"].startswith(trade_date):
            day_klines.append((i, k))

    if not day_klines:
        return {"match_method": "failed", "reason": "no_kline_for_date"}

    # 策略1: exact — 价格在K线范围内
    exact_matches = []
    for i, k in day_klines:
        if k["low"] <= trade_price <= k["high"]:
            exact_matches.append((i, k))

    if exact_matches:
        # 选成交量最大的
        best_idx, best_k = max(exact_matches, key=lambda x: x[1]["volume"])
        return _build_result(klines, best_idx, best_k, trade_price, "exact")

    # 策略2: boundary — 价格接近边界(<1%误差)
    best_boundary = None
    best_boundary_dist = float("inf")
    for i, k in day_klines:
        for boundary_price, label in [(k["low"], "low"), (k["high"], "high")]:
            if boundary_price > 0:
                dist_pct = abs(trade_price - boundary_price) / boundary_price
                if dist_pct < 0.01 and dist_pct < best_boundary_dist:
                    best_boundary_dist = dist_pct
                    best_boundary = (i, k, label)
    if best_boundary is not None:
        i, k, label = best_boundary
        return _build_result(klines, i, k, trade_price, "boundary")

    # 策略3: approximate — 价格最接近的K线(5%容差)
    # 复权价与不复权K线之间可能有5-10%偏差，取最接近的一根
    best_approx = None
    best_approx_dist = float("inf")
    for i, k in day_klines:
        # 计算trade_price到K线范围的距离
        if trade_price < k["low"]:
            dist_pct = (k["low"] - trade_price) / k["low"]
        elif trade_price > k["high"]:
            dist_pct = (trade_price - k["high"]) / k["high"]
        else:
            dist_pct = 0  # 已在范围内(exact应已匹配)
        if dist_pct < best_approx_dist:
            best_approx_dist = dist_pct
            best_approx = (i, k)

    if best_approx is not None and best_approx_dist < 0.15:
        i, k = best_approx
        return _build_result(klines, i, k, trade_price, "approximate")

    # 策略4: failed
    # 尝试检查是否涨跌停(全天只有1个价)
    day_prices = set()
    for _, k in day_klines:
        day_prices.add(round(k["open"], 2))
        day_prices.add(round(k["close"], 2))
    if len(day_prices) <= 2:
        return {"match_method": "failed", "reason": "limit_price"}

    return {"match_method": "failed", "reason": "price_out_of_range"}


def _build_result(
    klines: List[Dict],
    kline_index: int,
    kline: Dict,
    trade_price: float,
    match_method: str
) -> Dict:
    """构建匹配结果，计算各维度指标"""
    # 时间段
    time_slot = get_time_slot_from_kline(kline)

    # 15分BOLL
    boll_15m = calc_boll_15m(klines, kline_index)

    # 分时趋势: 前5根K线方向
    trend_15m = _calc_trend(klines, kline_index)

    # 成交量比
    vol_ratio = _calc_vol_ratio(klines, kline_index)

    # 价格在K线中的位置 (0=最低, 1=最高)
    kline_range = kline["high"] - kline["low"]
    if kline_range > 1e-6:
        price_position = (trade_price - kline["low"]) / kline_range
    else:
        price_position = 0.5

    return {
        "kline_index": kline_index,
        "time_slot": time_slot,
        "boll_15m": boll_15m,
        "trend_15m": trend_15m,
        "vol_ratio": round(vol_ratio, 2),
        "price_position": round(price_position, 4),
        "match_method": match_method,
    }


def _calc_trend(klines: List[Dict], index: int, lookback: int = 5) -> str:
    """计算前lookback根K线的趋势方向"""
    if index < lookback:
        return "unknown"
    closes = [klines[index - lookback + i]["close"] for i in range(lookback)]
    ups = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    downs = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])

    if ups >= 4:
        return "continuous_up"
    elif downs >= 4:
        return "continuous_down"
    elif ups >= 3:
        return "mostly_up"
    elif downs >= 3:
        return "mostly_down"
    else:
        return "sideways"


def _calc_vol_ratio(klines: List[ Dict], index: int, lookback: int = 5) -> float:
    """计算成交量比(当前/前N根均量)"""
    if index < lookback:
        return 1.0
    prev_vols = [klines[index - lookback + i]["volume"] for i in range(lookback)]
    avg_vol = np.mean(prev_vols) if prev_vols else 1
    if avg_vol < 1:
        return 1.0
    return klines[index]["volume"] / avg_vol


# ── 买入后1小时走势 ──

def analyze_first_hour(klines: List[Dict], buy_index: int) -> str:
    """
    买入后1小时(4根15分K线)走势类型
    continuous_up / continuous_down / v_shape / sideways / insufficient_data
    """
    if buy_index + 4 >= len(klines):
        return "insufficient_data"

    next_4 = klines[buy_index + 1: buy_index + 5]
    # 检查是否同一天
    buy_date_prefix = klines[buy_index]["date"][:10]
    same_day = all(k["date"].startswith(buy_date_prefix) for k in next_4)
    if not same_day:
        # 只取同一天的K线
        next_4 = [k for k in next_4 if k["date"].startswith(buy_date_prefix)]

    if len(next_4) < 2:
        return "insufficient_data"

    closes = [k["close"] for k in next_4]
    first_close = closes[0]
    last_close = closes[-1]

    # 连续上涨
    if all(closes[i] > closes[i - 1] for i in range(1, len(closes))):
        return "continuous_up"
    # 连续下跌
    if all(closes[i] < closes[i - 1] for i in range(1, len(closes))):
        return "continuous_down"
    # V型反转: 先跌后涨，终点>起点*1.01
    mid_idx = len(closes) // 2
    if (last_close > first_close * 1.005 and
            all(closes[i] < closes[i - 1] for i in range(1, mid_idx + 1)) and
            all(closes[i] > closes[i - 1] for i in range(mid_idx + 1, len(closes)))):
        return "v_shape"
    # 倒V: 先涨后跌
    if (last_close < first_close * 0.995 and
            all(closes[i] > closes[i - 1] for i in range(1, mid_idx + 1)) and
            all(closes[i] < closes[i - 1] for i in range(mid_idx + 1, len(closes)))):
        return "inverted_v"

    return "sideways"


# ── 批量处理 ──

UPDATE_COLUMNS = [
    "entry_time_slot", "entry_boll_15m", "entry_trend_15m",
    "entry_vol_ratio_15m", "entry_price_position", "entry_match_method",
    "exit_time_slot", "exit_boll_15m", "exit_trend_15m",
    "exit_vol_ratio_15m", "exit_price_position", "exit_match_method",
    "first_hour_trend", "buy_sell_symmetry",
]


def batch_analyze(
    force: bool = False,
    min_date: str = "2025-02-19",
    dry_run: bool = False,
    force_refresh: bool = False,
) -> Dict:
    """
    批量分析15分K线买卖位置

    Args:
        force: 是否强制重新分析(覆盖已有数据)
        min_date: 最早可分析日期(15分K线数据覆盖范围)
        dry_run: 只统计不写入
        force_refresh: 强制从API重新拉取K线(忽略DB缓存)
    """
    import pymysql

    stats = {"total": 0, "analyzed": 0, "skipped": 0, "failed": 0, "updated": 0, "stocks": 0}

    # 加载可分析的交易
    with get_conn() as conn:
        cur = conn.cursor(pymysql.cursors.DictCursor)

        if force:
            where = f"WHERE sell_date IS NOT NULL AND buy_date >= '{min_date}'"
        else:
            # 跳过已有entry_match_method的交易
            where = (
                f"WHERE sell_date IS NOT NULL AND buy_date >= '{min_date}'"
                f" AND (entry_match_method IS NULL OR entry_match_method = '')"
            )

        cur.execute(f"""
            SELECT id, stock_code, buy_date, buy_price, sell_date, sell_price
            FROM trade_audit {where}
            ORDER BY stock_code, buy_date
        """)
        trades = cur.fetchall()

    stats["total"] = len(trades)
    print(f"[15分分析] 待分析: {stats['total']}笔 (min_date={min_date})")

    if not trades:
        return stats

    # 按股票分组，批量拉取K线
    by_stock: Dict[str, List[Dict]] = {}
    for t in trades:
        by_stock.setdefault(t["stock_code"], []).append(t)

    stats["stocks"] = len(by_stock)

    for stock_code, stock_trades in by_stock.items():
        print(f"  [{stock_code}] 拉取15分K线...", end=" ", flush=True)
        klines = fetch_15min_kline(stock_code, force_refresh=force_refresh)
        print(f"{len(klines)}条", flush=True)

        if not klines:
            stats["failed"] += len(stock_trades)
            continue

        # 构建日期→K线索引
        kline_by_date: Dict[str, List[Tuple[int, Dict]]] = {}
        for i, k in enumerate(klines):
            day = k["date"][:10]
            kline_by_date.setdefault(day, []).append((i, k))

        for t in stock_trades:
            buy_date_str = str(t["buy_date"])
            sell_date_str = str(t["sell_date"])
            buy_price = float(t["buy_price"])
            sell_price = float(t["sell_price"])

            # 买入分析
            entry_result = locate_trade_position(klines, buy_price, buy_date_str, is_buy=True)

            # 卖出分析
            exit_result = locate_trade_position(klines, sell_price, sell_date_str, is_buy=False)

            # 买入后1小时走势
            first_hour = "insufficient_data"
            if entry_result.get("match_method") != "failed":
                first_hour = analyze_first_hour(klines, entry_result.get("kline_index", -1))

            # 买卖对称性
            symmetry = None
            if (entry_result.get("boll_15m") is not None and
                    exit_result.get("boll_15m") is not None):
                symmetry = round(entry_result["boll_15m"] - exit_result["boll_15m"], 2)

            # 合并结果（key映射：匹配结果key → 数据库列名）
            key_to_col = {
                "time_slot":      ("entry_time_slot",      "exit_time_slot"),
                "boll_15m":       ("entry_boll_15m",       "exit_boll_15m"),
                "trend_15m":      ("entry_trend_15m",      "exit_trend_15m"),
                "vol_ratio":      ("entry_vol_ratio_15m",  "exit_vol_ratio_15m"),
                "price_position": ("entry_price_position", "exit_price_position"),
                "match_method":   ("entry_match_method",   "exit_match_method"),
            }
            row = {}
            for key, (entry_col, exit_col) in key_to_col.items():
                row[entry_col] = entry_result.get(key)
                row[exit_col] = exit_result.get(key)
            row["first_hour_trend"] = first_hour
            row["buy_sell_symmetry"] = symmetry

            # 失败匹配跳过
            if (entry_result.get("match_method") == "failed" and
                    exit_result.get("match_method") == "failed"):
                stats["failed"] += 1
                continue

            stats["analyzed"] += 1

            if dry_run:
                stats["skipped"] += 1
                continue

            # 写入MySQL
            with get_conn() as conn:
                sets = []
                values = []
                for col in UPDATE_COLUMNS:
                    val = row.get(col)
                    if val is not None:
                        # numpy类型转原生Python
                        if hasattr(val, 'item'):
                            val = val.item()
                        sets.append(f"{col} = %s")
                        values.append(val)
                if sets:
                    values.append(t["id"])
                    sql = f"UPDATE trade_audit SET {', '.join(sets)} WHERE id = %s"
                    cur = conn.cursor()
                    cur.execute(sql, values)
                    conn.commit()
                    stats["updated"] += 1

        # 礼貌延迟，避免API频率过高
        time.sleep(0.3)

    print(f"\n[15分分析] 完成: 分析={stats['analyzed']}, 更新={stats['updated']}, "
          f"失败={stats['failed']}, 跳过={stats['skipped']}")
    return stats


# ── 交叉分析 ──

def cross_analyze_15m() -> str:
    """生成15分钟级别交叉分析报告"""
    import pymysql

    with get_conn() as conn:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT id, stock_code, buy_date, buy_price, sell_date, sell_price,
                   realized_pnl, pnl_rate, hold_days, stk_boll_pctb, stk_boll_zone,
                   sell_verdict, is_impulsive,
                   entry_time_slot, entry_boll_15m, entry_trend_15m,
                   entry_vol_ratio_15m, entry_price_position, entry_match_method,
                   exit_time_slot, exit_boll_15m, exit_trend_15m,
                   exit_vol_ratio_15m, exit_price_position, exit_match_method,
                   first_hour_trend, buy_sell_symmetry
            FROM trade_audit
            WHERE entry_match_method IS NOT NULL AND entry_match_method != 'failed'
            ORDER BY sell_date
        """)
        trades = cur.fetchall()

    if not trades:
        return "无15分K线分析数据"

    n = len(trades)
    wins = sum(1 for t in trades if float(t["realized_pnl"] or 0) > 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"""---
title: 15分钟K线买卖位置分析
date: {now}
tags: [复盘, 15分钟, 买卖位置, BOLL-15m]
---

# 15分钟K线买卖位置分析

> 生成时间: {now} | 有效匹配: {n}笔 | 胜率: {wins/n*100:.1f}%

"""]

    # ── 分析1: 入场时间 vs 胜率 ──
    lines.append("## 一、入场时间段 × 胜率\n")
    slot_order = ["morning_early", "morning_mid", "morning_late",
                  "afternoon_early", "afternoon_mid", "afternoon_late"]
    slot_labels = {
        "morning_early": "早盘(9:30-10:00)",
        "morning_mid": "上午中段(10:00-10:45)",
        "morning_late": "午前(10:45-11:30)",
        "afternoon_early": "午后开盘(13:00-13:30)",
        "afternoon_mid": "下午中段(13:30-14:15)",
        "afternoon_late": "尾盘(14:15-15:00)",
    }

    # Wilson CI 辅助函数（本地实现，避免跨模块条件导入）
    def _wilson(wins, total, z=1.96):
        if total == 0:
            return 0.0, 0.0
        p = wins / total
        d = 1 + z * z / total
        c = (p + z * z / (2 * total)) / d
        s = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / d
        return max(0.0, (c - s) * 100), min(100.0, (c + s) * 100)

    lines.append("| 时间段 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 | 冲动率 | 放量比>2占比 |")
    lines.append("|--------|-----:|:---------------|--------:|-------:|:-----------|")

    for slot in slot_order:
        subset = [t for t in trades if t["entry_time_slot"] == slot]
        if not subset:
            continue
        s_n = len(subset)
        s_wins = sum(1 for t in subset if float(t["realized_pnl"] or 0) > 0)
        s_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in subset])
        s_imp = sum(1 for t in subset if t.get("is_impulsive")) / s_n * 100
        s_vol2 = sum(1 for t in subset if _sf(t["entry_vol_ratio_15m"]) > 2) / s_n * 100
        lo, hi = _wilson(s_wins, s_n)
        label = slot_labels.get(slot, slot)
        lines.append(
            f"| **{label}** | {s_n} | {s_wins}/{s_n} [{lo:.0f}-{hi:.0f}%] | {s_avg_pnl:+,.0f} | {s_imp:.0f}% | {s_vol2:.0f}% |"
        )

    # ── 分析2: 日线BOLL × 15分BOLL 双层矩阵 ──
    lines.append("\n## 二、日线BOLL × 15分BOLL 双层矩阵\n")

    # 日线BOLL分3区
    def boll_zone(daily_boll):
        v = _sf(daily_boll)
        if v <= 0: return "缺失"
        if v <= 20: return "下轨区(≤20)"
        if v <= 80: return "中轨区(20-80)"
        return "上轨区(>80)"

    def boll_15m_zone(v):
        v = _sf(v)
        if v <= 0: return "缺失"
        if v <= 20: return "下轨(<20)"
        if v <= 80: return "中轨(20-80)"
        return "上轨(>80)"

    day_zones = ["下轨区(≤20)", "中轨区(20-80)", "上轨区(>80)"]
    m15_zones = ["下轨(<20)", "中轨(20-80)", "上轨(>80)"]

    lines.append("| 日线\\15分 | " + " | ".join(m15_zones) + " |")
    lines.append("|----------|" + "|".join("---:" for _ in m15_zones) + "|")

    for dz in day_zones:
        cells = []
        for mz in m15_zones:
            subset = [t for t in trades
                      if boll_zone(t.get("stk_boll_pctb")) == dz
                      and boll_15m_zone(t.get("entry_boll_15m")) == mz]
            if not subset:
                cells.append("—")
                continue
            s_n = len(subset)
            s_wins = sum(1 for t in subset if float(t["realized_pnl"] or 0) > 0)
            s_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in subset])
            lo, hi = _wilson(s_wins, s_n)
            cells.append(f"{s_n}笔 [{lo:.0f}-{hi:.0f}%] {s_avg_pnl:+,.0f}")
        lines.append(f"| **{dz}** | " + " | ".join(cells) + " |")

    # ── 分析3: 买入后1小时走势 × 最终盈亏 ──
    lines.append("\n## 三、买入后1小时走势 × 最终盈亏\n")
    trends = ["continuous_up", "mostly_up", "sideways", "mostly_down", "continuous_down", "v_shape", "inverted_v"]
    trend_labels = {
        "continuous_up": "连续上涨", "mostly_up": "偏涨", "sideways": "震荡",
        "mostly_down": "偏跌", "continuous_down": "连续下跌", "v_shape": "V型反转",
        "inverted_v": "倒V", "insufficient_data": "数据不足",
    }

    lines.append("| 首小时走势 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 | 平均持仓天 |")
    lines.append("|-----------|-----:|:---------------|--------:|----------:|")

    for trend in trends:
        subset = [t for t in trades if t.get("first_hour_trend") == trend]
        if not subset:
            continue
        s_n = len(subset)
        s_wins = sum(1 for t in subset if float(t["realized_pnl"] or 0) > 0)
        s_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in subset])
        s_avg_hold = np.mean([float(t.get("hold_days") or 0) for t in subset])
        lo, hi = _wilson(s_wins, s_n)
        label = trend_labels.get(trend, trend)
        lines.append(f"| **{label}** | {s_n} | {s_wins}/{s_n} [{lo:.0f}-{hi:.0f}%] | {s_avg_pnl:+,.0f} | {s_avg_hold:.1f} |")

    # ── 分析4: 买卖对称性 ──
    lines.append("\n## 四、买卖BOLL对称性\n")

    sym_data = [t for t in trades if t.get("buy_sell_symmetry") is not None]
    if sym_data:
        # symmetry = entry_boll - exit_boll
        # 正值 = 入场BOLL高、出场BOLL低 = 高买低卖(BOLL意义)
        # 负值 = 入场BOLL低、出场BOLL高 = 低买高卖(BOLL意义)
        pos_sym = [t for t in sym_data if _sf(t["buy_sell_symmetry"]) > 0]
        neg_sym = [t for t in sym_data if _sf(t["buy_sell_symmetry"]) <= 0]

        for label, group in [("BOLL高买低卖(sym>0)", pos_sym), ("BOLL低买高卖(sym≤0)", neg_sym)]:
            if not group:
                continue
            g_n = len(group)
            g_wins = sum(1 for t in group if float(t["realized_pnl"] or 0) > 0)
            g_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in group])
            lo, hi = _wilson(g_wins, g_n)
            lines.append(f"- **{label}**: {g_n}笔, 胜率{g_wins}/{g_n} [{lo:.0f}-{hi:.0f}%], 笔均{g_avg_pnl:+,.0f}")

    # ── 入场趋势×胜率 ──
    lines.append("\n## 五、入场前趋势状态 × 胜率\n")
    entry_trends = ["continuous_up", "mostly_up", "sideways", "mostly_down", "continuous_down"]
    entry_trend_labels = {
        "continuous_up": "追涨(连续上涨)", "mostly_up": "偏涨入场", "sideways": "震荡入场",
        "mostly_down": "偏跌抄底", "continuous_down": "抄底(连续下跌)",
    }

    lines.append("| 入场前趋势 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 | 放量占比 |")
    lines.append("|-----------|-----:|:---------------|--------:|:-------|")

    for trend in entry_trends:
        subset = [t for t in trades if t.get("entry_trend_15m") == trend]
        if not subset:
            continue
        s_n = len(subset)
        s_wins = sum(1 for t in subset if float(t["realized_pnl"] or 0) > 0)
        s_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in subset])
        s_vol2 = sum(1 for t in subset if _sf(t["entry_vol_ratio_15m"]) > 2) / s_n * 100
        lo, hi = _wilson(s_wins, s_n)
        label = entry_trend_labels.get(trend, trend)
        lines.append(f"| **{label}** | {s_n} | {s_wins}/{s_n} [{lo:.0f}-{hi:.0f}%] | {s_avg_pnl:+,.0f} | {s_vol2:.0f}% |")

    # ── 免责 ──
    lines.append(f"""
## 六、入场价格在K线中的位置 × 胜率

> price_position: 买入价在匹配K线的[low,high]范围中的位置，0=最低，1=最高

""")

    pos_zones = [
        (0, 0.2, "买在K线低位(0-0.2)"),
        (0.2, 0.5, "买在K线中低位(0.2-0.5)"),
        (0.5, 0.8, "买在K线中高位(0.5-0.8)"),
        (0.8, 1.01, "买在K线高位(0.8-1.0)"),
    ]
    lines.append("| 价格位置 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 |")
    lines.append("|---------|-----:|:---------------|--------:|")
    for lo_v, hi_v, label in pos_zones:
        subset = [t for t in trades if lo_v <= _sf(t.get("entry_price_position")) < hi_v]
        if not subset:
            continue
        s_n = len(subset)
        s_wins = sum(1 for t in subset if float(t["realized_pnl"] or 0) > 0)
        s_avg_pnl = np.mean([float(t["realized_pnl"] or 0) for t in subset])
        lo, hi = _wilson(s_wins, s_n)
        lines.append(f"| **{label}** | {s_n} | {s_wins}/{s_n} [{lo:.0f}-{hi:.0f}%] | {s_avg_pnl:+,.0f} |")

    # ── 免责 ──
    lines.append("""
---

## 免责声明

- 本报告基于15分钟K线自动分析，买卖时间为价格匹配推算，非精确成交时间
- 匹配方法: exact(价格在K线范围内) / boundary(<1%误差) / failed(无法匹配)
- Wilson CI 为 95% 置信区间
- 数据来源: TDX Client 15分K线 + trade_audit (MySQL)
""")

    return "\n".join(lines)


def _sf(v, default=0.0) -> float:
    """Safe float"""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ── CLI ──

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="15分钟K线买卖位置分析")
    parser.add_argument("--force", action="store_true", help="强制重新分析(覆盖trade_audit已有数据)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--min-date", default="2025-02-19", help="最早可分析日期")
    parser.add_argument("--report-only", action="store_true", help="只生成报告(不跑分析)")
    parser.add_argument("--refresh-cache", action="store_true", help="强制从API重新拉取K线并更新缓存")
    args = parser.parse_args()

    if not args.report_only:
        stats = batch_analyze(
            force=args.force, min_date=args.min_date,
            dry_run=args.dry_run, force_refresh=args.refresh_cache,
        )
        print(f"\n统计: {stats}")

    report = cross_analyze_15m()

    # 保存到Obsidian
    vault_path = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"
    if not os.path.exists(vault_path):
        vault_path = os.path.expanduser("~/Documents/Obsidian Vault")

    out_dir = os.path.join(vault_path, "mystocks", "复盘", "交易路径分析")
    os.makedirs(out_dir, exist_ok=True)

    now = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(out_dir, f"15分钟买卖位置分析_{now}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[15分分析] 报告已保存: {out_path}")
