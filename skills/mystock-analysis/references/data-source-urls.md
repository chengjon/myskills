# 股票数据源 API 参考

> .so 脚本不可用时的手动 fallback 数据源。所有 URL 已验证可用。

## 1. 新浪实时行情

```
GET http://hq.sinajs.cn/list=sz000938
Header: Referer: http://finance.sina.com.cn
```

返回 GBK 编码文本，格式：
```
var hq_str_sz000938="名称,今开,昨收,当前价,最高,最低,买一,卖一,成交量(股),成交额(元),...(30个字段)";
```

字段索引：0=名称 1=今开 2=昨收 3=当前价 4=最高 5=最低 8=成交量 9=成交额 30=日期 31=时间

**注意**：必须加 Referer 头，否则可能被拒绝。A股代码前缀：沪市=`sh`，深市=`sz`。

## 2. 新浪日K线（推荐，稳定）

```
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz000938&scale=240&ma=no&datalen=120
```

返回 JSON 数组，每条格式：
```json
{"day":"2026-03-03","open":"25.170","high":"25.450","low":"23.770","close":"23.860","volume":"76568093"}
```

参数：
- `symbol`: sz/sh + 6位代码
- `scale`: 240=日线, 60=60分钟, 30=30分钟
- `datalen`: 返回条数（最多约500）

**注意**：无需特殊 Header，返回 UTF-8 JSON。

## 3. 东方财富日K线（备用）

```
GET https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.000938&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt=120
Header: Referer: https://quote.eastmoney.com/
```

secid 格式：深市=`0.代码`，沪市=`1.代码`

返回 JSON，klines 在 `data.klines` 数组中，每条为逗号分隔字符串。

**注意**：需要 Referer 头。部分网络环境下 HTTPS 连接可能被拒绝，此时 fallback 到新浪。

## 数据源选择策略

1. 首选新浪日K线（简单、稳定、无需 Referer）
2. 实时行情用新浪 hq.sinajs.cn（需 Referer）
3. 东方财富作为补充，新浪不可用时再试
