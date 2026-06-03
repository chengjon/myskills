#!/usr/bin/env python3
"""
交易复盘评分引擎 + 复盘卡生成器
- 事前评分引擎(6维度×1-5分=30分制)
- 事后评分引擎(5维度×1-5分=25分制)
- 检测函数(追高/抄底/冲动/异常/成本)
- 复盘卡生成器(draft/update/daily)

依赖: fetch_market_data.py(同目录), review_config.yaml, requests, pyyaml
"""

import argparse
import json
import math
import os
import re
import sys
import yaml
from datetime import date, datetime, timedelta
from typing import Optional

# 同目录导入
sys.path.insert(0, os.path.dirname(__file__))
from fetch_market_data import (
    load_config, sina_code, safe_float,
    fetch_kline, fetch_realtime, fetch_realtime_batch,
    calc_ma, calc_atr, calc_macd, calc_rsi, calc_boll, calc_volume_ratio,
    fetch_sectors, find_sector_change, fetch_indices,
    clear_kline_cache,
    fetch_pre_snapshot, fetch_post_validation,
)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "review_config.yaml")
VAULT = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"

# 行业映射(与daily-stock skill一致)
# 优先从配置文件读取，降级使用硬编码
_DEF_INDUSTRY_MAP = {
    "000537": "电力", "000887": "汽车零部件", "000938": "ICT/服务器",
    "001896": "电力", "002077": "半导体封测", "002195": "互联网/AI",
    "002196": "IT服务", "002342": "机械制造", "002774": "电梯制造",
    "600172": "超硬材料", "600379": "电真空器件", "601138": "电子制造(EMS)",
    "601991": "电力", "688403": "半导体封测",
}

# 行业关键词映射(用于东财行业列表模糊匹配)
_DEF_INDUSTRY_KEYWORDS = {
    "电力": ["电力"],
    "汽车零部件": ["汽车"],
    "ICT/服务器": ["电子信息", "电子器件", "通信"],
    "半导体封测": ["电子器件", "电子信息", "半导体"],
    "互联网/AI": ["电子信息", "互联网", "软件"],
    "IT服务": ["电子信息", "软件", "计算机"],
    "机械制造": ["机械"],
    "电梯制造": ["机械", "专用设备"],
    "超硬材料": ["有色金属", "新材料", "矿物制品"],
    "电真空器件": ["电子器件", "电子信息"],
    "电子制造(EMS)": ["电子器件", "电子信息", "制造业"],
}

_DEF_CONCEPT_MAP = {
    "000537": ["绿电", "电改", "新能源"], "000887": ["新能源汽车", "空气悬挂", "密封件"],
    "000938": ["AI算力", "云计算", "新华三", "服务器"], "001896": ["火电", "电改", "河南国资"],
    "002077": ["半导体封测", "Chiplet", "先进封装"], "002195": ["AI大模型", "互联网", "AI应用"],
    "002196": ["IT服务", "PC", "信创"], "002342": ["索具", "基建", "一带一路"],
    "002774": ["电梯", "旧改", "维保"], "600172": ["超硬材料", "人造钻石", "工业金刚石"],
    "600379": ["真空灭弧室", "特高压", "智能电网"], "601138": ["AI服务器", "EMS", "云计算", "苹果产业链"],
    "601991": ["火电", "电改", "新能源转型"], "688403": ["半导体封测", "先进封装", "Chiplet"],
}


def _get_industry_map() -> dict:
    """行业映射：优先配置文件，降级硬编码"""
    cfg = load_config(CONFIG_PATH)
    return cfg.get("industry_map", _DEF_INDUSTRY_MAP)


def _get_industry_keywords() -> dict:
    """行业关键词映射：优先配置文件，降级硬编码"""
    cfg = load_config(CONFIG_PATH)
    return cfg.get("industry_keywords", _DEF_INDUSTRY_KEYWORDS)


def _get_concept_map() -> dict:
    """概念映射：优先配置文件，降级硬编码"""
    cfg = load_config(CONFIG_PATH)
    return cfg.get("concept_map", _DEF_CONCEPT_MAP)


# ============================================================
# 工具函数
# ============================================================

def score_label_pre(total: int) -> str:
    """事前评分标签"""
    cfg = load_config(CONFIG_PATH)
    excellent = cfg.get("pre_excellent", 24)
    good = cfg.get("pre_good", 18)
    if total >= excellent:
        return "🟢优质"
    elif total >= good:
        return "🟡一般"
    else:
        return "🔴问题"


def score_label_post(total: int) -> str:
    """事后评分标签"""
    cfg = load_config(CONFIG_PATH)
    excellent = cfg.get("post_excellent", 20)
    good = cfg.get("post_good", 13)
    if total >= excellent:
        return "✅验证成功"
    elif total >= good:
        return "⚠️中性"
    else:
        return "❌验证失败"


def combo_label(pre_total: int, post_total: int) -> str:
    """综合判定(九宫格)"""
    pre_l = score_label_pre(pre_total)
    post_l = score_label_post(post_total)
    matrix = {
        ("🟢优质", "✅验证成功"): "🏆正确决策，可复用",
        ("🟢优质", "⚠️中性"):   "🤔好决策运气差，坚持",
        ("🟢优质", "❌验证失败"): "🔍好决策为何失败？",
        ("🟡一般", "✅验证成功"): "😅决策一般运气好",
        ("🟡一般", "⚠️中性"):   "😐平庸交易，减少",
        ("🟡一般", "❌验证失败"): "⚠️双重问题，需反思",
        ("🔴问题", "✅验证成功"): "🚫危险盈利，不可复用",
        ("🔴问题", "⚠️中性"):   "🔴问题交易，止损出场",
        ("🔴问题", "❌验证失败"): "❌典型错误，录入教训库",
    }
    return matrix.get((pre_l, post_l), "未知")


# ============================================================
# 检测函数
# ============================================================

def detect_chase_high(buy_price: float, rt: dict, config: dict = None) -> dict:
    """追高检测"""
    config = config or load_config(CONFIG_PATH)
    threshold = config.get("chase_high_threshold", 0.05)
    base_key = config.get("chase_high_base", "open")
    base_price = rt.get("open") if base_key == "open" else rt.get("prev_close")
    if not base_price or base_price <= 0:
        return {"is_chase": False, "detail": "基准价缺失"}
    ratio = (buy_price - base_price) / base_price
    is_chase = ratio >= threshold
    return {
        "is_chase": is_chase,
        "ratio": round(ratio * 100, 2),
        "threshold": threshold * 100,
        "detail": f"买入{buy_price} vs {base_key}价{base_price}, 偏离{ratio*100:+.2f}%"
    }


def detect_bottom_fishing(buy_price: float, rt: dict, config: dict = None) -> dict:
    """抄底检测"""
    config = config or load_config(CONFIG_PATH)
    threshold = config.get("bottom_fishing_threshold", -0.03)
    prev_close = rt.get("prev_close", 0)
    if prev_close <= 0:
        return {"is_bottom": False, "detail": "昨收缺失"}
    change_pct = (buy_price - prev_close) / prev_close
    is_bottom = change_pct <= threshold
    return {
        "is_bottom": is_bottom,
        "change_pct": round(change_pct * 100, 2),
        "threshold": threshold * 100,
        "detail": f"买入时涨跌{change_pct*100:+.2f}%, 阈值{threshold*100}%"
    }


def detect_impulsive(has_plan: bool, config: dict = None) -> dict:
    """冲动交易检测"""
    config = config or load_config(CONFIG_PATH)
    rule = config.get("impulsive_trade_rule", True)
    is_impulsive = rule and not has_plan
    auto = config.get("impulsive_auto_score", {})
    return {
        "is_impulsive": is_impulsive,
        "auto_discipline": auto.get("discipline", 1) if is_impulsive else None,
        "auto_risk": auto.get("risk", 2) if is_impulsive else None,
        "detail": "无交易计划，标记冲动交易" if is_impulsive else ""
    }


def check_force_review(trade_info: dict, config: dict = None) -> dict:
    """异常交易强制复盘检测"""
    config = config or load_config(CONFIG_PATH)
    conditions = config.get("force_review_conditions", {})
    triggers = []
    if conditions.get("over_position") and trade_info.get("risk_ratio", 0) > config.get("max_single_risk", 0.02):
        triggers.append("超仓(单笔风险>{:.0f}%)".format(config.get("max_single_risk", 0.02) * 100))
    if conditions.get("no_stoploss") and not trade_info.get("stop_price"):
        triggers.append("无止损")
    overnight_threshold = conditions.get("overnight_heavy", 0.50)
    if isinstance(overnight_threshold, (int, float)) and trade_info.get("position_ratio", 0) > overnight_threshold:
        triggers.append(f"隔夜重仓(仓位>{overnight_threshold*100:.0f}%)")
    if conditions.get("reverse_heavy") and trade_info.get("market_down") and trade_info.get("position_ratio", 0) > 0.30:
        triggers.append("逆势重仓")
    if conditions.get("chase_high_no_plan") and trade_info.get("is_chase") and not trade_info.get("has_plan"):
        triggers.append("追高+无计划")
    if conditions.get("impulsive_trade") and trade_info.get("is_impulsive"):
        triggers.append("冲动交易")
    return {
        "force_review": len(triggers) > 0,
        "triggers": triggers,
    }


# ============================================================
# V3 核心判定函数 (四分法/顺势逆势/冲动增强/黑名单/错误枚举/反馈)
# ============================================================

# V3 错误分类枚举
ALLOWED_MISTAKES = {
    '入场过早', '入场过晚', '未等信号', '追高', '逆势抄底', '逆势追高',
    '未及时止盈', '止损不坚决', '无止损', '仓位过重', '行业集中',
    '连亏后冲动', '无计划交易', '卖飞后追回', '卖出过早', '卖出过晚',
    '无错(市场正常波动)',
}


def classify_stk_trend(indicators: dict) -> str:
    """
    从技术指标判定个股趋势方向(V3用)
    bull: MA5>MA10>MA20 且 MA20>MA60
    bear: MA5<MA10<MA20 且 MA20<MA60
    sideways: 其他
    """
    ma5 = indicators.get("MA5")
    ma10 = indicators.get("MA10")
    ma20 = indicators.get("MA20")
    ma60 = indicators.get("MA60")

    if all(v is not None and v > 0 for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20 and ma60 and ma20 > ma60:
            return 'bull'
        if ma5 < ma10 < ma20 and ma60 and ma20 < ma60:
            return 'bear'
    return 'sideways'


def classify_mkt_trend(indices: dict, config: dict = None) -> str:
    """
    从三大指数判定大盘趋势方向(V3用)
    bull: ≥2个上涨(>0.5%)
    bear: ≥2个下跌(<-0.5%)
    sideways: 其他
    """
    config = config or load_config(CONFIG_PATH)
    up_threshold = config.get("market_up_threshold", 0.5)
    down_threshold = config.get("market_down_threshold", -0.5)

    up_count = 0
    down_count = 0
    for name in ["上证", "深证", "创业板"]:
        idx = indices.get(name, {})
        chg = idx.get("change_pct", 0)
        if chg > up_threshold:
            up_count += 1
        elif chg < down_threshold:
            down_count += 1

    if up_count >= 2:
        return 'bull'
    if down_count >= 2:
        return 'bear'
    return 'sideways'


def calc_trade_direction(stk_trend: str, mkt_trend: str) -> str:
    """
    V3 顺势/逆势判定
    stk_trend/mkt_trend: 'bull'/'bear'/'sideways'
    返回: '顺势买入'/'轻逆势买入'/'强逆势买入'
    """
    if stk_trend == 'bull' and mkt_trend == 'bull':
        return '顺势买入'
    if stk_trend == 'bear' and mkt_trend == 'bear':
        return '强逆势买入'
    return '轻逆势买入'


def get_trade_category(stop_loss_set: int, position_rule: str,
                       trade_direction: str, is_profit: int) -> str:
    """
    V3 四分法：止损+仓位+顺势 → 规则内/外 × 盈/亏
    stop_loss_set: 1=有止损, 0=无止损
    position_rule: 'pass'/'exceed'/'critical'
    trade_direction: '顺势买入'/'轻逆势买入'/'强逆势买入'
    is_profit: 1=盈利, 0=亏损
    """
    rule_inside = (stop_loss_set == 1
                   and position_rule == 'pass'
                   and trade_direction == '顺势买入')
    if rule_inside and is_profit == 1:
        return '规则内盈利'
    elif rule_inside and is_profit == 0:
        return '规则内亏损'
    elif not rule_inside and is_profit == 1:
        return '规则外盈利'
    else:
        return '规则外亏损'


def detect_impulsive_v2(consecutive_losses: int, trades_same_day: int,
                        stop_loss_set: int, position_rule: str,
                        stk_atr_pctb: float) -> dict:
    """
    V3 冲动交易(增强版)：
    - 连亏≥3 → 冲动
    - 同日>3笔 → 冲动
    - 无止损+超仓 → 冲动
    - ATR历史分位>90% → 冲动(高波动追入)
    """
    triggers = []
    if consecutive_losses >= 3:
        triggers.append(f"连亏{consecutive_losses}笔")
    if trades_same_day > 3:
        triggers.append(f"同日{trades_same_day}笔")
    if stop_loss_set == 0 and position_rule != 'pass':
        triggers.append("无止损+超仓")
    if stk_atr_pctb > 90:
        triggers.append(f"ATR分位{stk_atr_pctb:.0f}%")

    is_impulsive = len(triggers) > 0
    impulsive_type = ",".join(triggers) if triggers else ""
    return {
        "is_impulsive": is_impulsive,
        "impulsive_type": impulsive_type,
    }


def check_blacklist(stock_code: str, db_conn=None) -> dict:
    """
    V3 黑名单判定(查MySQL历史)：
    - 该股累计亏损>15%
    - 该股亏损次数≥3
    - 该股规则外亏损≥2
    """
    if not db_conn:
        return {"in_blacklist": False, "reason": ""}

    # 延迟导入，避免非MySQL环境报错
    from trade_audit_sql import query_stock_history_stats

    stats = query_stock_history_stats(stock_code, db_conn)
    triggers = []
    if abs(stats.get("total_loss_pct", 0)) > 0.15:
        triggers.append(f"累计亏损{stats['total_loss_pct']:.1%}")
    if stats.get("loss_count", 0) >= 3:
        triggers.append(f"亏损{stats['loss_count']}次")
    if stats.get("outside_loss_count", 0) >= 2:
        triggers.append(f"规则外亏{stats['outside_loss_count']}次")

    in_blacklist = len(triggers) > 0
    return {
        "in_blacklist": in_blacklist,
        "reason": "; ".join(triggers),
    }


def infer_mistake_category(trade_info: dict, chase_detect: dict = None) -> str:
    """
    V3 自动推断错误分类
    优先级: 无止损 > 无计划 > 追高 > 逆势 > 连亏冲动 > 卖出过早 > 无错
    """
    stop_loss_set = trade_info.get("stop_loss_set", 0)
    has_plan = trade_info.get("has_plan", False)
    trade_direction = trade_info.get("trade_direction", "")
    is_profit = trade_info.get("is_profit", 0)
    consecutive_losses = trade_info.get("consecutive_losses", 0)
    sell_verdict = trade_info.get("sell_verdict", "")
    boll_pctb = trade_info.get("stk_boll_pctb", 50)
    chase = chase_detect or {}

    if stop_loss_set == 0:
        return '无止损'
    if not has_plan:
        return '无计划交易'
    if chase.get("is_chase") or chase.get("is_chase_high"):
        return '追高'
    if trade_direction == '强逆势买入' and is_profit == 0:
        if boll_pctb >= 70:
            return '逆势追高'
        return '逆势抄底'
    if consecutive_losses >= 3:
        return '连亏后冲动'
    if sell_verdict in ('missed_profit', 'late_stop'):
        return '卖出过早'
    # 规则内亏损+止损被触发 → 市场正常波动
    if is_profit == 0 and stop_loss_set == 1 and trade_direction == '顺势买入':
        return '无错(市场正常波动)'

    return ''  # 待人工标注


def calc_feedback_action(trade_category: str, total_score: float,
                         in_blacklist: bool, is_impulsive: bool) -> str:
    """
    V3 6级反馈: none/observe/plan_ready/exclude/blacklist/improve_template
    """
    if in_blacklist:
        return 'blacklist'
    if trade_category == '规则外亏损' and total_score < 5:
        return 'exclude'
    if trade_category == '规则外盈利':
        return 'observe'
    if is_impulsive and total_score < 6:
        return 'improve_template'
    if trade_category in ['规则内亏损', '规则内盈利'] and total_score >= 7:
        return 'plan_ready'
    return 'none'


def _sub_score(value: float, tiers: tuple = (0, 0.5, 1.0)) -> float:
    """子维度评分: 0/0.5/1.0 三档映射"""
    if value >= tiers[2]:
        return 1.0
    elif value >= tiers[1]:
        return 0.5
    return 0.0


def audit_score(trade_data: dict, config: dict = None) -> dict:
    """
    V3 4维10分制评分引擎
    入场(3) = 趋势(0-1) + 位置/信号(0-1) + 行业大盘(0-1)
    卖出(3) = 卖出时机(0-1) + 卖出原因(0-1) + 事后验证(0-1)
    纪律(2) = 有无计划(0-1) + 仓位合规(0-1)
    风控(2) = 止损设置(0-1) + 单笔风险(0-1)

    trade_data 需包含:
      indicators: dict (MA5/10/20/60, MACD_DIF/DEA/HIST, BOLL_*)
      stk_trend: str (bull/bear/sideways) — 由 classify_stk_trend() 生成
      mkt_trend: str (bull/bear/sideways) — 由 classify_mkt_trend() 生成
      boll_pctb: float (BOLL %B 0-100)
      is_chase: bool
      entry_signal: str (突破/回调/反转/金叉/放量/其他)
      sector_pct_rank: float (行业涨幅百分位 0-100)
      sell_reason: str
      sell_trigger: str (rule_triggered/subjective/emotional)
      sell_verdict: str (perfect_stop/good_profit/normal/late_stop/missed_profit/unknown)
      has_plan: bool
      position_rule: str (pass/exceed/critical)
      stop_loss_set: int (0/1)
      stop_loss_pct: float (止损幅度%)
      single_risk_pct: float (单笔风险占总资产%)
    """
    # ---- 入场评分 (3分) ----
    # 1) 趋势(0-1)
    indicators = trade_data.get("indicators", {})
    stk_trend = trade_data.get("stk_trend", "sideways")
    dif = indicators.get("MACD_DIF", 0) or 0
    dea = indicators.get("MACD_DEA", 0) or 0
    macd_bull = dif > dea

    if stk_trend == 'bull' and macd_bull:
        trend_sub = 1.0
    elif stk_trend == 'bull' or macd_bull:
        trend_sub = 0.5
    elif stk_trend == 'bear' and not macd_bull:
        trend_sub = 0.0
    else:
        trend_sub = 0.5

    # 2) 位置/信号(0-1)
    boll_pctb = trade_data.get("boll_pctb", 50)
    is_chase = trade_data.get("is_chase", False)
    entry_signal = trade_data.get("entry_signal", "")

    if is_chase or boll_pctb > 90:
        pos_signal_sub = 0.0
    elif boll_pctb >= 25 and boll_pctb <= 50 and entry_signal and entry_signal != "其他":
        pos_signal_sub = 1.0
    elif boll_pctb > 50 and boll_pctb <= 75:
        pos_signal_sub = 0.5
    elif not entry_signal or entry_signal == "其他":
        pos_signal_sub = 0.5
    else:
        pos_signal_sub = 0.5

    # 3) 行业大盘(0-1)
    mkt_trend = trade_data.get("mkt_trend", "sideways")
    sector_pct_rank = trade_data.get("sector_pct_rank", 50)  # 0=最好, 100=最差
    trade_dir = trade_data.get("trade_direction", "")

    if trade_dir == '顺势买入' and sector_pct_rank <= 30:
        sector_sub = 1.0
    elif trade_dir == '顺势买入' and sector_pct_rank <= 60:
        sector_sub = 0.8
    elif trade_dir == '轻逆势买入' and sector_pct_rank <= 40:
        sector_sub = 0.7
    elif trade_dir == '强逆势买入' and sector_pct_rank >= 70:
        sector_sub = 0.0
    elif trade_dir == '强逆势买入':
        sector_sub = 0.2
    elif trade_dir == '轻逆势买入' and sector_pct_rank >= 70:
        sector_sub = 0.3
    elif trade_dir == '轻逆势买入':
        sector_sub = 0.5
    elif sector_pct_rank <= 30:
        sector_sub = 0.7
    elif sector_pct_rank >= 70:
        sector_sub = 0.3
    else:
        sector_sub = 0.5

    entry_score = round(trend_sub + pos_signal_sub + sector_sub, 1)

    # ---- 卖出评分 (3分) ----
    # 1) 卖出时机(0-1)
    sell_reason = trade_data.get("sell_reason", "")
    if sell_reason in ("止损", "止盈", "目标价"):
        timing_sub = 1.0
    elif sell_reason in ("主观判断", "换股", "减仓"):
        timing_sub = 0.5
    else:
        timing_sub = 0.0  # 情绪化/恐慌/追回

    # 2) 卖出原因(0-1)
    sell_trigger = trade_data.get("sell_trigger", "subjective")
    trigger_map = {"rule_triggered": 1.0, "subjective": 0.5, "emotional": 0.0}
    reason_sub = trigger_map.get(sell_trigger, 0.5)

    # 3) 事后验证(0-1)
    sell_verdict = trade_data.get("sell_verdict", "normal")
    verdict_map = {
        "perfect_stop": 1.0, "good_profit": 0.8, "normal": 0.5,
        "late_stop": 0.2, "missed_profit": 0.0, "unknown": 0.5,
    }
    validation_sub = verdict_map.get(sell_verdict, 0.5)

    exit_score = round(timing_sub + reason_sub + validation_sub, 1)

    # ---- 纪律评分 (2分) ----
    # 1) 有无计划(0-1)
    has_plan = trade_data.get("has_plan", False)
    plan_sub = 1.0 if has_plan else 0.0

    # 2) 仓位合规(0-1)
    position_rule = trade_data.get("position_rule", "pass")
    if position_rule == 'pass':
        position_sub = 1.0
    elif position_rule == 'exceed':
        position_sub = 0.5
    else:  # critical
        position_sub = 0.0

    discipline_score = round(plan_sub + position_sub, 1)

    # ---- 风控评分 (2分) ----
    # 1) 止损设置(0-1)
    stop_loss_set = trade_data.get("stop_loss_set", 0)
    stop_loss_pct = trade_data.get("stop_loss_pct", 0)
    if config is None:
        config = load_config(CONFIG_PATH)
    scoring_cfg = config.get("scoring", {})
    stop_good_range = scoring_cfg.get("stop_loss_good_range", [3, 8])
    stop_wide = scoring_cfg.get("stop_loss_wide_threshold", 8)
    if stop_loss_set == 1 and stop_good_range[0] <= stop_loss_pct <= stop_good_range[1]:
        stop_sub = 1.0
    elif stop_loss_set == 1 and stop_loss_pct > stop_wide:
        stop_sub = 0.5  # 止损过宽
    elif stop_loss_set == 0 and trade_data.get("stk_atr_stop"):
        stop_sub = 0.5  # 无止损但有ATR参考
    else:
        stop_sub = 0.0

    # 2) 单笔风险(0-1)
    single_risk_pct = trade_data.get("single_risk_pct", 0)
    risk_good = scoring_cfg.get("single_risk_good", 2)
    risk_warn = scoring_cfg.get("single_risk_warn", 4)
    if single_risk_pct > 0 and single_risk_pct <= risk_good:
        risk_sub = 1.0
    elif single_risk_pct > risk_good and single_risk_pct <= risk_warn:
        risk_sub = 0.5
    else:
        risk_sub = 0.0

    risk_control_score = round(stop_sub + risk_sub, 1)

    # ---- 总分 ----
    total_score = round(entry_score + exit_score + discipline_score + risk_control_score, 1)
    # 封顶10
    total_score = min(10.0, total_score)

    return {
        "entry_score": entry_score,
        "exit_score": exit_score,
        "discipline_score": discipline_score,
        "risk_control_score": risk_control_score,
        "total_score": total_score,
        "entry_detail": f"趋势{trend_sub}/位置{pos_signal_sub}/行业大盘{sector_sub}",
        "exit_detail": f"时机{timing_sub}/原因{reason_sub}/事后验证{validation_sub}",
        "discipline_detail": f"计划{plan_sub}/仓位{position_sub}",
        "risk_control_detail": f"止损{stop_sub}/单笔风险{risk_sub}",
        "detail": {
            "trend_sub": trend_sub,
            "pos_signal_sub": pos_signal_sub,
            "sector_sub": sector_sub,
            "timing_sub": timing_sub,
            "reason_sub": reason_sub,
            "validation_sub": validation_sub,
            "plan_sub": plan_sub,
            "position_sub": position_sub,
            "stop_sub": stop_sub,
            "risk_sub": risk_sub,
        },
    }


def calc_sell_verdict(sell_price: float, post5_close: float = None,
                      post10_close: float = None, post20_high: float = None,
                      hold_period_max_price: float = None,
                      stop_price: float = 0, config: dict = None,
                      buy_price: float = 0) -> str:
    """
    V3 卖出审计判定 (6种)
    perfect_stop: 止损卖出(卖在止损价附近)
    good_profit:  卖出后5/10日继续下跌(卖出时机好)
    normal:       其他
    late_stop:    卖出后5日大跌(>5%)但不止损价(止损过晚)
    missed_profit:盈利交易卖出后20日内创新高(过早卖出错过了利润)
    unknown:      数据不足无法判定

    buy_price: 买入价(用于区分盈亏,missed_profit只在盈利交易中判定)
    """
    if sell_price <= 0:
        return 'unknown'

    # 数据不足判定
    if post5_close is None and post10_close is None:
        return 'unknown'

    # 配置读取
    if config is None:
        config = load_config(CONFIG_PATH)
    scoring_cfg = config.get("scoring", {})
    early_5d = scoring_cfg.get("sell_early_5d", 0.02)
    early_10d = scoring_cfg.get("sell_early_10d", 0.05)

    # perfect_stop: 止损价存在且卖出价在止损价附近(1%以内)
    if stop_price > 0 and sell_price <= stop_price * 1.01:
        return 'perfect_stop'

    # 区分盈亏: missed_profit只在盈利交易中判定
    is_profitable = (buy_price > 0 and sell_price > buy_price)

    # missed_profit: 盈利交易卖出后创新高(过早卖出)
    if is_profitable and hold_period_max_price and post20_high and post20_high > hold_period_max_price:
        return 'missed_profit'

    # good_profit: 卖出后5日和10日均低于卖出价
    if post5_close is not None and post10_close is not None:
        if post5_close < sell_price and post10_close < sell_price:
            return 'good_profit'

    # late_stop: 卖出后5日大跌(>5%), 说明止损过晚
    if post5_close is not None:
        if post5_close < sell_price * 0.95:
            return 'late_stop'

    return 'normal'


def _flatten_post_validation_for_update(post_validation: dict, days_list=None) -> dict:
    """把 fetch_post_validation(days_list=...) output 转成 trade_audit update fields."""
    days_list = days_list or [5, 10, 20, 60]
    data = {}
    for days in days_list:
        post = post_validation.get(f"post{days}")
        if isinstance(post, dict):
            if days == 60:
                data["post60_chg"] = post.get("chg")
            else:
                data[f"post{days}_close"] = post.get("close")
                data[f"post{days}_chg"] = post.get("chg")
                if days in (5, 20):
                    data[f"post{days}_high"] = post.get("high")
                    data[f"post{days}_low"] = post.get("low")
    if "post_new_high" in post_validation:
        data["post_new_high"] = post_validation.get("post_new_high")
    if "sell_verdict" in post_validation:
        data["sell_verdict"] = post_validation.get("sell_verdict")
    return data


def insert_audit_from_trade(trade: dict, db_conn=None, force: bool = False) -> dict:
    """
    V3 从交易记录生成完整审计并写入MySQL
    trade: 一笔已完成的交易记录，需包含:
      account, stock_code, stock_name, buy_date, buy_price, buy_shares, buy_amount,
      sell_date, sell_price, sell_shares, sell_amount, hold_days, realized_pnl,
      pnl_rate, total_fees, sell_reason, has_plan, stop_price, total_assets,
      position_ratio
    db_conn: MySQL连接(传则复用，None则自动创建并关闭)
    force: True=强制重写已有记录

    返回: {"audit_id": int, "record": dict, "status": str}
    """
    from trade_audit_sql import (
        get_conn, trade_exists, insert_audit, insert_signals,
        insert_audit_log, query_emotion_stats, validate_audit_record,
    )

    account = trade.get("account", "")
    stock_code = trade.get("stock_code", "")
    sell_date = trade.get("sell_date", "")
    sell_shares = trade.get("sell_shares", 0)
    buy_date = trade.get("buy_date", "")

    # 检查是否已存在(增量模式)
    auto_close = db_conn is None

    result = {"audit_id": 0, "record": {}, "status": ""}

    try:
        if trade.get("_needs_fifo"):
            raise ValueError("需要先通过 FIFO 适配层补齐买入日期/买价/盈亏后才能审计")

        if auto_close:
            from trade_audit_sql import _load_mysql_config as _sql_cfg
            import pymysql as _pymysql
            db_conn = _pymysql.connect(**_sql_cfg())

        # 增量检查
        if not force and trade_exists(db_conn, account, stock_code, buy_date, sell_date, sell_shares):
            result["status"] = "skipped_exists"
            return result

        # ---- 收集技术指标(入场环境 B组) ----
        config = load_config(CONFIG_PATH)
        indicators = {}
        stk_trend = "sideways"
        mkt_trend = "sideways"
        boll_pctb = 50.0
        sector_pct_rank = 50.0
        stk_atr_pctb = 0.0
        stk_atr_stop = None

        try:
            # 买入日快照(已结束交易用历史模式,跳过实时行情)
            is_historical = bool(sell_date)
            snapshot = fetch_pre_snapshot(stock_code, buy_date, historical=is_historical)
            indicators = snapshot.get("indicators", {})
            indices = snapshot.get("indices", {})
            chase_detect = snapshot.get("chase_detect", {})

            stk_trend = classify_stk_trend(indicators)
            mkt_trend = classify_mkt_trend(indices, config)

            # BOLL %B
            boll_upper = indicators.get("BOLL_upper")
            boll_lower = indicators.get("BOLL_lower")
            price = trade.get("buy_price", 0)
            if boll_upper and boll_lower and (boll_upper - boll_lower) > 0:
                boll_pctb = (price - boll_lower) / (boll_upper - boll_lower) * 100
                boll_pctb = max(0, min(100, boll_pctb))

            # ATR分位(简化: 用当前ATR/历史均值的比值)
            atr14 = indicators.get("ATR14", 0) or 0
            if atr14 > 0 and price > 0:
                stk_atr_pctb = min(atr14 / price * 100 * 10, 100)  # 近似分位
                stk_atr_stop = round(price - 2 * atr14, 3)

        except Exception as e:
            chase_detect = {}
            indices = {}

        # ---- 仓位判定 ----
        position_ratio = trade.get("position_ratio", 0)
        max_pos = config.get("max_single_position", 0.15)
        # position_ratio统一为小数比例(如0.15=15%)
        # 兼容: 如果>1则视为百分号形式, 自动转换
        if position_ratio > 1:
            position_ratio = position_ratio / 100
        if position_ratio <= max_pos:
            position_rule = "pass"
        elif position_ratio <= max_pos * 1.5:
            position_rule = "exceed"
        else:
            position_rule = "critical"

        # ---- 止损判定 ----
        stop_price = trade.get("stop_price", 0)
        stop_loss_set = 1 if stop_price > 0 else 0
        buy_price = trade.get("buy_price", 0)
        stop_loss_pct = round((buy_price - stop_price) / buy_price * 100, 2) if stop_price > 0 and buy_price > 0 else 0

        # ---- 顺势/逆势 ----
        trade_direction = calc_trade_direction(stk_trend, mkt_trend)

        # ---- 四分法 ----
        is_profit = 1 if trade.get("realized_pnl", 0) >= 0 else 0
        trade_category = get_trade_category(stop_loss_set, position_rule, trade_direction, is_profit)

        # ---- 冲动判定(增强版) ----
        emotion_stats = {"consecutive_losses": 0, "trades_same_day": 1,
                         "repeat_trades": 1, "repeat_loss_count": 0}
        try:
            emotion_stats = query_emotion_stats(account, buy_date, stock_code, db_conn)
        except Exception:
            pass  # 首次入库时查不到历史

        impulsive_result = detect_impulsive_v2(
            consecutive_losses=emotion_stats["consecutive_losses"],
            trades_same_day=emotion_stats["trades_same_day"],
            stop_loss_set=stop_loss_set,
            position_rule=position_rule,
            stk_atr_pctb=stk_atr_pctb,
        )

        # ---- 黑名单 ----
        blacklist_result = check_blacklist(stock_code, db_conn)

        # ---- 评分 ----
        sell_reason = trade.get("sell_reason", "")
        sell_trigger = trade.get("sell_trigger", "subjective")
        sell_verdict = trade.get("sell_verdict", "normal")

        # 事后验证(如果sell_date距今>=5交易日)
        post_validation = {}
        try:
            post_validation = fetch_post_validation(
                stock_code, buy_date, buy_price,
                stop_price, 0, days_list=[5, 10, 20, 60],
                sell_price=trade.get("sell_price", 0),
                sell_date=trade.get("sell_date"),
            )
            # 提取sell_verdict
            p5 = post_validation.get("post5", {})
            p10 = post_validation.get("post10", {})
            p20 = post_validation.get("post20", {})
            p60 = post_validation.get("post60", {})
            # 持仓期最高价: 从post_validation中取
            hold_max = post_validation.get("hold_period_max_price", trade.get("max_price_hold", buy_price))
            if p5 and p10:
                sell_verdict = calc_sell_verdict(
                    trade.get("sell_price", 0),
                    p5.get("close"), p10.get("close"),
                    p20.get("high") if p20 else None,
                    hold_max,
                    stop_price=stop_price, config=config,
                    buy_price=buy_price,
                )
        except Exception:
            p5 = p10 = p20 = p60 = None
            hold_max = trade.get("max_price_hold", buy_price)

        # 仓位/止损/单笔风险计算
        total_assets = trade.get("total_assets", 0)
        single_risk_pct = 0
        if stop_price > 0 and total_assets > 0:
            single_risk_pct = round((buy_price - stop_price) * trade.get("buy_shares", 0) / total_assets * 100, 2)

        # 入场信号推断(从indicators)
        entry_signal = _infer_entry_signal(indicators, chase_detect)

        # 行业排名百分位
        sector_pct_rank = 50.0  # 默认中位
        industry = _get_industry_map().get(stock_code, "")

        scoring_data = {
            "indicators": indicators,
            "stk_trend": stk_trend,
            "mkt_trend": mkt_trend,
            "boll_pctb": boll_pctb,
            "is_chase": chase_detect.get("is_chase") or chase_detect.get("is_chase_high", False),
            "entry_signal": entry_signal,
            "sector_pct_rank": sector_pct_rank,
            "trade_direction": trade_direction,
            "sell_reason": sell_reason,
            "sell_trigger": sell_trigger,
            "sell_verdict": sell_verdict,
            "has_plan": trade.get("has_plan", False),
            "position_rule": position_rule,
            "stop_loss_set": stop_loss_set,
            "stop_loss_pct": stop_loss_pct,
            "single_risk_pct": single_risk_pct,
            "stk_atr_stop": stk_atr_stop,
        }
        score_result = audit_score(scoring_data, config)

        # ---- 错误分类 ----
        mistake_category = infer_mistake_category({
            "stop_loss_set": stop_loss_set,
            "has_plan": trade.get("has_plan", False),
            "trade_direction": trade_direction,
            "is_profit": is_profit,
            "consecutive_losses": emotion_stats["consecutive_losses"],
            "sell_verdict": sell_verdict,
            "stk_boll_pctb": boll_pctb,
        }, chase_detect)

        # ---- 反馈动作 ----
        feedback_action = calc_feedback_action(
            trade_category, score_result["total_score"],
            blacklist_result["in_blacklist"], impulsive_result["is_impulsive"],
        )

        # ---- BOLL区间 ----
        if boll_pctb > 90:
            boll_zone = "above_upper"
        elif boll_pctb > 70:
            boll_zone = "upper_zone"
        elif boll_pctb > 30:
            boll_zone = "mid_zone"
        elif boll_pctb > 10:
            boll_zone = "lower_zone"
        else:
            boll_zone = "below_lower"

        # MA支撑判定
        ma20 = indicators.get("MA20")
        ma60 = indicators.get("MA60")
        if ma20 and buy_price >= ma20 * 0.98:
            ma_support = "on_ma20"
        elif ma60 and buy_price >= ma60 * 0.98:
            ma_support = "on_ma60"
        elif ma20 and buy_price > ma20:
            ma_support = "above"
        else:
            ma_support = "below"

        # MA排列
        ma5 = indicators.get("MA5")
        ma10 = indicators.get("MA10")
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                ma_arrange = "bullish"
            elif ma5 < ma10 < ma20:
                ma_arrange = "bearish"
            else:
                ma_arrange = "intertwined"
        else:
            ma_arrange = "intertwined"

        # MA距离
        ma_dist_pct = round((buy_price - ma20) / ma20 * 100, 2) if ma20 and buy_price > 0 else None

        # MACD state
        dif = indicators.get("MACD_DIF", 0) or 0
        dea = indicators.get("MACD_DEA", 0) or 0
        hist = indicators.get("MACD_HIST", 0) or 0
        if dif > dea and hist > 0:
            macd_state = "金叉向上"
        elif dif > dea:
            macd_state = "金叉走平"
        elif dif < dea and hist < 0:
            macd_state = "死叉向下"
        else:
            macd_state = "死叉走平"

        # BOLL宽度
        boll_width = "flat"
        if boll_upper and boll_lower and ma20:
            width = (boll_upper - boll_lower) / ma20 * 100
            if width > 15:
                boll_width = "expanding"
            elif width < 8:
                boll_width = "contracting"

        # 入场模式推断
        entry_mode = _infer_entry_mode(indicators, chase_detect, buy_price)

        # 持仓期
        hold_days = trade.get("hold_days", 0)
        if hold_days <= 3:
            hold_period = "超短"
        elif hold_days <= 10:
            hold_period = "短线"
        elif hold_days <= 30:
            hold_period = "中线"
        else:
            hold_period = "长线"

        # 量比(从indicators)
        vol_ratio = indicators.get("VOL_RATIO", 1.0) or 1.0

        # RSI6
        rsi6 = indicators.get("RSI6", 50) or 50

        # 大盘状态
        mkt_state = "oscillating"
        mkt_chg = 0
        mkt_close = 0
        sh_idx = indices.get("上证", {})
        mkt_chg = sh_idx.get("change_pct", 0)
        mkt_close = sh_idx.get("price", 0)
        mkt_above_ma20 = None  # 需额外数据，暂时留空

        if mkt_chg > 1:
            mkt_state = "strong"
        elif mkt_chg < -1:
            mkt_state = "weak"
        elif abs(mkt_chg) < 0.5:
            mkt_state = "oscillating"

        # ---- 组装审计记录 ----
        record = {
            # A: 基础
            "account": account,
            "stock_code": stock_code,
            "stock_name": trade.get("stock_name", ""),
            "industry": industry,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "buy_shares": trade.get("buy_shares", 0),
            "buy_amount": trade.get("buy_amount", 0),
            "sell_date": sell_date,
            "sell_price": trade.get("sell_price", 0),
            "sell_shares": sell_shares,
            "sell_amount": trade.get("sell_amount", 0),
            "hold_days": hold_days,
            "realized_pnl": trade.get("realized_pnl", 0),
            "pnl_rate": trade.get("pnl_rate", 0),
            "total_fees": trade.get("total_fees", 0),
            # B: 入场环境
            "mkt_state": mkt_state,
            "mkt_index_close": mkt_close,
            "mkt_index_chg": mkt_chg,
            "mkt_trend": mkt_trend,
            "mkt_above_ma20": mkt_above_ma20,
            "stk_trend": stk_trend,
            "stk_ma_arrange": ma_arrange,
            "stk_ma_support": ma_support,
            "stk_ma_dist_pct": ma_dist_pct,
            "stk_boll_zone": boll_zone,
            "stk_boll_pctb": round(boll_pctb, 4),
            "stk_boll_width": boll_width,
            "stk_vol_ratio": round(vol_ratio, 2),
            "stk_macd_state": macd_state,
            "stk_rsi6": round(rsi6, 2),
            "stk_atr14": indicators.get("ATR14"),
            "stk_atr_pctb": round(stk_atr_pctb, 2),
            "stk_atr_stop": stk_atr_stop,
            # C: 操作定性
            "trade_direction": trade_direction,
            "entry_mode": entry_mode,
            "entry_signal": entry_signal,
            "entry_quality": _infer_entry_quality(scoring_data),
            "hold_period": hold_period,
            "is_profit": is_profit,
            "trade_category": trade_category,
            # D: 仓位与风控
            "position_ratio": position_ratio,
            "position_rule": position_rule,
            "single_stock_limit": 1 if position_ratio > config.get("max_single_position", 0.15) else 0,
            "stop_loss_set": stop_loss_set,
            "stop_loss_type": "fixed_pct" if stop_loss_set else "",
            "stop_loss_price": stop_price,
            "stop_loss_hit": None,  # 需事后验证
            "max_drawdown_pct": trade.get("max_drawdown_pct"),
            "risk_reward_planned": None,
            "is_pyramid": 0,
            # E: 卖出审计
            "sell_reason": sell_reason,
            "sell_trigger": sell_trigger,
            "sell_trend": stk_trend,  # 简化，卖出时趋势待事后补
            "sell_boll_pctb": None,  # 卖出时BOLL待事后补
            "sell_timing": _infer_sell_timing(sell_verdict),
            "max_price_hold": hold_max if isinstance(hold_max, (int, float)) else trade.get("max_price_hold"),
            "min_price_hold": trade.get("min_price_hold"),
            "max_profit_pct": trade.get("max_profit_pct"),
            "profit_unrealized_rate": None,
            "sell_vs_plan": "per_plan" if sell_trigger == "rule_triggered" else "deviated",
            # F: 事后验证
            "post5_close": p5.get("close") if isinstance(p5, dict) else None,
            "post5_chg": p5.get("chg") if isinstance(p5, dict) else None,
            "post5_high": p5.get("high") if isinstance(p5, dict) else None,
            "post5_low": p5.get("low") if isinstance(p5, dict) else None,
            "post10_close": p10.get("close") if isinstance(p10, dict) else None,
            "post10_chg": p10.get("chg") if isinstance(p10, dict) else None,
            "post20_close": p20.get("close") if isinstance(p20, dict) else None,
            "post20_chg": p20.get("chg") if isinstance(p20, dict) else None,
            "post20_high": p20.get("high") if isinstance(p20, dict) else None,
            "post20_low": p20.get("low") if isinstance(p20, dict) else None,
            "post60_chg": p60.get("chg") if isinstance(p60, dict) else None,
            "post_new_high": post_validation.get("post_new_high"),
            "sell_verdict": sell_verdict,
            # G: 情绪与纪律
            "consecutive_losses": emotion_stats["consecutive_losses"],
            "trades_same_day": emotion_stats["trades_same_day"],
            "repeat_trades": emotion_stats["repeat_trades"],
            "repeat_loss_count": emotion_stats["repeat_loss_count"],
            "is_impulsive": 1 if impulsive_result["is_impulsive"] else 0,
            "impulsive_type": impulsive_result["impulsive_type"],
            "in_blacklist": 1 if blacklist_result["in_blacklist"] else 0,
            # H: 综合评分
            "strategy_tag": trade.get("strategy_tag", ""),
            "rule_violation": "",  # 待人工标注
            "entry_score": score_result["entry_score"],
            "exit_score": score_result["exit_score"],
            "discipline_score": score_result["discipline_score"],
            "risk_control_score": score_result["risk_control_score"],
            "total_score": score_result["total_score"],
            "mistake_category": mistake_category,
            "feedback_action": feedback_action,
            "data_complete": 1,
        }

        # 写入MySQL
        audit_id = insert_audit(db_conn, record)
        result["audit_id"] = audit_id
        result["record"] = record
        result["status"] = "inserted"

        # 写入信号
        if entry_signal:
            insert_signals(db_conn, audit_id, [entry_signal])

    except Exception as e:
        result["status"] = f"error: {e}"
    finally:
        if auto_close and db_conn:
            db_conn.close()

    return result


# ---- insert_audit_from_trade 的辅助函数 ----

def _infer_entry_signal(indicators: dict, chase_detect: dict) -> str:
    """从技术指标推断入场信号"""
    dif = indicators.get("MACD_DIF", 0) or 0
    dea = indicators.get("MACD_DEA", 0) or 0
    hist = indicators.get("MACD_HIST", 0) or 0
    vol_ratio = indicators.get("VOL_RATIO", 1.0) or 1.0

    if chase_detect.get("is_chase") or chase_detect.get("is_chase_high"):
        return "突破"
    if dif > dea and hist > 0:
        return "金叉"
    if vol_ratio > 2.0:
        return "放量"
    boll_pctb = indicators.get("BOLL_PCTB", 50)
    if boll_pctb and boll_pctb < 20:
        return "缩量止跌"
    return "其他"


def _infer_entry_mode(indicators: dict, chase_detect: dict, buy_price: float) -> str:
    """推断入场模式"""
    if chase_detect.get("is_chase") or chase_detect.get("is_chase_high"):
        return "breakout"
    ma20 = indicators.get("MA20")
    if ma20 and buy_price <= ma20 * 1.02:
        return "pullback"
    return "left_batch"


def _infer_entry_quality(scoring_data: dict) -> str:
    """推断入场质量"""
    boll_pctb = scoring_data.get("boll_pctb", 50)
    is_chase = scoring_data.get("is_chase", False)
    stk_trend = scoring_data.get("stk_trend", "sideways")

    if is_chase:
        return "poor"
    if stk_trend == 'bull' and 25 <= boll_pctb <= 50:
        return "excellent"
    if stk_trend == 'bull' or (30 <= boll_pctb <= 70):
        return "good"
    return "poor"


def _infer_sell_timing(sell_verdict: str) -> str:
    """从sell_verdict推断卖出时机评分"""
    mapping = {
        "perfect_stop": "high", "good_profit": "high", "normal": "mid",
        "late_stop": "low", "missed_profit": "low", "unknown": "mid",
    }
    return mapping.get(sell_verdict, "mid")


def calc_cost(trade_amount: float, config: dict = None) -> dict:
    """交易成本核算"""
    config = config or load_config(CONFIG_PATH)
    comm_rate = config.get("commission_rate", 0.00025)
    stamp_rate = config.get("stamp_tax_rate", 0.0005)
    transfer_rate = config.get("transfer_rate", 0.00001)
    min_commission = config.get("min_commission", 5.0)  # A股最低佣金5元/笔

    commission_buy = round(max(trade_amount * comm_rate, min_commission), 2)
    commission_sell = round(max(trade_amount * comm_rate, min_commission), 2)
    stamp_tax = round(trade_amount * stamp_rate, 2)
    transfer = round(trade_amount * transfer_rate * 2, 2)
    total = round(commission_buy + commission_sell + stamp_tax + transfer, 2)
    return {
        "commission_buy": commission_buy,
        "commission_sell": commission_sell,
        "stamp_tax": stamp_tax,
        "transfer": transfer,
        "total": total,
    }


# ============================================================
# 事前评分引擎 (6维度 × 1-5分 = 30分制)
# ============================================================

def score_trend(indicators: dict, klines: list) -> dict:
    """
    趋势评分(1-5): MA排列 + MACD方向 + 均线斜率
    5: 多头排列(MA5>MA10>MA20>MA60) + MACD金叉 + 均线向上
    3: 部分多头 或 MACD金叉
    1: 空头排列 + MACD死叉
    """
    score = 3  # 默认中性
    reasons = []

    ma5 = indicators.get("MA5")
    ma10 = indicators.get("MA10")
    ma20 = indicators.get("MA20")
    ma60 = indicators.get("MA60")
    dif = indicators.get("MACD_DIF", 0) or 0
    dea = indicators.get("MACD_DEA", 0) or 0
    hist = indicators.get("MACD_HIST", 0) or 0

    # MA排列判断
    has_ma60 = ma60 is not None and ma60 > 0
    if all(v is not None and v > 0 for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            if has_ma60 and ma20 > ma60:
                bull_align = True
                reasons.append("多头排列(MA5>MA10>MA20>MA60)")
            else:
                bull_align = ma5 > ma10 > ma20
                reasons.append("短中期多头(MA5>MA10>MA20)")
        elif ma5 < ma10 < ma20:
            bull_align = False
            if has_ma60 and ma20 < ma60:
                reasons.append("空头排列(MA5<MA10<MA20<MA60)")
            else:
                reasons.append("短中期空头(MA5<MA10<MA20)")
        else:
            bull_align = None
            reasons.append("均线缠绕")
    else:
        bull_align = None
        reasons.append("均线数据不足")

    # MACD方向
    macd_bull = dif > dea
    if macd_bull:
        reasons.append("MACD金叉")
    else:
        reasons.append("MACD死叉")

    # 均线斜率(用近5日MA20变化)
    slope_up = False
    if len(klines) >= 25 and ma20 is not None:
        closes = [k["close"] for k in klines[-25:]]
        ma20_5ago = sum(closes[-25:-5]) / 20 if len(closes) >= 25 else None
        if ma20_5ago and ma20 > ma20_5ago:
            slope_up = True
            reasons.append("MA20向上")
        else:
            reasons.append("MA20走平/向下")

    # 综合评分
    if bull_align is True and macd_bull:
        score = 5
    elif bull_align is True and not macd_bull:
        score = 4
    elif bull_align is None and macd_bull:
        score = 4
    elif bull_align is None:
        score = 3
    elif bull_align is False and macd_bull:
        score = 3
    elif bull_align is False and not macd_bull:
        score = 1
    # 斜率微调±1
    if slope_up and score >= 3:
        score = min(5, score + 1)
    elif not slope_up and score <= 3:
        score = max(1, score - 1)

    return {"score": score, "reason": "; ".join(reasons)}


def score_position(indicators: dict, rt: dict, chase_detect: dict, trend_score: int = 3) -> dict:
    """
    位置评分(1-5): BOLL位置 + 追高检测 + MA支撑距离
    5: BOLL中下(25-50%) + MA20支撑近 + 非追高
    1: BOLL上轨上方(>90%) + 追高
    注意: BOLL低位(<20%)在下跌趋势中不是好位置，需结合趋势
    """
    score = 3
    reasons = []

    # BOLL位置
    boll_upper = indicators.get("BOLL_upper")
    boll_lower = indicators.get("BOLL_lower")
    boll_mid = indicators.get("BOLL_mid")
    price = rt.get("price", 0) or indicators.get("close", 0)

    boll_pct = 50  # 默认中轨
    if boll_upper and boll_lower and (boll_upper - boll_lower) > 0:
        boll_pct = (price - boll_lower) / (boll_upper - boll_lower) * 100
        boll_pct = max(0, min(100, boll_pct))

    if boll_pct < 20:
        reasons.append(f"BOLL低位({boll_pct:.0f}%)")
    elif boll_pct < 50:
        reasons.append(f"BOLL中下({boll_pct:.0f}%)")
    elif boll_pct < 80:
        reasons.append(f"BOLL中上({boll_pct:.0f}%)")
    else:
        reasons.append(f"BOLL高位({boll_pct:.0f}%)")

    # 追高检测(兼容is_chase和is_chase_high两种key)
    is_chase = chase_detect.get("is_chase") or chase_detect.get("is_chase_high", False)
    if is_chase:
        reasons.append(f"🚨追高({chase_detect.get('ratio', 0)}%)")
    else:
        reasons.append("非追高")

    # MA支撑距离
    ma20 = indicators.get("MA20")
    if ma20 and price > 0:
        dist_ma20 = (price - ma20) / ma20 * 100
        reasons.append(f"距MA20 {dist_ma20:+.1f}%")

    # 评分映射(分段函数)
    if is_chase:
        score = 1  # 追高直接1分
    elif boll_pct >= 90:
        score = 1
    elif boll_pct >= 75:
        score = 2
    elif boll_pct >= 50:
        score = 3
    elif boll_pct >= 25:
        score = 4
    elif trend_score >= 4:
        # 上涨趋势中BOLL低位=回调好位置
        score = 5
    elif trend_score <= 2:
        # 下跌趋势中BOLL低位=继续下跌，不是好位置
        score = 2
        reasons.append("下跌趋势中BOLL低位≠好位置")
    else:
        score = 3  # 震荡趋势中性

    # 如果距MA20很近(±2%), 加1分(有支撑)
    if ma20 and price > 0 and abs((price - ma20) / ma20 * 100) <= 2 and not is_chase:
        score = min(5, score + 1)

    return {"score": score, "reason": "; ".join(reasons)}


def score_sector(indicators: dict, sector_list: list, industry_name: str = "") -> dict:
    """
    行业评分(1-5): 行业涨幅排名 + 个股相对强弱
    5: 行业涨幅TOP5 + 个股跑赢行业
    1: 行业跌幅TOP5
    """
    score = 3
    reasons = []

    if not sector_list:
        return {"score": 3, "reason": "行业数据缺失，默认3分"}

    # 确保按涨跌幅降序排列(评分逻辑依赖排名)
    try:
        sector_list = sorted(sector_list, key=lambda s: s.get("change_pct", 0), reverse=True)
    except Exception:
        pass

    total = len(sector_list)

    # 找到目标行业排名(先精确匹配, 再关键词模糊匹配)
    target_rank = None
    target_change = 0
    target_name = ""

    # 精确匹配
    for i, s in enumerate(sector_list):
        if industry_name and industry_name in s.get("name", ""):
            target_rank = i + 1
            target_change = s.get("change_pct", 0)
            target_name = s.get("name", "")
            break

    # 关键词模糊匹配
    if target_rank is None and industry_name:
        keywords = _get_industry_keywords().get(industry_name, [industry_name])
        for kw in keywords:
            for i, s in enumerate(sector_list):
                if kw in s.get("name", ""):
                    target_rank = i + 1
                    target_change = s.get("change_pct", 0)
                    target_name = s.get("name", "")
                    break
            if target_rank is not None:
                break

    if target_rank is not None:
        pct_rank = target_rank / total * 100
        if pct_rank <= 10:
            reasons.append(f"行业{industry_name}涨幅TOP10(第{target_rank}/{total}, {target_change:+.2f}%)")
            score = 5
        elif pct_rank <= 30:
            reasons.append(f"行业{industry_name}涨幅前30%(第{target_rank}/{total}, {target_change:+.2f}%)")
            score = 4
        elif pct_rank <= 70:
            reasons.append(f"行业{industry_name}涨幅中游(第{target_rank}/{total}, {target_change:+.2f}%)")
            score = 3
        elif pct_rank <= 90:
            reasons.append(f"行业{industry_name}涨幅后30%(第{target_rank}/{total}, {target_change:+.2f}%)")
            score = 2
        else:
            reasons.append(f"行业{industry_name}跌幅TOP10(第{target_rank}/{total}, {target_change:+.2f}%)")
            score = 1
    else:
        reasons.append(f"未匹配行业'{industry_name}'，默认3分")

    return {"score": score, "reason": "; ".join(reasons)}


def score_market(indices: dict, config: dict = None) -> dict:
    """
    大盘评分(1-5): 三大指数综合状态
    5: 三大指数均上涨
    1: 三大指数均下跌
    """
    config = config or load_config(CONFIG_PATH)
    score = 3
    reasons = []

    # 阈值可配置(默认0.5%)
    up_threshold = config.get("market_up_threshold", 0.5)
    down_threshold = config.get("market_down_threshold", -0.5)

    up_count = 0
    down_count = 0
    for name in ["上证", "深证", "创业板"]:
        idx = indices.get(name, {})
        chg = idx.get("change_pct", 0)
        if chg > up_threshold:
            up_count += 1
            reasons.append(f"{name}🟢{chg:+.2f}%")
        elif chg < down_threshold:
            down_count += 1
            reasons.append(f"{name}🔴{chg:+.2f}%")
        else:
            reasons.append(f"{name}➖{chg:+.2f}%")

    if up_count == 3:
        score = 5
    elif up_count >= 2:
        score = 4
    elif up_count >= 1:
        score = 3
    elif down_count == 3:
        score = 1
    elif down_count >= 2:
        score = 2
    else:
        score = 3

    return {"score": score, "reason": "; ".join(reasons)}


def score_risk(stop_price: float, buy_price: float, qty: int,
               total_assets: float, has_plan: bool, config: dict = None) -> dict:
    """
    风控评分(1-5): 止损合理性 + 单笔风险占比
    无计划→2分(配置可调)
    5: 止损合理(5-8%) + 单笔风险≤2%
    1: 无止损
    """
    config = config or load_config(CONFIG_PATH)
    score = 3
    reasons = []

    # 冲动交易自动分
    imp = detect_impulsive(has_plan, config)
    if imp["is_impulsive"]:
        score = imp.get("auto_risk", 2)
        reasons.append(imp["detail"])
        return {"score": score, "reason": "; ".join(reasons)}

    # 无止损
    if not stop_price or stop_price <= 0:
        score = 1
        reasons.append("无止损，风控1分")
        return {"score": score, "reason": "; ".join(reasons)}

    # 止损幅度
    if buy_price > 0:
        stop_pct = (buy_price - stop_price) / buy_price * 100
        if stop_pct <= 3:
            reasons.append(f"止损紧密({stop_pct:.1f}%)")
            score = 5
        elif stop_pct <= 5:
            reasons.append(f"止损合理({stop_pct:.1f}%)")
            score = 4
        elif stop_pct <= 8:
            reasons.append(f"止损偏宽({stop_pct:.1f}%)")
            score = 3
        elif stop_pct <= 12:
            reasons.append(f"止损过宽({stop_pct:.1f}%)")
            score = 2
        else:
            reasons.append(f"止损极宽({stop_pct:.1f}%)")
            score = 1

    # 单笔风险占比
    if total_assets > 0 and buy_price > 0:
        risk_amount = (buy_price - stop_price) * qty
        risk_ratio = risk_amount / total_assets
        max_risk = config.get("max_single_risk", 0.02)
        if risk_ratio > max_risk:
            score = max(1, score - 1)
            reasons.append(f"单笔风险{risk_ratio*100:.1f}%超限(>{max_risk*100:.0f}%)")
        else:
            reasons.append(f"单笔风险{risk_ratio*100:.1f}%合规")

    return {"score": score, "reason": "; ".join(reasons)}


def score_discipline(has_plan: bool, position_ratio: float = 0,
                     is_chase: bool = False, config: dict = None) -> dict:
    """
    纪律评分(1-5): 有无计划 + 仓位合规 + 追高冲动
    无计划→1分(硬编码不可配置覆盖)
    """
    config = config or load_config(CONFIG_PATH)
    reasons = []

    # 冲动交易自动1分
    imp = detect_impulsive(has_plan, config)
    if imp["is_impulsive"]:
        reasons.append(imp["detail"])
        return {"score": 1, "reason": "; ".join(reasons)}

    if not has_plan:
        reasons.append("无交易计划")
        return {"score": 1, "reason": "; ".join(reasons)}

    score = 5
    reasons.append("有交易计划")

    # 仓位合规检查
    max_pos = config.get("max_single_position", 0.15)
    if position_ratio > max_pos:
        score -= 1
        reasons.append(f"超仓({position_ratio*100:.1f}%>{max_pos*100:.0f}%)")

    # 追高
    if is_chase:
        score -= 1
        reasons.append("追高买入")

    score = max(1, score)
    return {"score": score, "reason": "; ".join(reasons)}


def pre_score(snapshot: dict, trade_info: dict) -> dict:
    """
    事前评分总入口
    snapshot: fetch_pre_snapshot()返回值
    trade_info: {buy_price, qty, stop_price, has_plan, total_assets, ...}
    """
    config = load_config(CONFIG_PATH)
    indicators = snapshot.get("indicators", {})
    rt = snapshot.get("realtime", {})
    klines = snapshot.get("kline_daily", [])
    sector_list = snapshot.get("sector_list", [])
    indices = snapshot.get("indices", {})
    chase_detect = snapshot.get("chase_detect", {})
    code = snapshot.get("code", "")
    industry = _get_industry_map().get(code, "")

    weights = config.get("pre_weights", {})
    w_trend = weights.get("trend", 1.0)
    w_pos = weights.get("position", 1.0)
    w_sector = weights.get("sector", 1.0)
    w_market = weights.get("market", 1.0)
    w_risk = weights.get("risk", 1.0)
    w_disc = weights.get("discipline", 1.0)

    s_trend = score_trend(indicators, klines)

    # 统一chase_detect: 合并snapshot自带+独立计算的结果，确保key兼容
    # snapshot的chase_detect用is_chase_high，独立detect_chase_high()用is_chase
    unified_chase = dict(chase_detect)  # 复制snapshot的数据
    # 如果snapshot有is_chase_high但没有is_chase，做映射
    if "is_chase_high" in unified_chase and "is_chase" not in unified_chase:
        unified_chase["is_chase"] = unified_chase["is_chase_high"]
    # 独立计算追高(基于用户输入的buy_price，比snapshot用实时价更准确)
    if trade_info.get("buy_price", 0) > 0 and rt:
        independent_chase = detect_chase_high(trade_info["buy_price"], rt, config)
        if independent_chase.get("is_chase"):
            unified_chase.update(independent_chase)

    s_pos = score_position(indicators, rt, unified_chase, s_trend["score"])
    # 行业评分需要完整行业列表(快照可能只含前10)
    if sector_list and len(sector_list) >= 30:
        full_sector_list = sector_list
    else:
        try:
            full_sector_list = fetch_sectors()
        except Exception:
            full_sector_list = sector_list
    s_sector = score_sector(indicators, full_sector_list, industry)
    s_market = score_market(indices, config)
    s_risk = score_risk(
        trade_info.get("stop_price", 0),
        trade_info.get("buy_price", 0),
        trade_info.get("qty", 0),
        trade_info.get("total_assets", 0),
        trade_info.get("has_plan", False),
        config,
    )
    s_disc = score_discipline(
        trade_info.get("has_plan", False),
        trade_info.get("position_ratio", 0),
        chase_detect.get("is_chase", False),
        config,
    )

    raw_total = (
        s_trend["score"] * w_trend +
        s_pos["score"] * w_pos +
        s_sector["score"] * w_sector +
        s_market["score"] * w_market +
        s_risk["score"] * w_risk +
        s_disc["score"] * w_disc
    )
    # 6维度×1-5分=30分制, 直接加权求和
    total = round(raw_total)

    return {
        "total": total,
        "label": score_label_pre(total),
        "dimensions": {
            "趋势": s_trend,
            "位置": s_pos,
            "行业": s_sector,
            "大盘": s_market,
            "风控": s_risk,
            "纪律": s_disc,
        },
    }


# ============================================================
# 事后评分引擎 (5维度 × 1-5分 = 25分制)
# ============================================================

def score_direction(final_pct: float) -> dict:
    """方向评分(1-5): N日涨跌幅"""
    score = 3
    if final_pct >= 10:
        score = 5
    elif final_pct >= 5:
        score = 4
    elif final_pct >= -2:
        score = 3
    elif final_pct >= -5:
        score = 2
    else:
        score = 1
    return {"score": score, "reason": f"N日涨跌{final_pct:+.2f}%"}


def score_timing(max_loss_pct: float, max_profit_pct: float) -> dict:
    """
    时机评分(1-5): 入场时机精度(最大回撤)
    5: 最大浮亏<2%
    1: 最大浮亏>10%
    """
    loss = abs(max_loss_pct)
    if loss < 2:
        score = 5
    elif loss < 4:
        score = 4
    elif loss < 7:
        score = 3
    elif loss < 10:
        score = 2
    else:
        score = 1
    return {
        "score": score,
        "reason": f"最大浮亏{max_loss_pct:.2f}%, 最大浮盈{max_profit_pct:+.2f}%",
    }


def score_stop_effect(min_low: float, stop_price: float, buy_price: float) -> dict:
    """
    风控有效评分(1-5): 止损距离
    5: 最低价远高于止损价(>5%缓冲)
    1: 止损被触发
    """
    if stop_price <= 0:
        return {"score": 3, "reason": "无止损价，默认3分"}

    if min_low <= stop_price:
        return {"score": 1, "reason": f"止损被触发(最低{min_low}<=止损{stop_price})"}

    buffer = (min_low - stop_price) / buy_price * 100 if buy_price > 0 else 0
    if buffer > 5:
        score = 5
    elif buffer > 3:
        score = 4
    elif buffer > 1:
        score = 3
    elif buffer > 0:
        score = 2
    else:
        score = 1

    return {"score": score, "reason": f"最低价{min_low}距止损{stop_price}, 缓冲{buffer:.1f}%"}


def score_profit_ratio(profit_ratio: float, final_pct: float) -> dict:
    """
    空间/盈亏比评分(1-5)
    5: 盈亏比≥3
    1: 亏损或盈亏比<0.5
    """
    if final_pct < 0:
        score = 1
    elif profit_ratio >= 3:
        score = 5
    elif profit_ratio >= 2:
        score = 4
    elif profit_ratio >= 1:
        score = 3
    elif profit_ratio >= 0.5:
        score = 2
    else:
        score = 1

    return {"score": score, "reason": f"盈亏比{profit_ratio:.2f}, 最终涨跌{final_pct:+.2f}%"}


def score_hold_quality(max_loss_pct: float, final_pct: float) -> dict:
    """
    持有质量评分(1-5): 最大浮亏深度
    5: 最大浮亏<3%
    1: 最大浮亏>15%
    """
    loss = abs(max_loss_pct)
    if loss < 3:
        score = 5
    elif loss < 5:
        score = 4
    elif loss < 8:
        score = 3
    elif loss < 15:
        score = 2
    else:
        score = 1

    return {"score": score, "reason": f"最大浮亏{max_loss_pct:.2f}%, 最终{final_pct:+.2f}%"}


def post_score(validation: dict, config: dict = None) -> dict:
    """
    事后评分总入口
    validation: fetch_post_validation()返回值
    """
    if "error" in validation:
        return {"total": 0, "label": "❌数据缺失", "dimensions": {}}

    config = config or load_config(CONFIG_PATH)
    weights = config.get("post_weights", {})
    w_dir = weights.get("direction", 1.0)
    w_time = weights.get("timing", 1.0)
    w_stop = weights.get("stop_effect", 1.0)
    w_pnl = weights.get("profit_ratio", 1.0)
    w_hold = weights.get("hold_quality", 1.0)

    final_pct = validation.get("final_pct", 0)
    max_loss_pct = validation.get("max_loss_pct", 0)
    max_profit_pct = validation.get("max_profit_pct", 0)
    min_low = validation.get("min_low", 0)
    stop_price = validation.get("stop_price", 0)
    buy_price = validation.get("buy_price", 0)
    profit_ratio = validation.get("profit_ratio", 0)

    s_dir = score_direction(final_pct)
    s_time = score_timing(max_loss_pct, max_profit_pct)
    s_stop = score_stop_effect(min_low, stop_price, buy_price)
    s_pnl = score_profit_ratio(profit_ratio, final_pct)
    s_hold = score_hold_quality(max_loss_pct, final_pct)

    # 加权求和(默认等权=原逻辑, 5维×1-5=25分制)
    raw_total = (
        s_dir["score"] * w_dir +
        s_time["score"] * w_time +
        s_stop["score"] * w_stop +
        s_pnl["score"] * w_pnl +
        s_hold["score"] * w_hold
    )
    total = round(raw_total)

    return {
        "total": total,
        "label": score_label_post(total),
        "dimensions": {
            "方向": s_dir,
            "时机": s_time,
            "风控有效性": s_stop,
            "空间(盈亏比)": s_pnl,
            "持有质量": s_hold,
        },
    }


# ============================================================
# 复盘卡生成器
# ============================================================

def _review_dir() -> str:
    cfg = load_config(CONFIG_PATH)
    out = cfg.get("output", {})
    vault = out.get("vault", VAULT)
    return os.path.join(vault, out.get("review_dir", "mystocks/复盘"))


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_draft(code: str, name: str, buy_price: float, qty: int,
                   trade_date: str = None, trade_time: str = None,
                   stop_price: float = 0, target_price: float = 0,
                   has_plan: bool = False, strategy: str = "",
                   entry_mode: str = "", plan_position: str = "",
                   plan_period: str = "", total_assets: float = 0,
                   account: str = "", template_version: str = "v2") -> str:
    """
    T+0草稿: 新建复盘卡文件
    template_version: 'v2'(旧30分制) / 'v3'(新10分制)
    返回生成的文件路径
    """
    trade_date = trade_date or _today_str()
    rdir = _review_dir()
    ym = trade_date[:7]  # YYYY-MM
    stock_dir = os.path.join(rdir, ym, "个股")
    os.makedirs(stock_dir, exist_ok=True)

    filename = f"{name}-{code}-{trade_date.replace('-', '')}.md"
    filepath = os.path.join(stock_dir, filename)

    # 加载配置(一次性)
    config = load_config(CONFIG_PATH)

    # 获取事前快照(含异常处理)
    try:
        snapshot = fetch_pre_snapshot(code, trade_date, trade_time)
    except Exception as e:
        snapshot = {
            "code": code, "trade_date": trade_date, "trade_time": trade_time,
            "realtime": {}, "kline_daily": [], "indicators": {},
            "sector_list": [], "indices": {}, "chase_detect": {},
            "_fetch_error": str(e),
        }

    # 交易信息
    trade_amount = buy_price * qty
    position_ratio = trade_amount / total_assets if total_assets > 0 else 0
    trade_info = {
        "buy_price": buy_price,
        "qty": qty,
        "stop_price": stop_price,
        "has_plan": has_plan,
        "total_assets": total_assets,
        "position_ratio": position_ratio,
    }

    # 事前评分
    pre = pre_score(snapshot, trade_info)

    # 追高/抄底检测(使用已加载config)
    chase = detect_chase_high(buy_price, snapshot.get("realtime", {}), config)
    bottom = detect_bottom_fishing(buy_price, snapshot.get("realtime", {}), config)

    # 异常交易检测
    force_check = check_force_review({
        "risk_ratio": (buy_price - stop_price) * qty / total_assets if total_assets > 0 and stop_price > 0 else 0,
        "stop_price": stop_price,
        "position_ratio": position_ratio,
        "market_down": any(v.get("change_pct", 0) < 0 for v in snapshot.get("indices", {}).values()),
        "is_chase": chase.get("is_chase", False),
        "has_plan": has_plan,
        "is_impulsive": not has_plan,
    }, config)

    # 成本核算(使用已加载config)
    cost = calc_cost(trade_amount, config)

    # 技术指标
    ind = snapshot.get("indicators", {})
    rt = snapshot.get("realtime", {})
    industry = _get_industry_map().get(code, "")
    concepts = _get_concept_map().get(code, [])

    # ATR止损(无计划时)
    atr14 = ind.get("ATR14", 0) or 0
    atr_stop = round(buy_price - 2 * atr14, 2) if atr14 > 0 else 0

    # 盈亏比
    actual_stop = stop_price if stop_price > 0 else atr_stop
    if actual_stop > 0 and buy_price > actual_stop and target_price > 0:
        risk = buy_price - actual_stop + cost["total"] / qty
        reward = target_price - buy_price - cost["total"] / qty
        pnl_ratio = round(reward / risk, 2) if risk > 0 else 0
    else:
        pnl_ratio = 0

    # 状态
    state = "draft"

    # 生成Markdown
    lines = []
    # frontmatter
    if template_version == 'v3':
        # V3 frontmatter
        indicators = snapshot.get("indicators", {})
        indices_v3 = snapshot.get("indices", {})
        stk_trend_v3 = classify_stk_trend(indicators)
        mkt_trend_v3 = classify_mkt_trend(indices_v3, config)
        trade_dir_v3 = calc_trade_direction(stk_trend_v3, mkt_trend_v3)
        lines.append("---")
        lines.append(f"tags: [trade-review, draft]")
        lines.append(f"stock: \"{code} {name}\"")
        lines.append(f"date: {trade_date}")
        lines.append(f"score: 0/10")
        lines.append(f"template_version: v3")
        lines.append(f"trade_direction: \"{trade_dir_v3}\"")
        lines.append(f"trade_category: \"待定\"")
        lines.append(f"account: \"{account}\"")
        lines.append(f"状态: {state}")
        lines.append("---")
    else:
        # V2 frontmatter (保持不变)
        lines.append("---")
        lines.append(f"交易方向: 买入")
        lines.append(f'股票代码: "{code}"')
        lines.append(f'股票名称: "{name}"')
        lines.append(f'成交时间: "{trade_date} {trade_time or ""}"')
        lines.append(f"成交价格: {buy_price}")
        lines.append(f"成交数量: {qty}")
        lines.append(f"成交金额: {round(trade_amount, 2)}")
        lines.append(f'绑定策略: "{strategy}"')
        lines.append(f'入场模式: "{entry_mode}"')
        lines.append(f"计划止损价: {stop_price}")
        lines.append(f"计划目标价: {target_price}")
        lines.append(f'计划仓位: "{plan_position}"')
        lines.append(f'计划持仓周期: "{plan_period}"')
        lines.append(f"事前评分: {pre['total']}")
        lines.append(f'事前标签: "{pre["label"]}"')
        lines.append(f"状态: {state}")
        lines.append("---")
    lines.append("")
    lines.append(f"# {name}({code}) 买入复盘")
    lines.append("")

    # 数据获取异常提示
    if snapshot.get("_fetch_error"):
        lines.append(f"> ⚠️ 市场数据获取异常: {snapshot['_fetch_error']}，部分指标可能缺失")
        lines.append("")

    # 基本信息
    lines.append("## 基本信息")
    lines.append("")
    lines.append("| 字段 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| 交易方向 | 买入 |")
    lines.append(f"| 股票代码 | {code} |")
    lines.append(f"| 股票名称 | {name} |")
    lines.append(f"| 所属行业 | {industry} |")
    lines.append(f"| 所属概念 | {'/'.join(concepts)} |")
    lines.append(f"| 绑定策略 | {strategy or '—'} |")
    lines.append(f"| 入场模式 | {entry_mode or '—'} |")
    lines.append(f"| 成交时间 | {trade_date} {trade_time or ''} |")
    lines.append(f"| 成交价格 | {buy_price} |")
    lines.append(f"| 成交数量 | {qty}股 |")
    lines.append(f"| 成交金额 | {round(trade_amount, 2)}元 |")
    plan_label = "✅有" if has_plan else "❌无"
    lines.append(f"| 有无交易计划 | {plan_label} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 仓位与风险测算
    lines.append("## 仓位与风险测算")
    lines.append("")
    lines.append("| 字段 | 数值 | 合规检查 |")
    lines.append("|------|------|----------|")
    if actual_stop > 0:
        per_risk = round(buy_price - actual_stop, 2)
        total_risk = round(per_risk * qty, 2)
        risk_ratio = round(total_risk / total_assets * 100, 1) if total_assets > 0 else 0
        risk_ok = "✅" if risk_ratio <= 2 else "❌"
        pos_ok = "✅" if position_ratio <= 0.15 else "❌"
        lines.append(f"| 每股风险 | 买入{buy_price} - 止损{actual_stop} = {per_risk}元 | — |")
        lines.append(f"| 总风险金额 | {per_risk} × {qty} = {total_risk}元 | ≤总资产×2% ? |")
        lines.append(f"| 风险占总资金比 | {risk_ratio}% | {risk_ok} |")
        lines.append(f"| 单票仓位占比 | {position_ratio*100:.1f}% | {pos_ok} |")
    else:
        lines.append("| 每股风险 | 无止损价，无法计算 | ❌ |")
    lines.append("")
    lines.append(f"> 若无交易计划，止损价按ATR(14)×2倒推：止损价 = {buy_price} - 2×{atr14:.2f} = {atr_stop}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 交易成本核算
    lines.append("## 交易成本核算")
    lines.append("")
    lines.append("| 费用项 | 计算公式 | 金额 |")
    lines.append("|--------|---------|------|")
    lines.append(f"| 佣金(买) | {round(trade_amount,0)} × 0.025% | {cost['commission_buy']}元 |")
    lines.append(f"| 佣金(卖) | {round(trade_amount,0)} × 0.025% | {cost['commission_sell']}元 |")
    lines.append(f"| 印花税(卖出) | {round(trade_amount,0)} × 0.05% | {cost['stamp_tax']}元 |")
    lines.append(f"| 过户费 | {round(trade_amount,0)} × 0.001%×2 | {cost['transfer']}元 |")
    lines.append(f"| **总成本** | 佣金×2 + 印花税 + 过户费 | **{cost['total']}元** |")
    if pnl_ratio > 0:
        lines.append(f"> 盈亏比 = (目标{target_price} - 买入{buy_price} - 总成本) / (买入{buy_price} - 止损{actual_stop} + 总成本) = {pnl_ratio}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 事前视角
    lines.append("## 事前视角（成交时刻快照）")
    lines.append("")
    lines.append("> ⚠️ 以下数据均为成交时刻及之前，不含未来信息")
    lines.append("")

    # 个股技术面
    lines.append("### 个股技术面")
    lines.append("")
    lines.append("| 指标 | 数值 | 方向 |")
    lines.append("|------|------|------|")
    for key, label in [("MA5", "MA5"), ("MA10", "MA10"), ("MA20", "MA20"), ("MA60", "MA60")]:
        val = ind.get(key, "—")
        lines.append(f"| {label} | {val if val is not None else '—'} | |")
    dif_v = ind.get("MACD_DIF", "—")
    dea_v = ind.get("MACD_DEA", "—")
    hist_v = ind.get("MACD_HIST", "—")
    macd_dir = "金叉" if (dif_v or 0) > (dea_v or 0) else "死叉"
    lines.append(f"| MACD | DIF={dif_v} DEA={dea_v} 柱={hist_v} | {macd_dir} |")
    rsi_v = ind.get("RSI14", "—")
    rsi_dir = "超买⚠️" if (rsi_v or 0) > 70 else ("超卖💎" if (rsi_v or 0) < 30 else "")
    lines.append(f"| RSI(14) | {rsi_v} | {rsi_dir} |")
    boll_u = ind.get("BOLL_upper", "—")
    boll_m = ind.get("BOLL_mid", "—")
    boll_l = ind.get("BOLL_lower", "—")
    lines.append(f"| BOLL | 上轨={boll_u} 中轨={boll_m} 下轨={boll_l} | |")
    lines.append(f"| ATR(14) | {atr14} | 止损参考: {buy_price}-{round(2*atr14,2)}={atr_stop} |")
    vr_v = ind.get("volume_ratio", "—")
    vr_dir = "放量" if (vr_v or 0) > 2 else ("缩量" if (vr_v or 0) < 0.5 else "正常")
    lines.append(f"| 量比 | {vr_v} | {vr_dir} |")
    lines.append("")

    # 行业/概念
    lines.append("### 行业/概念")
    lines.append("")
    lines.append("| 维度 | 名称 | 涨跌幅 |")
    lines.append("|------|------|--------|")
    sector_info = snapshot.get("sector_list", [])
    # 获取完整行业列表用于显示和匹配
    if len(sector_info) < 30:
        try:
            sector_info = fetch_sectors()
        except Exception:
            pass
    sector_match = None
    if industry:
        # 精确匹配
        for s in sector_info:
            if industry in s.get("name", ""):
                sector_match = s
                break
        # 关键词模糊匹配
        if not sector_match:
            keywords = _get_industry_keywords().get(industry, [industry])
            for kw in keywords:
                for s in sector_info:
                    if kw in s.get("name", ""):
                        sector_match = s
                        break
                if sector_match:
                    break
    if sector_match:
        lines.append(f"| 所属行业 | {sector_match['name']} | {sector_match.get('change_pct', 0):+.2f}% |")
    else:
        lines.append(f"| 所属行业 | {industry} | — |")
    lines.append(f"| 所属概念 | {'/'.join(concepts[:3])} | — |")
    lines.append("")
    lines.append("### 大盘环境")
    lines.append("")
    lines.append("| 指数 | 涨跌幅 | 信号 |")
    lines.append("|------|--------|------|")
    for idx_name in ["上证", "深证", "创业板"]:
        idx_data = snapshot.get("indices", {}).get(idx_name, {})
        chg = idx_data.get("change_pct", 0)
        sig = "🟢偏强" if chg > 0.5 else ("🔴偏弱" if chg < -0.5 else "➖震荡")
        lines.append(f"| {idx_name} | {chg:+.2f}% | {sig} |")
    lines.append("")

    # 追高/抄底
    lines.append("### 追高/抄底检测")
    lines.append("")
    lines.append("| 检测项 | 数值 | 判定 |")
    lines.append("|--------|------|------|")
    chase_label = f"🚨追高({chase.get('ratio', 0)}%)" if chase.get("is_chase") else "✅非追高"
    bottom_label = f"📉抄底({bottom.get('change_pct', 0)}%)" if bottom.get("is_bottom") else "非抄底"
    day_pos = snapshot.get("chase_detect", {}).get("day_position_pct", 50)
    pos_label = "高位" if day_pos > 80 else ("低位" if day_pos < 20 else "中位")
    lines.append(f"| 追高检测 | {chase.get('detail', '—')} | {chase_label} |")
    lines.append(f"| 抄底检测 | {bottom.get('detail', '—')} | {bottom_label} |")
    lines.append(f"| 日内位置 | {day_pos:.1f}% | {pos_label} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 事前评分
    lines.append("## 事前评分")
    lines.append("")
    lines.append("| 维度 | 评分(1-5) | 依据 |")
    lines.append("|------|----------|------|")
    for dim_name, dim_data in pre["dimensions"].items():
        lines.append(f"| {dim_name} | {dim_data['score']}/5 | {dim_data['reason']} |")
    lines.append(f"| **总分** | **{pre['total']}/30** | **{pre['label']}** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 操作偏差
    lines.append("## 操作偏差记录")
    lines.append("")
    lines.append("| 偏差项 | 是否发生 | 说明 |")
    lines.append("|--------|---------|------|")
    lines.append(f"| 未按计划价格买入 | ⬜ | |")
    lines.append(f"| 未按计划仓位执行 | ⬜ | |")
    lines.append(f"| 手动干预止损 | ⬜ | |")
    lines.append(f"| 情绪化交易迹象 | ⬜ | {'是' if not has_plan else ''} |")
    lines.append(f"| 超仓交易 | {'❌是' if position_ratio > 0.15 else '⬜否'} | |")
    lines.append(f"| 无止损 | {'❌是' if stop_price <= 0 else '⬜否'} | |")
    lines.append("")

    # 异常交易标记
    if force_check["force_review"]:
        lines.append(f"### 🚨 异常交易标记")
        for t in force_check["triggers"]:
            lines.append(f"- {t}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 事后视角(占位)
    lines.append("## 事后视角（T+5 / T+10 验证）")
    lines.append("")
    lines.append("> 📌 本区块在 T+5 / T+10 定时任务时自动填充")
    lines.append("")
    lines.append("### T+5 验证")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append("| 验证日期 | |")
    lines.append("| 最高价 | |")
    lines.append("| 最低价 | |")
    lines.append("| 收盘价 | |")
    lines.append("| 止损是否被触发 | ⬜是 ⬜否 |")
    lines.append("| 目标价是否到达 | ⬜是 ⬜否 |")
    lines.append("| 最大浮盈 | |")
    lines.append("| 最大浮亏 | |")
    lines.append("")
    lines.append("### T+10 验证")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append("| 验证日期 | |")
    lines.append("| 最高价 | |")
    lines.append("| 最低价 | |")
    lines.append("| 收盘价 | |")
    lines.append("| 止损是否被触发 | ⬜是 ⬜否 |")
    lines.append("| 目标价是否到达 | ⬜是 ⬜否 |")
    lines.append("| 最大浮盈 | |")
    lines.append("| 最大浮亏 | |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 事后评分(占位)
    lines.append("## 事后评分 (T+10)")
    lines.append("")
    lines.append("| 维度 | 评分(1-5) | 依据 |")
    lines.append("|------|----------|------|")
    lines.append("| 方向 | /5 | |")
    lines.append("| 时机 | /5 | |")
    lines.append("| 风控有效性 | /5 | |")
    lines.append("| 空间(盈亏比) | /5 | |")
    lines.append("| 持有质量 | /5 | |")
    lines.append("| **总分** | **/25** | |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 综合判定(占位)
    lines.append("## 综合判定")
    lines.append("")
    lines.append(f"**本笔判定**: 事前{pre['total']}分({pre['label']}) + 事后__分(__) = ____")
    lines.append("")
    lines.append("> ⚠️ 杜绝结果论规则：事前🔴(6-17分)的交易，无论盈亏，一律判定为错误交易，禁止复刻，必须录入教训库。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 卖出验证(占位)
    lines.append("## 卖出验证（发生卖出时追加）")
    lines.append("")
    lines.append("| 字段 | 内容 |")
    lines.append("|------|------|")
    lines.append("| 卖出日期 | |")
    lines.append("| 卖出价格 | |")
    lines.append("| 卖出原因 | |")
    lines.append("| 是否按计划卖出 | ⬜是 / ⬜否 |")
    lines.append("| 持仓天数 | |")
    lines.append("| 最终盈亏金额 | |")
    lines.append("| 最终盈亏比例 | |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 可复用/禁止
    lines.append("## 可复用/禁止清单")
    lines.append("")
    lines.append("| 结论 | 内容 |")
    lines.append("|------|------|")
    if pre["label"] == "🔴问题":
        lines.append("| ❌ 禁止 | 事前评分过低，禁止复刻 |")
    else:
        lines.append("| ✅ 可复用 | |")
    lines.append("| ⚠️ 条件复用 | |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 教训与改进
    lines.append("## 教训与改进")
    lines.append("")
    lines.append("1. ")
    lines.append("2. ")
    lines.append("")
    lines.append("## 行动清单")
    lines.append("")
    lines.append("- [ ] ")
    lines.append("- [ ] ")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 如果是异常交易，复制到异常交易目录
    if force_check["force_review"]:
        exc_dir = os.path.join(rdir, "异常交易")
        os.makedirs(exc_dir, exist_ok=True)
        exc_path = os.path.join(exc_dir, filename)
        with open(exc_path, "w", encoding="utf-8") as f:
            f.write(content)

    return filepath


def update_post_review(filepath: str, days: int = 5, template_version: str = None) -> str:
    """
    T+N事后更新: 解析已有复盘卡, 获取事后数据, 追加更新
    days: 5/10/20/60 (V3扩展)
    template_version: 自动检测或手动指定 v2/v3
    返回更新后的文件路径
    """
    if not os.path.exists(filepath):
        return f"文件不存在: {filepath}"

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 解析frontmatter
    fm_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return "无法解析frontmatter"

    fm_text = fm_match.group(1)
    fm = {}
    for line in fm_text.strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip('"')

    code = fm.get("股票代码", "")
    name = fm.get("股票名称", "")
    buy_price = safe_float(fm.get("成交价格", 0))
    stop_price = safe_float(fm.get("计划止损价", 0))
    target_price = safe_float(fm.get("计划目标价", 0))
    trade_time_str = fm.get("成交时间", "")
    buy_date = trade_time_str.split(" ")[0] if trade_time_str else ""

    if not code or not buy_date:
        return "缺少股票代码或成交时间"

    # 获取事后验证数据
    validation = fetch_post_validation(code, buy_date, buy_price, stop_price, target_price, days)

    if "error" in validation:
        return f"事后数据获取失败: {validation['error']}"

    # 事后评分
    post = post_score(validation)

    # 解析事前评分
    pre_total = 0
    pre_label = ""
    pre_match = re.search(r'\*\*总分\*\* \| \*\*(\d+)/30\*\* \| \*\*(.*?)\*\*', content)
    if pre_match:
        pre_total = int(pre_match.group(1))
        pre_label = pre_match.group(2)

    # 综合判定
    combo = combo_label(pre_total, post["total"])

    # 构建T+N区块
    t_label = f"T+{days}"
    now_str = _now_str()

    block_lines = []
    block_lines.append(f"")
    block_lines.append(f"> 🔄 {t_label}事后验证更新于 {now_str}")
    block_lines.append(f"")

    # 替换对应的T+N验证区块
    section_header = f"### {t_label} 验证"
    if section_header in content:
        # 找到该section的范围
        section_start = content.index(section_header)
        # 找到下一个###或---
        next_section = content.find("\n### ", section_start + len(section_header))
        next_hr = content.find("\n---", section_start + len(section_header))
        section_end = min(
            next_section if next_section > 0 else len(content),
            next_hr if next_hr > 0 else len(content),
        )

        # 构建新的T+N区块
        new_section = f"""### {t_label} 验证 (成交后第{days}个交易日)

| 指标 | 数值 |
|------|------|
| 验证日期 | {validation.get('validate_days', days)}个交易日后 |
| 最高价 | {validation.get('max_high', 0):.2f} (相对买入价 {validation.get('max_profit_pct', 0):+.2f}%) |
| 最低价 | {validation.get('min_low', 0):.2f} (相对买入价 {validation.get('max_loss_pct', 0):+.2f}%) |
| 收盘价 | {validation.get('final_close', 0):.2f} (相对买入价 {validation.get('final_pct', 0):+.2f}%) |
| 止损是否被触发 | {'✅是' if validation.get('stop_triggered') else '⬜否'} |
| 目标价是否到达 | {'✅是' if validation.get('target_reached') else '⬜否'} |
| 最大浮盈 | {validation.get('max_profit_pct', 0):+.2f}% |
| 最大浮亏 | {validation.get('max_loss_pct', 0):+.2f}% |
| 盈亏比 | {validation.get('profit_ratio', 0):.2f} |

"""
        content = content[:section_start] + new_section + content[section_end:]

    # 如果是T+10, 更新事后评分和综合判定
    if days == 10:
        # 更新事后评分区块
        post_section_start = content.find("## 事后评分 (T+10)")
        if post_section_start >= 0:
            post_section_end = content.find("\n---", post_section_start + 10)
            if post_section_end < 0:
                post_section_end = len(content)

            new_post_section = """## 事后评分 (T+10)

| 维度 | 评分(1-5) | 依据 |
|------|----------|------|
"""
            for dim_name, dim_data in post["dimensions"].items():
                new_post_section += f"| {dim_name} | {dim_data['score']}/5 | {dim_data['reason']} |\n"
            new_post_section += f"| **总分** | **{post['total']}/25** | **{post['label']}** |\n"

            content = content[:post_section_start] + new_post_section + content[post_section_end:]

        # 更新综合判定
        combo_old = re.search(r'\*\*本笔判定\*\*:.*', content)
        if combo_old:
            new_combo = f"**本笔判定**: 事前{pre_total}分({pre_label}) + 事后{post['total']}分({post['label']}) = {combo}"
            content = content[:combo_old.start()] + new_combo + content[combo_old.end():]

    # 更新frontmatter状态(只能递进，不能回退)
    STATE_ORDER = {"draft": 0, "t5_done": 1, "t10_done": 2, "closed": 3}
    if days == 5:
        new_state = "t5_done"
    elif days == 10:
        new_state = "t10_done"
    else:
        new_state = f"t{days}_done"
    # 获取当前状态
    current_state_match = re.search(r'状态:\s*(\S+)', content)
    current_state = current_state_match.group(1) if current_state_match else "draft"
    current_level = STATE_ORDER.get(current_state, 0)
    new_level = STATE_ORDER.get(new_state, 0)
    if new_level > current_level:
        content = re.sub(r'状态:\s*\S+', f'状态: {new_state}', content)

    # 写入事后评分到frontmatter(T+10时)
    if days == 10:
        # 更新或插入事后评分字段
        post_fm_line = f"事后评分: {post['total']}"
        post_label_line = f'事后标签: "{post["label"]}"'
        if re.search(r'事后评分:', content):
            content = re.sub(r'事后评分:\s*\S+', post_fm_line, content)
            content = re.sub(r'事后标签:.*', post_label_line, content)
        else:
            # 在"状态:"行前插入
            content = re.sub(r'(状态:)', f'{post_fm_line}\n{post_label_line}\n\\1', content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


def generate_daily(date: str = None) -> str:
    """
    日度汇总: 扫描当日所有复盘卡, 生成汇总文件
    返回汇总文件路径
    """
    date = date or _today_str()
    ym = date[:7]
    rdir = _review_dir()
    stock_dir = os.path.join(rdir, ym, "个股")
    summary_dir = os.path.join(rdir, ym, "汇总")
    os.makedirs(summary_dir, exist_ok=True)

    # 扫描当日复盘卡
    date_compact = date.replace("-", "")
    cards = []
    if os.path.exists(stock_dir):
        for fname in os.listdir(stock_dir):
            if date_compact in fname and fname.endswith(".md"):
                fpath = os.path.join(stock_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    card_content = f.read()
                # 解析frontmatter
                fm_match = re.search(r'^---\s*\n(.*?)\n---', card_content, re.DOTALL)
                if fm_match:
                    fm = {}
                    for line in fm_match.group(1).strip().split("\n"):
                        if ":" in line:
                            key, val = line.split(":", 1)
                            fm[key.strip()] = val.strip().strip('"')
                    # 解析事前评分(优先从frontmatter读取)
                    pre_total = safe_float(fm.get("事前评分", 0), 0)
                    pre_label = fm.get("事前标签", "")
                    if not pre_total:
                        # 降级: 从正文中解析
                        pre_match = re.search(r'\*\*总分\*\* \|\s*\*\*(\d+)/30\*\* \|\s*\*\*(.*?)\*\*', card_content)
                        if pre_match:
                            pre_total = int(pre_match.group(1))
                            pre_label = pre_match.group(2)
                    # 解析事后评分
                    post_total = safe_float(fm.get("事后评分", ""), 0)
                    post_label = fm.get("事后标签", "")
                    cards.append({
                        "name": fm.get("股票名称", ""),
                        "code": fm.get("股票代码", ""),
                        "buy_price": fm.get("成交价格", ""),
                        "qty": fm.get("成交数量", ""),
                        "pre_total": int(pre_total) if pre_total else 0,
                        "pre_label": pre_label,
                        "post_total": int(post_total) if post_total else None,
                        "post_label": post_label or None,
                        "state": fm.get("状态", "draft"),
                        "filename": fname,
                    })

    # 生成汇总
    lines = []
    lines.append(f"# {date} 交易复盘汇总")
    lines.append("")

    # 今日交易概览
    lines.append("## 今日交易概览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 交易笔数 | 买{len(cards)}笔 |")
    lines.append("")

    # 交易明细
    lines.append("## 交易明细")
    lines.append("")
    lines.append("| 股票 | 方向 | 成交价 | 数量 | 事前评分 | 事后评分 | 状态 |")
    lines.append("|------|------|--------|------|---------|---------|------|")
    for c in cards:
        state_map = {"draft": "待验证", "t5_done": "T+5验证", "t10_done": "T+10验证", "closed": "已关闭"}
        post_state = state_map.get(c["state"], c["state"])
        post_str = f"{c['post_total']}/25 {c['post_label']}" if c.get("post_total") else "—"
        lines.append(f"| {c['name']}({c['code']}) | 买 | {c['buy_price']} | {c['qty']} | {c['pre_total']}/30 {c['pre_label']} | {post_str} | {post_state} |")
    lines.append("")

    # 事前评分分布
    excellent = sum(1 for c in cards if c["pre_total"] >= 24)
    good = sum(1 for c in cards if 18 <= c["pre_total"] < 24)
    bad = sum(1 for c in cards if c["pre_total"] < 18)
    total_cards = len(cards) or 1

    lines.append("## 事前评分分布")
    lines.append("")
    lines.append("| 等级 | 笔数 | 占比 |")
    lines.append("|------|------|------|")
    lines.append(f"| 🟢优质(24-30) | {excellent} | {excellent/total_cards*100:.0f}% |")
    lines.append(f"| 🟡一般(18-23) | {good} | {good/total_cards*100:.0f}% |")
    lines.append(f"| 🔴问题(6-17) | {bad} | {bad/total_cards*100:.0f}% |")
    lines.append("")

    # 纪律问题
    no_plan = [c for c in cards if c["pre_label"] == "🔴问题"]
    lines.append("## 纪律问题")
    lines.append("")
    if no_plan:
        for c in no_plan:
            lines.append(f"- ⚠️ {c['name']}({c['code']}) 事前{c['pre_total']}分🔴问题")
    else:
        lines.append("- 无纪律问题")
    lines.append("")

    # 异常交易
    exc_dir = os.path.join(rdir, "异常交易")
    exc_files = []
    if os.path.exists(exc_dir):
        for fname in os.listdir(exc_dir):
            if date_compact in fname and fname.endswith(".md"):
                exc_files.append(fname.replace(".md", ""))
    lines.append("## 异常交易")
    lines.append("")
    if exc_files:
        for ef in exc_files:
            lines.append(f"- 🚨 {ef}")
    else:
        lines.append("- 无异常交易")
    lines.append("")

    # 有效/无效
    effective = sum(1 for c in cards if c["pre_total"] >= 18)
    ineffective = total_cards - effective
    lines.append("## 有效交易/无效交易")
    lines.append("")
    lines.append("| 类型 | 笔数 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| 有效交易 | {effective} | 事前≥18 |")
    lines.append(f"| 无效交易 | {ineffective} | 事前<18 |")
    lines.append(f"| 有效占比 | {effective/total_cards*100:.0f}% | 目标>60% |")
    lines.append("")

    # 行动清单
    lines.append("## 行动清单")
    lines.append("")
    lines.append("- [ ] ")
    lines.append("")

    # 关联复盘卡
    lines.append("## 关联复盘卡")
    lines.append("")
    for c in cards:
        base = c["filename"].replace(".md", "")
        lines.append(f"- [[个股/{base}]]")

    # 写入
    summary_path = os.path.join(summary_dir, f"{date}.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return summary_path


# ============================================================
# CLI入口
# ============================================================

def batch_audit(account: str = "", start_date: str = "", end_date: str = "",
                force: bool = False, template_version: str = "v3") -> dict:
    """
    V3 批量审计入口: 从MySQL交易表读取未审计交易，逐笔调用 insert_audit_from_trade()
    account: 账户ID(空=所有账户)
    start_date/end_date: 交易日期范围
    force: True=强制重写已有审计记录
    template_version: v3(默认)

    返回: {"processed": int, "inserted": int, "skipped": int, "errors": list}
    """
    from trade_audit_sql import get_conn, insert_audit_log

    stats = {"processed": 0, "inserted": 0, "skipped": 0, "errors": []}

    try:
        with get_conn() as conn:
            # 从平安交易表读取已完成的买卖对(FIFO结果)
            # 这里调用 calc_pingan_pnl 的适配层
            trades, fetch_errors = _fetch_completed_trades(conn, account, start_date, end_date)
            stats["errors"].extend(fetch_errors)
            stats["processed"] = len(trades)

            for trade in trades:
                result = insert_audit_from_trade(trade, db_conn=conn, force=force)
                if result["status"] == "inserted":
                    stats["inserted"] += 1
                elif result["status"] == "skipped_exists":
                    stats["skipped"] += 1
                else:
                    stats["errors"].append(f"{trade.get('stock_code','')}: {result['status']}")

            # 记录审计日志
            insert_audit_log(
                conn, mode="batch" if not force else "force",
                total_processed=stats["processed"],
                total_inserted=stats["inserted"],
                total_skipped=stats["skipped"],
                errors="; ".join(stats["errors"][:10]),
            )

    except Exception as e:
        stats["errors"].append(f"batch_audit error: {e}")

    return stats


def _fetch_completed_trades(conn, account: str = "", start_date: str = "", end_date: str = "") -> tuple:
    """
    从MySQL交易表获取已完成的买卖交易对(用于batch_audit)
    优先使用 calc_pnl_for_audit 的精确FIFO配对，fallback到简化版
    返回 (trades, errors)。trades 每个 dict 包含 insert_audit_from_trade 所需字段。
    未配对成功的卖出记录标记 _needs_fifo=True, 将被 insert_audit_from_trade 拦截。
    """
    trades = []
    errors = []

    # ---- 优先: 使用 calc_pnl_for_audit 精确FIFO配对 ----
    try:
        from calc_pingan_pnl import calc_pnl_for_audit

        table_account_map = {
            "pingan_normal_trade": "normal",
            "pingan_margin_trade": "margin",
        }
        # 如果指定了account, 只查对应表
        if account == "normal":
            tables = ["pingan_normal_trade"]
        elif account == "margin":
            tables = ["pingan_margin_trade"]
        else:
            tables = list(table_account_map.keys())

        for table_name in tables:
            tag = table_account_map[table_name]
            try:
                audit_trades = calc_pnl_for_audit(table_name, account_tag=tag)
                for t in audit_trades:
                    # 日期范围过滤
                    if start_date and t.get("sell_date", "") < start_date:
                        continue
                    if end_date and t.get("sell_date", "") > end_date:
                        continue
                    # 移除额外字段(buy_lots), 只保留insert_audit_from_trade所需的
                    t.pop("buy_lots", None)
                    trades.append(t)
            except Exception as e:
                errors.append(f"{table_name}(calc_pnl_for_audit): {e}")

        if trades or not errors:
            return trades, errors

    except ImportError:
        errors.append("calc_pingan_pnl not available, falling back to simplified matching")

    # ---- Fallback: 简化版配对 ----
    buy_abstracts = ('买入', '证券买入清算', '融资买入', '担保品买入', '证券买入清算(融资买入)')
    sell_abstracts = ('卖出', '证券卖出清算', '融券卖出', '卖券还款', '担保品卖出', '证券卖出清算(卖券还款)')

    for table_name in ["pingan_normal_trade", "pingan_margin_trade"]:
        try:
            with conn.cursor() as cur:
                where_clauses = []
                params = []
                if account:
                    where_clauses.append("account = %s")
                    params.append(account)
                if start_date:
                    where_clauses.append("posting_date >= %s")
                    params.append(start_date)
                if end_date:
                    where_clauses.append("posting_date <= %s")
                    params.append(end_date)

                where = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
                other_fee_col = "0 AS other_fee" if table_name == "pingan_normal_trade" else "other_fee"

                cur.execute(f"""
                    SELECT posting_date, abstract, stock_code, stock_name,
                           shares, price, amount, commission, stamp_tax,
                           transfer_fee, {other_fee_col}
                    FROM {table_name}
                    WHERE 1=1{where}
                    ORDER BY posting_date, stock_code
                """, params)
                rows = cur.fetchall()

                buy_pool = {}
                for row in rows:
                    posting_date, abstract, stock_code, stock_name, \
                        shares, price, amount, commission, stamp_tax, \
                        transfer_fee, other_fee = row

                    if not stock_code:
                        continue

                    fee_total = float((commission or 0) + (stamp_tax or 0) + (transfer_fee or 0) + (other_fee or 0))

                    if abstract in buy_abstracts:
                        buy_pool.setdefault(stock_code, []).append({
                            "date": str(posting_date),
                            "price": float(price) if price else 0,
                            "shares": int(shares) if shares else 0,
                            "amount": float(amount) if amount else 0,
                            "fees": fee_total,
                        })

                    elif abstract in sell_abstracts:
                        sell_info = {
                            "date": str(posting_date),
                            "price": float(price) if price else 0,
                            "shares": int(shares) if shares else 0,
                            "amount": float(amount) if amount else 0,
                            "fees": fee_total,
                        }

                        pool = buy_pool.get(stock_code, [])
                        matched_buy = pool.pop(0) if pool else None

                        if matched_buy:
                            total_fees = matched_buy["fees"] + sell_info["fees"]
                            try:
                                from datetime import datetime
                                bd = datetime.strptime(matched_buy["date"], "%Y-%m-%d")
                                sd = datetime.strptime(sell_info["date"], "%Y-%m-%d")
                                hold_days = (sd - bd).days
                            except Exception:
                                hold_days = 0

                            realized_pnl = sell_info["amount"] - matched_buy["amount"] - total_fees
                            buy_amount = matched_buy["amount"]
                            pnl_rate = round(realized_pnl / buy_amount * 100, 2) if buy_amount > 0 else 0

                            trades.append({
                                "account": table_name.split("_")[1],
                                "stock_code": stock_code,
                                "stock_name": stock_name or stock_code,
                                "buy_date": matched_buy["date"],
                                "buy_price": matched_buy["price"],
                                "buy_shares": matched_buy["shares"],
                                "buy_amount": buy_amount,
                                "sell_date": sell_info["date"],
                                "sell_price": sell_info["price"],
                                "sell_shares": sell_info["shares"],
                                "sell_amount": sell_info["amount"],
                                "hold_days": hold_days,
                                "realized_pnl": realized_pnl,
                                "pnl_rate": pnl_rate,
                                "total_fees": total_fees,
                                "sell_reason": abstract,
                                "has_plan": False,
                                "stop_price": 0,
                                "total_assets": 0,
                                "position_ratio": 0,
                            })

                            if matched_buy["shares"] > sell_info["shares"] and sell_info["shares"] > 0:
                                remaining = matched_buy["shares"] - sell_info["shares"]
                                pool.insert(0, {
                                    "date": matched_buy["date"],
                                    "price": matched_buy["price"],
                                    "shares": remaining,
                                    "amount": round(matched_buy["price"] * remaining, 2),
                                    "fees": round(matched_buy["fees"] * remaining / matched_buy["shares"], 2),
                                })
                        else:
                            trades.append({
                                "account": table_name.split("_")[1],
                                "stock_code": stock_code,
                                "stock_name": stock_name or stock_code,
                                "buy_date": "",
                                "buy_price": 0,
                                "buy_shares": 0,
                                "buy_amount": 0,
                                "sell_date": sell_info["date"],
                                "sell_price": sell_info["price"],
                                "sell_shares": sell_info["shares"],
                                "sell_amount": sell_info["amount"],
                                "hold_days": 0,
                                "realized_pnl": 0,
                                "pnl_rate": 0,
                                "total_fees": sell_info["fees"],
                                "sell_reason": abstract,
                                "has_plan": False,
                                "stop_price": 0,
                                "total_assets": 0,
                                "position_ratio": 0,
                                "_needs_fifo": True,
                            })
        except Exception as e:
            errors.append(f"{table_name}(fallback): {e}")

    return trades, errors


def _parse_days_list(days: str) -> list:
    """解析 CLI days 字符串，例如 '20,60'。"""
    if isinstance(days, (list, tuple)):
        return [int(d) for d in days]
    parsed = []
    for part in str(days or "").split(","):
        part = part.strip()
        if not part:
            continue
        parsed.append(int(part))
    return parsed or [20, 60]


def batch_update_post_validation(conn, days_list=None, account: str = "",
                                 start_date: str = "", end_date: str = "",
                                 recalc_verdict: bool = True) -> dict:
    """
    批量补充事后验证字段(从卖出日起算T+N)。
    conn: 复用外部 MySQL 连接，便于 cron 和测试注入。
    recalc_verdict: True=重算sell_verdict(修复missed_profit误判)
    """
    from trade_audit_sql import update_post_validation

    days_list = days_list or [5, 10, 20, 60]
    stats = {"processed": 0, "updated": 0, "skipped": 0, "errors": []}

    where_clauses = ["1=1"]
    params = []
    if account:
        where_clauses.append("account = %s")
        params.append(account)
    if start_date:
        where_clauses.append("sell_date >= %s")
        params.append(start_date)
    if end_date:
        where_clauses.append("sell_date <= %s")
        params.append(end_date)
    # 只处理缺失事后数据的记录
    need_post = []
    for d in days_list:
        if d == 60:
            need_post.append("post60_chg IS NULL")
        else:
            need_post.append(f"(post{d}_close IS NULL OR post{d}_chg IS NULL)")
    if need_post:
        where_clauses.append(f"({' OR '.join(need_post)})")

    query = (
        "SELECT id, stock_code, buy_date, buy_price, stop_loss_price, "
        "sell_price, max_price_hold, sell_date "
        f"FROM trade_audit WHERE {' AND '.join(where_clauses)} "
        "ORDER BY sell_date"
    )

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    stats["processed"] = len(rows)
    for row in rows:
        audit_id, stock_code, buy_date, buy_price, stop_price, sell_price, max_price_hold, _sell_date = row
        try:
            post_validation = fetch_post_validation(
                stock_code, str(buy_date), float(buy_price),
                float(stop_price or 0), 0,
                days_list=days_list,
                sell_price=float(sell_price or 0),
                sell_date=str(_sell_date) if _sell_date else None,
            )
            if post_validation.get("error"):
                stats["skipped"] += 1
                continue
            update_data = _flatten_post_validation_for_update(post_validation, days_list)

            # 写入持仓期最高价(如果之前没有)
            hold_max = post_validation.get("hold_period_max_price")
            if hold_max and not max_price_hold:
                update_data["max_price_hold"] = hold_max

            # 重算sell_verdict
            if recalc_verdict:
                p5_close = update_data.get("post5_close")
                p10_close = update_data.get("post10_close")
                post20_high = update_data.get("post20_high")
                hold_for_verdict = hold_max or (float(max_price_hold) if max_price_hold else float(sell_price or 0))
                if p5_close is not None or p10_close is not None:
                    update_data["sell_verdict"] = calc_sell_verdict(
                        float(sell_price or 0),
                        p5_close, p10_close,
                        post20_high,
                        hold_for_verdict,
                        stop_price=float(stop_price or 0),
                        buy_price=float(buy_price or 0),
                    )

            if update_post_validation(conn, audit_id, update_data):
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["errors"].append(f"{audit_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="交易复盘评分引擎 + 复盘卡生成器 (V3)")
    sub = parser.add_subparsers(dest="command")

    # draft: 新建复盘卡
    p_draft = sub.add_parser("draft", help="T+0草稿: 新建复盘卡")
    p_draft.add_argument("--code", required=True, help="股票代码")
    p_draft.add_argument("--name", required=True, help="股票名称")
    p_draft.add_argument("--price", type=float, required=True, help="买入价格")
    p_draft.add_argument("--qty", type=int, required=True, help="买入数量")
    p_draft.add_argument("--date", default=None, help="成交日期 YYYY-MM-DD")
    p_draft.add_argument("--time", default=None, help="成交时间 HH:MM")
    p_draft.add_argument("--stop", type=float, default=0, help="止损价")
    p_draft.add_argument("--target", type=float, default=0, help="目标价")
    p_draft.add_argument("--plan", action="store_true", help="有交易计划")
    p_draft.add_argument("--strategy", default="", help="绑定策略")
    p_draft.add_argument("--entry", default="", help="入场模式")
    p_draft.add_argument("--assets", type=float, default=0, help="总资产")
    p_draft.add_argument("--account", default="", help="账户名")
    p_draft.add_argument("--v3", action="store_true", help="使用V3模板(10分制)")

    # update: T+N事后更新
    p_update = sub.add_parser("update", help="T+N事后更新")
    p_update.add_argument("--file", required=True, help="复盘卡文件路径")
    p_update.add_argument("--days", type=int, default=5, choices=[5, 10, 20, 60], help="验证天数")

    # daily: 日度汇总
    p_daily = sub.add_parser("daily", help="日度汇总")
    p_daily.add_argument("--date", default=None, help="日期 YYYY-MM-DD")

    # score: 纯评分(不生成文件)
    p_score = sub.add_parser("score", help="纯评分(不生成文件)")
    p_score.add_argument("--code", required=True, help="股票代码")
    p_score.add_argument("--price", type=float, required=True, help="买入价格")
    p_score.add_argument("--qty", type=int, default=100, help="数量")
    p_score.add_argument("--stop", type=float, default=0, help="止损价")
    p_score.add_argument("--assets", type=float, default=0, help="总资产")
    p_score.add_argument("--plan", action="store_true", help="有交易计划")
    p_score.add_argument("--v3", action="store_true", help="使用V3评分(10分制)")

    # audit: V3批量审计
    p_audit = sub.add_parser("audit", help="V3批量审计: 从MySQL交易表生成审计记录")
    p_audit.add_argument("--account", default="", help="账户ID(空=所有)")
    p_audit.add_argument("--start", default="", help="开始日期 YYYY-MM-DD")
    p_audit.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    p_audit.add_argument("--force", action="store_true", help="强制重写已有记录")
    p_audit.add_argument("--update-post", action="store_true", help="补充T+20/T+60事后验证字段")
    p_audit.add_argument("--days", default="20,60", help="补数据窗口，逗号分隔，如20,60")

    # audit-single: V3单笔审计(用于调试)
    p_audit1 = sub.add_parser("audit-single", help="V3单笔审计(调试用)")
    p_audit1.add_argument("--code", required=True, help="股票代码")
    p_audit1.add_argument("--name", default="", help="股票名称")
    p_audit1.add_argument("--buy-date", required=True, help="买入日期 YYYY-MM-DD")
    p_audit1.add_argument("--buy-price", type=float, required=True, help="买入价格")
    p_audit1.add_argument("--sell-date", default="", help="卖出日期")
    p_audit1.add_argument("--sell-price", type=float, default=0, help="卖出价格")
    p_audit1.add_argument("--shares", type=int, default=0, help="数量")
    p_audit1.add_argument("--pnl", type=float, default=0, help="已实现盈亏")
    p_audit1.add_argument("--stop", type=float, default=0, help="止损价")
    p_audit1.add_argument("--plan", action="store_true", help="有交易计划")
    p_audit1.add_argument("--account", default="cli", help="账户标识")
    p_audit1.add_argument("--force", action="store_true", help="强制重写")

    args = parser.parse_args()

    if args.command == "draft":
        tv = "v3" if args.v3 else "v2"
        path = generate_draft(
            code=args.code, name=args.name, buy_price=args.price,
            qty=args.qty, trade_date=args.date, trade_time=args.time,
            stop_price=args.stop, target_price=args.target,
            has_plan=args.plan, strategy=args.strategy,
            entry_mode=args.entry, total_assets=args.assets,
            account=args.account, template_version=tv,
        )
        print(f"复盘卡已生成({tv}): {path}")

    elif args.command == "update":
        result = update_post_review(args.file, args.days)
        print(f"复盘卡已更新(T+{args.days}): {result}")

    elif args.command == "daily":
        path = generate_daily(args.date)
        print(f"日度汇总已生成: {path}")

    elif args.command == "score":
        snapshot = fetch_pre_snapshot(args.code, _today_str())
        trade_info = {
            "buy_price": args.price,
            "qty": args.qty,
            "stop_price": args.stop,
            "has_plan": args.plan,
            "total_assets": args.assets,
            "position_ratio": args.price * args.qty / args.assets if args.assets > 0 else 0,
        }
        if args.v3:
            # V3 10分制评分
            indicators = snapshot.get("indicators", {})
            indices = snapshot.get("indices", {})
            config = load_config(CONFIG_PATH)
            stk_trend = classify_stk_trend(indicators)
            mkt_trend = classify_mkt_trend(indices, config)
            trade_dir = calc_trade_direction(stk_trend, mkt_trend)
            boll_pctb = 50.0
            boll_upper = indicators.get("BOLL_upper")
            boll_lower = indicators.get("BOLL_lower")
            if boll_upper and boll_lower and (boll_upper - boll_lower) > 0:
                boll_pctb = (args.price - boll_lower) / (boll_upper - boll_lower) * 100
            scoring_data = {
                "indicators": indicators,
                "stk_trend": stk_trend,
                "mkt_trend": mkt_trend,
                "boll_pctb": boll_pctb,
                "is_chase": snapshot.get("chase_detect", {}).get("is_chase", False),
                "entry_signal": "CLI",
                "sector_pct_rank": 50.0,
                "trade_direction": trade_dir,
                "sell_reason": "", "sell_trigger": "subjective",
                "sell_verdict": "normal",
                "has_plan": args.plan,
                "position_rule": "pass",
                "stop_loss_set": 1 if args.stop > 0 else 0,
                "stop_loss_pct": 0,
                "single_risk_pct": 0,
                "stk_atr_stop": None,
            }
            score = audit_score(scoring_data, config)
            print(f"V3评分: {score['total_score']}/10")
            print(f"  入场: {score['entry_score']}/3  {score['entry_detail']}")
            print(f"  出场: {score['exit_score']}/3  {score['exit_detail']}")
            print(f"  纪律: {score['discipline_score']}/2  {score['discipline_detail']}")
            print(f"  风控: {score['risk_control_score']}/2  {score['risk_control_detail']}")
            print(f"  趋势: {stk_trend}  方向: {trade_dir}")
        else:
            # V2 30分制评分(保持不变)
            pre = pre_score(snapshot, trade_info)
            print(f"事前评分: {pre['total']}/30 {pre['label']}")
            for dim, data in pre["dimensions"].items():
                print(f"  {dim}: {data['score']}/5 - {data['reason']}")

    elif args.command == "audit":
        if args.update_post:
            from trade_audit_sql import get_conn
            with get_conn() as conn:
                stats = batch_update_post_validation(
                    conn,
                    days_list=_parse_days_list(args.days),
                    account=args.account,
                    start_date=args.start,
                    end_date=args.end,
                )
            print(f"事后验证补数据完成: 处理{stats['processed']}笔, "
                  f"更新{stats['updated']}笔, 跳过{stats['skipped']}笔")
        else:
            stats = batch_audit(
                account=args.account, start_date=args.start,
                end_date=args.end, force=args.force,
            )
            print(f"批量审计完成: 处理{stats['processed']}笔, "
                  f"写入{stats['inserted']}笔, 跳过{stats['skipped']}笔")
        if stats["errors"]:
            print(f"错误({len(stats['errors'])}条):")
            for e in stats["errors"][:10]:
                print(f"  - {e}")

    elif args.command == "audit-single":
        stock_name = args.name or args.code
        trade = {
            "account": args.account,
            "stock_code": args.code,
            "stock_name": stock_name,
            "buy_date": args.buy_date,
            "buy_price": args.buy_price,
            "buy_shares": args.shares,
            "buy_amount": args.buy_price * args.shares,
            "sell_date": args.sell_date,
            "sell_price": args.sell_price,
            "sell_shares": args.shares,
            "sell_amount": args.sell_price * args.shares,
            "hold_days": 0,
            "realized_pnl": args.pnl,
            "pnl_rate": round(args.pnl / (args.buy_price * args.shares) * 100, 2) if args.buy_price * args.shares > 0 else 0,
            "total_fees": 0,
            "sell_reason": "",
            "has_plan": args.plan,
            "stop_price": args.stop,
            "total_assets": 0,
            "position_ratio": 0,
        }
        result = insert_audit_from_trade(trade, force=args.force)
        if result["status"] == "inserted":
            rec = result["record"]
            print(f"审计完成: id={result['audit_id']}")
            print(f"  四分法: {rec.get('trade_category')}")
            print(f"  评分: {rec.get('total_score')}/10")
            print(f"  反馈: {rec.get('feedback_action')}")
        elif result["status"] == "skipped_exists":
            print("已存在，跳过(用--force强制重写)")
        else:
            print(f"审计失败: {result['status']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
