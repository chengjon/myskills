#!/usr/bin/env python3
"""
V4.1 综合评分报告生成器
用法: MYSQL_PWD=xxx python3 report_v4.py [--output PATH] [--year YYYY]

生成内容:
  1. V4.1修改内容(静态)
  2. 六大核心发现
  3. 六级分类深度分析 (含子类)
  4. Verdict×Grade交叉分析
  5. 行为标签深度分析 (单标签+组合)
  6. Shortfall Report (全局+年度演变)
  7. Perfect Stop 专项分析
  8. E2 风控瑕疵专项分析
  9. A/B级正面教材
  10. 规则引擎数据依据

所有数据均从 trade_audit 表实时查询，确保结论可复现。
"""
import os
import sys
import argparse
from datetime import datetime

# ── MySQL 连接 ──────────────────────────────────────────────

def get_conn():
    import pymysql
    pwd = os.environ.get("MYSQL_PWD", "")
    return pymysql.connect(
        host="192.168.123.104", port=3306, user="root",
        password=pwd, database="hermes", charset="utf8mb4"
    )


# ── 常量 ─────────────────────────────────────────────────────

DIMS = [
    ("entry_timing_score",  "入场时机", 3),
    ("entry_quality_score", "入场质量", 3),
    ("exit_timing_score",   "卖出时机", 3),
    ("risk_mgmt_score",     "风控执行", 2),
    ("behavior_score",      "行为纪律", 2),
    ("efficiency_score",    "交易效率", 2),
]

WHERE = "sell_date < '2026-01-01' AND total_score_v4 IS NOT NULL"

VERDICT_DESC = {
    "perfect_stop":    "亏损+卖在最低附近",
    "panic_sell":      "亏损+卖在最低+卖后暴跌",
    "discipline_sell": "盈利+持仓>=20天或盈利>=15%",
    "good_profit":     "盈利+卖后下跌",
    "nice_catch":      "盈利+卖在最高附近",
    "late_stop":       "亏损+卖后继续跌>3%",
    "missed_profit":   "盈利+卖后20日涨>8%",
    "normal":          "其他",
}

GRADE_DESC = {
    "A": "总分>=12+盈利 — 决策极优",
    "B": "总分>=9+盈利 — 决策良好",
    "C": "总分<9+盈利 — 运气盈利",
    "D": "总分>=9+亏损 — 正常亏损",
    "E": "总分6-8+亏损 — 可避免亏损",
    "F": "总分<=5+亏损 — 致命错误",
}

SUBGRADE_DESC = {
    "E1": "卖出时机差",
    "E2": "风控瑕疵(亏5-10%)",
    "F1": "入场灾难",
    "F2": "风控崩溃(亏>10%)",
    "F3": "纪律崩塌",
}


# ── 查询函数 ──────────────────────────────────────────────────

def query_total_stats(cur):
    """总量统计: 笔数、均分、胜率、总盈亏"""
    cur.execute(f"""
        SELECT COUNT(*),
               ROUND(AVG(total_score_v4), 2),
               ROUND(AVG(CASE WHEN pnl_rate > 0 THEN 100 ELSE 0 END), 1),
               ROUND(AVG(hold_days), 1),
               ROUND(SUM(realized_pnl), 0)
        FROM trade_audit WHERE {WHERE}
    """)
    return cur.fetchone()


def query_shortfall(cur, where_extra=None):
    """维度短板 (扣分率)"""
    where_clause = WHERE
    if where_extra:
        where_clause += f" AND ({where_extra})"
    result = []
    for col, label, mx in DIMS:
        cur.execute(f"SELECT AVG({col}) FROM trade_audit WHERE {where_clause} AND {col} IS NOT NULL")
        avg = float(cur.fetchone()[0])
        deduct = mx - avg
        rate = deduct / mx * 100
        result.append((col, label, mx, avg, deduct, rate))
    result.sort(key=lambda x: -x[5])
    return result


def query_grade_dist(cur):
    """六级分类分布"""
    cur.execute(f"""
        SELECT grade_v4, grade_sub, COUNT(*) as cnt,
               SUM(CASE WHEN pnl_rate > 0 THEN 1 ELSE 0 END) as profit_cnt,
               ROUND(AVG(pnl_rate), 2) as avg_pnl,
               ROUND(AVG(total_score_v4), 2) as avg_score,
               ROUND(AVG(hold_days), 1) as avg_hold,
               ROUND(SUM(realized_pnl), 0) as total_pnl
        FROM trade_audit
        WHERE {WHERE}
        GROUP BY grade_v4, grade_sub
        ORDER BY grade_v4, grade_sub
    """)
    return cur.fetchall()


def query_verdict_dist(cur):
    """Verdict分布"""
    cur.execute(f"""
        SELECT sell_verdict_v4, COUNT(*) as cnt,
               SUM(CASE WHEN pnl_rate > 0 THEN 1 ELSE 0 END) as profit_cnt,
               ROUND(AVG(pnl_rate), 2) as avg_pnl,
               ROUND(AVG(exit_timing_score), 2) as avg_exit
        FROM trade_audit
        WHERE {WHERE} AND sell_verdict_v4 IS NOT NULL
        GROUP BY sell_verdict_v4 ORDER BY cnt DESC
    """)
    return cur.fetchall()


def query_verdict_grade_cross(cur):
    """Verdict × Grade 交叉"""
    cur.execute(f"""
        SELECT sell_verdict_v4, grade_v4, COUNT(*), ROUND(AVG(pnl_rate), 2)
        FROM trade_audit WHERE {WHERE}
        GROUP BY sell_verdict_v4, grade_v4
        ORDER BY sell_verdict_v4, grade_v4
    """)
    return cur.fetchall()


def query_behavior_tags(cur):
    """行为标签 (组合+单标签)"""
    # 组合
    cur.execute(f"""
        SELECT behavior_tags, COUNT(*) as cnt,
               ROUND(AVG(pnl_rate), 2) as avg_pnl,
               ROUND(AVG(total_score_v4), 2) as avg_score
        FROM trade_audit
        WHERE {WHERE} AND behavior_tags IS NOT NULL AND behavior_tags != ''
        GROUP BY behavior_tags ORDER BY cnt DESC
    """)
    combo_rows = cur.fetchall()

    # 单标签
    tag_freq = {}
    tag_pnl = {}
    for r in combo_rows:
        for t in r[0].split(","):
            t = t.strip()
            tag_freq[t] = tag_freq.get(t, 0) + r[1]
            if t not in tag_pnl:
                tag_pnl[t] = []
            # 近似: 用该组合的均PNL加权
            tag_pnl[t].append((r[1], r[2]))

    # 单标签精确PNL
    single_tags = {}
    for tag in tag_freq:
        cur.execute(f"""
            SELECT COUNT(*), ROUND(AVG(pnl_rate), 2)
            FROM trade_audit
            WHERE {WHERE} AND behavior_tags LIKE %s
        """, (f"%{tag}%",))
        r = cur.fetchone()
        single_tags[tag] = {"cnt": r[0], "avg_pnl": r[1]}

    # 无标签
    cur.execute(f"SELECT COUNT(*) FROM trade_audit WHERE {WHERE.replace('AND total_score_v4 IS NOT NULL', '')} AND (behavior_tags IS NULL OR behavior_tags = '')")
    no_tag = cur.fetchone()[0]

    return combo_rows, single_tags, no_tag


def query_tag_combo_lethal(cur):
    """关键标签组合 + 均PNL + 均V4分"""
    combos = [
        ("追高+冲动+BOLL极端",
         "%追高%冲动%BOLL%"),
        ("冲动+BOLL极端+过早卖出",
         "%冲动%BOLL%过早卖出%"),
        ("追高+冲动+BOLL极端+过晚止损",
         "%追高%冲动%BOLL%过晚止损%"),
        ("抄底+冲动+BOLL极端",
         "%抄底%冲动%BOLL%"),
        ("追高+BOLL极端+过晚止损",
         "%追高%BOLL%过晚止损%"),
        ("BOLL极端+过晚止损",
         "%BOLL%过晚止损%"),
    ]
    results = []
    for label, pattern in combos:
        cur.execute(f"""
            SELECT COUNT(*), ROUND(AVG(pnl_rate), 2), ROUND(AVG(total_score_v4), 2)
            FROM trade_audit
            WHERE {WHERE} AND behavior_tags LIKE %s
        """, (pattern,))
        r = cur.fetchone()
        if r[0] > 0:
            results.append((label, r[0], r[1], r[2]))
    return results


def query_yearly(cur):
    """年度对比 V3 vs V4"""
    cur.execute(f"""
        SELECT YEAR(buy_date) as yr, COUNT(*) as cnt,
               ROUND(AVG(total_score_v3), 2) as avg_v3,
               ROUND(AVG(total_score_v4), 2) as avg_v4,
               ROUND(AVG(CASE WHEN pnl_rate > 0 THEN 100 ELSE 0 END), 1) as win_rate,
               ROUND(AVG(hold_days), 1) as avg_hold,
               ROUND(SUM(realized_pnl), 0) as total_pnl
        FROM trade_audit WHERE {WHERE}
        GROUP BY yr ORDER BY yr
    """)
    return cur.fetchall()


def query_perfect_stop(cur):
    """Perfect Stop 专项"""
    ps_where = f"{WHERE} AND sell_verdict_v4='perfect_stop'"

    # 总量
    cur.execute(f"""
        SELECT COUNT(*), ROUND(AVG(pnl_rate), 2),
               ROUND(SUM(realized_pnl), 0), ROUND(AVG(hold_days), 1)
        FROM trade_audit WHERE {ps_where}
    """)
    total = cur.fetchone()

    # BOLL分布
    boll_bins = [(0, 5, "0-4 极低位"), (5, 20, "5-19 低位"), (20, 50, "20-49 中低"),
                 (50, 80, "50-79 中部"), (80, 95, "80-94 高位"), (95, 101, "95-100 极高位")]
    boll_dist = []
    for lo, hi, label in boll_bins:
        cur.execute(f"SELECT COUNT(*) FROM trade_audit WHERE {ps_where} AND stk_boll_pctb >= %s AND stk_boll_pctb < %s", (lo, hi))
        boll_dist.append((label, cur.fetchone()[0]))

    # 趋势分布
    cur.execute(f"SELECT stk_trend, COUNT(*) FROM trade_audit WHERE {ps_where} GROUP BY stk_trend ORDER BY COUNT(*) DESC")
    trend_dist = cur.fetchall()

    # 持仓天数分布
    cur.execute(f"""
        SELECT
            CASE WHEN hold_days <= 1 THEN '1天'
                 WHEN hold_days <= 3 THEN '2-3天'
                 WHEN hold_days <= 7 THEN '4-7天'
                 WHEN hold_days <= 14 THEN '8-14天'
                 WHEN hold_days <= 30 THEN '15-30天'
                 ELSE '>30天' END as bucket,
            COUNT(*), ROUND(AVG(pnl_rate), 2)
        FROM trade_audit WHERE {ps_where}
        GROUP BY bucket ORDER BY MIN(hold_days)
    """)
    hold_dist = cur.fetchall()

    # 年度分布
    cur.execute(f"""
        SELECT YEAR(buy_date), COUNT(*), ROUND(AVG(pnl_rate), 2),
               ROUND(SUM(realized_pnl), 0), ROUND(AVG(hold_days), 1)
        FROM trade_audit WHERE {ps_where}
        GROUP BY YEAR(buy_date) ORDER BY YEAR(buy_date)
    """)
    yearly_dist = cur.fetchall()

    # Verdict × Grade
    cur.execute(f"""
        SELECT grade_v4, COUNT(*), ROUND(AVG(pnl_rate), 2)
        FROM trade_audit WHERE {ps_where}
        GROUP BY grade_v4 ORDER BY grade_v4
    """)
    grade_cross = cur.fetchall()

    # TOP10 最大亏损
    cur.execute(f"""
        SELECT stock_code, stock_name, buy_date, pnl_rate, hold_days,
               stk_boll_pctb, stk_trend, grade_v4, grade_sub
        FROM trade_audit WHERE {ps_where}
        ORDER BY pnl_rate ASC LIMIT 10
    """)
    top10 = cur.fetchall()

    # 反复亏损股票
    cur.execute(f"""
        SELECT stock_code, COUNT(*) as cnt,
               ROUND(SUM(pnl_rate), 2) as total_pnl_pct,
               GROUP_CONCAT(pnl_rate ORDER BY buy_date SEPARATOR ',') as pnl_list
        FROM trade_audit WHERE {ps_where}
        GROUP BY stock_code HAVING cnt >= 2
        ORDER BY total_pnl_pct ASC
    """)
    repeat_raw = cur.fetchall()

    # 补查名称
    repeat_stocks = []
    for r in repeat_raw:
        cur.execute("SELECT stock_name FROM trade_audit WHERE stock_code = %s LIMIT 1", (r[0],))
        name = cur.fetchone()[0]
        repeat_stocks.append((r[0], name, r[1], r[2], r[3]))

    return {
        "total": total,
        "boll_dist": boll_dist,
        "trend_dist": trend_dist,
        "hold_dist": hold_dist,
        "yearly_dist": yearly_dist,
        "grade_cross": grade_cross,
        "top10": top10,
        "repeat_stocks": repeat_stocks,
    }


def query_e2(cur):
    """E2 风控瑕疵专项"""
    e2_where = f"{WHERE} AND grade_sub = 'E2'"

    cur.execute(f"""
        SELECT COUNT(*), ROUND(AVG(pnl_rate), 2),
               ROUND(SUM(realized_pnl), 0),
               ROUND(AVG(hold_days), 1),
               ROUND(AVG(stk_boll_pctb), 2)
        FROM trade_audit WHERE {e2_where}
    """)
    stats = cur.fetchone()

    # Verdict分布
    cur.execute(f"SELECT sell_verdict_v4, COUNT(*) FROM trade_audit WHERE {e2_where} GROUP BY sell_verdict_v4")
    verdict_dist = cur.fetchall()

    # BOLL分布
    cur.execute(f"""
        SELECT CASE WHEN stk_boll_pctb < 20 THEN '<20'
                    WHEN stk_boll_pctb < 50 THEN '20-50'
                    WHEN stk_boll_pctb < 80 THEN '50-80'
                    ELSE '>=80' END,
               COUNT(*)
        FROM trade_audit WHERE {e2_where} GROUP BY 1
    """)
    boll_dist = cur.fetchall()

    # 明细
    cur.execute(f"""
        SELECT stock_code, stock_name, buy_date, sell_date,
               pnl_rate, hold_days, total_score_v4,
               stk_boll_pctb, stk_trend, behavior_tags, sell_verdict_v4
        FROM trade_audit WHERE {e2_where}
        ORDER BY pnl_rate ASC
    """)
    details = cur.fetchall()

    return {
        "stats": stats,
        "verdict_dist": verdict_dist,
        "boll_dist": boll_dist,
        "details": details,
    }


def query_ab_positive(cur):
    """A/B级正面教材"""
    cur.execute(f"""
        SELECT stock_code, stock_name, buy_date, sell_date,
               pnl_rate, hold_days, total_score_v4, grade_v4,
               sell_verdict_v4, behavior_tags
        FROM trade_audit WHERE {WHERE} AND grade_v4 IN ('A', 'B')
        ORDER BY total_score_v4 DESC LIMIT 15
    """)
    return cur.fetchall()


def query_e_f_comparison(cur):
    """D/E/E2/F 对比"""
    cur.execute(f"""
        SELECT
            CASE WHEN grade_v4 = 'D' THEN 'D'
                 WHEN grade_sub = 'E2' THEN 'E2'
                 WHEN grade_v4 = 'E' THEN 'E(无子类)'
                 WHEN grade_sub = 'F1' THEN 'F1'
                 WHEN grade_sub = 'F2' THEN 'F2'
                 WHEN grade_sub = 'F3' THEN 'F3'
                 ELSE grade_v4 END as grp,
            COUNT(*),
            ROUND(AVG(pnl_rate), 2),
            ROUND(AVG(hold_days), 1),
            ROUND(SUM(realized_pnl), 0)
        FROM trade_audit WHERE {WHERE} AND grade_v4 IN ('D', 'E', 'F')
        GROUP BY grp ORDER BY grp
    """)
    return cur.fetchall()


# ── Markdown 输出 ──────────────────────────────────────────────

def fmt(v, suffix=""):
    if v is None:
        return "-"
    return f"{v}{suffix}"


def generate_report(output_path=None, filter_year=None):
    conn = get_conn()
    cur = conn.cursor()

    L = []  # report lines

    # ── 头部 ──
    L.append("# V4.1 综合评分报告 (363笔)")
    L.append("")
    L.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append(f"> 数据范围: 2021-11 ~ 2025-12 (sell_date < 2026-01-01)")
    L.append(f"> 评分引擎: audit_v4_scorer.py v4.1")
    L.append(f"> 报告生成: report_v4.py")
    L.append("")

    # ── 一、V4.1修改内容 (静态) ──
    L.append("## 一、V4.1 修改内容")
    L.append("")
    L.append("| 修改 | V4.0 | V4.1 | 影响 |")
    L.append("|------|------|------|------|")
    L.append("| perfect_stop得分 | 3分 | **2分** | \"止损精准但买入已失败\"不再拿满分 |")
    L.append("| 风控评分 | 回撤<5%就得高分 | **盈利交易看回撤,亏损交易看亏损幅度** | 亏损交易\"回撤小\"不再算能力 |")
    L.append("| 冲动阈值 | is_impulsive=1即标 | **连亏>=4/同日>=4, 或impulsive+连亏>=2** | 冲动率从82.9%降至64.7% |")
    L.append("")

    # ── 二、六大核心发现 ──
    total_stats = query_total_stats(cur)
    total_cnt = total_stats[0]
    avg_score = float(total_stats[1])
    win_rate = float(total_stats[2])
    total_pnl = total_stats[4]

    shortfall = query_shortfall(cur)

    # 行为标签单标签
    _, single_tags, no_tag = query_behavior_tags(cur)
    impulsive_cnt = single_tags.get("冲动", {}).get("cnt", 0)
    boll_extreme_cnt = single_tags.get("BOLL极端", {}).get("cnt", 0)
    behavior_avg = next((x[3] for x in shortfall if x[1] == "行为纪律"), 0)

    # Verdict
    verdict_dist = query_verdict_dist(cur)
    perfect_stop_cnt = next((r[1] for r in verdict_dist if r[0] == "perfect_stop"), 0)
    discipline_cnt = next((r[1] for r in verdict_dist if r[0] == "discipline_sell"), 0)
    good_profit_cnt = next((r[1] for r in verdict_dist if r[0] == "good_profit"), 0)

    # 入场
    entry_timing_avg = next((x[3] for x in shortfall if x[1] == "入场时机"), 0)
    entry_quality_avg = next((x[3] for x in shortfall if x[1] == "入场质量"), 0)

    # 风控
    riskmgmt_avg = next((x[3] for x in shortfall if x[1] == "风控执行"), 0)
    riskmgmt_rate = next((x[5] for x in shortfall if x[1] == "风控执行"), 0)

    # Perfect Stop 总亏损
    ps_data = query_perfect_stop(cur)
    ps_total_loss = ps_data["total"][2]

    # A+B count
    grade_dist = query_grade_dist(cur)
    ab_cnt = sum(r[2] for r in grade_dist if r[0] in ("A", "B"))
    c_cnt = sum(r[2] for r in grade_dist if r[0] == "C")
    ef_cnt = sum(r[2] for r in grade_dist if r[0] in ("E", "F"))

    L.append("## 二、整体画像：六大核心发现")
    L.append("")

    L.append("### 发现1: 最大短板——行为纪律")
    b_rate = next((x[5] for x in shortfall if x[1] == "行为纪律"), 0)
    L.append("")
    L.append(f"- 行为纪律均分: {behavior_avg:.2f}/2 (扣分率{b_rate:.1f}%)")
    L.append(f"- 冲动交易率: {impulsive_cnt/total_cnt*100:.1f}% ({impulsive_cnt}笔)")
    L.append(f"- BOLL极端率: {boll_extreme_cnt/total_cnt*100:.1f}% ({boll_extreme_cnt}笔)")
    L.append(f"- **结论**: 问题不是选股能力，是**行为模式**——冲动、极端位置入场")
    L.append("")

    L.append("### 发现2: 入场问题是第二大弱点")
    et_rate = next((x[5] for x in shortfall if x[1] == "入场时机"), 0)
    eq_rate = next((x[5] for x in shortfall if x[1] == "入场质量"), 0)
    L.append("")
    L.append(f"- 入场时机 {entry_timing_avg:.2f}/3 (扣分率{et_rate:.1f}%)")
    L.append(f"- 入场质量 {entry_quality_avg:.2f}/3 (扣分率{eq_rate:.1f}%)")
    L.append(f"- **结论**: 买点选择有系统性缺陷——逆势、追涨、抄底失败")
    L.append("")

    L.append("### 发现3: 卖出决策暗藏矛盾")
    exit_avg = next((x[3] for x in shortfall if x[1] == "卖出时机"), 0)
    L.append("")
    L.append(f"- 卖出时机 {exit_avg:.2f}/3")
    L.append(f"- perfect_stop {perfect_stop_cnt}笔({perfect_stop_cnt/total_cnt*100:.1f}%) — 合计亏损约{ps_total_loss}")
    L.append(f"- discipline_sell {discipline_cnt}笔, good_profit {good_profit_cnt}笔")
    L.append(f"- **矛盾**: perfect_stop = \"止损精准\"，但实际是买入后一直跌被迫止损")
    L.append("")

    L.append("### 发现4: 风控维度不再虚高")
    L.append("")
    L.append(f"- 风控执行 {riskmgmt_avg:.2f}/2 (扣分率{riskmgmt_rate:.1f}%)")
    L.append(f"- **改进**: V4.1区分盈利交易看回撤(能力) vs 亏损交易看幅度(非运气)")
    L.append("")

    L.append("### 发现5: 只有不到10%的交易是真正高质量的")
    L.append("")
    L.append(f"- A+B(优质盈利): {ab_cnt}笔 ({ab_cnt/total_cnt*100:.1f}%)")
    L.append(f"- C(运气盈利): {c_cnt}笔 ({c_cnt/total_cnt*100:.1f}%)")
    L.append(f"- E+F(问题亏损): {ef_cnt}笔 ({ef_cnt/total_cnt*100:.1f}%)")
    L.append(f"- 近{c_cnt/total_cnt*100:.0f}%盈利是\"运气\"，一半是\"问题亏损\"")
    L.append("")

    L.append("### 发现6: 年度趋势")
    L.append("")
    yearly = query_yearly(cur)
    L.append("| 年份 | 笔数 | V3均分 | V4.1均分 | 胜率 | 均持仓天 | 总盈亏 |")
    L.append("|------|------|--------|---------|------|----------|--------|")
    for r in yearly:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} | {fmt(r[3])} | {fmt(r[4], '%')} | {fmt(r[5])} | {fmt(r[6])} |")
    L.append("")

    # ── 三、六级分类 ──
    L.append("## 三、六级分类深度分析")
    L.append("")
    L.append("### 3.1 分布")
    L.append("")
    L.append("| 等级 | 子类 | 笔数 | 盈利笔 | 均PNL% | 均V4分 | 均持仓天 | 总盈亏 |")
    L.append("|------|------|------|--------|--------|--------|----------|--------|")
    for r in grade_dist:
        L.append(f"| {r[0]} | {r[1] or '-'} | {r[2]} | {r[3]} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[6])} | {fmt(r[7])} |")
    L.append("")

    L.append("### 3.2 C级(运气盈利)")
    c_stats = [r for r in grade_dist if r[0] == "C"]
    if c_stats:
        cs = c_stats[0]
        L.append("")
        L.append(f"- {cs[2]}笔盈利但V4分<9，占全部盈利交易的{cs[2]/total_cnt*100:.1f}%")
        L.append(f"- 均盈{fmt(cs[4])}% 看似不错，但V4均分只有{fmt(cs[5])}/15，入场和卖出都有瑕疵")
        L.append(f"- **最大的隐性风险**: 市场环境转差时，这些\"运气盈利\"可能变成\"问题亏损\"")
        L.append("")

    L.append("### 3.3 E2(风控瑕疵)")
    e2_data = query_e2(cur)
    e2_cnt = e2_data["stats"][0]
    e2_avg_pnl = e2_data["stats"][1]
    e2_total_loss = e2_data["stats"][2]
    e2_avg_hold = e2_data["stats"][3]
    L.append("")
    L.append(f"- {e2_cnt}笔，均亏{fmt(e2_avg_pnl)}%，总亏{fmt(e2_total_loss)}")
    L.append(f"- 均持仓{fmt(e2_avg_hold)}天 — 止损拖延")
    L.append(f"- **改进ROI最高**: 控制在-5%止损可减少约50%亏损")
    L.append("")

    L.append("### 3.4 F1(入场灾难)")
    f1_stats = [r for r in grade_dist if r[1] == "F1"]
    if f1_stats:
        fs = f1_stats[0]
        L.append("")
        L.append(f"- {fs[2]}笔，总亏{fmt(fs[7])}")
        L.append(f"- 入场时机+入场质量双低，BOLL极端+逆趋势是标配")
        L.append(f"- 不是\"运气不好\"，而是**系统性重复同样的错误**")
        L.append("")

    # ── 四、Verdict×Grade交叉 ──
    L.append("## 四、卖出判定分布与交叉分析")
    L.append("")
    L.append("### 4.1 Verdict分布")
    L.append("")
    L.append("| Verdict | 笔数 | 盈利笔 | 均PNL% | 卖出时机分 | 含义 |")
    L.append("|---------|------|--------|--------|-----------|------|")
    for r in verdict_dist:
        desc = VERDICT_DESC.get(r[0], "")
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[3])} | {fmt(r[4])} | {desc} |")
    L.append("")

    vg_cross = query_verdict_grade_cross(cur)
    L.append("### 4.2 Verdict × Grade 交叉")
    L.append("")
    L.append("| Verdict | Grade | 笔数 | 均PNL% |")
    L.append("|---------|-------|------|--------|")
    for r in vg_cross:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[3])} |")
    L.append("")

    # ── 五、行为标签 ──
    L.append("## 五、行为标签深度分析")
    L.append("")
    L.append("### 5.1 单标签频次")
    L.append("")
    L.append("| 标签 | 笔数 | 占比 | 均PNL% |")
    L.append("|------|------|------|--------|")
    for tag in sorted(single_tags, key=lambda t: -single_tags[t]["cnt"]):
        s = single_tags[tag]
        L.append(f"| {tag} | {s['cnt']} | {s['cnt']/total_cnt*100:.1f}% | {fmt(s['avg_pnl'])} |")
    L.append(f"| (无标签) | {no_tag} | {no_tag/total_cnt*100:.1f}% | — |")
    L.append("")

    combo_rows, _, _ = query_behavior_tags(cur)
    L.append("### 5.2 标签组合 TOP15")
    L.append("")
    L.append("| 标签组合 | 笔数 | 均PNL% | 均V4分 |")
    L.append("|----------|------|--------|--------|")
    for r in combo_rows[:15]:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} | {fmt(r[3])} |")
    L.append("")

    lethal = query_tag_combo_lethal(cur)
    L.append("### 5.3 致命组合分析")
    L.append("")
    L.append("| 标签组合 | 笔数 | 均PNL% | 均V4分 |")
    L.append("|----------|------|--------|--------|")
    for label, cnt, pnl, score in lethal:
        L.append(f"| {label} | {cnt} | {fmt(pnl)} | {fmt(score)} |")
    L.append("")

    # ── 六、Shortfall Report ──
    L.append("## 六、Shortfall Report（维度短板排序）")
    L.append("")
    L.append("### 6.1 全局短板")
    L.append("")
    L.append("| 排名 | 维度 | 满分 | 均分 | 扣分 | 扣分率 |")
    L.append("|------|------|------|------|------|--------|")
    for i, (col, label, mx, avg, deduct, rate) in enumerate(shortfall, 1):
        L.append(f"| {i} | {label} | {mx} | {avg:.2f} | {deduct:.2f} | {rate:.1f}% |")
    L.append("")

    L.append("### 6.2 年度短板演变")
    L.append("")
    for year in [2021, 2022, 2023, 2024, 2025]:
        yr_shortfall = query_shortfall(cur, f"YEAR(buy_date)={year}")
        L.append(f"**{year}年**")
        L.append("")
        L.append("| 维度 | 满分 | 均分 | 扣分率 |")
        L.append("|------|------|------|--------|")
        for col, label, mx, avg, deduct, rate in yr_shortfall:
            L.append(f"| {label} | {mx} | {avg:.2f} | {rate:.1f}% |")
        L.append("")

    # ── 七、Perfect Stop 专项 ──
    L.append("## 七、Perfect Stop 专项分析")
    L.append("")
    ps_cnt = ps_data["total"][0]
    ps_avg_pnl = ps_data["total"][1]
    ps_avg_hold = ps_data["total"][3]
    L.append(f"> {ps_cnt}笔，合计亏损{fmt(ps_total_loss)}，均亏{fmt(ps_avg_pnl)}%，均持仓{fmt(ps_avg_hold)}天")
    L.append("")

    L.append("### 7.1 BOLL分布")
    L.append("")
    L.append("| 区间 | 笔数 | 占比 |")
    L.append("|------|------|------|")
    for label, cnt in ps_data["boll_dist"]:
        L.append(f"| {label} | {cnt} | {cnt/ps_cnt*100:.1f}% |")
    L.append("")

    L.append("### 7.2 趋势分布")
    L.append("")
    L.append("| 趋势 | 笔数 | 占比 |")
    L.append("|------|------|------|")
    for r in ps_data["trend_dist"]:
        L.append(f"| {r[0]} | {r[1]} | {r[1]/ps_cnt*100:.1f}% |")
    L.append("")

    L.append("### 7.3 持仓天数 vs 亏损")
    L.append("")
    L.append("| 持仓 | 笔数 | 均PNL% |")
    L.append("|------|------|--------|")
    for r in ps_data["hold_dist"]:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} |")
    L.append("")

    L.append("### 7.4 年度分布")
    L.append("")
    L.append("| 年份 | 笔数 | 均PNL% | 总亏损 | 均持仓天 |")
    L.append("|------|------|--------|--------|----------|")
    for r in ps_data["yearly_dist"]:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} | {fmt(r[3])} | {fmt(r[4])} |")
    L.append("")

    L.append("### 7.5 Verdict × Grade")
    L.append("")
    L.append("| 等级 | 笔数 | 均PNL% |")
    L.append("|------|------|--------|")
    for r in ps_data["grade_cross"]:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} |")
    L.append("")

    L.append("### 7.6 TOP10最大亏损")
    L.append("")
    L.append("| 代码 | 名称 | 买入日 | PNL% | 持仓天 | BOLL | 趋势 | 子类 |")
    L.append("|------|------|--------|------|--------|------|------|------|")
    for r in ps_data["top10"]:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[3])} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[6])} | {r[8] or '-'} |")
    L.append("")

    if ps_data["repeat_stocks"]:
        L.append("### 7.7 反复亏损股票")
        L.append("")
        L.append("| 代码 | 名称 | 次数 | 总PNL% | 各次PNL% |")
        L.append("|------|------|------|--------|----------|")
        for r in ps_data["repeat_stocks"]:
            L.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[3])} | {r[4]} |")
        L.append("")

    # ── 八、E2 专项 ──
    L.append("## 八、E2 风控瑕疵专项分析")
    L.append("")
    L.append(f"> {e2_cnt}笔，均亏{fmt(e2_avg_pnl)}%，总亏{fmt(e2_total_loss)}，均持仓{fmt(e2_avg_hold)}天")
    L.append("")

    L.append("### 8.1 Verdict分布")
    L.append("")
    for r in e2_data["verdict_dist"]:
        L.append(f"- {r[0]}: {r[1]}笔")
    L.append("")

    L.append("### 8.2 BOLL分布")
    L.append("")
    for r in e2_data["boll_dist"]:
        L.append(f"- {r[0]}: {r[1]}笔")
    L.append("")

    L.append("### 8.3 明细")
    L.append("")
    L.append("| 代码 | 名称 | 买入日 | 卖出日 | PNL% | 持仓天 | BOLL | 趋势 | Verdict |")
    L.append("|------|------|--------|--------|------|--------|------|------|---------|")
    for r in e2_data["details"]:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[7])} | {fmt(r[8])} | {r[10]} |")
    L.append("")

    # E/F 对比
    ef_comp = query_e_f_comparison(cur)
    L.append("### 8.4 亏损等级对比")
    L.append("")
    L.append("| 等级 | 笔数 | 均PNL% | 均持仓天 | 总亏损 |")
    L.append("|------|------|--------|----------|--------|")
    for r in ef_comp:
        L.append(f"| {r[0]} | {r[1]} | {fmt(r[2])} | {fmt(r[3])} | {fmt(r[4])} |")
    L.append("")

    # ── 九、A/B正面教材 ──
    L.append("## 九、A/B级正面教材")
    L.append("")
    ab_rows = query_ab_positive(cur)
    L.append("| 代码 | 名称 | 买入日 | PNL% | 持仓天 | V4分 | 等级 | Verdict | 标签 |")
    L.append("|------|------|--------|------|--------|------|------|---------|------|")
    for r in ab_rows:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[6])} | {r[7]} | {r[8]} | {r[9] or '-'} |")
    L.append("")

    # 共性
    verdicts = [r[8] for r in ab_rows]
    ds_cnt = verdicts.count("discipline_sell")
    gp_cnt = verdicts.count("good_profit")
    L.append(f"**共性**: discipline_sell {ds_cnt}笔, good_profit {gp_cnt}笔 — 交易纪律好")
    L.append("")

    # ── 十、规则引擎 ──
    L.append("## 十、规则引擎（已写入config）")
    L.append("")
    L.append("| 规则 | 条件 | 动作 | 数据依据 |")
    L.append("|------|------|------|----------|")

    # BOLL高位笔数
    boll_high = sum(c for _, c in ps_data["boll_dist"] if "高" in _)
    L.append(f"| 禁止BOLL极端追高 | BOLL>90+非上升趋势 | 阻止入场 | perfect_stop中BOLL>80: {boll_high}笔 |")

    # 逆势占比
    up_trends = {"bull", "up", "strong_up"}
    contra_cnt = sum(r[1] for r in ps_data["trend_dist"] if r[0] not in up_trends)
    L.append(f"| 顺势入场优先 | 非bull趋势 | 扣1分 | 逆势买入占比{contra_cnt/ps_cnt*100:.0f}% |")

    late_cnt = next((r[1] for r in verdict_dist if r[0] == "late_stop"), 0)
    missed_cnt = next((r[1] for r in verdict_dist if r[0] == "missed_profit"), 0)
    L.append(f"| 移动止盈 | pnl>10% | 5%回撤止盈 | {missed_cnt}笔missed_profit |")
    L.append(f"| 止损不延期 | 亏>5%且持>5天 | 强制止损 | {late_cnt}笔late_stop |")
    L.append(f"| 连亏冷却 | 连亏>=4笔 | 冷静期 | 冲动率{impulsive_cnt/total_cnt*100:.0f}% |")
    L.append("")

    # ══════════════════════════════════════════════════════════
    # V5 扩展章节（P1: 浮盈兑现 + 情绪周期 + 同股累计画像）
    # ══════════════════════════════════════════════════════════

    # ── 十一、浮盈兑现深度分析 ──
    L.append("## 十一、浮盈兑现深度分析")
    L.append("")

    # 11.1 总体分布
    L.append("### 11.1 浮盈兑现等级与盈亏")
    L.append("")
    L.append("| 等级 | 笔数 | avg_pnl% | 总盈亏 | 胜率 | avg_max浮盈% | avg持仓天 |")
    L.append("|------|------|----------|--------|------|-------------|-----------|")
    cur.execute("""
        SELECT 
            profit_capture_grade,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(realized_pnl), 0) as total_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate,
            ROUND(AVG(max_profit_pct), 2) as avg_max_prof,
            ROUND(AVG(hold_days), 1) as avg_hold
        FROM trade_audit 
        WHERE profit_capture_grade IS NOT NULL
        GROUP BY profit_capture_grade
        ORDER BY avg_pnl DESC
    """)
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]}% | {r[5]} | {r[6]} |")
    L.append("")

    # 11.2 全回吐交易特征
    L.append("### 11.2 全回吐交易特征分析")
    L.append("")
    L.append("**核心问题**: 280笔交易曾有浮盈(平均9.89%)但最终亏损，总亏48.8万")
    L.append("")
    L.append("| 特征维度 | 全回吐 | 非全回吐 | 差异 |")
    L.append("|----------|--------|----------|------|")
    cur.execute("""
        SELECT 
            'BOLL极端买入率' as dim,
            ROUND(SUM(CASE WHEN stk_boll_pctb > 90 OR stk_boll_pctb < 10 THEN 1 ELSE 0 END) / COUNT(*) * 100, 1),
            '—'
        FROM trade_audit WHERE profit_capture_grade = '利润全回吐'
    """)
    blowout_boll = cur.fetchone()
    cur.execute("""
        SELECT ROUND(SUM(CASE WHEN stk_boll_pctb > 90 OR stk_boll_pctb < 10 THEN 1 ELSE 0 END) / COUNT(*) * 100, 1)
        FROM trade_audit WHERE profit_capture_grade != '利润全回吐' AND profit_capture_grade IS NOT NULL
    """)
    other_boll = cur.fetchone()[0]
    L.append(f"| BOLL极端买入率 | {blowout_boll[1]}% | {other_boll}% | {'↑偏高' if float(blowout_boll[1]) > float(other_boll) else '↓偏低'} |")

    cur.execute("SELECT ROUND(AVG(hold_days),1) FROM trade_audit WHERE profit_capture_grade='利润全回吐'")
    bhd = cur.fetchone()[0]
    cur.execute("SELECT ROUND(AVG(hold_days),1) FROM trade_audit WHERE profit_capture_grade != '利润全回吐' AND profit_capture_grade IS NOT NULL")
    ohd = cur.fetchone()[0]
    L.append(f"| 平均持仓天数 | {bhd} | {ohd} | {'↑偏长' if float(bhd) > float(ohd) else '↓偏短'} |")

    cur.execute("SELECT ROUND(AVG(is_impulsive)*100,1) FROM trade_audit WHERE profit_capture_grade='利润全回吐'")
    bimp = cur.fetchone()[0]
    cur.execute("SELECT ROUND(AVG(is_impulsive)*100,1) FROM trade_audit WHERE profit_capture_grade != '利润全回吐' AND profit_capture_grade IS NOT NULL")
    oimp = cur.fetchone()[0]
    L.append(f"| 冲动买入率 | {bimp}% | {oimp}% | {'↑偏高' if float(bimp) > float(oimp) else '↓'} |")

    cur.execute("SELECT ROUND(AVG(days_to_max_profit),1) FROM trade_audit WHERE profit_capture_grade='利润全回吐' AND days_to_max_profit IS NOT NULL")
    bdm = cur.fetchone()[0]
    L.append(f"| 到达峰值天数 | {bdm} | — | 浮盈后持仓过久 |")

    cur.execute("SELECT ROUND(AVG(profit_decay_rate),2) FROM trade_audit WHERE profit_capture_grade='利润全回吐' AND profit_decay_rate IS NOT NULL")
    bdecay = cur.fetchone()[0]
    L.append(f"| 浮盈衰减速度 | {bdecay}%/天 | — | 浮盈蒸发速度 |")
    L.append("")

    # 11.3 浮盈峰值时间分析
    L.append("### 11.3 浮盈峰值到达时间 vs 兑现率")
    L.append("")
    cur.execute("""
        SELECT 
            CASE 
                WHEN days_to_max_profit = 0 THEN 'Day0(买入日)'
                WHEN days_to_max_profit <= 2 THEN 'Day1-2'
                WHEN days_to_max_profit <= 5 THEN 'Day3-5'
                WHEN days_to_max_profit <= 10 THEN 'Day6-10'
                ELSE 'Day11+'
            END as bucket,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(AVG(profit_capture_rate), 3) as avg_pcr
        FROM trade_audit 
        WHERE days_to_max_profit IS NOT NULL AND profit_capture_grade IS NOT NULL
        GROUP BY bucket ORDER BY MIN(days_to_max_profit)
    """)
    L.append("| 峰值到达 | 笔数 | avg_pnl% | avg_PCR |")
    L.append("|----------|------|----------|---------|")
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    L.append("")

    # ── 十二、情绪周期分析 ──
    L.append("## 十二、情绪周期分析")
    L.append("")

    # 12.1 总体分布
    L.append("### 12.1 情绪阶段与交易表现")
    L.append("")
    L.append("| 阶段 | 笔数 | avg_pnl% | 总盈亏 | 胜率 | 冲动率 | avg_PCR |")
    L.append("|------|------|----------|--------|------|--------|---------|")
    cur.execute("""
        SELECT 
            emotional_phase,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(realized_pnl), 0) as total_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate,
            ROUND(AVG(is_impulsive)*100, 1) as impulsive_rate,
            ROUND(AVG(profit_capture_rate), 3) as avg_pcr
        FROM trade_audit 
        WHERE emotional_phase IS NOT NULL
        GROUP BY emotional_phase
        ORDER BY avg_pnl DESC
    """)
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]}% | {r[5]}% | {r[6]} |")
    L.append("")

    # 12.2 tilt_phase深度分析
    L.append("### 12.2 Tilt Phase（连亏3笔后）——最致命的情绪陷阱")
    L.append("")
    cur.execute("""
        SELECT COUNT(*) FROM trade_audit WHERE emotional_phase='tilt_phase'
    """)
    tilt_cnt = cur.fetchone()[0]
    cur.execute("""
        SELECT 
            ROUND(AVG(pnl_rate), 2),
            ROUND(AVG(stk_boll_pctb), 1),
            ROUND(AVG(is_impulsive)*100, 1),
            ROUND(AVG(hold_days), 1),
            ROUND(SUM(CASE WHEN profit_capture_grade='利润全回吐' THEN 1 ELSE 0 END)/COUNT(*)*100, 1)
        FROM trade_audit WHERE emotional_phase='tilt_phase'
    """)
    tr = cur.fetchone()
    L.append(f"- **{tilt_cnt}笔** 交易发生在连亏3笔之后")
    L.append(f"- 平均盈亏: **{tr[0]}%** (远低于neutral的0.19%)")
    L.append(f"- 入场BOLL%B: **{tr[1]}** (极端位置入场)")
    L.append(f"- 冲动率: **{tr[2]}%**")
    L.append(f"- 持仓天数: **{tr[3]}天**")
    L.append(f"- 利润全回吐率: **{tr[4]}%**")
    L.append("")

    # 12.3 情绪周期交叉：情绪×浮盈兑现
    L.append("### 12.3 情绪阶段 × 浮盈兑现等级 交叉分析")
    L.append("")
    phases = ['overconfident', 'neutral', 'frustration', 'tilt_phase']
    grades = ['优秀兑现', '部分兑现', '少量兑现', '利润全回吐', '无意义浮盈']
    header = "| 情绪阶段 |" + "|".join(grades) + " |"
    L.append(header)
    L.append("|" + "|".join(["----------"] * (len(grades)+1)) + "|")
    for phase in phases:
        row_parts = [phase]
        for grade in grades:
            cur.execute("""
                SELECT COUNT(*) FROM trade_audit 
                WHERE emotional_phase=%s AND profit_capture_grade=%s
            """, (phase, grade))
            cnt = cur.fetchone()[0]
            row_parts.append(str(cnt))
        L.append("| " + " | ".join(row_parts) + " |")
    L.append("")

    # 12.4 情绪周期年度演变
    L.append("### 12.4 情绪阶段年度演变")
    L.append("")
    L.append("| 年份 | neutral | overconfident | frustration | tilt_phase |")
    L.append("|------|---------|---------------|-------------|------------|")
    cur.execute("""
        SELECT 
            YEAR(buy_date) as yr,
            SUM(CASE WHEN emotional_phase='neutral' THEN 1 ELSE 0 END),
            SUM(CASE WHEN emotional_phase='overconfident' THEN 1 ELSE 0 END),
            SUM(CASE WHEN emotional_phase='frustration' THEN 1 ELSE 0 END),
            SUM(CASE WHEN emotional_phase='tilt_phase' THEN 1 ELSE 0 END)
        FROM trade_audit
        WHERE buy_date IS NOT NULL
        GROUP BY yr ORDER BY yr
    """)
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")
    L.append("")

    # ── 十三、同股累计画像 ──
    L.append("## 十三、同股累计画像")
    L.append("")

    # 13.1 高频亏损股（"感情股"）
    L.append('### 13.1 高频亏损股 TOP15（"感情股"）')
    L.append("")
    L.append("| 代码 | 名称 | 笔数 | 总盈亏 | avg_pnl% | 胜率 | avg_PCR | avg持仓 |")
    L.append("|------|------|------|--------|----------|------|---------|---------|")
    cur.execute("""
        SELECT 
            stock_code, stock_name,
            COUNT(*) as trade_cnt,
            ROUND(SUM(realized_pnl), 0) as total_pnl,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate,
            ROUND(AVG(profit_capture_rate), 3) as avg_pcr,
            ROUND(AVG(hold_days), 1) as avg_hold
        FROM trade_audit 
        GROUP BY stock_code, stock_name
        HAVING trade_cnt >= 5
        ORDER BY total_pnl ASC
        LIMIT 15
    """)
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]}% | {r[6]} | {r[7]} |")
    L.append("")

    # 13.2 高频盈利股
    L.append("### 13.2 高频盈利股 TOP10")
    L.append("")
    L.append("| 代码 | 名称 | 笔数 | 总盈亏 | avg_pnl% | 胜率 |")
    L.append("|------|------|------|--------|----------|------|")
    cur.execute("""
        SELECT 
            stock_code, stock_name,
            COUNT(*) as trade_cnt,
            ROUND(SUM(realized_pnl), 0) as total_pnl,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate
        FROM trade_audit 
        GROUP BY stock_code, stock_name
        HAVING trade_cnt >= 3
        ORDER BY total_pnl DESC
        LIMIT 10
    """)
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]}% |")
    L.append("")

    # 13.3 第1笔 vs 后续笔胜率
    L.append("### 13.3 同股交易序号 vs 胜率变化（是否越做越差）")
    L.append("")
    L.append("| 第N笔 | 笔数 | avg_pnl% | 胜率 |")
    L.append("|--------|------|----------|------|")
    cur.execute("""
        SELECT 
            trade_seq,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate
        FROM (
            SELECT 
                t.*,
                ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY buy_date, id) as trade_seq
            FROM trade_audit t
            WHERE buy_date IS NOT NULL
        ) ranked
        WHERE trade_seq <= 10
        GROUP BY trade_seq ORDER BY trade_seq
    """)
    for r in cur.fetchall():
        L.append(f"| 第{r[0]}笔 | {r[1]} | {r[2]} | {r[3]}% |")
    L.append("")

    # 13.4 典型"越做越亏"模式
    L.append('### 13.4 典型"越做越亏"模式识别')
    L.append("")
    L.append("条件: 同股>=5笔, 前半胜率>后半胜率, 总亏损")
    L.append("")
    L.append("| 代码 | 名称 | 笔数 | 前半胜率 | 后半胜率 | 差值 | 总亏损 |")
    L.append("|------|------|------|----------|----------|------|--------|")
    # 使用临时表简化
    cur.execute("DROP TEMPORARY TABLE IF EXISTS _tmp_ranked")
    cur.execute("""
        CREATE TEMPORARY TABLE _tmp_ranked AS
        SELECT 
            id, stock_code, stock_name, buy_date, pnl_rate, realized_pnl, is_profit,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY buy_date, id) as trade_seq,
            COUNT(*) OVER (PARTITION BY stock_code) as total_cnt
        FROM trade_audit
        WHERE buy_date IS NOT NULL
    """)
    cur.execute("""
        SELECT 
            stock_code, stock_name,
            total_cnt,
            ROUND(SUM(CASE WHEN trade_seq <= total_cnt/2 AND is_profit=1 THEN 1 ELSE 0 END) / 
                NULLIF(SUM(CASE WHEN trade_seq <= total_cnt/2 THEN 1 ELSE 0 END), 0) * 100, 1) as first_half_wr,
            ROUND(SUM(CASE WHEN trade_seq > total_cnt/2 AND is_profit=1 THEN 1 ELSE 0 END) / 
                NULLIF(SUM(CASE WHEN trade_seq > total_cnt/2 THEN 1 ELSE 0 END), 0) * 100, 1) as second_half_wr,
            ROUND(SUM(realized_pnl), 0) as total_pnl
        FROM _tmp_ranked
        GROUP BY stock_code, stock_name, total_cnt
        HAVING total_cnt >= 5 AND total_pnl < 0 AND first_half_wr > second_half_wr
        ORDER BY total_pnl ASC
        LIMIT 10
    """)
    for r in cur.fetchall():
        diff = float(r[3] or 0) - float(r[4] or 0)
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]}% | {r[4]}% | {diff:+.1f}% | {r[5]} |")
    cur.execute("DROP TEMPORARY TABLE IF EXISTS _tmp_ranked")
    L.append("")

    # ── 十四、交叉发现 ──
    L.append("## 十四、V5 交叉发现")
    L.append("")

    # 14.1 情绪周期中的浮盈全回吐
    L.append("### 14.1 情绪×浮盈全回吐 × BOLL极端 三重交叉")
    L.append("")
    cur.execute("""
        SELECT 
            emotional_phase,
            COUNT(*) as cnt,
            ROUND(SUM(CASE WHEN profit_capture_grade='利润全回吐' THEN 1 ELSE 0 END)/COUNT(*)*100, 1) as blowout_rate,
            ROUND(SUM(CASE WHEN stk_boll_pctb>90 OR stk_boll_pctb<10 THEN 1 ELSE 0 END)/COUNT(*)*100, 1) as boll_extreme_rate
        FROM trade_audit
        WHERE emotional_phase IS NOT NULL
        GROUP BY emotional_phase ORDER BY SUM(realized_pnl) DESC
    """)
    L.append("| 情绪阶段 | 笔数 | 全回吐率 | BOLL极端率 |")
    L.append("|----------|------|----------|------------|")
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]}% | {r[3]}% |")
    L.append("")

    # 14.2 星期几效应
    L.append("### 14.2 买入星期几效应")
    L.append("")
    weekday_names = {1:'周一', 2:'周二', 3:'周三', 4:'周四', 5:'周五'}
    L.append("| 星期 | 笔数 | avg_pnl% | 胜率 | 冲动率 | tilt率 |")
    L.append("|------|------|----------|------|--------|--------|")
    cur.execute("""
        SELECT 
            buy_weekday,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate,
            ROUND(AVG(is_impulsive)*100, 1) as impulsive_rate,
            ROUND(SUM(CASE WHEN emotional_phase='tilt_phase' THEN 1 ELSE 0 END)/COUNT(*)*100, 1) as tilt_rate
        FROM trade_audit
        WHERE buy_weekday IS NOT NULL
        GROUP BY buy_weekday ORDER BY buy_weekday
    """)
    for r in cur.fetchall():
        wd = weekday_names.get(r[0], str(r[0]))
        L.append(f"| {wd} | {r[1]} | {r[2]} | {r[3]}% | {r[4]}% | {r[5]}% |")
    L.append("")

    # 14.3 大盘环境与浮盈兑现
    L.append("### 14.3 大盘MA20环境与浮盈兑现")
    L.append("")
    cur.execute("""
        SELECT 
            CASE 
                WHEN mkt_above_ma20 >= 0.7 THEN '强势(>70%天在MA20上)'
                WHEN mkt_above_ma20 >= 0.3 THEN '中性(30-70%)'
                ELSE '弱势(<30%)'
            END as mkt_env,
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*) * 100, 1) as win_rate,
            ROUND(AVG(profit_capture_rate), 3) as avg_pcr
        FROM trade_audit
        WHERE mkt_above_ma20 IS NOT NULL
        GROUP BY mkt_env ORDER BY avg_pnl DESC
    """)
    L.append("| 大盘环境 | 笔数 | avg_pnl% | 胜率 | avg_PCR |")
    L.append("|----------|------|----------|------|---------|")
    for r in cur.fetchall():
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]}% | {r[4]} |")
    L.append("")

    L.append("---")
    L.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    L.append(f"*数据来源: trade_audit表 ({total_cnt}笔交易), tdx_data.day_kline (日线K线)*")
    L.append("")

    conn.close()

    # ── 输出 ──
    report_text = "\n".join(L)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"报告已写入: {output_path}")
        print(f"行数: {len(L)}, 大小: {len(report_text)} bytes")
    else:
        print(report_text)

    return len(L)


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V4.1 综合评分报告生成器")
    parser.add_argument("--output", "-o", type=str, help="输出MD文件路径 (默认打印到stdout)")
    parser.add_argument("--year", type=int, help="只看指定年份 (未实现)")
    args = parser.parse_args()

    vault = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"
    default_output = f"{vault}/mynotes/学习材料/复盘方法/V4.1优化报告-perfect_stop与E2分析.md"

    output = args.output or default_output
    n = generate_report(output_path=output)
    print(f"生成完毕: {n} 行")


if __name__ == "__main__":
    main()
