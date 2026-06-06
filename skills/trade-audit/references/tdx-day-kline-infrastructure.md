# TDX日线数据基础设施

## 概述

通达信本地day文件解析 → MySQL `tdx_data.day_kline` 表，提供2000年至今的不复权日线数据，覆盖7843只股票。

## 数据源

- 目录: `D:\mystocks\tdx\vipdoc_merged\{sh,sz,bj}\lday\*.day`
- 文件数: sh:5896, sz:5231, bj:563 (共11690个day文件)
- 格式: 32字节记录 `struct.pack('IIIIIfII', date, open, high, low, close, amount, volume, reserved)`
- 价格÷100, 成交量÷100(手)
- 合并了多来源, 含manifest

## MySQL表

```sql
CREATE DATABASE IF NOT EXISTS tdx_data;
-- 表: day_kline
-- UNIQUE KEY(stock_code, trade_date)
-- 列: stock_code, trade_date, open, high, low, close_price, amount, volume
-- 数据量: 12,437,953行, 7,843只股票
-- 日期范围: 2000-02-14 ~ 2026-06-04
```

连接: `mysql -h $MYSQL_HOST -u root -P 3306 tdx_data`

## 导入脚本

`scripts/read_tdx_day.py` (294行)

参考用户脚本风格: `D:\MyData\GITHUB\Gitee\mystocks\mystocks\bin\comm\read_tdx_day.py` (52行)

### 运行命令

```bash
cd ~/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=xxx
source /root/.hermes/hermes-agent/venv/bin/activate

# 全量导入(增量: 已有skip, 只追加新增)
python3 read_tdx_day.py

# 指定股票
python3 read_tdx_day.py --codes 000001,600172,300275

# 强制覆盖(先删后插)
python3 read_tdx_day.py --force

# 试运行
python3 read_tdx_day.py --dry-run
```

### 增量逻辑

1. 扫描day文件目录，获取文件记录数(文件大小÷32)
2. 查DB: `SELECT COUNT(*) FROM day_kline WHERE stock_code=xxx`
3. DB记录数 == 文件记录数 → skip
4. DB记录数 < 文件记录数 → 只解析新增部分(从offset=DB记录数开始)
5. INSERT IGNORE幂等(UNIQUE KEY stock_code+trade_date)

### 全量导入结果 (2026-06-04)

- 11597个code(含指数ETF等无day文件的代码)
- 7840追加成功, 3754 no_file(指数/ETF无day文件), 3 skip
- 新增12,426,264行

## 关键用途

1. **71笔no_data交易的日线BOLL分析**: 15分K线无法覆盖2024-07-22前的交易，但日线数据从2000年起可用
2. **复权因子计算**: 不复权收盘价 vs trade_audit的前复权buy_price → 计算除权因子，修正approximate匹配
3. **事后验证增强**: 250条日K线的替代/补充数据源

## 陷阱

- **不复权价 vs 前复权价**: day文件价格是不复权价，trade_audit的buy_price/sell_price是前复权价，除权股偏差5-15%
- **指数/ETF无day文件**: 3754个code无对应day文件(标记no_file)，这些是指数、ETF等
- **close_price列名**: 避MySQL保留字`close`，用`close_price`
- **Windows路径映射**: WSL下 `/mnt/d/mystocks/tdx/...` 对应 Windows `D:\mystocks\tdx\...`
