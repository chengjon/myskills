#!/usr/bin/env python3
"""
交易路径交叉分析器 (Trade Path Cross-Analyzer)
基于 trade_path_summary + trade_audit 生成：
  1. BOLL位置 × 持仓天数 交叉胜率表
  2. 冲动交易细分 × sell_verdict
  3. 全局连亏次数 × 下次交易结果
  4. 交易顺序效应（路径内第N笔）
  5. 行为画像（含年度演变 + Wilson CI）
  6. 路径类型深度对比

输出: Obsidian Markdown 报告

依赖: pymysql, pyyaml, numpy
"""

import math
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

# ── 复用 trade_path_analyzer 的连接逻辑 ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRADE_AUDIT_DIR = os.path.dirname(_SCRIPT_DIR)
_CONFIG_PATH = os.path.join(_TRADE_AUDIT_DIR, "config", "review_config.yaml")


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


# ============================================================
# Wilson CI & Cohen's d
# ============================================================

def wilson_ci(wins: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for binomial proportion. Returns (lower, upper) in %."""
    if total == 0:
        return 0.0, 0.0
    n = total
    p_hat = wins / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * n)) / n) / denom
    return max(0.0, (center - spread) * 100), min(100.0, (center + spread) * 100)


def cohens_d(group_a: List[float], group_b: List[float]) -> Optional[float]:
    """Cohen's d effect size. Returns None if either group has < 2 values."""
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    a, b = np.array(group_a), np.array(group_b)
    pooled_std = math.sqrt(((len(a) - 1) * a.std(ddof=1) ** 2 + (len(b) - 1) * b.std(ddof=1) ** 2) / (len(a) + len(b) - 2))
    if pooled_std < 1e-6:
        return None
    return float((a.mean() - b.mean()) / pooled_std)


def fmt_ci(wins: int, total: int) -> str:
    """Format Wilson CI as '[lo%-hi%]' with sample size."""
    if total == 0:
        return "—"
    lo, hi = wilson_ci(wins, total)
    warn = " ⚠️" if total < 30 else ""
    return f"{wins}/{total} [{lo:.0f}-{hi:.0f}%]{warn}"


# ============================================================
# 数据加载
# ============================================================

def load_audit_trades(conn) -> List[Dict]:
    """加载 trade_audit 全量数据"""
    import pymysql
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT id, stock_code, stock_name, buy_date, buy_price, buy_shares, buy_amount,
               sell_date, sell_price, sell_shares, sell_amount,
               hold_days, realized_pnl, pnl_rate, total_fees,
               stk_boll_pctb, stk_boll_zone, stk_trend,
               sell_verdict, is_pyramid, is_impulsive,
               entry_score, exit_score, discipline_score, risk_control_score,
               total_score, position_ratio, consecutive_losses,
               hold_period, trade_category, sell_reason,
               max_price_hold, max_profit_pct, max_drawdown_pct,
               is_profit, path_id,
               post5_chg, post10_chg, post20_chg, post60_chg
        FROM trade_audit
        WHERE sell_date IS NOT NULL
        ORDER BY sell_date, stock_code
    """)
    rows = cur.fetchall()
    for r in rows:
        if isinstance(r.get("buy_date"), str):
            r["buy_date"] = datetime.strptime(r["buy_date"], "%Y-%m-%d").date()
        if isinstance(r.get("sell_date"), str):
            r["sell_date"] = datetime.strptime(r["sell_date"], "%Y-%m-%d").date()
    return rows


def load_path_summary(conn) -> List[Dict]:
    """加载 trade_path_summary 全量数据"""
    import pymysql
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM trade_path_summary ORDER BY total_pnl DESC")
    return cur.fetchall()


# ============================================================
# 交叉分析 1: BOLL × 持仓天数
# ============================================================

def analyze_boll_hold(trades: List[Dict]) -> str:
    """BOLL位置 × 持仓天数 交叉胜率表"""
    boll_bins = [("≤20%", 0, 20), ("20-80%", 20, 80), (">80%", 80, 101)]
    hold_bins = [("超短(≤3d)", 0, 3), ("短线(4-7d)", 4, 7), ("短中(8-20d)", 8, 20), ("中线(21d+)", 21, 9999)]

    lines = ["### 3.1 BOLL位置 × 持仓天数\n"]
    lines.append("| | " + " | ".join(h[0] for h in hold_bins) + " |")
    lines.append("|---|" + "|".join("---:" for _ in hold_bins) + "|")

    for boll_label, boll_lo, boll_hi in boll_bins:
        cells = []
        for hold_label, hold_lo, hold_hi in hold_bins:
            subset = [
                t for t in trades
                if t.get("stk_boll_pctb") is not None
                and boll_lo <= _safe_float(t["stk_boll_pctb"]) < boll_hi
                and t.get("hold_days") is not None
                and hold_lo <= (t["hold_days"] or 0) <= hold_hi
            ]
            wins = sum(1 for t in subset if _safe_float(t["realized_pnl"]) > 0)
            n = len(subset)
            avg_pnl = np.mean([_safe_float(t["realized_pnl"]) for t in subset]) if subset else 0
            cells.append(f"{fmt_ci(wins, n)} / {avg_pnl:+.0f}" if n > 0 else "—")
        lines.append(f"| **{boll_label}** | " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ============================================================
# 交叉分析 2: 冲动交易细分 × sell_verdict
# ============================================================

def analyze_impulsive_verdict(trades: List[Dict]) -> str:
    """冲动买入 vs 冲动卖出 × sell_verdict"""
    verdicts = ["good_profit", "normal", "missed_profit", "late_stop"]

    # 分类
    imp_buy_cool_sell = []  # 冲动买入 + 冷静卖出
    cool_buy_imp_sell = []  # 冷静买入 + 冲动卖出
    imp_both = []           # 双冲动
    cool_both = []          # 双冷静

    for t in trades:
        is_imp = t.get("is_impulsive", 0)
        # 简化: 用 is_impulsive 标记整体
        # 买入冲动判定: is_impulsive=1 且 entry_score < 5
        # 卖出冲动判定: is_impulsive=1 且 exit_score < 5
        entry_score = _safe_float(t.get("entry_score"), default=5)
        exit_score = _safe_float(t.get("exit_score"), default=5)
        imp_buy = is_imp and entry_score < 5
        imp_sell = is_imp and exit_score < 5

        if imp_buy and not imp_sell:
            imp_buy_cool_sell.append(t)
        elif not imp_buy and imp_sell:
            cool_buy_imp_sell.append(t)
        elif imp_buy and imp_sell:
            imp_both.append(t)
        else:
            cool_both.append(t)

    groups = [
        ("冲动买入+冷静卖出", imp_buy_cool_sell),
        ("冷静买入+冲动卖出", cool_buy_imp_sell),
        ("双冲动", imp_both),
        ("双冷静", cool_both),
    ]

    lines = ["### 3.2 冲动交易细分 × sell_verdict\n"]
    header = "| | 笔数 | " + " | ".join(verdicts) + " |"
    sep = "|---|---:" + "|".join("---:" for _ in verdicts) + "|"
    lines += [header, sep]

    for label, group in groups:
        n = len(group)
        verdict_counts = {}
        for v in verdicts:
            cnt = sum(1 for t in group if t.get("sell_verdict") == v)
            pct = cnt / n * 100 if n > 0 else 0
            verdict_counts[v] = f"{cnt}({pct:.0f}%)" if n > 0 else "0"
        cells = [str(n)] + [verdict_counts[v] for v in verdicts]
        lines.append(f"| **{label}** | " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ============================================================
# 交叉分析 3: 全局连亏次数 × 下次交易结果
# ============================================================

def analyze_consecutive_losses(trades: List[Dict]) -> str:
    """按 sell_date 全局排序，计算连亏对下次交易的影响"""
    sorted_trades = sorted(trades, key=lambda t: (t["sell_date"], t["stock_code"]))

    # 计算全局连亏序列
    loss_streak = 0
    streak_data = {0: [], 1: [], 2: [], 3: []}  # 连亏N次后→下次交易

    for i, t in enumerate(sorted_trades):
        if i > 0:
            prev_pnl = _safe_float(sorted_trades[i - 1]["realized_pnl"])
            if prev_pnl < 0:
                loss_streak += 1
            else:
                loss_streak = 0

        streak_key = min(loss_streak, 3)
        pnl = _safe_float(t["realized_pnl"])
        streak_data[streak_key].append(pnl)

    lines = ["### 3.3 全局连亏次数 × 下次交易结果\n"]
    lines.append("| 连亏N次后 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 | vs连亏0次 Cohen's d |")
    lines.append("|-----------|-----:|:---------------|--------:|:-------------------|")

    baseline_pnls = streak_data[0]

    for n_loss in range(4):
        pnls = streak_data[n_loss]
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        avg = np.mean(pnls) if pnls else 0
        ci = fmt_ci(wins, n)
        d = cohens_d(pnls, baseline_pnls) if n_loss > 0 and len(pnls) >= 2 else None
        d_str = f"{d:.2f}" if d is not None else "—"
        label = f"{n_loss}次+" if n_loss == 3 else f"{n_loss}次"
        lines.append(f"| **{label}** | {n} | {ci} | {avg:+.0f} | {d_str} |")

    return "\n".join(lines)


# ============================================================
# 交叉分析 4: 交易顺序效应
# ============================================================

def analyze_trade_order(trades: List[Dict]) -> str:
    """路径内第N笔的胜率变化"""
    # 按路径分组，给每笔交易标上路径内序号
    by_path: Dict[str, List[Dict]] = {}
    for t in trades:
        pid = t.get("path_id", "")
        if pid and not pid.startswith("single_"):
            by_path.setdefault(pid, []).append(t)

    order_pnls: Dict[int, List[float]] = {}
    for pid, path_trades in by_path.items():
        sorted_path = sorted(path_trades, key=lambda t: (t["buy_date"], t["id"]))
        for idx, t in enumerate(sorted_path):
            order_key = min(idx + 1, 5)  # 第5笔+ 合并
            if order_key not in order_pnls:
                order_pnls[order_key] = []
            order_pnls[order_key].append(_safe_float(t["realized_pnl"]))

    lines = ["### 3.4 交易顺序效应（路径内第N笔）\n"]
    lines.append("| 第N笔 | 笔数 | 胜率(Wilson CI) | 笔均盈亏 | vs第1笔 Cohen's d |")
    lines.append("|-------|-----:|:---------------|--------:|:-----------------|")

    baseline = order_pnls.get(1, [])

    for order in [1, 2, 3, 4, 5]:
        pnls = order_pnls.get(order, [])
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        avg = np.mean(pnls) if pnls else 0
        ci = fmt_ci(wins, n)
        d = cohens_d(pnls, baseline) if order > 1 and len(pnls) >= 2 else None
        d_str = f"{d:.2f}" if d is not None else "—"
        label = f"第5笔+" if order == 5 else f"第{order}笔"
        lines.append(f"| **{label}** | {n} | {ci} | {avg:+.0f} | {d_str} |")

    return "\n".join(lines)


# ============================================================
# 行为画像: 年度演变 + Wilson CI
# ============================================================

def analyze_behavior_profile(trades: List[Dict]) -> str:
    """年度行为演变 + Wilson CI"""
    # 按年度分组
    by_year: Dict[str, List[Dict]] = {}
    for t in trades:
        yr = str(t["sell_date"].year)
        by_year.setdefault(yr, []).append(t)

    # 合并 2021+2022 为"早期"
    early = by_year.pop("2021", []) + by_year.pop("2022", [])
    if early:
        by_year["早期(21-22)"] = early

    years = sorted(by_year.keys())

    lines = ["### 3.5 行为画像 — 年度演变\n"]
    lines.append("| 指标 | " + " | ".join(years) + " | 趋势 |")
    lines.append("|------|" + "|".join("---:" for _ in years) + "|:-----|")

    # 胜率
    wr_cells = []
    for yr in years:
        yr_trades = by_year[yr]
        n = len(yr_trades)
        wins = sum(1 for t in yr_trades if _safe_float(t["realized_pnl"]) > 0)
        lo, hi = wilson_ci(wins, n)
        warn = " ⚠️" if n < 30 else ""
        wr_cells.append(f"{wins/n*100:.1f}% [{lo:.0f}-{hi:.0f}%]{warn}")
    # 趋势
    wr_vals = [sum(1 for t in by_year[yr] if _safe_float(t["realized_pnl"]) > 0) / max(len(by_year[yr]), 1) for yr in years]
    trend = _detect_trend(wr_vals)
    lines.append("| **胜率** | " + " | ".join(wr_cells) + f" | {trend} |")

    # 冲动率
    imp_cells = []
    for yr in years:
        yr_trades = by_year[yr]
        n = len(yr_trades)
        imp = sum(1 for t in yr_trades if t.get("is_impulsive"))
        lo, hi = wilson_ci(imp, n)
        warn = " ⚠️" if n < 30 else ""
        imp_cells.append(f"{imp/n*100:.1f}% [{lo:.0f}-{hi:.0f}%]{warn}")
    imp_vals = [sum(1 for t in by_year[yr] if t.get("is_impulsive")) / max(len(by_year[yr]), 1) for yr in years]
    trend = _detect_trend(imp_vals)
    lines.append("| **冲动率** | " + " | ".join(imp_cells) + f" | {trend} |")

    # 平均持仓天数
    hold_cells = []
    for yr in years:
        yr_trades = by_year[yr]
        holds = [_safe_float(t.get("hold_days"), default=0) for t in yr_trades]
        avg = np.mean(holds) if holds else 0
        hold_cells.append(f"{avg:.1f}")
    hold_vals = [np.mean([_safe_float(t.get("hold_days"), default=0) for t in by_year[yr]]) for yr in years]
    trend = _detect_trend(hold_vals)
    lines.append("| **平均持仓天** | " + " | ".join(hold_cells) + f" | {trend} |")

    # 笔均盈亏
    pnl_cells = []
    for yr in years:
        yr_trades = by_year[yr]
        pnls = [_safe_float(t["realized_pnl"]) for t in yr_trades]
        avg = np.mean(pnls) if pnls else 0
        pnl_cells.append(f"{avg:+.0f}")
    pnl_vals = [np.mean([_safe_float(t["realized_pnl"]) for t in by_year[yr]]) for yr in years]
    trend = _detect_trend(pnl_vals)
    lines.append("| **笔均盈亏** | " + " | ".join(pnl_cells) + f" | {trend} |")

    # 行为改善指数
    lines.append(f"\n> 行为改善指数: {_behavior_improvement_index(by_year, years):.2f}")

    # 关键事件
    lines.append("\n**关键事件:**")
    if len(years) >= 3:
        # 找最差胜率年份
        wr_by_yr = {yr: sum(1 for t in by_year[yr] if _safe_float(t["realized_pnl"]) > 0) / max(len(by_year[yr]), 1) for yr in years}
        worst_yr = min(wr_by_yr, key=wr_by_yr.get)
        lines.append(f"  {worst_yr}大亏(胜率{wr_by_yr[worst_yr]*100:.0f}%) → 防御反应: 缩短持仓+增加交易频率")

    return "\n".join(lines)


def _detect_trend(vals: List[float]) -> str:
    """检测趋势方向"""
    if len(vals) < 2:
        return "—"
    first, last = vals[0], vals[-1]
    if abs(last - first) < 0.05:
        return "→ 平稳"
    if last > first:
        return "↑ 改善" if first < 0.5 else "↑↑ 上升"
    else:
        return "↓ 恶化" if first > 0.3 else "↓↓ 下降"


def _behavior_improvement_index(by_year: Dict, years: List[str]) -> float:
    """
    行为改善指数: 综合胜率+冲动率+持仓天数的变化
    >0 改善, <0 恶化
    """
    if len(years) < 2:
        return 0.0
    first, last = years[0], years[-1]

    # 胜率变化 (正=改善)
    wr_first = sum(1 for t in by_year[first] if _safe_float(t["realized_pnl"]) > 0) / max(len(by_year[first]), 1)
    wr_last = sum(1 for t in by_year[last] if _safe_float(t["realized_pnl"]) > 0) / max(len(by_year[last]), 1)
    wr_delta = wr_last - wr_first

    # 冲动率变化 (负=改善)
    imp_first = sum(1 for t in by_year[first] if t.get("is_impulsive")) / max(len(by_year[first]), 1)
    imp_last = sum(1 for t in by_year[last] if t.get("is_impulsive")) / max(len(by_year[last]), 1)
    imp_delta = -(imp_last - imp_first)

    # 持仓天数变化 (正=改善, 负=恶化)
    hold_first = np.mean([_safe_float(t.get("hold_days"), default=0) for t in by_year[first]])
    hold_last = np.mean([_safe_float(t.get("hold_days"), default=0) for t in by_year[last]])
    hold_delta = (hold_last - hold_first) / max(hold_first, 1)

    return round((wr_delta + imp_delta + hold_delta) / 3, 2)


# ============================================================
# 路径类型深度对比
# ============================================================

def analyze_path_types(paths: List[Dict]) -> str:
    """路径类型深度对比表"""
    by_type: Dict[str, List[Dict]] = {}
    for p in paths:
        pt = p.get("path_type", "unknown")
        by_type.setdefault(pt, []).append(p)

    lines = ["### 3.6 路径类型深度对比\n"]
    lines.append("| 类型 | 路径数 | 总笔数 | 平均胜率 | 平均PnL | 平均持仓天 | 冲动率 | 摊平率 |")
    lines.append("|------|-------:|-------:|--------:|--------:|----------:|-------:|-------:|")

    for pt in sorted(by_type.keys(), key=lambda x: -len(by_type[x])):
        ps = by_type[pt]
        n = len(ps)
        total_trades = sum(p.get("trade_count", 0) or 0 for p in ps)
        avg_wr = np.mean([_safe_float(p.get("win_rate")) for p in ps])
        avg_pnl = np.mean([_safe_float(p.get("total_pnl")) for p in ps])
        avg_hold = np.mean([_safe_float(p.get("avg_hold_days")) for p in ps])
        avg_imp = np.mean([_safe_float(p.get("impulsive_rate")) for p in ps])
        avg_ca = np.mean([1 if p.get("is_cost_averaging") else 0 for p in ps]) * 100
        lines.append(f"| **{pt}** | {n} | {total_trades} | {avg_wr:.1f}% | {avg_pnl:+,.0f} | {avg_hold:.1f} | {avg_imp:.0f}% | {avg_ca:.0f}% |")

    return "\n".join(lines)


# ============================================================
# 辅助函数
# ============================================================

def _safe_float(v, default=0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ============================================================
# 主报告生成
# ============================================================

def generate_report() -> str:
    """生成完整交叉分析报告"""
    with get_conn() as conn:
        trades = load_audit_trades(conn)
        paths = load_path_summary(conn)

    print(f"[交叉分析] 加载交易: {len(trades)} 笔, 路径: {len(paths)} 条")

    # 基本信息
    total_pnl = sum(_safe_float(t["realized_pnl"]) for t in trades)
    wins = sum(1 for t in trades if _safe_float(t["realized_pnl"]) > 0)
    total_n = len(trades)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = f"""---
title: 交易路径交叉分析报告
date: {now}
tags: [复盘, 交易路径, 交叉分析, Wilson-CI]
source: trade_audit + trade_path_summary
---

# 交易路径交叉分析报告

> 生成时间: {now} | 交易: {total_n}笔 | 路径: {len(paths)}条

## 一、总体概览

| 指标 | 值 |
|------|-----|
| 总交易笔数 | {total_n} |
| 总盈亏 | {total_pnl:+,.2f} |
| 总胜率 | {wins/total_n*100:.1f}% {fmt_ci(wins, total_n)} |
| 盈利路径 | {sum(1 for p in paths if _safe_float(p.get('total_pnl')) > 0)} / {len(paths)} |
| 平均路径长度 | {np.mean([p.get('trade_count',0) or 0 for p in paths]):.1f}笔 |

"""

    # 交叉分析
    report += "## 二、交叉分析\n\n"
    report += analyze_boll_hold(trades) + "\n\n"
    report += analyze_impulsive_verdict(trades) + "\n\n"
    report += analyze_consecutive_losses(trades) + "\n\n"
    report += analyze_trade_order(trades) + "\n\n"
    report += analyze_behavior_profile(trades) + "\n\n"
    report += analyze_path_types(paths) + "\n\n"

    # TOP 路径
    report += "## 三、关键路径\n\n"
    report += "### TOP5 最赚路径\n\n"
    by_pnl = sorted(paths, key=lambda p: _safe_float(p.get("total_pnl")), reverse=True)
    for p in by_pnl[:5]:
        report += f"- **{p.get('path_id','?')}** ({p.get('stock_name','')}) — {p.get('trade_count',0)}笔, PnL={_safe_float(p.get('total_pnl')):+,.0f}, WR={_safe_float(p.get('win_rate')):.1f}%, 类型={p.get('path_type','?')}\n"

    report += "\n### TOP5 最亏路径\n\n"
    for p in by_pnl[-5:]:
        report += f"- **{p.get('path_id','?')}** ({p.get('stock_name','')}) — {p.get('trade_count',0)}笔, PnL={_safe_float(p.get('total_pnl')):+,.0f}, WR={_safe_float(p.get('win_rate')):.1f}%, 类型={p.get('path_type','?')}\n"

    # 行为预警
    report += "\n## 四、行为预警\n\n"
    high_imp_paths = [p for p in paths if _safe_float(p.get("impulsive_rate")) > 50]
    high_revenge_paths = [p for p in paths if _safe_float(p.get("revenge_trade_rate")) > 30]
    cost_avg_paths = [p for p in paths if p.get("is_cost_averaging")]
    high_dd_paths = [p for p in paths if _safe_float(p.get("max_drawdown")) > 50]

    report += f"- 高冲动率(>50%)路径: **{len(high_imp_paths)}**条\n"
    report += f"- 高报复性(>30%)路径: **{len(high_revenge_paths)}**条\n"
    report += f"- 摊平加仓路径: **{len(cost_avg_paths)}**条\n"
    report += f"- 高回撤(>50%)路径: **{len(high_dd_paths)}**条\n"

    if cost_avg_paths:
        report += "\n**摊平路径详情:**\n"
        for p in cost_avg_paths:
            report += f"  - {p.get('path_id','?')} — {p.get('trade_count',0)}笔, PnL={_safe_float(p.get('total_pnl')):+,.0f}, 回撤={_safe_float(p.get('max_drawdown')):.1f}%\n"

    # 免责声明
    report += """
---

## 免责声明

- 本报告基于交易记录自动生成，仅供参考，不构成投资建议
- Wilson CI 为 95% 置信区间，⭐ 标注表示样本不足(n<30)
- Cohen's d 效应量: |d|<0.2 忽略, 0.2-0.5 小, 0.5-0.8 中, >0.8 大
- 数据来源: trade_audit + trade_path_summary (MySQL)
"""

    return report


def save_report_to_obsidian(report: str) -> str:
    """保存报告到 Obsidian Vault"""
    vault_path = os.path.expanduser("/mnt/c/Users/John Cheng/Documents/Obsidian Vault")
    if not os.path.exists(vault_path):
        vault_path = os.path.expanduser("~/Documents/Obsidian Vault")

    out_dir = os.path.join(vault_path, "mystocks", "复盘", "交易路径分析")
    os.makedirs(out_dir, exist_ok=True)

    now = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(out_dir, f"交叉分析报告_{now}.md")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    return out_path


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="交易路径交叉分析")
    parser.add_argument("--no-save", action="store_true", help="不保存到Obsidian，只打印")
    args = parser.parse_args()

    report = generate_report()

    if args.no_save:
        print(report)
    else:
        out_path = save_report_to_obsidian(report)
        print(f"[交叉分析] 报告已保存: {out_path}")
        # 同时打印摘要
        lines = report.split("\n")
        for line in lines:
            if line.startswith("|") or line.startswith("#") or line.startswith("- **") or line.startswith(">"):
                print(line)
