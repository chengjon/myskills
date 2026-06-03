---
name: hermes-health
description: "Hermes 配置健康度检查 — 诊断超时、上下文溢出、provider 缺陷等常见问题，给出修复建议"
version: 1.0.0
author: agent
metadata:
  hermes:
    tags: [hermes, config, healthcheck, timeout, diagnostics]
---

# Hermes 配置健康度检查

按以下检查清单逐步审计 Hermes 配置，定位超时 / 中断 / 上下文溢出等问题的根因，并给出可执行的修复命令。

## 检查流程

### 1. Provider Timeout 检查

**目的**: 确认当前 provider 有没有配置专属超时，避免走默认 120s read timeout。

```bash
# 读取 config
hermes config show
```

检查项:
- `providers.<id>.request_timeout_seconds` 是否存在且 >= 300
- `providers.<id>.stale_timeout_seconds` 是否存在且 >= 120

**常见问题**:
- `providers` 为空 `{}` → 所有超时走硬编码默认值
  - 非流式: `HERMES_API_TIMEOUT` 默认 1800s (OK)
  - **流式 read_timeout: 默认 120s** (GLM/DeepSeek 等长推理模型不够!)
  - stale_timeout: 默认 90s (可能误杀长推理)

**修复**:
```bash
hermes config set providers.<provider_id>.request_timeout_seconds 600
hermes config set providers.<provider_id>.stale_timeout_seconds 180
```

### 2. Streaming 模式检查

**目的**: `model.stream: false` 时必须等完整响应，更容易超时。

检查项:
- `model.stream` 应为 `true` (流式有心跳保活 + stale 检测)

**修复**:
```bash
hermes config set model.stream true
```

### 3. 上下文长度 & 压缩阈值检查

**目的**: 确认 Hermes 正确识别了模型的 context window，压缩在正确时机触发。

```bash
# 从日志读取已解析的 context
grep -iE 'ctx|context_length|threshold' ~/.hermes/logs/agent.log | tail -20
```

检查项:
- 模型的 context_length 是否正确 (参考 `agent/model_metadata.py` 中的 `DEFAULT_CONTEXT_LENGTHS`)
- 压缩阈值 = context_length * compression.threshold (默认 0.5)
- 上下文 token 数是否接近或超过阈值

**常见问题**:
- models.dev 查不到模型 → 回退到 DEFAULT_CONTEXT_LENGTHS 中的 substring 匹配
- 自定义模型 ID 没命中任何 pattern → 回退到 128K 默认值
- `model.context_length` 在 config 中被手动设错

**手动覆盖 context**:
```bash
hermes config set model.context_length 200000
```

### 4. 日志诊断 — 超时模式识别

```bash
# 提取最近 200 条错误日志中的超时/截断/上下文问题
grep -iE 'APITimeout|ReadTimeout|RemoteProtocolError|finish_reason.*length|truncat|context.*exceed|tokens=~' \
  ~/.hermes/logs/errors.log | tail -30
```

**模式匹配**:

| 日志模式 | 根因 | 修复方向 |
|---------|------|---------|
| `APITimeoutError` + `Request timed out` | 非流式请求超时 | 增加 provider timeout |
| `ReadTimeout` + `elapsed=12Xs` | 流式 read_timeout=120s 不够 | 设 `providers.<id>.request_timeout_seconds` 或 `HERMES_STREAM_READ_TIMEOUT` |
| `RemoteProtocolError` + `peer closed` | 模型端主动断开(通常是上下文溢出) | 触发压缩 或 降低 max_tokens |
| `length-truncated stub` + `Partial stream` | 流被超时硬断，Hermes 伪装成 length | 修复超时即可(不是真 token 超限) |
| `finish_reason='length'` + 大 token 数 | 真正的输出 token 超限 | 增加 max_tokens 或 开 reasoning |
| `finish_reason='length'` + 小 token 数 | 超时断流伪装(假 length) | 修复超时 |

### 5. 环境变量兜底检查

```bash
# 查看 .env 中的超时相关变量
grep -iE 'HERMES_STREAM_READ_TIMEOUT|HERMES_API_TIMEOUT|HERMES_API_CALL_STALE_TIMEOUT' ~/.hermes/.env
```

**推荐值** (用于 GLM/DeepSeek 等长推理模型):

```
HERMES_STREAM_READ_TIMEOUT=300
HERMES_API_TIMEOUT=600
```

> 注意: `.env` 是 Hermes 凭证保护文件，工具无法自动写入，需用户手动编辑。

### 6. Fallback Provider 检查

**目的**: 主 provider 超时后能否自动切换备用。

```bash
hermes config show | grep -A5 fallback
```

检查项:
- `fallback_model.provider` 和 `fallback_model.model` 是否已配置
- 对应 provider 的 API key 是否存在于 `.env`

### 7. 压缩配置检查

检查项:
- `compression.enabled: true` (默认)
- `compression.threshold: 0.5` (默认，context 50% 时触发)
- `compression.target_ratio: 0.2` (压缩到 20%)
- `compression.protect_last_n: 20` (保护最近 20 轮)

**关键**: 辅助压缩也用同一个 provider，如果主 provider 超时，压缩也会超时。

## 输出格式

完成检查后，输出如下格式的报告:

```
=== Hermes 配置健康度报告 ===
日期: YYYY-MM-DD HH:MM
Provider: <provider>/<model>

[✓] Provider Timeout: providers.<id>.request_timeout_seconds = 600s
[✗] Stream Read Timeout: 120s (默认) → 建议设为 300s
[✓] Streaming Mode: true
[✗] Fallback Provider: 未配置
[✓] Context Length: 200,000 (正确)
[✓] Compression: enabled, threshold=50%

⚠ 发现 2 个问题:
1. Stream read timeout 120s → 运行: hermes config set providers.<id>.request_timeout_seconds 600
2. Fallback 未配置 → 在 config.yaml 添加 fallback_model 段

修复命令:
  hermes config set providers.<id>.request_timeout_seconds 600
  hermes config set providers.<id>.stale_timeout_seconds 180
```

## 代码参考

关键文件路径 (用于深入诊断):

| 文件 | 作用 |
|------|------|
| `hermes_cli/timeouts.py` | provider timeout 解析逻辑 |
| `agent/chat_completion_helpers.py:1680-1700` | stream read_timeout 默认值逻辑 |
| `agent/conversation_loop.py:1546-1737` | finish_reason='length' 处理 |
| `agent/model_metadata.py:139-255` | DEFAULT_CONTEXT_LENGTHS |
| `agent/error_classifier.py:350-383` | 超时/断流分类 |

### 8. Auxiliary compression provider

**目的**: 辅助压缩也用同一个 provider，如果主 provider 超时，压缩也会超时。

检查项:
- `auxiliary.compression.provider` 是否为 `auto`（同主模型）
- 如果主 provider 经常超时，建议配置独立备用 provider 做压缩

### 9. Gateway 进程配置热加载检查

**目的**: config.yaml 修改后，gateway 进程不会自动热加载，需要重启才生效。

```bash
# 检查 gateway 启动时间 vs config.yaml 修改时间
stat -c '%Y' ~/.hermes/config.yaml           # config 最后修改时间戳
ps -o lstart= -p $(pgrep -f 'hermes.*gateway' | head -1)  # gateway 启动时间
```

**常见问题**:
- 修改了 `providers.<id>.request_timeout_seconds` 但没重启 gateway → 配置不生效
- 症状: 日志中 ReadTimeout 的 elapsed 值仍然等于旧默认值(如 120s)

**修复**:
```bash
hermes gateway run --replace
# 或
hermes gateway restart
```

### 10. ReadTimeout elapsed 聚合诊断

**目的**: 当 `providers.<id>.request_timeout_seconds` 看似正确但仍超时时，用 elapsed 聚合确认实际生效值。

```bash
# 提取所有 ReadTimeout 的 elapsed 值，按聚合看实际超时阈值
grep 'stream_diag.*ReadTimeout' ~/.hermes/logs/errors.log | \
  grep -oP 'elapsed=[\d.]+' | sort -t= -k2 -n | uniq -c
```

**诊断规则**:
- elapsed 聚合在 ~120-130s → read_timeout 还是默认 120s，provider 配置未生效
- elapsed 聚合在 ~180-190s → stale_timeout=180 触发了 stale_stream_kill
- elapsed 分散在不同值 → 多种根因叠加，需要逐条分析

### 11. stale_stream_kill 误杀检查

**目的**: `stale_timeout_seconds` 设得太短会把长推理（thinking）误判为无响应而杀掉连接。

```bash
# 检查是否有 stale_stream_kill 日志
grep 'stale_stream_kill' ~/.hermes/logs/errors.log | tail -10
```

**常见问题**:
- GLM/DeepSeek thinking 模式下，推理阶段可能 60-120s 不发 SSE 事件
- `stale_timeout_seconds: 90`（默认）会误杀
- 需要设为 >= 180s

**修复**:
```bash
hermes config set providers.<id>.stale_timeout_seconds 180
hermes gateway run --replace   # 必须!
```

## Pitfalls

1. **`model.timeout` vs `providers.<id>.request_timeout_seconds`**: 前者是 OpenAI 客户端级别的连接超时，后者是 Hermes 的 per-call 超时。后者优先级更高，但如果 `providers.<id>` 为空，后者不生效，read_timeout 回退到 120s 默认值。
2. **假 finish_reason='length'**: 流式连接超时断开后，Hermes 会生成一个 "length-truncated stub"，这不是真的 token 超限。诊断时看 `errors.log` 里的 `Partial stream delivered before error` 即可区分。
3. **压缩也用主 provider**: `auxiliary.compression` 默认用 `auto`（同主模型）。主模型超时 → 压缩也超时 → 上下文只会越积越大 → 死循环。可单独配 `auxiliary.compression.provider` 到备用 provider。
4. **`.env` 保护**: Hermes 安全策略阻止工具自动写入 `.env`，涉及 env var 修改时必须提示用户手动编辑。
5. **Gateway 配置不热加载**: 修改 config.yaml 后必须重启 gateway（`hermes gateway run --replace`），否则 gateway 进程仍用旧配置。这是最常见的"配了但还是超时"的根因。
6. **ReadTimeout 130s = 旧默认 120s + 网络延迟**: elapsed 聚合在 ~125-132s 的 ReadTimeout，几乎可以确定是 provider 未配或配置未生效（默认 read_timeout=120s + 网络波动）。不是 zai 服务端断连。
7. **stale_stream_kill vs ReadTimeout**: 看错误类型区分。`stale_stream_kill` 是 Hermes 主动杀（stale_timeout 触发），`ReadTimeout` 是 httpx 层超时。两者修复方向不同：前者增大 stale_timeout，后者增大 request_timeout_seconds。
8. **providers.<id> 为空 {} 的后果**: `get_provider_request_timeout('zai')` 返回 None → read_timeout 回退到 `HERMES_STREAM_READ_TIMEOUT` env var → 如果 env var 也没设 → 默认 120s。三层回退链条：provider config → env var → 120s hardcoded default。