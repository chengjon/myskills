#!/usr/bin/env python3
"""交易复盘回放器 — 结合TDX API大盘+个股数据还原买卖点

解析券商交易记录md文件，调用TDX API获取：
- 大盘指数日线/分时
- 个股日K/15分K/分时
- 历史逐笔成交(Tick级分析)
自动标注每笔交易的分时位置(分位%)，分类交易行为，V5纪律审查。

用法:
  python3 trade_replay.py --file <交易记录.md> [--date 20260605] [--focus 0605]
  python3 trade_replay.py --file <交易记录.md> --all

输出:
  - 大盘环境
  - 逐股分析(含买卖点vs分时 + Tick级成交分析)
  - V5纪律审查
  - 综合诊断

依赖:
  - TDXClient: ~/.hermes/skills/trade-audit/scripts/tdx_client.py
  - TDX API: http://192.168.123.104:8089 (NAS Docker)
  - Python 3.8+, 无额外依赖

数据格式:
  两融交易记录md文件，支持两种列格式:
  格式A: 含委托日期列(多日数据)
  格式B: 不含委托日期列(当日数据，日期从文件名提取)
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

# ──────────────────── TDX Client ────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tdx_client import TDXClient

tdx = TDXClient()

# ──────────────────── 解析交易记录 ────────────────────

# 买卖标志分类
BUY_KEYWORDS = {'买入', '融资买入', '担保品买入'}
SELL_KEYWORDS = {'卖出', '卖券还款', '担保品卖出', '融资卖出', '融券卖出'}

def parse_action(raw):
    """标准化买卖方向"""
    s = raw.strip()
    if s in BUY_KEYWORDS:
        return 'buy'
    if s in SELL_KEYWORDS:
        return 'sell'
    return 'unknown'

def code_to_tdx(code):
    """6位代码转TDX格式 sz002015/sh601138"""
    if code.startswith(('6', '9')):
        return f"sh{code}"
    return f"sz{code}"

def parse_md_file(filepath):
    """解析券商交易记录md文件，返回交易列表

    Returns:
        list of dict: [{date, time, code, tdx_code, name, action, price, qty, amount, account}, ...]
    """
    trades = []
    filename = os.path.basename(filepath)

    # 从文件名提取日期范围(如 两融20260601-0605 或 两融20260601-20260605)
    m = re.search(r'(\d{4})(\d{4})-(\d{4})', filename)
    if m:
        prefix = m.group(1)  # 2026
        file_end_date = prefix + m.group(3)  # 20260605
    else:
        file_end_date = None

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')

    # 检测是否有格式切换(第二段不含委托日期)
    # 格式A: 委托日期 | 委托时间 | ...
    # 格式B: 委托时间 | ... (第二段)
    section = 'header'  # header -> A -> B
    section_a_date = None  # 格式B的隐含日期
    seen_data = False  # 是否已见过格式A数据行

    for line in lines:
        # 跳过空行
        if not line.strip():
            continue

        # 检测分隔线
        if '---' in line and len(line.strip()) > 20:
            if seen_data:
                section = 'B'  # 第二次遇到分隔线 → 切换到格式B
            else:
                section = 'A'  # 第一次遇到分隔线 → 开始格式A
            continue

        # 跳过表头行
        if '委托日期' in line or '委托时间' in line:
            continue

        # 用多空格分割
        parts = [p.strip() for p in line.split('  ') if p.strip()]

        if len(parts) < 8:
            continue

        # 判断格式
        # 格式A第一列是日期(YYYY-MM-DD)，格式B第一列是时间(HH:MM:SS)
        if re.match(r'\d{4}-\d{2}-\d{2}', parts[0]):
            # 格式A
            section = 'A'
            trade_date = parts[0].replace('-', '')
            # 格式A字段: 日期 委托时间 委托编号 代码 名称 买卖标志 委托价格 委托数量 成交价格 成交数量 成交金额 成交日期 成交时间 ...
            if len(parts) >= 13:
                try:
                    trade = {
                        'date': trade_date,
                        'time': parts[12][:5] if len(parts) > 12 else parts[1][:5],  # 成交时间
                        'code': parts[3],
                        'tdx_code': code_to_tdx(parts[3]),
                        'name': parts[4],
                        'action': parse_action(parts[5]),
                        'price': float(parts[8]),   # 成交价格
                        'qty': int(float(parts[9])),  # 成交数量
                        'amount': float(parts[10]),   # 成交金额
                        'account': parts[14] if len(parts) > 14 else '',
                    }
                    section_a_date = trade_date
                    seen_data = True
                    if trade['action'] != 'unknown':
                        trades.append(trade)
                except (ValueError, IndexError):
                    continue
        elif re.match(r'\d{2}:\d{2}:\d{2}', parts[0]):
            # 格式B(无日期列)
            # 字段: 委托时间 委托编号 代码 名称 买卖标志 委托价格 委托数量 成交价格 成交数量 成交金额 成交时间 ...
            trade_date = file_end_date or section_a_date or ''
            if len(parts) >= 11:
                try:
                    trade = {
                        'date': trade_date,
                        'time': parts[10][:5] if len(parts) > 10 else parts[0][:5],  # 成交时间
                        'code': parts[2],
                        'tdx_code': code_to_tdx(parts[2]),
                        'name': parts[3],
                        'action': parse_action(parts[4]),
                        'price': float(parts[7]),   # 成交价格
                        'qty': int(float(parts[8])),  # 成交数量
                        'amount': float(parts[9]),   # 成交金额
                        'account': parts[12] if len(parts) > 12 else '',
                    }
                    if trade['action'] != 'unknown':
                        trades.append(trade)
                except (ValueError, IndexError):
                    continue

    return trades


# ──────────────────── 数据获取 ────────────────────

# 缓存API结果避免重复请求
_cache = {}

def _date_str(time_val):
    """从TDXClient返回的time字段提取日期部分(前10位)
    TDXClient返回的time带时区后缀如 '2026-06-05T15:00:00+08:00'
    """
    if not time_val:
        return ''
    return time_val[:10]

def get_index_daily():
    """获取上证指数近30天日K"""
    key = 'index_daily'
    if key not in _cache:
        _cache[key] = tdx.index('sh000001', count=30)
    return _cache[key]

def get_stock_daily(tdx_code):
    """获取个股日K近30天"""
    key = f'daily_{tdx_code}'
    if key not in _cache:
        _cache[key] = tdx.kline_day(tdx_code, count=30)
    return _cache[key]

def get_stock_kline15(tdx_code):
    """获取个股15分K线(近5天)"""
    key = f'k15_{tdx_code}'
    if key not in _cache:
        _cache[key] = tdx.kline_15m(tdx_code)
    return _cache[key]

def get_stock_minute(tdx_code, date):
    """获取个股分时数据"""
    key = f'min_{tdx_code}_{date}'
    if key not in _cache:
        _cache[key] = tdx.minute(tdx_code, date)
    return _cache[key]

def get_trade_history(tdx_code, date):
    """获取个股历史逐笔成交(Tick级数据)"""
    key = f'tick_{tdx_code}_{date}'
    if key not in _cache:
        _cache[key] = tdx.trade_history(tdx_code, date)
    return _cache[key]


# ──────────────────── 分析计算 ────────────────────

def calc_position_pct(price, kline15_day):
    """计算价格在当日15分K线中的分位(0-100%)"""
    if not kline15_day:
        return 50.0
    # TDXClient已转换price为元，无需再/1000
    day_high = max(r['high'] for r in kline15_day)
    day_low = min(r['low'] for r in kline15_day)
    if day_high == day_low:
        return 50.0
    return (price - day_low) / (day_high - day_low) * 100

def find_minute_price(minute_data, time_str):
    """找到分时数据中最接近的价格"""
    if not minute_data:
        return None, 0.0
    h, m = int(time_str[:2]), int(time_str[3:5])
    target = h * 60 + m
    best = None
    best_diff = 9999
    for r in minute_data:
        t = r['time']  # TDXClient返回小写key
        if not t:
            continue
        rh, rm = int(t[:2]), int(t[3:5])
        diff = abs(rh * 60 + rm - target)
        if diff < best_diff:
            best_diff = diff
            best = r
    if best:
        return best['price'], (target - int(best['time'][:2])*60 - int(best['time'][3:5]))
    return None, 0

def analyze_tick_level(trade_history, trade_price, trade_time, window_seconds=60):
    """Tick级成交分析: 查找交易前后窗口内的成交特征

    Args:
        trade_history: 逐笔成交列表 [{time, price, volume, is_buy}, ...]
        trade_price: 交易价格(元)
        trade_time: 交易时间 HH:MM
        window_seconds: 前后查找窗口(秒)

    Returns:
        dict: {
            nearby_buys: 附近主动买入笔数,
            nearby_sells: 附近主动卖出笔数,
            avg_tick_price: 附近成交均价,
            tick_imbalance: 买卖力度比(>1主动买强, <1主动卖强),
            volume_at_price: 在交易价格附近的成交量,
            is_good_price: 是否好价格(相对附近均价偏离<0.3%),
        }
    """
    if not trade_history:
        return {
            'nearby_buys': 0, 'nearby_sells': 0,
            'avg_tick_price': 0, 'tick_imbalance': 0,
            'volume_at_price': 0, 'is_good_price': True,
        }

    h, m = int(trade_time[:2]), int(trade_time[3:5])
    target_ts = h * 3600 + m * 60

    nearby = []
    for tick in trade_history:
        t = tick['time']
        if not t or len(t) < 5:
            continue
        th, tm = int(t[:2]), int(t[3:5])
        ts = int(t[6:8]) if len(t) >= 8 else 0  # 秒
        tick_ts = th * 3600 + tm * 60 + ts
        if abs(tick_ts - target_ts) <= window_seconds:
            nearby.append(tick)

    if not nearby:
        return {
            'nearby_buys': 0, 'nearby_sells': 0,
            'avg_tick_price': 0, 'tick_imbalance': 0,
            'volume_at_price': 0, 'is_good_price': True,
        }

    nearby_buys = sum(1 for t in nearby if t['is_buy'])
    nearby_sells = sum(1 for t in nearby if not t['is_buy'])
    total_vol = sum(t['volume'] for t in nearby)
    avg_tick_price = sum(t['price'] * t['volume'] for t in nearby) / total_vol if total_vol > 0 else 0

    # 在交易价格±0.1%附近的成交量
    vol_at_price = sum(t['volume'] for t in nearby if abs(t['price'] - trade_price) / trade_price < 0.001) if trade_price > 0 else 0

    imbalance = nearby_buys / nearby_sells if nearby_sells > 0 else (float('inf') if nearby_buys > 0 else 0)

    is_good = abs(trade_price - avg_tick_price) / avg_tick_price < 0.003 if avg_tick_price > 0 else True

    return {
        'nearby_buys': nearby_buys,
        'nearby_sells': nearby_sells,
        'avg_tick_price': avg_tick_price,
        'tick_imbalance': imbalance,
        'volume_at_price': vol_at_price,
        'is_good_price': is_good,
    }

def classify_trade(trades_of_code_on_day, all_trades_on_day, stock_daily_5d):
    """分类交易行为

    Returns: str - 行为分类
      'low_buy'   低吸买入(分位<30%)
      'high_chase' 追高买入(分位>70%)
      't_success'  做T成功(同日买卖，净卖出)
      't_fail'     做T失败(同日买卖，净买入)
      'avg_buy'    中位买入(30-70%)
      'stop_loss'  止损卖出
      'profit_sell' 止盈/获利卖出
      'avg_sell'   中位卖出
      'new_pos'    新建仓
      'add_pos'    加仓
    """
    buys = [t for t in trades_of_code_on_day if t['action'] == 'buy']
    sells = [t for t in trades_of_code_on_day if t['action'] == 'sell']

    if buys and sells:
        buy_qty = sum(t['qty'] for t in buys)
        sell_qty = sum(t['qty'] for t in sells)
        if sell_qty >= buy_qty:
            return 't_success'
        else:
            return 't_fail'

    if buys:
        avg_pct = sum(t.get('pct', 50) for t in buys) / len(buys)
        if avg_pct < 30:
            return 'low_buy'
        elif avg_pct > 70:
            return 'high_chase'
        else:
            return 'avg_buy'

    if sells:
        avg_pct = sum(t.get('pct', 50) for t in sells) / len(sells)
        # 判断是否亏损(需要前日收盘价)
        # TDXClient已转换price，无需/1000
        if stock_daily_5d and len(stock_daily_5d) >= 2:
            prev_close = stock_daily_5d[-2]['close']
            avg_sell_price = sum(t['price'] * t['qty'] for t in sells) / sum(t['qty'] for t in sells)
            if avg_sell_price < prev_close:
                return 'stop_loss'
            else:
                return 'profit_sell'
        if avg_pct > 70:
            return 'profit_sell'
        return 'avg_sell'

    return 'unknown'


# ──────────────────── 报告生成 ────────────────────

LABELS = {
    'low_buy':    ('🟢低吸', '分位<30%, 低位入场'),
    'high_chase': ('🔴追高', '分位>70%, 高位追涨'),
    't_success':  ('🟢做T成功', '同日低买高卖'),
    't_fail':     ('🔴做T失败', '同日买卖但净买入'),
    'avg_buy':    ('🟡中位买入', '分位30-70%'),
    'stop_loss':  ('🟢止损卖出', '低于前收盘价卖出'),
    'profit_sell':('🟢获利卖出', '高于前收盘价卖出'),
    'avg_sell':   ('🟡中位卖出', '分位30-70%卖出'),
    'new_pos':    ('🟡新建仓', '首次买入'),
    'add_pos':    ('🟡加仓', '已有持仓再加'),
}

def run_replay(filepath, focus_date=None, all_dates=False):
    """主函数：解析交易记录，获取行情数据，生成复盘报告"""

    trades = parse_md_file(filepath)
    if not trades:
        print("未解析到交易记录")
        return

    # 按日期分组
    by_date = defaultdict(list)
    for t in trades:
        by_date[t['date']].append(t)

    dates = sorted(by_date.keys())

    # 确定分析日期
    if focus_date:
        focus_date = focus_date.replace('-', '')
        if focus_date not in by_date:
            print(f"日期 {focus_date} 无交易记录")
            return
        target_dates = [focus_date]
    elif all_dates:
        target_dates = dates
    else:
        # 默认分析最后一天
        target_dates = [dates[-1]]

    # ── 大盘环境 ──
    print("=" * 72)
    print(f"    交易复盘回放 — {os.path.basename(filepath)}")
    print(f"    分析日期: {', '.join(target_dates)}")
    print("=" * 72)

    idx_data = get_index_daily()

    for target_date in target_dates:
        day_trades = by_date[target_date]

        print(f"\n{'━' * 72}")
        print(f"  📅 {target_date}  共 {len(day_trades)} 笔交易")
        print(f"{'━' * 72}")

        # ── 大盘 ──
        date_fmt = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
        idx_row = None
        idx_prev = None
        for i, r in enumerate(idx_data):
            # TDXClient返回的time字段可能带时区，取前10位做日期匹配
            r_date = _date_str(r.get('time', ''))
            if date_fmt in r_date:
                idx_row = r
                idx_prev = idx_data[i - 1] if i > 0 else None
                break

        if idx_row:
            # TDXClient已转换price为元，无需/1000
            o = idx_row['open']
            c = idx_row['close']
            h = idx_row['high']
            l = idx_row['low']
            chg = (c - o) / o * 100
            trend = "上涨" if chg > 0.5 else ("下跌" if chg < -0.5 else "震荡")
            print(f"\n  【大盘环境】")
            print(f"    上证指数: {o:.2f} → {c:.2f} ({chg:+.2f}%) {trend}")
            print(f"    振幅: {l:.2f} - {h:.2f}")
            print(f"    涨{idx_row['up_count']}家 / 跌{idx_row['down_count']}家")
        else:
            print(f"\n  【大盘环境】 未获取到 {date_fmt} 数据")

        # ── 汇总 ──
        buy_total = sum(t['price'] * t['qty'] for t in day_trades if t['action'] == 'buy')
        sell_total = sum(t['price'] * t['qty'] for t in day_trades if t['action'] == 'sell')
        codes_this_day = list(set(t['tdx_code'] for t in day_trades))

        print(f"\n  【当日汇总】")
        print(f"    买入: {buy_total:>12,.0f} 元")
        print(f"    卖出: {sell_total:>12,.0f} 元")
        print(f"    净额: {buy_total - sell_total:>+12,.0f} 元")
        print(f"    涉及: {len(codes_this_day)} 只股票")

        # ── 逐股分析 ──
        print(f"\n  {'─' * 68}")
        print(f"  【逐股分析】")
        print(f"  {'─' * 68}")

        violations = []  # V5违规记录
        analysis_results = []

        for tdx_code in sorted(set(t['tdx_code'] for t in day_trades)):
            stock_trades = [t for t in day_trades if t['tdx_code'] == tdx_code]
            name = stock_trades[0]['name']

            # 获取行情数据
            daily = get_stock_daily(tdx_code)
            k15 = get_stock_kline15(tdx_code)
            # 日期匹配: TDXClient的time带时区，需取前10位
            k15_day = [r for r in k15 if date_fmt in _date_str(r.get('time', ''))]
            minute = get_stock_minute(tdx_code, target_date)
            tick_data = get_trade_history(tdx_code, target_date)

            # 日K信息
            dk_row = None
            dk_prev = None
            for i, r in enumerate(daily):
                if date_fmt in _date_str(r.get('time', '')):
                    dk_row = r
                    dk_prev = daily[i - 1] if i > 0 else None
                    break

            print(f"\n    ━━ {stock_trades[0]['code']} {name} ━━")

            # 近5日走势
            if daily:
                recent = daily[-5:]
                chg5 = (recent[-1]['close'] - recent[0]['open']) / recent[0]['open'] * 100
                trend5 = "↑" if chg5 > 0 else "↓"
                dates_s = " → ".join([f"{_date_str(r['time'])[5:10]}C{r['close']:.2f}" for r in recent])
                print(f"    近5日{trend5}{abs(chg5):.1f}%: {dates_s}")

            # 当日K线概况
            if dk_row:
                # TDXClient已转换，无需/1000
                do = dk_row['open']
                dc = dk_row['close']
                dh = dk_row['high']
                dl = dk_row['low']
                day_chg = (dc - do) / do * 100
                if dk_prev:
                    prev_c = dk_prev['close']
                    gap = (do - prev_c) / prev_c * 100
                    gap_type = "高开" if gap > 0.5 else ("低开" if gap < -0.5 else "平开")
                    print(f"    当日: O{do:.2f} H{dh:.2f} L{dl:.2f} C{dc:.2f} ({day_chg:+.2f}%) {gap_type}{gap:+.2f}%")
                else:
                    print(f"    当日: O{do:.2f} H{dh:.2f} L{dl:.2f} C{dc:.2f} ({day_chg:+.2f}%)")

            # ── Tick级成交分析汇总 ──
            if tick_data:
                total_buy_vol = sum(t['volume'] for t in tick_data if t['is_buy'])
                total_sell_vol = sum(t['volume'] for t in tick_data if not t['is_buy'])
                total_tick_vol = total_buy_vol + total_sell_vol
                buy_ratio = total_buy_vol / total_tick_vol * 100 if total_tick_vol > 0 else 50
                tick_imb = "主买" if buy_ratio > 55 else ("主卖" if buy_ratio < 45 else "均衡")
                print(f"    Tick: {len(tick_data)}笔 主动买{total_buy_vol/10000:.1f}万手({buy_ratio:.0f}%) 主动卖{total_sell_vol/10000:.1f}万手 {tick_imb}")

            # 逐笔交易
            for t in sorted(stock_trades, key=lambda x: x['time']):
                pct = calc_position_pct(t['price'], k15_day)
                t['pct'] = pct
                mkt_price, time_diff = find_minute_price(minute, t['time'])
                diff_str = ""
                if mkt_price:
                    diff = (t['price'] - mkt_price) / mkt_price * 100
                    pos = "高于" if diff > 0.1 else ("低于" if diff < -0.1 else "≈")
                    diff_str = f"市价{mkt_price:.2f}({pos}{diff:+.1f}%)"

                # Tick级分析
                tick_str = ""
                if tick_data:
                    tick_info = analyze_tick_level(tick_data, t['price'], t['time'])
                    t['tick'] = tick_info
                    imb = tick_info['tick_imbalance']
                    if imb == float('inf'):
                        imb_str = "∞"
                    elif imb > 0:
                        imb_str = f"{imb:.1f}"
                    else:
                        imb_str = "0"
                    # 标记成交质量
                    quality = "✅" if tick_info['is_good_price'] else "⚠️"
                    tick_str = f" Tick:买{tick_info['nearby_buys']}/卖{tick_info['nearby_sells']} 力度{imb_str} {quality}"

                icon = "🔴" if t['action'] == 'buy' else "🟢"
                action_name = "买入" if t['action'] == 'buy' else "卖出"
                print(f"      {t['time']} {icon}{action_name:4s} {t['qty']:>5}股 @{t['price']:<8.2f} 分位{pct:>3.0f}% {diff_str}{tick_str}")

            # 分类
            if dk_row:
                stock_5d = [r for r in daily if _date_str(r.get('time', '')) <= date_fmt][-5:]
            else:
                stock_5d = daily[-5:] if daily else []
            trade_type = classify_trade(stock_trades, day_trades, stock_5d)
            label, desc = LABELS.get(trade_type, ('❓未知', ''))

            # 计算收盘浮盈亏
            pnl_str = ""
            if dk_row and any(t['action'] == 'buy' for t in stock_trades):
                dc = dk_row['close']
                buys = [t for t in stock_trades if t['action'] == 'buy']
                avg_buy = sum(t['price'] * t['qty'] for t in buys) / sum(t['qty'] for t in buys)
                pnl_pct = (dc - avg_buy) / avg_buy * 100
                pnl_str = f"收盘浮盈{pnl_pct:+.1f}%(均买{avg_buy:.2f}→收{dc:.2f})"

            print(f"    → {label}: {desc} {pnl_str}")

            # V5违规检测
            buys = [t for t in stock_trades if t['action'] == 'buy']
            if buys:
                avg_pct = sum(t.get('pct', 50) for t in buys) / len(buys)
                if avg_pct > 70:
                    violations.append(('🔴', name, f'追高入场(分位{avg_pct:.0f}%)'))
                if len(buys) >= 3:
                    violations.append(('🟡', name, f'单股{len(buys)}笔加仓'))

            if trade_type == 't_fail':
                violations.append(('🔴', name, '做T失败(买回>卖出)'))

        # ── V5纪律审查 ──
        print(f"\n  {'━' * 68}")
        print(f"  【V5纪律审查】")
        print(f"  {'━' * 68}")

        # 规则1: 单日过度交易
        if len(day_trades) > 15:
            violations.append(('🔴', '全局', f'过度交易: {len(day_trades)}笔/{len(codes_this_day)}只'))
        elif len(codes_this_day) > 5:
            violations.append(('🟡', '全局', f'股票过多: {len(codes_this_day)}只(建议≤5)'))

        # 规则2: 净买入金额过大
        net = buy_total - sell_total
        if net > 200000 and buy_total > 0:
            violations.append(('🟡', '全局', f'大幅净买入{net/10000:+.1f}万'))

        # 规则3: 开盘5分钟急扫
        early_trades = [t for t in day_trades if t['time'] < '09:45' and t['action'] == 'buy']
        if len(early_trades) >= 3:
            violations.append(('🔴', '全局', f'开盘急扫: 09:45前{len(early_trades)}笔买入'))

        if not violations:
            print("    ✅ 无违规")
        else:
            red = [v for v in violations if v[0] == '🔴']
            yellow = [v for v in violations if v[0] == '🟡']
            if red:
                print(f"\n    🔴 严重违规({len(red)}条):")
                for _, stock, desc in red:
                    print(f"      • {stock}: {desc}")
            if yellow:
                print(f"\n    🟡 轻度违规({len(yellow)}条):")
                for _, stock, desc in yellow:
                    print(f"      • {stock}: {desc}")

        # ── 评分 ──
        score = 100
        for v in violations:
            if v[0] == '🔴':
                score -= 15
            else:
                score -= 5
        score = max(score, 0)
        grade = 'A' if score >= 90 else ('B' if score >= 75 else ('C' if score >= 60 else ('D' if score >= 40 else 'F')))
        print(f"\n    交易纪律评分: {score}/100 (等级{grade})")


def main():
    parser = argparse.ArgumentParser(description='交易复盘回放器')
    parser.add_argument('--file', '-f', required=True, help='交易记录md文件路径')
    parser.add_argument('--date', '-d', help='聚焦日期(YYYYMMDD)')
    parser.add_argument('--all', '-a', action='store_true', help='分析所有日期')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"文件不存在: {args.file}")
        sys.exit(1)

    run_replay(args.file, focus_date=args.date, all_dates=getattr(args, 'all', False))


if __name__ == '__main__':
    main()
