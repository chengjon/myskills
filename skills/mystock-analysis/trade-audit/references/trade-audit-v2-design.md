# 交易复盘审计方案 V2.0

> 状态：待用户审核批准（4个决策点）。批准后方可实施编码。
> 设计日期：2026-06-02

## 设计目标

在现有复盘评分引擎(6+5维度)基础上，增加：
1. **四分法分类**：规则内/规则外 × 盈/亏，替代简单"有无交易计划"二元判定
2. **顺势分级**：顺势/轻逆势/强逆势，量化趋势顺逆程度
3. **仓位风控审计**：ATR止损距离 + 仓位合规性 + 单笔风险占比
4. **情绪检测**：连亏后冲动、感情股、黑名单触碰
5. **事后验证扩展**：5/10/20/60日四档验证
6. **8种卖出退出类型**：对标卖出规则§6
7. **反馈闭环**：blacklist/observe/exclude等6种后续行动

## 数据来源

V2.0基于已入库的228笔FIFO配对交易（平安普通148笔+两融80笔），以及1000w体系11份核心文档。

### 1000w体系文档（规则源）

| 文档 | 关键规则 | 对审计维度的影响 |
|------|----------|-----------------|
| 投资原则.md | 5大原则（纪律>策略>分析） | 纪律维度评分基准 |
| 买入卖出规则.md | 6节买入+6节卖出+6种退出 | 入场/卖出审计标准 |
| 交易闭环状态机.md | 9阶段闭环 | 操作定性+流程合规 |
| 仓位管理规则.md | ATR+固定风险双模式 | 仓位风控审计核心 |
| 投资禁忌与黑名单.md | 7条禁忌+黑名单机制 | 情绪检测+黑名单触碰 |
| 投资策略库.md | 4种投资策略定义 | 策略匹配判定 |
| 选股策略库.md | 5种选股策略定义 | 选股逻辑溯源 |
| ATR原理.md | ATR计算+应用方法 | ATR止损距离审计 |
| 规则校验矩阵.md | 9阶段×规则映射表 | 全流程规则合规 |
| V1.0数据模型.md | 32张表结构 | trade_audit表设计参考 |
| 交易计划表单字段.md | 计划卡必填字段 | 交易计划完整性审计 |

文档路径：`/mnt/c/Users/John Cheng/Documents/Obsidian Vault/mynotes/学习材料/`

## trade_audit 表结构（60+字段）

### A: 基础信息 (A01-A16)

| 字段 | 类型 | 说明 |
|------|------|------|
| A01 id | INT AUTO_INCREMENT | 主键 |
| A02 trade_pair_id | VARCHAR(32) | FIFO配对唯一ID |
| A03 account | ENUM('normal','margin') | 账户类型 |
| A04 stock_code | VARCHAR(10) | 股票代码 |
| A05 stock_name | VARCHAR(20) | 股票名称 |
| A06 buy_date | DATE | 买入日期 |
| A07 buy_price | DECIMAL(10,3) | 买入价格 |
| A08 buy_qty | INT | 买入数量 |
| A09 buy_abstract | VARCHAR(50) | 买入摘要 |
| A10 sell_date | DATE | 卖出日期 |
| A11 sell_price | DECIMAL(10,3) | 卖出价格 |
| A12 sell_qty | INT | 卖出数量 |
| A13 sell_abstract | VARCHAR(50) | 卖出摘要 |
| A14 holding_days | INT | 持仓天数 |
| A15 realized_pnl | DECIMAL(12,2) | 已实现盈亏 |
| A16 pnl_pct | DECIMAL(8,4) | 盈亏比例 |

### B: 入场环境 (B01-B18)

| 字段 | 类型 | 说明 |
|------|------|------|
| B01 buy_ma5 | DECIMAL(10,3) | 买入日MA5 |
| B02 buy_ma20 | DECIMAL(10,3) | 买入日MA20 |
| B03 buy_ma60 | DECIMAL(10,3) | 买入日MA60(可选) |
| B04 ma_alignment | VARCHAR(10) | 均线排列(multi/short/tangle) |
| B05 macd_signal | VARCHAR(10) | MACD信号(golden/death/divergence) |
| B06 rsi_value | DECIMAL(6,2) | RSI(14)值 |
| B07 boll_position | VARCHAR(10) | BOLL位置(upper/mid/lower) |
| B08 boll_direction | VARCHAR(10) | BOLL开口(expanding/squeezing) |
| B09 atr_value | DECIMAL(10,3) | ATR(14)值 |
| B10 buy_volume_ratio | DECIMAL(6,2) | 买入日量比 |
| B11 sector_name | VARCHAR(20) | 所属行业 |
| B12 sector_rank | INT | 行业涨幅排名 |
| B13 sector_change | DECIMAL(6,2) | 行业涨跌幅 |
| B14 market_sh_change | DECIMAL(6,2) | 上证涨跌幅 |
| B15 market_sz_change | DECIMAL(6,2) | 深证涨跌幅 |
| B16 market_cy_change | DECIMAL(6,2) | 创业板涨跌幅 |
| B17 market_sentiment | VARCHAR(10) | 市场情绪(up/down/neutral) |
| B18 index_dist_ma20 | DECIMAL(6,2) | 指数偏离MA20% |

### C: 操作定性 (C01-C07)

| 字段 | 类型 | 说明 |
|------|------|------|
| C01 trade_category | VARCHAR(20) | 四分法: rule_win/rule_lose/chaos_win/chaos_lose |
| C02 trend_alignment | VARCHAR(10) | 顺势分级: with_trend/light_against/strong_against |
| C03 has_plan | BOOLEAN | 有无交易计划 |
| C04 strategy_type | VARCHAR(20) | 策略类型(对应投资策略库) |
| C05 entry_mode | VARCHAR(20) | 入场模式(突破/回调/抄底/追高) |
| C06 is_chase_high | BOOLEAN | 是否追高 |
| C07 is_bottom_fishing | BOOLEAN | 是否抄底 |

### D: 仓位风控 (D01-D11)

| 字段 | 类型 | 说明 |
|------|------|------|
| D01 position_pct | DECIMAL(6,2) | 仓位占比% |
| D02 stop_price | DECIMAL(10,3) | 止损价(0=无) |
| D03 stop_distance_pct | DECIMAL(6,2) | 止损距离% |
| D04 atr_stop_distance | DECIMAL(6,2) | ATR止损距离% |
| D05 atr_stop_price | DECIMAL(10,3) | ATR建议止损价 |
| D06 single_risk_pct | DECIMAL(6,2) | 单笔风险占总资金% |
| D07 is_over_position | BOOLEAN | 是否超仓 |
| D08 is_no_stop | BOOLEAN | 是否无止损 |
| D09 is_overnight_heavy | BOOLEAN | 是否隔夜重仓 |
| D10 is_contra_trend_heavy | BOOLEAN | 是否逆势重仓 |
| D11 force_review | BOOLEAN | 是否触发强制复盘 |

### E: 卖出审计 (E01-E10)

| 字段 | 类型 | 说明 |
|------|------|------|
| E01 exit_type | VARCHAR(20) | 退出类型(8种,见下方) |
| E02 sell_reason | TEXT | 卖出原因描述 |
| E03 hold_max_profit_pct | DECIMAL(6,2) | 持仓最大浮盈% |
| E04 hold_max_loss_pct | DECIMAL(6,2) | 持仓最大浮亏% |
| E05 profit_unrealized_pct | DECIMAL(6,2) | 利润未兑现率% |
| E06 is_plan_target_hit | BOOLEAN | 是否触及计划目标价 |
| E07 is_stop_hit | BOOLEAN | 是否触发止损 |
| E08 sell_vs_ma5 | VARCHAR(10) | 卖出vs MA5位置 |
| E09 sell_vs_ma20 | VARCHAR(10) | 卖出vs MA20位置 |
| E10 sell_volume_ratio | DECIMAL(6,2) | 卖出日量比 |

### 8种卖出退出类型（对标卖出规则§6）

1. `target_hit` — 目标价达成
2. `stop_hit` — 止损触发
3. `trailing_stop` — 移动止盈触发
4. `logic_invalid` — 逻辑失效(基本面恶化)
5. `time_expire` — 时间过期(持仓超期)
6. `better_opportunity` — 更好机会换仓
7. `panic_sell` — 恐慌卖出(情绪驱动)
8. `rule_violation` — 违规卖出(未按规则)

### F: 事后验证 (F01-F14)

| 字段 | 类型 | 说明 |
|------|------|------|
| F01 post5_high | DECIMAL(10,3) | 5日最高价 |
| F02 post5_low | DECIMAL(10,3) | 5日最低价 |
| F03 post5_close | DECIMAL(10,3) | 5日收盘价 |
| F04 post5_change_pct | DECIMAL(6,2) | 5日涨跌幅% |
| F05 post10_high | DECIMAL(10,3) | 10日最高价 |
| F06 post10_low | DECIMAL(10,3) | 10日最低价 |
| F07 post10_close | DECIMAL(10,3) | 10日收盘价 |
| F08 post10_change_pct | DECIMAL(6,2) | 10日涨跌幅% |
| F09 post20_high | DECIMAL(10,3) | 20日最高价 |
| F10 post20_low | DECIMAL(10,3) | 20日最低价 |
| F11 post20_change_pct | DECIMAL(6,2) | 20日涨跌幅% |
| F12 post60_high | DECIMAL(10,3) | 60日最高价(可选) |
| F13 post60_low | DECIMAL(10,3) | 60日最低价(可选) |
| F14 post60_change_pct | DECIMAL(6,2) | 60日涨跌幅%(可选) |

### G: 情绪纪律 (G01-G08)

| 字段 | 类型 | 说明 |
|------|------|------|
| G01 consecutive_losses | INT | 买入前连亏笔数 |
| G02 is_impulsive | BOOLEAN | 是否冲动交易 |
| G03 is_emotional_stock | BOOLEAN | 是否感情股(反复交易) |
| G04 blacklist_action | VARCHAR(20) | 黑名单动作(none/observe/exclude/blacklist) |
| G05 discipline_violation | VARCHAR(50) | 纪律违规描述 |
| G06 is_rule_violation | BOOLEAN | 是否违反交易规则 |
| G07 violation_details | TEXT | 违规详情 |
| G08 calm_mode_triggered | BOOLEAN | 是否触发冷静模式 |

### H: 综合评分 (H01-H08)

| 字段 | 类型 | 说明 |
|------|------|------|
| H01 entry_score | DECIMAL(4,1) | 入场评分(0-5, 权重0.25) |
| H02 exit_score | DECIMAL(4,1) | 卖出评分(0-5, 权重0.25) |
| H03 risk_score | DECIMAL(4,1) | 风控评分(0-5, 权重0.20) |
| H04 discipline_score | DECIMAL(4,1) | 纪律评分(0-5, 权重0.15) |
| H05 emotion_score | DECIMAL(4,1) | 情绪评分(0-5, 权重0.15) |
| H06 total_score | DECIMAL(5,2) | 加权总分(0-5) |
| H07 grade | VARCHAR(5) | 等级(A/B/C/D) |
| H08 feedback_action | VARCHAR(20) | 反馈动作(6种) |

### 6种反馈动作

1. `blacklist` — 加入黑名单，禁止交易
2. `observe` — 观察名单，限制仓位
3. `exclude` — 排除策略，不再使用
4. `refine` — 精进策略，优化参数
5. `maintain` — 维持策略，继续执行
6. `escalate` — 升级关注，增加验证频率

## 评分权重设计

### V2.0 五维度（建议值，待用户确认）

| 维度 | 权重 | 说明 |
|------|------|------|
| 入场(H01) | 0.25 | 替代原趋势+位置+行业+大盘4维度 |
| 卖出(H02) | 0.25 | 新增，审计卖出质量 |
| 风控(H03) | 0.20 | 替代原风控维度，增加ATR+仓位 |
| 纪律(H04) | 0.15 | 替代原纪律维度，增加情绪检测 |
| 情绪(H05) | 0.15 | 新增，连亏/冲动/感情股/黑名单 |

### 与V1.0的对比

| 维度 | V1.0(事前6维+事后5维) | V2.0(5维度统一) |
|------|----------------------|----------------|
| 趋势 | 事前独立维度 | 合并入场 |
| 位置 | 事前独立维度 | 合并入场 |
| 行业 | 事前独立维度 | 合并入场 |
| 大盘 | 事前独立维度 | 合并入场 |
| 风控 | 事前1维度 | 独立维度(扩大) |
| 纪律 | 事前1维度 | 独立维度(增加情绪) |
| 卖出 | 无 | 新增独立维度 |
| 情绪 | 无 | 新增独立维度 |
| 方向 | 事后独立维度 | 合并入场+卖出 |
| 时机 | 事后独立维度 | 合并入场 |
| 风控有效 | 事后独立维度 | 合并风控 |
| 空间 | 事后独立维度 | 合并卖出 |
| 持有质量 | 事后独立维度 | 合并卖出 |

## 四分法分类逻辑（待决策）

### 方案：仓位+止损+顺势三指标替代"交易计划"判定

历史交易无交易计划记录，无法直接判定"规则内/规则外"。替代方案：

| 指标 | 规则内 | 规则外 |
|------|--------|--------|
| 仓位 | ≤总资金×单笔上限(2%) | >2% |
| 止损 | 有明确止损价 | 无止损 |
| 顺势 | 顺势/轻逆势 | 强逆势 |

三指标全部符合 = 规则内，任一不符合 = 规则外。

四分法：
- `rule_win` — 规则内盈利（应复用）
- `rule_lose` — 规则内亏损（正常概率，保留策略）
- `chaos_win` — 规则外盈利（禁止复刻，危险盈利）
- `chaos_lose` — 规则外亏损（典型错误，录入教训库）

## 顺势三分法

| 级别 | 判定 | 说明 |
|------|------|------|
| with_trend | MA5>MA20>MA60 且 MACD金叉/红柱 | 顺势操作 |
| light_against | 均线缠绕 或 MACD死叉但趋势未确认 | 轻逆势，可接受 |
| strong_against | MA5<MA20<MA60 且 MACD死叉/绿柱 | 强逆势，需警惕 |

## 10个关键统计查询

```sql
-- 1. 四分法分布
SELECT trade_category, COUNT(*), AVG(realized_pnl), AVG(pnl_pct) FROM trade_audit GROUP BY trade_category;

-- 2. 顺势 vs 逆势胜率
SELECT trend_alignment, COUNT(*), SUM(realized_pnl>0)/COUNT(*) AS win_rate, AVG(pnl_pct) FROM trade_audit GROUP BY trend_alignment;

-- 3. ATR止损距离分布
SELECT CASE WHEN atr_stop_distance BETWEEN 0 AND 3 THEN '0-3%' WHEN BETWEEN 3 AND 5 THEN '3-5%' ELSE '>5%' END AS dist_bucket, COUNT(*), AVG(pnl_pct) FROM trade_audit GROUP BY dist_bucket;

-- 4. 情绪交易占比
SELECT is_impulsive, COUNT(*), AVG(pnl_pct) FROM trade_audit GROUP BY is_impulsive;

-- 5. 卖出退出类型分析
SELECT exit_type, COUNT(*), AVG(pnl_pct), AVG(profit_unrealized_pct) FROM trade_audit GROUP BY exit_type;

-- 6. 仓位合规 vs 不合规
SELECT is_over_position, COUNT(*), AVG(pnl_pct) FROM trade_audit GROUP BY is_over_position;

-- 7. 黑名单/观察名单触发
SELECT blacklist_action, COUNT(*), GROUP_CONCAT(DISTINCT stock_name) FROM trade_audit WHERE blacklist_action != 'none' GROUP BY blacklist_action;

-- 8. 事后验证：N日极值统计
SELECT AVG(post5_change_pct), AVG(post10_change_pct), AVG(post20_change_pct), AVG(post60_change_pct) FROM trade_audit;

-- 9. 连亏后操作质量
SELECT consecutive_losses, COUNT(*), AVG(pnl_pct), SUM(realized_pnl>0)/COUNT(*) AS win_rate FROM trade_audit WHERE consecutive_losses > 0 GROUP BY consecutive_losses;

-- 10. 综合评分等级分布
SELECT grade, COUNT(*), AVG(realized_pnl), AVG(pnl_pct) FROM trade_audit GROUP BY grade;
```

## 待决策点（4个）

1. **四分法判定逻辑**：用仓位+止损+顺势三指标替代"交易计划"判定？（推荐：是，历史数据无计划记录）
2. **60日事后验证**：是否需要？（推荐：可选字段，默认不填，需额外K线数据）
3. **表结构增减**：60+字段是否过多？是否需要拆表？（推荐：单表，字段虽多但审计场景用全表扫描为主）
4. **评分权重调整**：入场0.25+卖出0.25+风控0.20+纪律0.15+情绪0.15？（推荐：可配置化，初始用此值）

## 实施路径（批准后）

1. 创建 `scripts/trade_audit.py` — 从MySQL读FIFO配对，填充B-G维度，写入trade_audit表
2. 扩展 `review_generator.py` — H维度评分逻辑 + 四分法分类 + 反馈动作
3. MySQL建表 `trade_audit` — 60+字段
4. review_config.yaml 新增审计相关配置
5. Obsidian输出：审计报告模板
