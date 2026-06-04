#!/usr/bin/env python3
"""
TdxQuant 数据适配层
- 通过 Windows Python 调用 TdxQuant 获取K线/指标/实时行情
- 适配 fetch_market_data.py 的接口
- WSL下通过 /mnt/c/.../python.exe 调用

依赖: TdxQuant(Windows), pyyaml
"""

import json
import os
import subprocess
import sys
from typing import Optional

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "review_config.yaml")


def _load_tdxquant_config() -> dict:
    """读取TdxQuant配置"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    return cfg.get("data_sources", {}).get("tdxquant", {})


def _build_python_command(script: str) -> list:
    """构建Windows Python命令"""
    tdx_cfg = _load_tdxquant_config()
    python_path = tdx_cfg.get("python_path",
        "/mnt/c/Users/John Cheng/AppData/Local/Programs/Python/Python312/python.exe")
    base_dir = tdx_cfg.get("base_dir", "/opt/iflow/TdxQuant")

    # 将WSL路径转为Windows路径
    if python_path.startswith("/mnt/c/"):
        win_python = "C:" + python_path[6:]
    else:
        win_python = python_path

    # TdxQuant脚本路径(Windows侧)
    script_path = os.path.join(base_dir, "scripts", script)
    if script_path.startswith("/mnt/"):
        # 转为Windows路径
        parts = script_path.replace("/mnt/", "").split("/", 1)
        win_script = parts[0].upper() + ":\\" + parts[1].replace("/", "\\")
    else:
        win_script = script_path

    return [win_python, "-c", f"import sys; sys.path.insert(0, r'{base_dir}'); exec(open(r'{win_script}').read())"]


def _run_tdxquant_script(script_code: str, timeout: int = 30) -> dict:
    """
    通过Windows Python执行TdxQuant脚本
    script_code: Python代码字符串
    返回: 解析后的JSON结果
    """
    tdx_cfg = _load_tdxquant_config()
    python_path = tdx_cfg.get("python_path",
        "/mnt/c/Users/John Cheng/AppData/Local/Programs/Python/Python312/python.exe")

    # WSL → Windows路径转换
    if python_path.startswith("/mnt/"):
        drive = python_path[5]  # c
        rest = python_path[7:]  # Users/...
        win_python = f"{drive.upper()}:\\{rest.replace('/', '\\')}"
    else:
        win_python = python_path

    base_dir = tdx_cfg.get("base_dir", "/opt/iflow/TdxQuant")
    if base_dir.startswith("/mnt/"):
        drive = base_dir[5]
        rest = base_dir[7:]
        win_base = f"{drive.upper()}:\\{rest.replace('/', '\\')}"
    else:
        win_base = base_dir

    # 构建完整脚本(TdxQuant初始化+用户代码)
    full_script = f"""
import sys
sys.path.insert(0, r'{win_base}')
import json
{script_code}
"""

    try:
        result = subprocess.run(
            [win_python, "-c", full_script],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return {"error": f"TdxQuant error: {result.stderr[:500]}"}

        output = result.stdout.strip()
        if output:
            # 尝试解析JSON
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"raw": output}
        return {"error": "empty output"}

    except subprocess.TimeoutExpired:
        return {"error": f"TdxQuant timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"error": f"Python not found: {win_python}"}
    except Exception as e:
        return {"error": f"TdxQuant exception: {e}"}


# ============================================================
# 公开接口: 与 fetch_market_data.py 对齐
# ============================================================

def tdx_fetch_kline(stock_code: str, period: str = "1d",
                    start_date: str = "", end_date: str = "",
                    count: int = -1, dividend_type: int = 1) -> list:
    """
    获取K线数据
    stock_code: 6位代码(如000539)，自动加.SZ/.SH/.BJ后缀
    period: "1d"(日线) / "5m"(5分钟)
    start_date/end_date: YYYYMMDD
    count: -1=无限制
    dividend_type: 0=不复权 1=前复权 2=后复权
    返回: list[dict] [{"date":"2025-01-01","open":...,"high":...,"low":...,"close":...,"volume":...,"amount":...}]
    """
    tdx_code = _to_tdx_code(stock_code)
    period_map = {"1d": "1d", "day": "1d", "240": "1d", "5m": "5m", "5min": "5m"}
    tdx_period = period_map.get(period, "1d")

    script = f"""
from TdxQuant import TdxQuant
tq = TdxQuant()
tq.connect()
try:
    klines = tq.get_market_data(
        stock_code='{tdx_code}',
        stock_period='{tdx_period}',
        start_time='{start_date}' if '{start_date}' else '',
        end_time='{end_date}' if '{end_date}' else '',
        count={count},
        dividend_type={dividend_type}
    )
    result = []
    if klines is not None and len(klines) > 0:
        for idx, row in klines.iterrows():
            result.append({{
                "date": str(idx)[:10],
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("volume", 0)),
                "amount": float(row.get("amount", 0)),
            }})
    print(json.dumps(result))
finally:
    tq.disconnect()
"""
    data = _run_tdxquant_script(script, timeout=60)
    if "error" in data:
        return []
    if "raw" in data:
        return []
    return data if isinstance(data, list) else []


def tdx_fetch_realtime(stock_code: str) -> dict:
    """获取实时行情快照"""
    tdx_code = _to_tdx_code(stock_code)
    script = f"""
from TdxQuant import TdxQuant
tq = TdxQuant()
tq.connect()
try:
    snap = tq.get_market_snapshot('{tdx_code}')
    if snap is not None and len(snap) > 0:
        row = snap.iloc[0] if hasattr(snap, 'iloc') else snap
        result = {{
            "price": float(row.get("price", 0)),
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "pre_close": float(row.get("pre_close", 0)),
            "volume": int(row.get("volume", 0)),
            "amount": float(row.get("amount", 0)),
            "change_pct": float(row.get("change_pct", 0)),
        }}
        print(json.dumps(result))
finally:
    tq.disconnect()
"""
    data = _run_tdxquant_script(script)
    if "error" in data:
        return {}
    return data if isinstance(data, dict) else {}


def tdx_formula_zb(stock_code: str, formula_name: str,
                   formula_arg: str = "", stock_period: str = "1d",
                   start_date: str = "", end_date: str = "",
                   xsflag: int = 6) -> dict:
    """
    调用 formula_zb 计算技术指标
    两步调用: formula_set_data_info() + formula_zb()
    返回: dict {"MA5": [...], "MA10": [...], ...}
    """
    tdx_code = _to_tdx_code(stock_code)
    script = f"""
from TdxQuant import TdxQuant
tq = TdxQuant()
tq.connect()
try:
    tq.formula_set_data_info(
        stock_code='{tdx_code}',
        stock_period='{stock_period}',
        start_time='{start_date}' if '{start_date}' else '',
        end_time='{end_date}' if '{end_date}' else '',
        dividend_type=1
    )
    result = tq.formula_zb(
        formula_name='{formula_name}',
        formula_arg='{formula_arg}',
        xsflag={xsflag}
    )
    if result is not None:
        out = {{}}
        for key, values in result.items():
            out[str(key)] = [str(v) for v in values]
        print(json.dumps(out))
finally:
    tq.disconnect()
"""
    data = _run_tdxquant_script(script)
    if "error" in data:
        return {}
    return data if isinstance(data, dict) else {}


def tdx_get_stock_info(stock_code: str) -> dict:
    """获取股票基本信息(行业分类等)"""
    tdx_code = _to_tdx_code(stock_code)
    script = f"""
from TdxQuant import TdxQuant
tq = TdxQuant()
tq.connect()
try:
    info = tq.get_stock_info('{tdx_code}')
    if info is not None and len(info) > 0:
        row = info.iloc[0] if hasattr(info, 'iloc') else info
        result = dict(row)
        # 转为可序列化
        out = {{k: str(v) if not isinstance(v, (int, float)) else v for k, v in result.items()}}
        print(json.dumps(out))
finally:
    tq.disconnect()
"""
    data = _run_tdxquant_script(script)
    if "error" in data:
        return {}
    return data if isinstance(data, dict) else {}


def tdx_get_trading_dates(start_date: str = "", end_date: str = "") -> list:
    """获取交易日历"""
    script = f"""
from TdxQuant import TdxQuant
tq = TdxQuant()
tq.connect()
try:
    dates = tq.get_trading_dates(market='SH', start_time='{start_date}', end_time='{end_date}')
    if dates is not None:
        result = [str(d)[:10] for d in dates]
        print(json.dumps(result))
finally:
    tq.disconnect()
"""
    data = _run_tdxquant_script(script)
    if "error" in data:
        return []
    return data if isinstance(data, list) else []


# ============================================================
# 辅助函数
# ============================================================

def _to_tdx_code(code: str) -> str:
    """
    6位代码转TdxQuant格式(带.市场后缀)
    000xxx/001xxx/002xxx/003xxx → .SZ
    600xxx/601xxx/603xxx/605xxx → .SH
    688xxx → .SH
    920xxx → .BJ
    """
    if "." in code:
        return code  # 已有后缀

    code6 = code[:6]
    if code6.startswith(("000", "001", "002", "003", "004", "300", "301")):
        return f"{code6}.SZ"
    elif code6.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{code6}.SH"
    elif code6.startswith("920"):
        return f"{code6}.BJ"
    elif code6.startswith("8"):
        return f"{code6}.BJ"
    else:
        return f"{code6}.SZ"  # 默认深市


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TdxQuant数据适配层")
    parser.add_argument("command", choices=["kline", "realtime", "info", "formula", "dates"])
    parser.add_argument("--code", required=True, help="股票代码")
    parser.add_argument("--start", default="", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default="", help="结束日期 YYYYMMDD")
    parser.add_argument("--formula", default="MA", help="指标名称")
    parser.add_argument("--arg", default="5,10,20,60", help="指标参数")
    args = parser.parse_args()

    if args.command == "kline":
        data = tdx_fetch_kline(args.code, start_date=args.start, end_date=args.end)
        print(f"获取 {len(data)} 根K线")
        if data:
            print(f"最新: {data[-1]}")

    elif args.command == "realtime":
        data = tdx_fetch_realtime(args.code)
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "formula":
        data = tdx_formula_zb(args.code, args.formula, args.arg,
                              start_date=args.start, end_date=args.end)
        print(f"指标: {list(data.keys())}")
        for k, v in data.items():
            vals = [x for x in v if x and x != "nan"]
            print(f"  {k}: {vals[-5:] if vals else '无数据'}")

    elif args.command == "info":
        data = tdx_get_stock_info(args.code)
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "dates":
        data = tdx_get_trading_dates(args.start, args.end)
        print(f"共 {len(data)} 个交易日")
        if data:
            print(f"范围: {data[0]} ~ {data[-1]}")
