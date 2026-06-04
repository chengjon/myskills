# 交易复盘系统架构

## 数据流

```
交易计划(Obsidian) ──→ review_generator.py draft ──→ 复盘卡草稿(T+0)
                                                      │
fetch_market_data.py pre ──→ 事前快照 ────────────────┘
                                                      │
                                 T+5/T+10 定时触发 ──→ 更新同一文件
                                                      │
fetch_market_data.py post ──→ 事后验证 ───────────────┘
```

## 两阶段生成

| 阶段 | 触发 | 写入内容 | 文件操作 |
|------|------|----------|----------|
| T+0 | 每日20:00 | 基本信息+事前视角+事前评分+空仓待验证 | 新建文件 |
| T+5 | 买入后5个交易日9:00 | 追加T+5事后验证+事后评分 | 更新同一文件 |
| T+10 | 买入后10个交易日9:00 | 追加T+10事后验证+综合判定+教训改进 | 更新同一文件 |

文件名固定: `个股名-代码-YYYYMMDD.md`（避免重复）

## 事前评分引擎 (6维度×1-5分)

| 维度 | 函数 | 输入 | 关键逻辑 |
|------|------|------|----------|
| 趋势 | score_trend | indicators, klines | MA排列+MACD方向+均线斜率(±1调整) |
| 位置 | score_position | indicators, realtime, chase_detect, trend_score | BOLL位置+追高检测+MA支撑+趋势感知 |
| 行业 | score_sector | sector_data, realtime | 行业涨跌分布+个股相对强弱 |
| 大盘 | score_market | indices, config | 三大指数综合状态(阈值可配置) |
| 风控 | score_risk | trade_info, config | 止损合理性+单笔风险占比(ATR参考) |
| 纪律 | score_discipline | trade_info, config | 有无计划(无→1分)+仓位合规+追高冲动 |

**无交易计划时**: 纪律=1分, 风控=2分, 自动归入异常交易

**BOLL位置趋势感知**（2026-06-01修复）：
- 上涨趋势(trend≥4) + BOLL低位 = 回调好位置(5分)
- 下跌趋势(trend≤2) + BOLL低位 = 继续下跌(2分)
- 震荡趋势 + BOLL低位 = 中性(3分)

## 事后评分引擎 (5维度×1-5分，权重可配置)

| 维度 | 函数 | 输入 | 关键逻辑 |
|------|------|------|----------|
| 方向 | score_direction | post_data | N日涨跌幅判定 |
| 时机 | score_timing | post_data, buy_price | 入场时机精度(最大回撤) |
| 风控有效 | score_stop_effect | post_data, stop_price | 止损是否被触发+距离 |
| 空间 | score_profit_ratio | post_data, stop_price, config | 盈亏比(计划止损价或ATR估算) |
| 持有质量 | score_hold_quality | post_data | 浮亏深度+持续时间 |

**事后评分加权**：`post_weights` 配置（默认等权1.0），加权求和后四舍五入。review_config.yaml 中可自定义各维度权重。

## 追高判定定义

```
chase_high_base = "open"  (配置: open=开盘价 / prev_close=昨收)
追高 = 买入价 >= 基准价 × (1 + chase_high_threshold)
例: 开盘20元, threshold=0.05, 买入≥21元 → 追高
```

**chase_detect key兼容**（2026-06-01修复）：
- `fetch_pre_snapshot()` 返回 `is_chase_high`
- `score_position()` 同时检查 `is_chase` 和 `is_chase_high`（`or` 逻辑）
- `pre_score()` 中做 `unified_chase` 映射：先复制 snapshot，再映射 `is_chase_high` → `is_chase`，再用用户 buy_price 独立计算并覆盖

## 盈亏比计算

优先使用计划止损价:
```
盈亏比 = (N日最高价 - 买入价) / (买入价 - 止损价)
```

无计划止损时用ATR估算:
```
风险 = 2 × ATR(14)
盈亏比 = (N日最高价 - 买入价) / 风险
备注: "基于ATR估算"
```

## 交易成本核算

```
最低佣金 = max(交易金额 × 佣金率, min_commission)  # min_commission=5.0
买入成本 = 最低佣金
卖出成本 = 最低佣金 + 卖出金额 × 印花税率
净盈亏 = 毛利 - 买入成本 - 卖出成本 - 过户费
净盈亏比 = 净盈亏 / 风险金额
```

## 杜绝结果论硬规则

- 事前🔴(6-17分): 无论盈亏，一律错误交易，禁止复刻，录入教训库
- 事前🟢(24-30分): 小幅亏损属概率波动，保留策略
- 月度优质决策胜率>50%: 体系有效; <40%: 需调参

## 异常交易强制复盘条件

| 条件 | 检测逻辑 |
|------|----------|
| 超仓 | 单笔风险 > max_single_risk(2%) |
| 无止损 | stop_price == 0 |
| 隔夜重仓 | 持仓市值 > 总资金50% |
| 逆势重仓 | 大盘下跌 + 仓位>30% |
| 追高冲动 | 追高标记 + 无计划 |

## fetch_market_data.py CLI接口

```bash
# 事前快照
python fetch_market_data.py pre --code 000887 --date 2026-06-01 --time 10:32

# 事后验证
python fetch_market_data.py post --code 000887 --buy-date 2026-06-01 --buy-price 21.34 --stop-price 19.64 --target-price 24.00 --days 10

# K线数据
python fetch_market_data.py kline --code 000887 --period 240 --count 30

# 行业板块
python fetch_market_data.py sector [--keyword 汽车零部件]

# 大盘指数
python fetch_market_data.py index

# 实时行情
python fetch_market_data.py realtime --code 000887
```

## review_generator.py CLI接口

```bash
# T+0草稿(新建复盘卡)
python review_generator.py draft --code 002077 --name 大港股份 --price 15.50 --qty 2000 \
  --date 2025-05-28 --time 10:30 --stop 14.80 --target 17.00 --plan \
  --strategy 半导体封测波段 --entry 突破买入 --assets 500000 --account 平安普通

# T+N事后更新(自动解析frontmatter获取code/price/stop等)
python review_generator.py update --file /path/to/复盘卡.md --days 5
python review_generator.py update --file /path/to/复盘卡.md --days 10

# 日度汇总(扫描当日所有复盘卡)
python review_generator.py daily --date 2025-05-28

# 纯评分(不生成文件, 快速查看)
python review_generator.py score --code 002077 --price 15.50 --qty 2000 --stop 14.80 --assets 500000 --plan
```

### 关键函数

| 函数 | 用途 |
|------|------|
| `pre_score(snapshot, trade_info)` | 事前评分总入口，返回总分+6维度明细 |
| `post_score(validation, config)` | 事后评分总入口，支持post_weights加权，返回总分+5维度明细 |
| `combo_label(pre_total, post_total)` | 九宫格综合判定 |
| `generate_draft(...)` | T+0草稿，生成完整复盘卡MD（含网络异常降级） |
| `update_post_review(filepath, days)` | T+N更新，状态只能递进(STATE_ORDER守卫) |
| `generate_daily(date)` | 日度汇总，frontmatter读取事前/事后评分 |
| `detect_chase_high/impulsive/bottom_fishing` | 检测函数（均接受config参数） |
| `check_force_review` | 异常交易强制复盘 |
| `calc_cost(trade_amount, config)` | 交易成本核算（含最低佣金5元） |
| `_get_industry_map/concept_map/keywords()` | 映射函数（优先配置文件，降级硬编码） |

### Pitfall

1. **行业评分需完整列表**：`fetch_pre_snapshot()` 的 `sector_list` 只含涨幅前10的行业，不足以排名。`pre_score()` 内部自动调用 `fetch_sectors()` 补全；单独调用 `score_sector()` 时需自行传入完整列表
2. **行业名称模糊匹配**：东财行业分类较粗（如"电子器件"而非"半导体封测"），`_DEF_INDUSTRY_KEYWORDS` 字典提供关键词映射，新行业需手动添加或配置到 review_config.yaml
3. **calc_cost返回键名**：`commission_buy` / `commission_sell`（不是 `commission` / `commission2`）
4. **事前评分=直接加权求和**：6维度×1-5分=30分制，`pre_score()` 内部对6个维度分数加权求和（权重默认全1.0=简单求和），不是加权平均
5. **frontmatter格式**：复盘卡使用YAML frontmatter（`---`包裹），包含 `事前评分`/`事前标签`/`事后评分`/`事后标签`，`update_post_review()` 通过正则解析+更新，格式修改需同步更新解析逻辑
6. **异常交易目录**：异常交易复盘卡同时存入 `个股/` 和 `异常交易/` 目录
7. **状态只能递进**：`update_post_review()` 使用 `STATE_ORDER` 守卫，draft→t5_done→t10_done→closed，不可回退
8. **config一次性加载**：`generate_draft()` 入口加载 config 传入各子函数，子函数签名保留 `config=None` 降级兼容
9. **网络异常降级**：`generate_draft()` 中 `fetch_pre_snapshot()` 失败时返回空快照(含 `_fetch_error`)，卡片顶部插入异常提示
10. **常量改名全量grep**：改名 `_DEF_INDUSTRY_MAP`/`_DEF_INDUSTRY_KEYWORDS`/`_DEF_CONCEPT_MAP` 后，所有引用处(L427/L614/L944/L1107)必须同步改为 `_get_industry_map()`/`_get_industry_keywords()`/`_get_concept_map()`，否则运行时 `NameError`
11. **`_get_*()` 函数签名**：`_get_industry_map()`/`_get_industry_keywords()`/`_get_concept_map()` 不接受参数（内部自行 `load_config()`），调用时不要传 config，否则报 `takes 0 positional arguments but 1 was given`。如需传 config 避免重复加载，须同步改签名为 `def _get_industry_map(config=None)`
12. **K线数据字符串类型**：`fetch_klines()` 返回的 open/close/high/low/volume 全部是 `str`，传入 numpy 前必须 `float()` 转换

### 跨模块数据契约

`fetch_market_data.py` 与 `review_generator.py` 之间的数据接口（2026-06-01 已修复兼容）：

| 数据生产方 (fetch_market_data.py) | 数据消费方 (review_generator.py) | 状态 |
|---|---|---|
| `fetch_pre_snapshot()` 返回 `chase_detect.is_chase_high` | `score_position()` 兼容 `is_chase` + `is_chase_high` | ✅ 已修复 |
| `fetch_pre_snapshot()` 返回 `sector_list`(前10) | `score_sector()` 入口自动排序+`pre_score()` 补调 `fetch_sectors()` | ✅ 已修复 |
| `generate_draft()` 独立 `detect_chase_high(buy_price)` | 结果合并进 `unified_chase` 传入 `pre_score()` | ✅ 已修复 |

## BUG修复记录（2026-06-01）

| # | 严重度 | BUG | 修复方案 |
|---|--------|-----|----------|
| 1 | 🔴 | chase_detect key不匹配(is_chase_high vs is_chase) | `score_position()` 兼容两种key；`pre_score()` 做 `unified_chase` 映射 |
| 2 | 🔴 | generate_draft()独立chase结果未传入pre_score | `unified_chase` 合并 snapshot + 独立计算结果 |
| 3 | 🟡 | score_trend()斜率+0/-0空操作 | 改为 `+1` / `-1` |
| 4 | 🟡 | update_post_review()状态可回退(t10→t5) | `STATE_ORDER` 守卫，只允许递进 |
| 5 | 🟡 | calc_cost()未设最低佣金5元/笔 | `max(amt*rate, min_commission)` |
| 6 | 🟠 | generate_draft()无网络异常处理 | try/except + `_fetch_error` 降级 |
| 7 | 🟠 | score_position() BOLL低位不区分趋势 | 新增 `trend_score` 参数 |
| 8 | 🟡 | 常量改名后4处引用未同步(L427/L614/L944/L1107) | `INDUSTRY_MAP` → `_get_industry_map()`，`INDUSTRY_KEYWORDS` → `_get_industry_keywords()`，`CONCEPT_MAP` → `_get_concept_map()`。**教训：改名常量后必须全量grep所有引用** |

### 配置新增项（review_config.yaml）

- `min_commission: 5.0` — A股最低佣金
- `post_weights` — 事后5维度权重（direction/timing/stop_effect/profit_ratio/hold_quality）
- `market_up_threshold: 0.5` — 大盘上涨判定阈值
- `market_down_threshold: -0.5` — 大盘下跌判定阈值
- `industry_map` / `industry_keywords` / `concept_map` — 行业/概念映射（可选，降级用硬编码）

## Obsidian目录结构

```
mystocks/复盘/
├── 2026-06/
│   ├── 汇总/
│   │   └── 2026-06-01.md
│   └── 个股/
│       └── 中鼎股份-000887-20260601.md
├── 异常交易/
│   └── 2026-06-01-大唐发电-600068.md
├── 模板/
│   ├── 复盘卡-买入模板.md
│   ├── 交易计划模板.md
│   └── 日度汇总模板.md
└── 复盘统计.md
```
