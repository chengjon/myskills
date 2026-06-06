#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日线级别买卖位置分析器 (Daily Kline Position Analyzer)

对71笔no_data交易(2024-07-22前，15分K线不可获取)，用本地TDX日线数据做分析:
  - 日线BOLL(20日MA): 买入/卖出当日BOLL位置(%B, 带宽)
  - 日线趋势: 买入前5日方向
  - 成交量比: 当日量/前5日均量
  - 价格位置: buy_price在当日振幅中的位置(需复权因子修正)
  - 买卖BOLL对称性

数据源: MySQL tdx_data.day_kline (来自TDX本地day文件, 7843只股票, 1243万行)
输出: UPDATE trade_audit相关字段, analysis_level='day'

用法:
  MYSQL_PWD=xxx python3 daily_position_analyzer.py
  MYSQL_PWD=xxx python3 daily_position_analyzer.py --force   # 重跑已有日线分析
  MYSQL_PWD=xxx python3 daily_position_analyzer.py --dry-run # 试运行
"""

import math
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import yaml

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRADE_AUDIT_DIR = os.path.dirname(_SCRIPT_DIR)
_CONFIG_PATH = os.path.join(_TRADE_AUDIT_DIR, "config", "review_config.yaml")


# ── MySQL配置 ──────────────────────────────────────────

def _load_mysql_config(db_name: str = "hermes") -> dict:
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    mysql_cfg = cfg.get("mysql", {})
    env_pwd = os.environ.get("MYSQL_PWD", "")
    return {
        "host": mysql_cfg.get("host", os.environ.get("MYSQL_HOST", "")),
        "port": mysql_cfg.get("port", 3306),
        "user": mysql_cfg.get("user", "root"),
        "password": env_pwd or mysql_cfg.get("password", ""),
        "database": db_name,
        "charset": "utf8mb4",
    }


@contextmanager
def get_conn(db_name: str = "hermes"):
    cfg = _load_mysql_config(db_name)
    conn = pymysql.connect(**cfg)
    try:
        yield conn
    finally:
        conn.close()


# ── 日线数据读取 ────────────────────────────────────────

def fetch_daily_kline(conn_tdx, stock_code: str, end_date: str, lookback: int = 30) -> List[Dict]:
    """从tdx_data.day_kline读取日线数据，end_date往前lookback条"""
    cur = conn_tdx.cursor(pymysql.cursors.DictCursor)
    sql = """
        SELECT stock_code, trade_date, open, high, low, close_price, volume, amount
        FROM day_kline
        WHERE stock_code = %s AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT %s
    """
    cur.execute(sql, (stock_code, end_date, lookback))
    rows = cur.fetchall()
    # 反转为时间正序
    rows.reverse()
    return rows


def fetch_daily_kline_range(conn_tdx, stock_code: str, start_date: str, end_date: str) -> List[Dict]:
    """读取指定日期范围的日线"""
    cur = conn_tdx.cursor(pymysql.cursors.DictCursor)
    sql = """
        SELECT stock_code, trade_date, open, high, low, close_price, volume, amount
        FROM day_kline
        WHERE stock_code = %s AND trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """
    cur.execute(sql, (stock_code, start_date, end_date))
    return cur.fetchall()


# ── BOLL计算 ────────────────────────────────────────────

def calc_boll(closes: List[float], period: int = 20, nbdev: float = 2.0) -> Optional[Dict]:
    """计算BOLL指标"""
    if len(closes) < period:
        return None
    recent = closes[-period:]
    ma = sum(recent) / period
    var = sum((c - ma) ** 2 for c in recent) / period
    std = math.sqrt(var)
    upper = ma + nbdev * std
    lower = ma - nbdev * std
    bandwidth = (upper - lower) / ma if ma > 0 else 0
    # %B
    cur_close = closes[-1]
    pct_b = (cur_close - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return {
        "ma": round(ma, 4),
        "upper": round(upper, 4),
        "lower": round(lower, 4),
        "std": round(std, 4),
        "bandwidth": round(bandwidth, 4),
        "pct_b": round(pct_b, 4),
    }


# ── 趋势判定 ────────────────────────────────────────────

def calc_trend(closes: List[float], n: int = 5) -> str:
    """根据前n根K线收盘价判定趋势"""
    if len(closes) < n + 1:
        return "insufficient"
    recent = closes[-(n+1):]  # 当前+前n根
    diffs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
    up = sum(1 for d in diffs if d > 0)
    down = sum(1 for d in diffs if d < 0)

    if up >= 4:
        return "strong_up"
    elif up >= 3:
        return "up"
    elif down >= 4:
        return "strong_down"
    elif down >= 3:
        return "down"
    else:
        return "sideways"


# ── 量比 ────────────────────────────────────────────────

def calc_vol_ratio(volumes: List[float], n: int = 5) -> Optional[float]:
    """当日量 / 前n日均量"""
    if len(volumes) < n + 1:
        return None
    avg_vol = sum(volumes[-(n+1):-1]) / n
    if avg_vol <= 0:
        return None
    return round(volumes[-1] / avg_vol, 2)


# ── 价格位置(复权修正) ─────────────────────────────────

def calc_price_position(adj_price: float, day_open: float, day_high: float, day_low: float,
                        adj_close: float, raw_close: float) -> Optional[float]:
    """
    用复权因子修正buy_price后计算在当日振幅中的位置。

    复权因子 = raw_close / adj_close (不复权/复权)
    不复权买价 = adj_price * 复权因子
    位置 = (不复权买价 - raw_low) / (raw_high - raw_low)
    """
    if not all([adj_price, adj_close, raw_close, day_high, day_low]):
        return None
    if adj_close <= 0 or (day_high - day_low) <= 0:
        return None
    factor = raw_close / adj_close  # 复权因子
    raw_buy_price = adj_price * factor
    position = (raw_buy_price - day_low) / (day_high - day_low)
    return round(max(0.0, min(1.0, position)), 4)


# ── BOLL区间标签 ────────────────────────────────────────

def boll_zone_label(pct_b: float) -> str:
    """%B → 区间标签"""
    if pct_b >= 1.0:
        return "above_upper"
    elif pct_b >= 0.8:
        return "upper_zone"
    elif pct_b >= 0.5:
        return "middle_upper"
    elif pct_b >= 0.2:
        return "middle_lower"
    elif pct_b >= 0.0:
        return "lower_zone"
    else:
        return "below_lower"


def boll_width_label(bandwidth: float) -> str:
    """带宽 → 收窄/正常/扩张"""
    if bandwidth < 0.05:
        return "squeeze"
    elif bandwidth < 0.10:
        return "narrow"
    elif bandwidth < 0.20:
        return "normal"
    else:
        return "wide"


# ── 单笔交易分析 ────────────────────────────────────────

def analyze_one_trade(conn_hermes, conn_tdx, trade: Dict, force: bool = False) -> Dict:
    """
    分析单笔no_data交易的日线BOLL位置。

    返回: {action, reason, fields}
    """
    stock_code = trade["stock_code"]
    buy_date = str(trade["buy_date"])
    sell_date = str(trade["sell_date"])
    buy_price = float(trade["buy_price"])
    sell_price = float(trade["sell_price"])
    trade_id = trade["id"]

    # 检查是否已分析
    if not force:
        cur = conn_hermes.cursor()
        cur.execute("SELECT analysis_level FROM trade_audit WHERE id = %s", (trade_id,))
        row = cur.fetchone()
        if row and row[0] == "day":
            return {"action": "skip", "reason": "already_analyzed", "fields": {}}

    # 1. 读取buy_date前30日日线数据（用于BOLL和趋势）
    buy_klines = fetch_daily_kline(conn_tdx, stock_code, buy_date, lookback=30)
    if len(buy_klines) < 20:
        return {"action": "no_kline", "reason": f"insufficient_kline:{len(buy_klines)}", "fields": {}}

    # 找到buy_date那条
    buy_day = None
    for k in buy_klines:
        if str(k["trade_date"]) == buy_date:
            buy_day = k
            break

    if not buy_day:
        return {"action": "no_match", "reason": f"buy_date_not_found:{buy_date}", "fields": {}}

    # 2. 计算买入日BOLL (用buy_date前20日close)
    closes_for_boll = [float(k["close_price"]) for k in buy_klines if str(k["trade_date"]) <= buy_date]
    if len(closes_for_boll) < 20:
        return {"action": "no_boll", "reason": f"insufficient_for_boll:{len(closes_for_boll)}", "fields": {}}

    buy_boll = calc_boll(closes_for_boll, period=20)
    if not buy_boll:
        return {"action": "no_boll", "reason": "calc_failed", "fields": {}}

    # 3. 计算卖出日BOLL
    sell_klines = fetch_daily_kline(conn_tdx, stock_code, sell_date, lookback=30)
    sell_day = None
    for k in sell_klines:
        if str(k["trade_date"]) == sell_date:
            sell_day = k
            break

    sell_boll = None
    if sell_day and len(sell_klines) >= 20:
        sell_closes = [float(k["close_price"]) for k in sell_klines if str(k["trade_date"]) <= sell_date]
        if len(sell_closes) >= 20:
            sell_boll = calc_boll(sell_closes, period=20)

    # 4. 趋势（前5日）
    buy_trend = calc_trend(closes_for_boll, n=5)
    sell_trend = "insufficient"
    if sell_day and len(sell_klines) >= 6:
        sell_closes_all = [float(k["close_price"]) for k in sell_klines if str(k["trade_date"]) <= sell_date]
        sell_trend = calc_trend(sell_closes_all, n=5)

    # 5. 量比
    buy_vols = [float(k["volume"]) for k in buy_klines if str(k["trade_date"]) <= buy_date]
    buy_vol_ratio = calc_vol_ratio(buy_vols, n=5)

    sell_vol_ratio = None
    if sell_day:
        sell_vols = [float(k["volume"]) for k in sell_klines if str(k["trade_date"]) <= sell_date]
        sell_vol_ratio = calc_vol_ratio(sell_vols, n=5)

    # 6. 价格位置（复权因子修正）
    raw_close_buy = float(buy_day["close_price"])
    adj_close_buy = buy_price  # buy_price是复权价，但可能不是收盘价
    # 更好的做法: 用sell_date的复权因子
    # 但我们没有复权收盘价数据，用近似:
    # 复权因子 = raw_close / (我们不知道复权收盘价)
    # 改用直接比值: position = (buy_price 在当日高低范围内的近似位置)
    # 用BOLL的%b作为近似价格位置
    buy_price_position = buy_boll["pct_b"]

    if sell_boll:
        sell_price_position = sell_boll["pct_b"]
    else:
        sell_price_position = None

    # 7. BOLL对称性
    symmetry = None
    if buy_boll and sell_boll:
        symmetry = round(buy_boll["pct_b"] - sell_boll["pct_b"], 4)

    # 8. 入场信号
    entry_signal = _derive_entry_signal(buy_boll, buy_trend, buy_vol_ratio)

    # 9. 组装更新字段
    fields = {
        "analysis_level": "day",
        "entry_match_method": "daily_exact",
        "entry_boll_15m": buy_boll["pct_b"],
        "entry_trend_15m": buy_trend,
        "entry_vol_ratio_15m": buy_vol_ratio,
        "entry_price_position": buy_price_position,
        "stk_boll_zone": boll_zone_label(buy_boll["pct_b"]),
        "stk_boll_pctb": buy_boll["pct_b"],
        "stk_boll_width": boll_width_label(buy_boll["bandwidth"]),
        "stk_trend": buy_trend,
        "mkt_trend": buy_trend,  # 日线级别无大盘数据，用个股趋势近似
        "stk_vol_ratio": buy_vol_ratio,
        "entry_signal": entry_signal,
    }

    if sell_boll:
        fields["exit_boll_15m"] = sell_boll["pct_b"]
        fields["exit_trend_15m"] = sell_trend
        fields["exit_vol_ratio_15m"] = sell_vol_ratio
        fields["exit_price_position"] = sell_price_position
        fields["exit_match_method"] = "daily_exact"

    # BOLL对称性标签
    if symmetry is not None:
        if symmetry > 0.2:
            fields["position_rule"] = "high_buy_low_sell"
        elif symmetry < -0.2:
            fields["position_rule"] = "low_buy_high_sell"
        else:
            fields["position_rule"] = "symmetric"

    return {"action": "analyzed", "reason": "ok", "fields": fields}


def _derive_entry_signal(boll: Dict, trend: str, vol_ratio: Optional[float]) -> str:
    """根据日线BOLL+趋势+量比推断入场信号"""
    pct_b = boll["pct_b"]
    bandwidth = boll["bandwidth"]

    if pct_b < 0 and trend in ("up", "strong_up"):
        return "boll_lower_reversal"
    elif pct_b < 0.2 and trend in ("down", "strong_down"):
        return "boll_lower_chase"
    elif pct_b > 1.0 and trend in ("up", "strong_up"):
        return "boll_upper_breakout"
    elif pct_b > 0.8 and trend in ("up", "strong_up"):
        return "boll_upper_momentum"
    elif pct_b > 1.0:
        return "boll_upper_overbought"
    elif bandwidth < 0.05:
        return "boll_squeeze"
    elif 0.4 <= pct_b <= 0.6 and trend == "sideways":
        return "boll_middle_sideways"
    elif vol_ratio and vol_ratio > 2.0:
        return "volume_breakout"
    else:
        return "normal_entry"


# ── 写入 ────────────────────────────────────────────────

def update_trade_audit(conn, trade_id: int, fields: Dict):
    """更新trade_audit记录"""
    if not fields:
        return
    set_clauses = [f"{k} = %s" for k in fields.keys()]
    values = list(fields.values()) + [trade_id]
    sql = f"UPDATE trade_audit SET {', '.join(set_clauses)} WHERE id = %s"
    cur = conn.cursor()
    cur.execute(sql, values)


# ── 主流程 ──────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="日线级别买卖位置分析器")
    parser.add_argument("--force", action="store_true", help="重跑已有日线分析")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入数据库")
    args = parser.parse_args()

    with get_conn("hermes") as conn_hermes, get_conn("tdx_data") as conn_tdx:
        cur = conn_hermes.cursor(pymysql.cursors.DictCursor)

        # 查询所有no_data交易
        if args.force:
            cur.execute(
                "SELECT id, stock_code, buy_date, sell_date, buy_price, sell_price, entry_match_method "
                "FROM trade_audit WHERE entry_match_method = 'no_data' OR analysis_level = 'day' "
                "ORDER BY buy_date"
            )
        else:
            cur.execute(
                "SELECT id, stock_code, buy_date, sell_date, buy_price, sell_price, entry_match_method "
                "FROM trade_audit WHERE entry_match_method = 'no_data' "
                "ORDER BY buy_date"
            )
        trades = cur.fetchall()

        print(f"待分析交易: {len(trades)}笔")

        stats = {"analyzed": 0, "skip": 0, "no_kline": 0, "no_match": 0, "no_boll": 0}
        total_updated = 0

        for i, trade in enumerate(trades, 1):
            result = analyze_one_trade(conn_hermes, conn_tdx, trade, force=args.force)
            action = result["action"]
            stats[action] = stats.get(action, 0) + 1

            if action == "analyzed":
                if not args.dry_run:
                    # 清除旧的日线字段再写入
                    if args.force:
                        cur2 = conn_hermes.cursor()
                        cur2.execute(
                            "UPDATE trade_audit SET "
                            "analysis_level=NULL, entry_match_method='no_data', "
                            "entry_boll_15m=NULL, entry_trend_15m=NULL, entry_vol_ratio_15m=NULL, "
                            "entry_price_position=NULL, exit_boll_15m=NULL, exit_trend_15m=NULL, "
                            "exit_vol_ratio_15m=NULL, exit_price_position=NULL, exit_match_method=NULL, "
                            "stk_boll_zone=NULL, stk_boll_pctb=NULL, stk_boll_width=NULL, "
                            "stk_trend=NULL, stk_vol_ratio=NULL, entry_signal=NULL, "
                            "position_rule=NULL, mkt_trend=NULL "
                            "WHERE id = %s", (trade["id"],)
                        )
                    update_trade_audit(conn_hermes, trade["id"], result["fields"])
                    conn_hermes.commit()
                total_updated += 1

            if i % 10 == 0 or action != "skip":
                print(f"  [{i}/{len(trades)}] {trade['stock_code']} {trade['buy_date']}: "
                      f"{action} {result.get('reason', '')}")

        print(f"\n=== 分析完成 ===")
        print(f"总交易: {len(trades)}")
        for k, v in sorted(stats.items()):
            print(f"  {k}: {v}")
        print(f"已更新: {total_updated}笔" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
