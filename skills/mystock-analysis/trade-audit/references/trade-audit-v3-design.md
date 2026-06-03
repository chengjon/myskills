# 交易复盘审计方案 V3.0（已实施完成）

> 状态：**V3改造12步全部实施完成(2026-06-03)**，TdxQuant确认为主数据源
> 设计日期：2026-06-02
> 审核通过日期：2026-06-03
> 实施完成日期：2026-06-03
> 方案文件：`mynotes/学习材料/复盘方法/review_generator_改造方案V3.md`（Obsidian）
> 终版基准：`mynotes/学习材料/复盘方法/合并后的终版方案.md`

## V2.0 → V3.0 核心变化

| 项目 | V2.0 | V3.0 |
|------|------|------|
| 评分维度 | 5维度(entry/exit/risk/discipline/emotion) | **4维度10分制**(entry3+exit3+discipline2+risk2) |
| 评分分值 | 每维0-5分，加权总分0-5 | 每维独立打分，总分0-10 |
| 事后验证 | T+5/10 | **T+5/10/20/60** 四档 |
| 卖出判定 | 8种退出类型 | **sell_verdict**(correct/missed/early/normal) |
| 表结构 | 60+字段单表 | **trade_audit主表84字段8组 + trade_audit_signal辅助表 + audit_log表** |
| 配置热更新 | 无 | batch_audit()每次重新load_config() |
| 数据校验 | 无 | validate_audit_record()校验5必填字段 |
| 旧评分兼容 | N/A | @deprecated保留6个月过渡期 |

## 评分4维度10分制

### 入场评分 (entry_score, 0-3分)
- 3分：趋势+位置+行业+大盘4项全优
- 2分：3项优/1项中性
- 1分：2项及以下优
- 0分：强逆势或追高+抄底同时触发

### 卖出评分 (exit_score, 0-3分)
- 3分：目标达成/移动止盈触发
- 2分：逻辑失效/时间过期，卖出位置合理
- 1分：恐慌卖出/换仓，但未触发止损
- 0分：止损触发/违规卖出

### 纪律评分 (discipline_score, 0-2分)
- 2分：规则内操作(仓位+止损+顺势三指标全合规)
- 1分：轻违规(1项不合规)
- 0分：重违规(2+项不合规)

### 风控评分 (risk_score, 0-2分)
- 2分：单笔风险≤2% + 有止损 + ATR止损距离合理
- 1分：单项不合规
- 0分：无止损或单笔风险>5%

### sell_verdict 卖出判定

| 判定 | 条件 |
|------|------|
| correct | 止损触发/目标达成/移动止盈 → 卖出正确 |
| missed | 卖出后继续上涨>10% → 错失利润 |
| early | 盈利卖出但未到目标价/未触发移动止盈 → 过早 |
| normal | 其他情况 |

## 新增6个判定函数

1. `classify_quadrant()` — 四分法：rule_win/rule_lose/chaos_win/chaos_lose
2. `judge_trend_alignment()` — 顺势三分：with_trend/light_against/strong_against
3. `enhance_impulsive_detection()` — 冲动增强检测：连亏+感情股+黑名单
4. `check_blacklist_touch()` — 黑名单触碰检测
5. `determine_feedback_action()` — 6种反馈动作：blacklist/observe/exclude/refine/maintain/escalate
6. `enumerate_errors()` — 错误枚举：收集所有违规项用于教训库

## trade_audit 表结构（84字段8组）

### A: 基础信息 (16字段)
同V2.0 A01-A16

### B: 入场环境 (18字段)
同V2.0 B01-B18

### C: 操作定性 (7字段)
同V2.0 C01-C07

### D: 仓位风控 (11字段)
同V2.0 D01-D11

### E: 卖出审计 (10字段)
同V2.0 E01-E10 + 新增 sell_verdict

### F: 事后验证 (14字段)
V2.0 的 F01-F14，新增 T+20/60 四档验证

### G: 情绪纪律 (8字段)
同V2.0 G01-G08

### H: 综合评分 (8字段)
更新为4维度10分制，新增 sell_verdict + feedback_action

## trade_audit_signal 辅助表

存储技术信号快照（买入日MA/MACD/RSI/BOLL/ATR/量比原始值），避免主表过宽。

## audit_log 表

记录批量审计运行情况：
- run_id, run_time, total_trades, new_trades, skipped_trades
- avg_score, grade_distribution, error_count

## 用户审核批准的决策

### 12步骤（全部批准）
1. MySQL建表 trade_audit + trade_audit_signal + audit_log
2. review_config.yaml 扩展V3配置
3. 6个新判定函数实现
4. validate_audit_record() 数据校验
5. adapt_fifo_to_audit() FIFO适配层
6. batch_audit() 批量审计主函数
7. sell_verdict + feedback_action 逻辑
8. T+20/60事后验证扩展
9. Obsidian审计报告模板
10. CLI子命令 `hermes review audit`
11. @deprecated旧评分函数保留
12. 集成测试+数据校验

### 5个决策点（全部回答）
1. 旧评分保留+@deprecated，6个月过渡期
2. 旧复盘卡不迁移，新旧共存，template_version='v3'参数控制
3. FIFO对接用adapt_fifo_to_audit()适配层
4. batch_audit增量模式，uk_trade唯一键去重，force=False默认跳过
5. T+60分两种：历史→立即算全；新交易→先写T+5/10/20，T+60留NULL后续cron补

### 4个额外建议（全部采纳）
1. validate_audit_record()校验5个必填字段(stock_code/buy_date/sell_date/buy_price/sell_price)
2. audit_log表记录批量审计运行情况
3. 配置热更新：batch_audit()每次重新load_config()
4. CLI子命令（步骤10）

## 实施优先级

| 优先级 | 步骤 | 说明 |
|--------|------|------|
| P0 | 步骤1+11+4 | 建表+旧评分兼容+数据校验（无依赖可先行） |
| P1 | 步骤2+3+7 | 配置+6判定函数+sell_verdict（核心逻辑） |
| P2 | 步骤5+6+8+9 | FIFO适配+批量审计+T+20/60+OB模板 |
| P3 | 步骤10+12 | CLI子命令+集成测试 |

## 阻塞项（已全部解除）

TdxQuant数据层3个P0阻塞项已于2026-06-03确认解除：
1. ✅ `formula_zb()`两步调用已验证：先`formula_set_data_info()`设数据，再`formula_zb(name,arg,xsflag)`取结果，返回dict key=Value.MA1等 value=list[str]
2. ✅ 2015年至今日线已下载完成
3. ✅ WSL调用方式：`/mnt/c/.../python.exe script.py` 直接调Windows Python

详见 `references/tdxquant-data-requirements.md`

## 实施记录

### 文件变更

| 文件 | 变更 | 说明 |
|------|------|------|
| scripts/trade_audit_sql.py | 新增615行 | 3张表93列MySQL存储层+CRUD+校验 |
| scripts/tdxquant_adapter.py | 新增308行 | WSL→Windows Python TdxQuant桥接层 |
| scripts/review_generator.py | 1690→2780行 | +15个V3函数(audit_score/四分法/sell_verdict/batch_audit等) |
| scripts/fetch_market_data.py | 小改 | fetch_post_validation支持days_list+sell_price |
| config/review_config.yaml | 143→237行 | V3全配置段(46项) |

### MySQL表验证

```
trade_audit: 93列, 8组(A基础16+B入场18+C定性7+D仓位9+E卖出12+F事后8+G情绪8+H评分6)+feedback_action
trade_audit_signal: 审计信号辅助表
audit_log: 批量审计运行日志表
uk_trade: UNIQUE(account,stock_code,buy_date,sell_date,sell_shares) 增量去重
```

### CLI验证

```
python review_generator.py audit --help       # 批量审计
python review_generator.py audit-single --help # 单笔审计
python review_generator.py score --v3          # V3 10分制评分
python review_generator.py draft --v3          # V3模板复盘卡
```
