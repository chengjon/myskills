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
| 主数据源 | 新浪15分K线 API (最多5000条/股票, 回溯约16个月, 覆盖2025-02-19至今) |
| 补充数据源 | pytdx (通达信行情服务器, 回溯到2024-05-22, 覆盖更早的69笔交易) |
| 覆盖范围 | 100%交易(1079/1079笔); 15分K线1008笔(93.4%), 日线BOLL 71笔(6.6%) |
| K线缓存 | MySQL `kline_15min` 表, 880153行/119只股票, 优先读缓存 |
| pytdx桥接 | WSL→Windows Python, 详见 references/wsl-pytdx-bridge.md |
| 日线数据源 | TDX本地day文件 → MySQL tdx_data.day_kline (7843只股票, 1243万行, 2000~2026-06-04, 不复权) |
| 匹配算法 | 多级匹配: exact → boundary(<1%) → approximate(<15%容差,复权偏差) → daily级别(71笔no_data) → failed |

## 核心脚本

```
/root/.hermes/skills/mystock-analysis/trade-audit/scripts/intraday_position_analyzer.py
```

## 运行命令

```bash
cd /root/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=<password>
source /root/.hermes/hermes-agent/venv/bin/activate

# 全量分析(强制覆盖trade_audit, 仅新浪数据)
python intraday_position_analyzer.py --force --min-date 2025-02-19

# 含pytdx补充(覆盖2024-07~2025-02的早期交易)
python intraday_position_analyzer.py --force --min-date 2024-07-22 \
  --pytdx-start 2024-07-01 --pytdx-end 2025-02-18

# 增量分析(只处理新交易)
python intraday_position_analyzer.py --min-date 2025-02-19

# 强制从API刷新K线缓存(忽略DB缓存，重新拉取并写入)
python intraday_position_analyzer.py --force --refresh-cache --min-date 2025-02-19

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

## 关键发现 (2026-06-04 数据, 1008笔已分析, 0 failed)

匹配方法分布: exact 878笔(87.1%), approximate 81笔(8.0%), boundary 49笔(4.9%), daily_exact 71笔(6.6%); failed 0笔; 总覆盖率100%

| 维度 | 最优 | 最差 |
|------|------|------|
| 入场时间 | 午后开盘(67%, +291) | 尾盘(42%, -372) |
| 入场趋势 | 偏跌抄底(+83/笔) | 追涨(26%, -453/笔) |
| 双层BOLL | 日下轨+15m中轨(65%, +836) | 日上轨+15m上轨(23%, -793) |
| 买卖对称 | BOLL低买高卖(64%, +632) | BOLL高买低卖(31%, -645) |

## K线缓存机制

15分K线数据缓存在 MySQL `kline_15min` 表中(55万+行，111只股票)，避免重复调API。

**流程**: `fetch_15min_kline(code)` → 查DB缓存 → 有且覆盖日期范围则返回 → 无则调新浪API → 若需补充早期数据则调pytdx → 合并去重 → 写入DB → 返回

| 参数 | 作用 |
|------|------|
| 默认 | 优先读DB缓存，miss才调API |
| `--refresh-cache` | 强制从API重新拉取，更新缓存(INSERT IGNORE不删旧数据) |
| `--force` | 只影响trade_audit写入，不影响缓存 |
| `--pytdx-start / --pytdx-end` | 补充新浪无法覆盖的早期数据(如2024-05-01~2025-02-18) |

**缓存表**: `kline_15min` (stock_code, kline_date, open, high, low, close_price, volume, fetched_at)
- UNIQUE KEY: (stock_code, kline_date)
- INSERT IGNORE: 新数据追加，已有数据不覆盖
- 如需更新特定股票: 先DELETE再--refresh-cache

**性能对比**: 纯缓存 2m41s vs API模式 5m02s (省47%时间，0次API调用)

1. **复权价 vs 不复权K线 (最关键陷阱)**: trade_audit中的buy_price/sell_price是前复权价(券商已调整分红送股)，但新浪/pytdx的15分K线是不复权价。对于有过除权除息的股票，偏差可达5-15%。原exact+boundary(<1%)匹配会大量failed。解决方案: 增加`approximate`策略(策略3)，找价格偏差最小的K线，容差15%。标记为`entry_match_method='approximate'`以便区分精度。实测: 容差5%→62笔,10%→77笔,15%→81笔(全部覆盖,0 failed)。
2. **row字典key映射**: 匹配结果key(vol_ratio) ≠ 数据库列名(entry_vol_ratio_15m)，必须用 key_to_col 映射表
2. **numpy类型**: boll_15m/vol_ratio 返回 numpy.float64，写入MySQL前必须 `.item()` 转原生Python
3. **买卖对称性符号**: buy_sell_symmetry = entry_boll - exit_boll，正值意味着"入场BOLL高"= 高买低卖
4. **成交量全NULL**: 上述key映射bug导致 vol_ratio/price_position 未写入，已修复
5. **15分BOLL需要20根前置K线**: 每日前30分钟的K线可能BOLL不稳定
6. **早盘集中**: 593/939(63%)交易在morning_early，可能与价格匹配算法有关(选了成交量最大的K线)
7. **venv依赖**: 需要 numpy + pymysql，用 `/root/.hermes/hermes-agent/venv/bin/activate`
8. **pytdx数据上限**: 通达信15分K线最多~7200根/股票(回溯到2024-07-22)，2024-07之前的交易无法覆盖，应标记 `entry_match_method = 'no_data'`
8. **pytdx需Windows Python**: WSL IP被TDX封锁，必须通过 `su john` 调Windows Python执行pytdx(详见 references/wsl-pytdx-bridge.md)
9. **71笔no_data交易已用日线BOLL补充完成**: 15分K线无法覆盖2024-07-22前的71笔交易，用daily_position_analyzer.py从tdx_data.day_kline计算20日BOLL/趋势/量比，标记analysis_level='day', entry_match_method='daily_exact'。最终1079/1079笔=100%覆盖率
10. **approximate容差阶梯调优**: 容差5%→62笔approximate, 10%→77笔, 15%→81笔(0 failed)。除权除息幅度大的股票偏差可达10-15%，最终15%覆盖所有。降容差会新增failed

## 文件清单

| 文件 | 用途 |
|------|------|
| `scripts/intraday_position_analyzer.py` | 核心分析脚本(匹配+8维度+报告+pytdx集成) |
| `scripts/daily_position_analyzer.py` | 日线BOLL分析(71笔no_data交易, 数据源: tdx_data.day_kline) |
| `scripts/pytdx_kline_adapter.py` | pytdx适配器(WSL→Windows Python桥接) |
| `config/review_config.yaml` | 评分规则(intraday_15m段) |
| `Obsidian: 15分钟买卖位置分析_YYYYMMDD.md` | 交叉分析报告 |
| `references/wsl-pytdx-bridge.md` | WSL下通过Windows Python调用pytdx的技术细节 |
