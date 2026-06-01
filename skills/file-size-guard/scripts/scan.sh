#!/usr/bin/env bash
# file-size-guard full project scan — dedup worktrees, then single awk pipeline
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

REPO_ROOT="${1:-.}"
[ ! -d "$REPO_ROOT" ] && { echo "Error: '$REPO_ROOT' is not a directory" >&2; exit 1; }
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
DATE=$(date +%Y-%m-%d)

# Build find exclude args from config
EXCLUDE_ARGS=()
while IFS= read -r dir; do
    [ -z "$dir" ] && continue
    EXCLUDE_ARGS+=(-not -path "*/$dir/*")
done < <(_cfg '.scan_exclude_dirs[]')

MIN_THRESHOLD=$(_get_min_threshold)

# Prepare data — use ENVIRON for small data, file for large cache
export _FSG_LIMITS=$(_cfg '.limits | to_entries[] | "\(.key)\t\(.value)"')
export _FSG_ALLOWLIST=" $(_cfg '.allowlist[]' | paste -sd ' ' -) "

# Write previous cache to temp file (not ENVIRON — can exceed ARG_MAX)
TMP_PREV_CACHE=""
if [ -f "$SCAN_CACHE" ]; then
    TMP_PREV_CACHE=$(mktemp)
    jq -r '.[] | "\(.path)\t\(.lines)"' "$SCAN_CACHE" 2>/dev/null > "$TMP_PREV_CACHE"
fi

TMP_CACHE_TSV=$(mktemp)
trap 'rm -f "$TMP_CACHE_TSV" "$TMP_PREV_CACHE"' EXIT

# Pipeline: find → dedup worktrees (python3) → wc -l → awk report
# python3 dedup normalizes .worktrees/<name>/rest → rest, keeps first occurrence
find "$REPO_ROOT" -type f "${EXCLUDE_ARGS[@]}" \( \
    -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o \
    -name "*.js" -o -name "*.vue" -o -name "*.scss" \
\) -print0 2>/dev/null | \
python3 -c "
import sys
root = '$REPO_ROOT'
root_len = len(root) + 1
data = sys.stdin.buffer.read()
# Collect: canon → (is_worktree, raw_path)
best = {}
for path in data.split(b'\x00'):
    if not path:
        continue
    rel = path[root_len:].decode(errors='replace')
    if rel.startswith('.worktrees/'):
        parts = rel.split('/')
        if len(parts) >= 3:
            canon = '/'.join(parts[2:])
        else:
            canon = rel
        is_wt = True
    else:
        canon = rel
        is_wt = False
    if canon not in best or (not is_wt and best[canon][0]):
        best[canon] = (is_wt, path)
# Output deduped paths (prefer main tree over worktree)
for canon, (is_wt, path) in best.items():
    sys.stdout.buffer.write(path + b'\x00')
" | \
xargs -0 wc -l 2>/dev/null | \
awk -v root="$REPO_ROOT" \
    -v min="$MIN_THRESHOLD" \
    -v dates="$DATE" \
    -v cachefile="$TMP_CACHE_TSV" \
    -v cachefile_prev="${TMP_PREV_CACHE:-}" \
'
BEGIN {
    # Parse limit rules from ENVIRON (supports multi-line)
    limits = ENVIRON["_FSG_LIMITS"]
    n_rules = split(limits, rule_lines, "\n")
    for (i = 1; i <= n_rules; i++) {
        if (rule_lines[i] == "") continue
        split(rule_lines[i], parts, "\t")
        pat = parts[1]
        val = parts[2] + 0
        gsub(/\*/, ".*", pat)
        gsub(/\?/, ".", pat)
        rules_pat[++num_rules] = "^" pat "$"
        rules_val[num_rules] = val
        rules_len[num_rules] = length(pat)
    }

    # Parse allowlist from ENVIRON
    allowlist = ENVIRON["_FSG_ALLOWLIST"]
    n_aw = split(allowlist, aw_arr, / +/)
    for (i = 1; i <= n_aw; i++) {
        if (aw_arr[i] != "") allow_set[aw_arr[i]] = 1
    }

    # Parse previous cache from file
    if (cachefile_prev != "" && (getline line < cachefile_prev) >= 0) {
        do {
            if (line == "") continue
            split(line, cp, "\t")
            prev_lines[cp[1]] = cp[2] + 0
        } while ((getline line < cachefile_prev) > 0)
        close(cachefile_prev)
    }

    total_candidates = 0
    over_count = 0
    within_count = 0
    allow_count = 0
    new_count = 0
    known_count = 0
}

/ total$/ { next }
{
    lines = $1 + 0
    if (lines < min) next

    path = ""
    for (i = 2; i <= NF; i++) path = path (i > 2 ? " " : "") $i
    rel = substr(path, length(root) + 2)

    n = split(path, fparts, "/")
    fname = fparts[n]

    total_candidates++

    best_limit = 0
    best_len = 0
    for (r = 1; r <= num_rules; r++) {
        if (rules_len[r] <= best_len && best_limit > 0) continue
        if (fname ~ rules_pat[r]) {
            best_limit = rules_val[r]
            best_len = rules_len[r]
        }
    }

    if (best_limit == 0) next

    printf "%s\t%d\n", rel, lines > cachefile

    is_aw = (rel in allow_set) ? 1 : 0
    if (is_aw) allow_count++

    if (lines > best_limit) {
        pct = int(lines * 100 / best_limit)
        delta = ""
        if (rel in prev_lines) {
            diff = lines - prev_lines[rel]
            if (diff > 0) delta = " [+" diff " since last]"
            else if (diff < 0) delta = " [" diff " since last]"
            known_count++
        } else {
            new_count++
            delta = " [NEW]"
        }
        over_pct[++over_count] = pct
        over_rel[over_count] = rel
        over_lines[over_count] = lines
        over_limit[over_count] = best_limit
        over_aw[over_count] = is_aw
        over_delta[over_count] = delta
    } else {
        within_count++
    }
}

END {
    close(cachefile)

    for (i = 1; i <= over_count; i++) {
        for (j = i + 1; j <= over_count; j++) {
            if (over_pct[j] > over_pct[i]) {
                tmp = over_pct[i]; over_pct[i] = over_pct[j]; over_pct[j] = tmp
                tmp_s = over_rel[i]; over_rel[i] = over_rel[j]; over_rel[j] = tmp_s
                tmp = over_lines[i]; over_lines[i] = over_lines[j]; over_lines[j] = tmp
                tmp = over_limit[i]; over_limit[i] = over_limit[j]; over_limit[j] = tmp
                tmp = over_aw[i]; over_aw[i] = over_aw[j]; over_aw[j] = tmp
                tmp_s = over_delta[i]; over_delta[i] = over_delta[j]; over_delta[j] = tmp_s
            }
        }
    }

    printf "\n"
    printf "📊 File Size Guard Report — %s\n", dates
    printf "──────────────────────────────────────\n"
    printf "   Scanned: %d candidate files (%d+ lines)\n", total_candidates, min

    if (over_count == 0) {
        printf "✅  All files within limits (%d files checked)\n", within_count
    } else {
        exempt_count = 0
        violation_count = 0
        for (i = 1; i <= over_count; i++) {
            if (over_aw[i]) {
                printf "  📌  %d%%  %s  %d/%d lines [exempt]%s\n", over_pct[i], over_rel[i], over_lines[i], over_limit[i], over_delta[i]
                exempt_count++
            } else {
                printf "  ⚠️  %d%%  %s  %d/%d lines%s\n", over_pct[i], over_rel[i], over_lines[i], over_limit[i], over_delta[i]
                violation_count++
            }
        }
        printf "\n"
        printf "⚠️  %d files exceed limits (%d new, %d known)\n", violation_count, new_count, known_count
        if (exempt_count > 0) printf "📌  %d exempt (allowlist)\n", exempt_count
    }

    printf "✅  %d files within limits\n", within_count
    printf "📋  Allowlist: %d file(s)\n", allow_count
    printf "\n"
    printf "💡 Split by responsibility boundary. No mechanical part1/part2 cuts.\n"
    printf "📌 Full tech debt analysis: /tech-debt-checker scan\n"
    printf "\n"
}
' -

# Convert TSV cache to JSON for next run's delta detection
if [ -f "$TMP_CACHE_TSV" ] && [ -s "$TMP_CACHE_TSV" ]; then
    awk -F'\t' 'BEGIN { printf "[" }
    NR > 1 { printf "," }
    { printf "{\"path\":\"%s\",\"lines\":%d}", $1, $2 }
    END { printf "]\n" }' "$TMP_CACHE_TSV" > "$SCAN_CACHE"
fi
