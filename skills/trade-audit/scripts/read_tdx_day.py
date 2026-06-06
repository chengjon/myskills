#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取TDX本地day文件，增量写入MySQL tdx_data.day_kline表。

参考: D:\\MyData\\GITHUB\\Gitee\\mystocks\\mystocks\\bin\\comm\\read_tdx_day.py
数据源: D:\\mystocks\\tdx\\vipdoc_merged\\{sh,sz,bj}\\lday\\*.day

用法:
  # 全量导入所有day文件
  MYSQL_PWD=xxx python3 read_tdx_day.py

  # 只导入指定股票
  MYSQL_PWD=xxx python3 read_tdx_day.py --codes 000001,600172

  # 强制覆盖已有数据(先删再插)
  MYSQL_PWD=xxx python3 read_tdx_day.py --force --codes 300275

  # 试运行(不写入数据库)
  MYSQL_PWD=xxx python3 read_tdx_day.py --dry-run

增量逻辑:
  先查DB中该股票已有多少条记录，与day文件记录数对比:
  - DB记录数 == 文件记录数 → 跳过
  - DB记录数 < 文件记录数 → 只追加新增记录
  - --force → 先删后全量插入
"""

import struct
import os
import sys
import glob
import argparse
from datetime import datetime

import pymysql

# ── 配置 ──────────────────────────────────────────────
TDX_BASE_DIR = "/mnt/d/mystocks/tdx/vipdoc_merged"
MYSQL_HOST = os.environ.get("MYSQL_HOST", "")
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_DB = "tdx_data"
MYSQL_TABLE = "day_kline"

# TDX day文件32字节记录格式: date(I) open(I) high(I) low(I) close(I) amount(f) volume(I) reserved(I)
DAY_RECORD_FMT = "IIIIIfII"
DAY_RECORD_SIZE = struct.calcsize(DAY_RECORD_FMT)

# 市场→子目录映射
MARKET_DIRS = {
    "sh": ["sh"],   # 沪市: 60xxxx, 68xxxx, 000xxx(指数)
    "sz": ["sz"],   # 深市: 00xxxx, 30xxxx
    "bj": ["bj"],   # 北交所: 8xxxxx, 4xxxxx
}


def read_day_file(file_path: str) -> list[dict]:
    """
    读取TDX日线文件并解析数据。
    参考: read_tdx_day.py (by CHENGJUN)

    参数:
        file_path: 日线文件路径

    返回:
        list[dict]: 每条记录包含 date, open, high, low, close, amount, vol
    """
    cols = ["date", "open", "high", "low", "close", "amount", "vol"]

    with open(file_path, "rb") as f:
        buf = f.read()

    items = [
        {
            cols[0]: str(record[0]),                        # 日期 YYYYMMDD字符串
            cols[1]: record[1] / 100.0,                     # 开盘价
            cols[2]: record[2] / 100.0,                     # 最高价
            cols[3]: record[3] / 100.0,                     # 最低价
            cols[4]: record[4] / 100.0,                     # 收盘价
            cols[5]: record[5],                              # 成交额(float)
            cols[6]: record[6] / 100.0,                     # 成交量(手)
        }
        for record in struct.iter_unpack(DAY_RECORD_FMT, buf)
    ]

    return items


def get_market(code: str) -> str:
    """根据股票代码判断市场目录"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith(("0", "3", "1")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    return "sz"  # 默认深市


def get_day_filepath(code: str) -> str | None:
    """根据股票代码查找day文件路径"""
    market = get_market(code)
    path = os.path.join(TDX_BASE_DIR, market, "lday", f"{market}{code}.day")
    return path if os.path.isfile(path) else None


def scan_all_day_files() -> dict[str, str]:
    """扫描所有day文件，返回 {code: filepath}"""
    result = {}
    for market in ["sh", "sz", "bj"]:
        ldir = os.path.join(TDX_BASE_DIR, market, "lday")
        if not os.path.isdir(ldir):
            continue
        for f in glob.glob(os.path.join(ldir, f"{market}*.day")):
            fname = os.path.basename(f)
            code = fname.replace(f"{market}", "").replace(".day", "")
            # 过滤指数/债券等: 只保留6位纯数字
            if code.isdigit() and len(code) == 6:
                result[code] = f
    return result


def get_db_connection():
    """获取MySQL连接"""
    pwd = os.environ.get("MYSQL_PWD", "")
    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=pwd,
        database=MYSQL_DB, charset="utf8mb4",
        autocommit=False
    )


def get_existing_count(cur, code: str) -> int:
    """查询DB中某股票已有多少条记录"""
    cur.execute(
        f"SELECT COUNT(*) FROM {MYSQL_TABLE} WHERE stock_code = %s",
        (code,)
    )
    return cur.fetchone()[0]


def get_existing_max_date(cur, code: str) -> str | None:
    """查询DB中某股票最新日期"""
    cur.execute(
        f"SELECT MAX(trade_date) FROM {MYSQL_TABLE} WHERE stock_code = %s",
        (code,)
    )
    result = cur.fetchone()[0]
    return str(result) if result else None


def insert_records(cur, code: str, records: list[dict], force: bool = False):
    """批量插入记录(INSERT IGNORE幂等)"""
    if not records:
        return 0

    if force:
        cur.execute(
            f"DELETE FROM {MYSQL_TABLE} WHERE stock_code = %s",
            (code,)
        )

    sql = f"""
        INSERT IGNORE INTO {MYSQL_TABLE}
        (stock_code, trade_date, open, high, low, close_price, amount, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows = []
    for r in records:
        # 日期格式转换: "20241029" → "2024-10-29"
        d = r["date"]
        trade_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        rows.append((
            code,
            trade_date,
            r["open"],
            r["high"],
            r["low"],
            r["close"],
            r["amount"],
            r["vol"],
        ))

    cur.executemany(sql, rows)
    return cur.rowcount


def import_one(code: str, conn, force: bool = False, dry_run: bool = False) -> dict:
    """
    导入单只股票的day文件，增量写入。

    返回: {code, file_records, db_records, new_records, action}
    """
    filepath = get_day_filepath(code)
    if not filepath:
        return {"code": code, "action": "no_file", "file_records": 0, "db_records": 0, "new_records": 0}

    # 读取day文件
    records = read_day_file(filepath)
    file_count = len(records)

    cur = conn.cursor()

    if dry_run:
        db_count = get_existing_count(cur, code)
        action = "skip" if db_count == file_count and not force else "would_insert"
        return {"code": code, "action": action, "file_records": file_count, "db_records": db_count,
                "new_records": file_count - db_count if not force else file_count}

    if force:
        # 强制模式: 先删后全量插入
        inserted = insert_records(cur, code, records, force=True)
        conn.commit()
        return {"code": code, "action": "force_replace", "file_records": file_count,
                "db_records": 0, "new_records": inserted}

    # 增量模式
    db_count = get_existing_count(cur, code)
    if db_count >= file_count:
        return {"code": code, "action": "skip", "file_records": file_count,
                "db_records": db_count, "new_records": 0}

    # 只追加新增部分
    if db_count > 0:
        max_date = get_existing_max_date(cur, code)
        # 过滤出日期大于max_date的记录
        if max_date:
            # max_date格式 "2024-10-29", records中日期格式 "20241029"
            max_date_compact = max_date.replace("-", "")
            new_records = [r for r in records if r["date"] > max_date_compact]
        else:
            new_records = records
    else:
        new_records = records

    inserted = insert_records(cur, code, new_records)
    conn.commit()

    return {"code": code, "action": "append", "file_records": file_count,
            "db_records": db_count, "new_records": inserted}


def main():
    parser = argparse.ArgumentParser(description="读取TDX day文件增量写入MySQL")
    parser.add_argument("--codes", help="只导入指定股票，逗号分隔，如 000001,600172")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有数据(先删后插)")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写入数据库")
    parser.add_argument("--batch-size", type=int, default=100, help="每批提交的股票数(默认100)")
    args = parser.parse_args()

    # 确定要导入的股票列表
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        print("扫描day文件...")
        all_files = scan_all_day_files()
        codes = list(all_files.keys())
        print(f"发现 {len(codes)} 个day文件")

    if not codes:
        print("无day文件可导入")
        return

    conn = get_db_connection()
    stats = {"total": len(codes), "skip": 0, "append": 0, "force_replace": 0,
             "no_file": 0, "would_insert": 0, "total_new_rows": 0}

    for i, code in enumerate(codes, 1):
        result = import_one(code, conn, force=args.force, dry_run=args.dry_run)
        action = result["action"]
        stats[action] = stats.get(action, 0) + 1
        stats["total_new_rows"] += result.get("new_records", 0)

        if i % 200 == 0 or action not in ("skip",):
            print(f"  [{i}/{len(codes)}] {code}: {action} "
                  f"(文件={result['file_records']}, DB={result['db_records']}, 新增={result['new_records']})")

    conn.close()

    print(f"\n=== 导入完成 ===")
    print(f"总股票: {stats['total']}")
    print(f"跳过(已存在): {stats.get('skip', 0)}")
    print(f"追加: {stats.get('append', 0)}")
    print(f"强制覆盖: {stats.get('force_replace', 0)}")
    print(f"无文件: {stats.get('no_file', 0)}")
    print(f"新增行数: {stats['total_new_rows']}")


if __name__ == "__main__":
    main()
