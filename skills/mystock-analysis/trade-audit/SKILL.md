---
name: trade-audit
description: 交易复盘审计——FIFO精确配对、4维10分评分、四分法、事后验证闭环、MySQL入库。支持单次运行、指定日期/时间段复盘。触发词：复盘/审计/audit/review。
user-invocable: true
dependency:
  python:
    - pymysql>=1.1.0
    - numpy>=1.24.0
  system:
    - mysql client
  env:
    - MYSQL_PWD
---

# 交易复盘审计（trade-audit）

> 独立的交易复盘审计引擎。FIFO精确配对 → 4维10分评分 → 四分法分类 → 事后验证闭环 → MySQL入库。

## 触发词

`复盘`、`审计`、`audit`、`review`、`交易复盘`

## 前置条件

- MySQL: `192.168.123.104:3306/hermes`（环境变量 MYSQL_PWD）
- 平安交易表: `pingan_normal_trade` / `pingan_margin_trade`
- 腾讯K线API可用（WSL下新浪被封，腾讯为fallback）
- venv选择: 路径分析+15分分析需numpy → `/root/.hermes/hermes-agent/venv`; 仅pymysql → `/opt/claude/Scrapling/.venv`

## 运行方式

### 单次运行（CLI）

```bash
cd ~/.hermes/skills/mystock-analysis/trade-audit/scripts
source /opt/claude/Scrapling/.venv/bin/activate

# 批量审计（指定时间段）
python review_generator.py audit --start 2026-01-01 --end 2026-06-30
python review_generator.py audit --start 2026-01-01 --end 2026-06-30 --force  # 强制重写

# 单只股票审计
python review_generator.py audit-single --code 000539 --buy-date 2025-03-01 --buy-price 5.10

# 事后验证补全
python review_generator.py audit --update-post --days 5,10,20,60

# 生成复盘卡（Obsidian）
python review_generator.py draft --code 002077 --name 大港股份 --price 15.50 --qty 2000 --v3
python review_generator.py update --file /path/to/复盘卡.md --days 5
```

### 对话中触发

- `复盘 2026-01-01 到 2026-03-31` → 指定时间段批量审计
- `复盘 000539` → 单只股票复盘
- `补全事后验证` → batch_update_post_validation

## V3评分体系（4维10分）

| 维度 | 满分 | 评分要素 |
|------|------|----------|
| 入场(entry) | 3 | 趋势+位置(BOLL%b)+信号 |
| 出场(exit) | 3 | 卖出判定(6种verdict)+事后涨跌 |
| 纪律(discipline) | 2 | 止损+仓位合规 |
| 风控(risk) | 2 | 追高+集中度+顺势 |

## 四分法

| 类别 | 条件 | 含义 |
|------|------|------|
| 规则内盈利 | 止损+仓位+顺势 | 系统性获利 |
| 规则外盈利 | 缺止损/仓位/顺势 | 运气成分 |
| 规则内亏损 | 止损+仓位但止损触发 | 系统性止损(正常) |
| 规则外亏损 | 无止损+仓位/顺势违规 | 需改进 |

## 卖出判定（6种verdict）

| verdict | 条件 |
|---------|------|
| normal | 一般卖出 |
| missed_profit | 盈利交易过早卖出(卖出后20日创新高) |
| good_profit | 卖出后5/10日继续跌 |
| late_stop | 止损过晚(5日跌>5%) |
| perfect_stop | 卖在止损价附近 |
| unknown | 数据不足 |

**关键**：missed_profit只在盈利交易(sell_price > buy_price)中判定，亏损交易卖出后反弹不判missed_profit。

## 数据流

```
calc_pingan_pnl.py (FIFO精确配对)
  → review_generator._fetch_completed_trades (优先FIFO, fallback SQL)
    → review_generator.batch_audit (逐笔评分+MySQL写入)
      → review_generator.insert_audit_from_trade
        → fetch_market_data.fetch_pre_snapshot (买入日快照)
        → fetch_market_data.fetch_post_validation (卖出后T+N验证)
        → trade_audit_sql.insert_audit_record (写入trade_audit表)
```

## MySQL表

| 表 | 用途 | 数据量 |
|----|------|--------|
| trade_audit | V3审计记录 | ~1026笔 |
| trade_audit_signal | 审计信号 | 空 |
| audit_log | 批量审计运行日志 | ~7条 |
| pingan_normal_trade | 平安普通原始交易 | 4,206行 |
| pingan_margin_trade | 平安两融原始交易 | 2,604行 |

## 配置

`config/review_config.yaml` — 评分参数（权重/阈值/成本，修改即生效）

## 关键设计

1. **FIFO精确配对**：calc_pingan_pnl.py 计算完整交易对（含buy_date/buy_price），非简化SQL配对
2. **sell_date基准**：事后验证从卖出日起算T+N，涨跌幅基准用sell_price
3. **max_price_hold**：从买入日到卖出日K线中取持仓期最高价
4. **腾讯K线fallback**：新浪WSL被封(HTTP 456)，自动切腾讯web.ifzq.gtimg.cn
5. **250条日K线**：确保MA60/BOLL/MACD等指标计算(BOLL覆盖率74%)
6. **增量模式**：uk_trade去重，force=False跳过已有记录
7. **配置热更新**：batch_audit每次重新load_config()

## 操作步骤（完整闭环）

### 批量审计

1. `python review_generator.py audit --start START --end END` — 逐笔评分写入trade_audit
2. `batch_update_post_validation(conn, days_list=[5,10,20,60], recalc_verdict=True)` — 补全事后字段+重算sell_verdict
3. 验证: `SELECT sell_verdict, COUNT(*) FROM trade_audit GROUP BY sell_verdict`
4. 如果missed_profit中亏损交易占比>5%，说明sell_verdict未用buy_price过滤，需重跑步骤2

### 事后验证补全（独立运行）

当只补post字段不改评分时：`recalc_verdict=False`
当post数据变更需重算verdict时：`recalc_verdict=True`（默认）

## 完整审计闭环操作步骤

1. `python review_generator.py audit --start START --end END --force` — 逐笔评分写入trade_audit
2. `batch_update_post_validation(conn, days_list=[5,10,20,60], recalc_verdict=True)` — 补全post字段+重算sell_verdict
3. 验证: `SELECT sell_verdict, COUNT(*) FROM trade_audit GROUP BY sell_verdict`
4. 如果missed_profit中亏损交易占比>5%，说明sell_verdict未用buy_price过滤，需SQL修正:
   ```sql
   UPDATE trade_audit SET sell_verdict='normal' WHERE sell_verdict='missed_profit' AND realized_pnl <= 0;
   ```
5. 确认max_price_hold写入: `SELECT COUNT(*) FROM trade_audit WHERE max_price_hold IS NOT NULL AND max_price_hold > 0`
6. 确认指标覆盖率: BOLL>70%, trend>60%, post5>90%

### 事后验证补全（独立运行）

当只补post字段不改评分时：`recalc_verdict=False`
当post数据变更需重算verdict时：`recalc_verdict=True`（默认）

## 陷阱

- **WSL下新浪K线被封**：HTTP 456，必须用腾讯fallback
- **腾讯K线列顺序**：[date,open,close,high,low,vol]，close在high前面（新浪是[open,high,low,close]）
- **missed_profit误判（已修复，勿回退）**：亏损交易卖出后反弹不应判missed_profit，calc_sell_verdict必须先检查buy_price vs sell_price，只有sell_price > buy_price时才可判missed_profit。历史教训：未加此检查时74%交易被判missed_profit，其中277笔为亏损交易
- **fetch_post_validation基准日（已修复，勿回退）**：必须从sell_date起算T+N，不是buy_date。事后验证是"卖出后"的表现，买入后5天可能还在持仓中。涨跌幅基准也必须用sell_price而非buy_price
- **POST_UPDATE_COLUMNS遗漏**：trade_audit_sql.py的POST_UPDATE_COLUMNS列表必须包含所有需要通过update_post_validation()更新的字段。新增字段时务必同步更新此列表，否则该字段永远为NULL。历史教训：max_price_hold加到insert但漏了POST_UPDATE_COLUMNS，716笔全部NULL
- **batch_update_post_validation的WHERE条件**：默认只处理post字段为NULL的记录。如果post数据已存在但sell_verdict需要重算（如修了missed_profit逻辑），需要用SQL直接UPDATE或加force参数
- **fetch_kline条数不足**：默认60条不够MA60/BOLL计算，fetch_pre_snapshot已改为250条。如果自定义调用fetch_kline，count参数至少120
- **60分K线**：腾讯不返回60分K线(m60=空)，追高检测降级
- **root用户无法执行Windows exe**：TdxQuant需su john，B3纯Python为推荐路径
- **技能独立性**：trade-audit是独立复盘功能，不依赖daily-stock工作流，也不应修改mystock-analysis的脚本。三者完全解耦
- **用户明确要求**：复盘审计是独立功能，与daily-stock完全解耦。不要把审计脚本混入mystock-analysis/scripts/（那里只有技术分析4文件），不要修改daily-stock的SKILL.md或脚本。mystock-analysis的SKILL.md必须保持GitHub原始版本(Part A/B/C)，审计内容放trade-audit/子目录。如果发现mystock-analysis被改了，必须从GitHub恢复

## 交易路径分析（已实现）

`trade_path_analyzer.py` 对同一股票完整交易路径进行聚合分析。

核心：L1单笔审计(V3) → L2交易路径(trade_path_summary) → L3行为画像(待实现)

### 运行方式

```bash
cd ~/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=xxx
python3 trade_path_analyzer.py              # 增量模式
python3 trade_path_analyzer.py --force      # 全量重算
python3 trade_path_analyzer.py --gap 30     # 覆盖gap阈值
```

### 47字段输出 → trade_path_summary 表

路径级汇总: 盈亏/胜率/回撤/Sharpe/Calmar/Pain Index/交易成本/持仓指标/行为指标(冲动率/报复率/摊平检测)/7种路径类型

### 路径切分算法

1. 按股票分组，组内按 buy_date 排序
2. 计算全局 gap P80（只统计正间隔，排除并行交易负gap）作为切分阈值
3. 相邻交易间隔 < gap_threshold → 同一路径；并行交易（gap<0）自动归入同一路径
4. path_id 格式: `{stock_code}_{start_yyyymmdd}_{end_yyyymmdd}`

### 7种路径类型

| 类型 | 判定条件 |
|------|----------|
| day_trade | 全部 hold_days≤1 |
| pyramid | is_pyramid=1 且 ≥3笔 |
| cost_averaging | 买入价递减 + 多笔亏损 |
| swing | 平均持仓≤5天（或≤30天且无长线混合） |
| position | 平均持仓20-60天 |
| long_term | 平均持仓>60天 |
| mixed | 无明确模式 |

### 设计要点

- 路径切分用自适应P80阈值（不要硬编码gap_days）
- Wilson CI 已实现（非入库，报告用）
- 包含风险调整指标(Sharpe/Calmar/Pain Index)
- 包含交易成本建模（佣金≈费用70%，印花税≈30%）
- 配置在 `config/review_config.yaml` → `path_analysis` 节

### 陷阱

- **gap P80 计算必须排除负间隔**：并行交易（gap<0）混入统计会导致 P80=0，使所有交易归入同一路径。`compute_gap_percentile` 必须只统计 gap>0 的样本，无正间隔时默认22天
- **MySQL DECIMAL 列宽**：BOLL %B 值范围 0-100，DECIMAL(6,4) 只能存到 99.9999，必须用 DECIMAL(8,4)；max_drawdown/pain_index/cost_ratio 等比例字段可能溢出 DECIMAL(8,4)，建表时统一用 DECIMAL(10,4)
- **impulsive_rate 偏高**：当前 is_impulsive 标记率 85%（923/1079），是 review_generator 的冲动标记逻辑过于宽松，不代表路径分析脚本有误。分析时应注意此基线偏差
- **pymysql import 位置**：在函数内部使用 pymysql 时，`import pymysql` 必须在函数顶部（if/else 分支之前），不能放在 `if conn is None:` 块内。否则在 conn 已传入时访问 conn 的 pymysql 方法会报 UnboundLocalError
- **max_drawdown 入库前需 clamp**：`_compute_drawdown` 返回的浮点值可能超出 DECIMAL 列范围，INSERT 前必须 `round(min(val, 99.9999), 4)` 限制精度和上限

### 交叉分析（trade_path_cross_analysis.py）

基于 trade_audit + trade_path_summary 生成 6 维交叉分析报告（Obsidian Markdown）。

```bash
cd ~/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=xxx
python3 trade_path_cross_analysis.py           # 生成报告到Obsidian
python3 trade_path_cross_analysis.py --no-save  # 只打印不保存
```

**6 个交叉分析模块:**

| # | 分析 | 核心指标 |
|---|------|---------|
| 1 | BOLL位置 × 持仓天数 | 3×4 交叉胜率+笔均盈亏 |
| 2 | 冲动交易细分 × sell_verdict | 4 组(冲动买入/卖出组合) × 4 verdict |
| 3 | 全局连亏 × 下次交易 | Wilson CI + Cohen's d 效应量 |
| 4 | 交易顺序效应 | 路径内第N笔的胜率+vs第1笔的d |
| 5 | 年度行为演变 | 胜率/冲动率/持仓天+CI+趋势 |
| 6 | 路径类型深度对比 | 各类型的胜率/盈亏/冲动率/摊平率 |

**统计方法:** Wilson 95% CI + Cohen's d 效应量; n<30 标注 ⚠️

**报告输出:** `Obsidian Vault/mystocks/复盘/交易路径分析/交叉分析报告_YYYYMMDD.md`

详见 [references/trade-path-cross-analysis.md](references/trade-path-cross-analysis.md)

设计详见 [references/trade-path-analysis-design.md](references/trade-path-analysis-design.md)

### 15分钟K线买卖位置分析（已实现）

`intraday_position_analyzer.py` 基于新浪15分K线（WSL稳定，最多5000条回溯~16个月），对买卖点做分时级别定位分析。
覆盖87%交易(939/1079, 2025-02-19之后)，939笔全量匹配成功(exact 88%+boundary 4%)。

#### 运行方式

```bash
cd ~/.hermes/skills/mystock-analysis/trade-audit/scripts
export MYSQL_PWD=xxx
source /root/.hermes/hermes-agent/venv/bin/activate   # 需要numpy+pymysql

python intraday_position_analyzer.py              # 增量模式（跳过已有entry_match_method）
python intraday_position_analyzer.py --force       # 全量重算
python intraday_position_analyzer.py --report-only  # 只生成交叉分析报告
python intraday_position_analyzer.py --dry-run     # 只统计不写入
```

#### 8个分析维度 → 14个新字段

| 维度 | 入场字段 | 出场字段 | 说明 |
|------|---------|---------|------|
| 分时位置 | entry_time_slot | exit_time_slot | 6段: morning_early/mid/late, afternoon_early/mid/late |
| 15分BOLL | entry_boll_15m | exit_boll_15m | %B (0-100), 需20根前置K线 |
| 分时趋势 | entry_trend_15m | exit_trend_15m | continuous_up/mostly_up/sideways/mostly_down/continuous_down |
| 成交量比 | entry_vol_ratio_15m | exit_vol_ratio_15m | 当前/前5根均量 |
| 价格位置 | entry_price_position | exit_price_position | 0=K线最低, 1=K线最高 |
| 匹配方法 | entry_match_method | exit_match_method | exact/boundary/failed |
| 买后1小时 | first_hour_trend | — | continuous_up/down/v_shape/inverted_v/sideways |
| BOLL对称性 | buy_sell_symmetry | — | entry_boll - exit_boll (正值=BOLL高买低卖) |

#### 多级匹配算法

1. **exact**: 价格在 [low, high] 范围内 → 选成交量最大的K线
2. **boundary**: 价格接近边界(<1%误差) → 选最近的
3. **failed**: 无法匹配 → 检查涨跌停/标注price_out_of_range

#### 关键发现（939笔数据）

| 维度 | 最优 | 最差 |
|------|------|------|
| 入场时间 | 午后开盘(67%, +291) | 尾盘(42%, -372) |
| 入场趋势 | 偏跌抄底(+83/笔) | 追涨(26%, -453/笔) |
| 双层BOLL | 日下轨+15m中轨(65%, +836) | 日上轨+15m上轨(23%, -793) |
| 买卖对称 | BOLL低买高卖(64%, +632) | BOLL高买低卖(31%, -645) |
| 买后1小时 | 连续上涨(45%) | 连续下跌(31%, -343) |
| K线内位置 | 中高位0.5-0.8(52%, +378) | 高位0.8-1.0(44%, -318) |

评分规则已写入 `config/review_config.yaml` → `intraday_15m` 节。

报告: `Obsidian Vault/mystocks/复盘/交易路径分析/15分钟买卖位置分析_YYYYMMDD.md`

#### 陷阱

- **row key映射必须用显式映射表**：匹配结果key(vol_ratio)与数据库列名(entry_vol_ratio_15m)不同，不能 `f"entry_{key}"` 拼接，必须用 `key_to_col` 映射表。否则 vol_ratio→entry_vol_ratio(不存在)，写入时该字段永远为NULL
- **numpy类型转原生Python**：`calc_boll_15m` 返回 `np.float64`，MySQL参数化绑定需 `val.item()` 转为 Python float，否则可能写入失败
- **buy_sell_symmetry方向**：`symmetry = entry_boll - exit_boll`；正值=入场BOLL高出场BOLL低=**BOLL高买低卖**(坏)，负值=**BOLL低买高卖**(好)。标签千万别反过来！
- **新浪15分K线回溯约16个月**：5000条对应2025-02-19至今，更早的交易(140笔/13%)无法覆盖，标记entry_match_method=NULL
- **venv选择**：需要numpy+pymysql，用 `/root/.hermes/hermes-agent/venv/bin/activate`（Scrapling venv无numpy）
- **早盘593笔偏重**：大量交易匹配到morning_early(9:30-10:00)，可能因为开盘价附近容易exact匹配，统计时注意样本不均

详见 [references/intraday-15m-analysis-design.md](references/intraday-15m-analysis-design.md)
