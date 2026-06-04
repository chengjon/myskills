# 交易路径分析方案 V1

> 对2026年前377笔交易(54只股票)的完整路径分析，目标：量化交易习惯→找出改进点→提升盈亏比

## 数据现状速览

| 指标 | 数值 | 说明 |
|------|------|------|
| 总交易 | 377笔(54只股票) | 2021-2025 |
| 净盈亏 | **-10.2万** | 盈+13.5万，亏-23.7万 |
| 胜率 | 47.8% | 接近50%但盈亏比严重失衡 |
| 盈亏比 | **0.57:1** | 每亏1元只赚0.57元(需>1.5) |
| 规则内交易 | **0笔** | 100%规则外(无止损/无仓位管理) |
| 重复交易 | 344笔(91%) | 同一股票≥3次交易 |
| 冲动交易 | 247笔(66%) | is_impulsive=1 |

## 分析框架：3层×5维度

### 层级

```
L1 单笔交易(Transaction) → L2 交易路径(Trade Path) → L3 行为画像(Behavior Profile)
```

### L2 路径定义

一只股票的一条完整交易路径 = 从首次买入日到最终持仓归零日之间的**所有交易序列**。

同一股票可有多条路径（买→卖→空仓→再买→卖 = 2条路径）。

### L2 路径切分算法

```python
def split_trade_paths(trades_of_stock):
    """
    输入: 同一股票按buy_date排序的交易列表
    输出: 多条TradePath
    
    切分规则: 
    - 如果当前交易的buy_date > 上一笔的sell_date + 5个交易日
      (空仓超过1周视为新路径)
    - 或者: 当前持仓已清零(所有卖出shares累计 >= 所有买入shares累计)
    """
    paths = []
    current_path = []
    cumulative_position = 0
    
    for trade in sorted_trades:
        if current_path:
            last_sell = current_path[-1].sell_date
            gap = trading_days_between(last_sell, trade.buy_date)
            if gap > 5 and cumulative_position <= 0:
                paths.append(TradePath(current_path))
                current_path = []
                cumulative_position = 0
        
        current_path.append(trade)
        cumulative_position += trade.buy_shares - trade.sell_shares
    
    if current_path:
        paths.append(TradePath(current_path))
    return paths
```

## 5维度量化指标

### 维度1：入场质量(Entry Quality)

| 指标 | 计算方式 | 理想值 | 当前数据 |
|------|---------|--------|----------|
| 入场BOLL位置 | avg(stk_boll_pctb) | ≤0.4(低吸) | 极低区53.6%胜率 vs 极高区43.7% |
| 顺势率 | bull趋势占比 | ≥60% | 仅11%在bull入场 |
| 逆势入场占比 | bear+sideways入场占比 | ≤30% | **89%**逆势入场 |

**关键发现**：bull入场胜率64.3%，avg_pnl+435元；bear胜率48.3%，sideways胜率43.4%

### 维度2：持仓管理(Hold Management)

| 指标 | 计算方式 | 理想值 | 当前数据 |
|------|---------|--------|----------|
| 过早卖出率 | missed_profit占比 | ≤15% | **41%**(154/377) |
| 利润实现率 | realized_pnl / (max_price_hold - buy_price) | ≥60% | 需补算 |
| 回撤容忍度 | max_drawdown_pct | ≤8% | 无数据(全0) |

**关键发现**：exit_score=0(好卖点)的交易96.9%盈利avg+851；exit_score=1(差卖点)avg-1142

### 维度3：风控执行(Risk Control)

| 指标 | 计算方式 | 理想值 | 当前数据 |
|------|---------|--------|----------|
| 止损设置率 | stop_loss_set=1占比 | 100% | **0%** |
| 单笔最大亏损 | min(realized_pnl) | ≥-总资产2% | 未知 |
| 连亏次数 | consecutive_losses | ≤3 | 需补算 |

**关键发现**：normal卖出140笔总亏-21.2万 = 最大亏损源

### 维度4：仓位与集中度(Position & Concentration)

| 指标 | 计算方式 | 理想值 | 当前数据 |
|------|---------|--------|----------|
| 重复交易指数 | 同股交易次数 | ≤5 | 40笔最高(600172) |
| 同日交易数 | trades_same_day | ≤2 | 149笔≥4笔/日 |

**关键发现**：1次交易股票胜率66.7%，6-10次avg_pnl=-2621，10次+=-6431

### 维度5：行为模式(Behavior Pattern)

| 指标 | 计算方式 | 理想值 | 当前数据 |
|------|---------|--------|----------|
| 冲动交易率 | is_impulsive=1占比 | ≤20% | **66%** |
| 亏损后加仓率 | 亏→加仓序列占比 | ≤10% | 需从路径分析 |

**关键发现**：冲动交易avg_pnl-333 vs 非冲动-158

## 路径分类(Typology)

| 模式 | 特征 | 改进方向 |
|------|------|---------|
| 猎手型 | 1-2笔，短持，快进快出 | 提升选股精度 |
| 波段型 | 2-5笔，持仓1-4周 | 加强止盈纪律 |
| 粘合型 | ≥10笔，反复进出 | 减少交易频率 |
| 越跌越买型 | bear中持续加仓 | 禁止逆势加仓 |
| 止损过晚型 | 浮盈转亏损 | 设置硬止损 |
| 错失利润型 | 盈利但过早卖出 | 移动止盈 |

## TradePath 数据类

```python
@dataclass
class TradePath:
    stock_code: str
    trades: list           # 按时间排序的交易列表
    path_start: date       # 首笔买入日
    path_end: date         # 末笔卖出日
    path_duration: int     # 路径持续天数
    
    # 收益指标
    total_pnl: float       # 路径总盈亏
    gross_profit: float    # 总盈利
    gross_loss: float      # 总亏损
    profit_loss_ratio: float  # 盈亏比
    win_rate: float        # 胜率
    max_single_profit: float
    max_single_loss: float
    avg_pnl_per_trade: float
    
    # 路径形态
    trade_count: int
    avg_hold_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    position_peak: float   # 持仓峰值(股数)
    is_pyramid_path: bool  # 是否加仓路径
    is_cost_averaging: bool  # 是否越跌越买
    
    # 入场质量
    avg_entry_boll: float
    bull_entry_rate: float
    avg_entry_score: float
    
    # 风控
    max_drawdown: float
    stop_loss_rate: float
    loss_exceed_threshold: int
    
    # 行为
    impulsive_rate: float
    revenge_trade_rate: float
    trade_density: float   # 笔/周
```

## 改进量化预测

| 改进措施 | 预期影响 | 量化依据 |
|----------|---------|---------|
| 设置8%硬止损 | 减少亏损30-40% | normal+late_stop共178笔总亏-23.4万 |
| 禁止BOLL>80%追高 | 减少亏损15% | BOLL极高区215笔avg_pnl-390 |
| 同股≤3路径/年 | 减少摩擦成本20% | 重复>5次avg_pnl=-2621 |
| 移动止盈(回撤5%卖) | 增加利润20-30% | missed_profit 154笔总盈+13.5万 |
| 顺势率提升到40% | 提升胜率8-10pp | bull入场胜率64% vs bear 48% |
| 冲动交易率降到20% | 减少亏损25% | 冲动交易avg_pnl-333 vs 非冲动-158 |

## 数据gap(需补全)

| 字段 | 缺失率 | 补全方案 |
|------|--------|---------|
| position_ratio | 100% | 从buy_amount/账户总额推算 |
| max_drawdown_pct | 100% | 从K线计算(持仓期最低价) |
| max_profit_pct | 100% | 从max_price_hold推算 |
| profit_unrealized_rate | 100% | 从max_profit-pnl_rate推算 |

## 实施计划

Phase 1: 路径切分与聚合 → trade_path_analyzer.py
Phase 2: 路径分析可视化
Phase 3: 规则引擎(个性化交易规则→review_config.yaml)
