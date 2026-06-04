#!/usr/bin/env python3
"""
V4 6维15分评分引擎 — 科学复盘体系
基于审核通过的V4升级方案实施

用法:
  MYSQL_PWD=xxx python3 audit_v4_scorer.py --validate 50    # 先跑50笔验证
  MYSQL_PWD=xxx python3 audit_v4_scorer.py --all             # 全量363笔
  MYSQL_PWD=xxx python3 audit_v4_scorer.py --all --force     # 强制重算全部
"""

import os
import sys
import argparse
import yaml
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("v4_scorer")

# ─── 配置加载 ─────────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "review_config.yaml")
_v4_config = None

def load_v4_config():
    """加载V4配置段"""
    global _v4_config
    with open(_CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    _v4_config = cfg.get("v4_scoring", {})
    if not _v4_config:
        log.warning("review_config.yaml 中无 v4_scoring 配置段，使用默认值")
        _v4_config = {}
    return _v4_config

def cfg(key, default=None):
    """获取V4配置值"""
    if _v4_config is None:
        load_v4_config()
    return _v4_config.get(key, default)


# ─── 辅助函数 ─────────────────────────────────────────────

def _safe_float(val, default=0.0):
    """安全转float"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _is_trend_up(stk_trend):
    """判断 stk_trend 是否为上升趋势"""
    return stk_trend in ("bull", "strong_up", "up")


def _is_trend_down(stk_trend):
    """判断 stk_trend 是否为下降趋势"""
    return stk_trend in ("bear", "strong_down", "down")


# ─── 1. 入场时机 (0-3分) ─────────────────────────────────

def score_entry_timing(trade):
    """
    3项计数法: BOLL位置(1) + 趋势向上(1) + 未追高(1)
    惩罚: 追高+逆势 → 直接0分
    """
    boll_pctb = _safe_float(trade.get("stk_boll_pctb"))  # 0-100
    stk_trend = trade.get("stk_trend", "") or ""
    buy_price = _safe_float(trade.get("buy_price"))
    # open price: 使用stk_boll_pctb>50近似追高, 或用chase_high_threshold
    # 这里用BOLL位置判定追高: buy在BOLL上轨区(>80%)且趋势向下
    boll_above_mid = boll_pctb > 50.0 if boll_pctb >= 0 else False
    trend_up = _is_trend_up(stk_trend)
    # 追高: BOLL > 80% 且 买价偏离
    boll_upper = boll_pctb > 80.0
    is_chase = boll_upper and not trend_up  # BOLL高位+非上升趋势=追高

    score = 0
    if boll_above_mid:
        score += 1
    if trend_up:
        score += 1
    if not boll_upper:  # 非BOLL高位=没追高
        score += 1

    # 惩罚: BOLL极端高位(>95%) + 趋势向下
    if boll_pctb > 95.0 and _is_trend_down(stk_trend):
        return 0

    return min(score, 3)


# ─── 2. 入场质量 (0-3分) ─────────────────────────────────

def score_entry_quality(trade):
    """
    3项计数法: 买后1h上涨(1) + K线内位置好(1) + 量比正常(1)
    惩罚: 买后1h大跌 → 直接0分
    无15分K线数据时满分降为2分
    """
    has_15m = trade.get("entry_boll_15m") is not None

    # 买后1小时趋势
    first_hour = trade.get("first_hour_trend", "") or ""
    if first_hour in ("continuous_up",):
        after_1h_ok = True
    elif first_hour in ("continuous_down", "v_shape"):
        after_1h_ok = False
    else:
        after_1h_ok = None  # neutral/None

    # K线内位置 (entry_price_position 0-1, <0.3为好位置)
    price_pos = _safe_float(trade.get("entry_price_position"))
    is_good_position = 0 < price_pos < 0.3 if price_pos > 0 else None

    # 量比 (entry_vol_ratio_15m)
    vol_ratio = _safe_float(trade.get("entry_vol_ratio_15m"))
    volume_ok = vol_ratio > 1.0 if vol_ratio > 0 else None

    # 惩罚: 买后大跌 (连续下跌)
    if first_hour == "continuous_down":
        return 0

    if not has_15m:
        # 无15分K线: 用日线近似，满分降为2
        score = 0
        if after_1h_ok is True:
            score += 1
        if volume_ok is True:
            score += 1
        return min(score, 2)

    score = 0
    if after_1h_ok is True:
        score += 1
    if is_good_position is True:
        score += 1
    if volume_ok is True:
        score += 1

    return min(score, 3)


# ─── 3. 卖出判定 (9种verdict) ─────────────────────────────

def get_sell_verdict_v4(trade):
    """
    9种verdict互斥优先级判定
    返回: (verdict_str, exit_timing_score)
    """
    sell_price = _safe_float(trade.get("sell_price"))
    buy_price = _safe_float(trade.get("buy_price"))
    pnl_rate = _safe_float(trade.get("pnl_rate"))
    post5_low = _safe_float(trade.get("post5_low"))
    post5_high = _safe_float(trade.get("post5_high"))
    post5_chg = _safe_float(trade.get("post5_chg"))
    post20_chg = _safe_float(trade.get("post20_chg"))
    hold_days = _safe_float(trade.get("hold_days"))

    # 判定盈亏
    is_profit = pnl_rate > 0

    # 辅助: 是否卖在5日最低附近
    def at_low():
        return post5_low > 0 and sell_price <= post5_low * 1.01

    # 辅助: 是否卖在5日最高附近
    def at_high():
        return post5_high > 0 and sell_price >= post5_high * 0.99

    # 数据不足检查
    if post5_low <= 0 and post5_high <= 0:
        return "unknown", 1

    # ── 优先级判定 ──

    # 1. perfect_stop: 亏损 + 卖在最低附近 (V4.1: 降至2分，虽止损精准但买入已失败)
    if not is_profit and at_low():
        return "perfect_stop", 2

    # 2. panic_sell: 亏损 + 卖在最低 + 卖后暴跌
    if not is_profit and at_low() and post5_chg < -3:
        return "panic_sell", 0

    # 3. discipline_sell: 盈利 + (持仓>=20天 或 盈利>=15%)
    if is_profit and (hold_days >= 20 or pnl_rate >= 15):
        return "discipline_sell", 3

    # 4. good_profit: 盈利 + 卖后跌
    if is_profit and post5_chg < 0:
        return "good_profit", 2

    # 5. nice_catch: 盈利 + 卖在最高附近
    if is_profit and at_high():
        return "nice_catch", 3

    # 6. late_stop: 亏损 + 卖后继续跌>3%
    if not is_profit and post5_chg < -3:
        return "late_stop", 0

    # 7. missed_profit: 盈利 + 卖后20日涨>8%
    if is_profit and post20_chg > 8:
        return "missed_profit", 0

    # 8. normal
    return "normal", 1


# ─── 4. 风控执行 (0-2分) ─────────────────────────────────

def score_risk_mgmt(trade):
    """
    V4.1: 风控能力评估(非运气评估)
    2项核心:
    - 亏损控制: 盈利交易满分, 亏损<3%=好(1), 亏损3-8%=一般(0.5→1分), 亏损>8%=差(0)
    - 回撤控制: intra_drawdown < 5% (但亏损+回撤小 = 自然止损，不算能力)
    
    关键改变: 盈利交易回撤小算能力; 亏损交易回撤小是"运气"不算能力
    """
    max_price = _safe_float(trade.get("max_price_hold"))
    sell_price = _safe_float(trade.get("sell_price"))
    pnl_rate = _safe_float(trade.get("pnl_rate"))

    # intra_drawdown
    if max_price > 0 and sell_price > 0 and max_price > sell_price:
        dd = 1.0 - sell_price / max_price
    else:
        dd = 0.0

    if pnl_rate > 0:
        # 盈利交易: 回撤小 = 持仓管理能力强
        if dd < 0.03:
            return 2
        elif dd < 0.08:
            return 1
        else:
            return 0
    else:
        # 亏损交易: 评估止损能力(非运气)
        # 小亏损(<3%)可能只是正常波动, 给1分
        # 大亏损(>8%)说明没有风控, 给0分
        if pnl_rate > -3.0:
            return 1
        else:
            return 0


# ─── 5. 行为纪律 (0-2分) ─────────────────────────────────

def generate_behavior_tags(trade, all_trades_by_date=None):
    """
    生成行为标签列表，返回: (tags_list, behavior_score)
    """
    tags = []

    buy_price = _safe_float(trade.get("buy_price"))
    stk_boll_pctb = _safe_float(trade.get("stk_boll_pctb"))
    stk_trend = trade.get("stk_trend", "") or ""
    pnl_rate = _safe_float(trade.get("pnl_rate"))
    position_ratio = _safe_float(trade.get("position_ratio"))
    hold_days = _safe_float(trade.get("hold_days"))
    is_impulsive = trade.get("is_impulsive")
    consecutive_losses = _safe_float(trade.get("consecutive_losses"))
    trades_same_day = _safe_float(trade.get("trades_same_day"))

    # 追高: BOLL > 80% 且 非上升趋势
    if stk_boll_pctb > 80 and not _is_trend_up(stk_trend):
        tags.append("追高")

    # 抄底: BOLL < 20% 且 下降趋势
    if stk_boll_pctb < 20 and _is_trend_down(stk_trend):
        tags.append("抄底")

    # V4.1冲动: 仅用"硬信号"——连亏>=4笔 或 同日>=4笔
    # 去掉is_impulsive(82.9%太宽，V3标记逻辑对历史数据过敏感)
    # 去掉单独的is_impulsive=1，除非同时有连亏/同日信号
    impulsive_hard = False
    if consecutive_losses >= 4:
        impulsive_hard = True
    if trades_same_day >= 4:
        impulsive_hard = True
    # is_impulsive + (连亏>=2 或 同日>=2) = 冲动
    if is_impulsive and (consecutive_losses >= 2 or trades_same_day >= 2):
        impulsive_hard = True
    if impulsive_hard:
        tags.append("冲动")

    # 重仓: position_ratio > 15%
    if position_ratio > 15:
        tags.append("重仓")

    # BOLL极端: <5% 或 >95% (从10/90收窄, 因BOLL%B呈U型分布)
    if stk_boll_pctb < 5 or stk_boll_pctb > 95:
        tags.append("BOLL极端")

    # 过早卖出: missed_profit
    verdict = trade.get("_verdict_v4", "")
    if verdict == "missed_profit":
        tags.append("过早卖出")

    # 过晚止损: late_stop / panic_sell
    if verdict in ("late_stop", "panic_sell"):
        tags.append("过晚止损")

    # 摊平: 无法从单笔数据判断，需要路径信息(暂跳过)

    # 报复性交易: 需要上一笔信息(暂跳过)

    # 计算behavior_score
    negative_tags = [t for t in tags if t in ("追高", "抄底", "冲动", "摊平", "报复",
                                               "过早卖出", "过晚止损", "重仓", "BOLL极端")]
    cnt = len(negative_tags)
    if cnt == 0:
        behavior_score = 2
    elif cnt == 1:
        behavior_score = 1
    else:
        behavior_score = 0

    return tags, behavior_score


# ─── 6. 交易效率 (0-2分) ─────────────────────────────────

def score_efficiency(trade):
    """
    盈利: 盈亏比合理(1) + 持仓效率>0.2%/天(1)
    亏损: 亏损幅度<3% 或 max_drawdown<5% → 1分, 否则0分
    """
    pnl_rate = _safe_float(trade.get("pnl_rate"))
    hold_days = _safe_float(trade.get("hold_days"), 1)
    max_price = _safe_float(trade.get("max_price_hold"))
    sell_price = _safe_float(trade.get("sell_price"))

    if pnl_rate > 0:
        # 盈利交易
        # 盈亏比合理: max_drawdown < 3% 且 pnl > 5%
        if max_price > 0 and max_price > sell_price:
            dd_pct = (1.0 - sell_price / max_price) * 100
        else:
            dd_pct = 0.0
        rr_ok = dd_pct < 3.0 and pnl_rate > 5.0

        # 持仓效率
        if hold_days > 0:
            daily_return = pnl_rate / hold_days
        else:
            daily_return = pnl_rate
        eff_ok = daily_return > 0.2

        if rr_ok and eff_ok:
            return 2
        elif rr_ok or eff_ok:
            return 1
        else:
            return 0
    else:
        # 亏损交易: 最高1分
        if pnl_rate > -3.0:
            return 1
        if max_price > 0 and sell_price > 0:
            dd_pct = (1.0 - sell_price / max_price) * 100
            if dd_pct < 5.0:
                return 1
        return 0


# ─── 六级分类 ──────────────────────────────────────────────

def classify_grade(total_score_v4, pnl_rate):
    """
    六级分类 + 子分类
    A: >=12 + 盈利
    B: >=9 + 盈利
    C: <9 + 盈利
    D: >=9 + 亏损
    E: 6-8 + 亏损
    F: <6 + 亏损
    """
    is_profit = pnl_rate > 0

    if is_profit:
        if total_score_v4 >= 12:
            return "A", None
        elif total_score_v4 >= 9:
            return "B", None
        else:
            return "C", None
    else:
        if total_score_v4 >= 9:
            return "D", None
        elif total_score_v4 >= 6:
            return "E", None  # E1/E2需要具体维度数据
        else:
            return "F", None  # F1/F2/F3需要具体维度数据


def classify_sub_grade(grade, scores, pnl_rate):
    """
    E/F级子分类
    F1: entry_timing + entry_quality 都<=1
    F2: risk_mgmt=0 且 亏损>10%
    F3: behavior=0 且 连亏
    E1: exit_timing<=1, 其他尚可
    E2: risk_mgmt=1, 单笔亏5-10%
    """
    if grade == "F":
        if scores.get("entry_timing", 0) <= 1 and scores.get("entry_quality", 0) <= 1:
            return "F1"
        if scores.get("risk_mgmt", 0) == 0 and pnl_rate < -10:
            return "F2"
        if scores.get("behavior", 0) == 0:
            return "F3"
        return None  # 默认F
    elif grade == "E":
        if scores.get("exit_timing", 0) <= 1:
            return "E1"
        if scores.get("risk_mgmt", 0) <= 1 and pnl_rate < -5:
            return "E2"
        return None  # 默认E
    return None


# ─── 量化指标 ──────────────────────────────────────────────

def calc_quantitative_metrics(trade):
    """
    计算4项量化指标
    """
    pnl_rate = _safe_float(trade.get("pnl_rate"))
    hold_days = _safe_float(trade.get("hold_days"), 1)
    sell_price = _safe_float(trade.get("sell_price"))
    max_price = _safe_float(trade.get("max_price_hold"))
    post20_chg = _safe_float(trade.get("post20_chg"))

    # intra_drawdown
    if max_price > 0 and sell_price > 0 and max_price > sell_price:
        intra_dd = 1.0 - sell_price / max_price
    else:
        intra_dd = 0.0

    # risk_adjusted_return (防除零)
    dd_safe = max(intra_dd, 0.01)
    risk_adj_return = pnl_rate / dd_safe if dd_safe > 0 else 0.0

    # hold_efficiency
    hold_eff = pnl_rate / hold_days if hold_days > 0 else None

    # opportunity_cost
    opp_cost = post20_chg - pnl_rate

    return {
        "intra_drawdown": round(intra_dd, 4),
        "risk_adjusted_return": round(risk_adj_return, 4),
        "hold_efficiency": round(hold_eff, 4) if hold_eff is not None else None,
        "opportunity_cost": round(opp_cost, 4),
    }


# ─── 主评分函数 ──────────────────────────────────────────────

def score_trade_v4(trade):
    """
    对单笔交易进行V4评分
    返回: dict with all V4 fields
    """
    # 1. 入场时机 (0-3)
    entry_timing = score_entry_timing(trade)

    # 2. 入场质量 (0-3)
    entry_quality = score_entry_quality(trade)

    # 3. 卖出判定 + 卖出时机得分
    verdict, exit_timing = get_sell_verdict_v4(trade)
    trade["_verdict_v4"] = verdict  # 传给behavior tags

    # 4. 风控执行 (0-2)
    risk_mgmt = score_risk_mgmt(trade)

    # 5. 行为标签 + 行为纪律得分
    tags, behavior = generate_behavior_tags(trade)

    # 6. 交易效率 (0-2)
    efficiency = score_efficiency(trade)

    # 总分
    total = entry_timing + entry_quality + exit_timing + risk_mgmt + behavior + efficiency

    # pnl_rate
    pnl_rate = _safe_float(trade.get("pnl_rate"))

    # 六级分类
    grade, _ = classify_grade(total, pnl_rate)

    # 维度分数dict
    scores = {
        "entry_timing": entry_timing,
        "entry_quality": entry_quality,
        "exit_timing": exit_timing,
        "risk_mgmt": risk_mgmt,
        "behavior": behavior,
        "efficiency": efficiency,
    }

    # 子分类
    sub_grade = classify_sub_grade(grade, scores, pnl_rate)

    # 量化指标
    quant = calc_quantitative_metrics(trade)

    return {
        "total_score_v4": total,
        "entry_timing_score": entry_timing,
        "entry_quality_score": entry_quality,
        "exit_timing_score": exit_timing,
        "risk_mgmt_score": risk_mgmt,
        "behavior_score": behavior,
        "efficiency_score": efficiency,
        "grade_v4": grade,
        "grade_sub": sub_grade,
        "sell_verdict_v4": verdict,
        "behavior_tags": ",".join(tags) if tags else None,
        **quant,
    }


# ─── 批量评分 + MySQL写入 ──────────────────────────────────

def batch_score_v4(limit=None, force=False):
    """
    批量V4评分
    limit: 限制笔数(用于验证)
    force: 强制重算已有V4数据的记录
    """
    import pymysql

    pwd = os.environ.get("MYSQL_PWD", "")
    conn = pymysql.connect(
        host="192.168.123.104", port=3306, user="root",
        password=pwd, database="hermes", charset="utf8mb4"
    )
    cur = conn.cursor()

    # 读取2026年前的交易
    where = "sell_date < '2026-01-01'"
    if not force:
        where += " AND total_score_v4 IS NULL"
    sql = """
        SELECT id, stock_code, stock_name, buy_date, sell_date, buy_price, sell_price,
               hold_days, pnl_rate, realized_pnl, position_ratio,
               stk_boll_pctb, stk_trend, stk_vol_ratio, stk_atr14, stk_rsi6,
               max_price_hold, min_price_hold, is_impulsive, is_profit,
               post5_low, post5_high, post5_chg, post20_chg,
               entry_boll_15m, entry_price_position, entry_vol_ratio_15m,
               entry_trend_15m, first_hour_trend, sell_verdict,
               consecutive_losses, trades_same_day
        FROM trade_audit
        WHERE %s
        ORDER BY buy_date
    """ % where

    if limit:
        sql += " LIMIT %d" % limit

    cur.execute(sql)
    rows = cur.fetchall()
    columns = [d[0] for d in cur.description]
    trades = [dict(zip(columns, r)) for r in rows]

    print("待评分交易: %d 笔" % len(trades))
    if not trades:
        print("无待处理记录 (使用 --force 重算已有数据)")
        conn.close()
        return

    # 逐笔评分
    update_sql = """
        UPDATE trade_audit SET
            total_score_v4 = %s,
            entry_timing_score = %s,
            entry_quality_score = %s,
            exit_timing_score = %s,
            risk_mgmt_score = %s,
            behavior_score = %s,
            efficiency_score = %s,
            grade_v4 = %s,
            grade_sub = %s,
            sell_verdict_v4 = %s,
            risk_adjusted_return = %s,
            hold_efficiency = %s,
            opportunity_cost = %s,
            intra_drawdown = %s,
            behavior_tags = %s
        WHERE id = %s
    """

    results = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
    verdict_dist = {}
    scored = 0
    errors = 0

    for t in trades:
        try:
            v4 = score_trade_v4(t)
            cur.execute(update_sql, (
                v4["total_score_v4"],
                v4["entry_timing_score"],
                v4["entry_quality_score"],
                v4["exit_timing_score"],
                v4["risk_mgmt_score"],
                v4["behavior_score"],
                v4["efficiency_score"],
                v4["grade_v4"],
                v4["grade_sub"],
                v4["sell_verdict_v4"],
                v4["risk_adjusted_return"],
                v4["hold_efficiency"],
                v4["opportunity_cost"],
                v4["intra_drawdown"],
                v4["behavior_tags"],
                t["id"],
            ))
            results[v4["grade_v4"]] = results.get(v4["grade_v4"], 0) + 1
            v = v4["sell_verdict_v4"]
            verdict_dist[v] = verdict_dist.get(v, 0) + 1
            scored += 1
        except Exception as e:
            log.error("id=%s %s: %s", t.get("id"), t.get("stock_code"), e)
            errors += 1

    conn.commit()

    # 打印统计
    print("\n=== V4评分结果 ===")
    print("成功: %d, 失败: %d" % (scored, errors))
    print("")
    print("六级分类分布:")
    for g in "ABCDEF":
        cnt = results.get(g, 0)
        pct = cnt / max(scored, 1) * 100
        print("  %s: %3d 笔 (%5.1f%%)" % (g, cnt, pct))

    print("")
    print("sell_verdict_v4分布:")
    for v in sorted(verdict_dist.keys()):
        print("  %-20s %3d" % (v, verdict_dist[v]))

    # 评分分布
    cur.execute("""
        SELECT MIN(total_score_v4), MAX(total_score_v4), AVG(total_score_v4)
        FROM trade_audit WHERE sell_date < '2026-01-01' AND total_score_v4 IS NOT NULL
    """)
    row = cur.fetchone()
    print("")
    print("V4总分: min=%d, max=%d, avg=%.2f (满分15)" % (row[0], row[1], float(row[2])))

    # 维度均分
    dims = ["entry_timing_score", "entry_quality_score", "exit_timing_score",
            "risk_mgmt_score", "behavior_score", "efficiency_score"]
    max_scores = [3, 3, 3, 2, 2, 2]
    print("")
    print("维度均分 (shortfall_report):")
    print("  %-25s %5s %5s %5s %5s" % ("维度", "满分", "均分", "扣分", "扣分率"))
    for dim, mx in zip(dims, max_scores):
        cur.execute("SELECT AVG(%s) FROM trade_audit WHERE sell_date < '2026-01-01' AND %s IS NOT NULL" % (dim, dim))
        avg = float(cur.fetchone()[0])
        deduct = mx - avg
        deduct_rate = deduct / mx * 100
        print("  %-25s %5d %5.2f %5.2f %5.1f%%" % (dim, mx, avg, deduct, deduct_rate))

    conn.close()
    return scored


# ─── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V4 6维15分评分引擎")
    parser.add_argument("--validate", type=int, metavar="N", help="验证模式: 只跑N笔")
    parser.add_argument("--all", action="store_true", help="全量363笔评分")
    parser.add_argument("--force", action="store_true", help="强制重算已有V4数据的记录")
    parser.add_argument("--dry-run", action="store_true", help="只评分不写入")
    parser.add_argument("--report", action="store_true", help="生成V4.1综合报告(调用report_v4.py)")
    parser.add_argument("--report-output", type=str, metavar="PATH", help="报告输出路径(配合--report)")
    args = parser.parse_args()

    load_v4_config()

    if args.report:
        from report_v4 import generate_report
        import pathlib
        output = args.report_output
        if not output:
            vault = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"
            output = f"{vault}/mynotes/学习材料/复盘方法/V4.1优化报告-perfect_stop与E2分析.md"
        n = generate_report(output_path=output)
        print(f"报告生成完毕: {n} 行")
    elif args.validate:
        print("验证模式: 跑 %d 笔" % args.validate)
        batch_score_v4(limit=args.validate, force=args.force)
    elif args.all:
        print("全量模式: 363笔")
        batch_score_v4(force=args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
