---
name: market-monitor
version: 1.0.0
description: 盘中监控页面 — 市场情绪、涨跌统计、活跃板块、人气股票、资金流向、持仓股实时监控
triggers:
  - 盘中监控
  - 刷新监控
  - 市场监控
  - market-monitor
---

# 盘中监控 Skill

生成并刷新 Obsidian 中的 `mystocks/盘中监控.md` 页面。

## 页面结构

```
mystocks/盘中监控.md
├── 大盘指数（上证/深证/创业板/沪深300/上证50/中小100）
├── 市场情绪
│   ├── 涨/跌/平家数 + 涨停/跌停数
│   ├── 创新高/新低家数
│   ├── 涨停/跌停比
│   └── 情绪指标（极度悲观~极度乐观5级）
├── 活跃行业板块（涨幅/跌幅各TOP10，含领涨股）
├── 活跃概念板块（涨幅/跌幅各TOP10，含领涨股+个股数）
├── 人气股票 TOP20（按成交额排名）
├── 资金流向
│   ├── 主力净流入 TOP10（含3日比）
│   └── 主力净流出 TOP10（含3日比）
├── 持仓股盘中监控
│   └── 持股>0的股票实时行情 + 信号标签
└── 数据来源与说明
```

## 数据来源

| 数据项 | 来源 | API |
|--------|------|-----|
| 大盘指数 | 新浪 | `hq.sinajs.cn/list=sh000001,...` |
| 涨跌家数 | 新浪 | 分页遍历 `hs_a` 节点（慢，约40秒） |
| 行业板块 | 新浪 | `newFLJK.php?param=industry` |
| 概念板块 | 新浪 | `newFLJK.php?param=class` |
| 人气股 | 新浪 | `Market_Center.getHQNodeData?sort=amount` |
| 资金流向 | 东财数据中心 | `datacenter-web.eastmoney.com RPT_DMSK_TS_STOCKNEW` |
| 持仓股实时 | 新浪 | `hq.sinajs.cn/list=...` |

## 执行步骤

### 步骤1：采集数据

运行 `scripts/monitor_fetch.py`：
```bash
source /root/.hermes/hermes-agent/venv/bin/activate
python ~/.hermes/skills/productivity/daily-stock/scripts/monitor_fetch.py [quick|full]
```

- `quick` 模式（默认）：跳过全市场涨跌统计（40秒），仅采集指数/板块/资金流/持仓股
- `full` 模式：包含全市场涨跌统计，适合每日定时任务

### 步骤2：生成页面

从 `/tmp/mystocks_monitor_data.json` 读取数据，按页面结构生成 Markdown，写入：
```
/mnt/c/Users/John Cheng/Documents/Obsidian Vault/mystocks/盘中监控.md
```

### 步骤3：（可选）推送摘要

如果配置了飞书，发送简要摘要：
- 市场情绪 + 涨跌比
- 持仓股涨跌概览
- 资金流入/流出前3

## 市场情绪判断规则

| 上涨家数占比 | 情绪 | 标签 |
|-------------|------|------|
| >70% | 极度乐观 | 🔥 |
| 55-70% | 偏乐观 | 😊 |
| 45-55% | 中性 | 😐 |
| 30-45% | 偏悲观 | 😟 |
| <30% | 极度悲观 | 😨 |

## 持仓股信号标签

| 涨跌幅 | 信号 |
|--------|------|
| >=9.9% | 🔴涨停 |
| >=5% | 🔥强势 |
| >=2% | ✅偏强 |
| -2%~2% | ➖震荡 |
| -5%~-2% | 📉偏弱 |
| <=-5% | ⚠️弱势 |
| <=-9.9% | 🟢跌停 |

## 注意事项

- 东财 `push2.eastmoney.com` 接口从 WSL 无法访问（IP 被限流），改用 `datacenter-web.eastmoney.com` 和新浪 API
- 全市场涨跌统计需遍历 ~70 页数据，耗时约 40 秒，quick 模式跳过此步骤
- 数据时间戳以实际获取时间为准，非交易时段数据为上一交易日收盘数据
- 持仓股列表从 `mystocks/index.md` 中持股>0的股票读取
