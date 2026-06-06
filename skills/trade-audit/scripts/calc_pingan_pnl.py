#!/usr/bin/env python3
"""
平安证券盈亏核算 - 分期间版
FIFO法逐笔配对买入/卖出，按卖出日期归属已实现盈亏到不同期间
2026-01-01为分界线：历史(<=2025) vs 当年(>=2026)
"""

import pymysql
from decimal import Decimal
from datetime import datetime, date
import os

MYSQL_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", ""),
    "port": 3306,
    "user": "root",
    "password": os.environ.get("MYSQL_PWD", ""),
    "database": "hermes",
    "charset": "utf8mb4",
}

OB_DIR = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault/mystocks/历史交易/"

CUTOFF = date(2026, 1, 1)  # 分界线

BUY_ABSTRACTS = {"买入", "证券买入清算", "融资买入", "担保品买入", "证券买入清算(融资买入)"}
SELL_ABSTRACTS = {"卖出", "证券卖出清算", "融券卖出", "卖券还款", "担保品卖出", "证券卖出清算(卖券还款)"}


def get_trades(table_name):
    conn = pymysql.connect(**MYSQL_CONFIG)
    cur = conn.cursor()
    other_fee_col = "0 AS other_fee" if table_name == "pingan_normal_trade" else "other_fee"
    cur.execute(f"""
        SELECT posting_date, abstract, stock_code, stock_name,
               shares, price, amount, commission, stamp_tax, transfer_fee, {other_fee_col}
        FROM {table_name}
        WHERE stock_code IS NOT NULL AND stock_code != ''
          AND abstract IN ('买入','卖出','证券买入清算','证券卖出清算',
                           '证券买入清算(融资买入)','证券卖出清算(卖券还款)',
                           '红股派息')
        ORDER BY posting_date, id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def calc_pnl(table_name):
    """
    FIFO法全量配对，每笔卖出记录所属期间。
    返回: realized_per_period[period_key][stock_code] -> rec, holdings
    period_key: "history" (<=2025) or "ytd" (>=2026)
    """
    trades = get_trades(table_name)

    positions = {}  # stock_code -> [{"shares", "price", "date", "comm_per_share"}, ...]
    realized = {}   # stock_code -> rec (全量，含trades带date)
    names = {}      # stock_code -> latest name

    for row in trades:
        dt, abstract, code, name, shares, price, amount, comm, stamp, transfer, other = row
        names[code] = name

        if abstract == "红股派息":
            if code not in positions:
                positions[code] = []
            if shares > 0:
                positions[code].append({
                    "shares": shares, "price": Decimal("0"), "date": dt,
                    "comm_per_share": Decimal("0")
                })
            continue

        is_buy = abstract in BUY_ABSTRACTS
        is_sell = abstract in SELL_ABSTRACTS

        if not is_buy and not is_sell:
            if shares > 0:
                is_buy = True
            elif shares < 0:
                is_sell = True
            else:
                continue

        trade_shares = abs(shares)
        if trade_shares == 0:
            continue

        if code not in positions:
            positions[code] = []
        if code not in realized:
            realized[code] = {
                "name": name, "buy_amount": Decimal("0"), "sell_amount": Decimal("0"),
                "comm": Decimal("0"), "stamp": Decimal("0"), "transfer": Decimal("0"),
                "other_fee": Decimal("0"), "pnl": Decimal("0"),
                "buy_shares": Decimal("0"), "sell_shares": Decimal("0"),
                "trades": [],
            }

        rec = realized[code]
        rec["name"] = name

        if is_buy:
            comm_per_share = abs(comm) / trade_shares if trade_shares else Decimal("0")
            transfer_per_share = abs(transfer) / trade_shares if trade_shares else Decimal("0")
            positions[code].append({
                "shares": trade_shares,
                "price": abs(amount) / trade_shares if trade_shares else price,
                "date": dt,
                "comm_per_share": comm_per_share + transfer_per_share,
            })
            rec["buy_shares"] += trade_shares
            rec["buy_amount"] += abs(amount)
            rec["comm"] += abs(comm)
            rec["transfer"] += abs(transfer)

        elif is_sell:
            sell_shares_remaining = trade_shares
            cost_total = Decimal("0")
            # 记录本笔卖出对应的买入批次(用于审计适配)
            buy_lots_info = []  # [{buy_date, shares, price}, ...]

            while sell_shares_remaining > 0 and positions.get(code):
                lot = positions[code][0]
                if lot["shares"] <= sell_shares_remaining:
                    cost_total += lot["shares"] * (lot["price"] + lot["comm_per_share"])
                    buy_lots_info.append({
                        "buy_date": lot["date"],
                        "shares": int(lot["shares"]),
                        "price": float(lot["price"]),
                    })
                    sell_shares_remaining -= lot["shares"]
                    positions[code].pop(0)
                else:
                    cost_total += sell_shares_remaining * (lot["price"] + lot["comm_per_share"])
                    buy_lots_info.append({
                        "buy_date": lot["date"],
                        "shares": int(sell_shares_remaining),
                        "price": float(lot["price"]),
                    })
                    lot["shares"] -= sell_shares_remaining
                    sell_shares_remaining = 0

            if sell_shares_remaining > 0:
                cost_total += sell_shares_remaining * price

            sell_proceeds = abs(amount) - abs(comm) - abs(stamp) - abs(transfer) - abs(other)
            lot_pnl = sell_proceeds - cost_total

            rec["sell_shares"] += trade_shares
            rec["sell_amount"] += abs(amount)
            rec["comm"] += abs(comm)
            rec["stamp"] += abs(stamp)
            rec["transfer"] += abs(transfer)
            rec["other_fee"] += abs(other)
            rec["pnl"] += lot_pnl
            rec["trades"].append({
                "date": dt, "shares": trade_shares, "price": price,
                "amount": abs(amount), "cost": cost_total, "pnl": lot_pnl,
                "buy_lots": buy_lots_info,
            })

    # 按卖出日期拆分到期间
    period_data = {"history": {}, "ytd": {}}

    for code, rec in realized.items():
        if rec["sell_shares"] == 0:
            continue

        for period_key in ("history", "ytd"):
            period_data[period_key][code] = {
                "name": rec["name"],
                "buy_amount": Decimal("0"), "sell_amount": Decimal("0"),
                "comm": Decimal("0"), "stamp": Decimal("0"), "transfer": Decimal("0"),
                "other_fee": Decimal("0"), "pnl": Decimal("0"),
                "buy_shares": Decimal("0"), "sell_shares": Decimal("0"),
                "trades": [],
            }

        # 买入金额按卖出的股数比例分配到期间
        for t in rec["trades"]:
            sell_date = t["date"] if isinstance(t["date"], date) else t["date"].date() if hasattr(t["date"], 'date') else t["date"]
            pk = "history" if sell_date < CUTOFF else "ytd"
            p = period_data[pk][code]
            p["sell_shares"] += t["shares"]
            p["sell_amount"] += t["amount"]
            p["pnl"] += t["pnl"]
            p["trades"].append(t)

        # 买入金额/费用按卖出股数比例分配
        if rec["sell_shares"] > 0:
            for pk in ("history", "ytd"):
                p = period_data[pk][code]
                if p["sell_shares"] > 0:
                    ratio = p["sell_shares"] / rec["sell_shares"]
                    p["buy_shares"] = (rec["buy_shares"] * Decimal(str(ratio))).quantize(Decimal("1"))
                    p["buy_amount"] = (rec["buy_amount"] * Decimal(str(ratio))).quantize(Decimal("0.01"))
                    p["comm"] = (rec["comm"] * Decimal(str(ratio))).quantize(Decimal("0.01"))
                    p["stamp"] = (rec["stamp"] * Decimal(str(ratio))).quantize(Decimal("0.01"))
                    p["transfer"] = (rec["transfer"] * Decimal(str(ratio))).quantize(Decimal("0.01"))
                    p["other_fee"] = (rec["other_fee"] * Decimal(str(ratio))).quantize(Decimal("0.01"))

    # 剩余持仓
    holdings = {}
    for code, lots in positions.items():
        total_shares = sum(lot["shares"] for lot in lots)
        total_cost = sum(lot["shares"] * lot["price"] for lot in lots)
        if total_shares > 0:
            avg_cost = total_cost / total_shares
            # 判断持仓的期间归属：按最早买入批次
            earliest = min((lot["date"] for lot in lots if lot["date"]), default=None)
            holdings[code] = {
                "name": names.get(code, code),
                "shares": total_shares,
                "avg_cost": avg_cost,
                "total_cost": total_cost,
                "earliest_buy": earliest,
            }

    return period_data, holdings


def summarize_period(period_rec):
    """汇总一个期间的已实现盈亏"""
    total_pnl = Decimal("0")
    total_comm = Decimal("0")
    total_stamp = Decimal("0")
    total_transfer = Decimal("0")
    total_other = Decimal("0")
    total_buy = Decimal("0")
    total_sell = Decimal("0")
    win_count = 0
    lose_count = 0
    stock_count = 0

    for code, rec in period_rec.items():
        if rec["sell_shares"] == 0:
            continue
        stock_count += 1
        pnl = rec["pnl"]
        total_pnl += pnl
        total_comm += rec["comm"]
        total_stamp += rec["stamp"]
        total_transfer += rec["transfer"]
        total_other += rec["other_fee"]
        total_buy += rec["buy_amount"]
        total_sell += rec["sell_amount"]
        if pnl > 0:
            win_count += 1
        elif pnl < 0:
            lose_count += 1

    return {
        "pnl": total_pnl, "comm": total_comm, "stamp": total_stamp,
        "transfer": total_transfer, "other_fee": total_other,
        "buy": total_buy, "sell": total_sell,
        "win": win_count, "lose": lose_count, "stocks": stock_count,
    }


def fmt_pnl(val):
    """格式化盈亏数字，正数带+号"""
    if val > 0:
        return f"+{val:,.2f}"
    return f"{val:,.2f}"


def generate_period_section(label, period_rec, holdings=None, show_holdings=False):
    """生成一个期间的报告段落"""
    s = summarize_period(period_rec)
    wr = s["win"] + s["lose"]
    win_rate = f"{s['win']/wr*100:.1f}%" if wr > 0 else "N/A"

    lines = []
    lines.append(f"### {label}")
    lines.append("")
    lines.append("| 项目 | 金额 |")
    lines.append("|------|------|")
    lines.append(f"| **已实现盈亏** | **{fmt_pnl(s['pnl'])}** |")
    lines.append(f"| 买入总额 | {s['buy']:,.2f} |")
    lines.append(f"| 卖出总额 | {s['sell']:,.2f} |")
    lines.append(f"| 手续费 | {s['comm']:,.2f} |")
    lines.append(f"| 印花税 | {s['stamp']:,.2f} |")
    lines.append(f"| 过户费 | {s['transfer']:,.2f} |")
    lines.append(f"| 盈利股票 | {s['win']} |")
    lines.append(f"| 亏损股票 | {s['lose']} |")
    lines.append(f"| 胜率 | {win_rate} |")

    # 盈利TOP5
    winners = sorted(
        [(c, r) for c, r in period_rec.items() if r["pnl"] > 0],
        key=lambda x: x[1]["pnl"], reverse=True
    )[:5]
    if winners:
        lines.append("")
        lines.append(f"盈利TOP5:")
        lines.append("")
        lines.append("| # | 股票 | 卖出金额 | 盈亏 | 盈亏率 |")
        lines.append("|---|------|---------|------|--------|")
        for i, (code, rec) in enumerate(winners, 1):
            rate = rec["pnl"] / rec["buy_amount"] * 100 if rec["buy_amount"] else 0
            lines.append(f"| {i} | {code} {rec['name']} | {rec['sell_amount']:,.0f} | {fmt_pnl(rec['pnl'])} | {fmt_pnl(rate)}% |")

    # 亏损TOP5
    losers = sorted(
        [(c, r) for c, r in period_rec.items() if r["pnl"] < 0],
        key=lambda x: x[1]["pnl"]
    )[:5]
    if losers:
        lines.append("")
        lines.append(f"亏损TOP5:")
        lines.append("")
        lines.append("| # | 股票 | 卖出金额 | 盈亏 | 盈亏率 |")
        lines.append("|---|------|---------|------|--------|")
        for i, (code, rec) in enumerate(losers, 1):
            rate = rec["pnl"] / rec["buy_amount"] * 100 if rec["buy_amount"] else 0
            lines.append(f"| {i} | {code} {rec['name']} | {rec['sell_amount']:,.0f} | {fmt_pnl(rec['pnl'])} | {fmt_pnl(rate)}% |")

    # 全部明细
    all_stocks = sorted(period_rec.items(), key=lambda x: x[1]["pnl"], reverse=True)
    active = [(c, r) for c, r in all_stocks if r["sell_shares"] > 0]
    if active:
        lines.append("")
        lines.append(f"全部明细 ({len(active)}只):")
        lines.append("")
        lines.append("| 股票 | 卖出股数 | 买入金额 | 卖出金额 | 盈亏 | 盈亏率 |")
        lines.append("|------|---------|---------|---------|------|--------|")
        for code, rec in active:
            rate = rec["pnl"] / rec["buy_amount"] * 100 if rec["buy_amount"] else 0
            lines.append(f"| {code} {rec['name']} | {rec['sell_shares']:,.0f} | {rec['buy_amount']:,.0f} | {rec['sell_amount']:,.0f} | {fmt_pnl(rec['pnl'])} | {fmt_pnl(rate)}% |")

    return "\n".join(lines), s


def main():
    print("=" * 60)
    print("平安证券盈亏核算 (分期间 FIFO法)")
    print(f"分界线: {CUTOFF}")
    print("=" * 60)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 普通账户
    print("\n核算普通账户...")
    n_period, n_holdings = calc_pnl("pingan_normal_trade")
    n_hist_section, n_hist = generate_period_section("历史 (2015~2025)", n_period["history"])
    n_ytd_section, n_ytd = generate_period_section("当年 (2026)", n_period["ytd"])

    # 两融账户
    print("核算两融账户...")
    m_period, m_holdings = calc_pnl("pingan_margin_trade")
    m_hist_section, m_hist = generate_period_section("历史 (2018~2025)", m_period["history"])
    m_ytd_section, m_ytd = generate_period_section("当年 (2026)", m_period["ytd"])

    # 综合汇总
    def add_sum(a, b):
        return {k: a[k] + b[k] for k in a}
    all_hist = add_sum(n_hist, m_hist)
    all_ytd = add_sum(n_ytd, m_ytd)
    all_total = add_sum(all_hist, all_ytd)

    def fmt_row(label, s):
        wr = s["win"] + s["lose"]
        wr_str = f"{s['win']}/{wr}={s['win']/wr*100:.1f}%" if wr > 0 else "N/A"
        return f"| {label} | {fmt_pnl(s['pnl'])} | {s['buy']:,.0f} | {s['sell']:,.0f} | {s['comm']:,.0f} | {s['stamp']:,.0f} | {wr_str} |"

    # === 组装报告 ===
    report = f"""---
title: 平安证券盈亏核算（分期间）
date: {now}
accounts: 平安普通+平安两融
method: FIFO先进先出法
cutoff: 2026-01-01
---

# 平安证券盈亏核算（分期间）

> 核算时间: {now}
> 方法: FIFO先进先出法，成本含手续费+过户费，卖出扣手续费+印花税+过户费
> 分界线: 2026-01-01（按卖出日期归属期间）
> 未含融资利息支出

## 综合盈亏对比

| 期间 | 已实现盈亏 | 买入总额 | 卖出总额 | 手续费 | 印花税 | 胜率 |
|------|-----------|---------|---------|--------|--------|------|
{fmt_row("历史(2025前)", all_hist)}
{fmt_row("当年(2026)", all_ytd)}
{fmt_row("**合计**", all_total)}

### 按账户×期间

| 账户 | 历史盈亏 | 当年盈亏 | **合计** |
|------|---------|---------|---------|
| 普通账户 | {fmt_pnl(n_hist['pnl'])} | {fmt_pnl(n_ytd['pnl'])} | **{fmt_pnl(n_hist['pnl'] + n_ytd['pnl'])}** |
| 两融账户 | {fmt_pnl(m_hist['pnl'])} | {fmt_pnl(m_ytd['pnl'])} | **{fmt_pnl(m_hist['pnl'] + m_ytd['pnl'])}** |
| **合计** | **{fmt_pnl(all_hist['pnl'])}** | **{fmt_pnl(all_ytd['pnl'])}** | **{fmt_pnl(all_total['pnl'])}** |

---

## 普通账户

{n_hist_section}

---

{n_ytd_section}

---

## 两融账户

{m_hist_section}

---

{m_ytd_section}

---

## 当前持仓（未实现盈亏）

### 普通账户 ({len(n_holdings)}只)

| 股票 | 持仓股数 | 持仓成本 | 均价 |
|------|---------|---------|------|
"""

    for code in sorted(n_holdings.keys()):
        h = n_holdings[code]
        report += f"| {code} {h['name']} | {h['shares']:,.0f} | {h['total_cost']:,.2f} | {h['avg_cost']:.3f} |\n"

    report += f"""
### 两融账户 ({len(m_holdings)}只)

| 股票 | 持仓股数 | 持仓成本 | 均价 |
|------|---------|---------|------|
"""

    for code in sorted(m_holdings.keys()):
        h = m_holdings[code]
        report += f"| {code} {h['name']} | {h['shares']:,.0f} | {h['total_cost']:,.2f} | {h['avg_cost']:.3f} |\n"

    # 写入Obsidian
    path = os.path.join(OB_DIR, "平安证券盈亏核算.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已写入: {path}")

    # 控制台摘要
    print(f"\n{'='*70}")
    print(f"{'期间':<12} {'普通账户':>14} {'两融账户':>14} {'合计':>14}")
    print(f"{'-'*70}")
    print(f"{'历史(2025前)':<12} {fmt_pnl(n_hist['pnl']):>14} {fmt_pnl(m_hist['pnl']):>14} {fmt_pnl(all_hist['pnl']):>14}")
    print(f"{'当年(2026)':<12} {fmt_pnl(n_ytd['pnl']):>14} {fmt_pnl(m_ytd['pnl']):>14} {fmt_pnl(all_ytd['pnl']):>14}")
    print(f"{'-'*70}")
    total_n = n_hist['pnl'] + n_ytd['pnl']
    total_m = m_hist['pnl'] + m_ytd['pnl']
    print(f"{'合计':<12} {fmt_pnl(total_n):>14} {fmt_pnl(total_m):>14} {fmt_pnl(all_total['pnl']):>14}")
    print(f"{'='*70}")
    print(f"\n手续费: 历史 {all_hist['comm']:,.0f} + 印花税 {all_hist['stamp']:,.0f}")
    print(f"        当年 {all_ytd['comm']:,.0f} + 印花税 {all_ytd['stamp']:,.0f}")
    print(f"        合计 {all_total['comm']:,.0f} + 印花税 {all_total['stamp']:,.0f}")


if __name__ == "__main__":
    main()


# ============================================================
# 逐笔适配函数: 供 review_generator.batch_audit() 调用
# ============================================================

def calc_pnl_for_audit(table_name: str, account_tag: str = "") -> list:
    """
    FIFO精确配对，返回每笔完整交易对(供审计引擎使用)

    与 calc_pnl() 的区别:
    - 不按期间拆分，保留全部逐笔记录
    - 每笔卖出保存对应的买入批次信息(buy_date, buy_price, buy_shares)
    - 返回扁平化的交易对列表，而非按股票聚合

    参数:
        table_name: MySQL表名(pingan_normal_trade / pingan_margin_trade)
        account_tag: 账户标识(normal / margin)，为空则从表名推断

    返回:
        list[dict] 每个dict包含 insert_audit_from_trade 所需字段
        如果一笔卖出对应多笔买入(FIFO拆分)，会产生多条记录
    """
    if not account_tag:
        account_tag = "normal" if "normal" in table_name else "margin"

    trades = get_trades(table_name)

    positions = {}  # stock_code -> [{shares, price, date, comm_per_share}, ...]
    names = {}      # stock_code -> latest name
    results = []    # 扁平化交易对列表

    for row in trades:
        dt, abstract, code, name, shares, price, amount, comm, stamp, transfer, other = row
        names[code] = name

        if abstract == "红股派息":
            if code not in positions:
                positions[code] = []
            if shares > 0:
                positions[code].append({
                    "shares": shares, "price": Decimal("0"), "date": dt,
                    "comm_per_share": Decimal("0")
                })
            continue

        is_buy = abstract in BUY_ABSTRACTS
        is_sell = abstract in SELL_ABSTRACTS

        if not is_buy and not is_sell:
            if shares > 0:
                is_buy = True
            elif shares < 0:
                is_sell = True
            else:
                continue

        trade_shares = abs(shares)
        if trade_shares == 0:
            continue

        if code not in positions:
            positions[code] = []

        if is_buy:
            comm_per_share = abs(comm) / trade_shares if trade_shares else Decimal("0")
            transfer_per_share = abs(transfer) / trade_shares if trade_shares else Decimal("0")
            positions[code].append({
                "shares": trade_shares,
                "price": abs(amount) / trade_shares if trade_shares else price,
                "date": dt,
                "comm_per_share": comm_per_share + transfer_per_share,
            })

        elif is_sell:
            sell_shares_remaining = trade_shares
            buy_lots_info = []

            while sell_shares_remaining > 0 and positions.get(code):
                lot = positions[code][0]
                if lot["shares"] <= sell_shares_remaining:
                    buy_lots_info.append({
                        "buy_date": lot["date"],
                        "shares": int(lot["shares"]),
                        "price": float(lot["price"]),
                    })
                    sell_shares_remaining -= lot["shares"]
                    positions[code].pop(0)
                else:
                    buy_lots_info.append({
                        "buy_date": lot["date"],
                        "shares": int(sell_shares_remaining),
                        "price": float(lot["price"]),
                    })
                    lot["shares"] -= sell_shares_remaining
                    sell_shares_remaining = 0

            # 计算费用
            total_buy_fees = sum(
                lot["comm_per_share"] * Decimal(str(bl["shares"]))
                for lot, bl in zip(positions.get(code, []), buy_lots_info)
            )
            # 重新从buy_lots算买入成本(更准确)
            buy_amount_total = sum(Decimal(str(bl["price"])) * Decimal(str(bl["shares"])) for bl in buy_lots_info)
            sell_amount_total = Decimal(str(abs(amount))) if amount else Decimal("0")
            total_sell_fees = Decimal(str(abs(comm or 0) + abs(stamp or 0) + abs(transfer or 0) + abs(other or 0)))

            realized_pnl = sell_amount_total - buy_amount_total - total_sell_fees
            pnl_rate = round(float(realized_pnl) / float(buy_amount_total) * 100, 2) if buy_amount_total > 0 else 0

            # 取最早买入日期作为本笔交易的buy_date
            earliest_buy_date = ""
            if buy_lots_info:
                for bl in buy_lots_info:
                    bd = str(bl["buy_date"])[:10]
                    if not earliest_buy_date or bd < earliest_buy_date:
                        earliest_buy_date = bd

            # 计算持仓天数
            hold_days = 0
            try:
                sell_date_str = str(dt)[:10]
                if earliest_buy_date and sell_date_str:
                    bd_obj = datetime.strptime(earliest_buy_date, "%Y-%m-%d").date()
                    sd_obj = datetime.strptime(sell_date_str, "%Y-%m-%d").date()
                    hold_days = (sd_obj - bd_obj).days
            except Exception:
                pass

            # 计算加权平均买入价
            avg_buy_price = float(buy_amount_total) / int(trade_shares) if trade_shares > 0 else 0

            results.append({
                "account": account_tag,
                "stock_code": code,
                "stock_name": name or code,
                "buy_date": earliest_buy_date,
                "buy_price": round(avg_buy_price, 4),
                "buy_shares": trade_shares,
                "buy_amount": round(float(buy_amount_total), 2),
                "sell_date": str(dt)[:10],
                "sell_price": float(price) if price else 0,
                "sell_shares": trade_shares,
                "sell_amount": round(float(sell_amount_total), 2),
                "hold_days": hold_days,
                "realized_pnl": round(float(realized_pnl), 2),
                "pnl_rate": pnl_rate,
                "total_fees": round(float(total_sell_fees), 2),
                "sell_reason": abstract,
                "has_plan": False,
                "stop_price": 0,
                "total_assets": 0,
                "position_ratio": 0,
                # 额外信息: FIFO拆分细节
                "buy_lots": buy_lots_info,
            })

    return results
