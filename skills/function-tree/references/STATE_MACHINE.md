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
- Structural evidence: GitNexus query/context/impact/detect_changes when available or required by repo profile.
- Runtime evidence: command output summarized into files or reports.
- Optional anchors: GitHub issue, PR URL, OPENDOG file activity, or external dashboards.

Git is the hard source of truth. Optional anchors cannot drive state alone.

## Command Workflow

### `/ft:init`

Creates `.governance/programs/<program>/`, empty `nodes.json`, a human tree, and active gate indexes. Use:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" init <program> --ref <function-tree-node>
```

### `/ft:observe`

Collect facts. Record evidence and `current_head`. Do not edit source files. If implementation pressure appears, move the node to `blocked` or prepare authorization.

### `/ft:authorize`

Prepare:

- `allowed_paths`
- `forbidden_paths` when useful
- at least one `non_goal`
- `commit_gate`
- `closeout_gate`

No source edit is allowed until the authorization is approved and the node reaches `approved-for-implementation`.

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
node "$SKILL_DIR/scripts/ft-governance.cjs" validate
node "$SKILL_DIR/scripts/ft-governance.cjs" sync
```

## Generated Files

`active-gates.json` is machine-owned. `active-gates.md` is generated from JSON. If they diverge, JSON wins and `sync` must regenerate markdown.
