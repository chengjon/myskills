# 交易复盘审计引擎 V3 实现审查报告

审查日期：2026-06-03

审查对象：

- 需求文档：`/mnt/c/Users/John Cheng/Documents/Obsidian Vault/mynotes/学习材料/复盘方法/review_generator_改造方案V3.md`
- 功能说明：`/mnt/c/Users/John Cheng/Documents/Obsidian Vault/mynotes/学习材料/复盘方法/V3功能说明.md`
- 实现目录：`/root/.hermes/skills/mystock-analysis`

## 总结结论

V3 功能已经完成了主体框架和大部分核心判定/评分函数，但还不能判定为“完全实现”。当前状态更准确地说是：

- V3 核心函数、V3 CLI 入口、MySQL 主表/信号表/日志表、V3 配置段、事后验证多窗口函数接口已经存在。
- `insert_audit_from_trade()` 在模拟 MySQL 和行情接口后可以组装 91 个审计字段并调用写入，说明主编排链路具备可运行骨架。
- 批量审计的数据来源仍未闭环，`batch_audit()` 读取的是卖出流水简化记录，缺少 FIFO 买卖配对、真实买入价、真实盈亏和持仓天数。
- V3 功能说明中列出的 8 个“已知待完善项”多数仍然存在，其中 FIFO 适配、TdxQuant 主数据源切换、T+20/T+60 补数据闭环是影响完整可用性的关键缺口。
- 还发现一个额外实现缺口：`insert_audit_from_trade()` 请求了 `[5, 10, 20, 60]` 事后验证，但写入 record 时 `post60_chg` 被硬编码为 `None`，即使数据源返回了 `post60.chg` 也不会入库。

## 已实现部分

### 1. V3 文件与入口基本到位

证据：

- `scripts/review_generator.py` 存在，约 2821 行，与功能说明中“1690→2820 行”的描述基本一致。
- `scripts/fetch_market_data.py` 存在，约 694 行，与功能说明中“~660→693 行”的描述基本一致。
- `config/review_config.yaml` 存在，约 237 行，与功能说明中“143→236 行”的描述基本一致。
- `scripts/trade_audit_sql.py` 与 `scripts/tdxquant_adapter.py` 均存在。

### 2. V3 核心判定函数已实现

`scripts/review_generator.py` 中存在以下函数：

- `classify_stk_trend()`
- `classify_mkt_trend()`
- `calc_trade_direction()`
- `get_trade_category()`
- `detect_impulsive_v2()`
- `check_blacklist()`
- `infer_mistake_category()`
- `calc_feedback_action()`
- `audit_score()`
- `calc_sell_verdict()`
- `insert_audit_from_trade()`
- `batch_audit()`

验证结果：

- `python -m py_compile scripts/review_generator.py scripts/fetch_market_data.py scripts/trade_audit_sql.py scripts/tdxquant_adapter.py` 无输出，语法编译通过。
- `python review_generator.py --help` 能展示 `{draft,update,daily,score,audit,audit-single}`。
- `python trade_audit_sql.py --help` 能展示 `{create,check,stats}`。
- `import review_generator`、`import trade_audit_sql` 均成功。
- 纯函数 smoke check 通过：`calc_trade_direction()`、`get_trade_category()`、`calc_feedback_action()`、`calc_sell_verdict()`、`audit_score()` 均能返回基本结果。

### 3. V3 MySQL 存储层已搭建

`scripts/trade_audit_sql.py` 中已实现：

- `trade_audit` 主表建表 SQL。
- `trade_audit_signal` 信号表建表 SQL。
- `audit_log` 审计日志表建表 SQL。
- `create_tables()` 幂等建表。
- `insert_audit()` 插入或更新审计记录。
- `insert_signals()` 插入入场信号。
- `query_stock_history_stats()` 查询黑名单/历史统计所需数据。
- `query_emotion_stats()` 查询冲动交易所需历史情绪指标。
- `trade_exists()` 增量去重检查。
- `update_post_validation()` 更新事后验证字段。

当前 `AUDIT_COLUMNS` 为 91 列，建表 SQL 主表不含 `id/created_at` 时对应 91 个可插入字段；模拟主编排时未发现 record 缺失列。

### 4. `insert_audit_from_trade()` 主编排骨架可运行

使用 monkeypatch 模拟：

- `trade_exists()`
- `insert_audit()`
- `insert_signals()`
- `query_emotion_stats()`
- `query_stock_history_stats()`
- `fetch_pre_snapshot()`
- `fetch_post_validation()`

结果：

- `insert_audit_from_trade()` 返回 `status=inserted`。
- 组装 record 字段数为 91。
- `AUDIT_COLUMNS` 中没有缺失字段。
- 能计算出 `trade_direction`、`trade_category`、`entry_score`、`exit_score`、`total_score`、`feedback_action` 等核心字段。

这说明 V3 编排不是只有函数壳，主体流程已能跑通。

## 未完全实现或需要修改的问题

### HIGH 1. 批量审计缺少 FIFO 买卖配对，`batch_audit()` 产出的交易记录不具备真实复盘价值

证据：

- 功能说明已明确列出：`FIFO适配层 adapt_fifo_to_audit()` 是 P1 待完善项，说明 `_fetch_completed_trades` 当前为简化版，`buy_date/买价/盈亏` 需从 `calc_pingan_pnl` 的 FIFO 结果填充。
- 代码中没有 `adapt_fifo_to_audit()` 定义。
- `scripts/review_generator.py` 的 `_fetch_completed_trades()` 只读取 `pingan_normal_trade` 与 `pingan_margin_trade` 的卖出流水。
- `_fetch_completed_trades()` 构造的交易 dict 中：
  - `buy_date` 是空字符串。
  - `buy_price` 是 `0`。
  - `buy_shares` 是 `0`。
  - `buy_amount` 是 `0`。
  - `hold_days` 是 `0`。
  - `realized_pnl` 是 `0`。
  - `pnl_rate` 是 `0`。
  - `_needs_fifo` 被标记为 `True`。

影响：

- 批量审计可能写入无效日期或被 MySQL `DATE NOT NULL` 阻断。
- 即使写入成功，盈亏、持仓天数、四分法、评分、错误归因都会失真。
- `audit` 命令目前不能作为真实批量复盘入口使用。

建议：

1. 在 `calc_pingan_pnl.py` 或新适配模块中产出标准 FIFO 配对结果。
2. 增加 `adapt_fifo_to_audit(fifo_result, account, source_table)`，至少填充：
   - `buy_date`
   - `buy_price`
   - `buy_shares`
   - `buy_amount`
   - `sell_date`
   - `sell_price`
   - `sell_shares`
   - `sell_amount`
   - `hold_days`
   - `realized_pnl`
   - `pnl_rate`
   - `total_fees`
3. `batch_audit()` 改为调用 FIFO 适配层，而不是直接把卖出流水伪造成完整交易。
4. 在 FIFO 不可用时，不应静默生成审计；应返回明确错误或跳过并记录原因。

### HIGH 2. `post60_chg` 在主编排中被硬编码为 `None`

证据：

- `insert_audit_from_trade()` 调用 `fetch_post_validation(..., days_list=[5, 10, 20, 60], sell_price=sell_price)`。
- 但 record 组装时：
  - `post5_*` 从 `p5` 映射。
  - `post10_*` 从 `p10` 映射。
  - `post20_*` 从 `p20` 映射。
  - `post60_chg` 直接写为 `None`。
- monkeypatch smoke check 中模拟 `fetch_post_validation()` 返回 `post60: {chg: -12}`，最终 record 仍为 `post60_chg=None`。

影响：

- V3 声称支持 T+60 事后验证窗口，但主审计写入路径不会保存 T+60 涨跌。
- `update_post_validation()` 虽支持补字段，但首次审计即使已有 T+60 数据也会丢弃。

建议：

1. 在 `insert_audit_from_trade()` 中增加：
   - `p60 = post_validation.get("post60", {})`
   - `"post60_chg": p60.get("chg") if isinstance(p60, dict) else None`
2. 如果未来需要更完整 T+60 数据，表结构也应补 `post60_close/post60_high/post60_low`，否则仅存 `post60_chg` 会限制后续分析。

### HIGH 3. TdxQuant 适配层存在，但未接入 `fetch_pre_snapshot()` 主数据流

证据：

- `scripts/tdxquant_adapter.py` 已实现：
  - `tdx_fetch_kline()`
  - `tdx_fetch_realtime()`
  - `tdx_formula_zb()`
  - `tdx_get_stock_info()`
  - `tdx_get_trading_dates()`
  - `_to_tdx_code()`
- 功能说明把“fetch_market_data→TdxQuant切换”列为 P1 待完善项。
- `scripts/fetch_market_data.py` 中未发现 `fetch_pre_snapshot()` 调用 `tdxquant_adapter` 或 `tdx_fetch_*`。

影响：

- V3 文档中的 “TdxQuant 主数据源” 尚未成为真实主路径。
- 当前仍主要依赖原 API/手算指标；如果原 API 数据不足或不可用，V3 审计质量和稳定性会下降。

建议：

1. 在 `fetch_pre_snapshot()` 中加入数据源策略：
   - 优先 TdxQuant。
   - 失败时回退当前接口。
   - 返回结果中记录 `data_source` 与 fallback reason。
2. 给 `tdxquant_adapter` 增加最小集成 smoke check，验证 WSL 到 Windows Python 的 JSON 桥接失败时能给出清晰错误。

### MED 4. T+20/T+60 补数据 cron/CLI 未闭环

证据：

- V3 改造方案提到 `python review_generator.py audit --update-post --days 20,60`。
- 当前 `review_generator.py --help` 的 `audit` 子命令只有：
  - `--account`
  - `--start`
  - `--end`
  - `--force`
- `trade_audit_sql.py` 有 `update_post_validation()`，但未发现 `review_generator.py audit --update-post` 入口。
- 功能说明也把 `T+60事后补数据cron` 列为 P1 待完善项。

影响：

- 事后验证字段有存储函数，但缺少可操作的批量补数据入口。
- T+20/T+60 长窗口数据只能靠手写脚本或未来补充，不符合完整功能闭环。

建议：

1. 给 `audit` 增加 `--update-post --days 20,60` 参数。
2. 实现 `batch_update_post_validation(days_list)`：
   - 查询需要补数据的 `trade_audit` 记录。
   - 调用 `fetch_post_validation()`。
   - 写入 `update_post_validation()`。
   - 写 `audit_log`。
3. 提供 cron 示例或 `scripts/run_post_validation_cron.sh`。

### MED 5. 行业排名、大盘 MA20、卖出时 BOLL/趋势等字段仍是默认值或空值

证据：

- 功能说明将以下项列为 P2 待完善：
  - `sector_pct_rank` 暂默认 `50.0`。
  - `mkt_above_ma20` 暂为 `None`。
  - `sell_boll_pctb/sell_trend` 暂为空。
  - `single_risk_pct` 需对接持仓表取 `total_assets`。
- 代码审查确认：
  - `sector_pct_rank` 仍使用默认 `50.0`。
  - `mkt_above_ma20` 仍为 `None`。
  - `sell_boll_pctb` 仍为 `None`。
  - 单笔风险计算依赖交易 dict 的 `total_assets`，批量路径里 `total_assets=0`。

影响：

- 入场评分中的“行业大盘”子项会失真。
- 卖出审计无法完整评价卖出时市场/个股技术状态。
- 风控评分中的单笔风险在批量路径中无法可信计算。

建议：

1. 对接行业涨跌排名数据源，替换 `sector_pct_rank=50.0`。
2. 在入场快照中补上大盘 MA20 判断。
3. 卖出审计时获取卖出日快照，填充 `sell_trend` 与 `sell_boll_pctb`。
4. 从账户资金/持仓表读取 `total_assets`，无法读取时将 `data_complete=0` 并记录缺失原因。

### MED 6. 数据校验过弱，无法阻止空字符串日期和 0 价格/数量进入审计

证据：

- `trade_audit_sql.REQUIRED_FIELDS` 只包含 14 个字段。
- `validate_audit_record()` 只判断字段值是否为 `None`。
- `_fetch_completed_trades()` 当前会产出 `buy_date=""`、`buy_price=0`、`buy_shares=0`，这些不会被 `validate_audit_record()` 拦截。

影响：

- 可能把无效交易送入 MySQL，由数据库报错。
- 如果数据库隐式转换空日期，可能产生脏数据。
- 错误会晚于业务校验暴露，定位困难。

建议：

1. `validate_audit_record()` 增强校验：
   - 日期字段不能为空且可解析。
   - 价格、数量、金额需大于 0。
   - `sell_date >= buy_date`。
   - `sell_shares > 0`。
   - `pnl_rate` 与 `realized_pnl` 可以为 0，但必须来自真实计算路径。
2. 对 `_needs_fifo=True` 的记录直接拒绝写入。

### MED 7. `_fetch_completed_trades()` 拼接 SQL 条件且吞掉异常，不利于安全和排错

证据：

- `account/start_date/end_date` 被直接拼接进 SQL 字符串。
- 表不存在或查询错误时 `except Exception: pass`。

影响：

- CLI 参数可能引发 SQL 注入风险或查询语法问题。
- 表结构变化、字段缺失、连接权限问题会被静默吞掉，最终表现为“没有交易”，不利于定位。

建议：

1. 改为参数化 SQL。
2. 区分“表不存在”和“查询失败”。
3. 失败时写入 `stats["errors"]` 或 `audit_log.errors`，不要静默忽略。

### MED 8. 配置和代码存在硬编码 MySQL fallback 密码

证据：

- `scripts/trade_audit_sql.py` 的 `_load_mysql_config()` 中存在 `hardcoded_pwd = "[REDACTED]"` fallback。

影响：

- 凭据进入代码库，存在泄漏风险。
- 环境迁移时可能误连到非预期数据库。

建议：

1. 删除硬编码密码。
2. 强制使用 `MYSQL_PWD` 或配置文件。
3. 若缺密码，启动时报明确错误。

### LOW 9. 文档之间对 `classify_mkt_trend()` 的描述有不一致

证据：

- `review_generator_改造方案V3.md` 描述的大盘趋势逻辑：上证/深证/创业板中 ≥2 个上涨或下跌。
- `V3功能说明.md` 某处描述为：上证 MA5 > MA20 判 bull，MA5 < MA20 判 bear。
- 实现采用的是三大指数涨跌幅投票逻辑。

影响：

- 代码与改造方案一致，但与功能说明局部描述不一致。
- 后续验收和维护容易产生分歧。

建议：

- 统一文档口径。若继续采用三指数投票，应更新 `V3功能说明.md` 中的 `classify_mkt_trend()` 描述。

### LOW 10. 测试缺失

证据：

- 当前目录未发现 test-like 文件。
- 已运行的验证均为临时 smoke check，不是项目内可复用测试。

影响：

- V3 函数较多，且包含交易规则、数据库写入、行情回退、日期窗口等高风险逻辑，后续改动容易回归。

建议：

至少补以下测试：

1. `get_trade_category()` 四分法 4 类全覆盖。
2. `calc_trade_direction()` 对 bull/bear/sideways 组合全覆盖。
3. `audit_score()` 对 10 分制边界覆盖。
4. `calc_sell_verdict()` 覆盖 correct/missed/early/normal。
5. `insert_audit_from_trade()` 用 monkeypatch 覆盖完整 record 映射，特别是 `post60_chg`。
6. `_fetch_completed_trades()` 在 FIFO 缺失时应拒绝生成审计，或返回明确错误。
7. `trade_audit_sql.validate_audit_record()` 对空日期、0 买价、0 数量失败。

## 建议修改优先级

### P0：让批量审计不再产出无效记录

- 实现 FIFO 适配层。
- `_fetch_completed_trades()` 不再用卖出流水伪造完整交易。
- 对 `_needs_fifo=True` 的交易拒绝写入。
- 强化 `validate_audit_record()`。

### P1：补齐 V3 事后验证闭环

- 修复 `post60_chg` 映射。
- 增加 `audit --update-post --days 20,60`。
- 实现 T+20/T+60 批量补数据与日志。

### P1：接入 TdxQuant 主数据源

- `fetch_pre_snapshot()` 优先调用 `tdxquant_adapter`。
- 失败回退当前数据源。
- 记录实际数据源和 fallback reason。

### P2：提高评分可信度

- 行业排名百分位。
- 大盘 MA20 判断。
- 卖出日 BOLL/趋势。
- 账户总资产/持仓数据对接。

### P2：治理与安全

- 移除硬编码 MySQL 密码。
- SQL 参数化。
- 不再吞异常。
- 增加最小测试集。

## 验证记录

已执行：

```text
python -m py_compile scripts/review_generator.py scripts/fetch_market_data.py scripts/trade_audit_sql.py scripts/tdxquant_adapter.py
```

结果：无输出，语法编译通过。

```text
python review_generator.py --help
```

结果：展示 `{draft,update,daily,score,audit,audit-single}`。

```text
python trade_audit_sql.py --help
```

结果：展示 `{create,check,stats}`。

```text
import review_generator
import trade_audit_sql
```

结果：导入成功。

```text
pure function smoke check
```

结果：

- `calc_trade_direction('bull','bull')` 返回 `顺势买入`。
- `calc_trade_direction('bear','bear')` 返回 `强逆势买入`。
- `get_trade_category(1,'pass','顺势买入',1)` 返回 `规则内盈利`。
- `get_trade_category(0,'pass','顺势买入',0)` 返回 `规则外亏损`。
- `calc_feedback_action('规则外亏损',4,False,False)` 返回 `exclude`。
- `audit_score(...)` 返回 `total_score=9.5`。

```text
insert_audit_from_trade monkeypatch smoke check
```

结果：

- 返回 `status=inserted`。
- record 字段数为 91。
- `AUDIT_COLUMNS` 无缺失字段。
- 发现 `post60_chg` 即使有输入数据也仍为 `None`。

未执行：

- 未连接真实 MySQL 建表/写入，因为当前任务是实现审查，且真实数据库状态可能受环境影响。
- 未跑 pytest，因为仓库当前没有测试文件。
- 未调用真实行情网络接口做端到端审计，因为这会混入外部数据源稳定性问题；建议在补完 FIFO 和 T+60 映射后单独做端到端验收。

