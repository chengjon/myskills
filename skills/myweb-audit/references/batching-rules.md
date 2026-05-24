# Batching Rules

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use these rules to split the audit into lightweight, repairable batches.

For long-term governance and stop conditions, read this together with:

- `route-truth-operations.md`
- `route-truth-coverage-matrix.md`
- `route-truth-families.md`

## Batch Size

Default batch size:

- 1 primary defect family per batch
- 1 to 3 tightly related canonical routes by default

Do not create large batches that delay repair and verification.

Expand beyond 3 routes only when the routes clearly share:

- the same owner or shared primitive
- the same active defect family
- the same verification pattern

If a module has more candidate routes than one batch should carry, split it using this order:

1. stable defect family
2. canonical route family
3. shared owner or shared primitive
4. layout or interaction density

Core business modules may remain a standalone batch even when they contain only 1 or 2 pages if they are critical entry points or high-risk workbench surfaces.

## Grouping Priority

Group pages in this order:

1. same stable defect family
2. same shared owner or shared primitive
3. same canonical route family
4. same layout family
5. same component pattern family

Examples:

- `/market/*`
- `/risk/*`
- `/trade/*`
- `/watchlist/*`

Prefer grouping pages that share filters, tables, charts, cards, detail layouts, or selector semantics.
If `route-inventory` identifies a `shared-owner watchlist`, prefer keeping those related pages inside the same batch or in immediately adjacent batches when feasible.

## Special Routes

Special routes must be handled explicitly:

- 404 pages
- redirect-only routes
- compatibility wrappers
- embedded shell routes
- ArtDeco route exceptions declared directly in router

Do not mix these blindly into a normal business-page batch. Mark them as special-case pages and batch them only when they are part of the requested scope.

Default handling:

- process them after canonical business-page batches
- prioritize them earlier only if the user explicitly requests them or they block a core navigation path
- when a special route only wraps a canonical page, audit the canonical page first
- when the special route is a blank-layout shell such as `/login` or `404`, use a lightweight mini batch rather than a full canonical business-page regression stack
- blank-layout mini batches should verify only shell isolation, no stale-route contamination, no snapshot-fallback chrome, targeted type check, and basic smoke

## Priority Rules

Treat these as higher priority when no user preference is given:

1. unresolved or lightly scanned `SEL`, `PART`, `PROV`, or `ENR` cells in the coverage matrix
2. pages reachable from primary navigation
3. pages that serve as canonical entry points for a business domain
4. pages with dense user interaction or high operational risk
5. pages with known inconsistency or recent churn

When priority signals conflict, resolve in this order:

1. blocking or high-severity operational risk
2. unresolved high-risk family coverage in the matrix
3. primary navigation importance
4. canonical-entry importance
5. interaction density
6. recent churn or known inconsistency

## Canonical Page Rules

Before batching, verify the canonical page entry:

- prefer router truth and current active page entry
- do not assume wrapper or compatibility pages are the canonical source
- when in doubt, resolve via router definitions and current frontend structure guidance

## Global Batch Order

Unless the user specifies a different scope, run batches in this order:

1. unresolved high-risk family cells on primary navigation routes
2. core business workbench pages with shared-owner repeatability
3. dense analysis/detail pages with selector or enrichment risk
4. remaining special-case blank-layout routes
5. secondary inventory heuristic backlog after canonical matrix coverage is effectively closed
6. supporting settings and utility pages
7. other special-case routes and compatibility pages

When route truth and ArtDeco page truth diverge, prioritize the canonical routed page first.

## Stop Conditions

Do not open a fresh batch for a route only because it appears in old changelog history.

A route is usually skipped until new drift appears when:

- the relevant family cells in `route-truth-coverage-matrix.md` are already `R` or `S`
- no meaningful code drift has occurred on the route or its shared owner
- the suspected issue is already a known representative case in `route-truth-casebook.md`

Reopen the route when:

- a new stable family is implicated
- a shared owner changed and the matrix row is no longer trustworthy
- runtime verification shows the earlier closure evidence is no longer valid

When the canonical matrix no longer has meaningful `?` cells, stop opening new canonical route batches by default and switch to the generated `secondary-view-inventory.md/json` backlog.

## Batch Naming

Use this naming pattern:

- `batch-id = [module]-batch-[nn]`

Examples:

- `market-batch-01`
- `trade-batch-02`
- `risk-batch-03`

Keep numbering stable within the current audit run.

## Batch Completion Standard

A batch is complete only when:

- all pages in the batch were audited
- findings were merged and deduplicated
- in-scope fixes were applied
- focused regression verification was recorded
- a batch report was produced
- any approved shared-impact item has related-page spot-check coverage recorded or an explicit deferred follow-up

## Defer Rules

Defer an issue instead of forcing a fix when:

- it requires backend contract changes
- it requires product requirement clarification
- it implies architecture-level rework
- it conflicts with current project standards
- it touches unrelated page families outside the current batch

Deferred items must include:

- affected page
- severity
- reason for deferral
- dependency or blocking condition
- recommended next batch or owner

Deferred items should be reintroduced when the blocking dependency is resolved or when the next relevant page family batch begins.
