#!/usr/bin/env python3
"""
pytdx 15分钟K线数据适配器 (WSL端)

通过 su john -> Windows Python 调用 D:\\MyCode3\\TdxQuant\\scripts\\pytdx_kline.py
获取通达信行情服务器的15分钟K线数据。

用法:
  from pytdx_kline_adapter import fetch_15min_kline_pytdx
  klines = fetch_15min_kline_pytdx("000539", start="2024-07-22", end="2025-02-17")

数据范围: pytdx 15分钟K线可回溯到约2024-07-22 (~7200根)
"""

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

# Windows Python路径
_WIN_PYTHON = "/mnt/c/Users/John Cheng/AppData/Local/Programs/Python/Python312/python.exe"
# Linux用户名(用于su切换)
_LINUX_USER = "john"
# pytdx脚本路径(Windows路径)
_PYTDX_SCRIPT_WIN = r"D:\MyCode3\TdxQuant\scripts\pytdx_kline.py"


def fetch_15min_kline_pytdx(
    stock_code: str,
    start_date: str = "",
    end_date: str = "",
    timeout: int = 120,
) -> List[Dict]:
    """
    通过Windows Python + pytdx获取15分钟K线

    Args:
        stock_code: 6位股票代码(如"000539")
        start_date: 起始日期(如"2024-07-22")
        end_date: 结束日期(如"2025-02-17")
        timeout: 超时秒数

    Returns:
        List[Dict]: K线数据 [{datetime, open, high, low, close, volume, amount}, ...]
    """
    cmd_parts = [
        f'su - {_LINUX_USER} -c',
        f'\'"{_WIN_PYTHON}" "{_PYTDX_SCRIPT_WIN}"',
        f'--code {stock_code[:6]}',
    ]
    if start_date:
        cmd_parts.append(f'--start {start_date}')
    if end_date:
        cmd_parts.append(f'--end {end_date}')
    cmd_parts.append("\'")

    cmd = " ".join(cmd_parts)

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace"
        )

        if result.returncode != 0:
            return []

        output = result.stdout.strip()
        if not output:
            return []

        # 解析JSON
        data = json.loads(output)
        if isinstance(data, dict) and "error" in data:
            return []

        return data if isinstance(data, list) else []

    except subprocess.TimeoutExpired:
        return []
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="pytdx 15分钟K线获取(WSL端)")
    parser.add_argument("--code", required=True, help="股票代码")
    parser.add_argument("--start", default="", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    klines = fetch_15min_kline_pytdx(args.code, args.start, args.end)
    print(f"获取 {len(klines)} 根15分钟K线")
    if klines:
        print(f"范围: {klines[0]['datetime']} ~ {klines[-1]['datetime']}")
        for k in klines[:3]:
            print(f"  {k['datetime']} O:{k['open']} H:{k['high']} L:{k['low']} C:{k['close']}")
