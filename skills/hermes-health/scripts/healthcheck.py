#!/usr/bin/env python3
"""Hermes 配置健康度检查脚本 — 诊断超时、上下文溢出、provider 缺陷等常见问题。

用法:
  python3 scripts/healthcheck.py                    # 检查当前配置
  python3 scripts/healthcheck.py --fix              # 检查并输出修复命令
  python3 scripts/healthcheck.py --provider zai     # 只检查指定 provider
"""

from __future__ import annotations

import os
import re
import sys
import yaml
import argparse
from pathlib import Path
from datetime import datetime


def get_hermes_home() -> Path:
    """Resolve HERMES_HOME."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def load_config() -> dict:
    """Load config.yaml."""
    cfg_path = get_hermes_home() / "config.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


def load_env() -> dict:
    """Load .env as key=value pairs."""
    env_path = get_hermes_home() / ".env"
    env = {}
    if not env_path.exists():
        return env
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def parse_log_errors(limit: int = 50, hours: int = 72) -> list[dict]:
    """Parse recent errors from errors.log (within last N hours)."""
    log_path = get_hermes_home() / "logs" / "errors.log"
    if not log_path.exists():
        return []
    errors = []
    cutoff = datetime.now().timestamp() - hours * 3600
    try:
        with open(log_path) as f:
            lines = f.readlines()[-limit * 3:]  # rough tail
    except Exception:
        return []

    for line in lines:
        entry = {}
        # APITimeoutError
        m = re.search(r'error_type=(\w+).*provider=(\w+).*model=([\w.\-]+)', line)
        if m:
            entry["error_type"] = m.group(1)
            entry["provider"] = m.group(2)
            entry["model"] = m.group(3)
        # ReadTimeout with elapsed
        m2 = re.search(r'error_type=(ReadTimeout|RemoteProtocolError).*elapsed=([\d.]+)s', line)
        if m2:
            entry["error_type"] = m2.group(1)
            entry["elapsed_s"] = float(m2.group(2))
        # tokens
        m3 = re.search(r'tokens=~([\d,]+)', line)
        if m3:
            entry["tokens"] = int(m3.group(1).replace(",", ""))
        # length-truncated stub
        if "length-truncated stub" in line:
            entry["error_type"] = "length_truncated_stub"
            m4 = re.search(r'(\d+) chars of recovered content', line)
            if m4:
                entry["recovered_chars"] = int(m4.group(1))
        if entry:
            entry["raw"] = line.strip()[:200]
            # Filter by timestamp
            m_ts = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if m_ts:
                try:
                    ts = datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            errors.append(entry)
    return errors[-limit:]


# ── Context length reference (from model_metadata.py) ──
KNOWN_CONTEXT_LENGTHS = {
    "glm": 202752,
    "zai-org/GLM-5": 202752,
    "deepseek": 128000,
    "deepseek-v4-pro": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
    "qwen": 131072,
    "claude": 200000,
    "gpt-4": 128000,
    "gpt-5": 400000,
    "gemini": 1048576,
    "grok": 131072,
    "kimi": 262144,
    "minimax": 204800,
}

MIN_TIMEOUT_READ = 300    # Minimum recommended stream read timeout
MIN_TIMEOUT_REQUEST = 300  # Minimum recommended request timeout
MIN_STALE_TIMEOUT = 120    # Minimum recommended stale timeout


def lookup_context(model: str) -> int | None:
    """Best-effort context length lookup via substring matching."""
    model_lower = model.lower()
    # Longest-first match
    for key in sorted(KNOWN_CONTEXT_LENGTHS, key=len, reverse=True):
        if key.lower() in model_lower:
            return KNOWN_CONTEXT_LENGTHS[key]
    return None


def run_check(provider_filter: str | None = None) -> list[dict]:
    """Run all health checks. Returns list of {check, status, detail, fix?}."""
    config = load_config()
    env = load_env()
    log_errors = parse_log_errors()
    results = []

    model_cfg = config.get("model", {})
    provider = model_cfg.get("provider", "")
    model = model_cfg.get("default", "")

    if provider_filter and provider != provider_filter:
        return [{"check": "Provider mismatch", "status": "skip",
                 "detail": f"Active provider is '{provider}', filter was '{provider_filter}'"}]

    # ── 1. Provider timeout ──
    providers = config.get("providers", {}) or {}
    p_cfg = providers.get(provider, {}) or {}
    req_timeout = p_cfg.get("request_timeout_seconds")
    stale_timeout = p_cfg.get("stale_timeout_seconds")

    if req_timeout is not None and req_timeout >= MIN_TIMEOUT_REQUEST:
        results.append({"check": "Provider request timeout", "status": "ok",
                        "detail": f"providers.{provider}.request_timeout_seconds = {req_timeout}s"})
    elif req_timeout is not None:
        results.append({"check": "Provider request timeout", "status": "warn",
                        "detail": f"providers.{provider}.request_timeout_seconds = {req_timeout}s (建议 >= {MIN_TIMEOUT_REQUEST}s)",
                        "fix": f"hermes config set providers.{provider}.request_timeout_seconds {MIN_TIMEOUT_REQUEST}"})
    else:
        results.append({"check": "Provider request timeout", "status": "fail",
                        "detail": f"providers.{provider} 未配置 request_timeout_seconds → 默认 1800s(非流式)/120s(流式 read)",
                        "fix": f"hermes config set providers.{provider}.request_timeout_seconds 600"})

    if stale_timeout is not None and stale_timeout >= MIN_STALE_TIMEOUT:
        results.append({"check": "Provider stale timeout", "status": "ok",
                        "detail": f"providers.{provider}.stale_timeout_seconds = {stale_timeout}s"})
    elif stale_timeout is not None:
        results.append({"check": "Provider stale timeout", "status": "warn",
                        "detail": f"providers.{provider}.stale_timeout_seconds = {stale_timeout}s (建议 >= {MIN_STALE_TIMEOUT}s)",
                        "fix": f"hermes config set providers.{provider}.stale_timeout_seconds {MIN_STALE_TIMEOUT}"})
    else:
        results.append({"check": "Provider stale timeout", "status": "fail",
                        "detail": f"providers.{provider} 未配置 stale_timeout_seconds → 默认 90s",
                        "fix": f"hermes config set providers.{provider}.stale_timeout_seconds 180"})

    # ── 2. Streaming mode ──
    stream = model_cfg.get("stream", False)
    if stream:
        results.append({"check": "Streaming mode", "status": "ok",
                        "detail": f"model.stream = {stream}"})
    else:
        results.append({"check": "Streaming mode", "status": "warn",
                        "detail": f"model.stream = {stream} → 非流式更容易超时",
                        "fix": "hermes config set model.stream true"})

    # ── 3. Context length ──
    configured_ctx = model_cfg.get("context_length")
    known_ctx = lookup_context(model)
    if configured_ctx:
        results.append({"check": "Context length", "status": "ok",
                        "detail": f"手动配置 context_length = {configured_ctx:,}"})
    elif known_ctx:
        results.append({"check": "Context length", "status": "ok",
                        "detail": f"自动识别 context_length ≈ {known_ctx:,} (基于 model name pattern)"})
    else:
        results.append({"check": "Context length", "status": "warn",
                        "detail": f"无法自动识别 '{model}' 的 context_length → 可能回退到 128K 默认值",
                        "fix": f"hermes config set model.context_length <正确值>"})

    # ── 4. Compression ──
    comp = config.get("compression", {}) or {}
    comp_enabled = comp.get("enabled", True)
    comp_threshold = comp.get("threshold", 0.5)
    if comp_enabled:
        results.append({"check": "Compression", "status": "ok",
                        "detail": f"enabled=true, threshold={comp_threshold}"})
    else:
        results.append({"check": "Compression", "status": "warn",
                        "detail": "compression.enabled = false → 上下文只会增长不会压缩",
                        "fix": "hermes config set compression.enabled true"})

    # ── 5. Fallback provider ──
    fb = config.get("fallback_model") or config.get("fallback_model")
    if fb and isinstance(fb, dict) and fb.get("provider"):
        results.append({"check": "Fallback provider", "status": "ok",
                        "detail": f"provider={fb.get('provider')}, model={fb.get('model', '?')}"})
    else:
        results.append({"check": "Fallback provider", "status": "warn",
                        "detail": "未配置 fallback_model → 主 provider 不可用时无自动切换",
                        "fix": "hermes config set fallback_model.provider <provider_id>"})

    # ── 6. Env var timeout ──
    srt = env.get("HERMES_STREAM_READ_TIMEOUT")
    if srt and int(srt) >= MIN_TIMEOUT_READ:
        results.append({"check": "HERMES_STREAM_READ_TIMEOUT", "status": "ok",
                        "detail": f"{srt}s"})
    elif srt:
        results.append({"check": "HERMES_STREAM_READ_TIMEOUT", "status": "warn",
                        "detail": f"{srt}s (建议 >= {MIN_TIMEOUT_READ}s)",
                        "fix": f"在 ~/.hermes/.env 中设置 HERMES_STREAM_READ_TIMEOUT={MIN_TIMEOUT_READ}"})
    else:
        results.append({"check": "HERMES_STREAM_READ_TIMEOUT", "status": "fail",
                        "detail": f"未设置 → 默认 120s (GLM/DeepSeek 长推理不够!)",
                        "fix": f"在 ~/.hermes/.env 中添加 HERMES_STREAM_READ_TIMEOUT={MIN_TIMEOUT_READ}"})

    at = env.get("HERMES_API_TIMEOUT")
    if at and int(at) >= 600:
        results.append({"check": "HERMES_API_TIMEOUT", "status": "ok",
                        "detail": f"{at}s"})
    elif at:
        results.append({"check": "HERMES_API_TIMEOUT", "status": "warn",
                        "detail": f"{at}s (建议 >= 600s)",
                        "fix": "在 ~/.hermes/.env 中设置 HERMES_API_TIMEOUT=600"})
    else:
        results.append({"check": "HERMES_API_TIMEOUT", "status": "info",
                        "detail": "未设置 → 默认 1800s (OK)"})

    # ── 7. Log error pattern analysis ──
    if log_errors:
        timeout_count = sum(1 for e in log_errors if e.get("error_type") in ("APITimeoutError", "ReadTimeout"))
        disconnect_count = sum(1 for e in log_errors if e.get("error_type") == "RemoteProtocolError")
        stub_count = sum(1 for e in log_errors if e.get("error_type") == "length_truncated_stub")

        if timeout_count > 3:
            results.append({"check": "Log: 超时频率", "status": "fail",
                            "detail": f"最近日志中有 {timeout_count} 次超时 — read_timeout 很可能不够",
                            "fix": "增加 providers.<id>.request_timeout_seconds 或 HERMES_STREAM_READ_TIMEOUT"})
        elif timeout_count > 0:
            results.append({"check": "Log: 超时频率", "status": "warn",
                            "detail": f"最近日志中有 {timeout_count} 次超时"})

        if disconnect_count > 2:
            results.append({"check": "Log: 连接断开", "status": "warn",
                            "detail": f"最近日志中有 {disconnect_count} 次 peer closed — 可能是上下文溢出导致服务端断开"})

        if stub_count > 0:
            results.append({"check": "Log: 超时伪装截断", "status": "warn",
                            "detail": f"最近日志中有 {stub_count} 次 length-truncated stub — 这是超时断流，不是真 token 超限"})

    # ── 8. Provider base_url consistency ──
    config_base_url = model_cfg.get("base_url")
    plugin_base_url = None
    provider_plugin_path = get_hermes_home() / "hermes-agent" / "plugins" / "model-providers" / provider / "__init__.py"
    if provider_plugin_path.exists():
        try:
            with open(provider_plugin_path) as pf:
                for pline in pf:
                    m = re.search(r'base_url\s*=\s*["\']([^"\']+)["\']', pline)
                    if m:
                        plugin_base_url = m.group(1)
                        break
        except Exception:
            pass

    if config_base_url and plugin_base_url:
        if config_base_url.rstrip("/") == plugin_base_url.rstrip("/"):
            results.append({"check": "Provider base_url 一致性", "status": "ok",
                            "detail": f"config 和插件均为 {config_base_url}"})
        else:
            results.append({"check": "Provider base_url 一致性", "status": "warn",
                            "detail": f"config={config_base_url} vs 插件={plugin_base_url} — config 优先但易混淆",
                            "fix": f"统一插件默认值: 编辑 {provider_plugin_path} 将 base_url 改为 {config_base_url}"})
    elif config_base_url and not plugin_base_url:
        results.append({"check": "Provider base_url 一致性", "status": "ok",
                        "detail": f"config 设置 base_url={config_base_url}，插件无默认值"})
    elif not config_base_url and plugin_base_url:
        results.append({"check": "Provider base_url 一致性", "status": "info",
                        "detail": f"config 未设 base_url，使用插件默认值 {plugin_base_url}"})
    else:
        results.append({"check": "Provider base_url 一致性", "status": "warn",
                        "detail": "config 和插件均未设置 base_url — 可能回退到 httpx 默认行为"})

    # ── 9. Auxiliary compression provider ──
    aux = config.get("auxiliary", {}) or {}
    aux_comp = aux.get("compression", {}) or {}
    aux_comp_provider = aux_comp.get("provider")
    if aux_comp_provider and aux_comp_provider != "auto":
        results.append({"check": "Auxiliary compression provider", "status": "ok",
                        "detail": f"provider = {aux_comp_provider}"})
    else:
        results.append({"check": "Auxiliary compression provider", "status": "info",
                        "detail": "provider = auto (同主模型) — 主模型超时时压缩也会超时"})

    # ── 10. Gateway config hot-reload check ──
    config_path = get_hermes_home() / "config.yaml"
    if config_path.exists():
        config_mtime = config_path.stat().st_mtime
        import subprocess
        try:
            gw_pids = subprocess.check_output(
                ["pgrep", "-f", "hermes.*gateway"], text=True
            ).strip().split("\n")
            if gw_pids and gw_pids[0]:
                gw_pid = int(gw_pids[0])
                gw_start = os.path.getctime(f"/proc/{gw_pid}") if os.path.exists(f"/proc/{gw_pid}") else 0
                if gw_start > 0 and config_mtime > gw_start:
                    results.append({"check": "Gateway 配置热加载", "status": "fail",
                                    "detail": f"config.yaml 修改于 {datetime.fromtimestamp(config_mtime).strftime('%H:%M:%S')}, "
                                              f"gateway 启动于 {datetime.fromtimestamp(gw_start).strftime('%H:%M:%S')} — 配置未生效!",
                                    "fix": "hermes gateway run --replace"})
                else:
                    results.append({"check": "Gateway 配置热加载", "status": "ok",
                                    "detail": "gateway 启动时间 >= config.yaml 修改时间，配置已生效"})
            else:
                results.append({"check": "Gateway 配置热加载", "status": "info",
                                "detail": "gateway 进程未运行"})
        except (subprocess.CalledProcessError, ValueError, OSError):
            results.append({"check": "Gateway 配置热加载", "status": "info",
                            "detail": "无法检测 gateway 进程"})

    # ── 11. ReadTimeout elapsed aggregation ──
    read_timeouts = [e for e in log_errors if e.get("error_type") == "ReadTimeout" and "elapsed_s" in e]
    if len(read_timeouts) >= 3:
        elapsed_vals = [e["elapsed_s"] for e in read_timeouts]
        avg_elapsed = sum(elapsed_vals) / len(elapsed_vals)
        clustered_at_120 = sum(1 for v in elapsed_vals if 115 <= v <= 140) / len(elapsed_vals)
        if clustered_at_120 > 0.5:
            results.append({"check": "ReadTimeout elapsed 聚合", "status": "fail",
                            "detail": f"{len(read_timeouts)} 次 ReadTimeout 聚合在 ~{avg_elapsed:.0f}s — "
                                      f"疑似 read_timeout=120s 默认值未覆盖 (配置未生效?)",
                            "fix": "确认 providers.<id>.request_timeout_seconds 已设 且 gateway 已重启"})
        else:
            results.append({"check": "ReadTimeout elapsed 聚合", "status": "warn",
                            "detail": f"{len(read_timeouts)} 次 ReadTimeout，平均 elapsed={avg_elapsed:.0f}s"})

    # ── 12. stale_stream_kill check ──
    stale_kills = [e for e in log_errors if "stale_stream_kill" in e.get("raw", "")]
    if len(stale_kills) >= 2:
        results.append({"check": "stale_stream_kill 误杀", "status": "warn",
                        "detail": f"最近日志中有 {len(stale_kills)} 次 stale_stream_kill — "
                                  f"stale_timeout 可能太短，长推理被误杀",
                        "fix": f"hermes config set providers.{provider}.stale_timeout_seconds 180"})

    return results


def format_report(results: list[dict], show_fix: bool = False) -> str:
    """Format check results into a readable report."""
    icon_map = {"ok": "[OK]", "fail": "[FAIL]", "warn": "[WARN]", "info": "[INFO]", "skip": "[SKIP]"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    config = load_config()
    provider = config.get("model", {}).get("provider", "?")
    model = config.get("model", {}).get("default", "?")

    lines = [
        f"=== Hermes 配置健康度报告 ===",
        f"日期: {now}",
        f"Provider: {provider}/{model}",
        "",
    ]

    issues = []
    fixes = []

    for r in results:
        icon = icon_map.get(r["status"], "[?]")
        lines.append(f"  {icon} {r['check']}: {r['detail']}")
        if r["status"] in ("fail", "warn"):
            issues.append(r)
            if show_fix and r.get("fix"):
                fixes.append(r["fix"])

    if issues:
        lines.append("")
        lines.append(f"!! 发现 {len(issues)} 个问题:")
        for i, r in enumerate(issues, 1):
            lines.append(f"  {i}. {r['check']}: {r['detail']}")
            if r.get("fix"):
                lines.append(f"     修复: {r['fix']}")

    if fixes:
        lines.append("")
        lines.append("修复命令:")
        for fx in fixes:
            lines.append(f"  {fx}")
    elif not issues:
        lines.append("")
        lines.append("所有检查通过!")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Hermes 配置健康度检查")
    parser.add_argument("--fix", action="store_true", help="输出修复命令")
    parser.add_argument("--provider", type=str, help="只检查指定 provider")
    args = parser.parse_args()

    results = run_check(provider_filter=args.provider)
    report = format_report(results, show_fix=args.fix)
    print(report)

    has_fail = any(r["status"] == "fail" for r in results)
    sys.exit(1 if has_fail else 0)


if __name__ == "__main__":
    main()
