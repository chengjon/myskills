# V3.2 基础设施优化 + 方案C事后补字段 完整记录

> 日期: 2026-06-03
> 状态: 全部完成

## 一、V3.2 基础设施优化（5项）

### 1. calc_pnl_for_audit() 精确FIFO适配
- 新增函数返回扁平化交易对列表，每笔卖出保存 buy_date/buy_price/buy_shares + buy_lots FIFO拆分细节
- `_fetch_completed_trades()` 改为优先调用 calc_pnl_for_audit，fallback到简化版SQL配对
- 2023笔交易对中2016笔有完整买入日期（仅7笔早期数据缺失）
- calc_pingan_pnl.py Decimal/float类型混合Bug修复：buy_amount_total用Decimal运算，输出转float

### 2. 腾讯K线fallback
- fetch_kline 新浪优先+腾讯fallback（新浪HTTP 456时自动切腾讯）
- 腾讯K线API格式：`[date, open, close, high, low, volume]`（close在high前面！需列转换）
- fetch_kline_tencent() 统一转换为 `{date, open, high, low, close, volume}` 格式

### 3. 三级缓存
- `_kline_cache`: 最多500个code+period组合
- `_snapshot_cache`: 最多2000个code+trade_date+historical组合
- `_indices_cache`/`_sectors_cache`: TTL=300秒
- batch_audit 716笔约5-8分钟（无缓存会超时）

### 4. fetch_indices 腾讯行情fallback
- 新浪行情API被封时自动切到腾讯 qt.gtimg.cn
- 返回格式不同但已做统一适配

### 5. MySQL硬编码密码全移除
- calc_pingan_pnl.py 密码改为 `os.environ.get("MYSQL_PWD", "")`
- 与 trade_audit_sql.py 一致

## 二、方案C 事后补字段（3项）

### 1. fetch_post_validation 改用 sell_date 基准
- **旧逻辑**：从 buy_date 起算T+N，涨跌幅以 buy_price 为基准
- **新逻辑**：从 **sell_date** 起算T+N，涨跌幅以 **sell_price** 为基准
- 持仓期最高价从 buy_date 到 sell_date 的K线中取
- 新增 sell_date 参数（必须），hold_period_max_price 写入 trade_audit.max_price_hold
- fetch_count 根据持仓期动态计算（持仓天数+事后max_days+20）

### 2. calc_sell_verdict missed_profit 修复
- **旧逻辑**：只要 post20_high > hold_period_max_price 就判 missed_profit，亏损交易也会被判
- **新逻辑**：新增 buy_price 参数，missed_profit 只在盈利交易中判定（buy_price>0 且 sell_price>buy_price）
- 亏损交易卖出后反弹改判 normal/good_profit/late_stop
- 修复结果：missed_profit 从74%→33%，且98%是盈利交易

#### sell_verdict 最终分布（1026笔）
| verdict | 笔数 | 占比 | 盈利 | 亏损 | 均分 |
|---------|------|------|------|------|------|
| normal | 414 | 40% | 47 | 367 | 3.92 |
| missed_profit | 338 | 33% | 332 | 6 | 3.38 |
| good_profit | 238 | 23% | 78 | 160 | 3.50 |
| late_stop | 36 | 3% | 11 | 25 | 4.03 |

### 3. BOLL覆盖率提升
- fetch_pre_snapshot 日K线从60→250条
- 确保MA60/BOLL/MACD/RSI等指标有足够历史数据
- BOLL覆盖率 68%→74%
- 数据不足时 boll_pctb 保持默认50.0（NULL容忍）

## 三、代码修改清单

| 文件 | 修改点 |
|------|--------|
| fetch_market_data.py | fetch_post_validation 新增 sell_date 参数，基准日切换，涨跌幅改sell_price，持仓期最高价计算，fetch_count动态调整 |
| fetch_market_data.py | fetch_pre_snapshot 日K线60→250条 |
| review_generator.py | calc_sell_verdict 新增 buy_price 参数，missed_profit 限定盈利交易 |
| review_generator.py | insert_audit_from_trade 传 sell_date 给 fetch_post_validation |
| review_generator.py | hold_max 写入 max_price_hold（不再为NULL） |
| review_generator.py | batch_update_post_validation 加 recalc_verdict 参数 |
| trade_audit_sql.py | POST_UPDATE_COLUMNS 加 max_price_hold + sell_verdict |

## 四、MySQL数据质量（1026笔，2024-2026）

| 指标 | 覆盖率 |
|------|--------|
| BOLL(非默认50) | 74.2% |
| stk_trend(非sideways) | 64.4% |
| mkt_trend | 100% |
| max_price_hold | 100% |
| post5 | 94.0% |
| post20 | 82.0% |
| post60 | 47.3% |

post60偏低(47%)是因为很多近期卖出还没到T+60，后续cron补全即可。

## 五、batch_update_post_validation 用法

```bash
# 补全5/10/20/60事后验证+重算sell_verdict
export MYSQL_PWD=xxx
cd /root/.hermes/skills/mystock-analysis/scripts
source /opt/claude/Scrapling/.venv/bin/activate
python -c "
import sys; sys.path.insert(0,'.')
from trade_audit_sql import get_conn
from review_generator import batch_update_post_validation
with get_conn() as conn:
    stats = batch_update_post_validation(conn, days_list=[5,10,20,60], recalc_verdict=True)
print(stats)
"
```

## 六、待推进项

| 项目 | 优先级 | 说明 |
|------|--------|------|
| post60补全 | P1 | 近期交易T+60留NULL，需cron定期补 |
| 行业排名sector_pct_rank | P3 | 当前占位50，需TdxQuant或东财API |
| 两融特殊处理 | P3 | 融券卖出/担保品等特殊abstract |
| BOLL→95% | P2 | 部分次新股K线不足250条 |
