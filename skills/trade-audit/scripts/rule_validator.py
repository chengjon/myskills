#!/usr/bin/env python3
"""V5 规则验证集测试
训练集: 2025及之前 (366笔)
验证集: 2026Q1+Q2 (713笔)
"""
import pymysql
import os
from datetime import datetime

conn = pymysql.connect(
    host='192.168.123.104', port=3306, user='root',
    password=os.environ.get('MYSQL_PWD', ''), database='hermes', charset='utf8mb4'
)
cur = conn.cursor()

def stats(label, where_clause, params=None):
    """计算给定条件的胜率、avg_pnl、样本量"""
    sql = f"""
        SELECT 
            COUNT(*) as cnt,
            ROUND(AVG(pnl_rate), 2) as avg_pnl,
            ROUND(SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END)/COUNT(*)*100, 1) as win_rate,
            ROUND(SUM(realized_pnl), 0) as total_pnl
        FROM trade_audit WHERE {where_clause}
    """
    cur.execute(sql, params)
    r = cur.fetchone()
    return {
        'label': label,
        'cnt': int(r[0]),
        'avg_pnl': float(r[1] or 0),
        'win_rate': float(r[2] or 0),
        'total_pnl': float(r[3] or 0)
    }

def print_stats(s, baseline=None):
    """格式化输出"""
    line = f"  {s['label']:35s} {s['cnt']:5d}笔  pnl={s['avg_pnl']:+6.2f}%  胜率={s['win_rate']:5.1f}%  总={s['total_pnl']:+10.0f}"
    if baseline and baseline['avg_pnl'] != 0:
        delta = s['avg_pnl'] - baseline['avg_pnl']
        line += f"  Δ={delta:+.2f}%"
    print(line)

# 数据集分割
train_where = "buy_date < '2026-01-01'"
test_where = "buy_date >= '2026-01-01'"

print("=" * 80)
print("V5 规则验证集测试")
print("=" * 80)
print()

# 基线
train_base = stats("训练集基线", train_where)
test_base = stats("验证集基线", test_where)
print("--- 基线 ---")
print_stats(train_base)
print_stats(test_base)
print()

# ============================================================
rules = [
    # 情绪规则
    {
        'name': 'R1: tilt预警(连亏>=2笔)',
        'condition': """id IN (
            SELECT t.id FROM trade_audit t 
            WHERE t.buy_date {date_range}
            AND (
                SELECT COUNT(*) FROM trade_audit t2 
                WHERE t2.buy_date < t.buy_date OR (t2.buy_date = t.buy_date AND t2.id < t.id)
            ) >= 2
            AND (
                SELECT COUNT(*) FROM trade_audit t3 
                WHERE (t3.buy_date < t.buy_date OR (t3.buy_date = t.buy_date AND t3.id < t.id))
                AND t3.pnl_rate < 0
                ORDER BY t3.buy_date DESC, t3.id DESC LIMIT 2
            ) = 2
        )""",
    },
]

# 简化：用Python逐笔计算连亏序列
print("--- 规则验证 ---")
print()

def eval_rule(name, check_fn, date_filter_col='buy_date'):
    """通用规则评估器"""
    train_pass, train_fail = [], []
    test_pass, test_fail = [], []
    
    cur.execute(f"""
        SELECT id, buy_date, pnl_rate, is_profit, realized_pnl,
               stk_boll_pctb, days_to_max_profit, emotional_phase,
               buy_weekday, mkt_above_ma20, hold_days,
               max_profit_pct, profit_capture_rate
        FROM trade_audit 
        WHERE buy_date IS NOT NULL
        ORDER BY buy_date, id
    """)
    all_trades = cur.fetchall()
    
    for i, t in enumerate(all_trades):
        triggered = check_fn(i, all_trades, t)
        bucket = test_pass if t[1] >= datetime(2026, 1, 1).date() else train_pass
        bucket_fail = test_fail if t[1] >= datetime(2026, 1, 1).date() else train_fail
        
        if triggered:
            bucket.append(t)
        else:
            bucket_fail.append(t)
    
    # 计算触发后的表现
    def summarize(trades, label):
        if not trades:
            print(f"  {label:40s} 0笔 (无样本)")
            return
        cnt = len(trades)
        avg_pnl = sum(float(t[2]) for t in trades) / cnt
        win_rate = sum(int(t[3]) for t in trades) / cnt * 100
        total = sum(float(t[4]) for t in trades)
        print(f"  {label:40s} {cnt:4d}笔  pnl={avg_pnl:+6.2f}%  胜率={win_rate:5.1f}%  总={total:+10.0f}")
    
    print(f"  [{name}]")
    summarize(train_pass, "训练集-规则触发")
    summarize(test_pass, "验证集-规则触发")
    
    # 规则目的：规则触发时应比基线差（预警类）或更好（保护类）
    if test_pass:
        test_pnl = sum(float(t[2]) for t in test_pass) / len(test_pass)
        delta = test_pnl - test_base['avg_pnl']
        print(f"  {'':40s} vs基线 Δ={delta:+.2f}%  {'✓有效' if delta < -0.5 else '△弱' if delta < 0 else '✗无效'}")
    print()

# ---- R1: 连亏>=2笔 ----
def check_tilt2(i, trades, t):
    if i < 2: return False
    return float(trades[i-1][2]) < 0 and float(trades[i-2][2]) < 0

eval_rule("R1: 连亏>=2笔预警", check_tilt2)

# ---- R2: 连亏>=3笔 ----
def check_tilt3(i, trades, t):
    if i < 3: return False
    return float(trades[i-1][2]) < 0 and float(trades[i-2][2]) < 0 and float(trades[i-3][2]) < 0

eval_rule("R2: 连亏>=3笔强制冷却", check_tilt3)

# ---- R3: BOLL>50 + Day0峰值 ----
def check_day0_boll(i, trades, t):
    boll = float(t[5] or 0)
    d2m = t[6]  # days_to_max_profit
    return boll > 50 and d2m is not None and int(d2m) == 0

eval_rule("R3: BOLL>50 + Day0峰值减仓", check_day0_boll)

# ---- R4: 浮盈>=5%但PCR<0.3 ----
def check_profit5(i, trades, t):
    max_prof = float(t[10] or 0)
    return max_prof >= 5

eval_rule("R4: 浮盈>=5%(PCR应转正)", check_profit5)

# ---- R5: 周四买入 ----
def check_thursday(i, trades, t):
    wd = t[8]  # buy_weekday
    return wd is not None and int(wd) == 4

eval_rule("R5: 周四买入谨慎", check_thursday)

# ---- R6: 弱势大盘 ----
def check_weak_market(i, trades, t):
    mkt = t[9]  # mkt_above_ma20
    return mkt is not None and float(mkt) < 0.3

eval_rule("R6: 弱势大盘减仓", check_weak_market)

# ---- R7: tilt_phase + 全回吐组合 ----
def check_tilt_blowout(i, trades, t):
    phase = t[7]  # emotional_phase
    return phase == 'tilt_phase'

eval_rule("R7: tilt_phase情绪(连亏3笔)", check_tilt_blowout)

# ---- 综合规则效果: 多规则同时触发 ----
print("--- 综合规则效果 ---")
print()

# 验证集中，规则触发 vs 未触发的对比
cur.execute("""
    SELECT id, buy_date, pnl_rate, is_profit, realized_pnl,
           stk_boll_pctb, days_to_max_profit, emotional_phase,
           buy_weekday, mkt_above_ma20, hold_days,
           max_profit_pct, profit_capture_rate
    FROM trade_audit 
    WHERE buy_date >= '2026-01-01'
    ORDER BY buy_date, id
""")
test_trades = cur.fetchall()

# 统计：触发>=1条预警规则的交易表现
def multi_rule_check(trades_list):
    """检查所有规则，返回按触发规则数分组的统计"""
    from collections import defaultdict
    groups = defaultdict(list)
    
    for i, t in enumerate(trades_list):
        triggered = 0
        if check_tilt2(i, trades_list, t): triggered += 1
        if check_day0_boll(i, trades_list, t): triggered += 1
        if check_thursday(i, trades_list, t): triggered += 1
        if check_weak_market(i, trades_list, t): triggered += 1
        if check_tilt_blowout(i, trades_list, t): triggered += 1
        groups[triggered].append(t)
    
    print(f"  {'触发规则数':12s} {'笔数':>5s} {'avg_pnl':>8s} {'胜率':>7s} {'总盈亏':>10s}")
    print("  " + "-" * 50)
    for k in sorted(groups.keys()):
        g = groups[k]
        cnt = len(g)
        avg_pnl = sum(float(t[2]) for t in g) / cnt
        wr = sum(int(t[3]) for t in g) / cnt * 100
        total = sum(float(t[4]) for t in g)
        print(f"  {k:12d} {cnt:5d} {avg_pnl:+8.2f}% {wr:6.1f}% {total:+10.0f}")

print("  [验证集] 按触发规则数量分组:")
multi_rule_check(test_trades)

# 同样看训练集
print()
print("  [训练集] 按触发规则数量分组:")
cur.execute("""
    SELECT id, buy_date, pnl_rate, is_profit, realized_pnl,
           stk_boll_pctb, days_to_max_profit, emotional_phase,
           buy_weekday, mkt_above_ma20, hold_days,
           max_profit_pct, profit_capture_rate
    FROM trade_audit 
    WHERE buy_date < '2026-01-01'
    ORDER BY buy_date, id
""")
train_trades = cur.fetchall()
multi_rule_check(train_trades)

# ---- 过拟合检测: 每条规则在训练集vs验证集的效果差异 ----
print()
print("--- 过拟合检测 ---")
print()

def overfit_check(name, check_fn):
    """检查规则在训练集和验证集上的效果一致性"""
    results = {}
    for label, trades_list in [("训练集", train_trades), ("验证集", test_trades)]:
        triggered = [(i, t) for i, t in enumerate(trades_list) if check_fn(i, trades_list, t)]
        if triggered:
            cnt = len(triggered)
            avg_pnl = sum(float(t[2]) for _, t in triggered) / cnt
            wr = sum(int(t[3]) for _, t in triggered) / cnt * 100
        else:
            cnt, avg_pnl, wr = 0, 0, 0
        results[label] = {'cnt': cnt, 'pnl': avg_pnl, 'wr': wr}
    
    t = results['训练集']
    v = results['验证集']
    pnl_delta = v['pnl'] - t['pnl']
    wr_delta = v['wr'] - t['wr']
    
    status = "✓一致" if abs(pnl_delta) < 2 else "△偏移" if abs(pnl_delta) < 4 else "✗过拟合"
    print(f"  {name:35s} 训练:{t['pnl']:+.2f}%/{t['wr']:.0f}%  验证:{v['pnl']:+.2f}%/{v['wr']:.0f}%  Δpnl={pnl_delta:+.2f}%  {status}")

overfit_check("R1:连亏>=2笔", check_tilt2)
overfit_check("R2:连亏>=3笔", check_tilt3)
overfit_check("R3:BOLL>50+Day0", check_day0_boll)
overfit_check("R4:浮盈>=5%", check_profit5)
overfit_check("R5:周四买入", check_thursday)
overfit_check("R6:弱势大盘", check_weak_market)
overfit_check("R7:tilt_phase", check_tilt_blowout)

conn.close()
