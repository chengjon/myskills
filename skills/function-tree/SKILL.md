---
name: function-tree
description: Use when governing FUNCTION_TREE-linked work, creating or refreshing FUNCTION_TREE.md, using /ft commands, collecting evidence, authorizing scope, checking active gates, or performing FUNCTION_TREE closeout.
---

# Function Tree Governance

Use this skill to keep FUNCTION_TREE work serialized, evidence-backed, and scoped. `FUNCTION_TREE.md` is the project's current/future feature tree: it records existing features plus planned/unfinished features, giving developers a direction guide so new work can stay aligned and avoid drift. The skill governs work; it does not itself authorize source edits.

Trigger on `/ft`, `FUNCTION_TREE.md`, `FUNCTION_TREE governance`, `function tree gate`, scope authorization, evidence collection, active gates, or FUNCTION_TREE closeout requests.

## Quick Start

1. Resolve the repository root.
2. Run the deterministic helper for state files and guards:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" <command> [args]
```

3. Read `references/STATE_MACHINE.md` for transition rules before moving a node.
4. Read `references/STEWARD_PROFILE.md` when the work needs cross-tool responsibility boundaries or derived steward indexes.
5. If the repository defines project-local governance instructions, such as `.governance/profile.md` or agent rules, load them before authorization or implementation gates.

## Commands

| User command | Helper command | Purpose |
|--------------|----------------|---------|
| `/ft:init <program> --ref <node>` | `init <program> --ref <node>` | Create `.governance/programs/<program>/`, active gate files, and a function-tree-style root `FUNCTION_TREE.md` seeded from README feature lists, entrypoint-derived feature candidates, source modules, source TODOs, UI/page routes, navigation/menu links, API/OpenAPI routes, documented command examples, and common package/Cargo/Python/Go/Make/Just/Task commands |
| `/ft:doc` | `doc` | Refresh root `FUNCTION_TREE.md` while preserving function-tree sections, project notes, and auto-discovered feature/roadmap candidates |
| `/ft:new-node <program> <node-id>` | `new-node <program> <node-id> --title <text> --ref <node> [--type <kind>] [--owner-lane <lane>] [--parent <id>] [--freshness <policy>] [--track <mainline\|backlog\|optimize\|untracked>] [--mainline-id <root-node-id>] [--depth <0\|1\|2\|99>]` | Add a planning node and active gate; steward fields are optional and do not replace `status`. `--track`/`--mainline-id`/`--depth` are optional mainline-layering fields (Phase 1) |
| `/ft:observe <program> <node-id> --evidence <path-or-note>` | `observe <program> <node-id> --evidence <path-or-note>` | Record evidence with current `HEAD`; source edits stay unauthorized |
| `/ft:authorize <program> <node-id>` | `authorize <program> <node-id> --allowed ... --non-goal ...` | Generate task card, scope, non-goals, and acceptance gates |
| `/ft:transition <program> <node-id> --to <status>` | `transition <program> <node-id> --to <status>` | Move through legal states and block stale implementation approval |
| `/ft:implement <program> <node-id>` | `scope-check` | Confirm edits remain inside active authorization |
| `/ft:closeout <program> <node-id>` | `closeout <program> <node-id> --summary <path-or-note>` | Record landed summary, compatibility, and passed gates |
| `/ft:gate [--verbose]` | `gate [--verbose]` | Show active blockers and next allowed action |
| `/ft:status` | `status` | Summarize governance programs and active gates |
| `/ft:steward-sync` | `steward-sync` | Derive `.governance/steward/` relationship index, current next gates, evidence index, and track files from program nodes |
| `/ft:install-guard` | `install-guard [--force]` | Install `.governance/guards/ft-scope-check.sh` (PostToolUse: scope-check) + `.governance/guards/pre-commit` (drift-check --staged); print hook integration snippets for git core.hooksPath / husky / lefthook / Claude Code settings.json |
| `/ft:repair` | `repair` | Rebuild active gates from program nodes and drop closed/archived gates |
| `/ft:mainline` | `mainline` | Print the active mainline tree (depth=0 root + depth=1/2 children + backlog + switch-lock state). Use to verify work stays on the唯一 active mainline |
| `/ft:locate <file>` | `locate <file>` | Resolve which track (mainline/backlog/optimize/untracked) a file belongs to via `.governance/file-to-track.json`. Use before edits to catch drift |
| `/ft:map` | `map` | Rebuild the file-to-track reverse index and print coverage stats (files per track). Idempotent; safe to run anytime |
| `/ft:drift-check` | `drift-check --files <a,b,c> \| --staged` | Strict drift detector. Exit 0 = all files on mainline (or backlog/optimize with warning); exit 1 = any UNTRACKED file; exit 2 = bad args. Outputs JSON lines per file + summary |
| `/ft:accept-drift` | `accept-drift --reason <text> --files <a,b,c> [--expires <spec>] [--mainline <id\|none>] [--by <name>]` | Phase 3. Write a temporary drift-acceptance record binding files to the current active mainline. `--expires` default `30d`; `0` for permanent; format `<N><s\|m\|h\|d\|w>`. Files must exist on disk. See Phase 3 section for binding semantics |
| `/ft:revoke-drift` | `revoke-drift --id <acceptance-id>` | Phase 3. Mark an acceptance `revoked` (record kept for audit). Exit 1 if id not found or already revoked |
| `/ft:config` | `config [list\|get\|set] [--key <name>] [--value <text>]` | Phase 4. Read/write `.governance/config.json`. Keys: `drift_check_mode` (hard/soft/off), `hooks_mode` (on/off), `mainline_warning` (bool), `auto_accept_suggest` (bool). Env vars `FT_DRIFT_CHECK_MODE` / `FT_HOOKS_MODE` / `FT_MAINLINE_WARNING` / `FT_AUTO_ACCEPT_SUGGEST` override file values |
| `/ft:session-start` | `session-start` | Phase 4. Print compact session context: active mainline + descendants, worktree drift counts via `git status --porcelain`, active acceptances + nearest expiry, next-gate suggestion. Designed for Claude Code SessionStart hook `additionalContext` |
| `/ft:pre-edit` | `pre-edit --files <a,b,c>` | Phase 4. PreToolUse hook for Edit/Write/MultiEdit. Emits Claude Code hook JSON: `{decision:"approve"}` or `{decision:"block", reason, context}`. Honors `drift_check_mode` (hard=block, soft=approve+warning, off=skip) and `hooks_mode`. Suggests `accept-drift` or `authorize` cmd templates |

## Mainline Layering (Phase 1)

Nodes carry an optional `track` field (`mainline` / `backlog` / `optimize` / `untracked`) plus `depth` (0=root, 1/2=children, 99=non-mainline) and `mainline_id` (parent root's node id). Missing fields auto-resolve to `untracked` / depth 99 at read time — existing nodes need no migration.

**Mainline uniqueness rule**: at most one active (non-closed) `track=mainline depth=0` node should exist. `ft mainline` warns when this is violated; Phase 2 will hard-enforce via `validate full`.

**Switch-lock**: while an active mainline exists, backlog/optimize nodes cannot be authorized — `/ft:mainline` prints `切换锁：active` to surface this. Run `/ft:mainline` before starting work and `/ft:locate <file>` before editing to catch drift early.

Phase 1 only adds read-only visibility (`ft mainline` / `ft locate` / `ft map`). Accept/reject drift prompts, validate-full mainline rules, and hook enforcement arrive in Phase 2-4.

## Mainline Enforcement (Phase 2)

Phase 2 hardens the read-only visibility into write-time checks:

**`validate full` mainline rules** (run automatically when `.governance/programs/` exists):

- **V-MAINLINE-UNIQUE**: error if more than one active `track=mainline depth=0` node exists
- **V-MAINLINE-ORPHAN**: error if a `track=mainline depth=1/2` node's `mainline_id` doesn't resolve to a mainline root
- **V-BACKLOG-LOCK**: error if any `track=backlog`/`optimize` node is in `authorized`/`implementation` status while an active mainline exists (switch lock violation); warning if such a node is still in `planning`
- **V-DEPTH-MISMATCH**: error if `depth=0` node has `mainline_id != self.id`, or `depth=1/2` node has `mainline_id == self.id` / missing

**`ft drift-check` exit codes (strict mode)**:

| Situation | Exit | Output |
|---|---|---|
| All files tracked (any track) | 0 | JSON lines + summary, silent unless backlog/optimize warning |
| Any file UNTRACKED | 1 | JSON lines + `HARD FAIL: N file(s) UNTRACKED` |
| Missing `--files` or `--staged` | 2 | `drift-check requires --files <a,b,c> or --staged` |

Output format per file: `{"file": "<rel>", "track": "<mainline|backlog|optimize|untracked>", "drift": <bool>, "active_mainline": "<prog/id|null>", "node_id": "...", "program": "...", "mainline_id": "...", "depth": <n>}`.

Use `ft drift-check --staged` in pre-commit hooks (Phase 4 target). `ft accept-drift` provides the opt-out escape hatch (see Phase 3); without an effective acceptance, UNTRACKED files still hard-fail drift-check.

## Drift Acceptance (Phase 3)

Phase 3 makes drift-check enforceable in practice by giving developers an explicit, audited opt-out. Without it, Phase 2's HARD FAIL on UNTRACKED files would block every commit that touches a non-mainline file.

**`ft accept-drift --reason <text> --files <a,b,c> [--expires <spec>] [--mainline <id|none>] [--by <name>]`**

Writes one record to `.governance/drift-acceptances.json`:

```json
{
  "id": "drift-2026-06-19-001",
  "files": ["scripts/cleanup_legacy.py"],
  "reason": "<mandatory audit text>",
  "accepted_at": "2026-06-19T14:30:00Z",
  "accepted_by": "<$LOGNAME or --by>",
  "mainline_at_accept": "B1.000",
  "expires_at": "2026-07-19T14:30:00Z",
  "status": "active"
}
```

Acceptance is **effective** for a given file iff all hold:

- `status === 'active'`
- `mainline_at_accept === <current active mainline id>` (null matches "no active mainline"; mainline switch auto-invalidates prior acceptances — re-accept in the new cycle)
- `expires_at` is `null` (permanent) OR in the future

**`--expires` semantics** (matches the mainline methodology's "temporary override, time-bounded closure" rule):

| Input | Meaning |
|---|---|
| (omitted) | default 30 days from now |
| `0` or `permanent` | never expires (`expires_at = null`) |
| `<N><s\|m\|h\|d\|w>` | e.g. `7d`, `12h`, `2w`; parsed to seconds and added to now |

**`ft drift-check` upgrade** — exit code table extended:

| Situation | Exit |
|---|---|
| All files mainline OR accepted-drift | 0 |
| Any file UNTRACKED with no effective acceptance | 1 |
| Bad arguments | 2 |

UNTRACKED files with an effective acceptance are reported as `track: "accepted-drift"`, `drift: false`, `accepted: true`, `acceptance_id: "..."`, `expires_at: "permanent" | "<iso>"`. They no longer trigger HARD FAIL.

**`ft revoke-drift --id <acceptance-id>`** — sets `status: 'revoked'`, stamps `revoked_at`/`revoked_by`. Record is retained for audit (not deleted). Revoking a non-existent or already-revoked id exits 1.

**`validate full` rule**:

- **V-ACCEPTANCE-EXPIRED**: warning when an active acceptance's `expires_at` is in the past. Expired records are already ineffective in drift-check (no enforcement effect); the warning nudges the developer to revoke or re-accept so the audit file stays honest. Not an error — expiry is expected.
- **V-ACCEPTANCE-MALFORMED**: warning when `expires_at` is non-null but unparseable; drift-check treats such records as ineffective.

**Backlog binding is separate** (per mainline methodology): `accept-drift` is a *submission-level* audit opt-out, not a backlog promotion. Accepted-drift files do NOT get added to any backlog node's `allowed_paths`. Promoting a drifted file into a real backlog node requires manual `ft authorize` — keeping human-in-the-loop on every node-path change.

**Lifecycle**: accept → drift-check passes → (periodically review; convert to backlog node when stabilized via `ft authorize`) → revoke or let expire when the work is integrated or abandoned.

## Hook Integration (Phase 4)

Phase 4 wires drift-check into three intervention points so UNTRACKED drift is surfaced *before* a commit lands or an edit is applied — not after. All three honor `.governance/config.json` and the matching env vars.

**Configuration** (`ft config list` shows resolved values, env vars override file):

| Key | Values | Env override | Default |
|---|---|---|---|
| `drift_check_mode` | `hard` / `soft` / `off` | `FT_DRIFT_CHECK_MODE` | `hard` |
| `hooks_mode` | `on` / `off` | `FT_HOOKS_MODE` | `on` |
| `mainline_warning` | bool | `FT_MAINLINE_WARNING=1\|0` | `true` |
| `auto_accept_suggest` | bool | `FT_AUTO_ACCEPT_SUGGEST=1\|0` | `true` |

- `hard` = block commit / block edit (exit 1)
- `soft` = warn but allow (exit 0, message to stderr)
- `off` = skip entirely

**1. Pre-commit (git)** — runs `ft drift-check --staged`, blocks UNTRACKED in hard mode. Install:

```bash
ft install-guard            # writes .governance/guards/{ft-scope-check.sh, pre-commit}
# option A: git core.hooksPath (simplest)
git config core.hooksPath .governance/guards
# option B: symlink only pre-commit
ln -sf ../../.governance/guards/pre-commit .git/hooks/pre-commit
# option C: husky — add to .husky/pre-commit: bash .governance/guards/pre-commit
```

**2. Claude Code SessionStart** — injects session context (active mainline, drift counts, acceptances, next-gate suggestion). Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "command": "node $FT_GOVERNANCE_SCRIPT session-start --root $(git rev-parse --show-toplevel)",
      "description": "function-tree session context"
    }]
  }
}
```

**3. Claude Code PreToolUse (Edit/Write/MultiEdit)** — emits Claude Code hook JSON `{decision:"approve"|"block", reason, context}`. Suggests the exact `accept-drift` / `authorize` command for the file being edited. Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Edit|MultiEdit|Write",
      "command": "node $FT_GOVERNANCE_SCRIPT pre-edit --files {file}",
      "description": "function-tree drift-check + accept-drift suggestion"
    }],
    "PostToolUse": [{
      "matcher": "Edit|MultiEdit|Write",
      "command": "bash .governance/guards/ft-scope-check.sh",
      "description": "scope-check after edit"
    }]
  }
}
```

**Escape hatch**: `FT_DRIFT_CHECK_MODE=off git commit ...` or `FT_HOOKS_MODE=off` in the session skips all enforcement. Use sparingly; prefer `ft accept-drift` to keep the audit trail honest.

**Output contract for non-Claude integrations**: `ft pre-edit` exit codes align with drift-check (0=approve, 1=block, 2=bad args) so the same command works in editor plugins (VS Code, Neovim) that consume exit codes rather than JSON.

## Hard Rules

- Do not edit source code from `evidence-prepared`, `decision-prepared`, or `authorization-prepared`.
- Do not skip evidence collection before authorization.
- Do not use a GitHub issue or PR as the state-machine source of truth. Git commit, branch, and diff evidence are the hard source.
- Do not hand-edit generated active gate markdown; update JSON and run `sync`.
- Do not hand-edit generated steward profile artifacts; update program nodes and run `steward-sync`.
- Do not hand-edit the generated section of `FUNCTION_TREE.md`; it should remain a real feature tree with feature map, status registry, evidence, dependencies, and maintenance rules. Put durable local notes in its project-notes block and run `doc`.
- `doc` may regenerate skill-managed candidate sections when project evidence changes, but it must preserve project-notes and hand-maintained function-tree bodies.
- If evidence `current_head` differs from `HEAD`, mark the node stale before implementation.
- Project-specific impact, build, test, or compliance gates must be captured as explicit commit or closeout gates before implementation.

## Files

The helper creates and validates:

- `.governance/active-gates.json`
- `.governance/active-gates.md`
- `.governance/programs/<program>/tree.md`
- `.governance/programs/<program>/nodes.json`
- `.governance/programs/<program>/cards/*.yaml`
- `.governance/steward/steward-index.json`
- `.governance/steward/current-next-gates.md`
- `.governance/steward/evidence-index.md`
- `.governance/steward/tracks/*.md`
- `.governance/backups/FUNCTION_TREE.*.md`
- `.governance/file-to-track.json` (reverse file→track index, incrementally rebuilt by `ft map` / `ft locate`)
- `.governance/drift-acceptances.json` (Phase 3 audit log of accepted drift records, written by `ft accept-drift` / `ft revoke-drift`)
- `.governance/config.json` (Phase 4 governance config: drift_check_mode, hooks_mode, mainline_warning, auto_accept_suggest; written by `ft config set`)
- `.governance/guards/pre-commit` (Phase 4 git pre-commit hook calling `ft drift-check --staged`, generated by `ft install-guard`)
- `FUNCTION_TREE.md`

## References

- `references/STATE_MACHINE.md` - statuses, transitions, evidence classes, and command workflow.
- `references/STEWARD_PROFILE.md` - optional cross-tool responsibility contract and generated steward artifacts.
- `templates/` - deterministic starter files used by the helper.

Project-specific profiles belong in the consuming repository, not in this public skill.
