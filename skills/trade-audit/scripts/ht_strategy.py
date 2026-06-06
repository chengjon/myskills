#!/usr/bin/env python3
"""汇通理论 — 尾盘买入隔日交易系统 (HuiTong Strategy)

数据源: TDX API REST (tdx_client.py)
文档: Hermes/DOCS/网络收集/尾盘买入隔日交易系统-汇通理论.md

用法:
  # 实时选股(14:30执行)
  python3 ht_strategy.py --scan

  # 指定日期选股(回测模式)
  python3 ht_strategy.py --scan --date 20260605

  # 只输出活跃股池(不执行完整筛选)
  python3 ht_strategy.py --pool active

  # 查看指定股票的止跌信号
  python3 ht_strategy.py --signal 600172

  # 查看大盘环境
  python3 ht_strategy.py --market

配置: ht_config.yaml (同目录，可调参数)
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/local'))  # 私有工具库
from tdx_client import TDXClient

# ──── 默认参数 (可被 ht_config.yaml 覆盖) ────

CONFIG = {
    # 选股参数
    'active_days': [10, 20],          # 活跃股回溯天数
    'active_threshold': 7.0,          # 单日涨幅阈值(%)
    'limit_up_threshold': 9.8,        # 涨停阈值(%)
    'trend_days': 25,                 # 强趋势回溯天数
    'trend_gain': 50.0,               # 强趋势涨幅阈值(%)
    'top_amount_count': 50,           # 成交额前N
    'min_amount': 1e8,                # 最低成交额(1亿)
    'max_consecutive_up': 3,          # 最大连涨天数
    'ma_near_pct': 3.0,              # 均线附近范围(%)

    # 止跌信号参数
    'shadow_ratio': 2.0,             # 下影线/实体比
    'doji_body_pct': 0.1,            # 十字星实体占比
    'flat_bottom_diff': 1.0,         # 平底最低价差(%)
    'dawn_penetration': 0.5,         # 曙光初现深入比例

    # 买入参数
    'buy_time': '14:30',             # 买入时间窗口
    'max_buy_pct': 2.0,              # 最大允许阳线(%)
    'max_picks': 3,                  # 最多选几只

    # 大盘参数
    'index_code': 'sh000001',        # 参考指数
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,

    # 数据源
    'scan_universe': 'auto',         # auto=all A / etf=ETF / index=指数成分
}


def load_config():
    """加载ht_config.yaml覆盖默认参数"""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ht_config.yaml')
    if os.path.exists(cfg_path):
        import yaml
        with open(cfg_path) as f:
            user_cfg = yaml.safe_load(f) or {}
        CONFIG.update(user_cfg)


tdx = None

def get_tdx():
    global tdx
    if tdx is None:
        tdx = TDXClient()
    return tdx


# ──── 工具函数 ────

def calc_ma(closes, period):
    """计算移动平均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_ema(values, period):
    """计算EMA"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD"""
    if len(closes) < slow + signal:
        return None, None, None
    ema_f = calc_ema(closes, fast)
    ema_s = calc_ema(closes, slow)
    # 对齐
    offset = len(ema_f) - len(ema_s)
    dif = [ema_f[i + offset] - ema_s[i] for i in range(len(ema_s))]
    dea = calc_ema(dif, signal)
    offset2 = len(dif) - len(dea)
    macd = [(dif[i + offset2] - dea[i]) * 2 for i in range(len(dea))]
    return dif, dea, macd


def kline_body(k):
    """K线实体大小"""
    return abs(k['close'] - k['open'])


def kline_upper_shadow(k):
    """上影线"""
    return k['high'] - max(k['open'], k['close'])


def kline_lower_shadow(k):
    """下影线"""
    return min(k['open'], k['close']) - k['low']


def kline_is_yang(k):
    """阳线"""
    return k['close'] >= k['open']


def kline_change_pct(k):
    """涨跌幅(需前一日close)"""
    return k.get('change_pct', 0)


def date_str(s):
    """从TDX时间字符串取日期部分"""
    return str(s)[:10]


# ──── 模块1: 大盘环境判断 ────

def check_market_env(tdx_client=None):
    """大盘环境判断

    Returns:
        dict: {
            status: 'bull'/'neutral'/'bear',
            index_close, ma20, above_ma20,
            macd_above_zero,
            position_pct: 0/50/100,
            details: str
        }
    """
    tdx = tdx_client or get_tdx()
    idx = tdx.index(CONFIG['index_code'], count=60)
    if not idx or len(idx) < 30:
        return {'status': 'unknown', 'position_pct': 0, 'details': '数据不足'}

    closes = [r['close'] for r in idx]
    ma20 = calc_ma(closes, 20)
    ma5 = calc_ma(closes, 5)
    last_close = closes[-1]

    dif, dea, macd_hist = calc_macd(
        closes,
        CONFIG['macd_fast'],
        CONFIG['macd_slow'],
        CONFIG['macd_signal']
    )

    above_ma20 = ma20 and last_close > ma20
    macd_above = dif and dif[-1] > 0 if dif else False

    if above_ma20 and macd_above:
        status = 'bull'
        position_pct = 100
        details = f'上证{last_close:.2f} > MA20({ma20:.2f}), MACD零轴上方'
    elif above_ma20 and not macd_above:
        status = 'neutral'
        position_pct = 50
        details = f'上证{last_close:.2f} > MA20({ma20:.2f}), MACD零轴下方(谨慎)'
    else:
        status = 'bear'
        position_pct = 0
        details = f'上证{last_close:.2f} < MA20({ma20:.2f}), 空仓观望'

    return {
        'status': status,
        'index_close': last_close,
        'ma5': ma5,
        'ma20': ma20,
        'above_ma20': above_ma20,
        'macd_above_zero': macd_above,
        'position_pct': position_pct,
        'details': details,
    }


# ──── 模块2: 选股引擎 ────

def scan_active_pool(klines_map, days_list=None, threshold=None):
    """备选池一: 活跃股 (近N日有过涨停或大涨)

    Args:
        klines_map: {code: [kline_dict, ...]} 日K数据
        days_list: 回溯天数列表 [10, 20]
        threshold: 单日涨幅阈值(%)

    Returns:
        set of codes
    """
    days_list = days_list or CONFIG['active_days']
    threshold = threshold or CONFIG['active_threshold']
    limit_up = CONFIG['limit_up_threshold']
    result = set()

    for code, klines in klines_map.items():
        if len(klines) < 2:
            continue
        for days in days_list:
            window = klines[-days:] if len(klines) >= days else klines
            for i in range(1, len(window)):
                prev_c = window[i-1]['close']
                cur_c = window[i]['close']
                if prev_c > 0:
                    chg = (cur_c - prev_c) / prev_c * 100
                    if chg >= limit_up or chg >= threshold:
                        result.add(code)
                        break
    return result


def scan_trend_pool(klines_map, days=None, gain=None):
    """备选池二: 强趋势股 (N日涨幅≥X%)"""
    days = days or CONFIG['trend_days']
    gain = gain or CONFIG['trend_gain']
    result = set()

    for code, klines in klines_map.items():
        if len(klines) < days:
            continue
        window = klines[-days:]
        start_c = window[0]['close']
        end_c = window[-1]['close']
        if start_c > 0:
            chg = (end_c - start_c) / start_c * 100
            if chg >= gain:
                result.add(code)
    return result


def scan_amount_pool(quotes):
    """备选池三: 成交额前N"""
    if not quotes:
        return set()
    sorted_codes = sorted(quotes.items(), key=lambda x: x[1].get('amount', 0), reverse=True)
    return {code for code, _ in sorted_codes[:CONFIG['top_amount_count']]}


def secondary_filter(code, klines, quote=None):
    """二次筛选: 删除/保留规则

    Returns:
        (pass: bool, reasons: list[str])
    """
    reasons_pass = []
    reasons_fail = []

    if len(klines) < 20:
        return False, ['数据不足20日']

    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    amounts = [k['amount'] for k in klines]
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    # 1. 成交额 < 1亿 → 删除 (volume是手, *100*close估算)
    today_vol = volumes[-1] if volumes else 0
    today_close = closes[-1]
    est_amount = today_vol * 100 * today_close if today_vol and today_close else 0
    if est_amount < CONFIG['min_amount']:
        reasons_fail.append(f'成交额~{est_amount/1e8:.1f}亿<1亿')

    # 2. 明显下跌趋势 (连续5日收盘创新低) → 删除
    # 但均线附近的票不受此限制
    near_ma10 = ma10 and abs(closes[-1] - ma10) / ma10 * 100 <= CONFIG['ma_near_pct']
    near_ma20 = ma20 and abs(closes[-1] - ma20) / ma20 * 100 <= CONFIG['ma_near_pct']
    if not near_ma10 and not near_ma20 and len(closes) >= 5:
        consec_low = 0
        for i in range(len(closes)-1, max(len(closes)-6, 0), -1):
            if i > 0 and closes[i] < closes[i-1]:
                consec_low += 1
            else:
                break
        if consec_low >= 5:
            reasons_fail.append(f'连续{consec_low}日下跌')

    # 3. 连涨≥N日且每日涨幅>X% → 删除
    consec_up = 0
    for i in range(len(klines)-1, 0, -1):
        if klines[i]['close'] > klines[i-1]['close']:
            chg = (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close'] * 100
            if chg >= CONFIG.get('consecutive_up_threshold', 5.0):
                consec_up += 1
            else:
                break
        else:
            break
    if consec_up >= CONFIG['max_consecutive_up']:
        reasons_fail.append(f'连涨{consec_up}日且每日涨幅>{CONFIG.get("consecutive_up_threshold", 5.0):.0f}%')

    # 4. 长上影线过多 (近5日有≥3根上影线>实体) → 删除
    recent = klines[-5:] if len(klines) >= 5 else klines
    long_upper = 0
    for k in recent:
        body = kline_body(k)
        if body > 0 and kline_upper_shadow(k) / body > 1.5:
            long_upper += 1
    if long_upper >= 3:
        reasons_fail.append(f'近5日{long_upper}根长上影线')

    # 5. 均线附近加分
    near_ma = False
    if ma10 and abs(closes[-1] - ma10) / ma10 * 100 <= CONFIG['ma_near_pct']:
        reasons_pass.append(f'接近MA10({ma10:.2f})')
        near_ma = True
    if ma20 and abs(closes[-1] - ma20) / ma20 * 100 <= CONFIG['ma_near_pct']:
        reasons_pass.append(f'接近MA20({ma20:.2f})')
        near_ma = True

    # 6. 堆量加分 (近3日量能 > 前5日均量1.5倍)
    if len(volumes) >= 8:
        avg_vol_5 = sum(volumes[-8:-3]) / 5
        avg_vol_3 = sum(volumes[-3:]) / 3
        if avg_vol_5 > 0 and avg_vol_3 / avg_vol_5 > 1.5:
            reasons_pass.append(f'堆量(近3日均量/前5日均量={avg_vol_3/avg_vol_5:.1f}倍)')

    passed = len(reasons_fail) == 0
    return passed, reasons_fail + reasons_pass


# ──── 模块3: 止跌信号识别 ────

def detect_stop_fall_signals(klines, ma10=None, ma20=None):
    """识别5种止跌信号

    Args:
        klines: 日K线数据(至少最近2-3日)
        ma10, ma20: 均线值(可选,用于触均线判断)

    Returns:
        list of {signal_type, description, score}
    """
    if len(klines) < 2:
        return []

    signals = []
    today = klines[-1]
    yesterday = klines[-2]
    closes = [k['close'] for k in klines]

    # 触均线判断
    def near_ma(price):
        if ma10 and abs(price - ma10) / ma10 * 100 < 1:
            return 'MA10'
        if ma20 and abs(price - ma20) / ma20 * 100 < 1:
            return 'MA20'
        return None

    # ──── 信号1: 长下影线/锤子线 ────
    body = kline_body(today)
    lower = kline_lower_shadow(today)
    upper = kline_upper_shadow(today)
    if body > 0 and lower >= body * CONFIG['shadow_ratio'] and upper < body * 0.3:
        ma_hit = near_ma(today['low'])
        desc = f'长下影线(下影={lower:.2f}, 实体={body:.2f}, 比={lower/body:.1f})'
        if ma_hit:
            desc += f' 触{ma_hit}'
        signals.append({
            'type': 'long_lower_shadow',
            'score': 3 if ma_hit else 2,
            'desc': desc,
        })

    # ──── 信号2: 曙光初现 ────
    y_body = yesterday['close'] - yesterday['open']  # 阴线实体(负数)
    t_body_range = today['close'] - today['open']
    # 前日跌幅需≥dawn_prev_min_drop(默认3%)
    if len(klines) >= 3:
        prev_close_2 = klines[-3]['close']
    else:
        prev_close_2 = yesterday['open']
    y_drop = (yesterday['close'] - prev_close_2) / prev_close_2 * 100 if prev_close_2 > 0 else 0

    if (yesterday['close'] < yesterday['open']  # 前日阴
            and y_drop <= -CONFIG.get('dawn_prev_min_drop', 3.0)  # 前日跌幅≥3%
            and today['close'] > today['open']   # 今日阳
            and today['open'] < yesterday['close']  # 低开
            and abs(y_body) > 0):
        penetration = t_body_range / abs(y_body)
        if penetration >= CONFIG['dawn_penetration']:
            signals.append({
                'type': 'dawn',
                'score': 3,
                'desc': f'曙光初现(深入{penetration:.0%})',
            })

    # ──── 信号3: 十字星 ────
    if body > 0:
        body_pct = body / today['close'] * 100
        if body_pct < 0.5:  # 实体极小
            ma_hit = near_ma(today['low'])
            if lower > body * 2:  # 有下影线
                desc = f'十字星(实体占比{body_pct:.2f}%)'
                if ma_hit:
                    desc += f' 触{ma_hit}'
                signals.append({
                    'type': 'doji',
                    'score': 3 if ma_hit else 1,
                    'desc': desc,
                })

    # ──── 信号4: 孕线/母子线 ────
    y_body_size = kline_body(yesterday)
    t_body_size = kline_body(today)
    # 前日跌幅需≥big_yin_drop(默认3%)
    if len(klines) >= 3:
        prev_close_2 = klines[-3]['close']
    else:
        prev_close_2 = yesterday['open']
    y_drop = (yesterday['close'] - prev_close_2) / prev_close_2 * 100 if prev_close_2 > 0 else 0

    if (yesterday['close'] < yesterday['open']  # 前日阴
            and y_drop <= -CONFIG.get('big_yin_drop', 3.0)  # 前日大阴线(跌幅≥3%)
            and today['high'] <= yesterday['open']   # 今日被包含
            and today['low'] >= yesterday['close']
            and y_body_size > t_body_size * 2):
        ma_hit = near_ma(today['low'])
        desc = f'孕线(前阴实体={kline_body(yesterday):.2f}, 今={kline_body(today):.2f})'
        if ma_hit:
            desc += f' 触{ma_hit}'
        signals.append({
            'type': 'inside_bar',
            'score': 3 if ma_hit else 2,
            'desc': desc,
        })

    # ──── 信号5: 平底/双针探底 ────
    if len(klines) >= 2:
        low_diff = abs(today['low'] - yesterday['low']) / yesterday['low'] * 100
        if low_diff <= CONFIG['flat_bottom_diff']:
            # 两日都有下影线
            if lower > body * 1.5 and kline_lower_shadow(yesterday) > kline_body(yesterday) * 1.5:
                ma_hit = near_ma(today['low'])
                # 缩量确认
                vol_shrink = today['volume'] < yesterday['volume']
                desc = f'平底(低点差{low_diff:.1f}%)'
                if vol_shrink:
                    desc += ' 缩量'
                if ma_hit:
                    desc += f' 触{ma_hit}'
                signals.append({
                    'type': 'flat_bottom',
                    'score': (3 if ma_hit else 2) + (1 if vol_shrink else 0),
                    'desc': desc,
                })

    return signals


# ──── 模块4: 买入信号判断 ────

def check_buy_signal(code, klines, quote, market_env):
    """判断是否产生买入信号

    Args:
        code: 股票代码
        klines: 近30日日K
        quote: 当日实时行情
        market_env: check_market_env()返回值

    Returns:
        dict or None (None=不满足)
    """
    if len(klines) < 20:
        return None

    closes = [k['close'] for k in klines]
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    today = klines[-1]
    cur_price = quote['price'] if quote else today['close']

    # 条件1: 大盘环境允许
    if market_env['position_pct'] == 0:
        return None

    # 条件2: 股价在10日或20日均线附近(±3%)
    near_ma10 = ma10 and abs(cur_price - ma10) / ma10 * 100 <= CONFIG['ma_near_pct']
    near_ma20 = ma20 and abs(cur_price - ma20) / ma20 * 100 <= CONFIG['ma_near_pct']
    if not near_ma10 and not near_ma20:
        return None

    # 条件3: 当日K线为阴线或小阳线(≤3%)
    if len(klines) >= 2:
        prev_close = klines[-2]['close']
        if prev_close > 0:
            today_chg = (cur_price - prev_close) / prev_close * 100
        else:
            today_chg = 0
    else:
        today_chg = 0

    is_yin = cur_price <= today['open']  # 阴线
    is_small_yang = not is_yin and today_chg <= CONFIG['max_buy_pct']
    if not is_yin and not is_small_yang:
        return None

    # 条件3.5: 避免涨停板买入 (>9.5%跳过)
    if today_chg >= CONFIG.get('limit_up_skip', 9.5):
        return None

    # 条件4: 止跌信号
    stop_signals = detect_stop_fall_signals(klines, ma10, ma20)
    if not stop_signals:
        return None

    # 计算综合得分
    total_score = sum(s['score'] for s in stop_signals)
    # 均线附近加分
    if near_ma10:
        total_score += 1
    if near_ma20:
        total_score += 1
    # 堆量加分
    volumes = [k['volume'] for k in klines]
    if len(volumes) >= 8:
        avg_5 = sum(volumes[-8:-3]) / 5
        avg_3 = sum(volumes[-3:]) / 3
        if avg_5 > 0 and avg_3 / avg_5 > 1.5:
            total_score += 1

    # 板块热度加分
    bonus, bonus_reason = add_sector_bonus(code)
    if bonus > 0:
        total_score += bonus

    ma_label = ''
    if near_ma10:
        ma_label += f'MA10({ma10:.2f})'
    if near_ma20:
        ma_label += ('+' if ma_label else '') + f'MA20({ma20:.2f})'

    return {
        'code': code,
        'price': cur_price,
        'change_pct': today_chg,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'near_ma': ma_label,
        'kline_type': '阴线' if is_yin else f'小阳+{today_chg:.1f}%',
        'signals': stop_signals,
        'total_score': total_score,
        'market_env': market_env['status'],
        'buy_date': klines[-1].get('time', ''),
        'sector_bonus': bonus_reason if bonus > 0 else '',
    }


# ──── 模块5: 卖出规则 ────

def calc_avg_price(minute_data):
    """从分时数据计算均价线 (成交额/成交量)"""
    if not minute_data:
        return None, None
    total_amount = 0
    total_vol = 0
    for p in minute_data:
        vol = p.get('Number', p.get('volume', 0))
        price = p.get('Price', p.get('price', 0))
        if vol > 0 and price > 0:
            total_amount += price * vol * 100  # 手→股
            total_vol += vol * 100
    if total_vol > 0:
        return total_amount / total_vol / 1000, total_vol  # 厘→元
    return None, None


def check_sell_signal(code, buy_price, buy_date, klines30, quote, minute_data=None):
    """次日卖出信号判断

    Args:
        code: 股票代码
        buy_price: 买入价
        buy_date: 买入日期
        klines30: 近30日日K
        quote: 当日实时行情
        minute_data: 当日分时数据(可选)

    Returns:
        dict: {action, reason, price, profit_pct}
    """
    if not quote or not klines30 or len(klines30) < 5:
        return {'action': 'hold', 'reason': '数据不足', 'price': 0, 'profit_pct': 0}

    cur_price = quote.get('price', 0)
    prev_close = quote.get('prev_close', 0)
    open_price = quote.get('open', 0)

    if cur_price <= 0 or buy_price <= 0:
        return {'action': 'hold', 'reason': '价格异常', 'price': cur_price, 'profit_pct': 0}

    profit_pct = (cur_price - buy_price) / buy_price * 100

    closes = [k['close'] for k in klines30]
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    # 条件一: 低开止损 (>2%且破均线)
    if prev_close > 0 and open_price < prev_close:
        open_drop = (open_price - prev_close) / prev_close * 100
        below_ma = (ma10 and open_price < ma10) or (ma20 and open_price < ma20)
        if open_drop < -2 and below_ma:
            return {
                'action': 'sell_stop_loss',
                'reason': f'低开{open_drop:.1f}%且破均线, 竞价止损',
                'price': open_price,
                'profit_pct': (open_price - buy_price) / buy_price * 100,
            }

    # 条件二: 低开未达止损但弱势 (15分钟未站上均价线)
    if prev_close > 0 and open_price < prev_close:
        if minute_data and len(minute_data) >= 15:
            avg_price, _ = calc_avg_price(minute_data[:15])
            if avg_price and cur_price < avg_price:
                return {
                    'action': 'sell_weak',
                    'reason': f'低开后15分钟未站上均价线({avg_price:.2f})',
                    'price': cur_price,
                    'profit_pct': profit_pct,
                }

    # 条件三: 冲高到5日线 → 止盈一半
    if ma5 and cur_price >= ma5:
        return {
            'action': 'sell_half',
            'reason': f'冲高到5日线(MA5={ma5:.2f}), 止盈一半',
            'price': cur_price,
            'profit_pct': profit_pct,
        }

    # 条件三补充: 冲高回落破均价线 → 全部止盈
    if minute_data and len(minute_data) >= 30:
        avg_price, _ = calc_avg_price(minute_data)
        if avg_price and cur_price < avg_price and profit_pct > 0:
            # 今日最高价 > 均价线*1.005 说明冲高过
            day_high = max(p.get('Price', p.get('price', 0)) / 1000 for p in minute_data)
            if day_high > avg_price * 1.005:
                return {
                    'action': 'sell_profit',
                    'reason': f'冲高({day_high:.2f})回落破均价线({avg_price:.2f})',
                    'price': cur_price,
                    'profit_pct': profit_pct,
                }

    # 条件四: 高开≥3%且5分钟未涨停 → 分批止盈
    if prev_close > 0:
        open_pct = (open_price - prev_close) / prev_close * 100
        if open_pct >= 3:
            today_chg = quote.get('change_pct', 0)
            if today_chg < 9.5:  # 未涨停
                return {
                    'action': 'sell_high_open',
                    'reason': f'高开{open_pct:.1f}%且未涨停, 分批止盈',
                    'price': cur_price,
                    'profit_pct': profit_pct,
                }

    # 条件五: 时间止损 (14:00未盈利 → 强制离场)
    # 需要传入当前时间, 这里简化判断
    if profit_pct < 0:
        return {
            'action': 'hold_warning',
            'reason': f'当前亏损{profit_pct:.1f}%, 关注14:00时间止损',
            'price': cur_price,
            'profit_pct': profit_pct,
        }

    return {'action': 'hold', 'reason': '持仓中', 'price': cur_price, 'profit_pct': profit_pct}


def run_sell_check(holdings, tdx_client=None):
    """次日卖出检查

    Args:
        holdings: list of {code, buy_price, buy_date, shares}
        tdx_client: TDX客户端

    Returns:
        list of sell_signal dict
    """
    tdx = tdx_client or get_tdx()
    results = []

    for h in holdings:
        code = h['code']
        tdx_code = TDXClient.code_to_tdx(code)
        try:
            quote = tdx.quote(tdx_code)
            klines = tdx.kline_day(tdx_code, count=30)
            minute = tdx.minute(tdx_code)
        except:
            continue

        sig = check_sell_signal(code, h['buy_price'], h.get('buy_date', ''),
                                klines, quote, minute)
        sig['code'] = code
        sig['name'] = quote.get('name', code)
        sig['buy_price'] = h['buy_price']
        results.append(sig)

    return results


# ──── 模块6: 板块热度因子 ────

# 申万二级→指数代码映射 (从MySQL/akshare动态构建)
_SW2_INDEX_CACHE = None


def _build_sw2_index_map():
    """构建申万二级行业名称→akshare指数代码的映射

    数据源: MySQL mystocks.sw_industry_classification (个股→行业)
            + akshare sw_index_second_info (行业→指数代码)
    """
    global _SW2_INDEX_CACHE
    if _SW2_INDEX_CACHE is not None:
        return _SW2_INDEX_CACHE

    name_to_idx = {}

    # 1. 从akshare获取二级指数列表
    try:
        import akshare as ak
        df = ak.sw_index_second_info()
        for _, row in df.iterrows():
            name = row['行业名称'].replace('Ⅱ', '').strip()
            code = row['行业代码'].replace('.SI', '')
            name_to_idx[name] = code
    except Exception as e:
        print(f'  akshare获取二级指数列表失败: {e}', file=sys.stderr)

    _SW2_INDEX_CACHE = name_to_idx
    return name_to_idx


def get_stock_sw2(code, conn=None):
    """获取个股所属申万二级行业

    Args:
        code: 6位股票代码 (如 '600172')
        conn: 可选pymysql连接

    Returns:
        str: 二级行业名称, None=未找到
    """
    try:
        import pymysql
        own_conn = conn is None
        if own_conn:
            conn = pymysql.connect(
                host='192.168.123.104', user='root',
                password=os.environ.get('MYSQL_PWD', 'c790414J'),
                database='mystocks', connect_timeout=5, read_timeout=5
            )
        cur = conn.cursor()
        # 兼容 600172 和 600172.SH
        patterns = [f'{code}%', code]
        for pat in patterns:
            cur.execute(
                "SELECT 新版二级行业 FROM sw_industry_classification "
                "WHERE 股票代码 LIKE %s AND 新版二级行业 != '' LIMIT 1",
                (pat,)
            )
            r = cur.fetchone()
            if r:
                if own_conn:
                    conn.close()
                return r[0]
        if own_conn:
            conn.close()
    except Exception:
        pass
    return None


def get_sector_heat(tdx_client=None):
    """获取申万二级行业涨幅排名

    Returns:
        dict: {行业名称: 涨跌幅%}  涨幅前5
    """
    try:
        import akshare as ak
        df = ak.index_realtime_sw(symbol='二级行业')
        # 计算涨跌幅: (最新价-昨收盘)/昨收盘*100
        df['涨跌幅'] = (df['最新价'] - df['昨收盘']) / df['昨收盘'] * 100
        df = df.sort_values('涨跌幅', ascending=False)
        top5 = {}
        for _, row in df.head(5).iterrows():
            top5[row['指数名称']] = round(row['涨跌幅'], 2)
        return top5
    except Exception as e:
        print(f'  获取板块热度失败: {e}', file=sys.stderr)
        return {}


def add_sector_bonus(code, sector_heat=None):
    """板块热度加分

    逻辑: 个股所属申万二级行业在涨幅前5名 → +1分

    Args:
        code: 6位股票代码
        sector_heat: get_sector_heat()的结果, None=自动获取

    Returns:
        int: 加分值 (0 or 1)
        str: 加分原因
    """
    if sector_heat is None:
        sector_heat = get_sector_heat()
    if not sector_heat:
        return 0, ''

    # 查个股所属行业
    sw2_name = get_stock_sw2(code)
    if not sw2_name:
        return 0, ''

    # 检查是否在热度前5
    clean_name = sw2_name.replace('Ⅱ', '').strip()
    for hot_name, chg in sector_heat.items():
        hot_clean = hot_name.replace('Ⅱ', '').strip()
        if clean_name == hot_clean or sw2_name == hot_name:
            return 1, f'板块热度: {hot_name}({chg:+.1f}%)'

    return 0, ''


# ──── 主流程 ────

def get_stock_universe(tdx_client):
    """获取股票池 (全A股活跃股)

    优先MySQL(tdx_data.day_kline), 回退东财API
    """
    # 方案1: MySQL获取近期有数据的股票
    try:
        import pymysql
        conn = pymysql.connect(
            host='192.168.123.104', user='root',
            password=os.environ.get('MYSQL_PWD', 'c790414J'),
            database='tdx_data', connect_timeout=10, read_timeout=30
        )
        cur = conn.cursor()
        # 近10个交易日有数据
        cur.execute(
            "SELECT DISTINCT stock_code FROM day_kline "
            "WHERE trade_date >= DATE_SUB(NOW(), INTERVAL 20 DAY) "
            "ORDER BY stock_code"
        )
        codes = [r[0] for r in cur.fetchall()]
        conn.close()
        # 排除北交所(8/4开头)和科创板(688)
        codes = [c for c in codes if not c.startswith(('8', '4'))
                 and not c.startswith('688')]
        # 用TDX API批量获取行情
        tdx_codes = [TDXClient.code_to_tdx(c) for c in codes]
        # batch_quote每次最多50只
        stocks = {}
        for i in range(0, len(tdx_codes), 50):
            batch = tdx_codes[i:i+50]
            try:
                quotes = tdx_client.batch_quote(batch)
                for tc, q in quotes.items():
                    # tc=sh600172 → 600172
                    pure_code = tc[2:] if len(tc) > 6 else tc
                    stocks[pure_code] = q
            except:
                pass
        return stocks
    except Exception as e:
        print(f'  MySQL/TDX获取股票列表失败: {e}', file=sys.stderr)

    # 方案2: 回退东财API (WSL可能被封)
    import urllib.request
    import json as _json

    url = 'https://80.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f2,f3,f6,f15,f16,f17,f18'
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://quote.eastmoney.com'
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        diff = data.get('data', {}).get('diff', [])
        stocks = {}
        for item in diff:
            code = item.get('f12', '')
            name = item.get('f14', '')
            if 'ST' in name or '退' in name:
                continue
            stocks[code] = {
                'code': code,
                'name': name,
                'price': item.get('f2', 0),
                'change_pct': item.get('f3', 0),
                'amount': item.get('f6', 0),
                'high': item.get('f15', 0),
                'low': item.get('f16', 0),
                'open': item.get('f17', 0),
                'prev_close': item.get('f18', 0),
            }
        return stocks
    except Exception as e:
        print(f'  东财API也失败: {e}', file=sys.stderr)
        return {}


def run_scan(tdx_client=None, target_date=None):
    """执行完整选股流程

    Args:
        target_date: 指定日期(YYYYMMDD), None=当天

    Returns:
        list of buy_signal dict
    """
    tdx = tdx_client or get_tdx()

    print('━' * 60)
    print('  汇通理论 — 尾盘买入隔日交易系统')
    print('━' * 60)

    # Step 0: 大盘环境
    print('\n[Step 0] 大盘环境判断...')
    market = check_market_env(tdx)
    print(f'  {market["details"]}')
    print(f'  建议仓位: {market["position_pct"]}%')
    if market['position_pct'] == 0:
        print('\n  ⚠️ 大盘环境不支持操作(仍展示选股结果供参考)')
        # 不return, 继续选股

    # Step 1: 获取股票池
    print('\n[Step 1] 获取股票池...')
    if target_date:
        print(f'  回测模式: {target_date}')

    universe = get_stock_universe(tdx)
    print(f'  全市场: {len(universe)}只')

    # 成交额过滤: TDX实时行情无amount字段, 用MySQL最近一天日K的amount
    # 或者跳过成交额过滤, 在二次筛选时用K线的amount判断
    amount_filtered = {c: q for c, q in universe.items()
                       if q.get('amount', 0) >= CONFIG['min_amount']
                       or q.get('volume', 0) > 0}  # 有成交量就行
    print(f'  有行情数据: {len(amount_filtered)}只')

    # Step 2: 四池选股
    print('\n[Step 2] 四池选股...')

    # 备选池三: 成交额前50
    pool_amount = scan_amount_pool(universe)

    # 对成交额>1亿的 + 成交额前50 取并集，获取K线
    kline_candidates = set(amount_filtered.keys()) | pool_amount
    # 取成交额前500获取K线(减少API调用)
    by_amount = sorted(kline_candidates,
                       key=lambda c: universe.get(c, {}).get('amount', 0),
                       reverse=True)
    top_codes = by_amount[:200]

    # 批量获取日K
    print(f'  批量获取日K({len(top_codes)}只)...')
    klines_map = {}
    for i in range(0, len(top_codes), 50):
        batch = top_codes[i:i+50]
        for code in batch:
            try:
                tdx_code = TDXClient.code_to_tdx(code)
                k = tdx.kline_day(tdx_code, count=30)
                if k and len(k) >= 10:
                    klines_map[code] = k
            except:
                pass
        if i % 100 == 0 and i > 0:
            print(f'    已获取 {len(klines_map)}只...')
    print(f'  日K数据: {len(klines_map)}只')

    pool_active = scan_active_pool(klines_map)
    print(f'  活跃股池: {len(pool_active)}只')

    pool_trend = scan_trend_pool(klines_map)
    print(f'  强趋势池: {len(pool_trend)}只')

    pool_amount = scan_amount_pool(universe)
    pool_amount_in_klines = pool_amount & set(klines_map.keys())
    print(f'  成交额池: {len(pool_amount)}只 (有K线{len(pool_amount_in_klines)})')

    # 合并
    all_candidates = (pool_active | pool_trend | pool_amount_in_klines) & set(klines_map.keys())
    print(f'  合并去重: {len(all_candidates)}只')

    # Step 3: 二次筛选
    print('\n[Step 3] 二次筛选...')
    passed = {}
    for code in all_candidates:
        klines = klines_map[code]
        quote = universe.get(code)
        ok, reasons = secondary_filter(code, klines, quote)
        if ok:
            passed[code] = {'klines': klines, 'quote': quote, 'reasons': reasons}
    print(f'  通过筛选: {len(passed)}只')
    for code, info in list(passed.items())[:5]:
        print(f'    {code}: {info["reasons"]}')

    # Step 4: 止跌信号+买入信号
    print('\n[Step 4] 止跌信号识别 + 买入判断...')
    stop_fall_only = []  # 有止跌信号但未满足买入条件
    buy_signals = []
    for code, info in passed.items():
        klines = info['klines']
        quote = info['quote']
        closes = [k['close'] for k in klines]
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)

        # 止跌信号
        signals = detect_stop_fall_signals(klines, ma10, ma20)
        if not signals:
            continue

        # 买入信号
        signal = check_buy_signal(code, klines, quote, market)
        if signal:
            buy_signals.append(signal)
        else:
            stop_fall_only.append({
                'code': code,
                'signals': signals,
                'price': quote.get('price', 0) if quote else 0,
            })

    if stop_fall_only:
        print(f'  有止跌信号但未满足买入条件: {len(stop_fall_only)}只')
        for s in stop_fall_only[:5]:
            sig_desc = ', '.join(sig['type'] for sig in s['signals'])
            print(f'    {s["code"]}: {sig_desc} (价格{s["price"]:.2f})')

    # 按得分排序
    buy_signals.sort(key=lambda x: x['total_score'], reverse=True)
    # 动态仓位: 大盘5日线下减少选股数
    max_picks = CONFIG['max_picks']
    if market.get('index_close', 0) < market.get('ma5', float('inf')):
        max_picks = CONFIG.get('max_picks_below_ma5', 2)
        print(f'\n  📊 大盘5日线下，最多选{max_picks}只')
    buy_signals = buy_signals[:max_picks]

    # Step 5: 输出结果
    print('\n' + '━' * 60)
    if buy_signals:
        print(f'  ✅ 选出 {len(buy_signals)} 只标的:')
        print('━' * 60)
        for i, s in enumerate(buy_signals, 1):
            print(f'\n  [{i}] {s["code"]}  价格: {s["price"]:.2f}  {s["kline_type"]}  涨跌: {s["change_pct"]:+.1f}%')
            print(f'      均线: {s["near_ma"]}')
            print(f'      得分: {s["total_score"]}  大盘: {s["market_env"]}')
            for sig in s['signals']:
                print(f'      📊 {sig["desc"]} (+{sig["score"]}分)')
            if s.get('sector_bonus'):
                print(f'      🔥 {s["sector_bonus"]} (+1分)')
    else:
        print('  ❌ 今日无符合条件的标的')

    print('\n' + '━' * 60)
    return buy_signals


def show_signal(code, tdx_client=None):
    """查看指定股票的止跌信号"""
    tdx = tdx_client or get_tdx()
    tdx_code = TDXClient.code_to_tdx(code)
    klines = tdx.kline_day(tdx_code, count=30)

    if not klines or len(klines) < 5:
        print(f'{code}: 数据不足')
        return

    closes = [k['close'] for k in klines]
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    print(f'\n{code} 近5日K线:')
    for k in klines[-5:]:
        d = date_str(k['time'])
        chg = ''
        print(f'  {d} O={k["open"]:.2f} H={k["high"]:.2f} L={k["low"]:.2f} C={k["close"]:.2f} V={k["volume"]}')

    print(f'\nMA10={ma10:.2f}  MA20={ma20:.2f}')

    signals = detect_stop_fall_signals(klines, ma10, ma20)
    if signals:
        print(f'\n止跌信号 ({len(signals)}个):')
        for s in signals:
            print(f'  [{s["type"]}] {s["desc"]} (得分+{s["score"]})')
    else:
        print('\n无止跌信号')


# ──── 模块7: 回测引擎 ────

def backtest_single(code, tdx_client, start_date=None, end_date=None):
    """单只股票历史回测

    流程: 遍历每个交易日, 用截至当日的日K判断选股+买入信号,
          次日按卖出规则模拟卖出, 记录每笔交易结果.

    Args:
        code: 6位股票代码
        tdx_client: TDXClient
        start_date: YYYYMMDD, 默认60日前
        end_date: YYYYMMDD, 默认最新

    Returns:
        dict: {code, trades, stats}
    """
    tdx = tdx_client
    tdx_code = TDXClient.code_to_tdx(code)
    # 取120根日K (足够覆盖MA20+回测窗口)
    all_klines = tdx.kline_day(tdx_code, count=120)
    if not all_klines or len(all_klines) < 30:
        return {'code': code, 'error': 'K线数据不足'}

    trades = []
    i = 30  # 从第30根开始(有足够MA数据)

    while i < len(all_klines) - 1:
        klines_up_to = all_klines[:i+1]  # 截至当日
        today = klines_up_to[-1]
        tomorrow = all_klines[i+1]

        # 大盘环境 (用上证日K)
        try:
            idx_klines = tdx.kline_day('sh000001', count=30)
            market = check_market_env(tdx)
        except:
            market = {'position_pct': 50}

        # 二次筛选
        ok, reasons = secondary_filter(code, klines_up_to[-25:], None)
        if not ok:
            i += 1
            continue

        # 止跌信号
        closes = [k['close'] for k in klines_up_to]
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        signals = detect_stop_fall_signals(klines_up_to, ma10, ma20)
        if not signals:
            i += 1
            continue

        # 买入: 以当日收盘价模拟尾盘买入
        buy_price = today['close']
        buy_date = date_str(today['time'])

        # 卖出模拟 (次日)
        sell_price = None
        sell_reason = ''
        next_open = tomorrow['open']
        next_close = tomorrow['close']
        next_high = tomorrow['high']
        next_low = tomorrow['low']
        prev_close = today['close']

        # 条件一: 低开止损 (>2%且破均线)
        if prev_close > 0:
            open_drop = (next_open - prev_close) / prev_close * 100
            below_ma = (ma10 and next_open < ma10) or (ma20 and next_open < ma20)
            if open_drop < -2 and below_ma:
                sell_price = next_open
                sell_reason = f'竞价止损(低开{open_drop:.1f}%)'

        # 条件四: 高开≥3% → 开盘卖出
        if not sell_price and prev_close > 0:
            open_pct = (next_open - prev_close) / prev_close * 100
            if open_pct >= 3:
                sell_price = next_open
                sell_reason = f'高开{open_pct:.1f}%止盈'

        # 条件三: 冲高到5日线 → 取5日线价和收盘价的较高者
        if not sell_price:
            closes5 = [k['close'] for k in klines_up_to]
            ma5 = calc_ma(closes5, 5)
            if ma5 and next_high >= ma5:
                sell_price = max(ma5, next_open)  # 模拟取MA5价或开盘价
                sell_reason = f'冲高到MA5({ma5:.2f})'
            else:
                # 收盘卖出 (默认隔日交易)
                sell_price = next_close
                sell_reason = '收盘卖出'

        if sell_price:
            profit_pct = (sell_price - buy_price) / buy_price * 100
            trades.append({
                'buy_date': buy_date,
                'buy_price': round(buy_price, 2),
                'sell_date': date_str(tomorrow['time']),
                'sell_price': round(sell_price, 2),
                'profit_pct': round(profit_pct, 2),
                'sell_reason': sell_reason,
                'signals': [s['type'] for s in signals],
            })

        # 跳过次日 (已卖出)
        i += 2

    # 统计
    if not trades:
        return {'code': code, 'trades': 0, 'stats': {}}

    profits = [t['profit_pct'] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    total_profit = sum(profits)
    avg_profit = sum(profits) / len(profits) if profits else 0
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    stats = {
        'total_trades': len(trades),
        'win_trades': len(wins),
        'loss_trades': len(losses),
        'win_rate': round(win_rate, 1),
        'avg_profit_pct': round(avg_profit, 2),
        'total_profit_pct': round(total_profit, 2),
        'max_win': round(max(profits), 2) if profits else 0,
        'max_loss': round(min(profits), 2) if profits else 0,
    }

    return {'code': code, 'trades': trades, 'stats': stats}


def run_backtest(codes=None, top_n=20, tdx_client=None):
    """批量回测

    Args:
        codes: 指定代码列表, None=从成交额前top_n选
        top_n: 未指定codes时, 取成交额前N只
        tdx_client: TDXClient
    """
    tdx = tdx_client or get_tdx()
    load_config()

    print('━' * 60)
    print('  汇通理论 — 回测引擎')
    print('━' * 60)

    if not codes:
        # 从股票池取成交额前N只
        print('\n[1] 获取股票池...')
        universe = get_stock_universe(tdx)
        # 取有成交量的前N只
        by_vol = sorted(
            [(c, q) for c, q in universe.items() if q.get('volume', 0) > 0],
            key=lambda x: x[1].get('volume', 0),
            reverse=True
        )
        codes = [c for c, _ in by_vol[:top_n]]
        print(f'  取成交额前{top_n}只: {codes[:5]}...')

    print(f'\n[2] 逐只回测({len(codes)}只)...')
    results = []
    for code in codes:
        r = backtest_single(code, tdx)
        if 'error' not in r and r.get('trades'):
            results.append(r)
            s = r['stats']
            print(f'  {code}: {s["total_trades"]}笔 胜率{s["win_rate"]:.0f}% '
                  f'均利{s["avg_profit_pct"]:+.2f}% 总{s["total_profit_pct"]:+.1f}%')

    if not results:
        print('\n  无回测结果')
        return []

    # 汇总统计
    all_trades_count = sum(r['stats']['total_trades'] for r in results)
    all_profits = []
    for r in results:
        all_profits.extend([t['profit_pct'] for t in r['trades']])

    total_win = len([p for p in all_profits if p > 0])
    total_loss = len([p for p in all_profits if p <= 0])

    print(f'\n{"━" * 60}')
    print(f'  回测汇总 ({len(results)}只, {all_trades_count}笔交易)')
    print(f'{"━" * 60}')
    print(f'  总胜率: {total_win}/{all_trades_count} = {total_win/all_trades_count*100:.1f}%')
    print(f'  平均每笔: {sum(all_profits)/len(all_profits):+.2f}%')
    print(f'  累计收益: {sum(all_profits):+.2f}%')
    print(f'  最大单笔盈利: {max(all_profits):+.2f}%')
    print(f'  最大单笔亏损: {min(all_profits):+.2f}%')

    # 止损类型分布
    reasons = {}
    for r in results:
        for t in r['trades']:
            reason = t['sell_reason'].split('(')[0]  # 去掉括号细节
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f'\n  卖出类型分布:')
    for reason, cnt in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        pct = cnt / all_trades_count * 100
        print(f'    {reason}: {cnt}笔 ({pct:.0f}%)')

    # 胜率前5
    by_wr = sorted(results, key=lambda r: r['stats']['win_rate'], reverse=True)
    print(f'\n  胜率前5:')
    for r in by_wr[:5]:
        s = r['stats']
        print(f'    {r["code"]}: 胜率{s["win_rate"]:.0f}% 均利{s["avg_profit_pct"]:+.2f}% ({s["total_trades"]}笔)')

    print(f'{"━" * 60}')
    return results


# ──── CLI ────

def main():
    parser = argparse.ArgumentParser(description='汇通理论尾盘买入隔日交易系统')
    parser.add_argument('--scan', action='store_true', help='执行完整选股流程')
    parser.add_argument('--date', help='指定日期(YYYYMMDD), 回测模式')
    parser.add_argument('--signal', help='查看指定股票的止跌信号')
    parser.add_argument('--market', action='store_true', help='查看大盘环境')
    parser.add_argument('--sell', nargs='+', metavar='CODE:PRICE',
                        help='卖出检查, 格式: 600172:13.50 [002015:22.00]')
    parser.add_argument('--backtest', action='store_true', help='回测(成交额前20只)')
    parser.add_argument('--backtest-codes', nargs='+', metavar='CODE',
                        help='指定代码回测, 如: --backtest-codes 600172 002015')
    parser.add_argument('--pool', choices=['active', 'trend', 'amount'], help='只输出指定池')
    args = parser.parse_args()

    load_config()

    if args.market:
        env = check_market_env()
        print(json.dumps(env, ensure_ascii=False, indent=2, default=str))
    elif args.signal:
        show_signal(args.signal)
    elif args.sell:
        # 解析 CODE:PRICE
        holdings = []
        for item in args.sell:
            parts = item.split(':')
            if len(parts) == 2:
                holdings.append({
                    'code': parts[0],
                    'buy_price': float(parts[1]),
                    'buy_date': '',
                })
        if holdings:
            results = run_sell_check(holdings)
            print('\n卖出信号检查:')
            for r in results:
                action_map = {
                    'sell_stop_loss': '🔴 竞价止损',
                    'sell_weak': '🟡 弱势卖出',
                    'sell_half': '🟢 止盈一半',
                    'sell_profit': '🟢 全部止盈',
                    'sell_high_open': '🟢 高开止盈',
                    'hold_warning': '⚠️ 持仓预警',
                    'hold': '⚪ 继续持有',
                }
                label = action_map.get(r['action'], r['action'])
                print(f'  {r["code"]} {r.get("name","")} | {label}')
                print(f'    {r["reason"]} | 现价{r["price"]:.2f} 盈亏{r["profit_pct"]:+.1f}%')
    elif args.backtest:
        run_backtest(top_n=20)
    elif args.backtest_codes:
        run_backtest(codes=args.backtest_codes)
    elif args.scan:
        results = run_scan(target_date=args.date)
        if results:
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
