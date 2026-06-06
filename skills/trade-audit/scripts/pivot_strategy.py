#!/usr/bin/env python3
"""潜行轴心点策略 (Stealth Pivot Strategy)

基于道格的15分钟K线入场策略，适配A股T+1市场。
核心逻辑：价格到支撑位 → 等15分止跌K线 → 等确认K线 → 入场。

数据源:
  - 日线四线: tdx_data.day_kline
  - 15分K线: hermes.kline_15min
  - 实时行情: TDX API (tdx_client)

用法:
  MYSQL_PWD=xxx python pivot_strategy.py --stock 002491 --signal
  MYSQL_PWD=xxx python pivot_strategy.py --stock 002491 --signal --verbose
"""
import argparse
import os
import sys

from datetime import datetime, date, timedelta

import pymysql

# ─── 配置 ──────────────────────────────────────────────────

MYSQL_HOST = '192.168.123.104'
MYSQL_PORT = 3306
MYSQL_USER = 'root'
MYSQL_DB = 'hermes'

# 策略参数
SUPPORT_TOLERANCE = 0.01      # 支撑位距离容差 ±1%
SWING_LOOKBACK = 20           # 摆动高低点回溯天数
RELIABLE_HOURS = [(11, 0, 11, 30), (13, 0, 13, 30)]  # 可靠时段


# ─── TDX 客户端 ──────────────────────────────────────────

_tdx_client = None

def _get_tdx():
    """懒加载 TDXClient 单例"""
    global _tdx_client
    if _tdx_client is None:
        sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser('~/.hermes/local'))  # 私有工具库
        from tdx_client import TDXClient
        _tdx_client = TDXClient()
    return _tdx_client

# ─── 数据获取 ──────────────────────────────────────────────

def get_tencent_price(code):
    """通过 TDXClient 获取实时行情

    返回格式(兼容旧接口):
        {'name': str, 'price': float, 'yesterday_close': float}  或  None
    """
    try:
        tdx = _get_tdx()
        q = tdx.quote(code)
        if q is None:
            return None
        # 尝试从 _raw 取股票名称
        name = ''
        raw = q.get('_raw', {})
        if isinstance(raw, dict):
            name = raw.get('Name', '')
        # 回退: 用 search 查一次
        if not name:
            results = tdx.search(code)
            if results:
                name = results[0].get('Name', '') if isinstance(results[0], dict) else ''
        return {
            'name': name,
            'price': float(q['price']),
            'yesterday_close': float(q['prev_close']),
        }
    except Exception as e:
        print(f"  [WARN] 获取实时行情失败(TDX): {e}", file=sys.stderr)
        return None


def get_pivot_levels(cur, code, trade_date):
    """
    计算四线:
      range_high: 前一交易日最高价
      range_low:  前一交易日最低价
      swing_high: 近20日最高价 (不含当天)
      swing_low:  近20日最低价 (不含当天)
    """
    # 前一交易日高低
    cur.execute("""
        SELECT high, low FROM tdx_data.day_kline
        WHERE stock_code = %s AND trade_date < %s
        ORDER BY trade_date DESC LIMIT 1
    """, (code, trade_date))
    prev = cur.fetchone()
    if not prev or float(prev[0]) <= 0:
        return None
    range_high = float(prev[0])
    range_low = float(prev[1])

    # 近20日摆动高低 (不含当天)
    cur.execute("""
        SELECT MAX(high), MIN(low) FROM tdx_data.day_kline
        WHERE stock_code = %s AND trade_date < %s
        AND trade_date >= DATE_SUB(%s, INTERVAL %s DAY)
    """, (code, trade_date, trade_date, SWING_LOOKBACK + 5))
    swing = cur.fetchone()
    if not swing:
        return None
    swing_high = float(swing[0]) if swing[0] else range_high
    swing_low = float(swing[1]) if swing[1] else range_low

    return {
        'range_high': range_high,
        'range_low': range_low,
        'swing_high': max(swing_high, range_high),
        'swing_low': min(swing_low, range_low),
    }


def get_15min_klines(cur, code, trade_date):
    """获取指定日期的15分K线"""
    cur.execute("""
        SELECT kline_date, open, high, low, close_price, volume
        FROM kline_15min
        WHERE stock_code = %s AND DATE(kline_date) = %s
        ORDER BY kline_date
    """, (code, trade_date))
    rows = cur.fetchall()
    klines = []
    for r in rows:
        klines.append({
            'time': r[0],
            'open': float(r[1]),
            'high': float(r[2]),
            'low': float(r[3]),
            'close': float(r[4]),
            'volume': int(r[5] or 0),
        })
    return klines


# ─── 信号检测 ──────────────────────────────────────────────

def detect_reversal_candle(candle):
    """
    止跌K线判定 (做多方向):
      1. 下影线长度 > 实体长度
      2. 收盘价 > 最低价 + (最高价-最低价) * 0.3
    """
    o = candle['open']
    h = candle['high']
    l = candle['low']
    c = candle['close']
    rng = h - l
    if rng <= 0:
        return False, 0.0

    body = abs(c - o)
    lower_shadow = min(o, c) - l
    shadow_body_ratio = lower_shadow / body if body > 0 else 999.0

    cond1 = lower_shadow > body
    cond2 = c > l + rng * 0.3

    return (cond1 and cond2), shadow_body_ratio


def is_reliable_time(candle_time):
    """判断K线时间是否在可靠时段"""
    if isinstance(candle_time, datetime):
        h, m = candle_time.hour, candle_time.minute
    else:
        return False
    for start_h, start_m, end_h, end_m in RELIABLE_HOURS:
        if start_h <= h <= end_h:
            if h == start_h and m < start_m:
                continue
            if h == end_h and m > end_m:
                continue
            return True
    return False


def check_pivot_signal(levels, klines, current_price, verbose=False):
    """
    综合检查潜行轴心点信号。

    返回: (signal, details)
      signal: 'BUY' | 'WAIT' | 'NO_SUPPORT'
      details: dict with explanation
    """
    range_low = levels['range_low']
    swing_low = levels['swing_low']

    # 1. 价格是否在支撑位附近
    near_range_low = abs(current_price - range_low) / range_low <= SUPPORT_TOLERANCE
    near_swing_low = (swing_low != range_low and
                      abs(current_price - swing_low) / swing_low <= SUPPORT_TOLERANCE)

    support_type = None
    support_price = 0
    if near_range_low:
        support_type = '区间低点'
        support_price = range_low
    elif near_swing_low:
        support_type = '摆动低点'
        support_price = swing_low

    if support_type is None:
        dist_range = (current_price - range_low) / range_low * 100
        dist_swing = (current_price - swing_low) / swing_low * 100
        return 'NO_SUPPORT', {
            'reason': '价格不在支撑位附近',
            'dist_range_low': f'{dist_range:+.1f}%',
            'dist_swing_low': f'{dist_swing:+.1f}%',
        }

    # 2. 扫描15分K线寻找止跌信号
    if not klines:
        return 'WAIT', {
            'reason': '无15分K线数据',
            'support_type': support_type,
            'support_price': support_price,
        }

    signals = []
    for i in range(len(klines) - 1):
        k = klines[i]
        is_rev, ratio = detect_reversal_candle(k)

        if not is_rev:
            continue

        # 止跌K线的最低价是否接近支撑位
        k_low = k['low']
        near_support = abs(k_low - support_price) / support_price <= SUPPORT_TOLERANCE * 2

        if not near_support:
            continue

        # 检查时段可靠性
        time_ok = is_reliable_time(k['time'])

        # 检查确认K线（下一根收盘更高）
        next_k = klines[i + 1]
        confirmed = next_k['close'] > k['close']

        time_str = k['time'].strftime('%H:%M') if hasattr(k['time'], 'strftime') else str(k['time'])
        signals.append({
            'time': time_str,
            'reversal_ratio': ratio,
            'time_ok': time_ok,
            'confirmed': confirmed,
            'confirm_time': next_k['time'].strftime('%H:%M') if hasattr(next_k['time'], 'strftime') else str(next_k['time']),
            'candle_low': k_low,
        })

    if not signals:
        return 'WAIT', {
            'reason': '支撑位附近无止跌K线',
            'support_type': support_type,
            'support_price': support_price,
        }

    # 找到最优信号（有时段确认 + K线确认的优先）
    best = None
    for s in signals:
        if s['confirmed'] and s['time_ok']:
            best = s
            break  # 第一个双确认的信号

    if best is None:
        # 只有时段确认
        for s in signals:
            if s['time_ok']:
                best = s
                break

    if best is None:
        # 只有止跌K线
        best = signals[-1]  # 取最近的

    # 判定最终信号
    if best['confirmed'] and best['time_ok']:
        signal = 'BUY'
    elif best['confirmed']:
        signal = 'WAIT'  # 有确认但时段不可靠
    else:
        signal = 'BLOCKED'  # 在支撑位但无止跌确认 → 禁止买入

    detail = {
        'support_type': support_type,
        'support_price': support_price,
        'best_signal': best,
        'all_signals': signals if verbose else None,
        'reason': '',
    }

    if signal == 'BUY':
        detail['reason'] = f"支撑位({support_type})+止跌确认+时段可靠"
    elif best['confirmed']:
        detail['reason'] = f"止跌+确认，但时段不在可靠区间"
    else:
        detail['reason'] = f"在支撑位({support_type})但无止跌确认 → 禁止买入"

    return signal, detail


# ─── 止损止盈计算 ──────────────────────────────────────────

def calc_stop_targets(levels, current_price):
    """计算止损止盈位"""
    swing_low = levels['swing_low']
    range_high = levels['range_high']

    # 初始止损: 摆动低点下方2%
    initial_stop = swing_low * 0.98

    # 绝对止损
    hard_stop = current_price * 0.95

    # 第一目标: 区间高点
    target_1 = range_high

    return {
        'initial_stop': round(initial_stop, 2),
        'hard_stop': round(hard_stop, 2),
        'target_1': round(target_1, 2),
        'stop_pct': round((initial_stop - current_price) / current_price * -100, 1),
        'target_pct': round((target_1 - current_price) / current_price * 100, 1),
    }


# ─── 格式化输出 ────────────────────────────────────────────

def format_pivot_report(levels, signal, detail, targets, current_price, stock_name, verbose=False):
    """格式化输出报告"""
    lines = []

    lines.append("  潜行轴心点信号:")
    lines.append(f"    区间高点: {levels['range_high']:.2f} | 区间低点: {levels['range_low']:.2f}")
    lines.append(f"    摆动高点: {levels['swing_high']:.2f} | 摆动低点: {levels['swing_low']:.2f}")

    dist_range = (current_price - levels['range_low']) / levels['range_low'] * 100
    lines.append(f"    当前价: {current_price:.2f} (距区间低点 {dist_range:+.1f}%)")
    lines.append("")

    if signal == 'NO_SUPPORT':
        lines.append(f"    信号: -- 无信号 ({detail['reason']})")
        lines.append(f"    距区间低点: {detail['dist_range_low']}, 距摆动低点: {detail['dist_swing_low']}")
    else:
        lines.append(f"    支撑位: {detail['support_type']} @ {detail['support_price']:.2f}")
        lines.append("")

        best = detail.get('best_signal')
        if best:
            lines.append("    15分K线信号:")
            ratio_str = f"{best['reversal_ratio']:.1f}x" if best['reversal_ratio'] < 100 else ">100x"
            lines.append(f"      {best['time']} 止跌K线 (下影线{ratio_str}实体) {'  true' if True else ''}")

            # 用unicode checkmark
            rev_mark = "[OK]" if best['reversal_ratio'] > 1 else "[?]"
            time_mark = "[OK]" if best['time_ok'] else "[--]"
            conf_mark = "[OK]" if best['confirmed'] else "[--]"

            lines = []
            lines.append("  潜行轴心点信号:")
            lines.append(f"    区间高点: {levels['range_high']:.2f} | 区间低点: {levels['range_low']:.2f}")
            lines.append(f"    摆动高点: {levels['swing_high']:.2f} | 摆动低点: {levels['swing_low']:.2f}")
            dist_range = (current_price - levels['range_low']) / levels['range_low'] * 100
            lines.append(f"    当前价: {current_price:.2f} (距区间低点 {dist_range:+.1f}%)")
            lines.append("")
            lines.append(f"    支撑位: {detail['support_type']} @ {detail['support_price']:.2f}")
            lines.append("")
            lines.append("    15分K线信号:")

            # 所有信号
            all_sig = detail.get('all_signals') or [best]
            for s in all_sig:
                r_str = f"{s['reversal_ratio']:.1f}x" if s['reversal_ratio'] < 100 else ">>"
                t_ok = "OK" if s['time_ok'] else "--"
                c_ok = "OK" if s['confirmed'] else "--"
                lines.append(f"      {s['time']} 止跌K线 (下影线{r_str}实体) 时段[{t_ok}] 确认[{c_ok}]")
                if s['confirmed']:
                    lines.append(f"      {s['confirm_time']} 确认K线 (收盘更高)")

            lines.append("")

            # 止损止盈
            if targets:
                lines.append("    止损止盈:")
                lines.append(f"      初始止损: {targets['initial_stop']:.2f} (摆动低点-2%, {targets['stop_pct']:.1f}%)")
                lines.append(f"      绝对止损: {targets['hard_stop']:.2f} (-5%)")
                lines.append(f"      第一目标: {targets['target_1']:.2f} (区间高点, +{targets['target_pct']:.1f}%)")

            lines.append("")

            # 最终信号
            if signal == 'BUY':
                lines.append(f"    结论: --> 绿灯 支撑位+止跌确认+时段可靠 --> 可入场")
            else:
                lines.append(f"    结论: --> 黄灯 {detail['reason']}")

    return '\n'.join(lines)


# ─── 主入口 ────────────────────────────────────────────────

def run_pivot_check(code, verbose=False, cur=None):
    """
    执行潜行轴心点检查。
    返回: (signal, report_text, levels, targets)
      signal: 'BUY' | 'WAIT' | 'NO_SUPPORT' | 'ERROR'
    """
    close_conn = False
    if cur is None:
        pwd = os.environ.get('MYSQL_PWD', '')
        conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                               password=pwd, database=MYSQL_DB, charset='utf8mb4')
        cur = conn.cursor()
        close_conn = True

    try:
        today = date.today().isoformat()

        # 获取实时价格
        quote = get_tencent_price(code)
        if quote:
            current_price = quote['price']
            stock_name = quote['name']
        else:
            # 回退：从TDX日线取最新收盘价
            cur.execute("""
                SELECT close_price FROM tdx_data.day_kline
                WHERE stock_code = %s ORDER BY trade_date DESC LIMIT 1
            """, (code,))
            r = cur.fetchone()
            if not r:
                return 'ERROR', f"无法获取 {code} 的价格", None, None
            current_price = float(r[0])
            stock_name = code

        # 获取四线
        levels = get_pivot_levels(cur, code, today)
        if not levels:
            return 'ERROR', f"无法计算 {code} 的轴心点", None, None

        # 获取15分K线（当天）
        klines = get_15min_klines(cur, code, today)

        # 如果当天没有15分K线（非交易时间），取最近的交易日
        if not klines:
            cur.execute("""
                SELECT DATE(kline_date) as d FROM kline_15min
                WHERE stock_code = %s GROUP BY d ORDER BY d DESC LIMIT 1
            """, (code,))
            r = cur.fetchone()
            if r:
                klines = get_15min_klines(cur, code, r[0])

        # 检查信号
        signal, detail = check_pivot_signal(levels, klines, current_price, verbose)

        # 计算止损止盈
        targets = calc_stop_targets(levels, current_price)

        # 格式化报告
        report = format_pivot_report(levels, signal, detail, targets, current_price, stock_name, verbose)

        return signal, report, levels, targets

    finally:
        if close_conn:
            cur.connection.close()


def main():
    parser = argparse.ArgumentParser(description='潜行轴心点策略信号检查')
    parser.add_argument('--stock', type=str, required=True, help='股票代码')
    parser.add_argument('--signal', action='store_true', help='检查当前信号')
    parser.add_argument('--verbose', action='store_true', help='显示所有信号详情')
    args = parser.parse_args()

    if not args.signal:
        print("请使用 --signal 检查信号")
        return

    signal, report, _, _ = run_pivot_check(args.stock, verbose=args.verbose)
    print(report)


if __name__ == '__main__':
    main()
