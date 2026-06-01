---
name: file-size-guard
description: >
  Lightweight file line count gate — warns when files exceed size limits, never blocks.
  Triggers automatically via PostToolUse hook after Edit/Write. Supports allowlist,
  full project scan, and incremental delta detection. Thresholds: Python 800, Vue/TS 500,
  Tests 1000. Use when: user mentions "file size", "line count", "file too large",
  "split file", "file guard", "size limit", or wants to check/scan file sizes.
  Triggers: "/file-size-guard", "check file size", "scan file sizes", "file too long".
  Do NOT use for: code refactoring, actual file splitting, security analysis.
---

# File Size Guard

> **补充规范说明**: 本文件是技能执行提示。涉及项目治理、审批门禁时，优先遵循项目 `architecture/STANDARDS.md`。

## Overview

Lightweight file line count gate that **warns but never blocks**. Fires automatically after every Edit/Write operation, checks the file against configured limits, and outputs a stderr warning if exceeded. Also provides full project scan with incremental delta detection.

## Core Principle

**Detect and warn only. Never block, never auto-split.**

## Default Limits (from `architecture/STANDARDS.md`)

| Pattern | Limit | Scope |
|---------|-------|-------|
| `*.py` | 800 | All Python files |
| `*_test.py` | 1000 | Python test files |
| `*test_*.py` | 1000 | Python test files (pytest convention) |
| `*.vue` | 500 | Vue single-file components |
| `*.ts` | 500 | TypeScript files |
| `*.tsx` | 500 | TSX files |
| `*.js` | 500 | JavaScript files |
| `*.spec.ts` | 1000 | TS spec tests |
| `*.test.ts` | 1000 | TS test files |
| `*.test.tsx` | 1000 | TSX test files |
| `*.scss` | 500 | SCSS stylesheets |

**Matching rule**: Longest suffix match wins. `*_test.py` (more specific) takes precedence over `*.py` (general).

## When to Use

- After Edit/Write operations (automatic via hook)
- User asks to check file sizes or line counts
- Periodic project health scan
- Before release to identify files needing split

## Do Not Use

- Actual file splitting (this skill only warns)
- Security analysis or code quality audit
- As a replacement for `/tech-debt-checker`

## Modes

| Mode | Trigger | Behavior | Mutates |
|------|---------|----------|---------|
| `check` | Hook auto / `/file-size-guard check <file>` | Single file check | No |
| `scan` | `/file-size-guard scan` | Full project scan with deltas | Cache file only |
| `allowlist` | `/file-size-guard allowlist` | Show/manage allowlist | config.json only |
| `config` | `/file-size-guard config show` | Show/test config | No |

## Hook Behavior

**Trigger**: PostToolUse on Edit|Write
**Exit**: Always 0 (never blocks)

```
Flow:
  1. Read tool_input from stdin
  2. Skip if: file missing, binary, below min threshold, or allowlisted
  3. Match file against limits (longest suffix first)
  4. If over limit → warning to stderr
  5. exit 0
```

**Warning format**:
```
⚠️ [file-size-guard] path/to/file.py (923 lines, 115%) exceeds limit (800 lines).
   Split by responsibility boundary, not by line count. No mechanical part1/part2 cuts.
```

## Scan Report Format

```
📊 File Size Guard Report — 2026-05-31
──────────────────────────────────────
⚠️  3 files exceed limits (2 new, 1 known):

  124%  src/services/market_data.py          923/800 lines [+42 lines since last scan]
  118%  web/frontend/src/views/Dashboard.vue 591/500 lines [NEW]
  📌    src/monitoring/scanner.py             1102/800 [exempt]

✅  847 files within limits
📋  Allowlist: 1 file(s)

💡 Split by responsibility boundary. No mechanical part1/part2 cuts.
📌 Full tech debt analysis: /tech-debt-checker scan
```

## Allowlist Management

Files in the allowlist are skipped during both hook checks and scans. Use for files that are intentionally large and not candidates for splitting.

```bash
# CLI usage
bash .claude/skills/file-size-guard/scripts/cli.sh allowlist add src/foo.py
bash .claude/skills/file-size-guard/scripts/cli.sh allowlist remove src/foo.py
bash .claude/skills/file-size-guard/scripts/cli.sh allowlist
```

- Paths are auto-converted to relative (from repo root)
- Auto-deuplicated
- Edit `config.json` directly for batch changes

## Configuration

File: `.claude/skills/file-size-guard/config.json`

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `limits` | object | (see above) | Glob pattern → max lines |
| `allowlist` | array | `[]` | Exempt file paths (relative) |
| `scan_exclude_dirs` | array | (see config) | Directories to skip in scan |
| `scan_exclude_files` | array | (see config) | File patterns to skip |
| `check_on_write` | boolean | `true` | Toggle hook on/off |
| `min_line_threshold` | integer | `10` | Skip files below this line count |

## Relationship to tech-debt-checker

| Aspect | file-size-guard | tech-debt-checker |
|--------|----------------|-------------------|
| Timing | Real-time (hook) | Periodic (manual/cron) |
| Weight | Milliseconds | Seconds-minutes |
| Scope | Line count only | 6-dimension debt audit |
| Allowlist | Independent | Independent |
| Behavior | Warn only | Gate + report |

Complementary: hook for real-time awareness, tech-debt-checker for comprehensive audit.

## Splitting Guidance (STANDARDS.md §三.3)

When warning fires, the recommended approach:

1. **Split by responsibility boundary** — each file has one clear purpose
2. **Split by semantic boundary** — grouped by domain/feature
3. **Split by dependency boundary** — minimize cross-file coupling
4. **NEVER split mechanically** — `part1.py`, `part2.py` is forbidden
5. **Temporary files need exit conditions** — `*_new.py` must have owner + retirement date
