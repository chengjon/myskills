---
title: V4升级方案 — 6维15分科学复盘体系
date: 2026-06-04 18:00
updated: 2026-06-04 19:30
status: 已更新（整合审核意见）
scope: 2026年前363笔交易全面复盘
tags: [复盘, 评分体系, V4, 科学分类, 可计量]
---

# V4升级方案 — 6维15分科学复盘体系

> 目标：对2026年前全部363笔交易进行系统性复盘，实现科学分类、科学标准、科学评判、可计量。

## 一、现有问题诊断（V3 4维10分制）

从363笔已审计数据发现以下结构性缺陷：

### 1.1 评分数据

| 指标 | 数值 |
|------|------|
| 总交易笔数 | 363笔 |
| 时间跨度 | 2021(3) / 2022(14) / 2023(36) / 2024(49) / 2025(261) |
| 平均持仓天数 | 14.2天 |
| 总已实现盈亏 | -100,929.74元 |
| 胜率 | 175/363 = 48.2% |
| 评分均值 | 3.63（满分10） |

### 1.2 V3结构性缺陷

| 问题 | 现状 | 根因 |
|------|------|------|
| discipline_score恒=1 | 363笔全部1分 | 历史交易无计划记录，默认判"轻违规" |
| risk_control_score恒=0 | 363笔全部0分 | 历史交易无止损记录，默认判"无止损" |
| 四分法只分两类 | 规则外盈利175 + 规则外亏损188 | stop_loss_set/position_rule全部判False |
| total_score集中在2-5分 | 62%是4分，区分度极差 | 4维中2维是固定值 |
| sell_verdict不完整 | 无late_stop/perfect_stop | calc_sell_verdict只有6种判定 |
| good_profit含50笔亏损 | 违反语义 | 判定逻辑有bug |

**总结**：V3是"合规审计"思路——用"有无计划/止损"判定规则内外。历史交易无此记录，导致两个维度形同虚设。V4需要转向"行为画像"思路——用市场数据反推决策质量。

## 二、V4评分体系设计（6维15分）

### 2.1 六维度定义

| 维度 | 满分 | 评判标准 | 数据来源 |
|------|------|---------|----------|
| **入场时机 (entry_timing)** | 3 | BOLL位置 + 趋势方向 + 追高检测 | 日线BOLL + 15分BOLL + 开盘价偏离 |
| **入场质量 (entry_quality)** | 3 | 买后1小时表现 + K线内位置 + 量比 | 15分K线 + 成交量 |
| **卖出时机 (exit_timing)** | 3 | sell_verdict + 事后涨跌 + 持仓天数合理性 | post5/10/20 + hold_days |
| **风控执行 (risk_mgmt)** | 2 | 最大回撤比 + 单笔亏损幅度 + 仓位集中度 | max_price_hold + pnl_rate + position_ratio |
| **行为纪律 (behavior)** | 2 | 冲动指标 + 连亏报复 + 摊平检测 | is_impulsive + 同日多笔 + 买入价递减 |
| **交易效率 (efficiency)** | 2 | 盈亏比 + 持仓效率(日均收益) + 机会成本 | realized_pnl / max_drawdown |

### 2.2 各维度评分细则

#### 入场时机 (0-3分)

采用3项计数法（每项1分，满3分；追高+逆势惩罚归零）：

| 条件 | 加分 |
|------|------|
| BOLL中低位(<50%) | +1 |
| 趋势向上(MOM10>0) | +1 |
| 未追高(buy_price / open - 1 < 0.03) | +1 |
| **惩罚：追高且趋势向下** | **直接0分** |

#### 入场质量 (0-3分)

采用3项计数法：

| 条件 | 加分 |
|------|------|
| 买后1h上涨(after_1h_return > 0.5%) | +1 |
| K线内位置良好(candle_position < 0.3，靠近低点买入) | +1 |
| 量比正常(volume_ratio > 1.0) | +1 |
| **惩罚：买后1h大跌(跌幅>2%)** | **直接0分** |

> 无15分K线数据时（71笔daily_exact），按日线当天振幅和位置评估：
> - 有数据时：after_1h_return 用次日开盘vs买入价近似，candle_position 用日线 (buy-low)/(high-low)
> - 无数据时：满分降为2分

> candle_position = (buy_price - day_low) / (day_high - day_low + 1e-6)
> 值<0.3表示买在K线下方(接近最低价)=好位置

#### 卖出时机 (0-3分)

基于 sell_verdict_v4 映射得分（verdict定义见 3.2 节）：

| verdict | 得分 | 说明 |
|---------|------|------|
| perfect_stop | 3 | 卖在最低点附近（纪律止损） |
| discipline_sell | 3 | 纪律卖点（止盈/时间止损） |
| nice_catch | 3 | 卖在最高点附近（精准卖出） |
| good_profit | 2 | 盈利且卖后跌（正确止盈） |
| normal | 1 | 其他情况 |
| late_stop | 0 | 亏损且卖后继续跌（止损太晚） |
| panic_sell | 0 | 恐慌抛售 |
| missed_profit | 0 | 盈利但卖后大涨（卖早了） |
| unknown | 1 | 数据不足（中性） |

#### 风控执行 (0-2分)

3项计数法，满足几项得几分（0-2分，3项全满足=2分）：

| 条件 | 判定 |
|------|------|
| intra_drawdown < 5% | 回撤可控 |
| pnl_rate > -8% (亏损时) | 单笔亏损不过大 |
| position_ratio ≤ 15% | 仓位合规 |

> 注：3项全满足=2分，满足2项=1分，满足0-1项=0分

#### 行为纪律 (0-2分)

基于行为标签数量（见 3.3 节定义）：

| 标签数 | 得分 |
|--------|------|
| 0个负面标签 | 2 |
| 1个负面标签 | 1 |
| ≥2个负面标签 | 0 |

#### 交易效率 (0-2分)

分盈利/亏损两种情况：

**盈利交易**：
| 条件 | 得分 |
|------|------|
| 盈亏比合理(max_drawdown<3%且pnl_rate>5%) + 持仓效率>0.2%/天 | 2 |
| 满足其中1项 | 1 |
| 都不满足 | 0 |

**亏损交易**：
| 条件 | 得分 |
|------|------|
| 亏损幅度<3% 或 max_drawdown<5% | 1 |
| 其他 | 0 |

> 亏损交易最高1分（虽亏但有效率），不会与盈利交易同分。

## 三、科学分类标准

### 3.1 六级分类法（替代四分法）

| 等级 | 条件 | 含义 | 占比预期 | 后续动作 |
|------|------|------|---------|---------|
| **A 精华交易** | 总分≥12 + 盈利 | 可复制的系统性盈利 | ~5% | 总结模式，写入策略库 |
| **B 合格交易** | 总分≥9 + 盈利 | 决策正确，小瑕疵 | ~15% | 保持，优化细节 |
| **C 运气盈利** | 总分<9 + 盈利 | 结果好但过程有问题 | ~15% | 警惕，不复制 |
| **D 正常亏损** | 总分≥9 + 亏损 | 决策对但市场不给力 | ~15% | 正常概率，不调整 |
| **E 可避免亏损** | 总分6-8 + 亏损 | 有改进空间 | ~25% | 针对性改进 |
| **F 致命错误** | 总分<6 + 亏损 | 需录入教训库 | ~25% | 录入教训库，设黑名单 |

#### 六级子分类（E/F级细分，便于定位改进方向）

| 等级 | 子类 | 典型特征 | 改进方向 |
|------|------|---------|---------|
| F 致命错误 | F1 入场灾难 | entry_timing + entry_quality 都≤1 | 改进入场规则 |
| | F2 风控崩溃 | risk_mgmt=0 且 亏损>10% | 加强止损纪律 |
| | F3 纪律崩塌 | behavior=0 且连亏≥3笔 | 控制情绪和频率 |
| E 可避免亏损 | E1 卖点问题 | exit_timing≤1，其他尚可 | 优化卖出策略 |
| | E2 风控瑕疵 | risk_mgmt=1，单笔亏5-10% | 缩小止损幅度 |

> 好处：统计时能看出"你是哪种亏"——入场问题、风控问题还是纪律问题，针对性改进。

**与V3四分法的映射**：

| V3 | V4 |
|----|-----|
| rule_win | → A + B + C（盈利交易按评分细分） |
| rule_lose | → D（正常亏损） |
| chaos_win | → C（运气盈利，需验证是运气还是能力） |
| chaos_lose | → E + F（亏损交易按严重程度细分） |

### 3.2 卖出判定升级为9种

按**互斥优先级**从高到低判定（只匹配第一个满足的条件）：

| 优先级 | verdict | 条件 | 语义 |
|--------|---------|------|------|
| 1 | **perfect_stop** | 亏损(pnl<0) 且 卖在5日最低点附近(sell ≤ post5_low × 1.01) | 纪律止损，卖在最低 |
| 2 | **panic_sell** | 亏损(pnl<0) 且 卖在5日最低点附近 且 post5_chg < -3% | 恐慌抛售，卖后继续暴跌 |
| 3 | **discipline_sell** | 盈利 且 (持仓≥20天 或 pnl_rate≥15%) | 纪律卖点：止盈/时间止损 |
| 4 | **good_profit** | 盈利 且 post5_chg < 0 | 卖后跌了=正确止盈 |
| 5 | **nice_catch** | 盈利 且 卖在5日最高点附近(sell ≥ post5_high × 0.99) | 精准卖出 |
| 6 | **late_stop** | 亏损 且 post5_chg < -3% | 止损太晚 |
| 7 | **missed_profit** | 盈利 且 post20_chg > 8% | 卖后大涨，错失利润 |
| 8 | **normal** | 其他 | 默认 |
| 9 | **unknown** | post5/post20 数据不足 | 无法判定 |

**互斥逻辑说明**：
- perfect_stop 与 panic_sell 区分：两者都"卖在最低"，但 panic_sell 要求卖后继续暴跌(chg5<-3%)，说明不是主动止损而是被动恐慌。优先判定 perfect_stop（更积极的解释）。
- discipline_sell 新增：解决"卖飞但合理"的问题——已经赚15%或持有20天以上，即使卖后继续涨也是纪律卖点，不算 missed_profit。

### 3.3 行为标签（可计量）

| 标签 | 计量方法 | 阈值配置 |
|------|---------|----------|
| 追高 | buy_price > open × (1 + threshold) | chase_high_threshold: 0.03 |
| 抄底 | buy_price < prev_close × (1 - threshold) **且** MOM10 < -5% | bottom_fishing_threshold: 0.03, bottom_trend_threshold: -5% |
| 冲动 | 按交易日期排序，最近N笔中连续亏损≥3笔 / 同日≥3笔 / ATR分位>90% | impulsive_v2 |
| 摊平 | 同股票第N笔买入价 < 第1笔买入价 | 自动检测 |
| 报复性交易 | 上一笔亏损 → 当日买入不同股票 | 自动检测 |
| 过早卖出 | sell_verdict_v4 = missed_profit | 自动标记 |
| 过晚止损 | sell_verdict_v4 = late_stop / panic_sell | 自动标记 |
| 重仓 | position_ratio > max_single_position | 15% |
| BOLL极端 | stk_boll_pctb < 10% 或 > 90% | 自动检测 |

**抄底标签的改进**（审核意见 1.2）：

原定义 buy_price < prev_close × 0.97 会在上升趋势的正常回调中误标为"抄底"。改进为**必须同时满足趋势下行**：

```python
is_real_bottom_fishing = (
    buy_price < prev_close * (1 - bottom_fishing_threshold)
    AND MOM10 < bottom_trend_threshold  # 近10日动量为负
)
```

这样上升趋势中的低吸不会被标为"抄底"，只有下跌趋势中接飞刀才标记。

**冲动标签中"连亏"的定义**（审核意见 2.3）：

明确为：**按交易日期排序，最近N笔交易中连续亏损≥3笔**。在代码中需维护按日期排序的交易序列，滑动窗口检测连亏。

每笔交易可有0-9个标签，存入 `behavior_tags` 字段（逗号分隔），可做统计分布。

## 四、可计量指标

每笔交易计算以下量化指标，全部存入MySQL：

### 4.1 单笔指标

| 指标 | 公式 | 用途 | 特殊处理 |
|------|------|------|---------|
| 风险调整收益 (risk_adjusted_return) | R = pnl_rate / max(intra_drawdown, 0.01) | 单笔风险效率 | 防除零：回撤<1%时用0.01 |
| 持仓效率 (hold_efficiency) | E = pnl_rate / hold_days | 日均收益率% | hold_days=0时返回NULL |
| 机会成本 (opportunity_cost) | OC = post20_chg - realized_pnl_rate | 持有vs卖出的差 | OC<0说明卖对了 |
| 持仓期内回撤 (intra_drawdown) | DD = 1 - sell_price / max_price_hold | 从浮盈最高到卖出的回撤 | 近似值（见下方说明） |

**intra_drawdown 计算精度说明**（审核意见 2.1）：

- `max_price_hold` 取持仓期间**日线 high 的最大值**
- `min_price` 取持仓期间**日线 low 的最小值**（当前已有此字段）
- 由于使用日线而非分钟线，此指标为**近似值**，可能低估实际日内最大回撤
- 数据源：TDX本地day文件（11034个文件，覆盖全部股票，2015-2026）
- 精度提升路径：若未来需要更精确数据，可用15分K线重新计算

### 4.2 系统级统计指标

| 指标 | 计算方法 | 用途 |
|------|---------|------|
| Wilson胜率CI | binom_confidence(wins, n, 0.95) | 小样本也可靠 |
| Cohen's d效应量 | (mean_A - mean_B) / pooled_std | A级vs F级行为差异显著性 |
| 盈亏比 | avg_win_amount / avg_loss_amount | 系统性优势，>2:1为健康 |
| 期望值 | win_rate × avg_win - (1-win_rate) × avg_loss | 正=长期盈利系统 |

### 4.3 统计可靠性约束（审核意见 3.1）

363笔交易按六级分类拆开后，A类可能只有~20笔，Wilson区间很宽：

- **报告中明确标注每个统计量的样本量**
- **样本量<30的类**：只做描述性统计，不做显著性检验
- **对比分析**：A+B 合并为"优质交易组"，E+F 合并为"问题交易组"，确保样本量≥50再做 Cohen's d

### 4.4 综合扣分来源分析 — shortfall_report（审核意见 3.2）

新增维度级扣分汇总，回答"我最大的短板是什么"：

| 维度 | 满分 | 实际均分 | 扣分 | 扣分率 |
|------|------|---------|------|--------|
| entry_timing | 3 | ? | ? | ?% |
| entry_quality | 3 | ? | ? | ?% |
| exit_timing | 3 | ? | ? | ?% |
| risk_mgmt | 2 | ? | ? | ?% |
| behavior | 2 | ? | ? | ?% |
| efficiency | 2 | ? | ? | ?% |

按扣分率降序排列，一眼看出最大亏损来源是入场时机不对还是风控崩塌。此表单独生成为 `shortfall_report` 部分。

## 五、MySQL字段扩展

```sql
-- V4新增字段（不删除V3字段）
ALTER TABLE trade_audit ADD COLUMN total_score_v4 TINYINT DEFAULT NULL COMMENT 'V4总分(0-15)';
ALTER TABLE trade_audit ADD COLUMN entry_timing_score TINYINT DEFAULT NULL COMMENT '入场时机(0-3)';
ALTER TABLE trade_audit ADD COLUMN entry_quality_score TINYINT DEFAULT NULL COMMENT '入场质量(0-3)';
ALTER TABLE trade_audit ADD COLUMN exit_timing_score TINYINT DEFAULT NULL COMMENT '卖出时机(0-3)';
ALTER TABLE trade_audit ADD COLUMN risk_mgmt_score TINYINT DEFAULT NULL COMMENT '风控执行(0-2)';
ALTER TABLE trade_audit ADD COLUMN behavior_score TINYINT DEFAULT NULL COMMENT '行为纪律(0-2)';
ALTER TABLE trade_audit ADD COLUMN efficiency_score TINYINT DEFAULT NULL COMMENT '交易效率(0-2)';
ALTER TABLE trade_audit ADD COLUMN grade_v4 VARCHAR(2) DEFAULT NULL COMMENT '六级分类(A-F)';
ALTER TABLE trade_audit ADD COLUMN grade_sub VARCHAR(3) DEFAULT NULL COMMENT '子分类(F1/F2/F3/E1/E2)';
ALTER TABLE trade_audit ADD COLUMN sell_verdict_v4 VARCHAR(20) DEFAULT NULL COMMENT 'V4卖出判定(9种)';
ALTER TABLE trade_audit ADD COLUMN risk_adjusted_return DECIMAL(10,4) DEFAULT NULL COMMENT '风险调整收益';
ALTER TABLE trade_audit ADD COLUMN hold_efficiency DECIMAL(10,4) DEFAULT NULL COMMENT '持仓效率';
ALTER TABLE trade_audit ADD COLUMN opportunity_cost DECIMAL(10,4) DEFAULT NULL COMMENT '机会成本';
ALTER TABLE trade_audit ADD COLUMN intra_drawdown DECIMAL(10,4) DEFAULT NULL COMMENT '持仓期内回撤(日线近似)';
ALTER TABLE trade_audit ADD COLUMN behavior_tags VARCHAR(200) DEFAULT NULL COMMENT '行为标签(逗号分隔)';
```

共新增 **16** 个字段（原方案15个 + grade_sub）。

## 六、实施计划

| 步骤 | 内容 | 产出 | 预估 |
|------|------|------|------|
| 1 | ALTER TABLE 新增16个V4字段 | MySQL字段就绪 | 1分钟 |
| 2 | 编写 `audit_v4_scorer.py` 评分引擎 | 6维评分+9种verdict+行为标签+量化指标 | ~500行，1-2小时 |
| 3 | 更新 `review_config.yaml` 增加V4配置段 | 阈值可配置 | ~60行 |
| 4 | **先跑50笔验证** — 随机抽50笔检查verdict互斥和评分合理性 | 验证脚本正确性 | 5分钟 |
| 5 | 363笔 `--force --v4` 全量重算 | V4数据入库 | 5-10分钟 |
| 6 | 生成六级分类报告 + shortfall_report + 行为标签统计 + 量化指标分析 | Obsidian报告（详细版+聚合版） | 10分钟 |
| 7 | F级交易自动生成 `教训库.md` 条目（固定格式，方便积累） | Obsidian教训库 | 5分钟 |
| 8 | 更新 trade-audit SKILL.md 文档 | 文档同步 | 10分钟 |

### 实施细节

- **脚本统一用 `--version v3/v4` 控制**（不搞 v3/v4 双脚本）
- **YAML配置全量可调**：追高3%、抄底3%（含趋势阈值-5%）、重仓15%等
- **报告双版本输出**：详细版（每笔交易V4评分） + 聚合版（按等级/标签统计）
- **教训库格式固定**：`教训库.md` 中每条格式 = 日期 + 股票 + 错误类型 + 亏损金额 + 改进方向

## 七、与V3的关系

| 方面 | V3 | V4 |
|------|-----|-----|
| 评分 | 4维10分 | 6维15分 |
| 分类 | 四分法(规则内/外×盈/亏) | 六级法(A-F) + 子分类 |
| sell_verdict | 6种 | 9种（新增 discipline_sell） |
| 纪律判定 | 有无计划(历史交易无数据) | 行为标签(从交易数据推断) |
| 风控判定 | 有无止损(历史交易无数据) | 最大回撤+亏损幅度+仓位 |
| 量化指标 | 无 | 4项可计量指标 + shortfall_report |
| 行为分析 | 冲动检测(弱) | 9种行为标签(抄底含趋势判断) |
| 数据兼容 | trade_audit现有字段保留 | 新增16字段，V3字段不动 |

**兼容策略**：
- V3的 `total_score` 保留为 `total_score_v3`
- V4写入新字段 `total_score_v4`
- 四分法保留为 `trade_category`，六级法为 `grade_v4`
- 所有脚本支持 `--version v3` / `--version v4` 切换，默认V4

## 八、预期产出

完成后的分析报告包含：

1. **六级分类分布** — A/B/C/D/E/F各多少笔，占比多少
2. **E/F子分类分布** — 致命错误是入场问题、风控问题还是纪律问题
3. **按年度趋势** — 评分是否逐年改善
4. **行为标签热力图** — 哪些错误最常见
5. **卖出判定分布** — 9种verdict各多少笔
6. **shortfall_report** — 六维度扣分率排序，一眼看出最大短板
7. **量化指标统计** — Wilson CI胜率、Cohen's d差异、盈亏比、期望值
8. **针对性改进建议** — 按最常见错误给Top 3改进方向
9. **教训库候选** — F级交易清单（固定格式），可直接录入

## 九、审核意见整合记录

以下修改已整合进本方案：

| # | 审核意见 | 修改位置 |
|---|---------|---------|
| 1.1 | sell_verdict互斥优先级 + 新增 discipline_sell | 3.2节：8种→9种，优先级表 |
| 1.2 | 抄底标签需结合趋势判断 | 3.3节：加 MOM10 < -5% 条件 |
| 1.3 | E/F级增加子分类 | 3.1节：F1/F2/F3/E1/E2 |
| 2.1 | intra_drawdown精度说明 | 4.1节：标注日线近似值 |
| 2.2 | risk_adjusted_return 防除零 | 4.1节：max(drawdown, 0.01) |
| 2.3 | 连亏窗口定义 | 3.3节：按交易日期排序滑动窗口 |
| 3.1 | 统计可靠性约束 | 4.3节：样本量<30只做描述统计 |
| 3.2 | shortfall_report | 4.4节：维度级扣分率排序 |
| 4   | 实施优化（50笔先行/双版本报告/教训库/脚本统一） | 6节实施计划 |

---

## 审核意见

> 请在下方追加审核意见（✅/❌+评论）
