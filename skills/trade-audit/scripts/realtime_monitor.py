#!/usr/bin/env python3
"""盘中实时风控监控 —— 每30分钟执行一次

检查项:
  1. 浮盈三阶段管理（3%/5%/8%）
  2. 止损-5%触发
  3. 连亏状态预警
  4. 同日交易频次
  5. 感情股持仓预警

用法:
  MYSQL_PWD=xxx python realtime_monitor.py                # 控制台输出
  MYSQL_PWD=xxx python realtime_monitor.py --push-feishu  # 推送飞书

数据源:
  - 持仓: trade_audit (sell_date IS NULL)
  - 实时行情: TDX API (via tdx_client)
"""
import argparse
import os
import sys
from datetime import datetime, date
from collections import defaultdict

import pymysql

sys.path.insert(0, os.path.dirname(__file__))
from tdx_client import TDXClient

# ─── 配置 ──────────────────────────────────────────────────

MYSQL_HOST = '192.168.123.104'
MYSQL_PORT = 3306
MYSQL_USER = 'root'
MYSQL_DB = 'hermes'

# 浮盈三阶段阈值
PROFIT_STAGE_1 = 0.03   # 3%: 设保本止损
PROFIT_STAGE_2 = 0.05   # 5%: 跟踪止盈, 回撤3%卖出50%
PROFIT_STAGE_3 = 0.08   # 8%: 收紧止盈, 回撤2%卖出100%

STOP_LOSS_PCT = -0.05    # -5%: 无条件卖出

# 同日上限
SAME_DAY_LIMIT = 4

# 感情股黑名单
BLACKLIST = {
    '002195': '岩山科技',
    '002506': '协鑫集成',
    '002929': '润建股份',
}


# ─── TDX行情 ──────────────────────────────────────────────

def fetch_quotes(codes):
    """批量获取实时行情 (via TDX), 返回 {code: {'price', 'name', 'change_pct', 'yesterday_close'}}"""
    if not codes:
        return {}

    tdx = TDXClient()

    # codes是6位纯数字列表, batch_quote接受6位或TDX格式
    try:
        raw = tdx.batch_quote(codes)
    except Exception as e:
        print(f"  [ERROR] TDX batch_quote失败: {e}", file=sys.stderr)
        return {}

    results = {}
    for code in codes:
        q = raw.get(code)
        if not q:
            continue
        results[code] = {
            'price': q.get('price', 0),
            'name': '',  # name从holdings表获取, 此处留空
            'change_pct': q.get('change_pct', 0),
            'yesterday_close': q.get('prev_close', 0),
        }

    return results


# ─── 连亏计算 ──────────────────────────────────────────────

def get_consecutive_losses(cur):
    """获取当前连亏笔数"""
    cur.execute("""
        SELECT pnl_rate FROM trade_audit 
        WHERE buy_date IS NOT NULL ORDER BY buy_date DESC, id DESC
    """)
    rows = cur.fetchall()
    consec = 0
    for r in rows:
        pnl = float(r[0] or 0)
        if pnl < 0:
            consec += 1
        else:
            break
    return consec


# ─── 主逻辑 ────────────────────────────────────────────────

def run_monitor(cur, push_feishu=False):
    """执行盘中风控检查"""
    alerts = []  # (level, icon, message)
    now = datetime.now()
    today = now.date()

    # 1. 获取当前持仓（从holdings表取最新日期）
    cur.execute("""
        SELECT h.stock_code, h.stock_name, h.shares, h.cost_price, 
               h.current_price, h.pnl_pct, h.account_name, h.date
        FROM holdings h
        INNER JOIN (
            SELECT MAX(date) as max_date FROM holdings
        ) latest ON h.date = latest.max_date
        WHERE h.shares > 0
        ORDER BY h.pnl_pct ASC
    """)
    positions = []
    for r in cur.fetchall():
        positions.append({
            'stock_code': r[0],
            'stock_name': r[1],
            'shares': int(r[2] or 0),
            'cost_price': float(r[3] or 0),
            'current_price_db': float(r[4] or 0),
            'pnl_pct_db': float(r[5] or 0),
            'account': r[6],
            'holdings_date': r[7],
        })

    if not positions:
        # 无持仓时只检查连亏状态
        consec = get_consecutive_losses(cur)
        if consec >= 3:
            alerts.append(('RED', '🔴', f'连亏状态: {consec}笔 — 强制冷却，禁止买入'))
        elif consec >= 2:
            alerts.append(('YELLOW', '⚡', f'连亏状态: {consec}笔 — 新开仓仓位减半'))
        
        if not alerts:
            return alerts  # 无持仓无预警，静默
        else:
            return alerts

    # 2. 获取实时行情
    codes = [p['stock_code'] for p in positions]
    quotes = fetch_quotes(codes)

    # 3. 逐只检查
    stop_loss_alerts = []
    profit_alerts = []
    blacklist_alerts = []

    for pos in positions:
        code = pos['stock_code']
        name = pos['stock_name'] or code
        cost_price = pos['cost_price']
        shares = pos['shares']
        if cost_price <= 0:
            continue

        q = quotes.get(code, {})
        current_price = q.get('price', 0)
        if current_price <= 0:
            current_price = pos['current_price_db']  # 回退到DB价格
        if current_price <= 0:
            continue

        current_profit = (current_price - cost_price) / cost_price
        # 用DB中的pnl_pct作为历史最大浮盈参考（保守估计）
        max_profit = max(float(pos.get('pnl_pct_db') or 0) / 100, current_profit)
        if max_profit <= 0:
            max_profit = current_profit

        # 3a. 止损检查
        if current_profit <= STOP_LOSS_PCT:
            stop_loss_alerts.append(
                f"🔴 {name}({code}) 亏损{current_profit*100:+.1f}% — 触及-5%止损，无条件卖出"
            )
        # 3b. 浮盈三阶段
        elif current_profit >= PROFIT_STAGE_3:
            drawdown = (max_profit - current_profit) / max_profit if max_profit > 0 else 0
            if drawdown >= 0.02:
                profit_alerts.append(
                    f"⚠️ {name}({code}) 浮盈{current_profit*100:.1f}%(最高{max_profit*100:.1f}%) — 回撤>{2}%, 卖出全部"
                )
            else:
                profit_alerts.append(
                    f"💡 {name}({code}) 浮盈{current_profit*100:.1f}%(≥8%阶段) — 收紧止盈，回撤2%卖出"
                )
        elif current_profit >= PROFIT_STAGE_2:
            drawdown = (max_profit - current_profit) / max_profit if max_profit > 0 else 0
            if drawdown >= 0.03:
                profit_alerts.append(
                    f"⚠️ {name}({code}) 浮盈{current_profit*100:.1f}%(最高{max_profit*100:.1f}%) — 回撤>3%, 卖出50%"
                )
            else:
                profit_alerts.append(
                    f"💡 {name}({code}) 浮盈{current_profit*100:.1f}%(≥5%阶段) — 跟踪止盈，回撤3%卖出50%"
                )
        elif current_profit >= PROFIT_STAGE_1:
            profit_alerts.append(
                f"💡 {name}({code}) 浮盈{current_profit*100:.1f}%(≥3%阶段) — 设保本止损"
            )

        # 3c. 黑名单持仓预警
        if code in BLACKLIST:
            blacklist_alerts.append(
                f"🔴 {name}({code}) 是黑名单感情股({BLACKLIST[code]}) — 建议尽快清仓"
            )

    # 4. 连亏状态
    consec = get_consecutive_losses(cur)
    consec_msg = ''
    if consec >= 3:
        consec_msg = f'🔴 当前连亏{consec}笔 — 强制冷却，禁止买入'
    elif consec >= 2:
        consec_msg = f'⚡ 当前连亏{consec}笔 — 新开仓仓位减半'

    # 5. 同日交易笔数
    cur.execute("""
        SELECT COUNT(*) FROM trade_audit 
        WHERE buy_date = %s AND buy_date IS NOT NULL
    """, (today.isoformat(),))
    today_cnt = int(cur.fetchone()[0])
    freq_msg = ''
    if today_cnt >= SAME_DAY_LIMIT:
        freq_msg = f'🔴 今日已买入{today_cnt}只(上限{SAME_DAY_LIMIT}只) — 停止交易'

    # ── 组装输出 ──
    lines = []
    has_alert = False

    # 持仓概览
    lines.append(f'### 持仓概览（{len(positions)}只）')
    lines.append('')
    lines.append('| 股票 | 代码 | 持仓 | 成本 | 现价 | 浮盈 |')
    lines.append('|------|------|------|------|------|------|')
    for pos in positions:
        code = pos['stock_code']
        q = quotes.get(code, {})
        cp = q.get('price', pos['current_price_db']) or pos['current_price_db']
        if cp and pos['cost_price'] > 0:
            pf = (cp - pos['cost_price']) / pos['cost_price'] * 100
        else:
            pf = float(pos['pnl_pct_db'] or 0)
        lines.append(f"| {pos['stock_name']} | {code} | {pos['shares']} | {pos['cost_price']:.2f} | {cp or 0:.2f} | {pf:+.1f}% |")
    lines.append('')

    if stop_loss_alerts:
        has_alert = True
        lines.append('### 🔴 止损触发（立即执行）')
        for a in stop_loss_alerts:
            lines.append(f'- {a}')
        lines.append('')

    if profit_alerts:
        has_alert = True
        lines.append('### ⚠️ 浮盈管理')
        for a in profit_alerts:
            lines.append(f'- {a}')
        lines.append('')

    if blacklist_alerts:
        has_alert = True
        lines.append('### 🔴 黑名单持仓')
        for a in blacklist_alerts:
            lines.append(f'- {a}')
        lines.append('')

    if consec_msg:
        has_alert = True
        lines.append('### ⚡ 状态预警')
        lines.append(f'- {consec_msg}')
        lines.append('')

    if freq_msg:
        has_alert = True
        lines.append(f'- {freq_msg}')

    if not has_alert:
        return []  # 无警报，静默

    # 标题
    header = f'## 盘中风控警报 {now.strftime("%Y-%m-%d %H:%M")}'
    output = header + '\n\n' + '\n'.join(lines)

    if push_feishu:
        return output  # 返回格式化文本供飞书推送
    else:
        print(output)
        return output


def main():
    parser = argparse.ArgumentParser(description='盘中实时风控监控')
    parser.add_argument('--push-feishu', action='store_true', help='格式化输出供飞书推送')
    args = parser.parse_args()

    pwd = os.environ.get('MYSQL_PWD', '')
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                           password=pwd, database=MYSQL_DB, charset='utf8mb4')
    cur = conn.cursor()

    try:
        run_monitor(cur, push_feishu=args.push_feishu)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
