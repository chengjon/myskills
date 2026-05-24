# Plugin Doctor — Design Spec

> Date: 2026-05-23
> Status: Draft

## Overview

A skill (`/plugin-doctor`) that scans, health-checks, and updates all installed extensions across supported AI coding runtimes (Claude Code, Codex, OpenCode). It provides a unified view of plugins, skills, GSD framework, and runtime versions with one command.

## Scope

### In Scope

- Claude Code plugins (marketplace-installed, 27 plugins from 14 marketplaces)
- GSD framework (get-shit-done)
- Manually installed skills (gitnexus-*, graphify, etc.)
- Claude Code runtime itself (`claude --version`)
- Codex plugins (when `~/.codex/` exists)
- OpenCode plugins (when `~/.config/opencode/` or `~/.opencode/` exists)
- Health checks: integrity, cache, configuration validation

### Out of Scope

- Gemini, Kilo runtime support (future extension points only)
- Marketplace management (add/remove marketplaces)
- Plugin installation from scratch
- Automatic scheduled updates

## Architecture

### File Structure

```
~/.claude/skills/plugin-doctor/
├── SKILL.md                          # Skill definition and dispatch logic
├── DESIGN.md                         # This design spec
└── bin/
    ├── plugin-doctor-scan.cjs        # Scan all sources, output JSON
    ├── plugin-doctor-health.cjs      # Augment entries with health diagnostics
    └── plugin-doctor-update.cjs      # Execute updates per plugin type
```

### Data Flow

```
[scan.cjs] --JSON--> [health.cjs] --JSON--> [SKILL.md formats output]
                                                     |
                                        [--update flag?]
                                                     |
                                          [update.cjs] -- executes updates
```

Each module is independent and testable in isolation. They communicate via structured JSON on stdout.

## Data Model

### Scan Output

```jsonc
{
  "scanTime": "2026-05-23T12:00:00Z",
  "runtimes": [
    {
      "runtime": "claude-code",
      "runtimeVersion": "4.7.0",
      "configDir": "/root/.claude",
      "plugins": [/* PluginEntry[] */]
    },
    {
      "runtime": "codex",
      "runtimeVersion": null,
      "configDir": "/root/.codex",
      "plugins": []
    },
    {
      "runtime": "opencode",
      "runtimeVersion": null,
      "configDir": "/root/.config/opencode",
      "plugins": []
    }
  ]
}
```

### PluginEntry

```jsonc
{
  "id": "superpowers@claude-plugins-official",
  "name": "superpowers",
  "marketplace": "claude-plugins-official",
  "type": "plugin",          // "plugin" | "gsd" | "skill" | "runtime"
  "scope": "user",
  "enabled": true,
  "installPath": "/root/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0",
  "installedVersion": "5.0.0",
  "latestVersion": "5.1.0",  // null if cannot determine
  "status": "outdated",      // "current" | "outdated" | "unknown" | "error"
  "installedAt": "2026-03-07T00:00:00Z",
  "lastUpdated": "2026-05-05T00:00:00Z",
  "gitCommitSha": "abc123...",
  "source": {
    "type": "git",
    "url": "https://github.com/anthropics/claude-code.git"
  }
}
```

### HealthIssue

```jsonc
{
  "severity": "warn",          // "error" | "warn" | "info"
  "category": "integrity",     // "integrity" | "cache" | "config"
  "message": "Stale version cache (fetched 30+ days ago)",
  "fixable": true,
  "fixAction": "clear-cache"   // machine-readable fix identifier
}
```

### Health-Augmented PluginEntry

After health.cjs processes an entry, it adds:

```jsonc
{
  // ... all PluginEntry fields ...
  "health": "warn",            // "healthy" | "warn" | "error" | "unknown"
  "issues": [/* HealthIssue[] */]
}
```

## Supported Runtimes

| Runtime | Config Dir (priority order) | Version Command | Plugin Update Command |
|---------|----------------------------|-----------------|----------------------|
| Claude Code | `$CLAUDE_CONFIG_DIR` → `~/.claude/` | `claude --version` | `claude plugins update <plugin>` |
| Codex | `$CODEX_HOME` → `~/.codex/` | `codex --version` | Per Codex CLI mechanism |
| OpenCode | `$OPENCODE_CONFIG_DIR` → `~/.config/opencode/` → `~/.opencode/` | `opencode --version` | Per OpenCode CLI mechanism |

**Runtime Detection Logic** (applied in order, first match wins):

```
Claude Code:  $CLAUDE_CONFIG_DIR set OR ~/.claude/ exists
Codex:        $CODEX_HOME set OR ~/.codex/ exists
OpenCode:     $OPENCODE_CONFIG_DIR set OR ~/.config/opencode/ exists OR ~/.opencode/ exists
```

Each runtime uses the same internal plugin structure (`plugins/installed_plugins.json`, `plugins/cache/`, `plugins/marketplaces/`) so scan logic is shared.

## Module Specifications

### 1. scan.cjs

**Input**: None (reads filesystem directly)
**Output**: JSON to stdout

**Scan Sources (per runtime)**:

| Priority | Source | PluginEntry.type | Version Source | Latest Version Source |
|----------|--------|-----------------|----------------|----------------------|
| 1 | `installed_plugins.json` | `plugin` | Cache dir `package.json` | Marketplace git repo `package.json` |
| 2 | `get-shit-done/VERSION` | `gsd` | VERSION file | npm registry (via check-latest-version.cjs) |
| 3 | `skills/*/SKILL.md` | `skill` | `skills/*/package.json` or git SHA | `git ls-remote HEAD` |
| 4 | Runtime binary | `runtime` | `claude --version` / `codex --version` / `opencode --version` | npm registry |

**Latest Version Resolution for Plugins**:

1. Read `known_marketplaces.json` to get marketplace source URL
2. `git fetch` the marketplace repo (with 60s timeout)
3. Parse the plugin's `package.json` from the fetched repo
4. Compare installed vs fetched version

**Error Handling**:

- If a marketplace git fetch fails: set `latestVersion: null`, `status: "unknown"`
- If `installed_plugins.json` is missing: skip plugin scan for that runtime
- If cache directory is missing: mark as `status: "error"` with health issue

### 2. health.cjs

**Input**: JSON from scan.cjs on stdin
**Output**: Augmented JSON to stdout (same structure + health fields)

**Checks**:

| Category | Check | Severity | Fixable |
|----------|-------|----------|---------|
| integrity | `installPath` directory exists | error | false |
| integrity | `package.json` or VERSION file present in installPath | error | false |
| integrity | `gitCommitSha` exists in marketplace git history | warn | false |
| config | `installed_plugins.json` entry matches cache directory structure | error | false |
| config | Skill frontmatter has required fields (name, description) | warn | false |
| cache | Multiple version directories for same plugin in cache | warn | true |
| cache | Disabled plugin still has cache directory | info | true |
| cache | `install-counts-cache.json` older than 30 days | info | true |

**Fix Actions**:

| Fix ID | Action |
|--------|--------|
| `clear-old-cache` | Remove version directories other than the installed one |
| `clear-disabled-cache` | Remove cache for disabled plugins |
| `refresh-install-counts` | Clear install-counts-cache.json to force refresh |

### 3. update.cjs

**Input**: Command-line arguments
**Output**: JSON to stdout with update results

**Arguments**:

```
--all            Update all outdated items
--id <id>        Update specific plugin by full id
--runtime <name> Only update within specified runtime
--dry-run        Show what would be updated without executing
--json           Output results as JSON (for programmatic use)
```

**Update Methods by Type and Runtime**:

| Runtime | Type | Method | Command |
|---------|------|--------|---------|
| Claude Code | plugin | Official CLI | `claude plugins update <plugin>` |
| Claude Code | GSD | npm package update | `npx -y --package=get-shit-done-cc@latest -- get-shit-done-cc --claude --global` |
| Codex | plugin | Codex CLI | Per Codex's update mechanism |
| Codex | GSD | npm package update | `npx -y --package=get-shit-done-cc@latest -- get-shit-done-cc --codex --global` |
| OpenCode | plugin | OpenCode CLI | Per OpenCode's update mechanism |
| OpenCode | GSD | npm package update | `npx -y --package=get-shit-done-cc@latest -- get-shit-done-cc --opencode --global` |
| All | Manual skill (git) | git pull | `git -C <dir> pull --ff-only` |
| All | Runtime | npm/cargo/binary update | Per runtime's update mechanism |

**Result Format**:

```jsonc
{
  "results": [
    {
      "id": "superpowers@claude-plugins-official",
      "action": "updated",
      "fromVersion": "5.0.0",
      "toVersion": "5.1.0",
      "success": true,
      "message": null
    },
    {
      "id": "oh-my-claudecode@omc",
      "action": "skipped",
      "fromVersion": "4.13.7",
      "toVersion": null,
      "success": true,
      "message": "already on latest version"
    }
  ]
}
```

## Terminal Output Format

### Filter Flags

| Flag | Effect |
|------|--------|
| `--outdated` | Show only outdated/error items (compact view) |
| `--type <type>` | Filter by type: `plugin`, `skill`, `gsd`, `runtime`. Overrides smart collapsing — always shows full table |

### Default (scan + health)

```
## Plugin Doctor

| Runtime | Version | Plugins | Skills | GSD | Status |
|---------|---------|---------|--------|-----|--------|
| Claude Code | 2.1.116 | 27 | 79 | 1 | ✔ |
| Codex | 0.133.0 | 1 | 2 | 1 | ⚠ 1 outdated |
| OpenCode | 1.14.35 | 0 | 0 | 0 | — |

**Scan: 113 items | 112 ✔ healthy | 1 ↑ outdated | 0 ✘ errors** | _Scanned at 2026-05-24 10:30 UTC_

---

### Items Needing Attention (1)

| ID | Type | Installed | Latest | Health | Issue |
|----|------|-----------|--------|--------|-------|
| claude-code-runtime | runtime | 2.1.116 | 2.1.150 | ↑ outdated | — |

### Runtime

| Name | Installed | Latest | Status |
|------|-----------|--------|--------|
| claude-code | 2.1.116 | 2.1.150 | ↑ outdated |
| codex | 0.133.0 | 0.133.0 | ✔ |

### Plugins (27)

| Name | Marketplace | Version | Latest | Status | Updated |
|------|-------------|---------|--------|--------|---------|
| superpowers | claude-plugins-official | 5.1.0 | 5.1.0 | ✔ | 2026-04-14 |
| oh-my-claude | omc | 4.13.7 | 4.13.7 | ✔ | 2026-05-01 |

### GSD

| Runtime | Version | Latest | Status |
|---------|---------|--------|--------|
| Claude Code | 1.42.3 | 1.42.3 | ✔ |

### Skills (79) — ✔ all healthy
> 79 skills installed in `~/.claude/skills/` — use `--type skill` to list individually
```

### `--outdated` Mode

```
## Plugin Doctor — Outdated Only

| Runtime | Version | Plugins | Skills | GSD | Status |
|---------|---------|---------|--------|-----|--------|
| Claude Code | 2.1.116 | 27 | 79 | 1 | ⚠ 1 outdated |
| Codex | 0.133.0 | 1 | 2 | 1 | ✔ |
| OpenCode | 1.14.35 | 0 | 0 | 0 | — |

**Scan: 113 items | 1 ↑ outdated**

### Items Needing Attention (1)

| ID | Type | Installed | Latest | Health | Issue |
|----|------|-----------|--------|--------|-------|
| claude-code-runtime | runtime | 2.1.116 | 2.1.150 | ↑ outdated | — |
```

### `--type skill` Mode

```
## Plugin Doctor — Skills Only

| Runtime | Version | Plugins | Skills | GSD | Status |
|---------|---------|---------|--------|-----|--------|
| Claude Code | 2.1.116 | 27 | 79 | 1 | ✔ |
| Codex | 0.133.0 | 1 | 2 | 1 | ✔ |
| OpenCode | 1.14.35 | 0 | 0 | 0 | — |

**Scan: 113 items | 112 ✔ healthy**

### Skills (79)

| Name | Version | Status | Health |
|------|---------|--------|--------|
| gitnexus-guide | abc1234 | unknown | ✔ |
| graphify | 1.0.0 | current | ✔ |
| plugin-doctor | — | unknown | ✔ |
| ... | | | |
```

### Update Mode

```
### Update Complete

| Status | Count |
|--------|-------|
| ✔ Updated | 2 |
| ⊘ Skipped | 1 |
| ✘ Failed | 0 |

| ID | From | To | Result |
|----|------|----|--------|
| superpowers@claude-plugins-official | 5.0.0 | 5.1.0 | ✔ updated |
| compound-engineering@every-marketplace | 2.12.0 | 2.13.0 | ✔ updated |
| oh-my-claudecode@omc | 4.13.7 | — | ⊘ already current |
```

## Skill Dispatch Logic (SKILL.md)

1. Parse `ARGUMENTS` for flags
2. Run `scan.cjs --json`
3. Pipe into `health.cjs`
4. Compute aggregates (total, healthy, outdated, errors, warns) and group by type
5. Apply filters:
   - `--outdated`: keep only items with status=outdated or health≠healthy
   - `--type <type>`: keep only matching type entries
6. Render output:
   a. Always show Dashboard table
   b. Show Items Needing Attention (if any problems exist)
   c. Show grouped detail tables (smart collapse for healthy skills ≥5)
   d. If no flags: show full report
   e. If `--outdated`: show only Dashboard + Items Needing Attention
   f. If `--type`: show Dashboard + only requested type's detail table
7. If `--fix`: execute auto-fixable issues, display results. Cannot be combined with `--update`.
8. If `--update`:
   a. Filter to outdated items
   b. If `--all`: proceed without asking
   c. If `--id <id>`: proceed with single item
   d. Otherwise: AskUserQuestion with multi-select
   e. Run `update.cjs` with selected items
   f. Display update results

## Error Handling

- **Scan failure**: Show partial results + error message. Don't abort if one runtime fails.
- **Health check failure**: Mark plugin as `health: "unknown"`, continue.
- **Update failure**: Report failure per-plugin, don't abort batch. Show rollback instructions.
- **Network failure**: Scan still works (uses local data), latestVersion shows `null`.

## Security Considerations

- Never execute arbitrary code from plugin directories
- Validate all paths before file operations (no path traversal)
- Use `--ff-only` for git operations to prevent divergent merges
- Confirm before deleting any files (cache cleanup)
- Don't expose API keys or credentials in output

## Testing Strategy

- Unit tests for each module with fixture data
- Integration test: full scan on a test environment with known plugins
- Mock marketplace git repos for version comparison tests
- Test edge cases: missing files, corrupted JSON, network timeouts

## Success Criteria

- [ ] Scans all 4 source types (plugins, GSD, skills, runtime)
- [ ] Groups output by runtime (Claude Code / Codex / OpenCode)
- [ ] Dashboard overview with per-runtime health at a glance
- [ ] Markdown tables for all detail views
- [ ] Smart collapse: healthy skills ≥5 collapsed to one-line summary
- [ ] Detects outdated plugins by comparing with marketplace
- [ ] Runs health checks across integrity, cache, config categories
- [ ] `--outdated` flag shows only items needing attention
- [ ] `--type <type>` flag filters by plugin type
- [ ] Updates plugins via official CLI per runtime
- [ ] Updates GSD via npm with correct runtime flag
- [ ] Handles partial failures gracefully
