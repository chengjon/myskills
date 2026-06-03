#!/usr/bin/env python3
"""
交易路径分析器 (Trade Path Analyzer)
将同一股票的交易序列按"冷却期"切分为独立路径，计算路径级指标并入库。

核心概念:
  - 路径(Path): 同一股票的一系列交易，相邻交易间隔 < gap_threshold 视为同一路径
  - gap_threshold 默认取全局 P80（历史计算约22天），可配置覆盖
  - 同股并行交易（持仓重叠）自动归入同一路径

输出:
  - trade_path_summary 表: 47个字段，路径级汇总
  - trade_audit.path_id 字段: 回填每笔交易所属路径ID

依赖: pymysql, pyyaml, numpy
"""

import math
import os
import sys
import warnings
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

# ── 本模块路径 ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRADE_AUDIT_DIR = os.path.dirname(_SCRIPT_DIR)
_CONFIG_PATH = os.path.join(_TRADE_AUDIT_DIR, "config", "review_config.yaml")


# ============================================================
# 配置 & MySQL 连接（复用 trade_audit_sql 的逻辑）
# ============================================================

def _load_config() -> dict:
    """加载 review_config.yaml，路径分析配置在 path_analysis 节"""
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    return cfg


def _load_mysql_config() -> dict:
    cfg = _load_config()
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
    cfg = config or _load_mysql_config()
    import pymysql
    conn = pymysql.connect(**cfg)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_path_config() -> dict:
    """读取路径分析专用配置，带默认值"""
    cfg = _load_config()
    pa = cfg.get("path_analysis", {})
    return {
        "gap_threshold": pa.get("gap_threshold", None),  # None=自动P80
        "min_path_trades": pa.get("min_path_trades", 2),  # 最少2笔才算路径
        "revenge_gap_days": pa.get("revenge_gap_days", 3),  # 报复性交易间隔
        "impulsive_boll_threshold": pa.get("impulsive_boll_threshold", 90),  # BOLL>%B阈值
        "high_density_trades_per_month": pa.get("high_density_trades_per_month", 8),
        "day_trade_hold_days": pa.get("day_trade_hold_days", 1),
        "pyramid_overlap_days": pa.get("pyramid_overlap_days", 5),
    }


# ============================================================
# 数据加载
# ============================================================

def load_trades(conn=None) -> List[Dict[str, Any]]:
    """从 trade_audit 加载所有已完成交易（sell_date IS NOT NULL）"""
    import pymysql

    close_after = False
    if conn is None:
        conn = pymysql.connect(**_load_mysql_config())
        close_after = True

    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT id, account, stock_code, stock_name, industry,
                   buy_date, buy_price, buy_shares, buy_amount,
                   sell_date, sell_price, sell_shares, sell_amount,
                   hold_days, realized_pnl, pnl_rate, total_fees,
                   stk_boll_pctb, stk_boll_zone,
                   sell_verdict, is_pyramid, is_impulsive,
                   entry_score, exit_score, discipline_score, risk_control_score,
                   total_score, position_ratio, consecutive_losses,
                   trades_same_day, hold_period, trade_category,
                   sell_reason, max_price_hold, max_profit_pct,
                   max_drawdown_pct, stop_loss_hit, is_profit,
                   post5_chg, post10_chg, post20_chg, post60_chg
            FROM trade_audit
            WHERE sell_date IS NOT NULL
            ORDER BY stock_code, buy_date, id
        """)
        rows = cur.fetchall()
        # 转换日期为 date 对象
        for r in rows:
            if isinstance(r.get("buy_date"), str):
                r["buy_date"] = datetime.strptime(r["buy_date"], "%Y-%m-%d").date()
            if isinstance(r.get("sell_date"), str):
                r["sell_date"] = datetime.strptime(r["sell_date"], "%Y-%m-%d").date()
        return rows
    finally:
        if close_after:
            conn.close()


# ============================================================
# Gap 分析 & 自适应切分
# ============================================================

def compute_gap_percentile(trades: List[Dict], percentile: int = 80) -> int:
    """
    计算同一股票相邻交易（上次卖出→本次买入）间隔的百分位。
    只统计正间隔（排除并行交易的负gap），返回整数天数。
    """
    by_stock: Dict[str, List[Dict]] = {}
    for t in trades:
        by_stock.setdefault(t["stock_code"], []).append(t)

    gaps = []
    for code, tlist in by_stock.items():
        sorted_trades = sorted(tlist, key=lambda x: x["buy_date"])
        for i in range(1, len(sorted_trades)):
            prev_sell = sorted_trades[i - 1]["sell_date"]
            curr_buy = sorted_trades[i]["buy_date"]
            if prev_sell and curr_buy:
                gap = (curr_buy - prev_sell).days
                if gap > 0:  # 只统计正间隔
                    gaps.append(gap)

    if not gaps:
        return 22  # 无正间隔数据时用历史P80默认值

    result = int(np.percentile(gaps, percentile))
    return max(result, 5)  # 最小5天，避免极端值


def split_into_paths(trades: List[Dict], gap_threshold: int) -> List[List[Dict]]:
    """
    将交易列表按股票分组，每只股票内按 gap_threshold 切分为路径。
    并行交易（买入日期在前笔卖出日期之前）自动归入同一路径。

    返回: List[路径], 每条路径 = List[交易dict]
    """
    by_stock: Dict[str, List[Dict]] = {}
    for t in trades:
        by_stock.setdefault(t["stock_code"], []).append(t)

    all_paths = []
    for code, tlist in by_stock.items():
        sorted_trades = sorted(tlist, key=lambda x: (x["buy_date"], x["id"]))

        if not sorted_trades:
            continue

        # 切分路径
        current_path = [sorted_trades[0]]
        for i in range(1, len(sorted_trades)):
            prev_sell = max(t["sell_date"] for t in current_path)
            curr_buy = sorted_trades[i]["buy_date"]
            gap = (curr_buy - prev_sell).days

            # gap < threshold 或 并行交易（gap < 0）→ 同一路径
            if gap < gap_threshold:
                current_path.append(sorted_trades[i])
            else:
                all_paths.append(current_path)
                current_path = [sorted_trades[i]]

        all_paths.append(current_path)

    return all_paths


# ============================================================
# 路径级指标计算
# ============================================================

def _safe_float(v, default=0.0) -> float:
    """安全转 float，None/异常返回 default"""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _max_consecutive(seq: List[bool]) -> int:
    """计算布尔序列最长连续 True"""
    max_run = 0
    current = 0
    for v in seq:
        if v:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _compute_drawdown(pnls: List[float]) -> Tuple[float, int, float]:
    """
    计算最大回撤、回撤持续天数、痛感指数(pain index)
    返回: (max_drawdown_ratio, max_dd_duration_days, pain_index)
    max_drawdown_ratio: 0.15 = 最大回撤15%
    """
    if not pnls:
        return 0.0, 0, 0.0

    # 累计PnL曲线
    cum = np.cumsum(pnls)
    peak = cum[0]
    max_dd = 0.0
    max_dd_duration = 0
    dd_start = 0
    pain_values = []

    for i, c in enumerate(cum):
        if c > peak:
            peak = c
            dd_start = i
        dd = peak - c
        if peak > 0:
            dd_ratio = dd / abs(peak) if abs(peak) > 1e-6 else 0.0
        else:
            dd_ratio = dd if dd > 0 else 0.0
        if dd_ratio > max_dd:
            max_dd = dd_ratio
            max_dd_duration = i - dd_start
        pain_values.append(dd_ratio)

    pain_index = float(np.mean(pain_values)) if pain_values else 0.0
    return max_dd, max_dd_duration, pain_index


def _wilson_ci(wins: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """
    Wilson score interval for binomial proportion
    返回: (lower, upper)
    """
    if total == 0:
        return 0.0, 0.0
    n = total
    p_hat = wins / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def _compute_sharpe(pnls: List[float], annualize: bool = True) -> Optional[float]:
    """路径级 Sharpe ratio，<5笔返回 None"""
    if len(pnls) < 5:
        return None
    arr = np.array(pnls)
    mean = arr.mean()
    std = arr.std(ddof=1)
    if std < 1e-6:
        return None
    sharpe = mean / std
    if annualize:
        # 年化：假设平均每笔交易持仓 hold_days 天，一年约250个交易日
        sharpe *= math.sqrt(250 / max(np.mean([1]), 1))  # 简化，用 sqrt(250)
    return round(sharpe, 4)


def _classify_path_type(path: List[Dict], config: dict) -> str:
    """
    七种路径类型:
      1. pyramid       - 金字塔加仓（逐笔加仓+成本下移）
      2. cost_averaging- 摊平（亏损中加仓）
      3. day_trade     - 日内/超短路径（全部 hold_days<=1）
      4. swing         - 波段（持仓1-20天为主）
      5. position      - 中线（持仓20-60天为主）
      6. long_term     - 长线（持仓>60天为主）
      7. mixed         - 混合（无明确模式）
    """
    hold_days_list = [t.get("hold_days", 0) or 0 for t in path]

    # 日内/超短
    if all(hd <= config["day_trade_hold_days"] for hd in hold_days_list):
        return "day_trade"

    # 金字塔加仓: 逐笔买入价递增，或同股并行且买入量递增
    is_pyramid_flag = any(t.get("is_pyramid") for t in path)
    if is_pyramid_flag and len(path) >= 3:
        return "pyramid"

    # 摊平: 亏损加仓（买入价逐步走低，且多笔亏损）
    buy_prices = [_safe_float(t["buy_price"]) for t in path]
    pnls = [_safe_float(t["realized_pnl"]) for t in path]
    if len(path) >= 3:
        declining_prices = all(buy_prices[i] <= buy_prices[i - 1] for i in range(1, len(buy_prices)))
        mostly_losing = sum(1 for p in pnls if p < 0) / len(pnls) > 0.5
        if declining_prices and mostly_losing:
            return "cost_averaging"

    # 按持仓天数分类
    avg_hold = np.mean(hold_days_list)
    if avg_hold <= 5:
        return "swing"
    elif avg_hold <= 20:
        return "swing" if max(hold_days_list) <= 30 else "mixed"
    elif avg_hold <= 60:
        return "position"
    else:
        return "long_term"


def compute_path_metrics(path: List[Dict], config: dict) -> Dict[str, Any]:
    """
    计算一条路径的所有47个字段指标
    输入: path = 同一股票同一路径的交易列表
    """
    n = len(path)
    pnls = [_safe_float(t["realized_pnl"]) for t in path]
    buy_prices = [_safe_float(t["buy_price"]) for t in path]
    sell_prices = [_safe_float(t["sell_price"]) for t in path]
    buy_amounts = [_safe_float(t["buy_amount"]) for t in path]
    sell_amounts = [_safe_float(t["sell_amount"]) for t in path]
    hold_days_list = [t.get("hold_days", 0) or 0 for t in path]
    boll_pctb = [_safe_float(t["stk_boll_pctb"]) for t in path if t.get("stk_boll_pctb") is not None]

    # ── 基础信息 ──
    stock_code = path[0]["stock_code"]
    stock_name = path[0].get("stock_name", "")
    path_start = min(t["buy_date"] for t in path)
    path_end = max(t["sell_date"] for t in path)
    path_duration = (path_end - path_start).days

    # ── 盈亏指标 ──
    total_pnl = sum(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_loss_ratio = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
    wins = sum(1 for p in pnls if p > 0)
    win_rate = round(wins / n * 100, 2) if n > 0 else 0.0
    max_single_profit = max(pnls) if pnls else 0.0
    max_single_loss = min(pnls) if pnls else 0.0
    avg_pnl_per_trade = round(total_pnl / n, 2) if n > 0 else 0.0

    # ── 风险指标 ──
    max_dd, max_dd_dur, pain_index = _compute_drawdown(pnls)
    sharpe = _compute_sharpe(pnls)
    # 限制 max_dd 在 DECIMAL(8,4) 范围内
    max_dd = round(min(max_dd, 99.9999), 4)
    calmar = None
    if max_dd > 0 and total_pnl != 0:
        # 年化收益估算: total_pnl / 总投入 / 年数
        years = max(path_duration / 365.0, 1 / 365)
        total_in = sum(buy_amounts)
        annual_return = (total_pnl / total_in / years) if total_in > 0 else 0
        calmar = round(annual_return / max_dd, 4) if max_dd > 1e-6 else None

    # ── 成本指标 ──
    total_commission = sum(_safe_float(t.get("total_fees", 0)) * 0.7 for t in path)  # 佣金≈费用70%
    total_stamp_tax = sum(_safe_float(t.get("total_fees", 0)) * 0.3 for t in path)   # 印花税≈30%
    total_capital_in = sum(buy_amounts)
    total_capital_out = sum(sell_amounts)
    cost_ratio = round((total_commission + total_stamp_tax) / total_capital_in, 4) if total_capital_in > 0 else None
    net_pnl_after_cost = total_pnl - sum(_safe_float(t.get("total_fees", 0)) for t in path)

    # ── 持仓指标 ──
    avg_hold_days = round(np.mean(hold_days_list), 1) if hold_days_list else 0.0
    max_consec_wins = _max_consecutive([p > 0 for p in pnls])
    max_consec_losses = _max_consecutive([p < 0 for p in pnls])

    # position_peak: 同日最大并行持仓数
    # 按日期统计每只交易的持仓区间重叠
    position_peak = _compute_position_peak(path)

    # ── 行为指标 ──
    is_pyramid = 1 if any(t.get("is_pyramid") for t in path) else 0
    # 摊平检测: 亏损中继续加仓
    is_cost_averaging = 0
    if n >= 3:
        declining = all(buy_prices[i] <= buy_prices[i - 1] for i in range(1, len(buy_prices)))
        mostly_losing = sum(1 for p in pnls if p < 0) / len(pnls) > 0.5
        if declining and mostly_losing:
            is_cost_averaging = 1

    is_intraday = 1 if all(hd <= config["day_trade_hold_days"] for hd in hold_days_list) else 0

    # BOLL 入场位
    avg_entry_boll = round(np.mean(boll_pctb), 4) if boll_pctb else None
    bull_entry_rate = round(
        sum(1 for b in boll_pctb if b > 50) / len(boll_pctb) * 100, 2
    ) if boll_pctb else None

    # 入场评分均值
    entry_scores = [_safe_float(t.get("entry_score"), default=0) for t in path if t.get("entry_score") is not None]
    avg_entry_score = round(np.mean(entry_scores), 1) if entry_scores else None

    # 冲动交易率
    impulsive_count = sum(1 for t in path if t.get("is_impulsive"))
    impulsive_rate = round(impulsive_count / n * 100, 2) if n > 0 else 0.0

    # 报复性交易率: 连亏后 N 天内买入同一股票
    revenge_gap = config["revenge_gap_days"]
    revenge_count = 0
    for i in range(1, len(path)):
        if pnls[i - 1] < 0:
            gap = (path[i]["buy_date"] - path[i - 1]["sell_date"]).days
            if 0 <= gap <= revenge_gap:
                revenge_count += 1
    revenge_trade_rate = round(revenge_count / max(n - 1, 1) * 100, 2)

    # 交易密度: 每月平均交易笔数
    months = max(path_duration / 30.0, 1 / 30)
    trade_density = round(n / months, 2)

    # ── 价格指标 ──
    avg_cost_price = round(np.mean(buy_prices), 3) if buy_prices else None
    avg_sell_price = round(np.mean(sell_prices), 3) if sell_prices else None
    cost_improvement = None
    if avg_cost_price and len(buy_prices) >= 2:
        # 成本改善: 后半段买入均价 vs 前半段
        mid = len(buy_prices) // 2
        if mid > 0:
            first_half_avg = np.mean(buy_prices[:mid])
            second_half_avg = np.mean(buy_prices[mid:])
            if first_half_avg > 0:
                cost_improvement = round((first_half_avg - second_half_avg) / first_half_avg, 4)

    # ── 间隔指标 ──
    intervals = []
    for i in range(1, len(path)):
        interval = (path[i]["buy_date"] - path[i - 1]["buy_date"]).days
        intervals.append(abs(interval))
    avg_trade_interval = round(np.mean(intervals), 1) if intervals else None

    # 日内交易笔数
    day_trading_count = sum(1 for hd in hold_days_list if hd <= config["day_trade_hold_days"])

    # ── 路径类型 ──
    path_type = _classify_path_type(path, config)

    # ── path_id ──
    path_id = f"{stock_code}_{path_start.strftime('%Y%m%d')}_{path_end.strftime('%Y%m%d')}"

    # ── Wilson CI ──
    win_rate_lower, win_rate_upper = _wilson_ci(wins, n)

    return {
        "path_id": path_id,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "path_start": path_start,
        "path_end": path_end,
        "path_duration": path_duration,
        "trade_count": n,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "win_rate": win_rate,
        "max_single_profit": max_single_profit,
        "max_single_loss": max_single_loss,
        "avg_pnl_per_trade": avg_pnl_per_trade,
        "sharpe_of_path": sharpe,
        "max_drawdown": max_dd,
        "max_drawdown_duration": max_dd_dur,
        "pain_index": pain_index,
        "calmar_ratio": calmar,
        "total_commission": round(total_commission, 2),
        "total_stamp_tax": round(total_stamp_tax, 2),
        "cost_ratio": cost_ratio,
        "net_pnl_after_cost": net_pnl_after_cost,
        "avg_hold_days": avg_hold_days,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "position_peak": position_peak,
        "is_pyramid": is_pyramid,
        "is_cost_averaging": is_cost_averaging,
        "is_intraday": is_intraday,
        "avg_entry_boll": avg_entry_boll,
        "bull_entry_rate": bull_entry_rate,
        "avg_entry_score": avg_entry_score,
        "impulsive_rate": impulsive_rate,
        "revenge_trade_rate": revenge_trade_rate,
        "trade_density": trade_density,
        "total_capital_in": total_capital_in,
        "total_capital_out": total_capital_out,
        "avg_cost_price": avg_cost_price,
        "avg_sell_price": avg_sell_price,
        "cost_improvement": cost_improvement,
        "avg_trade_interval": avg_trade_interval,
        "day_trading_count": day_trading_count,
        "path_type": path_type,
        # 非入库字段，报告用
        "_win_rate_ci": (win_rate_lower, win_rate_upper),
        "_trade_ids": [t["id"] for t in path],
    }


def _compute_position_peak(path: List[Dict]) -> int:
    """计算路径中同日最大并行持仓数"""
    # 构建每笔交易的持仓区间
    intervals = [(t["buy_date"], t["sell_date"]) for t in path]
    if not intervals:
        return 0

    # 采样所有边界日期
    all_dates = set()
    for start, end in intervals:
        all_dates.add(start)
        all_dates.add(end)

    peak = 0
    for d in all_dates:
        overlap = sum(1 for s, e in intervals if s <= d <= e)
        peak = max(peak, overlap)

    return peak


# ============================================================
# 入库
# ============================================================

def _build_upsert_sql() -> str:
    """构建 INSERT ... ON DUPLICATE KEY UPDATE 语句"""
    fields = [
        "path_id", "stock_code", "stock_name", "path_start", "path_end",
        "path_duration", "trade_count", "total_pnl", "gross_profit", "gross_loss",
        "profit_loss_ratio", "win_rate", "max_single_profit", "max_single_loss",
        "avg_pnl_per_trade", "sharpe_of_path", "max_drawdown", "max_drawdown_duration",
        "pain_index", "calmar_ratio", "total_commission", "total_stamp_tax",
        "cost_ratio", "net_pnl_after_cost", "avg_hold_days", "max_consec_wins",
        "max_consec_losses", "position_peak", "is_pyramid", "is_cost_averaging",
        "is_intraday", "avg_entry_boll", "bull_entry_rate", "avg_entry_score",
        "impulsive_rate", "revenge_trade_rate", "trade_density",
        "total_capital_in", "total_capital_out", "avg_cost_price", "avg_sell_price",
        "cost_improvement", "avg_trade_interval", "day_trading_count", "path_type",
    ]
    placeholders = ", ".join(["%s"] * len(fields))
    field_str = ", ".join(fields)
    # ON DUPLICATE KEY UPDATE: 更新除 path_id 外所有字段
    update_str = ", ".join(f"{f}=VALUES({f})" for f in fields if f != "path_id")
    return f"""
        INSERT INTO trade_path_summary ({field_str})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {update_str}
    """


def save_path_to_db(metrics: Dict[str, Any], conn=None):
    """保存一条路径指标到 trade_path_summary"""
    close_after = False
    if conn is None:
        import pymysql
        conn = pymysql.connect(**_load_mysql_config())
        close_after = True

    try:
        cur = conn.cursor()
        sql = _build_upsert_sql()
        values = (
            metrics["path_id"],
            metrics["stock_code"],
            metrics["stock_name"],
            metrics["path_start"],
            metrics["path_end"],
            metrics["path_duration"],
            metrics["trade_count"],
            metrics["total_pnl"],
            metrics["gross_profit"],
            metrics["gross_loss"],
            metrics["profit_loss_ratio"],
            metrics["win_rate"],
            metrics["max_single_profit"],
            metrics["max_single_loss"],
            metrics["avg_pnl_per_trade"],
            metrics["sharpe_of_path"],
            metrics["max_drawdown"],
            metrics["max_drawdown_duration"],
            metrics["pain_index"],
            metrics["calmar_ratio"],
            metrics["total_commission"],
            metrics["total_stamp_tax"],
            metrics["cost_ratio"],
            metrics["net_pnl_after_cost"],
            metrics["avg_hold_days"],
            metrics["max_consec_wins"],
            metrics["max_consec_losses"],
            metrics["position_peak"],
            metrics["is_pyramid"],
            metrics["is_cost_averaging"],
            metrics["is_intraday"],
            metrics["avg_entry_boll"],
            metrics["bull_entry_rate"],
            metrics["avg_entry_score"],
            metrics["impulsive_rate"],
            metrics["revenge_trade_rate"],
            metrics["trade_density"],
            metrics["total_capital_in"],
            metrics["total_capital_out"],
            metrics["avg_cost_price"],
            metrics["avg_sell_price"],
            metrics["cost_improvement"],
            metrics["avg_trade_interval"],
            metrics["day_trading_count"],
            metrics["path_type"],
        )
        cur.execute(sql, values)

        # 回填 trade_audit.path_id
        trade_ids = metrics["_trade_ids"]
        if trade_ids:
            placeholders = ", ".join(["%s"] * len(trade_ids))
            cur.execute(
                f"UPDATE trade_audit SET path_id = %s WHERE id IN ({placeholders})",
                [metrics["path_id"]] + trade_ids,
            )

        conn.commit()
    finally:
        if close_after:
            conn.close()


# ============================================================
# 主入口
# ============================================================

def analyze_paths(force: bool = False) -> Dict[str, Any]:
    """
    执行路径分析主流程

    Args:
        force: True=强制全量重算，False=增量（跳过已有 path_id 的交易）

    Returns:
        dict with summary stats
    """
    config = _get_path_config()

    with get_conn() as conn:
        # 1. 加载交易数据
        trades = load_trades(conn)
        print(f"[路径分析] 加载交易: {len(trades)} 笔")

        if not trades:
            return {"error": "no trades found"}

        # 增量模式: 过滤掉已分配 path_id 的交易
        if not force:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT id FROM trade_audit WHERE path_id IS NOT NULL")
            existing_ids = {row[0] for row in cur.fetchall()}
            new_trades = [t for t in trades if t["id"] not in existing_ids]
            if not new_trades:
                print("[路径分析] 无新交易，跳过")
                return {"total_paths": 0, "skipped": True}
            trades = new_trades
            print(f"[路径分析] 增量模式: {len(trades)} 笔新交易")

        # 2. 计算 gap 阈值
        gap_threshold = config["gap_threshold"]
        if gap_threshold is None:
            # 全量计算百分位
            all_trades = load_trades(conn)
            gap_threshold = compute_gap_percentile(all_trades, percentile=80)
            print(f"[路径分析] 自动 gap_threshold = P80 = {gap_threshold} 天")
        else:
            print(f"[路径分析] 配置 gap_threshold = {gap_threshold} 天")

        # 3. 切分路径
        paths = split_into_paths(trades, gap_threshold)
        print(f"[路径分析] 切分为 {len(paths)} 条路径")

        # 4. 过滤短路径
        min_trades = config["min_path_trades"]
        valid_paths = [p for p in paths if len(p) >= min_trades]
        single_paths = [p for p in paths if len(p) < min_trades]
        print(f"[路径分析] 有效路径(≥{min_trades}笔): {len(valid_paths)}, 单笔路径: {len(single_paths)}")

        # 5. 计算指标 & 入库
        results = []
        for i, path in enumerate(valid_paths):
            metrics = compute_path_metrics(path, config)
            save_path_to_db(metrics, conn)
            results.append(metrics)
            if (i + 1) % 20 == 0 or i == len(valid_paths) - 1:
                print(f"[路径分析] 进度: {i + 1}/{len(valid_paths)}")

        # 单笔路径也分配 path_id（格式: single_XXX）
        for path in single_paths:
            t = path[0]
            pid = f"single_{t['stock_code']}_{t['buy_date'].strftime('%Y%m%d')}"
            cur = conn.cursor()
            cur.execute("UPDATE trade_audit SET path_id = %s WHERE id = %s", (pid, t["id"]))
        conn.commit()

    # 6. 输出报告
    report = _generate_report(results, gap_threshold, config)
    return report


def _generate_report(results: List[Dict], gap_threshold: int, config: dict) -> Dict[str, Any]:
    """生成汇总报告"""
    if not results:
        return {"total_paths": 0}

    total_pnl = sum(r["total_pnl"] for r in results)
    total_trades = sum(r["trade_count"] for r in results)

    # 路径类型分布
    type_dist = {}
    for r in results:
        pt = r["path_type"]
        type_dist[pt] = type_dist.get(pt, 0) + 1

    # 赢/亏路径
    winning_paths = sum(1 for r in results if r["total_pnl"] > 0)
    losing_paths = sum(1 for r in results if r["total_pnl"] <= 0)

    # TOP5 最赚/最亏
    by_pnl = sorted(results, key=lambda x: x["total_pnl"], reverse=True)
    top5_profit = [
        {"path_id": r["path_id"], "pnl": r["total_pnl"], "trades": r["trade_count"], "type": r["path_type"]}
        for r in by_pnl[:5]
    ]
    top5_loss = [
        {"path_id": r["path_id"], "pnl": r["total_pnl"], "trades": r["trade_count"], "type": r["path_type"]}
        for r in by_pnl[-5:]
    ]

    # 行为问题
    high_impulsive = [r for r in results if r["impulsive_rate"] > 30]
    high_revenge = [r for r in results if r["revenge_trade_rate"] > 30]
    cost_averaging = [r for r in results if r["is_cost_averaging"]]

    # Wilson CI 汇总
    win_rates = [r["win_rate"] for r in results if r["win_rate"] is not None]
    avg_win_rate = round(np.mean(win_rates), 2) if win_rates else 0.0

    return {
        "total_paths": len(results),
        "total_trades_in_paths": total_trades,
        "gap_threshold": gap_threshold,
        "total_pnl": round(total_pnl, 2),
        "winning_paths": winning_paths,
        "losing_paths": losing_paths,
        "avg_win_rate": avg_win_rate,
        "path_type_distribution": type_dist,
        "top5_profit_paths": top5_profit,
        "top5_loss_paths": top5_loss,
        "behavior_issues": {
            "high_impulsive_paths": len(high_impulsive),
            "high_revenge_paths": len(high_revenge),
            "cost_averaging_paths": len(cost_averaging),
        },
    }


def print_report(report: Dict[str, Any]):
    """打印人类可读的报告"""
    if "error" in report:
        print(f"错误: {report['error']}")
        return
    if report.get("skipped"):
        print("无新交易需要分析")
        return
    if report["total_paths"] == 0:
        print("无有效路径")
        return

    print("\n" + "=" * 60)
    print("  交易路径分析报告")
    print("=" * 60)
    print(f"  路径切分阈值(gap): {report['gap_threshold']} 天")
    print(f"  有效路径数: {report['total_paths']}")
    print(f"  路径内交易总数: {report['total_trades_in_paths']}")
    print(f"  路径总盈亏: {report['total_pnl']:,.2f}")
    print(f"  盈利路径: {report['winning_paths']} / 亏损路径: {report['losing_paths']}")
    print(f"  路径平均胜率: {report['avg_win_rate']:.1f}%")

    print("\n  路径类型分布:")
    for pt, cnt in sorted(report.get("path_type_distribution", {}).items(), key=lambda x: -x[1]):
        pct = cnt / report["total_paths"] * 100
        print(f"    {pt:20s}: {cnt:3d} ({pct:.0f}%)")

    print("\n  TOP5 最赚路径:")
    for r in report.get("top5_profit_paths", []):
        print(f"    {r['path_id']:30s}  PnL={r['pnl']:>10,.2f}  {r['trades']}笔  {r['type']}")

    print("\n  TOP5 最亏路径:")
    for r in report.get("top5_loss_paths", []):
        print(f"    {r['path_id']:30s}  PnL={r['pnl']:>10,.2f}  {r['trades']}笔  {r['type']}")

    bi = report.get("behavior_issues", {})
    if bi:
        print(f"\n  行为预警:")
        print(f"    高冲动率(>30%)路径: {bi.get('high_impulsive_paths', 0)}")
        print(f"    高报复性(>30%)路径: {bi.get('high_revenge_paths', 0)}")
        print(f"    摊平加仓路径:       {bi.get('cost_averaging_paths', 0)}")

    print("=" * 60)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="交易路径分析器")
    parser.add_argument("--force", action="store_true", help="强制全量重算")
    parser.add_argument("--gap", type=int, default=None, help="覆盖 gap 阈值(天)")
    args = parser.parse_args()

    if args.gap is not None:
        # 临时覆盖配置
        cfg = _get_path_config()
        cfg["gap_threshold"] = args.gap

    report = analyze_paths(force=args.force)
    print_report(report)
