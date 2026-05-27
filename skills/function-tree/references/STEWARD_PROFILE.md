# Steward Profile

The steward profile is an optional function-tree contract layer. It keeps the normal
`status` state machine intact while adding a derived relationship index across
governance tools, evidence, delivery review, memory, and implementation truth.

## Responsibility Boundaries

| System | Primary responsibility | Steward relationship |
|---|---|---|
| context-mode | Searchable command output, counts, and analysis without flooding context | Record concise evidence pointers only; never treat it as durable repo truth |
| GitNexus | Code graph, symbol context, impact analysis, and staged blast-radius checks | Record risk result and next gate before source edits |
| GitHub PR / issue | Delivery review, merge decision, labels, discussion, and branch state | Record PR or issue state and next action; do not approve or merge |
| Graphiti | Cross-session memory digest of accepted decisions and milestones | Record what should be remembered after accepted repo/GitHub artifacts exist |
| OpenSpec | Proposal, capability delta, task checklist, approval, and archive authority | Route architecture changes through OpenSpec and record approval/archive state |
| Reports | Human-readable evidence, verification, closeout, and review notes | Index reports and distinguish accepted fact from review input |
| Source / tests / runtime probes | Actual implementation truth | Defer to current verification when report snapshots are stale |

## Node Fields

Steward fields are additive. Existing nodes keep `status`, `allowed_paths`,
`forbidden_paths`, `non_goals`, `current_head`, and `next_gate`.

Optional steward fields:

- `node_type`: `evidence`, `decision`, `authorization`, `implementation`, `closeout`, or `external`
- `owner_lane`: lane responsible for the next action
- `parent`: parent node id
- `freshness`: freshness policy, such as `current-head`, `commit-scoped`, or `external`

`steward-sync` derives:

- `.governance/steward/steward-index.json`
- `.governance/steward/current-next-gates.md`
- `.governance/steward/evidence-index.md`
- `.governance/steward/tracks/*.md`

## Quality Rules

- Every implementation lane must have a prior authorization node.
- Every source lane must record impact evidence before edits and staged change evidence before commit.
- Every generated artifact reference must have a freshness policy.
- External review input stays review input until accepted by the owning system.
- Broad architecture work must be split into lane-sized decisions before source implementation begins.
