---
name: plugin-doctor
description: Scan, health-check, and update all installed plugins, skills, GSD, and runtime across Claude Code, Codex, and OpenCode. Trigger: /plugin-doctor
---

# Plugin Doctor

Manage the health and versions of all installed extensions across supported AI coding runtimes.

## Triggers

- `/plugin-doctor` — full scan + dashboard report
- `/plugin-doctor --outdated` — show only items needing attention
- `/plugin-doctor --type <type>` — filter by type (plugin, skill, gsd, runtime)
- `/plugin-doctor --update` — interactive update: show outdated items, ask which to update
- `/plugin-doctor --update --all` — non-interactive: update all outdated items
- `/plugin-doctor --update --id <pluginId>` — update a specific plugin
- `/plugin-doctor --fix` — scan + auto-fix repairable health issues

## Arguments

Parse `ARGUMENTS` string for these flags:

| Flag | Effect |
|------|--------|
| (none) | Full scan + dashboard report |
| `--outdated` | Show only outdated/error items (compact view) |
| `--type <type>` | Filter by type: `plugin`, `skill`, `gsd`, `runtime` |
| `--update` | Interactive update: show outdated items, ask which to update |
| `--update --all` | Non-interactive: update all outdated items |
| `--update --id <id>` | Update a single plugin by its full id |
| `--fix` | Auto-fix repairable health issues (clear stale cache, etc.) |

## Process

### Step 1: Run scan

Execute `node "$SKILL_DIR/bin/plugin-doctor-scan.cjs" --json` and capture JSON output.

If exit code is non-zero, display the error and exit.

### Step 2: Run health checks

Pipe scan output into `node "$SKILL_DIR/bin/plugin-doctor-health.cjs"`:

```bash
node "$SKILL_DIR/bin/plugin-doctor-scan.cjs" --json | node "$SKILL_DIR/bin/plugin-doctor-health.cjs"
```

Capture the augmented JSON (each plugin entry now has `health` and `issues` fields).

### Step 3: Display report

Compute these aggregate values from the JSON before rendering:

```
total = count of all plugins across all runtimes
healthy = count where health === "healthy"
outdated = count where status === "outdated"
errors = count where health === "error"
warns = count where health === "warn"
```

Also group each runtime's plugins by type: `{ plugin: [...], skill: [...], gsd: [...], runtime: [...] }`.

#### 3a: Apply filters (if any)

If `--outdated` flag: only include entries where `status === "outdated"` OR `health === "error"` OR `health === "warn"`. Dashboard summary still shows full counts.

If `--type <type>` flag: only include entries where `type === <type>`. Dashboard summary still shows full counts.

#### 3b: Dashboard

Always display the dashboard first, using a markdown table:

```
## Plugin Doctor

| Runtime | Version | Plugins | Skills | GSD | Status |
|---------|---------|---------|--------|-----|--------|
| Claude Code | 2.1.116 | 27 | 79 | 1 | ✔ |
| Codex | 0.133.0 | 1 | 2 | 1 | ⚠ 1 outdated |
| OpenCode | 1.14.35 | 0 | 0 | 0 | — |

**Scan: 113 items | 112 ✔ healthy | 1 ↑ outdated | 0 ✘ errors** | _Scanned at 2026-05-24 10:30 UTC_
```

Runtime Status column rules:
- ✔ if all items in that runtime are healthy AND current
- ⚠ with count if any outdated/warn items
- ✘ with count if any error items
- — if runtime not detected (no configDir)

#### 3c: Items Needing Attention (if any)

If any entries have `status === "outdated"` OR `health !== "healthy"`, show this section FIRST (before healthy items):

```
### Items Needing Attention (3)

| ID | Type | Installed | Latest | Health | Issue |
|----|------|-----------|--------|--------|-------|
| claude-code-runtime | runtime | 2.1.116 | 2.1.150 | ↑ outdated | — |
| broken-plugin@marketplace | plugin | 1.0.0 | — | ✘ error | install path missing |
| stale-cache@omc | plugin | 4.13.7 | 4.13.7 | ⚠ warn | stale cache (45d old) |
```

Health column symbols:
- ↑ outdated
- ⚠ warn
- ✘ error
- ✔ healthy (only shown in full view)

#### 3d: Runtime

Always show runtime table (at most 3 rows, always expanded):

```
### Runtime (3)

| Name | Installed | Latest | Status |
|------|-----------|--------|--------|
| claude-code | 2.1.116 | 2.1.150 | ↑ outdated |
| codex | 0.133.0 | 0.133.0 | ✔ |
| opencode | 1.14.35 | — | ✔ |
```

#### 3e: Plugins — always expanded

Always show the full plugins table (typically 10-30 entries, manageable without collapsing):

```
### Plugins (27)

| Name | Marketplace | Version | Latest | Status | Updated |
|------|-------------|---------|--------|--------|---------|
| superpowers | claude-plugins-official | 5.1.0 | 5.1.0 | ✔ | 2026-04-14 |
| oh-my-claude | omc | 4.13.7 | 4.13.7 | ✔ | 2026-05-01 |
| ... | | | | | |
```

#### 3f: GSD

Always show the GSD table (at most 3 rows):

```
### GSD (2)

| Runtime | Version | Latest | Status |
|---------|---------|--------|--------|
| Claude Code | 1.42.3 | 1.42.3 | ✔ |
| OpenCode | 1.36.0 | — | ✔ |
```

#### 3g: Skills — hierarchical grouped display

Skills are grouped by **family** (level 1) then **sub-group** (level 2). Apply these classification rules to each skill's `name` field:

**Family classification rules:**

| Family | Match Rule | Examples |
|--------|-----------|----------|
| GSD | name starts with `gsd-` | gsd-plan-phase, gsd-debug |
| GitNexus | name starts with `gitnexus-` | gitnexus-cli, gitnexus-guide |
| Standalone | everything else | graphify, plugin-doctor |

**GSD sub-group classification rules** (applied to name after stripping `gsd-` prefix):

| Sub-group | Match keywords in remaining name |
|-----------|-------------------------------|
| Planning | `plan-phase`, `spec-phase`, `ultraplan-phase`, `mvp-phase`, `ui-phase`, `ai-integration-phase`, `discuss-phase`, `sketch`, `spike` |
| Execution | `execute-phase`, `fast`, `quick`, `autonomous`, `dispatching-parallel`, `ship`, `pr-branch` |
| Review & Audit | `code-review`, `audit-fix`, `audit-uat`, `audit-milestone`, `eval-review`, `ui-review`, `secure-phase`, `validate-phase`, `review-backlog`, `plan-review-convergence`, `review` |
| Project Lifecycle | `new-project`, `new-milestone`, `complete-milestone`, `milestone-summary`, `progress`, `phase`, `workstream` |
| Config & Ops | `workspace`, `manager`, `config`, `settings`, `surface`, `help`, `cleanup`, `ns-manage`, `inbox`, `update` |
| Intelligence | `map-codebase`, `capture`, `extract-learnings`, `profile-user`, `explore`, `grill-me`, `grill-with-docs`, `docs-update`, `ingest-docs`, `import` |
| Work Ops | `add-tests`, `verify-work`, `resume-work`, `pause-work`, `thread`, `undo`, `doc-writer`, `doc-classifier`, `doc-verifier`, `doc-synthesizer` |
| Diagnostics | `debug`, `forensics`, `graphify`, `health` |
| Namespace (ns-*) | name starts with `ns-` |

**Display format:**

```
### Skills (81)

**GSD** (67)

| Sub-group | Count | Skills |
|-----------|-------|--------|
| Review & Audit | 11 | audit-fix, audit-milestone, audit-uat, code-review, eval-review, plan-review-convergence, review, review-backlog, secure-phase, ui-review, validate-phase |
| Intelligence | 8 | capture, docs-update, explore, extract-learnings, grill-me, grill-with-docs, import, ingest-docs |
| Work Ops | 7 | add-tests, doc-classifier, doc-synthesizer, doc-verifier, doc-writer, pause-work, resume-work, thread, undo, verify-work |
| Planning | 7 | ai-integration-phase, discuss-phase, mvp-phase, plan-phase, sketch, spec-phase, ui-phase |
| Project Lifecycle | 7 | complete-milestone, milestone-summary, new-milestone, new-project, phase, progress, workstream |
| Config & Ops | 7 | cleanup, config, help, inbox, manager, settings, surface, update |
| Namespace | 6 | ns-context, ns-ideate, ns-manage, ns-project, ns-review, ns-workflow |
| Execution | 4 | autonomous, execute-phase, fast, quick |
| Diagnostics | 4 | debug, forensics, graphify, health |

**GitNexus** (6)

| Skill | Description |
|-------|-------------|
| gitnexus-cli | CLI commands for index and status |
| gitnexus-debugging | Trace bugs via execution flows |
| gitnexus-exploring | Search and understand code |
| gitnexus-guide | Tools and schema reference |
| gitnexus-impact-analysis | Blast radius before editing |
| gitnexus-refactoring | Safe multi-file refactoring |

**Standalone** (8)

| Skill | Runtime | Version |
|-------|---------|---------|
| graphify | claude-code | abc1234 |
| impeccable | claude-code | — |
| kami | claude-code | 1.0.0 |
| plugin-doctor | claude-code | — |
| review2md | claude-code | — |
| karpathy-guidelines | codex | — |
| meeting-notes-and-actions | codex | — |
| zread-skill | codex | — |
```

**GitNexus description mapping:** Use these static descriptions (they don't change between scans):

| Skill | Description |
|-------|-------------|
| gitnexus-cli | Index, status, clean, config commands |
| gitnexus-debugging | Trace bugs via execution flows |
| gitnexus-exploring | Search and navigate code concepts |
| gitnexus-guide | Tools, resources, schema reference |
| gitnexus-impact-analysis | Blast radius before editing |
| gitnexus-refactoring | Safe multi-file rename/extract/split |

For Standalone skills where description is unknown, show `—`.

Type display order: Items Needing Attention → Runtime → Plugins → GSD → Skills.

### Step 4: Handle flags

**If `--outdated` (no `--update`):**

Show only the Dashboard + Items Needing Attention section. Skip all grouped detail tables.

**If `--type <type>`:**

Show Dashboard (full counts) + only the detail section for the requested type:
- `--type plugin`: show full Plugins table
- `--type skill`: show full hierarchical Skills section
- `--type gsd`: show GSD table
- `--type runtime`: show Runtime table

**If `--update` (no `--all`):**

Use AskUserQuestion to present outdated items:

- Question: "Which plugins do you want to update?"
- Options: each outdated plugin as a multi-select option
- Include a "Update all" option

**If `--update --all`:**

Proceed to update all outdated items without asking.

**If `--update --id <id>`:**

Update only the specified plugin.

**If `--fix`:**

For each issue with `fixable: true`:
1. Display the fix action
2. Execute the fix
3. Report result

### Step 5: Run updates

Execute `node "$SKILL_DIR/bin/plugin-doctor-update.cjs"` with appropriate arguments:

```bash
# Update all
node "$SKILL_DIR/bin/plugin-doctor-update.cjs" --all"

# Update specific
node "$SKILL_DIR/bin/plugin-doctor-update.cjs" --id "superpowers@claude-plugins-official"

# Dry run
node "$SKILL_DIR/bin/plugin-doctor-update.cjs" --all --dry-run
```

The update script handles each plugin type with the correct update method.

### Step 6: Display results

Show a summary of what was updated, what failed, and what was skipped:

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
