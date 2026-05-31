# .so Compatibility and HTTP Fallback

## Problem

The core scripts (`fetch_stock_data.py`, `analyze_stock.py`) are wrapper entry points that import compiled `.so` modules (e.g. `core_fetch_stock_data_e73d4d80.cpython-313-x86_64-linux-gnu.so`). These are compiled for **Python 3.13**. If the runtime is Python 3.12 or another version, `import` will fail with `ImportError: magic number` or similar.

## Fallback: Direct HTTP + Manual Calculation

When `.so` modules cannot load, use this pattern:

### Fetch Real-Time Data (Sina)

```python
import urllib.request, json

def fetch_sina(code):
    """Fetch real-time quote from Sina.
    For SH codes prefix with 'sh', for SZ prefix with 'sz'."""
    if code.startswith(('6', '9')):
        prefix = 'sh'
    else:
        prefix = 'sz'
    url = f"http://hq.sinajs.cn/list={prefix}{code}"
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("gbk")
    # Parse the comma-separated fields
    fields = raw.split('"')[1].split(",")
    return {
        "name": fields[0],
        "open": float(fields[1]),
        "prev_close": float(fields[2]),
        "price": float(fields[3]),
        "high": float(fields[4]),
        "low": float(fields[5]),
        "volume": int(fields[8]),
        "amount": float(fields[9]),
        "date": fields[30],
        "time": fields[31],
    }
```

### Fetch Historical K-Line (East Money)

```python
def fetch_kline(code, days=30):
    """Fetch daily K-line from East Money.
    Market: 1=SH, 0=SZ"""
    if code.startswith(('6', '9')):
        market = 1
    else:
        market = 0
    url = (
        f"http://push2his.eastmoney.com/api/qt/stock/kline"
        f"?secid={market}.{code}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&end=20500101&lmt={days}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    rows = data["data"]["klines"]
    # Each row: "date,open,close,high,low,volume,amount,amplitude,pct_change,change,turnover"
    return [dict(zip(
        ["date","open","close","high","low","volume","amount","amplitude","pct_change","change","turnover"],
        r.split(",")
    )) for r in rows]
```

### Calculate Technical Indicators (pandas/numpy)

```python
import pandas as pd, numpy as np

def calc_indicators(klines):
    df = pd.DataFrame(klines)
    for col in ["open","close","high","low","volume"]:
        df[col] = df[col].astype(float)

    # MA
    for n in [5, 10, 20, 60]:
        df[f"ma{n}"] = df["close"].rolling(n).mean()

    # MACD (12,26,9)
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])

    # RSI (14)
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))

    return df
```

## Xiaping Download Gotcha

The `/api/skills/{id}/download` endpoint does NOT return a zip file directly. It returns JSON:

```json
{
  "success": true,
  "data": { ... },
  "skill_meta": { "download_url": "https://...", "skill_md_url": "..." }
}
```

You must parse the JSON, extract `skill_meta.download_url`, then fetch that URL to get the actual zip.

## Decision Record

- 2026-05-31: .so files kept (user chose option A: preserve for future Python 3.13 compat)
- 2026-05-31: HTTP fallback documented as the primary path when .so cannot load
