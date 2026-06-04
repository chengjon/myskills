# WSL → Windows Python 桥接 (pytdx)

## 问题

WSL环境下通达信行情服务器(TDX)和部分金融API封锁WSL的IP地址：
- WSL侧 `pytdx.connect()` → 超时/拒绝
- WSL侧 `curl` 新浪K线/东方财富API → 456/403
- Windows侧网络正常

## 解决方案

通过 `su - john` 切换到Linux用户，调用Windows Python执行pytdx脚本。

### 关键路径

| 组件 | 路径 |
|------|------|
| Windows Python | `/mnt/c/Users/John Cheng/AppData/Local/Programs/Python/Python312/python.exe` |
| Linux用户 | `john` (非root才能执行Windows exe) |
| 脚本存放 | `/mnt/c/Users/John Cheng/Desktop/` (WSL写, Windows读) |

### 调用模式

```python
import subprocess

WIN_PYTHON = "/mnt/c/Users/John Cheng/AppData/Local/Programs/Python/Python312/python.exe"
LINUX_USER = "john"
SCRIPT_DIR = "/mnt/c/Users/John Cheng/Desktop"

# 1. 写脚本到Windows可访问路径
script_path = os.path.join(SCRIPT_DIR, f"pytdx_kline_{code}.py")
win_script_path = f"C:\\Users\\John Cheng\\Desktop\\pytdx_kline_{code}.py"

with open(script_path, "w") as f:
    f.write(script_content)

# 2. su john 调用 Windows Python (用Windows路径引用脚本)
cmd = f'su - {LINUX_USER} -c \'"{_WIN_PYTHON}" "{win_script_path}"\''
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
```

### 踩坑记录

1. **root无法执行Windows exe**: 必须su到john用户。root调用`/mnt/c/.../python.exe`返回`Invalid argument`
2. **脚本路径必须用Windows格式**: Windows Python无法解析`/tmp/xxx.py`这样的WSL路径，要用`C:\Users\...`
3. **单引号嵌套**: su -c 的参数用单引号，内部Windows路径用双引号包裹(含空格)
4. **输出回车符**: Windows Python输出含`\r\n`，需`.strip()`后才能正确解析JSON
5. **并发风险**: 多只股票串行调用(每只写一个临时脚本)，避免并发写同一文件

## pytdx 数据范围

- 通达信行情服务器: `180.153.18.170:7709` (当前可用)
- 15分钟K线: 每次`get_security_bars(1, market, code, start, 800)`最多800根
- 翻页: start从0递增800，最多~8000根(回溯到2024-05-22)
- 市场代码: 0=深圳(000/002/300), 1=上海(600/601/603/688)
- datetime格式: `"2024-10-10 09:45"` (分钟级, 无秒)

## 适配器文件

`scripts/pytdx_kline_adapter.py` 封装了完整的调用流程：
- `fetch_15min_kline_pytdx(code, start_date, end_date)` → List[Dict]
- `batch_fetch_15min_kline_pytdx(codes, ...)` → Dict[str, List[Dict]]
- 自动生成临时Python脚本 → 写到Desktop → su john执行 → 解析JSON返回
