#!/usr/bin/env python3
"""
东方财富股吧人气榜 & 飙升榜数据抓取脚本

Steps:
1. Playwright抓取人气榜+飙升榜排名数据(各翻5页=100条)
2. 腾讯行情API补全名称+价格
3. 新浪/腾讯K线API计算MA5/MA20(线程池8并发)
4. 筛选股价>MA5且>MA20的股票
5. 写Obsidian 3个文件(人气榜.md, 飙升榜.md, index.md)
6. 写MySQL 3张表(guba_popular_rank, guba_surge_rank, guba_index_picks)
"""

import os
import sys
import re
import json
import time
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

import pymysql
import numpy as np

# ============================================================
# 配置
# ============================================================
OBSIDIAN_VAULT = os.environ.get(
    "OBSIDIAN_VAULT_PATH",
    "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"
)
MARKET_DIR = os.path.join(OBSIDIAN_VAULT, "mystocks", "市场行情")

MYSQL_HOST = "192.168.123.104"
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_DB = "hermes"
MYSQL_PWD = os.environ.get("MYSQL_PWD", "c790414J")

PAGES = 5  # 每个榜单翻5页
PER_PAGE = 20
KLINE_WORKERS = 8

# ============================================================
# MySQL
# ============================================================
@contextmanager
def get_conn():
    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PWD, database=MYSQL_DB, charset="utf8mb4"
    )
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# Step 1: Playwright抓取
# ============================================================
def fetch_rank_data(rank_type="popular"):
    """抓取人气榜或飙升榜数据
    rank_type: 'popular' = 人气榜, 'surge' = 飙升榜
    
    人气榜结构:
      - Cell 0: 当前排名(可能为空，用icon表示)
      - Cell 1: 排名变动
      - data-strdata最后一条: RANK, RANKCHANGE
      
    飙升榜结构:
      - Cell 0: 飙升位(HISRANKCHANGE) - 较昨日上升了多少位
      - Cell 1: 当前排名(RANK)
      - data-strdata最后一条: RANK, HISRANKCHANGE_RANK, HISRANKCHANGE
    """
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto("https://guba.eastmoney.com/rank/", timeout=30000)
        page.wait_for_timeout(3000)

        # Click the right tab
        if rank_type == "surge":
            surge_tab = page.query_selector("span.rankup")
            if surge_tab:
                surge_tab.click()
                page.wait_for_timeout(3000)
                print(f"  切换到飙升榜标签页")

        # Paginate through 5 pages
        for pg in range(1, PAGES + 1):
            if pg > 1:
                next_link = page.query_selector(f'a.go_page[data-page="{pg}"]')
                if next_link:
                    next_link.click()
                    page.wait_for_timeout(2000)
                else:
                    print(f"  ⚠ 第{pg}页未找到翻页按钮，跳过")
                    continue

            rows = page.query_selector_all("tbody.stock_tbody tr")
            for row in rows:
                try:
                    # Get code from class name
                    row_class = row.get_attribute("class") or ""
                    code_match = re.search(r"item_(\d+)", row_class)
                    if not code_match:
                        continue
                    code = code_match.group(1)

                    # Get data from data-strdata
                    chart = row.query_selector("a.chart_line")
                    rank = len(results) + 1
                    rank_change = 0
                    surge_positions = 0  # 飙升位数
                    if chart:
                        strdata = chart.get_attribute("data-strdata") or "[]"
                        data = json.loads(strdata)
                        if data:
                            last = data[-1]
                            if rank_type == "surge":
                                rank = last.get("HISRANKCHANGE_RANK", rank)
                                surge_positions = last.get("HISRANKCHANGE", 0)
                            else:
                                rank = last.get("RANK", rank)
                                rank_change = last.get("RANKCHANGE", 0)
                    
                    # Also try to get rank_change from cells for popular rank
                    cells = row.query_selector_all("td")
                    if rank_type == "popular" and rank_change == 0 and len(cells) >= 2:
                        try:
                            cell1_text = cells[1].inner_text().strip()
                            nums = re.findall(r'-?\d+', cell1_text)
                            if nums:
                                rank_change = int(nums[0])
                        except (ValueError, IndexError):
                            pass
                    
                    # For surge rank, also get surge_positions from Cell 0
                    if rank_type == "surge" and surge_positions == 0 and len(cells) >= 1:
                        try:
                            cell0_text = cells[0].inner_text().strip()
                            nums = re.findall(r'\d+', cell0_text)
                            if nums:
                                surge_positions = int(nums[0])
                        except (ValueError, IndexError):
                            pass

                    # Get fans percentages from Cell 9
                    new_fans_pct = 0.0
                    loyal_fans_pct = 0.0
                    if len(cells) >= 10:
                        fans_text = cells[9].inner_text().strip()
                        fans_parts = fans_text.replace("%", "").split("\n")
                        if len(fans_parts) >= 2:
                            try:
                                new_fans_pct = float(fans_parts[0].strip())
                            except ValueError:
                                pass
                            try:
                                loyal_fans_pct = float(fans_parts[1].strip())
                            except ValueError:
                                pass

                    results.append({
                        "rank": rank,
                        "rank_change": rank_change if rank_type == "popular" else surge_positions,
                        "code": code,
                        "name": "",
                        "price": None,
                        "change_pct": None,
                        "new_fans_pct": new_fans_pct,
                        "loyal_fans_pct": loyal_fans_pct,
                    })
                except Exception as e:
                    print(f"  ⚠ 解析行失败: {e}")
                    continue

            print(f"  第{pg}页: 已采集{len(results)}条")

        browser.close()

    return results


# ============================================================
# Step 2: 腾讯行情API补全名称+价格
# ============================================================
def fetch_tencent_quote(codes):
    """批量获取腾讯行情数据"""
    result = {}
    batch_size = 40
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        query_codes = []
        for c in batch:
            if c.startswith(('6', '5')):
                query_codes.append(f"sh{c}")
            else:
                query_codes.append(f"sz{c}")

        url = f"https://qt.gtimg.cn/q={','.join(query_codes)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.qq.com/"
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("gbk")
        except Exception as e:
            print(f"  ⚠ 腾讯行情API请求失败: {e}")
            continue

        for line in body.split(";"):
            line = line.strip()
            if not line or '~' not in line:
                continue
            try:
                parts = line.split('~')
                if len(parts) < 45:
                    continue
                m = re.match(r'v_(sh|sz)(\d+)', line)
                if not m:
                    continue
                code = m.group(2)
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0.0
                prev_close = float(parts[4]) if parts[4] else 0.0
                change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
                result[code] = {
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                }
            except (ValueError, IndexError):
                continue

    return result


# ============================================================
# Step 3: K线API计算MA5/MA20
# ============================================================
def fetch_kline(code):
    """获取日K线数据，计算MA5和MA20"""
    prefix = "sh" if code.startswith(('6', '5')) else "sz"
    full_code = f"{prefix}{code}"

    # Try Tencent K-line API first
    try:
        tencent_url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
            f"param={full_code},day,,,30,qfq"
        )
        with urllib.request.urlopen(tencent_url, timeout=15) as resp:
            body = json.loads(resp.read().decode())
        kdata = body.get("data", {}).get(full_code, {})
        day_key = "qfqday" if "qfqday" in kdata else "day"
        klines = kdata.get(day_key, [])
        if klines and len(klines) >= 20:
            closes = np.array([float(k[2]) for k in klines])
            ma5 = float(np.mean(closes[-5:]))
            ma20 = float(np.mean(closes[-20:]))
            return {"code": code, "ma5": ma5, "ma20": ma20}
    except Exception:
        pass

    # Fallback to Sina K-line API
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={full_code}&scale=240&ma=no&datalen=30"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if data and len(data) >= 20:
            closes = np.array([float(k["close"]) for k in data])
            ma5 = float(np.mean(closes[-5:]))
            ma20 = float(np.mean(closes[-20:]))
            return {"code": code, "ma5": ma5, "ma20": ma20}
    except Exception:
        pass

    return None


def batch_fetch_klines(codes, workers=KLINE_WORKERS):
    """批量获取K线并计算MA5/MA20"""
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_kline, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
                if result:
                    results[code] = result
            except Exception as e:
                print(f"  ⚠ K线计算失败 {code}: {e}")
    return results


# ============================================================
# Step 4: 筛选
# ============================================================
def filter_above_ma(popular_data, surge_data, kline_data):
    """筛选股价>MA5且>MA20的股票"""
    picks = []
    seen = set()

    for source, data in [("人气", popular_data), ("飙升", surge_data)]:
        for item in data:
            code = item["code"]
            price = item.get("price")
            if not price or price <= 0:
                continue
            kl = kline_data.get(code)
            if not kl or kl["ma5"] is None or kl["ma20"] is None:
                continue
            ma5 = kl["ma5"]
            ma20 = kl["ma20"]
            if price > ma5 and price > ma20:
                if code in seen:
                    continue
                seen.add(code)
                dist_ma5 = round((price - ma5) / ma5 * 100, 2)
                dist_ma20 = round((price - ma20) / ma20 * 100, 2)
                picks.append({
                    "code": code,
                    "name": item.get("name", ""),
                    "price": price,
                    "change_pct": item.get("change_pct", 0),
                    "ma5": round(ma5, 3),
                    "ma20": round(ma20, 3),
                    "dist_ma5_pct": dist_ma5,
                    "dist_ma20_pct": dist_ma20,
                    "source": source,
                })

    picks.sort(key=lambda x: x["dist_ma20_pct"], reverse=True)
    return picks


# ============================================================
# Step 5: 写Obsidian文件
# ============================================================
def format_change(change):
    """格式化排名变动(人气榜用)"""
    if change > 0:
        return f"↑{change}"
    elif change < 0:
        return f"↓{abs(change)}"
    return "→"


def format_pct(pct):
    """格式化涨跌幅"""
    if pct is None:
        return "--"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct}%"


def write_obsidian_popular(data, now_str):
    """写人气榜.md"""
    lines = [
        "---",
        f"title: 东方财富股吧人气榜",
        f"date: {now_str}",
        f"source: https://guba.eastmoney.com/rank/",
        f"market: A股",
        "---",
        "",
        "# 人气榜 TOP100",
        "",
        f"> 更新时间: {now_str}",
        "",
        "| 排名 | 变动 | 股票 | 最新价 | 涨跌幅 | 新晋粉丝 | 铁杆粉丝 |",
        "|------|------|------|--------|--------|----------|----------|",
    ]
    for item in data[:100]:
        change_str = format_change(item["rank_change"])
        price_str = f"{item['price']:.2f}" if item.get("price") else "--"
        pct_str = format_pct(item.get("change_pct"))
        new_fans = f"{item['new_fans_pct']:.2f}%" if item.get("new_fans_pct") else ""
        loyal_fans = f"{item['loyal_fans_pct']:.2f}%" if item.get("loyal_fans_pct") else ""
        name = item.get("name", "")
        stock_label = f"{item['code']} {name}" if name else item['code']
        lines.append(
            f"| {item['rank']} | {change_str} | {stock_label} | {price_str} | {pct_str} | {new_fans} | {loyal_fans} |"
        )

    filepath = os.path.join(MARKET_DIR, "人气榜.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  ✅ Obsidian: {filepath}")


def write_obsidian_surge(data, now_str):
    """写飙升榜.md"""
    lines = [
        "---",
        f"title: 东方财富股吧飙升榜",
        f"date: {now_str}",
        f"source: https://guba.eastmoney.com/rank/",
        f"market: A股",
        "---",
        "",
        "# 飙升榜 TOP100",
        "",
        f"> 更新时间: {now_str}",
        "",
        "| 排名 | 飙升位 | 股票 | 最新价 | 涨跌幅 | 新晋粉丝 | 铁杆粉丝 |",
        "|------|--------|------|--------|--------|----------|----------|",
    ]
    for item in data[:100]:
        surge_pos = f"↑{item['rank_change']}" if item.get("rank_change") else "↑0"
        price_str = f"{item['price']:.2f}" if item.get("price") else "--"
        pct_str = format_pct(item.get("change_pct"))
        new_fans = f"{item['new_fans_pct']:.2f}%" if item.get("new_fans_pct") else ""
        loyal_fans = f"{item['loyal_fans_pct']:.2f}%" if item.get("loyal_fans_pct") else ""
        name = item.get("name", "")
        stock_label = f"{item['code']} {name}" if name else item['code']
        lines.append(
            f"| {item['rank']} | {surge_pos} | {stock_label} | {price_str} | {pct_str} | {new_fans} | {loyal_fans} |"
        )

    filepath = os.path.join(MARKET_DIR, "飙升榜.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  ✅ Obsidian: {filepath}")


def write_obsidian_index(picks, now_str):
    """写index.md (均线筛选)"""
    lines = [
        "---",
        f"title: 人气榜均线筛选",
        f"date: {now_str}",
        f"source: guba人气榜+飙升榜",
        f"filter: 股价>MA5且>MA20",
        "---",
        "",
        "# 人气榜均线筛选 — 股价站上MA5 & MA20",
        "",
        f"> 更新时间: {now_str} | 来源: 人气榜+飙升榜 | 筛选: 收盘价>MA5 且 收盘价>MA20",
        f"> 按偏离MA20降序(强势排前)",
        "",
        "| 股票 | 最新价 | 涨跌幅 | MA5 | MA20 | 偏离MA5 | 偏离MA20 | 来源 |",
        "|------|--------|--------|-----|------|---------|----------|------|",
    ]
    for p in picks:
        pct_str = format_pct(p["change_pct"])
        dist5_sign = "+" if p["dist_ma5_pct"] > 0 else ""
        dist20_sign = "+" if p["dist_ma20_pct"] > 0 else ""
        lines.append(
            f"| {p['code']} {p['name']} | {p['price']:.2f} | {pct_str} | "
            f"{p['ma5']:.3f} | {p['ma20']:.3f} | "
            f"{dist5_sign}{p['dist_ma5_pct']:.2f}% | {dist20_sign}{p['dist_ma20_pct']:.2f}% | {p['source']} |"
        )

    popular_codes = set(p["code"] for p in picks if p["source"] == "人气")
    surge_codes = set(p["code"] for p in picks if p["source"] == "飙升")
    popular_only = len(popular_codes - surge_codes)
    surge_only = len(surge_codes - popular_codes)

    lines.extend([
        "",
        "---",
        "",
        "## 摘要",
        "",
        f"- 筛选结果: **{len(picks)}只** 股价站上MA5&MA20",
        f"- 双榜交集: 0只 | 仅人气榜: {popular_only}只 | 仅飙升榜: {surge_only}只",
    ])
    if picks:
        best = picks[0]
        worst = picks[-1]
        lines.append(f"- 偏离MA20最大: {best['code']} {best['name']} +{best['dist_ma20_pct']:.2f}%")
        lines.append(f"- 偏离MA20最小: {worst['code']} {worst['name']} +{worst['dist_ma20_pct']:.2f}%")

    filepath = os.path.join(MARKET_DIR, "index.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  ✅ Obsidian: {filepath}")


# ============================================================
# Step 6: 写MySQL
# ============================================================
def write_mysql_popular(data, fetch_time):
    """写guba_popular_rank"""
    with get_conn() as conn:
        cur = conn.cursor()
        count = 0
        for item in data:
            cur.execute(
                """INSERT INTO guba_popular_rank
                   (fetch_time, `rank`, rank_change, code, name, price, change_pct, new_fans_pct, loyal_fans_pct)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (fetch_time, item["rank"], item["rank_change"], item["code"],
                 item.get("name", ""), item.get("price"), item.get("change_pct"),
                 item.get("new_fans_pct"), item.get("loyal_fans_pct"))
            )
            count += 1
        conn.commit()
    print(f"  ✅ MySQL guba_popular_rank: {count}条")


def write_mysql_surge(data, fetch_time):
    """写guba_surge_rank"""
    with get_conn() as conn:
        cur = conn.cursor()
        count = 0
        for item in data:
            cur.execute(
                """INSERT INTO guba_surge_rank
                   (fetch_time, `rank`, rank_change, code, name, price, change_pct, new_fans_pct, loyal_fans_pct)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (fetch_time, item["rank"], item["rank_change"], item["code"],
                 item.get("name", ""), item.get("price"), item.get("change_pct"),
                 item.get("new_fans_pct"), item.get("loyal_fans_pct"))
            )
            count += 1
        conn.commit()
    print(f"  ✅ MySQL guba_surge_rank: {count}条")


def write_mysql_index_picks(picks, fetch_time):
    """写guba_index_picks"""
    with get_conn() as conn:
        cur = conn.cursor()
        count = 0
        for p in picks:
            cur.execute(
                """INSERT INTO guba_index_picks
                   (fetch_time, code, name, price, change_pct, ma5, ma20, dist_ma5_pct, dist_ma20_pct, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (fetch_time, p["code"], p["name"], p["price"], p["change_pct"],
                 p["ma5"], p["ma20"], p["dist_ma5_pct"], p["dist_ma20_pct"], p["source"])
            )
            count += 1
        conn.commit()
    print(f"  ✅ MySQL guba_index_picks: {count}条")


# ============================================================
# Main
# ============================================================
def main():
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

    print(f"🚀 东方财富股吧人气榜&飙升榜抓取 - {now_str}")
    print("=" * 60)

    # Step 1: Playwright抓取
    print("\n📊 Step 1: Playwright抓取排名数据...")
    print("  抓取人气榜...")
    popular_data = fetch_rank_data("popular")
    print(f"  人气榜: {len(popular_data)}条")

    print("  抓取飙升榜...")
    surge_data = fetch_rank_data("surge")
    print(f"  飙升榜: {len(surge_data)}条")

    # Step 2: 腾讯行情API补全
    print("\n📈 Step 2: 腾讯行情API补全名称+价格...")
    all_codes = list(set(
        [item["code"] for item in popular_data] +
        [item["code"] for item in surge_data]
    ))
    print(f"  去重后共{len(all_codes)}只股票")
    tencent_data = fetch_tencent_quote(all_codes)
    print(f"  获取到{len(tencent_data)}只行情数据")

    # Merge tencent data
    for item in popular_data + surge_data:
        code = item["code"]
        if code in tencent_data:
            td = tencent_data[code]
            if td["name"]:
                item["name"] = td["name"]
            if td["price"] and td["price"] > 0:
                item["price"] = td["price"]
                item["change_pct"] = td["change_pct"]

    popular_with_price = sum(1 for i in popular_data if i.get("price"))
    surge_with_price = sum(1 for i in surge_data if i.get("price"))
    print(f"  人气榜有价格: {popular_with_price}/{len(popular_data)}")
    print(f"  飙升榜有价格: {surge_with_price}/{len(surge_data)}")

    # Step 3: K线MA计算
    print("\n📉 Step 3: K线API计算MA5/MA20...")
    codes_with_price = list(set(
        [item["code"] for item in popular_data if item.get("price")] +
        [item["code"] for item in surge_data if item.get("price")]
    ))
    print(f"  需计算MA的股票: {len(codes_with_price)}只")
    kline_data = batch_fetch_klines(codes_with_price)
    print(f"  成功计算MA: {len(kline_data)}只")

    # Step 4: 筛选
    print("\n🔍 Step 4: 筛选股价>MA5且>MA20...")
    picks = filter_above_ma(popular_data, surge_data, kline_data)
    print(f"  符合条件: {len(picks)}只")

    # Step 5: 写Obsidian
    print("\n📝 Step 5: 写Obsidian文件...")
    write_obsidian_popular(popular_data, now_str)
    write_obsidian_surge(surge_data, now_str)
    write_obsidian_index(picks, now_str)

    # Step 6: 写MySQL
    print("\n💾 Step 6: 写MySQL...")
    write_mysql_popular(popular_data, fetch_time)
    write_mysql_surge(surge_data, fetch_time)
    write_mysql_index_picks(picks, fetch_time)

    # Summary
    print("\n" + "=" * 60)
    popular_only = sum(1 for p in picks if p["source"] == "人气")
    surge_only = sum(1 for p in picks if p["source"] == "飙升")
    best = picks[0] if picks else None
    worst = picks[-1] if picks else None

    # Build top 10 list for the summary
    top10_lines = []
    for i, p in enumerate(picks[:10]):
        top10_lines.append(
            f"  {i+1}. {p['code']} {p['name']} | ¥{p['price']:.2f} | MA20+{p['dist_ma20_pct']:.1f}% | {p['source']}"
        )

    summary = (
        f"📊 人气榜&飙升榜日报 {now_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"人气榜: {len(popular_data)}条 | 飙升榜: {len(surge_data)}条\n"
        f"均线筛选: {len(picks)}只站上MA5&MA20\n"
        f"仅人气: {popular_only} | 仅飙升: {surge_only}\n"
    )
    if best:
        summary += f"最强: {best['code']} {best['name']} +{best['dist_ma20_pct']:.2f}%\n"
    if worst:
        summary += f"最弱: {worst['code']} {worst['name']} +{worst['dist_ma20_pct']:.2f}%\n"
    if top10_lines:
        summary += "\n🏆 MA20偏离TOP10:\n" + "\n".join(top10_lines) + "\n"
    summary += "━━━━━━━━━━━━━━━━━━━━"

    print(summary)
    return summary


if __name__ == "__main__":
    try:
        summary = main()
    except Exception as e:
        import traceback
        error_msg = f"❌ 脚本执行失败: {e}\n{traceback.format_exc()}"
        print(error_msg)
        summary = f"📊 人气榜&飙升榜日报 - 执行失败\n❌ {e}"
