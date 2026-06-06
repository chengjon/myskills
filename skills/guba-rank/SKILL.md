---
name: guba-rank
description: 东方财富股吧人气榜&飙升榜下载器 - 每日抓取A股TOP100排名，均线筛选，保存Obsidian+MySQL
version: 2.0.0
trigger: 人气榜, guba, 股吧排名, 飙升榜, 均线筛选
---

# 东方财富股吧人气榜 & 飙升榜

## 概述
从东方财富股吧(guba.eastmoney.com)抓取A股市场人气榜和飙升榜TOP100数据，补全名称行情，计算MA5/MA20均线，筛选站上双均线的股票，输出到Obsidian 3个文件 + MySQL 3张表。

## 运行命令
```bash
cd /opt/claude/Scrapling && .venv/bin/python ~/.hermes/skills/mystock-analysis/scripts/fetch_guba_rank.py
```

## 6步工作流

### 1. Scrapling StealthyFetcher 抓取排名数据
- StealthyFetcher 反检测浏览器，5页x20条 = 100条/榜
- 数据通过base64编码注入DOM，从resp.html_content解码取回
- 人气榜: 默认tab，翻页用 `a.go_page:has-text('下一页')`
- 飙升榜: 点击"飙升榜"tab切换，同样翻5页
- 表格列结构: col0=排名图标, col1=变动, col2=空, col3=代码, col4=话题, col5=链接, col6-8=行情, col9=粉丝

### 2. 腾讯行情API 补全名称+价格
- `qt.gtimg.cn` 批量查询，每批≤50只，GBK编码
- 前缀规则: 6/9开头=sh, 8/4开头=bj, 其他=sz
- 北交所920xxx名称暂缺（腾讯不支持）
- 返回字段: 名称/最新价/昨收/涨跌幅

### 3. 腾讯K线API 计算MA5/MA20
- `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,25,qfq`
- 新浪K线API在WSL返回HTTP 456(频率限制)，**必须用腾讯K线替代**
- 返回格式: `{data: {symbol: {qfqday: [[日期,开盘,收盘,最高,最低,成交量],...]}}}`
- 收盘价是 index 2: `float(k[2])`
- 优先取 `qfqday`（前复权），fallback 到 `day`
- **指数key不同**：个股用 `qfqday`，上证指数(sh000001)用 `day`（无前复权）
- **历史数据批量获取**：指定日期范围可取2015年至今，单次最多620根。格式：`param=sz002491,day,2015-01-01,2015-12-31,800,qfq`。跨年需分批请求
- **必须线程池并行**(`ThreadPoolExecutor(max_workers=8)`)，串行200只需>120s会超时
- 每只3次重试+0.5s间隔
- 本地算均值: MA5=近5日收盘均值, MA20=近20日收盘均值
- 北交所代码用 `bj` 前缀（腾讯可能不支持，静默跳过）

### 4. 均线筛选
- 条件: 股价 > MA5 且 股价 > MA20
- 按偏离MA20降序排列（强势股排前面）
- source字段: popular / surge / popular+surge

### 5. Obsidian 3个文件（覆盖写，仅保留最新）
| 文件 | 路径 | 内容 |
|------|------|------|
| 人气榜.md | `mystocks/市场行情/` | TOP100排名+变动+行情+粉丝 |
| 飙升榜.md | `mystocks/市场行情/` | TOP100飙升+行情+粉丝 |
| index.md | `mystocks/市场行情/` | 均线筛选结果+摘要 |

### 6. MySQL 3张表（INSERT，保留完整历史）
| 表 | 内容 | 关键字段 |
|----|------|---------|
| guba_popular_rank | 人气榜 | fetch_time, rank, code, name, price, change_pct, new_fans_pct, loyal_fans_pct |
| guba_surge_rank | 飙升榜 | 同上 |
| guba_index_picks | 均线筛选 | fetch_time, code, name, price, change_pct, ma5, ma20, dist_ma5_pct, dist_ma20_pct, source |

MySQL连接: `${MYSQL_HOST}:3306/hermes`

## 报告格式规范

### 股票名称显示: "代码+名称"
- 有名称: `000539 粤电力Ａ`、`600011 华能国际`
- 无名称(如北交所920xxx): 仅显示代码 `920223`
- 统一用 `_code_name(code, name)` 函数，合并到"股票"列（不分代码/名称两列）

### 日期时间
- frontmatter `date` 和 `更新时间` 均写完整日期+时间: `2026-06-02 09:00`
- 不只写日期，必须带时分

## 关键 Pitfall

### API可用性（WSL环境）
| API | 可用性 | 用途 |
|-----|--------|------|
| 腾讯 qt.gtimg.cn | ✅ 可用 | 名称+行情 |
| 腾讯 K线 web.ifzq.gtimg.cn | ✅ 可用 | MA计算(前复权日K) |
| 新浪 K线 | ❌ HTTP 456频率限制 | WSL不可用，用腾讯替代 |
| 东财 push2 | ❌ WSL IP封锁 | 不可用 |
| curl_cffi | ❌ TLS指纹被识别 | 不可用 |
| 东财加密JS(gbcdn) | ❌ 加密不可解 | 不可用 |

### Scrapling StealthyFetcher 数据提取模式

**关键**：`page_action(page)` 的返回值被引擎丢弃（源码 L248-252 `_=page_action(page)`），无法通过 return 传数据出来。

**解决方案**：在 page_action 内把数据 base64 编码注入 DOM，从 `resp.html_content` 提取：
```python
import base64, json, re

def page_action(page):
    # ... 翻页+JS提取逻辑 ...
    data = {"popular": popular, "surge": surge}
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    page.evaluate(f'document.body.insertAdjacentHTML("beforeend",\'<textarea id="scrapling_data" style="display:none">{encoded}</textarea>\')')

resp = StealthyFetcher.fetch(url, page_action=page_action, ...)
# 从响应HTML中提取
match = re.search(r'<textarea id="scrapling_data"[^>]*>([^<]+)</textarea>', resp.html_content)
data = json.loads(base64.b64decode(match.group(1)).decode())
```

### 飙升榜tab切换
- `text=飙升榜` 会匹配到隐藏的 `<p class="cc">` 元素，导致点错
- **必须**用精确选择器：`page.locator('.box_header >> text=飙升榜').first.click()`
- 降级方案：`page.get_by_role("tab", name="飙升榜")` 或遍历所有含文本的可点击元素

### 运行环境
- **必须**在 Scrapling venv 下运行: `/opt/claude/Scrapling/.venv/bin/python`
- 该venv有: playwright + chromium + pymysql + curl_cffi
- 安装新包到该venv: `/opt/claude/Scrapling/.venv/bin/pip install XXX`

### 性能
- MA计算用腾讯K线API(新浪API在WSL有频率限制)，200只需ThreadPoolExecutor并行(4~8并发)
- 翻页后需 `wait_for_timeout(2000)` 等数据加载
- 非交易时间行情可能显示"--"

### 飞书推送
- 脚本末尾输出📊开头的摘要，cron任务将此摘要推飞书
- 摘要中TOP3/TOP5统一用"代码+名称"格式

## Cron 定时任务
- Job ID: `5e0fc625ddc2`
- 调度: `0 9 * * 1-5` (工作日9点)
- 推送: origin + 飞书
- 模型: glm-5.1

## 依赖
- Scrapling StealthyFetcher + Chromium (venv /opt/claude/Scrapling/.venv)
- pymysql (已安装在 Scrapling venv)
- urllib (标准库)
