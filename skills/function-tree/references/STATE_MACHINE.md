# FUNCTION_TREE Governance State Machine

This skill adds a governance layer around an existing `FUNCTION_TREE.md`. It must not create a second function tree.

## Statuses

| Status | Meaning | Source edits authorized |
|--------|---------|-------------------------|
| `planning` | Candidate exists but facts are not collected | no |
| `evidence-prepared` | Baseline facts and evidence are recorded | no |
| `decision-prepared` | Decision package is ready for review | no |
| `authorization-prepared` | Scope, task card, and gates are drafted | no |
| `approved-for-implementation` | Implementation scope is explicitly approved | yes |
| `implementation-ready` | Changes are prepared and bound to Git evidence | yes |
| `implementation-landed` | Changes landed in target branch or commit range | no |
| `closeout-prepared` | Closeout report and FUNCTION_TREE delta are ready | no |
| `closed` | Governance node is complete | no |
| `blocked` | A blocker prevents forward progress | no |
| `archived` | Node is intentionally retired | no |

`blocked` requires `blocker_reason`, `unblock_target_state`, and `source_edits_authorized: false`.

## Allowed Flow

`planning -> evidence-prepared -> decision-prepared -> authorization-prepared -> approved-for-implementation -> implementation-ready -> implementation-landed -> closeout-prepared -> closed`

Any active state can move to `blocked` when the blocker is explicit. A blocked node can only return to its `unblock_target_state`.

## Evidence Classes

- Baseline evidence: local file paths, `git status`, `git log`, `git diff`, current `HEAD`.
- Structural evidence: dependency graphs, call graphs, ownership maps, design docs, or other impact analysis when available or required by the project profile.
- Runtime evidence: command output summarized into files or reports.
- Optional anchors: GitHub issue, PR URL, OPENDOG file activity, or external dashboards.

Git is the hard source of truth. Optional anchors cannot drive state alone.

## Command Workflow

### `/ft:init`

Creates `.governance/programs/<program>/`, empty `nodes.json`, a human tree, active gate indexes, and root `FUNCTION_TREE.md`. If `FUNCTION_TREE.md` already exists and content changes, the helper writes a timestamped backup to `.governance/backups/` before updating it. Use:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" init <program> --ref <function-tree-node>
```

The generated root document records detected project context, trigger keywords for future skill use, governance programs, active state files, and a preserved project-notes section.

### `/ft:new-node`

Create a concrete governance node under an initialized program:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" new-node <program> <node-id> \
  --title "<title>" \
  --ref <function-tree-node>
```

This appends to `nodes.json`, updates the human tree, and creates an active gate in `planning`.

### `/ft:observe`

Collect facts. Record evidence and `current_head`. Do not edit source files. If implementation pressure appears, move the node to `blocked` or prepare authorization.

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" observe <program> <node-id> \
  --evidence <path-or-note> \
  --kind baseline \
  --note "<short note>"
```

### `/ft:authorize`

Prepare:

- `allowed_paths`
- `forbidden_paths` when useful
- at least one `non_goal`
- `commit_gate`
- `closeout_gate`

No source edit is allowed until the authorization is approved and the node reaches `approved-for-implementation`.

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" authorize <program> <node-id> \
  --allowed <path> \
  --non-goal "<text>" \
  --commit-gate "<text>" \
  --closeout-gate "<text>"
```

### `/ft:transition`

Move only through legal states:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" transition <program> <node-id> --to approved-for-implementation
```

Implementation approval fails if the latest evidence `current_head` does not match the current Git `HEAD`.

### `/ft:implement`

Before editing, check:

- node status is `approved-for-implementation`
- evidence `current_head` matches current `HEAD`
- requested files match `allowed_paths`
- repo profile gates are satisfied

During editing, run:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" scope-check
```

### `/ft:closeout`

Answer:

- what landed
- what compatibility surface was preserved or intentionally retired
- which gates passed
- whether `FUNCTION_TREE.md` status, evidence, or boundaries need an update
- the next gate, if any

Run:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" closeout <program> <node-id> \
  --summary <path-or-note> \
  --compatibility "<text>" \
  --gate "<passed gate>"
node "$SKILL_DIR/scripts/ft-governance.cjs" validate
```

## Generated Files

`active-gates.json` is machine-owned. `active-gates.md` is generated from JSON. If they diverge, JSON wins and `sync` must regenerate markdown.

## Maintenance Commands

### `/ft:doc`

Refresh root `FUNCTION_TREE.md` from current project context and governance state:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" doc --root <repo>
```

Existing `FUNCTION_TREE.md` content is backed up before changed output is written. Content inside the project-notes marker block is preserved. If an existing document has no marker block yet, its previous body is carried into the new project-notes block as preserved content.

### `/ft:install-guard`

Install a repo-local wrapper for edit hooks:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" install-guard --root <repo>
```

This creates `.governance/guards/ft-scope-check.sh`, marks it executable, and prints a hook snippet. Existing guards are not overwritten unless `--force` is passed.

### `/ft:repair`

Rebuild active gates from program nodes:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" repair --root <repo>
```

This treats `.governance/programs/*/nodes.json` as the source, removes `closed` and `archived` nodes from `active-gates.json`, and regenerates `active-gates.md`.
