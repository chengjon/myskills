#!/usr/bin/env python3
"""持仓日报解析器 — 每日18:00由cron触发

扫描 mystocks/持仓/ 下最新的持仓文件，解析内容：
1. 结构化汇总表 → 写入MySQL holdings + account_overview
2. 图片引用 → 复制到 pic/ 按日期+账户命名归档
3. 更新 index.md

用法:
  MYSQL_PWD=xxx python holdings_daily.py                    # 自动扫描最新
  MYSQL_PWD=xxx python holdings_daily.py --date 20260603    # 指定日期
  MYSQL_PWD=xxx python holdings_daily.py --all              # 处理所有未入库的
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime, date
from decimal import Decimal

import pymysql

# ─── 配置 ──────────────────────────────────────────────────

VAULT_BASE = '/mnt/c/Users/John Cheng/Documents/Obsidian Vault'
HOLDINGS_DIR = os.path.join(VAULT_BASE, 'mystocks', '持仓')
PIC_DIR = os.path.join(HOLDINGS_DIR, 'pic')
INDEX_FILE = os.path.join(HOLDINGS_DIR, 'index.md')

MYSQL_HOST = '192.168.123.104'
MYSQL_PORT = 3306
MYSQL_USER = 'root'
MYSQL_DB = 'hermes'

# 账户识别关键词
ACCOUNT_MAP = {
    '平安两融': ['两融', '平安两融', '融资融券', '302199966809'],
    '平安普通': ['平安普通', '普通账户', '302119114015'],
    '国金QMT': ['QMT', '国金', '国金QMT', '8886873933'],
}


# ─── 文件扫描 ──────────────────────────────────────────────

def find_daily_files():
    """找到所有 YYYYMMDD.md 文件，按日期排序"""
    files = []
    for f in os.listdir(HOLDINGS_DIR):
        if re.match(r'^\d{8}\.md$', f):
            dt = datetime.strptime(f[:8], '%Y%m%d').date()
            files.append((dt, os.path.join(HOLDINGS_DIR, f)))
    files.sort(key=lambda x: x[0])
    return files


def find_subdir_files():
    """找到 YYYYMMDD/ 子目录下的md文件"""
    files = []
    for d in os.listdir(HOLDINGS_DIR):
        dp = os.path.join(HOLDINGS_DIR, d)
        if os.path.isdir(dp) and re.match(r'^\d{8}$', d):
            dt = datetime.strptime(d, '%Y%m%d').date()
            for f in os.listdir(dp):
                if f.endswith('.md'):
                    files.append((dt, os.path.join(dp, f), f))
    files.sort(key=lambda x: (x[0], x[2]))
    return files


def find_attachment(filename):
    """在vault根目录查找附件"""
    target = os.path.join(VAULT_BASE, filename)
    if os.path.exists(target):
        return target
    # 尝试常见附件目录
    for subdir in ['', 'attachments', 'pic']:
        p = os.path.join(VAULT_BASE, subdir, filename)
        if os.path.exists(p):
            return p
    return None


# ─── 图片归档 ──────────────────────────────────────────────

def archive_images(content, trade_date):
    """解析图片引用，按账户归档到pic/目录"""
    os.makedirs(PIC_DIR, exist_ok=True)
    date_str = trade_date.strftime('%Y%m%d')

    # 按段落分割，识别每个图片所属账户
    # 账户标注一旦设置，持续到下一个标注或文件结束（空行不重置）
    lines = content.split('\n')
    current_account = '未分类'
    archived = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue  # 空行不重置账户

        # 检测行内账户标注（可能和图片在同一行）
        for acct, keywords in ACCOUNT_MAP.items():
            for kw in keywords:
                if kw in line_stripped:
                    current_account = acct
                    break

        # 提取图片引用 ![[xxx.png]] 或 ![[xxx.png|695]]
        imgs = re.findall(r'!\[\[([^\]|]+\.(?:png|jpg|jpeg|gif))', line_stripped)
        for img_name in imgs:
            src = find_attachment(img_name)
            if not src:
                archived.append(f'  [MISS] {img_name} (附件未找到)')
                continue

            # 目标文件名: YYYYMMDD_账户名.ext
            ext = os.path.splitext(img_name)[1]
            # 如果同账户多张图，追加序号
            base = f'{date_str}_{current_account}{ext}'
            dst = os.path.join(PIC_DIR, base)

            # 如果已存在，追加序号
            idx = 1
            while os.path.exists(dst):
                base = f'{date_str}_{current_account}_{idx}{ext}'
                dst = os.path.join(PIC_DIR, base)
                idx += 1

            shutil.copy2(src, dst)
            archived.append(f'  [OK] {os.path.basename(dst)} ({current_account})')

    return archived


# ─── 汇总表解析 ────────────────────────────────────────────

def parse_markdown_table(lines, header_marker='|'):
    """解析markdown表格为字典列表"""
    rows = []
    headers = None

    for line in lines:
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.split('|')]
        cells = [c for c in cells if c]  # 去空

        # 跳过分隔行
        if all(set(c) <= set('-: ') for c in cells):
            continue

        if headers is None:
            headers = cells
            continue

        if headers and len(cells) >= len(headers):
            row = {}
            for i, h in enumerate(headers):
                row[h] = cells[i] if i < len(cells) else ''
            rows.append(row)

    return headers, rows


def parse_account_overview(content):
    """解析账户概览表 → account_overview"""
    results = []
    lines = content.split('\n')

    # 找"账户概览"后的表格
    in_section = False
    table_lines = []

    for i, line in enumerate(lines):
        if '账户概览' in line or '账户' in line and '概览' in line:
            in_section = True
            table_lines = []
            continue

        if in_section:
            if line.strip() == '' and table_lines:
                in_section = False
                continue
            if '|' in line:
                table_lines.append(line)

    if not table_lines:
        return results

    headers, rows = parse_markdown_table(table_lines)
    if not rows:
        return results

    # 判断是合并表（含账户列）还是单账户表
    has_account_col = headers and any('账户' in h for h in headers)

    for row in rows:
        if has_account_col:
            acct = row.get('账户', '')
            balance = _parse_num(row.get('余额', '0'))
            available = _parse_num(row.get('可用', '0'))
            withdrawable = _parse_num(row.get('可取', '0'))
            in_transit = _parse_num(row.get('在途', '0'))
            mv = _parse_num(row.get('市值', row.get('参考市值', '0')))
            total = _parse_num(row.get('总资产', '0'))
            pnl = _parse_num(row.get('盈亏', row.get('持仓盈亏', '0')))
        else:
            # 单账户表
            acct = '未知'
            balance = _parse_num(row.get('人民币余额', row.get('余额', '0')))
            available = _parse_num(row.get('可用', '0'))
            withdrawable = _parse_num(row.get('可取', '0'))
            in_transit = _parse_num(row.get('在途', '0'))
            mv = _parse_num(row.get('参考市值', row.get('市值', '0')))
            total = _parse_num(row.get('总资产', '0'))
            pnl = _parse_num(row.get('盈亏', row.get('持仓盈亏', row.get('盈亏', '0'))))

        results.append({
            'account_name': acct,
            'balance': balance,
            'available': available,
            'withdrawable': withdrawable,
            'in_transit': in_transit,
            'market_value': mv,
            'total_assets': total,
            'total_pnl': pnl,
        })

    return results


def parse_holdings_detail(content, account_name='未知'):
    """解析持仓明细表 → holdings"""
    results = []
    lines = content.split('\n')

    in_section = False
    table_lines = []

    for line in lines:
        if '持仓明细' in line:
            in_section = True
            table_lines = []
            continue

        if in_section:
            if line.strip() == '' and len(table_lines) > 2:
                in_section = False
                continue
            if '|' in line:
                table_lines.append(line)

    if not table_lines:
        return results

    headers, rows = parse_markdown_table(table_lines)
    if not rows:
        return results

    for row in rows:
        code = row.get('代码', row.get('证券代码', ''))
        name = row.get('名称', row.get('证券名称', ''))
        shares = int(_parse_num(row.get('持股', row.get('当前拥股', row.get('合计持股', '0')))))
        available = int(_parse_num(row.get('可用', row.get('可用数量', '0'))))
        cost = _parse_num(row.get('成本价', '0'))
        price = _parse_num(row.get('现价', row.get('最新价', '0')))
        mv = _parse_num(row.get('市值', row.get('总市值', '0')))
        pnl = _parse_num(row.get('浮动盈亏', row.get('盈亏', row.get('总盈亏', row.get('持仓盈亏', '0')))))
        pct = _parse_num(row.get('盈亏比例', row.get('盈亏%', '0')))

        status = row.get('状态', '持仓')

        if not code or len(code) < 6:
            continue
        # 跳过已清仓
        if '清仓' in status:
            continue

        results.append({
            'account_name': account_name,
            'stock_code': code,
            'stock_name': name,
            'shares': shares,
            'available': available,
            'cost_price': cost,
            'current_price': price,
            'market_value': mv,
            'floating_pnl': pnl,
            'pnl_pct': pct,
        })

    return results


def parse_consolidated_holdings(content):
    """解析汇总表的持仓明细（合并去重表）"""
    results = []
    lines = content.split('\n')

    in_section = False
    table_lines = []

    for line in lines:
        if '持仓明细' in line and '合并' in line:
            in_section = True
            table_lines = []
            continue

        if in_section:
            if line.strip() == '' and len(table_lines) > 2:
                break
            if '|' in line:
                table_lines.append(line)

    if not table_lines:
        return results

    headers, rows = parse_markdown_table(table_lines)
    if not rows:
        return results

    for row in rows:
        code = row.get('代码', '')
        name = row.get('名称', '')
        status = row.get('状态', '')

        if not code or len(code) < 6:
            continue
        if '清仓' in status:
            continue

        # 汇总表有多列账户持股
        for acct in ['平安普通', '平安两融', '国金QMT']:
            shares = int(_parse_num(row.get(acct, '0')))
            if shares <= 0:
                continue

            price = _parse_num(row.get('现价', '0'))
            mv = _parse_num(row.get('总市值', '0'))
            pnl = _parse_num(row.get('总盈亏', '0'))

            # 汇总表没有单独的成本价，从盈亏反推
            cost = price * shares / (shares + pnl / price) if price > 0 and shares > 0 else 0

            results.append({
                'account_name': acct,
                'stock_code': code,
                'stock_name': name,
                'shares': shares,
                'available': shares,
                'cost_price': round(cost, 4),
                'current_price': price,
                'market_value': mv,
                'floating_pnl': pnl,
                'pnl_pct': round(pnl / (cost * shares) * 100, 2) if cost > 0 and shares > 0 else 0,
            })

    return results


# ─── 数字解析 ──────────────────────────────────────────────

def _parse_num(s):
    """解析带逗号和百分号的数字"""
    if s is None:
        return Decimal('0')
    s = str(s).strip()
    s = s.replace(',', '').replace('，', '').replace('%', '').replace('+', '')
    s = s.replace(' ', '').strip()
    if not s or s == '-':
        return Decimal('0')
    try:
        return Decimal(s)
    except:
        return Decimal('0')


# ─── MySQL写入 ─────────────────────────────────────────────

def upsert_account(cur, trade_date, data):
    """写入account_overview"""
    sql = """
    INSERT INTO account_overview (date, account_name, balance, available, withdrawable, in_transit, market_value, total_assets, total_pnl)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        balance=VALUES(balance), available=VALUES(available), withdrawable=VALUES(withdrawable),
        in_transit=VALUES(in_transit), market_value=VALUES(market_value), total_assets=VALUES(total_assets), total_pnl=VALUES(total_pnl)
    """
    cur.execute(sql, (
        trade_date, data['account_name'], data['balance'], data['available'],
        data['withdrawable'], data['in_transit'], data['market_value'],
        data['total_assets'], data['total_pnl']
    ))


def upsert_holding(cur, trade_date, data):
    """写入holdings"""
    sql = """
    INSERT INTO holdings (date, account_name, stock_code, stock_name, shares, available, cost_price, current_price, market_value, floating_pnl, pnl_pct)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        shares=VALUES(shares), available=VALUES(available), cost_price=VALUES(cost_price),
        current_price=VALUES(current_price), market_value=VALUES(market_value),
        floating_pnl=VALUES(floating_pnl), pnl_pct=VALUES(pnl_pct)
    """
    cur.execute(sql, (
        trade_date, data['account_name'], data['stock_code'], data['stock_name'],
        data['shares'], data['available'], data['cost_price'], data['current_price'],
        data['market_value'], data['floating_pnl'], data['pnl_pct']
    ))


def check_date_exists(cur, trade_date):
    """检查某日数据是否已入库"""
    cur.execute("SELECT COUNT(*) FROM holdings WHERE date = %s", (trade_date,))
    return cur.fetchone()[0] > 0


def check_overview_exists(cur, trade_date):
    cur.execute("SELECT COUNT(*) FROM account_overview WHERE date = %s", (trade_date,))
    return cur.fetchone()[0] > 0


# ─── index.md更新 ──────────────────────────────────────────

def update_index(trade_date, accounts_data, holdings_count, img_count):
    """更新index.md追加当日记录"""
    if not os.path.exists(INDEX_FILE):
        return

    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查是否已有当日记录
    date_str = trade_date.strftime('%Y-%m-%d')
    if date_str in content:
        return

    # 在末尾追加
    lines = [f'\n## {date_str} 持仓日报\n']
    lines.append(f'> 自动解析 | 持仓{holdings_count}条 | 图片{img_count}张\n')

    # 账户概览
    if accounts_data:
        lines.append('\n| 账户 | 总资产 | 盈亏 |\n|------|--------|------|')
        for a in accounts_data:
            pnl = a['total_pnl']
            sign = '+' if pnl > 0 else ''
            lines.append(f"| {a['account_name']} | {a['total_assets']:,.2f} | {sign}{pnl:,.2f} |")

    lines.append(f'\n> 详见 [[mystocks/持仓/{trade_date.strftime("%Y%m%d")}.md]]\n')

    with open(INDEX_FILE, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# ─── 主流程 ────────────────────────────────────────────────

def process_date(cur, trade_date, force=False):
    """处理指定日期的持仓数据"""
    date_file = os.path.join(HOLDINGS_DIR, trade_date.strftime('%Y%m%d') + '.md')

    if not os.path.exists(date_file):
        # 尝试子目录
        subdir = os.path.join(HOLDINGS_DIR, trade_date.strftime('%Y%m%d'))
        if os.path.isdir(subdir):
            return process_subdir(cur, trade_date, subdir, force)
        print(f"  [SKIP] {trade_date} 无持仓文件")
        return False

    with open(date_file, 'r', encoding='utf-8') as f:
        content = f.read()

    if not content.strip():
        print(f"  [SKIP] {trade_date} 文件为空")
        return False

    has_table = '|' in content and '持仓' in content
    has_images = '![[' in content

    print(f"  表格: {'有' if has_table else '无'}, 图片: {'有' if has_images else '无'}")

    # 1. 图片归档
    img_results = []
    if has_images:
        img_results = archive_images(content, trade_date)
        for r in img_results:
            print(f"  {r}")

    # 2. 解析汇总表（如果有）
    accounts_data = []
    holdings_data = []

    if has_table:
        accounts_data = parse_account_overview(content)
        holdings_data = parse_consolidated_holdings(content)

        # 如果汇总表没有持仓明细，尝试解析单账户明细
        if not holdings_data:
            holdings_data = parse_holdings_detail(content)

    # 3. 写入MySQL
    wrote = False

    if accounts_data and (force or not check_overview_exists(cur, trade_date)):
        for a in accounts_data:
            upsert_account(cur, trade_date, a)
        print(f"  [DB] account_overview: {len(accounts_data)}条")
        wrote = True

    if holdings_data and (force or not check_date_exists(cur, trade_date)):
        for h in holdings_data:
            upsert_holding(cur, trade_date, h)
        print(f"  [DB] holdings: {len(holdings_data)}条")
        wrote = True

    if not has_table and has_images:
        print(f"  [INFO] 纯图片文件，已归档{len(img_results)}张，无法提取结构化数据")

    # 4. 更新index
    if wrote or img_results:
        update_index(trade_date, accounts_data, len(holdings_data), len(img_results))
        print(f"  [INDEX] 已更新")

    return wrote or len(img_results) > 0


def process_subdir(cur, trade_date, subdir, force=False):
    """处理子目录格式（如20260530/汇总-2026-05-30.md）"""
    accounts_data = []
    holdings_data = []
    img_results = []

    for f in sorted(os.listdir(subdir)):
        if not f.endswith('.md'):
            continue
        fp = os.path.join(subdir, f)
        with open(fp, 'r', encoding='utf-8') as fh:
            content = fh.read()

        print(f"  处理: {f}")

        # 图片归档
        if '![[' in content:
            imgs = archive_images(content, trade_date)
            img_results.extend(imgs)
            for r in imgs:
                print(f"    {r}")

        # 识别账户类型
        account_name = '未知'
        for acct, keywords in ACCOUNT_MAP.items():
            for kw in keywords:
                if kw in f or kw in content[:200]:
                    account_name = acct
                    break

        # 解析汇总表
        if '汇总' in f:
            accounts_data = parse_account_overview(content)
            holdings_data = parse_consolidated_holdings(content)
        else:
            # 单账户
            acct_data = parse_account_overview(content)
            for a in acct_data:
                a['account_name'] = account_name
            accounts_data.extend(acct_data)

            h = parse_holdings_detail(content, account_name)
            holdings_data.extend(h)

    # 写入MySQL
    wrote = False
    if accounts_data and (force or not check_overview_exists(cur, trade_date)):
        for a in accounts_data:
            upsert_account(cur, trade_date, a)
        print(f"  [DB] account_overview: {len(accounts_data)}条")
        wrote = True

    if holdings_data and (force or not check_date_exists(cur, trade_date)):
        for h in holdings_data:
            upsert_holding(cur, trade_date, h)
        print(f"  [DB] holdings: {len(holdings_data)}条")
        wrote = True

    if wrote or img_results:
        update_index(trade_date, accounts_data, len(holdings_data), len(img_results))
        print(f"  [INDEX] 已更新")

    return wrote or len(img_results) > 0


def main():
    parser = argparse.ArgumentParser(description='持仓日报解析器')
    parser.add_argument('--date', type=str, help='指定日期 YYYYMMDD')
    parser.add_argument('--all', action='store_true', help='处理所有未入库的日期')
    parser.add_argument('--force', action='store_true', help='强制覆盖已有数据')
    args = parser.parse_args()

    pwd = os.environ.get('MYSQL_PWD', '')
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                           password=pwd, database=MYSQL_DB, charset='utf8mb4')
    cur = conn.cursor()

    try:
        if args.date:
            dt = datetime.strptime(args.date, '%Y%m%d').date()
            print(f"=== 处理 {dt} ===")
            process_date(cur, dt, force=args.force)
            conn.commit()
        elif args.all:
            # 处理所有未入库日期
            daily_files = find_daily_files()
            subdir_files = find_subdir_files()

            all_dates = set()
            for dt, _ in daily_files:
                all_dates.add(dt)
            for dt, _, _ in subdir_files:
                all_dates.add(dt)

            processed = 0
            for dt in sorted(all_dates):
                if not args.force and check_date_exists(cur, dt) and check_overview_exists(cur, dt):
                    print(f"[SKIP] {dt} 已入库")
                    continue
                print(f"\n=== {dt} ===")
                if process_date(cur, dt, force=args.force):
                    conn.commit()
                    processed += 1

            print(f"\n共处理 {processed} 个新日期")
        else:
            # 默认：处理最新的
            daily_files = find_daily_files()
            if not daily_files:
                print("无持仓文件")
                return

            latest_dt, _ = daily_files[-1]
            print(f"=== 最新 {latest_dt} ===")
            process_date(cur, latest_dt, force=args.force)
            conn.commit()

    finally:
        conn.close()


if __name__ == '__main__':
    main()
