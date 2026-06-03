---
name: intraday-15m-analysis
version: 1.0
description: 15分钟K线买卖位置分析——基于15分K线精确定位买卖时点，分析入场/出场的分时位置、BOLL位置、趋势状态、成交量异动等8维度，写入trade_audit并生成交叉分析报告。
trigger: 用户提到"15分钟分析"、"买卖位置"、"分时分析"、"intraday"、"15m"相关复盘
---

# 15分钟K线买卖位置分析

## 概述

对 trade_audit 中的交易，用15分钟K线精确匹配买卖时点，计算8个分析维度，写入 trade_audit 表并生成 Obsidian 报告。

## 数据基础

| 项目 | 值 |
|------|-----|
| 数据源 | 新浪15分K线 API (最多5000条/股票, 回溯约16个月) |
| 覆盖范围 | 2025-02-19 至今, 约87%交易(939/1079笔) |
| K线缓存 | MySQL `kline_15min` 表, 优先读缓存 |
| 匹配算法 | 多级匹配: exact → boundary → failed |

## 核心脚本

```
/root/.hermes/skills/mystock-analysis/trade-audit/scripts/intraday_position_analyzer.py
```

## 运行命令

```bash
cd /root/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=<password>
source /root/.hermes/hermes-agent/venv/bin/activate

# 全量分析(强制覆盖)
python intraday_position_analyzer.py --force --min-date 2025-02-19

# 增量分析(只处理新交易)
python intraday_position_analyzer.py --min-date 2025-02-19

# 只重新生成报告(不跑分析)
python intraday_position_analyzer.py --report-only

# 试运行(不写入数据库)
python intraday_position_analyzer.py --dry-run
```

## MySQL 依赖

- `trade_audit` 表: 14个15分分析字段 (entry_time_slot, entry_boll_15m, entry_trend_15m, entry_vol_ratio_15m, entry_price_position, entry_match_method, exit_*, first_hour_trend, buy_sell_symmetry)
- `kline_15min` 表: 15分K线缓存 (stock_code, kline_date, open, high, low, close, volume, fetched_at)

## 配置文件

- 评分规则: `trade-audit/config/review_config.yaml` → `intraday_15m` 段
- MySQL连接: 同 review_config.yaml → `mysql` 段

## 分析维度 (8个)

1. **入场分时位置** (entry_time_slot): morning_early/mid/late, afternoon_early/mid/late
2. **15分BOLL位置** (entry_boll_15m): %B = (price-lower)/(upper-lower) × 100
3. **分时趋势状态** (entry_trend_15m): 前5根K线方向 → continuous_up/mostly_up/sideways/mostly_down/continuous_down
4. **成交量异动** (entry_vol_ratio_15m): 当前量/前5根均量
5. **价格在K线中的位置** (entry_price_position): 0=最低, 1=最高
6. **买入后1小时走势** (first_hour_trend): 4根K线方向 → continuous_up/down/v_shape/sideways
7. **买卖BOLL对称性** (buy_sell_symmetry): entry_boll - exit_boll (正值=高买低卖)
8. **出场侧镜像** (exit_*): 时间段/BOLL/趋势/量比/价格位置/匹配方法

## 交叉分析报告 (6个表)

1. 入场时间段 × 胜率 (含Wilson CI, 冲动率, 放量比)
2. 日线BOLL × 15分BOLL 双层矩阵 (3×3)
3. 买入后1小时走势 × 最终盈亏
4. 买卖BOLL对称性
5. 入场前趋势状态 × 胜率
6. 入场价格在K线中的位置 × 胜率

## 关键发现 (2026-06-04 数据)

| 维度 | 最优 | 最差 |
|------|------|------|
| 入场时间 | 午后开盘(67%, +291) | 尾盘(42%, -372) |
| 入场趋势 | 偏跌抄底(+83/笔) | 追涨(26%, -453/笔) |
| 双层BOLL | 日下轨+15m中轨(65%, +836) | 日上轨+15m上轨(23%, -793) |
| 买卖对称 | BOLL低买高卖(64%, +632) | BOLL高买低卖(31%, -645) |

## K线缓存机制

15分K线数据缓存在 MySQL `kline_15min` 表中(55万+行，111只股票)，避免重复调API。

**流程**: `fetch_15min_kline(code)` → 查DB缓存 → 有则返回 → 无则调新浪API → 写入DB → 返回

| 参数 | 作用 |
|------|------|
| 默认 | 优先读DB缓存，miss才调API |
| `--refresh-cache` | 强制从API重新拉取，更新缓存(INSERT IGNORE不删旧数据) |
| `--force` | 只影响trade_audit写入，不影响缓存 |

**缓存表**: `kline_15min` (stock_code, kline_date, open, high, low, close_price, volume, fetched_at)
- UNIQUE KEY: (stock_code, kline_date)
- INSERT IGNORE: 新数据追加，已有数据不覆盖
- 如需更新特定股票: 先DELETE再--refresh-cache

**性能对比**: 纯缓存 2m41s vs API模式 5m02s (省47%时间，0次API调用)

1. **row字典key映射**: 匹配结果key(vol_ratio) ≠ 数据库列名(entry_vol_ratio_15m)，必须用 key_to_col 映射表
2. **numpy类型**: boll_15m/vol_ratio 返回 numpy.float64，写入MySQL前必须 `.item()` 转原生Python
3. **买卖对称性符号**: buy_sell_symmetry = entry_boll - exit_boll，正值意味着"入场BOLL高"= 高买低卖
4. **成交量全NULL**: 上述key映射bug导致 vol_ratio/price_position 未写入，已修复
5. **15分BOLL需要20根前置K线**: 每日前30分钟的K线可能BOLL不稳定
6. **早盘集中**: 593/939(63%)交易在morning_early，可能与价格匹配算法有关(选了成交量最大的K线)
7. **venv依赖**: 需要 numpy + pymysql，用 `/root/.hermes/hermes-agent/venv/bin/activate`

## 文件清单

| 文件 | 用途 |
|------|------|
| `scripts/intraday_position_analyzer.py` | 核心分析脚本(匹配+8维度+报告) |
| `config/review_config.yaml` | 评分规则(intraday_15m段) |
| `Obsidian: 15分钟买卖位置分析_YYYYMMDD.md` | 交叉分析报告 |
