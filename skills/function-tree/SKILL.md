---
name: function-tree
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
4. If the repository defines project-local governance instructions, such as `.governance/profile.md` or agent rules, load them before authorization or implementation gates.

## Commands

| User command | Helper command | Purpose |
|--------------|----------------|---------|
| `/ft:init <program> --ref <node>` | `init <program> --ref <node>` | Create `.governance/programs/<program>/` and active gate files |
| `/ft:new-node <program> <node-id>` | `new-node <program> <node-id> --title <text> --ref <node>` | Add a planning node and active gate |
| `/ft:observe <program> <node-id> --evidence <path-or-note>` | `observe <program> <node-id> --evidence <path-or-note>` | Record evidence with current `HEAD`; source edits stay unauthorized |
| `/ft:authorize <program> <node-id>` | `authorize <program> <node-id> --allowed ... --non-goal ...` | Generate task card, scope, non-goals, and acceptance gates |
| `/ft:transition <program> <node-id> --to <status>` | `transition <program> <node-id> --to <status>` | Move through legal states and block stale implementation approval |
| `/ft:implement <program> <node-id>` | `scope-check` | Confirm edits remain inside active authorization |
| `/ft:closeout <program> <node-id>` | `closeout <program> <node-id> --summary <path-or-note>` | Record landed summary, compatibility, and passed gates |
| `/ft:gate [--verbose]` | `gate [--verbose]` | Show active blockers and next allowed action |
| `/ft:status` | `status` | Summarize governance programs and active gates |
| `/ft:install-guard` | `install-guard [--force]` | Install `.governance/guards/ft-scope-check.sh` and print hook snippet |
| `/ft:repair` | `repair` | Rebuild active gates from program nodes and drop closed/archived gates |

## Hard Rules

- Do not edit source code from `evidence-prepared`, `decision-prepared`, or `authorization-prepared`.
- Do not skip evidence collection before authorization.
- Do not use a GitHub issue or PR as the state-machine source of truth. Git commit, branch, and diff evidence are the hard source.
- Do not hand-edit generated active gate markdown; update JSON and run `sync`.
- If evidence `current_head` differs from `HEAD`, mark the node stale before implementation.
- Project-specific impact, build, test, or compliance gates must be captured as explicit commit or closeout gates before implementation.

## Files

The helper creates and validates:

- `.governance/active-gates.json`
- `.governance/active-gates.md`
- `.governance/programs/<program>/tree.md`
- `.governance/programs/<program>/nodes.json`
- `.governance/programs/<program>/cards/*.yaml`

## References

- `references/STATE_MACHINE.md` - statuses, transitions, evidence classes, and command workflow.
- `templates/` - deterministic starter files used by the helper.

Project-specific profiles belong in the consuming repository, not in this public skill.
