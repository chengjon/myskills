#!/usr/bin/env python3
"""A股数据源统一接口 (Unified A-Share Data Sources)

提供三大数据源的统一封装，自动选择可用源:
  1. TDX API REST  — 主数据源 (行情/K线/分时/逐笔/指数)
  2. easyquotation  — 备用行情 (腾讯/新浪源, 含五档盘口)
  3. akshare        — 行业/板块/指数 (申万行业分类)
  4. efinance       — 备用K线/行情 (东财API, 需非WSL环境)
  5. MySQL          — 本地数据 (股票列表/申万映射/日K)

环境说明:
  - WSL下东财API(push2.eastmoney.com)被封, efinance/东财直连不可用
  - easyquotation腾讯(qt.gtimg.cn)/新浪(sinajs.cn)源在WSL可用
  - TDX API(局域网192.168.123.104:8089)始终可用
  - akshare走申万官网, WSL可用

用法:
  from data_sources import DataHub
  hub = DataHub()
  quote = hub.quote('600172')              # 实时行情
  klines = hub.kline_day('600172', 30)     # 日K
  sw2 = hub.get_stock_sw2('600172')        # 申万二级
  heat = hub.sector_heat_top5()            # 板块涨幅Top5
"""

import os
import sys
import time
import json
import logging

logger = logging.getLogger('data_sources')

# ── 全局配置 ──

MYSQL_HOST = os.environ.get('MYSQL_HOST', '192.168.123.104')
MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
MYSQL_PWD = os.environ.get('MYSQL_PWD', 'c790414J')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '3306'))
TDX_API_URL = os.environ.get('TDX_API_URL', 'http://192.168.123.104:8089')


# ── 工具函数 ──

def _import_tdx_client():
    """懒加载 tdx_client.py (同目录或skills路径)"""
    try:
        from tdx_client import TDXClient
        return TDXClient
    except ImportError:
        # 尝试从skills目录加载
        skills_dir = os.path.expanduser('~/.hermes/skills/trade-audit/scripts')
        if skills_dir not in sys.path:
            sys.path.insert(0, skills_dir)
        from tdx_client import TDXClient
        return TDXClient


def code_to_tdx(code):
    """6位代码转TDX格式 (600172 → sh600172)"""
    if '.' in code or code.startswith(('sh', 'sz')):
        return code
    if code.startswith(('6',)):
        return f'sh{code}'
    elif code.startswith(('0', '3')):
        return f'sz{code}'
    elif code.startswith(('4', '8')):
        return f'bj{code}'
    return code


def tdx_to_code(tdx_code):
    """TDX格式转6位代码 (sh600172 → 600172)"""
    if tdx_code.startswith(('sh', 'sz', 'bj')):
        return tdx_code[2:]
    return tdx_code


# ═══════════════════════════════════════════════════════════════
#  数据源1: TDX API REST
# ═══════════════════════════════════════════════════════════════

class TDXSource:
    """TDX REST API 数据源

    能力: 行情/批量行情/日K/15分K/1分K/逐笔成交/指数/涨跌统计/股票搜索
    延迟: quote 46ms / batch 52ms / kline_day 343ms
    """

    def __init__(self, api_url=None):
        self.api_url = api_url or TDX_API_URL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            TDXClient = _import_tdx_client()
            self._client = TDXClient(base_url=self.api_url)
        return self._client

    def quote(self, code):
        """单只实时行情"""
        return self.client.quote(code_to_tdx(code))

    def batch_quote(self, codes):
        """批量实时行情 (自动分批, 每批50只)"""
        tdx_codes = [code_to_tdx(c) for c in codes]
        result = {}
        for i in range(0, len(tdx_codes), 50):
            batch = tdx_codes[i:i+50]
            try:
                r = self.client.batch_quote(batch)
                for tc, q in r.items():
                    result[tdx_to_code(tc)] = q
            except Exception:
                pass
        return result

    def kline_day(self, code, count=30):
        """日K线"""
        return self.client.kline_day(code_to_tdx(code), count=count)

    def kline_15m(self, code, count=100):
        """15分钟K线"""
        return self.client.kline_15m(code_to_tdx(code), count=count)

    def kline_1m(self, code, count=240):
        """1分钟K线"""
        return self.client.kline_1m(code_to_tdx(code), count=count)

    def minute(self, code):
        """分时数据"""
        return self.client.minute(code_to_tdx(code))

    def trade_history(self, code):
        """逐笔成交"""
        return self.client.trade_history(code_to_tdx(code))

    def index(self, code='sh000001'):
        """指数行情"""
        return self.client.index(code)

    def market_stats(self):
        """涨跌统计"""
        return self.client.market_stats()

    def search(self, keyword):
        """股票搜索"""
        return self.client.search(keyword)


# ═══════════════════════════════════════════════════════════════
#  数据源2: easyquotation (腾讯/新浪)
# ═══════════════════════════════════════════════════════════════

class EasyQuotationSource:
    """easyquotation 数据源

    能力:
      - 腾讯源: 实时行情(含五档盘口)/批量行情/成交额/换手率/PE
      - 新浪源: 实时行情(备选)
    优势: WSL可用, 五档盘口数据, 成交额/换手率/PE
    """

    def __init__(self, source='tencent'):
        self.source = source
        self._q = None

    @property
    def q(self):
        if self._q is None:
            import easyquotation
            self._q = easyquotation.use(self.source)
        return self._q

    def quote(self, code):
        """单只行情 (含五档盘口)

        Returns:
            dict: {name, now, open, close, high, low, 涨跌(%), 成交量(手),
                  成交额(万), turnover, PE, bid1-5, ask1-5, bid1-5_volume, ...}
        """
        d = self.q.real(str(code))
        return d.get(str(code), d)

    def batch_quote(self, codes):
        """批量行情"""
        return self.q.stocks([str(c) for c in codes])

    def get_stock_codes(self):
        """获取全部A股代码列表"""
        import easyquotation
        return easyquotation.get_stock_codes()

    def market_snapshot(self):
        """全市场快照"""
        try:
            return self.q.all_market
        except Exception:
            return self.q.stocks(self.get_stock_codes())


# ═══════════════════════════════════════════════════════════════
#  数据源3: akshare (申万行业/指数)
# ═══════════════════════════════════════════════════════════════

class AkshareSource:
    """akshare 申万行业数据源

    能力:
      - 申万一二三级行业实时行情 + 涨幅排名
      - 行业指数历史K线(日/周/月)
      - 行业成分股列表
      - 行业基本信息(PE/PB/股息率)
    """

    def _ak(self):
        import akshare as ak
        return ak

    # ── 行业行情 ──

    def sector_realtime(self, level='二级行业'):
        """申万行业实时行情

        Args:
            level: '一级行业' / '二级行业' / '三级行业'

        Returns:
            DataFrame: [指数代码, 指数名称, 昨收盘, 今开盘, 最新价, 成交额, 成交量, 最高价, 最低价]
        """
        ak = self._ak()
        df = ak.index_realtime_sw(symbol=level)
        df['涨跌幅'] = (df['最新价'] - df['昨收盘']) / df['昨收盘'] * 100
        return df

    def sector_heat_top(self, n=5, level='二级行业'):
        """涨幅前N行业

        Returns:
            list of {name, code, change_pct}
        """
        df = self.sector_realtime(level)
        top = df.nlargest(n, '涨跌幅')
        return [
            {'name': r['指数名称'], 'code': r['指数代码'],
             'change_pct': round(r['涨跌幅'], 2)}
            for _, r in top.iterrows()
        ]

    def sector_heat_bottom(self, n=5, level='二级行业'):
        """跌幅前N行业"""
        df = self.sector_realtime(level)
        bottom = df.nsmallest(n, '涨跌幅')
        return [
            {'name': r['指数名称'], 'code': r['指数代码'],
             'change_pct': round(r['涨跌幅'], 2)}
            for _, r in bottom.iterrows()
        ]

    # ── 行业信息 ──

    def sector_info(self, level='二级行业'):
        """行业基本信息 (PE/PB/股息率)

        Args:
            level: '一级行业' / '二级行业' / '三级行业'

        Returns:
            DataFrame: [行业代码, 行业名称, 上级行业, 成份个数, 静态市盈率, TTM市盈率, 市净率, 静态股息率]
        """
        ak = self._ak()
        if level == '一级行业':
            return ak.sw_index_first_info()
        elif level == '二级行业':
            return ak.sw_index_second_info()
        else:
            return ak.sw_index_third_info()

    def sector_components(self, index_code='801072'):
        """行业成分股

        Args:
            index_code: 申万行业指数代码 (如 '801072'=通用设备)

        Returns:
            DataFrame: [序号, 证券代码, 证券名称, 最新权重, 计入日期]
        """
        ak = self._ak()
        return ak.index_component_sw(symbol=index_code)

    def sector_hist(self, index_code='801030', period='day'):
        """行业指数历史K线

        Args:
            index_code: 指数代码
            period: 'day' / 'week' / 'month'

        Returns:
            DataFrame: [代码, 日期, 收盘, 开盘, 最高, 最低, 成交量, 成交额]
        """
        ak = self._ak()
        return ak.index_hist_sw(symbol=index_code, period=period)

    def stock_sw2_name(self, code):
        """通过akshare查询个股所属申万行业 (备选, 优先用MySQL)"""
        ak = self._ak()
        try:
            df = ak.stock_individual_info_em(symbol=code)
            # 查找行业信息
            for _, row in df.iterrows():
                if '行业' in str(row.get('item', '')):
                    return row.get('value', '')
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
#  数据源4: MySQL 本地数据
# ═══════════════════════════════════════════════════════════════

class MySQLSource:
    """MySQL 本地数据源

    数据库:
      - mystocks: 申万行业分类 (sw_industry_classification 4430只)
      - tdx_data: TDX日K线 (day_kline 1243万行)
      - hermes:  持仓/交易记录
    """

    def __init__(self, host=None, user=None, password=None, port=None):
        self.host = host or MYSQL_HOST
        self.user = user or MYSQL_USER
        self.password = password or MYSQL_PWD
        self.port = port or MYSQL_PORT

    def _conn(self, database='mystocks'):
        import pymysql
        return pymysql.connect(
            host=self.host, user=self.user, password=self.password,
            port=self.port, database=database,
            connect_timeout=10, read_timeout=30
        )

    # ── 申万行业 ──

    def get_stock_sw2(self, code):
        """查询个股所属申万二级行业

        Args:
            code: 6位股票代码 (如 '600172')

        Returns:
            dict: {lv1, lv2, lv3, industry_code} or None
        """
        conn = self._conn('mystocks')
        try:
            cur = conn.cursor()
            for pat in [f'{code}%', code]:
                cur.execute(
                    "SELECT 行业代码, 新版一级行业, 新版二级行业, 新版三级行业 "
                    "FROM sw_industry_classification "
                    "WHERE 股票代码 LIKE %s AND 新版二级行业 != '' LIMIT 1",
                    (pat,)
                )
                r = cur.fetchone()
                if r:
                    return {
                        'industry_code': r[0],
                        'lv1': r[1],
                        'lv2': r[2],
                        'lv3': r[3],
                    }
        finally:
            conn.close()
        return None

    def get_stocks_by_sw2(self, lv2_name):
        """查询申万二级行业下的所有股票

        Args:
            lv2_name: 二级行业名称 (如 '通用设备')

        Returns:
            list of {code, name, lv1, lv2, lv3}
        """
        conn = self._conn('mystocks')
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 股票代码, 公司简称, 新版一级行业, 新版二级行业, 新版三级行业 "
                "FROM sw_industry_classification "
                "WHERE 新版二级行业 = %s",
                (lv2_name,)
            )
            rows = cur.fetchall()
            return [
                {'code': r[0].split('.')[0], 'name': r[1],
                 'lv1': r[2], 'lv2': r[3], 'lv3': r[4]}
                for r in rows
            ]
        finally:
            conn.close()

    def get_all_sw2_list(self):
        """获取全部申万二级行业列表

        Returns:
            list of {industry_code, lv1, lv2}
        """
        conn = self._conn('mystocks')
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT 行业代码, 新版一级行业, 新版二级行业 "
                "FROM sw_industry_classification "
                "WHERE 新版二级行业 != '' ORDER BY 行业代码"
            )
            return [
                {'industry_code': r[0], 'lv1': r[1], 'lv2': r[2]}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    # ── TDX日K ──

    def get_stock_list(self):
        """获取全部有日K数据的股票代码

        Returns:
            list of str (6位代码)
        """
        conn = self._conn('tdx_data')
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT stock_code FROM day_kline "
                "WHERE trade_date >= DATE_SUB(NOW(), INTERVAL 20 DAY) "
                "ORDER BY stock_code"
            )
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    def get_day_kline(self, code, days=30):
        """从MySQL读取日K线

        Args:
            code: 6位股票代码
            days: 回溯天数

        Returns:
            list of dict {date, open, close, high, low, volume, amount}
        """
        conn = self._conn('tdx_data')
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT trade_date, open_price, close_price, high_price, low_price, volume, amount "
                "FROM day_kline WHERE stock_code = %s "
                "ORDER BY trade_date DESC LIMIT %s",
                (code, days)
            )
            rows = cur.fetchall()
            return [
                {'date': str(r[0]), 'open': r[1], 'close': r[2],
                 'high': r[3], 'low': r[4], 'volume': r[5], 'amount': r[6]}
                for r in reversed(rows)
            ]
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════
#  数据源5: baostock (免费历史数据)
# ═══════════════════════════════════════════════════════════════

class BaostockSource:
    """baostock 数据源 (免费, WSL可用)

    核心能力:
      - 日K/周K/月K + 前复权/后复权/不复权
      - 5分/15分/30分/60分K线
      - 指数K线 (上证/深证/沪深300等)
      - 估值数据 (PE_TTM, PB_MRQ, PS_TTM, 现金流)
      - 财务数据: 盈利/偿债/运营/成长/现金流/杜邦分析
      - 交易日历 / 复权因子 / 分红配股
      - 全证券列表(8772只) / 证监会行业分类
      - 沪深300/上证50/中证500成分股
      - 宏观: 存贷款利率/存款准备金率/货币供应量

    与其他数据源的互补:
      - TDX无估值数据 → baostock有PE/PB/PS
      - TDX无财务数据 → baostock有季频财务全量
      - TDX无周K/月K → baostock有
      - easyquotation无K线 → baostock有全频段K线
      - TDX API宕机时 → baostock可完全替代行情+K线
    """

    def __init__(self):
        self._bs = None
        self._logged_in = False

    def _ensure_login(self):
        if not self._logged_in:
            import baostock as bs
            self._bs = bs
            lg = bs.login()
            if lg.error_code != '0':
                raise RuntimeError(f'baostock login failed: {lg.error_msg}')
            self._logged_in = True

    def _code_to_bs(self, code):
        """6位代码转baostock格式 (600172 → sh.600172)"""
        if '.' in code:
            return code
        if code.startswith(('6',)):
            return f'sh.{code}'
        elif code.startswith(('0', '3')):
            return f'sz.{code}'
        elif code.startswith(('4', '8')):
            return f'bj.{code}'
        return f'sh.{code}'

    def _bs_to_code(self, bs_code):
        """baostock格式转6位代码 (sh.600172 → 600172)"""
        return bs_code.split('.')[-1] if '.' in bs_code else bs_code

    # ── K线 ──

    def kline(self, code, start_date, end_date=None, frequency='d',
              adjustflag='2', fields=None):
        """K线数据 (日/周/月/分钟)

        Args:
            code: 6位代码
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD, None=最新
            frequency: 'd'=日 / 'w'=周 / 'm'=月 / '5'=5分 / '15'=15分 / '30'=30分 / '60'=60分
            adjustflag: '1'=后复权 / '2'=前复权 / '3'=不复权
            fields: 字段列表, None=默认全量

        Returns:
            DataFrame
        """
        self._ensure_login()
        if fields is None:
            if frequency == 'd':
                fields = 'date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,isST'
            elif frequency in ('w', 'm'):
                fields = 'date,code,open,high,low,close,volume,amount'
            else:
                fields = 'date,time,open,high,low,close,volume,amount'
        if end_date is None:
            from datetime import datetime
            end_date = datetime.now().strftime('%Y-%m-%d')
        rs = self._bs.query_history_k_data_plus(
            self._code_to_bs(code), fields,
            start_date=start_date, end_date=end_date,
            frequency=frequency, adjustflag=adjustflag
        )
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        # rs.data 在循环后可能为空，用 data 替代
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame(columns=rs.fields)

    def kline_day(self, code, days=30, adjustflag='2'):
        """日K线 (最近N天)

        Args:
            code: 6位代码
            days: 回溯天数
            adjustflag: '1'=后复权 / '2'=前复权 / '3'=不复权

        Returns:
            DataFrame: [date, open, high, low, close, preclose, volume, amount, turn, pctChg, isST]
        """
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime('%Y-%m-%d')
        return self.kline(code, start, frequency='d', adjustflag=adjustflag)

    def kline_week(self, code, weeks=52, adjustflag='2'):
        """周K线"""
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(weeks=weeks)).strftime('%Y-%m-%d')
        return self.kline(code, start, frequency='w', adjustflag=adjustflag)

    def kline_month(self, code, months=24, adjustflag='2'):
        """月K线"""
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=months * 31)).strftime('%Y-%m-%d')
        return self.kline(code, start, frequency='m', adjustflag=adjustflag)

    def kline_5min(self, code, date_str=None):
        """5分钟K线"""
        from datetime import datetime
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return self.kline(code, date_str, date_str, frequency='5', adjustflag='3')

    def kline_15min(self, code, date_str=None):
        """15分钟K线"""
        from datetime import datetime
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return self.kline(code, date_str, date_str, frequency='15', adjustflag='3')

    def kline_30min(self, code, date_str=None):
        """30分钟K线"""
        from datetime import datetime
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return self.kline(code, date_str, date_str, frequency='30', adjustflag='3')

    def kline_60min(self, code, date_str=None):
        """60分钟K线"""
        from datetime import datetime
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return self.kline(code, date_str, date_str, frequency='60', adjustflag='3')

    # ── 指数K线 ──

    def index_kline(self, code='sh.000001', days=30):
        """指数日K线

        Args:
            code: baostock指数代码 (sh.000001=上证, sz.399001=深证成指, sh.000300=沪深300)

        Returns:
            DataFrame
        """
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime('%Y-%m-%d')
        return self.kline(code, start, frequency='d', adjustflag='3',
                          fields='date,code,open,high,low,close,volume')

    # ── 估值数据 ──

    def valuation(self, code, days=30):
        """估值数据 (PE/PB/PS/现金流)

        Args:
            code: 6位代码
            days: 回溯天数

        Returns:
            DataFrame: [date, close, peTTM, pbMRQ, psTTM, pcfNcfTTM]
        """
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=int(days * 1.8))).strftime('%Y-%m-%d')
        return self.kline(code, start,
                          fields='date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM',
                          frequency='d', adjustflag='3')

    # ── 财务数据 ──

    def profit(self, code, year, quarter):
        """季频盈利能力 (ROE/净利率/毛利率/EPS)"""
        self._ensure_login()
        rs = self._bs.query_profit_data(code=self._code_to_bs(code),
                                         year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def balance(self, code, year, quarter):
        """季频偿债能力 (资产负债率/流动比率/速动比率)"""
        self._ensure_login()
        rs = self._bs.query_balance_data(code=self._code_to_bs(code),
                                          year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def operation(self, code, year, quarter):
        """季频运营能力 (应收周转/存货周转/总资产周转)"""
        self._ensure_login()
        rs = self._bs.query_operation_data(code=self._code_to_bs(code),
                                            year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def growth(self, code, year, quarter):
        """季频成长能力 (营收同比/净利润同比/EPS同比)"""
        self._ensure_login()
        rs = self._bs.query_growth_data(code=self._code_to_bs(code),
                                         year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def cash_flow(self, code, year, quarter):
        """季频现金流 (经营/投资/筹资活动现金流)"""
        self._ensure_login()
        rs = self._bs.query_cash_flow_data(code=self._code_to_bs(code),
                                            year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def dupont(self, code, year, quarter):
        """杜邦分析 (ROE拆解)"""
        self._ensure_login()
        rs = self._bs.query_dupont_data(code=self._code_to_bs(code),
                                         year=year, quarter=quarter)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 基础信息 ──

    def stock_basic(self, code=None, code_name=None):
        """证券基本信息

        Args:
            code: baostock格式 (如 'sh.600172')
            code_name: 证券名称 (如 '黄河旋风')

        Returns:
            DataFrame: [code, code_name, ipoDate, outDate, type, status]
        """
        self._ensure_login()
        kwargs = {}
        if code:
            kwargs['code'] = code
        if code_name:
            kwargs['code_name'] = code_name
        rs = self._bs.query_stock_basic(**kwargs)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def stock_industry(self, code):
        """证监会行业分类

        Args:
            code: baostock格式 (如 'sh.600172')

        Returns:
            DataFrame: [updateDate, code, code_name, industry, industryClassification]
        """
        self._ensure_login()
        rs = self._bs.query_stock_industry(code=self._code_to_bs(code))
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def all_stocks(self, date=None):
        """指定日期全部上市证券"""
        self._ensure_login()
        if date is None:
            from datetime import datetime
            date = datetime.now().strftime('%Y-%m-%d')
        rs = self._bs.query_all_stock(date=date)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 指数成分股 ──

    def hs300(self):
        """沪深300成分股"""
        self._ensure_login()
        rs = self._bs.query_hs300_stocks()
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def sz50(self):
        """上证50成分股"""
        self._ensure_login()
        rs = self._bs.query_sz50_stocks()
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def zz500(self):
        """中证500成分股"""
        self._ensure_login()
        rs = self._bs.query_zz500_stocks()
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 交易日/复权/分红 ──

    def trade_dates(self, start_date, end_date):
        """交易日历"""
        self._ensure_login()
        rs = self._bs.query_trade_dates(start_date=start_date, end_date=end_date)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def adjust_factor(self, code, start_date, end_date=None):
        """复权因子"""
        self._ensure_login()
        if end_date is None:
            from datetime import datetime
            end_date = datetime.now().strftime('%Y-%m-%d')
        rs = self._bs.query_adjust_factor(code=self._code_to_bs(code),
                                           start_date=start_date, end_date=end_date)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def dividend(self, code, year=None):
        """分红配股"""
        self._ensure_login()
        kwargs = {'code': self._code_to_bs(code)}
        if year:
            kwargs['year'] = year
        rs = self._bs.query_dividend_data(**kwargs)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 宏观数据 ──

    def deposit_rate(self, start_date, end_date=None):
        """存款利率"""
        self._ensure_login()
        rs = self._bs.query_deposit_rate_data(start_date=start_date, end_date=end_date or '')
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def loan_rate(self, start_date, end_date=None):
        """贷款利率"""
        self._ensure_login()
        rs = self._bs.query_loan_rate_data(start_date=start_date, end_date=end_date or '')
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def money_supply(self, year=None, month=None):
        """货币供应量 (月度/年度)"""
        self._ensure_login()
        if year and month:
            rs = self._bs.query_money_supply_data_month(year=year, month=month)
        elif year:
            rs = self._bs.query_money_supply_data_year(year=year)
        else:
            return __import__('pandas').DataFrame()
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 业绩预告/快报 ──

    def forecast(self, code, start_date, end_date=None):
        """业绩预告"""
        self._ensure_login()
        kwargs = {'code': self._code_to_bs(code), 'start_date': start_date}
        if end_date:
            kwargs['end_date'] = end_date
        rs = self._bs.query_forecast_report(**kwargs)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    def performance_express(self, code, start_date, end_date=None):
        """业绩快报"""
        self._ensure_login()
        kwargs = {'code': self._code_to_bs(code), 'start_date': start_date}
        if end_date:
            kwargs['end_date'] = end_date
        rs = self._bs.query_performance_express_report(**kwargs)
        import pandas as pd
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        return pd.DataFrame(data, columns=rs.fields) if data else pd.DataFrame()

    # ── 关闭 ──

    def close(self):
        if self._logged_in:
            self._bs.logout()
            self._logged_in = False

    def __del__(self):
        self.close()


# ═══════════════════════════════════════════════════════════════
#  统一入口: DataHub
# ═══════════════════════════════════════════════════════════════

class DataHub:
    """A股数据统一入口

    自动选择最优数据源:
      - 行情/K线/分时 → TDX API (主) / easyquotation (备) / baostock (历史备)
      - 行业/板块 → akshare + MySQL
      - 估值/财务 → baostock
      - 股票列表 → MySQL (主) / easyquotation (备) / baostock (备)
    """

    def __init__(self, tdx_url=None):
        self.tdx = TDXSource(tdx_url)
        self.eq = EasyQuotationSource('tencent')
        self.ak = AkshareSource()
        self.db = MySQLSource()
        self.bs = BaostockSource()

    # ── 行情 ──

    def quote(self, code):
        """实时行情 (TDX主, easyquotation备)

        Returns:
            dict: {price, open, high, low, close, volume, change_pct, name, ...}
        """
        try:
            return self.tdx.quote(code)
        except Exception:
            return self.eq.quote(code)

    def batch_quote(self, codes):
        """批量行情"""
        try:
            return self.tdx.batch_quote(codes)
        except Exception:
            return self.eq.batch_quote(codes)

    def quote_with_depth(self, code):
        """含五档盘口的行情 (easyquotation)"""
        return self.eq.quote(code)

    # ── K线 ──

    def kline_day(self, code, count=30):
        """日K线 (TDX API)"""
        return self.tdx.kline_day(code, count)

    def kline_15m(self, code, count=100):
        """15分钟K线"""
        return self.tdx.kline_15m(code, count)

    def kline_1m(self, code, count=240):
        """1分钟K线"""
        return self.tdx.kline_1m(code, count)

    # ── 分时/逐笔 ──

    def minute(self, code):
        """分时数据"""
        return self.tdx.minute(code)

    def trade_history(self, code):
        """逐笔成交"""
        return self.tdx.trade_history(code)

    # ── 行业/板块 ──

    def sector_heat_top5(self, level='二级行业'):
        """涨幅前5行业 (akshare)"""
        return self.ak.sector_heat_top(5, level)

    def sector_heat_bottom5(self, level='二级行业'):
        """跌幅前5行业"""
        return self.ak.sector_heat_bottom(5, level)

    def sector_realtime(self, level='二级行业'):
        """行业实时行情 (124个二级)"""
        return self.ak.sector_realtime(level)

    def sector_components(self, index_code):
        """行业成分股"""
        return self.ak.sector_components(index_code)

    def sector_hist(self, index_code, period='day'):
        """行业指数历史"""
        return self.ak.sector_hist(index_code, period)

    def sector_info(self, level='二级行业'):
        """行业PE/PB/股息率"""
        return self.ak.sector_info(level)

    def get_stock_sw2(self, code):
        """个股所属申万二级 (MySQL主, akshare备)"""
        r = self.db.get_stock_sw2(code)
        if r:
            return r['lv2']
        return self.ak.stock_sw2_name(code)

    def get_stocks_by_sw2(self, lv2_name):
        """行业下所有股票"""
        return self.db.get_stocks_by_sw2(lv2_name)

    def get_all_sw2_list(self):
        """全部申万二级行业列表"""
        return self.db.get_all_sw2_list()

    # ── 指数/市场 ──

    def index(self, code='sh000001'):
        """指数行情"""
        return self.tdx.index(code)

    def market_stats(self):
        """涨跌统计"""
        return self.tdx.market_stats()

    # ── 股票列表 ──

    def stock_list(self):
        """全A股列表 (MySQL主, easyquotation备)"""
        try:
            return self.db.get_stock_list()
        except Exception:
            return self.eq.get_stock_codes()

    # ── baostock: 估值/财务/历史K线 ──

    def valuation(self, code, days=30):
        """估值数据 PE/PB/PS/现金流 (baostock)"""
        return self.bs.valuation(code, days)

    def profit(self, code, year, quarter):
        """季频盈利能力 ROE/净利率/毛利率/EPS"""
        return self.bs.profit(code, year, quarter)

    def balance(self, code, year, quarter):
        """季频偿债能力 资产负债率/流动比率/速动比率"""
        return self.bs.balance(code, year, quarter)

    def operation(self, code, year, quarter):
        """季频运营能力 应收周转/存货周转/总资产周转"""
        return self.bs.operation(code, year, quarter)

    def growth(self, code, year, quarter):
        """季频成长能力 营收同比/净利润同比"""
        return self.bs.growth(code, year, quarter)

    def cash_flow(self, code, year, quarter):
        """季频现金流 经营/投资/筹资活动现金流"""
        return self.bs.cash_flow(code, year, quarter)

    def dupont(self, code, year, quarter):
        """杜邦分析 ROE拆解"""
        return self.bs.dupont(code, year, quarter)

    def forecast(self, code, start_date, end_date=None):
        """业绩预告"""
        return self.bs.forecast(code, start_date, end_date)

    def performance_express(self, code, start_date, end_date=None):
        """业绩快报"""
        return self.bs.performance_express(code, start_date, end_date)

    def kline_week(self, code, weeks=52, adjustflag='2'):
        """周K线 (baostock)"""
        return self.bs.kline_week(code, weeks, adjustflag)

    def kline_month(self, code, months=24, adjustflag='2'):
        """月K线 (baostock)"""
        return self.bs.kline_month(code, months, adjustflag)

    def kline_5min(self, code, date_str=None):
        """5分钟K线 (baostock)"""
        return self.bs.kline_5min(code, date_str)

    def kline_30min(self, code, date_str=None):
        """30分钟K线 (baostock)"""
        return self.bs.kline_30min(code, date_str)

    def kline_60min(self, code, date_str=None):
        """60分钟K线 (baostock)"""
        return self.bs.kline_60min(code, date_str)

    def index_kline(self, code='sh.000001', days=30):
        """指数日K线 (baostock)"""
        return self.bs.index_kline(code, days)

    def trade_dates(self, start_date, end_date):
        """交易日历"""
        return self.bs.trade_dates(start_date, end_date)

    def adjust_factor(self, code, start_date, end_date=None):
        """复权因子"""
        return self.bs.adjust_factor(code, start_date, end_date)

    def dividend(self, code, year=None):
        """分红配股"""
        return self.bs.dividend(code, year)

    def stock_basic(self, code=None, code_name=None):
        """证券基本信息"""
        return self.bs.stock_basic(code, code_name)

    def stock_industry_csrc(self, code):
        """证监会行业分类"""
        return self.bs.stock_industry(code)

    def hs300(self):
        """沪深300成分股"""
        return self.bs.hs300()

    def sz50(self):
        """上证50成分股"""
        return self.bs.sz50()

    def zz500(self):
        """中证500成分股"""
        return self.bs.zz500()

    def close(self):
        """释放资源 (baostock logout)"""
        self.bs.close()


# ── CLI 测试入口 ──

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='A股数据源统一接口测试')
    parser.add_argument('--quote', help='实时行情: --quote 600172')
    parser.add_argument('--depth', help='五档盘口: --depth 600172')
    parser.add_argument('--kline', help='日K线: --kline 600172')
    parser.add_argument('--sw2', help='申万二级: --sw2 600172')
    parser.add_argument('--sector-top', action='store_true', help='板块涨幅Top5')
    parser.add_argument('--sector-bottom', action='store_true', help='板块跌幅Top5')
    parser.add_argument('--sector-list', action='store_true', help='全部二级行业')
    parser.add_argument('--sector-components', help='行业成分股: --sector-components 801072')
    parser.add_argument('--stocks', action='store_true', help='全A股数量')
    # baostock
    parser.add_argument('--valuation', help='估值数据(PE/PB/PS): --valuation 600172')
    parser.add_argument('--profit', help='季频盈利: --profit 600172')
    parser.add_argument('--growth', help='季频成长: --growth 600172')
    parser.add_argument('--dupont', help='杜邦分析: --dupont 600172')
    parser.add_argument('--cash-flow', help='季频现金流: --cash-flow 600172')
    parser.add_argument('--kline-week', help='周K线: --kline-week 600172')
    parser.add_argument('--kline-month', help='月K线: --kline-month 600172')
    parser.add_argument('--index-kline', action='store_true', help='上证指数日K')
    parser.add_argument('--trade-dates', action='store_true', help='最近10个交易日')
    parser.add_argument('--dividend', help='分红配股: --dividend 600172')
    parser.add_argument('--hs300', action='store_true', help='沪深300成分股数量')
    parser.add_argument('--industry', help='证监会行业: --industry 600172')
    args = parser.parse_args()

    hub = DataHub()

    if args.quote:
        d = hub.quote(args.quote)
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    elif args.depth:
        d = hub.quote_with_depth(args.depth)
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    elif args.kline:
        klines = hub.kline_day(args.kline, 5)
        for k in klines:
            print(f"  {k.get('time','')} O={k['open']:.2f} H={k['high']:.2f} "
                  f"L={k['low']:.2f} C={k['close']:.2f} V={k['volume']}")
    elif args.sw2:
        sw2 = hub.get_stock_sw2(args.sw2)
        full = hub.db.get_stock_sw2(args.sw2)
        print(f'  申万二级: {sw2}')
        if full:
            print(f'  完整: {json.dumps(full, ensure_ascii=False)}')
    elif args.sector_top:
        top = hub.sector_heat_top5()
        print('板块涨幅Top5:')
        for s in top:
            print(f'  {s["name"]}({s["code"]}): {s["change_pct"]:+.2f}%')
    elif args.sector_bottom:
        bottom = hub.sector_heat_bottom5()
        print('板块跌幅Top5:')
        for s in bottom:
            print(f'  {s["name"]}({s["code"]}): {s["change_pct"]:+.2f}%')
    elif args.sector_list:
        lst = hub.get_all_sw2_list()
        for s in lst:
            print(f'  {s["industry_code"]} | {s["lv1"]} > {s["lv2"]}')
        print(f'共{len(lst)}个二级行业')
    elif args.sector_components:
        df = hub.sector_components(args.sector_components)
        print(df.to_string())
    elif args.stocks:
        codes = hub.stock_list()
        print(f'共{len(codes)}只股票')
        print(f'前10: {codes[:10]}')
    elif args.valuation:
        df = hub.valuation(args.valuation, 10)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无数据')
    elif args.profit:
        df = hub.profit(args.profit, 2026, 1)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无数据(尝试更早季度)')
    elif args.growth:
        df = hub.growth(args.growth, 2025, 4)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无数据(尝试更早季度)')
    elif args.dupont:
        df = hub.dupont(args.dupont, 2025, 4)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无数据(尝试更早季度)')
    elif args.cash_flow:
        df = hub.cash_flow(args.cash_flow, 2025, 4)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无数据(尝试更早季度)')
    elif args.kline_week:
        df = hub.kline_week(args.kline_week, 4)
        if len(df):
            print(df.to_string(index=False))
    elif args.kline_month:
        df = hub.kline_month(args.kline_month, 6)
        if len(df):
            print(df.to_string(index=False))
    elif args.index_kline:
        df = hub.index_kline('sh.000001', 5)
        if len(df):
            print(df.to_string(index=False))
    elif args.trade_dates:
        df = hub.trade_dates('2026-06-01', '2026-06-15')
        print(df.to_string(index=False))
    elif args.dividend:
        df = hub.dividend(args.dividend)
        if len(df):
            print(df.to_string(index=False))
        else:
            print('无分红数据')
    elif args.hs300:
        df = hub.hs300()
        print(f'沪深300共{len(df)}只')
        print(df.head(5).to_string(index=False))
    elif args.industry:
        df = hub.stock_industry_csrc(args.industry)
        if len(df):
            print(df.to_string(index=False))
    else:
        parser.print_help()
    hub.close()
