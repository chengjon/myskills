# TdxQuant 数据需求清单

> 日期：2026-06-03（V3.1更新）
> 来源：`/opt/iflow/TdxQuant/docs/TdxQuant数据能力清单.md`
> 用途：V3复盘审计引擎的数据源替代方案，替代腾讯/新浪网络API

## 概述

TdxQuant是Windows端通达信量化数据接口，可替代WSL环境受限的网络API（东财push2封锁、新浪K线456、curl_cffi TLS指纹被识别）。

**路径**: `/opt/iflow/TdxQuant/`
**运行环境**: Windows Python 3.12，依赖TDX客户端DLL+客户端在线
**API入口**: `tqcenter.tq`（不是 `TdxQuant.TdxQuant`），调用前必须 `tq.initialize(__file__)`

## WSL调用约束（关键 Pitfall）

⚠️ **root用户无法执行Windows .exe**：WSL2中直接调用 `/mnt/c/.../python.exe` 返回 "Invalid argument"。这是WSL2 interop限制，与binfmt_misc无关（WSLInterop已启用）。

**解决方案**：
1. **su到john用户**：`su - john -c '/mnt/c/.../python.exe -c "..."'` — 简单但需john用户环境配置好TdxQuant
2. **bridge_http模式**：在Windows侧启动TdxQuant HTTP bridge服务，WSL通过HTTP请求获取数据
3. **纯Python fallback（推荐主路径）**：用腾讯K线API + fetch_market_data.py自带的calc_ma/calc_macd/calc_boll等函数计算指标，完全不依赖Windows。历史交易审计不需要实时行情

**DLL路径**：`TPythClient.dll` 由 `tqcenter.py` 中 `Path(__file__).resolve().parents[1] / 'TPythClient.dll'` 定位。从Windows Python通过WSL UNC路径(`\\wsl.localhost\Ubuntu\...`)运行时，DLL路径解析可能失败。

## 核心API对照

| 数据需求 | TdxQuant API | 返回格式 | V3审计用途 |
|----------|-------------|----------|-----------|
| 日K线(MA/MACD/RSI/BOLL) | `tq.get_market_data(stock_list, period='1d', dividend_type='front', count=-1)` | DataFrame(OHLCV) | B组入场环境 |
| 技术指标 | `tq.formula_set_data_info()` + `tq.formula_zb(name, arg, xsflag)` | dict{key: [values]} | B组MA/MACD/RSI/BOLL/ATR |
| 行业涨跌幅排序 | `tq.get_sector_list()` + 遍历 | 586板块 | B组行业排名 |
| 股票信息(63字段) | `tq.get_stock_info()` | DataFrame | 行业分类+基本面 |
| 指数行情 | 统一接口`999999.SH` | 同个股 | B组大盘环境 |
| 事后验证K线 | 同日K线，指定日期范围 | 无620根限制 | F组T+5/10/20/60 |
| 批量200+只 | `tq.get_market_data(stock_list=[...])` | **性能待测** | batch_audit |

## 优势 vs 网络API

| 对比项 | TdxQuant | 网络API(腾讯/新浪) |
|--------|----------|-------------------|
| K线数量限制 | 无限制(一次取全部) | 腾讯620根/次，需分批 |
| WSL可用性 | ❌ 仅Windows(需john用户或bridge) | ✅ 腾讯可用，新浪受限 |
| 数据新鲜度 | 盘后下载(延迟待确认) | 实时/准实时 |
| 北交所920xxx | 需确认 | 腾讯不支持名称 |
| 历史深度 | 2015至今(需确认是否已下载) | 腾讯可取2015至今(分批) |
| 依赖 | TDX客户端在线+DLL | 无 |

## 推荐架构

```
主路径: 腾讯K线API + Python自算指标(fetch_market_data.py)
增强路径: TdxQuant via john用户/bridge_http(可选，需要Windows侧通达信在线)
降级: 新浪API(仅腾讯不可用时)
```

## 完整需求清单

详见 `mynotes/学习材料/复盘方法/TdxQuant数据需求清单.md`（Obsidian，12,832字）
