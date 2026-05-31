#!/usr/bin/env python3
"""盘中监控数据采集脚本 - 从新浪+东财获取市场全貌数据"""
import urllib.request, json, re, sys
from datetime import datetime

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://finance.sina.com.cn/"}

def fetch_indices():
    """获取大盘指数"""
    url = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000300,sh000016,sz399005"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode("gbk")
    indices = {}
    for line in text.strip().split("\n"):
        if '="' in line:
            cid, data = line.split('="')
            code = cid.split("hq_str_")[1]
            fields = data.rstrip('";').split(",")
            if len(fields) > 30:
                price = float(fields[3]); prev = float(fields[2])
                indices[code] = {
                    "name": fields[0], "price": price, "prev_close": prev,
                    "chg": round(price - prev, 2), "chg_pct": round((price-prev)/prev*100, 2),
                    "high": fields[4], "low": fields[5],
                    "amount": round(float(fields[9])/1e8, 0)
                }
    return indices

def fetch_market_stats():
    """获取全市场涨跌统计"""
    up = down = flat = limit_up = limit_down = 0
    all_stocks = []
    for page in range(1, 75):
        try:
            url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=80&sort=changepercent&asc=0&node=hs_a&symbol=&_s_r_a=auto"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if not data: break
            for s in data:
                chg = float(s.get("changepercent",0))
                if chg > 0: up += 1
                elif chg < 0: down += 1
                else: flat += 1
                if chg >= 9.9: limit_up += 1
                if chg <= -9.9: limit_down += 1
            all_stocks.extend(data)
        except: break
    for page in range(1, 5):
        try:
            url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=80&sort=changepercent&asc=1&node=hs_a&symbol=&_s_r_a=auto"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if not data: break
            seen = {s.get("symbol") for s in all_stocks}
            for s in data:
                if s.get("symbol") not in seen:
                    chg = float(s.get("changepercent",0))
                    if chg > 0: up += 1
                    elif chg < 0: down += 1
                    else: flat += 1
                    if chg >= 9.9: limit_up += 1
                    if chg <= -9.9: limit_down += 1
                    all_stocks.append(s)
        except: break
    new_high = sum(1 for s in all_stocks if s.get("high") and s.get("trade") and s["high"]==s["trade"] and float(s.get("changepercent",0))>0)
    new_low = sum(1 for s in all_stocks if s.get("low") and s.get("trade") and s["low"]==s["trade"] and float(s.get("changepercent",0))<0)
    return {"up": up, "down": down, "flat": flat, "limit_up": limit_up, "limit_down": limit_down,
            "new_high": new_high, "new_low": new_low, "total": len(all_stocks)}

def fetch_sectors():
    """获取行业/概念板块"""
    def parse_blocks(text, var_name, key_prefix):
        match = re.search(f'var {var_name} = ({{.*}})', text, re.DOTALL)
        if not match: return []
        raw = match.group(1)
        results = []
        for m in re.finditer(r'"(' + key_prefix + r'[^"]+)":\s*"([^"]*)"', raw):
            fields = m.group(2).split(",")
            if len(fields) >= 13:
                try:
                    results.append({"name": fields[1], "count": int(fields[2]),
                        "chg_pct": float(fields[5]), "lead_code": fields[8], "lead_name": fields[12]})
                except: pass
        return results
    
    url1 = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=industry"
    with urllib.request.urlopen(urllib.request.Request(url1, headers=headers), timeout=10) as resp:
        industries = parse_blocks(resp.read().decode("gbk"), "S_Finance_bankuai_industry", "hangye_")
    industries.sort(key=lambda x: x["chg_pct"], reverse=True)
    
    url2 = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class"
    with urllib.request.urlopen(urllib.request.Request(url2, headers=headers), timeout=10) as resp:
        concepts = parse_blocks(resp.read().decode("gbk"), "S_Finance_bankuai_class", "gn_")
    concepts.sort(key=lambda x: x["chg_pct"], reverse=True)
    
    return {"industries": industries, "concepts": concepts}

def fetch_active_stocks():
    """获取人气股(成交额TOP20)"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=20&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=auto"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    for s in data:
        s["amount_yi"] = round(float(s.get("amount",0))/1e8, 1)
    return data

def fetch_moneyflow():
    """获取资金流向"""
    dc_headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
    cols = "SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,CLOSE_PRICE,PRIME_INFLOW,RATIO_3DAYS"
    base = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_TS_STOCKNEW"
    
    result = {"inflow": [], "outflow": []}
    for direction, sort_dir in [("inflow", "-1"), ("outflow", "1")]:
        url = f"{base}&columns={cols}&filter=&pageNumber=1&pageSize=20&sortTypes={sort_dir}&sortColumns=PRIME_INFLOW&source=WEB&client=WEB"
        req = urllib.request.Request(url, headers=dc_headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("result",{}).get("data",[])
            for it in items:
                it["prime_yi"] = round(float(it.get("PRIME_INFLOW",0))/1e8, 1)
            result[direction] = items
        except: pass
    return result

def fetch_holdings_realtime():
    """获取持仓股实时行情（从index.md动态读取）"""
    vault = "/mnt/c/Users/John Cheng/Documents/Obsidian Vault"
    index_path = f"{vault}/mystocks/index.md"
    holdings_dict = {}
    try:
        with open(index_path) as f:
            text = f.read()
        in_table = False
        for line in text.split("\n"):
            if "| 代码 | 名称 |" in line and "平安普通" in line:
                in_table = True
                continue
            if in_table and line.startswith("|") and not line.startswith("|--"):
                cols = [c.strip() for c in line.split("|")[1:-1]]
                if len(cols) >= 6:
                    code = cols[0]
                    name = cols[1].replace("[[","").replace("]]","")
                    try:
                        total_shares = int(cols[5])
                    except:
                        continue
                    if total_shares > 0:
                        holdings_dict[code] = name
            elif in_table and not line.startswith("|"):
                in_table = False
    except FileNotFoundError:
        # Fallback: hardcoded for offline
        holdings_dict = {
            "000537": "绿发电力", "000887": "中鼎股份", "000938": "紫光股份",
            "001896": "豫能控股", "002077": "大港股份", "002195": "岩山科技",
            "002196": "方正科技", "002342": "巨力索具", "002774": "快意电梯",
            "600172": "黄河旋风", "600379": "宝光股份", "601138": "工业富联",
            "601991": "大唐发电", "688403": "汇成股份",
        }
    
    codes_str = ",".join([f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in holdings_dict.keys()])
    url = f"https://hq.sinajs.cn/list={codes_str}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode("gbk")
    result = []
    for line in text.strip().split("\n"):
        if '="' in line:
            cid, data = line.split('="')
            code = cid.split("hq_str_")[1][2:]
            fields = data.rstrip('";').split(",")
            if len(fields) > 30 and code in holdings_dict:
                price = float(fields[3]); prev = float(fields[2])
                result.append({
                    "code": code, "name": holdings_dict[code], "price": price,
                    "chg_pct": round((price-prev)/prev*100, 2),
                    "high": float(fields[4]), "low": float(fields[5]),
                    "amount": round(float(fields[9])/1e8, 2)
                })
    result.sort(key=lambda x: x["chg_pct"], reverse=True)
    return result

if __name__ == "__main__":
    # Quick mode: only indices + sectors + moneyflow (skip full market scan)
    mode = sys.argv[1] if len(sys.argv) > 1 else "quick"
    
    print("Fetching indices...")
    indices = fetch_indices()
    for c, d in indices.items():
        print(f"  {d['name']}: {d['price']} {d['chg_pct']:+.2f}%")
    
    print("\nFetching sectors...")
    sectors = fetch_sectors()
    print(f"  Industries: {len(sectors['industries'])}, Concepts: {len(sectors['concepts'])}")
    
    print("\nFetching active stocks...")
    active = fetch_active_stocks()
    for s in active[:5]:
        print(f"  {s['symbol']} {s['name']} {s['changepercent']}% {s['amount_yi']}亿")
    
    print("\nFetching moneyflow...")
    mf = fetch_moneyflow()
    print(f"  Inflow TOP3: {[(i['SECURITY_NAME_ABBR'], i['prime_yi']) for i in mf['inflow'][:3]]}")
    print(f"  Outflow TOP3: {[(i['SECURITY_NAME_ABBR'], i['prime_yi']) for i in mf['outflow'][:3]]}")
    
    if mode == "full":
        print("\nFetching full market stats (slow)...")
        stats = fetch_market_stats()
        print(f"  Up:{stats['up']} Down:{stats['down']} LimitUp:{stats['limit_up']} LimitDown:{stats['limit_down']}")
    else:
        print("\nSkipping full market stats (use 'full' arg for complete scan)")
    
    # Save all data
    output = {"indices": indices, "sectors": sectors, "active": active, "moneyflow": mf,
              "timestamp": datetime.now().isoformat(), "mode": mode}
    if mode == "full":
        output["stats"] = stats
    with open("/tmp/mystocks_monitor_data.json","w") as f:
        json.dump(output, f, ensure_ascii=False)
    print("\nData saved to /tmp/mystocks_monitor_data.json")
