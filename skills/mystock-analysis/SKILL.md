---
name: mystock-analysis
description: 股票全面分析——技术面（实时行情/MA/MACD/RSI/缺口/支撑压力/3天走势预测）+ 基本面五步法（好公司/好未来/好价格/好买卖/风险提示）+ 综合评级 + 飞书文档输出。支持A股/港股/美股。
dependency:
  python:
    - requests>=2.28.0
    - numpy>=1.24.0
    - pandas>=2.0.0
    # akshare  # 基本面财务数据获取（可选）
    # openclaw>=0.1.0  # 可选，提供更多数据源支持
user-invocable: true
---

# 股票全面分析 Skill（mystock-analysis）

> 技术面 × 基本面 × 综合评级。短期看走势，长期看价值，一次搞定。

## 触发词

`股票分析`、`个股分析`、`技术分析`、`基本面分析`、`五步法`、`走势预测`

## 三种分析模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| 技术面 | 实时行情 + 技术指标 + 缺口分析 + 3天走势预测 | 短线操作、择时 |
| 基本面 | 五步法深度分析 + 估值 + 分档建仓策略 | 中长期投资决策 |
| 全面分析 | 先技术面再基本面，综合给出最终评级 | 完整个股研究 |

**默认模式：全面分析**（用户未指定时执行）

---

# Part A: 技术面分析

## 任务目标

- 对指定股票进行技术分析：实时数据获取、技术指标计算、支撑位压力位分析、缺口识别
- 能力：实时行情获取、MA/MACD/RSI 计算、支撑压力位识别、缺口分析、趋势判断、3天走势预测

## 前置准备

- 必需依赖：`requests>=2.28.0`、`numpy>=1.24.0`、`pandas>=2.0.0`
- 可选依赖：`openclaw>=0.1.0`（更多数据源）
- 核心脚本为预编译 .so 模块（Python 3.13 编译）；若当前环境 Python 版本不匹配，Agent 按以下步骤手动执行技术分析流程

## 操作步骤

### A-1. 获取股票代码并验证

- 用户提供股票代码，如：000001（平安银行）、sh600000（浦发银行）、000001.SZ（深交所格式）
- 参考股票代码格式文档 [references/stock_code_format.md](references/stock_code_format.md)

### A-2. 获取实时行情数据（多数据源支持）

- 调用 `scripts/fetch_stock_data.py` 获取实时行情和历史K线数据
- **多数据源自动切换机制**：
  - 主数据源：新浪财经（免费、稳定）
  - 备用数据源1：东方财富
  - 备用数据源2：雪球
  - 自动切换：主数据源失败时自动尝试备用
- 参数：
  - `--stock_code`: 股票代码（必需）
  - `--days`: 获取历史数据天数（默认30天）
  - `--source`: 指定数据源（可选：sina/eastmoney/xueqiu）
- 返回：当前价格、涨跌幅、成交量、历史K线、数据源信息

### A-3. 计算技术指标和支撑位

- 调用 `scripts/analyze_stock.py` 进行技术分析
- 参数：`--data_file`（上一步的数据文件路径）
- 计算结果：
  - MA5/MA10/MA20/MA60 均线
  - MACD 指标
  - RSI 指标
  - 支撑位和压力位
  - 缺口分析（向上/向下缺口）
  - 成交量分析
  - 趋势判断

### A-4. 分析当前走势

- 均线排列（多头/空头/缠绕）
- MACD 金叉死叉状态
- RSI 超买超卖状态
- 成交量配合情况
- K线形态分析
- **缺口分析**：
  - 向上缺口：回调时缺口上沿可能成为支撑
  - 向下缺口：反弹时缺口下沿可能成为压力
  - 缺口大小和位置对走势的影响

### A-5. 预测未来3天走势

- 综合技术指标和趋势分析判断未来3天走势
- 考虑因素：趋势方向、支撑压力位、缺口支撑压力、成交量变化、市场情绪
- 给出概率评估：上涨/下跌/横盘的概率和强度

### A-6. 生成操作建议

- 买入/持有/卖出/观望
- 建议的买入/卖出价格区间
- 止损位和止盈位设置
- 缺口相关的操作提示

### .so 脚本不可用时的手动流程

若 `.so` 模块因 Python 版本不匹配无法加载，使用 `scripts/tech_analysis.py` 执行：

1. **确保依赖已安装**（首次使用时）：
   ```bash
   source /root/.hermes/hermes-agent/venv/bin/activate && pip install numpy pandas -q
   ```
2. **在 execute_code 中调用**：
   ```python
   from tech_analysis import fetch_klines, fetch_realtime, compute_indicators, find_gaps
   # 实时行情
   rt = fetch_realtime("sz000938")  # 沪市用 sh
   # 日K线 + 指标计算
   klines = fetch_klines("sz000938", days=120)
   result = compute_indicators(klines)
   gaps = find_gaps(klines, lookback=60)
   ```
3. 基于计算结果按 A-4~A-6 步骤完成分析

**数据源 API 详见** [references/data-source-urls.md](references/data-source-urls.md)

**Pitfall**：
- 新浪实时行情必须加 `Referer: http://finance.sina.com.cn` 头，否则被拒绝
- 新浪 K 线 API 无需 Referer，更稳定，优先使用
- 东方财富 K 线 API 部分网络环境下 HTTPS 连接被拒，作为备用
- A股代码前缀：沪市=`sh`，深市=`sz`
- **akshare `stock_financial_abstract_ths` 数据排序**：`indicator="按年度"` 返回的 DataFrame 从旧到新排列（iloc[0] 是上市首年，iloc[-1] 是最新年度），取最新数据必须用 `df.iloc[-1]` 或按报告期筛选含 "2024"/"2025" 的行，**绝不能用 `df.iloc[0]`**
- **腾讯行情两种格式**：`s_sz002929`（s_前缀）返回精简格式约10个字段（名称~代码~现价~涨跌额~涨跌幅~成交量~成交额~~总市值~市场类型）；`sz002929`（无s_前缀）返回完整格式约50个字段，含 PE/PB/换手率/流通市值/总市值 等。需要完整指标时用无s_格式
- **腾讯市值字段单位是亿元**（非万元）：`total_cap` 和 `market_cap` 返回值单位为亿元，例如中科曙光返回 1262.96 即约1263亿元。估算总资产时注意：净资产=总市值/ PB，总资产=净资产/(1-资产负债率)

---

# Part B: 基本面五步法分析

## 任务目标

- 基于**长投学堂五步分析法**的完整个股分析系统
- 涵盖公司基本面、未来成长性、估值分析到买卖决策的全流程
- 自动生成标准化分析报告并输出飞书文档

## 适用场景

| 场景 | 说明 |
|------|------|
| 深度个股分析 | 对单只股票进行完整的五步法分析 |
| 投资决策支持 | 为买入/卖出决策提供量化依据 |
| 定期复盘跟踪 | 对持仓股票进行季度/年度复盘 |
| 学习案例参考 | 分析标杆公司（伊利、茅台、腾讯等） |

## 操作步骤

### B-1. 数据采集与验证

- 从年报、研报提取核心数据
- 验证财务数据真实性（回款率、扣非净利润）
- 同行业数据对比（毛利率、净利率、ROE）
- 使用 [templates/data-template.md](templates/data-template.md) 结构化采集数据
- 原始数据存入 `memory/YYYY-MM-DD.md`

### B-2. Step 1: 好公司——过去是否持续赚钱？

- **公司三问**（产品/销售/成本）
- **净利润拆解**（真实性验证）：
  - 销售回款率 > 100% → 收入真实
  - 扣非净利润为核心盈利指标（不能用总净利润！）
  - 10年净利润CAGR > GDP增速
- **七大竞争力评估**：品牌优势/规模优势/资源占领/技术优势/转换成本/网络效应/政府授权

### B-3. Step 2: 好未来——未来能否持续赚钱？

- **行业天花板测算**（常识法/研报法/海外比较法）
- **行业供给与竞争格局分析**（CRN分析）
- **营收增速预测**：
  ```
  营收增速 = (1 + 行业增速) × (1 + 市占率增幅) - 1
  ```
- 三情景预测：悲观/中性/乐观

### B-4. Step 3: 好价格——当前价格是否便宜？

- **相对估值法**：PE、PB 历史百分位
- **绝对估值法**：市值 = 预测净利润 × PE
- 估值中枢判断
- 安全边际不少于8折

### B-5. Step 4: 好买卖——何时买入卖出？

- **分档建仓策略**（3-4个价位区间）
- **卖出策略**（估值过高/基本面恶化/目标价达成）
- 持仓管理逻辑

### B-6. Step 5: 风险提示

- 行业风险
- 公司风险
- 估值风险

### B-7. 生成分析报告

- 基于 [templates/analysis-template.md](templates/analysis-template.md) 生成标准化报告
- 报告包含：摘要/好公司/好未来/好价格/好买卖/数据速查表/免责声明
- **飞书文档输出**：创建飞书文档并发送链接给用户

---

# Part C: 综合分析流程

## 全面分析执行顺序

```
1. 技术面分析（Part A 全流程）
   ├─ A-1 获取代码
   ├─ A-2 获取行情
   ├─ A-3 计算指标
   ├─ A-4 分析走势
   ├─ A-5 预测3天
   └─ A-6 操作建议
   ↓
2. 基本面分析（Part B 全流程）
   ├─ B-1 数据采集
   ├─ B-2 好公司
   ├─ B-3 好未来
   ├─ B-4 好价格
   ├─ B-5 好买卖
   ├─ B-6 风险提示
   └─ B-7 生成报告
   ↓
3. 综合评级
   ├─ 技术面评分（短中期走势判断）
   ├─ 基本面评分（中长期价值判断）
   ├─ 综合建议（操作方向+价格区间+风险等级）
   └─ 输出飞书文档
```

## 综合评级表

| 维度 | 评分 | 说明 |
|------|------|------|
| 技术面 | ⭐1-5 | 短期走势和买卖点判断 |
| 好公司 | ⭐1-5 | 过去持续赚钱能力 |
| 好未来 | ⭐1-5 | 未来持续赚钱能力 |
| 好价格 | ⭐1-5 | 当前估值合理性 |
| 好买卖 | ⭐1-5 | 买卖时机把握 |
| **综合** | **X/5** | **最终操作建议** |

## 综合建议逻辑

- **技术面+基本面共振看多** → 积极建仓
- **技术面看多+基本面一般** → 小仓位短线
- **技术面看空+基本面优秀** → 等待技术面企稳再加仓
- **技术面+基本面共振看空** → 观望或减仓

---

# 资源索引

| 文件 | 用途 |
|------|------|
| [scripts/tech_analysis.py](scripts/tech_analysis.py) | **手动 fallback 核心**：fetch_klines/fetch_realtime/compute_indicators/find_gaps，.so 不可用时直接 import |
| [scripts/fetch_stock_data.py](scripts/fetch_stock_data.py) | 多数据源获取股票数据（.so wrapper，需 Python 3.13） |
| [scripts/analyze_stock.py](scripts/analyze_stock.py) | 计算技术指标和支撑位压力位（.so wrapper，需 Python 3.13） |
| [scripts/fetch_stock_data_openclaw.py](scripts/fetch_stock_data_openclaw.py) | 基于 openclaw 的数据获取（可选） |
| [references/data-source-urls.md](references/data-source-urls.md) | **数据源 API 参考**：新浪/东方财富 URL、参数、Header 要求、选择策略 |
| [references/stock_code_format.md](references/stock_code_format.md) | 股票代码格式参考 |
| [references/openclaw_integration.md](references/openclaw_integration.md) | openclaw 集成说明 |
| [references/sector-concept-analysis.md](references/sector-concept-analysis.md) | **板块/概念股批量分析工作流**：板块代码搜索→成分股获取→批量行情→K线涨跌→财务数据→报告生成 |
| [templates/analysis-template.md](templates/analysis-template.md) | 五步法分析报告模板 |
| [templates/data-template.md](templates/data-template.md) | 数据采集模板 |
| [examples/yili-analysis.md](examples/yili-analysis.md) | 伊利股份完整分析案例 |

---

# 使用示例

## 示例1：全面分析（默认）

```
用户：分析002639雪人集团
执行：
1. 技术面：fetch_stock_data.py --stock_code 002639 --days 30
2. 技术面：analyze_stock.py --data_file stock_data_002639.json
3. 基本面：采集数据 → 五步法分析
4. 综合评级 + 飞书文档输出
```

## 示例2：纯技术面

```
用户：技术分析贵州茅台
执行：
1. fetch_stock_data.py --stock_code 600519 --days 30
2. analyze_stock.py --data_file stock_data_600519.json
3. 输出技术面分析报告
```

## 示例3：纯基本面

```
用户：五步法分析伊利股份
执行：
1. 采集年报/研报数据
2. 按 Step 1-5 分析
3. 基于 analysis-template.md 生成报告
4. 输出飞书文档
```

## 示例4：指定数据源

```
用户：用东方财富数据源分析招商银行
执行：
1. fetch_stock_data.py --stock_code 600036 --source eastmoney --days 30
2. analyze_stock.py --data_file stock_data_600036.json
```

## 示例5：港股/美股

```
用户：分析腾讯控股 00700.HK
用户：分析AAPL苹果公司
执行：同上，代码格式参考 references/stock_code_format.md
```

---

# 注意事项

## 数据准确性原则

1. **必须用年报原文数据**，避免二次引用错误
2. **必须用扣非净利润**进行估值，不能用总净利润
3. PE 数据需注明是 TTM（滚动12个月）
4. 原始数据必须保留来源标注（年报第几页、研报名称）

## 保守原则

1. 增长预测取保守值（行业增速取历史下限）
2. 估值给予保守 PE（历史分位20%-50%）
3. 安全边际不少于8折
4. 风险提示必须全面

## 缺口分析要点

- 向上缺口（跳空高开）：回调时可能构成支撑，关注是否回补
- 向下缺口（跳空低开）：反弹时可能构成压力，关注是否回补
- 缺口越大，支撑或压力作用通常越强
- 成交量配合的缺口更具参考意义
- 近期缺口参考价值高于远期缺口

## .so 兼容性说明

- 核心脚本为 Python 3.13 编译的 `.so` 模块
- 若当前环境为 Python 3.12，.so 无法加载时按「手动流程」执行
- 手动流程使用 `scripts/tech_analysis.py`，依赖 numpy+pandas
- **首次使用前**必须在 Hermes venv 中安装依赖：`pip install numpy pandas`
- Hermes venv 路径是 `venv/bin/activate`（不是 `.venv`）

## 数据源说明

- 系统支持多数据源自动切换，提高数据获取稳定性
- 默认新浪财经，失败时自动尝试东方财富和雪球
- 可通过 `--source` 参数指定数据源
- openclaw 可选，提供 SSE/SZSE 等官方数据源

## 子技能

| 子技能 | 触发词 | 位置 |
|--------|--------|------|
| 交易复盘审计 | 复盘/审计/audit | `trade-audit/` 子目录（独立运行） |

**独立性原则**：trade-audit 是独立功能，不依赖也不影响 daily-stock 工作流。不要把审计脚本混入本技能的 scripts/ 目录。本技能的 SKILL.md 必须保持 GitHub 原始版本（仅 Part A/B/C），如果发现被改了需从 GitHub 恢复。

## 免责声明

- 股票市场存在风险，所有分析仅供参考，不构成投资建议
- 技术分析基于历史数据，不能保证未来表现
- 建议结合基本面分析和市场环境进行综合判断
- 实时数据可能存在延迟，请以实际交易数据为准
- 过往业绩不代表未来收益
- 必须在所有建议中包含风险提示
