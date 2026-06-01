#!/usr/bin/env bash
# file-size-guard PostToolUse hook — checks file line count after Edit/Write
# Always exits 0 (never blocks). Outputs warning to stderr if file exceeds limit.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../scripts/utils.sh"

# Check global toggle
if ! _is_check_enabled; then
    exit 0
fi

# Read tool input from stdin
INPUT_JSON=$(cat 2>/dev/null || true)
if [ -z "$INPUT_JSON" ]; then
    exit 0
fi

if ! echo "$INPUT_JSON" | jq empty 2>/dev/null; then
    exit 0
fi

FILE_PATH=$(echo "$INPUT_JSON" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
TOOL_NAME=$(echo "$INPUT_JSON" | jq -r '.tool_name // "Unknown"' 2>/dev/null || echo "Unknown")
CWD=$(echo "$INPUT_JSON" | jq -r '.cwd // "unknown"' 2>/dev/null || echo "unknown")

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Only handle Edit and Write
if [ "$TOOL_NAME" != "Edit" ] && [ "$TOOL_NAME" != "Write" ]; then
    exit 0
fi

# Skip if tool execution failed
SUCCESS=$(echo "$INPUT_JSON" | jq -r '.tool_response.success // true' 2>/dev/null || echo "true")
if [ "$SUCCESS" != "true" ]; then
    exit 0
fi

# Resolve to absolute path
if [[ "$FILE_PATH" != /* ]]; then
    ABS_PATH="$CWD/$FILE_PATH"
else
    ABS_PATH="$FILE_PATH"
fi

# File must exist
if [ ! -f "$ABS_PATH" ]; then
    exit 0
fi

# Skip binary files (by extension)
if ! _is_text_by_ext "$ABS_PATH"; then
    exit 0
fi

# Skip small files early
MIN_THRESHOLD=$(_get_min_threshold)
LINES=$(_count_lines "$ABS_PATH")
if [ "$LINES" -lt "$MIN_THRESHOLD" ]; then
    exit 0
fi

# Get repo root for relative path
REPO_ROOT=$(_get_repo_root "$ABS_PATH")
if [ -z "$REPO_ROOT" ]; then
    REPO_ROOT="$CWD"
fi

# Convert to relative path
REL_PATH=$(_to_relative "$ABS_PATH" "$REPO_ROOT")
FILENAME=$(basename "$ABS_PATH")

# Check allowlist
if _is_allowlisted "$REL_PATH"; then
    exit 0
fi

# Match against limits (longest suffix first)
LIMIT=$(_match_limit "$FILENAME")
if [ "$LIMIT" -eq 0 ]; then
    # No matching rule — skip
    exit 0
fi

if [ "$LINES" -gt "$LIMIT" ]; then
    PCT=$(( LINES * 100 / LIMIT ))
    echo "" >&2
    echo "⚠️ [file-size-guard] $REL_PATH ($LINES lines, ${PCT}%) exceeds limit ($LIMIT lines)." >&2
    echo "   Split by responsibility boundary, not by line count. No mechanical part1/part2 cuts." >&2
    echo "" >&2
fi

exit 0
