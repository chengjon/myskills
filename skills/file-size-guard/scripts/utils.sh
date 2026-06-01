#!/usr/bin/env bash
# file-size-guard shared utilities
set -uo pipefail

# Resolve skill root directory (follow symlinks)
_resolve_skill_root() {
    local src="${BASH_SOURCE[0]}"
    while [ -L "$src" ]; do
        local dir
        dir="$(cd -P "$(dirname "$src")" && pwd)"
        src="$(readlink "$src")"
        [[ $src != /* ]] && src="$dir/$src"
    done
    cd -P "$(dirname "$src")" && pwd
}

SKILL_ROOT="$(_resolve_skill_root)"
SKILL_ROOT="$(cd "$SKILL_ROOT/.." && pwd)"
CONFIG_FILE="$SKILL_ROOT/config.json"
LOG_DIR="$SKILL_ROOT/logs"
SCAN_CACHE="$SKILL_ROOT/.scan-cache.json"

# --- Config cache (load once, reuse) ---
_CFG_CACHE=""
_load_config() {
    if [ -z "$_CFG_CACHE" ]; then
        _CFG_CACHE=$(cat "$CONFIG_FILE")
    fi
}
_cfg() { _load_config; echo "$_CFG_CACHE" | jq -r "$1" 2>/dev/null; }

# Text file extensions whitelist — skip binary by extension (fast, no I/O)
_TEXT_EXTENSIONS="py ts tsx js vue scss css html htm md json yaml yml xml toml ini cfg conf sh bash zsh fish sql txt csv tsv env gitignore dockerfile makefile r go rs java c h cpp hpp rb php pl lua vim lock"

_is_text_by_ext() {
    local file="$1"
    local ext="${file##*.}"
    ext="${ext,,}"  # lowercase
    echo " $_TEXT_EXTENSIONS " | grep -q " $ext "
}

# Count lines — wc -l is much faster than grep -c
_count_lines() {
    wc -l < "$1" 2>/dev/null | tr -d ' '
}

# --- Limit rules cache ---
_LIMIT_RULES=""
_load_limits() {
    if [ -z "$_LIMIT_RULES" ]; then
        _LIMIT_RULES=$(_cfg '.limits | to_entries[] | "\(.key)\t\(.value)"')
    fi
}

# Longest-suffix-first matching against config limits
_match_limit() {
    local filename="$1"
    _load_limits
    local limit=0 best_len=0

    while IFS=$'\t' read -r pattern val; do
        [ -z "$pattern" ] && continue
        local pat_len=${#pattern}
        [ "$pat_len" -le "$best_len" ] && [ "$limit" -gt 0 ] && continue
        local regex="^${pattern//\*/.*}$"
        if [[ "$filename" =~ $regex ]]; then
            limit="$val"
            best_len="$pat_len"
        fi
    done <<< "$_LIMIT_RULES"

    echo "$limit"
}

# --- Allowlist cache ---
_ALLOWLIST_SET=""
_load_allowlist() {
    if [ -z "$_ALLOWLIST_SET" ]; then
        _ALLOWLIST_SET=" $(_cfg '.allowlist[]' | tr '\n' ' ') "
    fi
}

_is_allowlisted() {
    local relpath="$1"
    relpath="${relpath#./}"
    _load_allowlist
    echo "$_ALLOWLIST_SET" | grep -q " $relpath "
}

_get_min_threshold() { _cfg '.min_line_threshold // 10'; }

_is_check_enabled() {
    local val; val=$(_cfg '.check_on_write // true')
    [ "$val" = "true" ]
}

_to_relative() {
    local abs_path="$1" repo_root="$2"
    if command -v realpath &>/dev/null; then
        realpath --relative-to="$repo_root" "$abs_path" 2>/dev/null || echo "$abs_path"
    else
        echo "${abs_path#$repo_root/}"
    fi
}

_get_repo_root() {
    local file_path="$1"
    git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null
}

_log_error() {
    mkdir -p "$LOG_DIR"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG_DIR/error.log"
}
