#!/usr/bin/env bash
# file-size-guard CLI entry point
# Usage: cli.sh <command> [args...]
# Commands: check <file>, scan [dir], allowlist [add|remove <path>], config [show|test <file>]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

usage() {
    echo "file-size-guard — lightweight file line count gate"
    echo ""
    echo "Commands:"
    echo "  check <file>               Check a single file against limits"
    echo "  scan [dir]                 Full project scan (default: .)"
    echo "  allowlist                  Show current allowlist"
    echo "  allowlist add <path>       Add file to allowlist"
    echo "  allowlist remove <path>    Remove file from allowlist"
    echo "  config show                Show current configuration"
    echo "  config test <file>         Test which rule matches a file"
    echo ""
}

# Use python3 for reliable JSON manipulation
_json_allowlist_add() {
    local rel_path="$1"
    python3 -c "
import json, sys
with open('$CONFIG_FILE', 'r') as f:
    cfg = json.load(f)
if '$rel_path' not in cfg['allowlist']:
    cfg['allowlist'].append('$rel_path')
    with open('$CONFIG_FILE', 'w') as f:
        json.dump(cfg, f, indent=2)
    print('added')
else:
    print('duplicate')
"
}

_json_allowlist_remove() {
    local rel_path="$1"
    python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    cfg = json.load(f)
if '$rel_path' in cfg['allowlist']:
    cfg['allowlist'].remove('$rel_path')
    with open('$CONFIG_FILE', 'w') as f:
        json.dump(cfg, f, indent=2)
    print('removed')
else:
    print('not_found')
"
}

cmd_check() {
    local file="${1:-}"
    if [ -z "$file" ]; then
        echo "Usage: cli.sh check <file>" >&2
        return 1
    fi

    if [ ! -f "$file" ]; then
        echo "Error: '$file' not found" >&2
        return 1
    fi

    if ! _is_text_file "$file"; then
        echo "Binary file, skipping."
        return 0
    fi

    local lines limit pct filename rel_path repo_root
    lines=$(_count_lines "$file")
    min=$(_get_min_threshold)

    if [ "$lines" -lt "$min" ]; then
        echo "✅ $file ($lines lines) — below threshold ($min)"
        return 0
    fi

    filename=$(basename "$file")
    repo_root=$(_get_repo_root "$file")
    [ -z "$repo_root" ] && repo_root="$(pwd)"
    rel_path=$(_to_relative "$(cd "$(dirname "$file")" && pwd)/$filename" "$repo_root")

    if _is_allowlisted "$rel_path"; then
        echo "📌 $rel_path ($lines lines) — allowlisted"
        return 0
    fi

    limit=$(_match_limit "$filename")
    if [ "$limit" -eq 0 ]; then
        echo "ℹ️  $rel_path ($lines lines) — no matching rule"
        return 0
    fi

    if [ "$lines" -gt "$limit" ]; then
        pct=$(( lines * 100 / limit ))
        echo "⚠️  $rel_path ($lines lines, ${pct}%) exceeds limit ($limit lines)"
        echo "   Split by responsibility boundary, not by line count."
        return 0
    else
        echo "✅ $rel_path ($lines/$limit lines)"
        return 0
    fi
}

cmd_scan() {
    local dir="${1:-.}"
    bash "$SCRIPT_DIR/scan.sh" "$dir"
}

cmd_allowlist_show() {
    echo "📋 Allowlist:"
    local count
    count=$(_cfg '.allowlist | length')
    if [ "$count" -eq 0 ]; then
        echo "  (empty)"
        return 0
    fi
    _cfg '.allowlist[]' | while IFS= read -r entry; do
        echo "  - $entry"
    done
    echo ""
    echo "Total: $count file(s)"
}

cmd_allowlist_add() {
    local path="${1:-}"
    if [ -z "$path" ]; then
        echo "Usage: cli.sh allowlist add <path>" >&2
        return 1
    fi

    if [ ! -f "$path" ]; then
        echo "Warning: '$path' does not exist. Adding anyway." >&2
    fi

    local repo_root
    repo_root="$(pwd)"
    if command -v git &>/dev/null; then
        local git_root
        git_root=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
        [ -n "$git_root" ] && repo_root="$git_root"
    fi

    local rel_path
    rel_path=$(_to_relative "$path" "$repo_root")

    local result
    result=$(_json_allowlist_add "$rel_path")
    if [ "$result" = "added" ]; then
        echo "✅ Added to allowlist: $rel_path"
    else
        echo "Already in allowlist: $rel_path"
    fi
}

cmd_allowlist_remove() {
    local path="${1:-}"
    if [ -z "$path" ]; then
        echo "Usage: cli.sh allowlist remove <path>" >&2
        return 1
    fi

    local repo_root
    repo_root="$(pwd)"
    if command -v git &>/dev/null; then
        local git_root
        git_root=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
        [ -n "$git_root" ] && repo_root="$git_root"
    fi

    local rel_path
    rel_path=$(_to_relative "$path" "$repo_root")

    local result
    result=$(_json_allowlist_remove "$rel_path")
    if [ "$result" = "removed" ]; then
        echo "✅ Removed from allowlist: $rel_path"
    else
        echo "Not in allowlist: $rel_path"
    fi
}

cmd_config_show() {
    echo "📋 file-size-guard configuration"
    echo "──────────────────────────────────"
    echo ""
    echo "Limits:"
    _cfg '.limits | to_entries[] | "  \(.key): \(.value) lines"' | sort -t: -k2 -rn
    echo ""
    echo "Settings:"
    echo "  check_on_write: $(_cfg '.check_on_write')"
    echo "  min_line_threshold: $(_cfg '.min_line_threshold')"
    echo ""
    echo "Exclude dirs: $(_cfg '.scan_exclude_dirs | join(", ")')"
    echo "Exclude files: $(_cfg '.scan_exclude_files | join(", ")')"
    echo ""
    cmd_allowlist_show
}

cmd_config_test() {
    local file="${1:-}"
    if [ -z "$file" ]; then
        echo "Usage: cli.sh config test <filename>" >&2
        return 1
    fi

    local filename
    filename=$(basename "$file")
    echo "Testing: $filename"

    echo ""
    echo "Matching rules (longest first):"
    local found=0
    while IFS=$'\t' read -r pattern val; do
        [ -z "$pattern" ] && continue
        local regex="^${pattern//\*/.*}$"
        if echo "$filename" | grep -qE "$regex" 2>/dev/null; then
            local pat_len=${#pattern}
            echo "  ✅ $pattern → $val lines (specificity: $pat_len chars)"
            found=1
        fi
    done < <(_cfg '.limits | to_entries[] | "\(.key)\t\(.value)"' | sort -t$'\t' -k1 -r)

    if [ "$found" -eq 0 ]; then
        echo "  ℹ️  No matching rule"
    fi

    echo ""
    local limit
    limit=$(_match_limit "$filename")
    echo "Effective limit: $([ "$limit" -gt 0 ] && echo "$limit lines" || echo "none")"
}

# Main dispatch
COMMAND="${1:-}"
shift 2>/dev/null || true

case "$COMMAND" in
    check)          cmd_check "$@" ;;
    scan)           cmd_scan "$@" ;;
    allowlist)
        SUB="${1:-show}"
        [ "$#" -gt 0 ] && shift
        case "$SUB" in
            show)   cmd_allowlist_show ;;
            add)    cmd_allowlist_add "$@" ;;
            remove) cmd_allowlist_remove "$@" ;;
            *)      echo "Usage: cli.sh allowlist [show|add|remove] [path]" ;;
        esac
        ;;
    config)
        SUB="${1:-show}"
        [ "$#" -gt 0 ] && shift
        case "$SUB" in
            show)   cmd_config_show ;;
            test)   cmd_config_test "$@" ;;
            *)      echo "Usage: cli.sh config [show|test <file>]" ;;
        esac
        ;;
    -h|--help|help)  usage ;;
    "")               usage ;;
    *)                echo "Unknown command: $COMMAND" >&2; usage; return 1 ;;
esac
