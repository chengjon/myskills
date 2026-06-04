# 可用数据源 API 端点

> 基于 2026-05-31 实测验证。仅记录稳定可用的端点。

## 新浪实时行情（推荐，主数据源）

```
GET http://hq.sinajs.cn/list=sz000938
Header: Referer: http://finance.sina.com.cn
编码: GBK
```

返回格式（逗号分隔）：
```
名称,今开,昨收,当前价,最高,最低,买一,卖一,成交量(股),成交额(元),
买一量,买一价,...(5档买),卖一量,卖一价,...(5档卖),日期,时间,00
```

**必须加 Referer 头**，否则请求被拒。

A股前缀：沪市=`sh`，深市=`sz`。如 `sh600519`（茅台）、`sz000938`（紫光）

## 新浪日K线（WSL环境不稳定，推荐腾讯替代）

```
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz000938&scale=240&ma=no&datalen=120
```

- 无需 Referer
- 返回 JSON 数组，每条：`{"day":"2026-05-29","open":"30.030","high":"30.490","low":"27.450","close":"28.640","volume":"255632978"}`
- `scale=240` = 日K，`datalen` = 返回条数（最大约500）
- ⚠️ **WSL环境下频率限制(HTTP 456)**：连续请求200只后会被封，批量MA计算必须用腾讯K线API替代

## 腾讯前复权日K线（推荐，WSL稳定）

```
GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000938,day,,,25,qfq
Header: User-Agent: Mozilla/5.0, Referer: https://finance.qq.com/
```

- 返回 JSON：`{data: {symbol: {qfqday: [[日期,开盘,收盘,最高,最低,成交量],...]}}}`
- 优先取 `qfqday`（前复权），fallback 到 `day`
- 收盘价 = `k[2]`（index 2，不是index 3）
- 参数: `symbol=sh/sz/bj+代码,day,,,25,qfq`
- **WSL环境稳定可用**，替代新浪K线做批量MA计算

## 东方财富 K线（不稳定，备用）

```
GET http://push2his.eastmoney.com/api/qt/stock/kline?secid=0.000938&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt=120
```

- `secid` 格式：深市=`0.{code}`，沪市=`1.{code}`
- HTTPS 版本在部分网络环境下 404 或连接重置
- HTTP 版本稍稳定但仍可能失败
- **建议仅作备用**，新浪 K线不可用时再试

## 数据选择策略

1. 实时行情 → 新浪 `hq.sinajs.cn`（加 Referer）
2. 历史K线(少量) → 新浪 `money.finance.sina.com.cn`（无需 Referer）
3. 历史K线(批量/WSL) → 腾讯 `web.ifzq.gtimg.cn`（新浪WSL有频率限制）
4. 批量名称+行情 → 腾讯 `qt.gtimg.cn`（东财push2被封时的替代，GBK编码）
5. 新浪失败 → 尝试东方财富 HTTP（非 HTTPS）
6. 东方财富失败 → 告知用户数据源不可用，建议稍后重试

## 腾讯财经批量行情（补充数据源）

```
GET https://qt.gtimg.cn/q=s_sh600011,s_sz000539
Header: Referer: https://gu.qq.com/
编码: GBK
```

批量查询股票名称+价格+涨跌幅。格式：`s_sh` + 沪市代码，`s_sz` + 深市代码，逗号分隔，每批≤20只。

返回格式（每只一行，`~`分隔）：
```
v_sh600011="1~华能国际~600011~9.76~8.87~0.89~...~10.03%~...";
```

关键字段索引：1=名称 2=代码 3=当前价 31=涨跌额 32=涨跌幅

**适用场景**：
- 东财push2 API被封（WSL环境常见）时的fallback
- 批量补全股票名称（非交易时间东财页面名称列为空时）
- 不支持北交所(920xxx)

## 新浪分钟K线（WSL稳定可用，2026-06-04 验证）

```
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz002195&scale=15&ma=no&datalen=3200
```

- `scale`: 5=5分K, 15=15分K, 30=30分K, 60=60分K, 240=日K
- `datalen`: 最大 5000 条（超过自动截断到5000）
- 返回格式同日K线: `{"day":"2026-06-03 11:15:00","open":"7.640","high":"7.680","low":"7.630","close":"7.650","volume":"7303700"}`
- **WSL下稳定可用**（与日K线的 HTTP 456 封杀不同，分钟K线未被限制）
- 15分K线 5000 条约覆盖 4 个月历史（2025-02-19 ~ 当前）
- 5分K线 5000 条约覆盖 1.5 个月
- **不支持指定历史日期范围**（只能拉最近N条，不能指定start/end）

### 腾讯分钟K线 — 不可用

腾讯 `fqkline` 接口对 `m1/m5/m15/m30/m60` 全部返回 `param error`。
`mkline` 接口在 WSL 下 DNS 解析失败（`web.ifzq.gtimg.cn` 域名仅 fqkline 路径可达）。
**结论：分钟K线只能走新浪路径。**

### fetch_kline period 映射注意

`fetch_market_data.py` 的 `_fetch_kline_tencent` 中 `period_map` 没有 `"15": "m15"` 映射，
但 `fetch_kline("002195", period="15", count=10)` 仍可工作——因为它走了新浪路径而非腾讯。
新增分钟级别 period 时需确认新浪路径是否被优先，否则腾讯路径会静默返回空列表。

## 数据选择策略（更新版）

1. 实时行情 → 新浪 `hq.sinajs.cn`（加 Referer）
2. 历史日K线(少量) → 新浪 `money.finance.sina.com.cn`
3. 历史日K线(批量/WSL) → 腾讯 `web.ifzq.gtimg.cn`（新浪WSL有频率限制）
4. **分钟K线(5/15/30/60分)** → 新浪 `money.finance.sina.com.cn`（腾讯不支持，WSL稳定）
5. 批量名称+行情 → 腾讯 `qt.gtimg.cn`
6. 东方财富 HTTP → 仅备用

## execute_code 依赖注意

`execute_code` 沙箱不继承 Hermes venv 的包。首次使用前需安装：
```python
from hermes_tools import terminal
terminal(command="pip install numpy pandas -q")
```
或在 execute_code 内用 subprocess 调 curl 获取数据后用标准库 json 解析。
