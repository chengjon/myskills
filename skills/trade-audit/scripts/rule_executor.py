#!/usr/bin/env python3
"""V5 规则执行器 —— 扫描当前持仓/近期交易，检查是否触发v5_rules
用法:
    MYSQL_PWD=xxx python rule_executor.py                    # 扫描当前未平仓交易
    MYSQL_PWD=xxx python rule_executor.py --recent 10        # 扫描最近10笔交易
    MYSQL_PWD=xxx python rule_executor.py --stock 002195     # 扫描指定股票
    MYSQL_PWD=xxx python rule_executor.py --all              # 全量扫描+综合评分
"""
import argparse
import os
import sys
from datetime import datetime, date, timedelta
from collections import defaultdict

import pymysql


# ─── 规则定义(与review_config.yaml v5_rules一致) ──────────────

# weight>0的规则参与综合评分, weight=0仅监控
RULES = [
    # 情绪规则
    {
        'id': 'R1', 'name': '连亏>=2笔预警', 'weight': 1,
        'action': 'warning', 'level': 'yellow',
        'check': lambda ctx: ctx.get('consecutive_losses', 0) >= 2,
    },
    {
        'id': 'R2', 'name': '连亏>=3笔冷却', 'weight': 2,
        'action': 'force_cooldown', 'cooldown_days': 3,
        'check': lambda ctx: ctx.get('consecutive_losses', 0) >= 3,
    },
    {
        'id': 'R3', 'name': '连亏>=5笔禁止', 'weight': 2,
        'action': 'block_entry', 'cooldown_days': 7,
        'check': lambda ctx: ctx.get('consecutive_losses', 0) >= 5,
    },
    # BOLL规则(最有效)
    {
        'id': 'R4', 'name': 'BOLL>50+Day0峰值', 'weight': 2,
        'action': 'block_entry',
        'check': lambda ctx: ctx.get('stk_boll_pctb', 0) > 50 and ctx.get('is_day0_peak', False),
    },
    # 监控规则(weight=0)
    {
        'id': 'R5', 'name': '浮盈>=5%提醒', 'weight': 0,
        'action': 'info',
        'check': lambda ctx: ctx.get('max_profit_pct', 0) >= 5,
    },
    {
        'id': 'R6', 'name': '周四监控', 'weight': 0,
        'action': 'monitor',
        'check': lambda ctx: ctx.get('buy_weekday') == 4,
    },
    {
        'id': 'R7', 'name': '弱势大盘监控', 'weight': 0,
        'action': 'monitor',
        'check': lambda ctx: ctx.get('mkt_above_ma20', 1) < 0.3,
    },
]

# 感情股黑名单
BLACKLIST = {
    '002195': '岩山科技(115笔亏11.7万)',
    '002506': '协鑫集成(48笔亏9万)',
    '002929': '润建股份(12笔亏4.2万)',
}

# 综合阈值
THRESHOLD_REDUCE = 2
THRESHOLD_BLOCK = 3


# ─── 上下文构建 ─────────────────────────────────────────────

def build_contexts_batch(cur, trades, stock_stats, consec_map):
    """批量构建上下文(避免逐笔SQL)"""
    contexts = []
    for trade in trades:
        ctx = {
            'id': trade['id'],
            'stock_code': trade['stock_code'],
            'stock_name': trade['stock_name'],
            'buy_date': trade['buy_date'],
            'sell_date': trade['sell_date'],
            'buy_price': float(trade['buy_price'] or 0),
            'pnl_rate': float(trade['pnl_rate'] or 0),
            'is_profit': int(trade['is_profit'] or 0),
            'consecutive_losses': consec_map.get(trade['id'], 0),
            'stk_boll_pctb': float(trade.get('stk_boll_pctb') or 0),
            'is_day0_peak': (trade.get('days_to_max_profit') is not None 
                            and int(trade['days_to_max_profit']) == 0),
            'max_profit_pct': float(trade.get('max_profit_pct') or 0),
            'buy_weekday': trade['buy_date'].weekday() + 1 if trade['buy_date'] else 0,
            'mkt_above_ma20': float(trade.get('mkt_above_ma20') or 1),
            'blacklisted': trade['stock_code'] in BLACKLIST,
        }

        # 同股统计
        code = trade['stock_code']
        if code in stock_stats:
            ss = stock_stats[code]
            ctx['same_stock_trades'] = ss['cnt']
            ctx['same_stock_pnl'] = ss['total_pnl']
            ctx['same_stock_wr_declining'] = ss.get('wr_declining', False)

        contexts.append(ctx)
    return contexts


def precompute_consecutive_losses(cur):
    """一次性预计算所有交易的连亏序列"""
    cur.execute("""
        SELECT id, pnl_rate FROM trade_audit 
        WHERE buy_date IS NOT NULL ORDER BY buy_date, id
    """)
    all_trades = cur.fetchall()
    
    consec_map = {}
    consec = 0
    for r in all_trades:
        tid = r[0]
        pnl = float(r[1] or 0)
        consec_map[tid] = consec
        if pnl < 0:
            consec += 1
        else:
            consec = 0
    return consec_map


def compute_stock_stats(cur):
    """计算每只股票的累计统计"""
    cur.execute("""
        SELECT 
            stock_code,
            COUNT(*) as cnt,
            SUM(realized_pnl) as total_pnl,
            SUM(CASE WHEN is_profit=1 THEN 1 ELSE 0 END) as wins
        FROM trade_audit
        WHERE buy_date IS NOT NULL
        GROUP BY stock_code
    """)
    stats = {}
    for r in cur.fetchall():
        code = r[0]
        cnt = int(r[1])
        total = float(r[2] or 0)
        wins = int(r[3] or 0)
        stats[code] = {'cnt': cnt, 'total_pnl': total, 'wins': wins}

    # 计算胜率递减
    cur.execute("""
        SELECT stock_code, buy_date, id, is_profit,
               ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY buy_date, id) as seq
        FROM trade_audit WHERE buy_date IS NOT NULL
    """)
    trades_by_stock = defaultdict(list)
    for r in cur.fetchall():
        trades_by_stock[r[0]].append(int(r[3] or 0))

    for code, trades_list in trades_by_stock.items():
        if code not in stats or stats[code]['cnt'] < 5:
            continue
        half = len(trades_list) // 2
        if half == 0:
            continue
        first_wr = sum(trades_list[:half]) / half * 100
        second_wr = sum(trades_list[half:]) / (len(trades_list) - half) * 100
        stats[code]['wr_declining'] = first_wr > second_wr and stats[code]['total_pnl'] < 0

    return stats


# ─── 规则检查 ─────────────────────────────────────────────────

def check_rules(ctx):
    """检查所有规则，返回触发的规则列表"""
    triggered = []

    # 常规规则
    for rule in RULES:
        try:
            if rule['check'](ctx):
                triggered.append(rule)
        except Exception:
            pass

    # 感情股预警
    code = ctx.get('stock_code', '')
    if code in BLACKLIST:
        triggered.append({
            'id': 'BL', 'name': f'黑名单: {BLACKLIST[code]}',
            'weight': 2, 'action': 'block_entry'
        })
    elif ctx.get('same_stock_trades', 0) >= 5 and ctx.get('same_stock_pnl', 0) < 0:
        if ctx.get('same_stock_wr_declining'):
            triggered.append({
                'id': 'ES', 'name': '感情股越做越亏',
                'weight': 2, 'action': 'block_entry'
            })
        else:
            triggered.append({
                'id': 'EW', 'name': '感情股预警(多次亏损)',
                'weight': 1, 'action': 'warning', 'level': 'red'
            })

    return triggered


def composite_action(triggered):
    """根据触发规则数量计算综合动作"""
    weighted_count = sum(r['weight'] for r in triggered)
    if weighted_count >= THRESHOLD_BLOCK:
        return 'BLOCK', weighted_count
    elif weighted_count >= THRESHOLD_REDUCE:
        return 'REDUCE', weighted_count
    elif weighted_count > 0:
        return 'WARN', weighted_count
    return 'SAFE', 0


# ─── 输出 ─────────────────────────────────────────────────────

def print_scan_result(ctx, triggered, action, score):
    """格式化输出扫描结果"""
    code = ctx.get('stock_code', '')
    name = ctx.get('stock_name', '')
    pnl = ctx.get('pnl_rate', 0)
    boll = ctx.get('stk_boll_pctb', 0)
    consec = ctx.get('consecutive_losses', 0)
    buy_dt = ctx.get('buy_date', '')

    # 动作标签
    labels = {'BLOCK': '⛔禁止', 'REDUCE': '⚠️减仓', 'WARN': '⚡预警', 'SAFE': '✅安全'}
    label = labels.get(action, '?')

    print(f"  {label} [{score}] {code} {name} 买入:{buy_dt} pnl={pnl:+.2f}% BOLL={boll:.0f} 连亏={consec}")

    for r in triggered:
        print(f"      → {r['id']}: {r['name']} (weight={r['weight']}, action={r['action']})")


# ─── 主函数 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='V5规则执行器')
    parser.add_argument('--recent', type=int, default=0, help='扫描最近N笔交易')
    parser.add_argument('--stock', type=str, help='扫描指定股票代码')
    parser.add_argument('--open', action='store_true', help='仅扫描未平仓交易')
    parser.add_argument('--all', action='store_true', help='全量扫描')
    parser.add_argument('--summary', action='store_true', help='仅输出统计摘要')
    args = parser.parse_args()

    pwd = os.environ.get('MYSQL_PWD', '')
    conn = pymysql.connect(host='192.168.123.104', port=3306, user='root',
                           password=pwd, database='hermes', charset='utf8mb4')
    cur = conn.cursor()

    # 获取股票统计
    stock_stats = compute_stock_stats(cur)
    consec_map = precompute_consecutive_losses(cur)

    # 获取待扫描的交易
    if args.stock:
        cur.execute("""
            SELECT * FROM trade_audit 
            WHERE stock_code = %s AND buy_date IS NOT NULL
            ORDER BY buy_date DESC, id DESC
        """, (args.stock,))
    elif args.open:
        cur.execute("""
            SELECT * FROM trade_audit 
            WHERE sell_date IS NULL AND buy_date IS NOT NULL
            ORDER BY buy_date DESC
        """)
    elif args.recent > 0:
        cur.execute("""
            SELECT * FROM trade_audit 
            WHERE buy_date IS NOT NULL
            ORDER BY buy_date DESC, id DESC LIMIT %s
        """, (args.recent,))
    else:
        # 默认: 最近30天
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        cur.execute("""
            SELECT * FROM trade_audit 
            WHERE buy_date >= %s
            ORDER BY buy_date DESC, id DESC
        """, (cutoff,))

    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not trades:
        print("无交易数据")
        conn.close()
        return

    # 移除全量加载，已用consec_map替代
    all_recent = []

    # 批量构建上下文
    contexts = build_contexts_batch(cur, trades, stock_stats, consec_map)

    # 扫描
    print("=" * 70)
    print(f"V5 规则执行器 | 扫描{len(trades)}笔交易 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    results = {'BLOCK': [], 'REDUCE': [], 'WARN': [], 'SAFE': []}
    for ctx in contexts:
        triggered = check_rules(ctx)
        action, score = composite_action(triggered)
        results[action].append((ctx, triggered, score))

        if not args.summary:
            print_scan_result(ctx, triggered, action, score)

    # 摘要
    print()
    print("--- 扫描摘要 ---")
    for act in ['BLOCK', 'REDUCE', 'WARN', 'SAFE']:
        cnt = len(results[act])
        if cnt > 0:
            total_pnl = sum(c['pnl_rate'] for c, _, _ in results[act])
            avg_pnl = total_pnl / cnt
            print(f"  {act:6s}: {cnt:3d}笔  avg_pnl={avg_pnl:+.2f}%")

    # 规则触发频率
    print()
    print("--- 规则触发频率 ---")
    rule_counts = defaultdict(int)
    for act, items in results.items():
        if act == 'SAFE':
            continue
        for ctx, triggered, score in items:
            for r in triggered:
                rule_counts[r['name']] += 1
    for name, cnt in sorted(rule_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {cnt}次")

    conn.close()


if __name__ == '__main__':
    main()
