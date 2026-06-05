#!/usr/bin/env python3
"""TDX API 共享客户端 — 所有股票技能共用

NAS Docker服务: http://192.168.123.104:8089
数据单位: 厘 (1000 = 1元)
代码格式: sh600000 / sz000001 / bj430001

用法:
  from tdx_client import TDXClient
  tdx = TDXClient()

  # 实时行情(单只)
  q = tdx.quote('sh600172')

  # 批量行情
  quotes = tdx.batch_quote(['sh600172', 'sz002015'])

  # 日K线
  klines = tdx.kline('sh600172', 'day', count=30)

  # 15分K线
  k15 = tdx.kline('sh600172', 'minute15')

  # 分时
  mins = tdx.minute('sz002015', '20260605')

  # 历史逐笔成交
  trades = tdx.trade_history('sh601138', '20260605')

  # 指数
  idx = tdx.index('sh000001')

  # 搜索
  results = tdx.search('黄河')

  # 交易日
  wd = tdx.workday('20260605')

  # 市场统计
  stats = tdx.market_stats()

  # 股票代码→TDX格式
  code = TDXClient.code_to_tdx('600172')  # → 'sh600172'
"""

import json
import os
import urllib.request
import urllib.parse
from collections import defaultdict

TDX_BASE = os.environ.get('TDX_API_BASE', 'http://192.168.123.104:8089')


class TDXClient:
    """TDX API 客户端，带缓存和统一接口"""

    def __init__(self, base_url=None, timeout=15):
        self.base = (base_url or TDX_BASE).rstrip('/')
        self.timeout = timeout
        self._cache = {}

    # ──── 底层请求 ────

    def _get(self, path, params=None):
        """GET请求，返回JSON dict"""
        if params:
            qs = urllib.parse.urlencode(params)
            url = f"{self.base}{path}?{qs}"
        else:
            url = f"{self.base}{path}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TDXClient/1.0'})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"code": -1, "message": str(e), "data": None}

    def _post(self, path, body):
        """POST请求(JSON body)，返回JSON dict"""
        url = f"{self.base}{path}"
        try:
            data = json.dumps(body).encode('utf-8')
            req = urllib.request.Request(url, data=data,
                                         headers={'Content-Type': 'application/json',
                                                  'User-Agent': 'TDXClient/1.0'})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"code": -1, "message": str(e), "data": None}

    # ──── 工具方法 ────

    @staticmethod
    def code_to_tdx(code):
        """6位代码→TDX格式 (sh600172/sz002015/bj430001)"""
        c = str(code).strip()
        if c[0] in ('6', '9'):
            return f'sh{c}'
        elif c[0] in ('0', '3'):
            return f'sz{c}'
        elif c[0] in ('4', '8'):
            return f'bj{c}'
        return f'sz{c}'

    @staticmethod
    def tdx_to_code(tdx_code):
        """TDX格式→6位代码"""
        return tdx_code[2:] if len(tdx_code) == 8 else tdx_code

    @staticmethod
    def price(li):
        """厘→元 (1000 → 1.00)"""
        return li / 1000 if isinstance(li, (int, float)) else 0.0

    @staticmethod
    def price_int(yuan):
        """元→厘 (1.00 → 1000)"""
        return int(yuan * 1000)

    # ──── 行情接口 ────

    def quote(self, code):
        """实时五档行情(单只)

        Args:
            code: TDX格式代码 (sh600172) 或 6位纯数字

        Returns:
            dict: {code, name, price, open, high, low, prev_close,
                   volume, amount, change_pct, bid1..bid5, ask1..ask5}
        """
        if len(str(code)) == 6:
            code = self.code_to_tdx(code)
        d = self._get('/api/quote', {'code': code})
        if d.get('code') == 0 and d.get('data'):
            raw_list = d['data']
            if isinstance(raw_list, list) and raw_list:
                raw = raw_list[0]
            elif isinstance(raw_list, dict):
                raw = raw_list
            else:
                return None
            k = raw.get('K', {})
            last = self.price(k.get('Last', 0))
            open_p = self.price(k.get('Open', 0))
            high = self.price(k.get('High', 0))
            low = self.price(k.get('Low', 0))
            close = self.price(k.get('Close', 0))
            # Last是昨收(收盘后的最终价), Close是最新价
            # 盘中: Last=昨收, Close=最新价; 盘后: 两者相同
            prev_close = last if last != close else open_p  # fallback
            # 实际: TDX K.Last = 前收盘, K.Close = 最新/收盘
            # 但盘后数据两者一样，需要从index推算
            # Rate字段可能有用
            rate = raw.get('Rate', 0)
            if rate == 0 and last > 0:
                change_pct = (close - last) / last * 100
            else:
                change_pct = rate / 100 if rate else 0

            buy_levels = raw.get('BuyLevel', [])
            sell_levels = raw.get('SellLevel', [])
            result = {
                'code': raw.get('Code', self.tdx_to_code(code)),
                'exchange': raw.get('Exchange', 0),
                'price': close,
                'open': open_p,
                'high': high,
                'low': low,
                'prev_close': last,
                'close': close,
                'volume': raw.get('TotalHand', 0),
                'amount': raw.get('Amount', 0),
                'change_pct': change_pct,
                'bid1': self.price(buy_levels[0]['Price']) if len(buy_levels) > 0 else 0,
                'bid1_vol': buy_levels[0].get('Number', 0) if len(buy_levels) > 0 else 0,
                'bid2': self.price(buy_levels[1]['Price']) if len(buy_levels) > 1 else 0,
                'bid3': self.price(buy_levels[2]['Price']) if len(buy_levels) > 2 else 0,
                'bid4': self.price(buy_levels[3]['Price']) if len(buy_levels) > 3 else 0,
                'bid5': self.price(buy_levels[4]['Price']) if len(buy_levels) > 4 else 0,
                'ask1': self.price(sell_levels[0]['Price']) if len(sell_levels) > 0 else 0,
                'ask1_vol': sell_levels[0].get('Number', 0) if len(sell_levels) > 0 else 0,
                'ask2': self.price(sell_levels[1]['Price']) if len(sell_levels) > 1 else 0,
                'ask3': self.price(sell_levels[2]['Price']) if len(sell_levels) > 2 else 0,
                'ask4': self.price(sell_levels[3]['Price']) if len(sell_levels) > 3 else 0,
                'ask5': self.price(sell_levels[4]['Price']) if len(sell_levels) > 4 else 0,
                '_raw': raw,
            }
            return result
        return None

    def batch_quote(self, codes):
        """批量实时行情

        Args:
            codes: list of TDX格式代码 或 6位纯数字

        Returns:
            dict: {纯6位code: {price, name, change_pct, prev_close, ...}, ...}
        """
        tdx_codes = [c if len(str(c)) == 8 else self.code_to_tdx(c) for c in codes]
        d = self._post('/api/batch-quote', {'codes': tdx_codes})
        if d.get('code') == 0 and d.get('data'):
            raw_list = d['data']
            if isinstance(raw_list, dict):
                raw_list = raw_list.get('List', [])
            if not isinstance(raw_list, list):
                return {}
            result = {}
            for raw in raw_list:
                if not isinstance(raw, dict):
                    continue
                k = raw.get('K', {})
                last = self.price(k.get('Last', 0))
                close = self.price(k.get('Close', 0))
                rate = raw.get('Rate', 0)
                if rate == 0 and last > 0:
                    change_pct = (close - last) / last * 100
                else:
                    change_pct = rate / 100 if rate else 0
                buy_levels = raw.get('BuyLevel', [])
                sell_levels = raw.get('SellLevel', [])
                c = raw.get('Code', '')
                result[c] = {
                    'code': c,
                    'price': close,
                    'open': self.price(k.get('Open', 0)),
                    'high': self.price(k.get('High', 0)),
                    'low': self.price(k.get('Low', 0)),
                    'prev_close': last,
                    'volume': raw.get('TotalHand', 0),
                    'change_pct': change_pct,
                    'bid1': self.price(buy_levels[0]['Price']) if len(buy_levels) > 0 else 0,
                    'ask1': self.price(sell_levels[0]['Price']) if len(sell_levels) > 0 else 0,
                }
            return result
        return {}

    # ──── K线接口 ────

    def kline(self, code, ktype='day', count=None, start_date=None):
        """K线数据

        Args:
            code: TDX格式或6位纯数字
            ktype: day|week|month|minute1|minute5|minute15|minute30|minute60
            count: 返回条数(None=全部)
            start_date: 起始日期(仅分页接口)

        Returns:
            list of dict: [{time, open, high, low, close, volume, amount}, ...]
        """
        if len(str(code)) == 6:
            code = self.code_to_tdx(code)
        d = self._get('/api/kline', {'code': code, 'type': ktype})
        if d.get('code') == 0 and d.get('data'):
            rows = d['data'].get('List', [])
            result = []
            for r in rows:
                result.append({
                    'time': r.get('Time', ''),
                    'open': self.price(r.get('Open', 0)),
                    'high': self.price(r.get('High', 0)),
                    'low': self.price(r.get('Low', 0)),
                    'close': self.price(r.get('Close', 0)),
                    'volume': r.get('Volume', 0),
                    'amount': r.get('Amount', 0),
                })
            if count:
                result = result[-count:]
            return result
        return []

    def kline_day(self, code, count=30):
        """日K线(快捷方法)"""
        return self.kline(code, 'day', count)

    def kline_15m(self, code):
        """15分钟K线"""
        return self.kline(code, 'minute15')

    def kline_1m(self, code):
        """1分钟K线"""
        return self.kline(code, 'minute1')

    def kline_5m(self, code):
        """5分钟K线"""
        return self.kline(code, 'minute5')

    def kline_week(self, code, count=30):
        """周K线"""
        return self.kline(code, 'week', count)

    def kline_month(self, code, count=24):
        """月K线"""
        return self.kline(code, 'month', count)

    # ──── 分时/成交 ────

    def minute(self, code, date=None):
        """分时数据(每分钟价格+成交量)

        Args:
            code: TDX格式或6位
            date: YYYYMMDD格式(None=当天)

        Returns:
            list of dict: [{time, price, volume}, ...]
        """
        if len(str(code)) == 6:
            code = self.code_to_tdx(code)
        params = {'code': code}
        if date:
            params['date'] = date
        d = self._get('/api/minute', params)
        if d.get('code') == 0 and d.get('data'):
            rows = d['data'].get('List', [])
            result = []
            for r in rows:
                result.append({
                    'time': r.get('Time', ''),
                    'price': self.price(r.get('Price', 0)),
                    'volume': r.get('Number', r.get('Volume', 0)),
                })
            return result
        return []

    def trade_history(self, code, date=None, offset=0, limit=2000):
        """历史逐笔成交

        Args:
            code: TDX格式或6位
            date: YYYYMMDD格式
            offset/limit: 分页

        Returns:
            list of dict: [{time, price, volume, is_buy}, ...]
        """
        if len(str(code)) == 6:
            code = self.code_to_tdx(code)
        params = {'code': code, 'offset': offset, 'limit': limit}
        if date:
            params['date'] = date
        d = self._get('/api/trade-history', params)
        if d.get('code') == 0 and d.get('data'):
            rows = d['data'].get('List', [])
            result = []
            for r in rows:
                result.append({
                    'time': r.get('Time', ''),
                    'price': self.price(r.get('Price', 0)),
                    'volume': r.get('Volume', 0),
                    'is_buy': r.get('Status', 0) == 1,
                })
            return result
        return []

    # ──── 指数 ────

    def index(self, code='sh000001', count=None):
        """指数K线(含涨跌家数)

        Args:
            code: sh000001(上证)/sz399001(深证)/sz399006(创业板)
            count: 返回条数

        Returns:
            list of dict: [{time, open, high, low, close, up_count, down_count}, ...]
        """
        d = self._get('/api/index', {'code': code})
        if d.get('code') == 0 and d.get('data'):
            rows = d['data'].get('List', [])
            result = []
            for r in rows:
                result.append({
                    'time': r.get('Time', ''),
                    'open': self.price(r.get('Open', 0)),
                    'high': self.price(r.get('High', 0)),
                    'low': self.price(r.get('Low', 0)),
                    'close': self.price(r.get('Close', 0)),
                    'volume': r.get('Volume', 0),
                    'up_count': r.get('UpCount', 0),
                    'down_count': r.get('DownCount', 0),
                })
            if count:
                result = result[-count:]
            return result
        return []

    # ──── 辅助接口 ────

    def search(self, keyword):
        """模糊搜索股票代码/名称"""
        d = self._get('/api/search', {'keyword': keyword})
        if d.get('code') == 0 and d.get('data'):
            raw = d['data']
            if isinstance(raw, list):
                return raw
            return raw.get('List', [])
        return []

    def workday(self, date):
        """查询是否交易日

        Args:
            date: YYYYMMDD

        Returns:
            dict: {is_workday, next, previous} 或 None
        """
        d = self._get('/api/workday', {'date': date})
        if d.get('code') == 0 and d.get('data'):
            return d['data']
        return None

    def market_stats(self):
        """市场涨跌统计 {sh: {total, up, down, flat}, sz: ..., bj: ...}"""
        d = self._get('/api/market-stats')
        if d.get('code') == 0 and d.get('data'):
            return d['data']
        return {}

    def stock_info(self, code):
        """聚合接口: 行情+K线+分时 一次获取"""
        if len(str(code)) == 6:
            code = self.code_to_tdx(code)
        d = self._get('/api/stock-info', {'code': code})
        if d.get('code') == 0:
            return d.get('data')
        return None

    def health(self):
        """健康检查"""
        d = self._get('/api/health')
        return d.get('code') == 0


# 便捷单例
_default = None

def get_client():
    global _default
    if _default is None:
        _default = TDXClient()
    return _default
