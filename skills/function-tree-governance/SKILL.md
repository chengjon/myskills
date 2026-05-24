---
name: function-tree-governance
description: Use when governing FUNCTION_TREE-linked work with /ft commands, evidence collection, authorization gates, scope guards, active implementation gates, or FUNCTION_TREE closeout.
---

# Function Tree Governance

Use this skill to keep FUNCTION_TREE work serialized, evidence-backed, and scoped. The skill governs work; it does not itself authorize source edits.

Trigger on `/ft`, `FUNCTION_TREE governance`, `function tree gate`, scope authorization, evidence collection, active gates, or FUNCTION_TREE closeout requests.

## Quick Start

1. Resolve the repository root.
2. Run the deterministic helper for state files and guards:

```bash
node "$SKILL_DIR/scripts/ft-governance.cjs" <command> [args]
```

3. Read `references/STATE_MACHINE.md` for transition rules before moving a node.
4. If the repo is `quantix-rust`, read `references/QUANTIX_PROFILE.md` before any implementation gate.

## Commands

| User command | Helper command | Purpose |
|--------------|----------------|---------|
| `/ft:init <program> --ref <node>` | `init <program> --ref <node>` | Create `.governance/programs/<program>/` and active gate files |
| `/ft:observe <node-id> --evidence <path-or-note>` | `validate` then update node evidence | Record facts only; source edits stay unauthorized |
| `/ft:authorize <node-id>` | `validate` then prepare task-card | Create allowed paths, non-goals, and gate criteria |
| `/ft:implement <node-id>` | `scope-check` | Confirm edits remain inside authorization |
| `/ft:closeout <node-id>` | `validate` and `sync` | Close landed work and refresh active gates |
| `/ft:gate [--verbose]` | `gate [--verbose]` | Show active blockers and next allowed action |
| `/ft:status` | `status` | Summarize governance programs and active gates |

## Hard Rules

- Do not edit source code from `evidence-prepared`, `decision-prepared`, or `authorization-prepared`.
- Do not skip evidence collection before authorization.
- Do not use a GitHub issue or PR as the state-machine source of truth. Git commit, branch, and diff evidence are the hard source.
- Do not hand-edit generated active gate markdown; update JSON and run `sync`.
- If evidence `current_head` differs from `HEAD`, mark the node stale before implementation.
- In `quantix-rust`, GitNexus impact and detect_changes gates are mandatory where `QUANTIX_PROFILE.md` says so.

## Files

The helper creates and validates:

- `.governance/active-gates.json`
- `.governance/active-gates.md`
- `.governance/programs/<program>/tree.md`
- `.governance/programs/<program>/nodes.json`
- `.governance/programs/<program>/cards/*.yaml`

## References

- `references/STATE_MACHINE.md` - statuses, transitions, evidence classes, and command workflow.
- `references/QUANTIX_PROFILE.md` - repo-specific rules for `quantix-rust`.
- `templates/` - deterministic starter files used by the helper.
