# Example Audit Run

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use this reference when you want a concrete execution pattern instead of only abstract rules.

## Quick Mode Example

Request shape:

`Check /market/overview for obvious interaction and layout issues. Do not write files.`

Recommended execution:

1. Resolve canonical entry from router truth.
2. Use `live-audit` if the frontend is reachable and browser tooling is available.
3. Run the audit dimensions inline:
   - functional
   - data/state
   - visual/ArtDeco
   - responsive/a11y
4. Consolidate findings inline.
5. Package merged findings into repair decisions:
   - `fix-now`
   - `fix-with-shared-impact-review`
   - `defer`
6. Ask the user which findings to repair before editing.
7. If the user only wants a check, stop after reporting.

Expected output shape:

```md
# Quick Audit: /market/overview

## Canonical Entry
- web/frontend/src/views/market/MarketOverview.vue

## Findings
- [High] Filter reset leaves stale rows visible after controls clear.
- [Medium] Table toolbar spacing collapses at 1280 width.
- [Low] Empty state copy is technically correct but visually weak.

## Shared Impact
- Candidate: yes
- Basis: shared filter composable
- Primary owner: `web/frontend/src/composables/useMarketFilters.ts`
- Related pages to spot-check: /market/watchlist

## Recommendation
- Fix now: stale reset behavior
- Fix with shared-impact review: shared filter composable alignment
- Defer: visual empty-state polish

## Verification Surface
- live-audit
```

Quick Mode defaults:

- no manifest file
- no batch report
- no closeout checklist
- inline-only unless the user asks for files

## Full Mode Example

Request shape:

`Audit the market pages in batches and repair approved frontend issues. Write files.`

Sample batch:

- batch id: `market-batch-01`
- pages:
  - `/market/overview`
  - `/market/watchlist`
  - `/market/heatmap`

Recommended execution:

1. Create manifest:
   - `docs/reports/quality/myweb-audit/audit-20260425-01/manifests/market-batch-01-manifest.yaml`
   - validate against `references/manifest-schema.json` if the run needs machine-checked artifacts
   - example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema manifest --file docs/reports/quality/myweb-audit/audit-20260425-01/manifests/market-batch-01-manifest.yaml`
2. Run `route-inventory`.
3. Run the 4 audit roles in parallel when capacity allows.
4. Write raw findings:
   - `findings/market-batch-01-raw-findings.yaml`
   - validate raw findings against `references/findings-schema.json` if structured consumption is required
   - example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema findings --file docs/reports/quality/myweb-audit/audit-20260425-01/findings/market-batch-01-raw-findings.yaml`
5. Merge and deduplicate:
   - `findings/market-batch-01-merged-findings.yaml`
   - validate merged findings against `references/merged-findings-schema.json` if structured consumption is required
   - example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema merged --file docs/reports/quality/myweb-audit/audit-20260425-01/findings/market-batch-01-merged-findings.yaml`
   - aggregate example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --all --manifest docs/reports/quality/myweb-audit/audit-20260425-01/manifests/market-batch-01-manifest.yaml --findings docs/reports/quality/myweb-audit/audit-20260425-01/findings/market-batch-01-raw-findings.yaml --merged docs/reports/quality/myweb-audit/audit-20260425-01/findings/market-batch-01-merged-findings.yaml`
   - auto-resolve example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --all --run-id audit-20260425-01 --batch-id market-batch-01`
   - manifest-truth example: `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --from-manifest docs/reports/quality/myweb-audit/audit-20260425-01/manifests/market-batch-01-manifest.yaml`
6. Select one `primary_owner` for each merged finding and mark shared-impact candidates.
7. Set manifest `repair_approval.status: pending`.
8. Present merged findings to the user as repair packages.
   - optional formal artifact: `approvals/market-batch-01-repair-approval.yaml`
9. Update manifest `repair_approval`.
10. Apply only approved fixes.
11. Run focused verification.
12. Update manifest `resume` and `state_tracking`.
13. Write per-page report(s), batch report, and closeout.

## Route-Inventory To Manifest Example

Use this handoff when `route-inventory` completes before the four finding-producing roles start.

Example scope handoff:

```yaml
scope:
  requested_by: user
  pages:
    - route: /data/fund-flow
      page_key: data-fund-flow
      route_class: canonical-page
      canonical_entry: web/frontend/src/views/data/FundFlowPage.vue
    - route: /data/indicator
      page_key: data-indicator
      route_class: canonical-page
      canonical_entry: web/frontend/src/views/data/DataIndicatorPage.vue
  compatibility_redirects: []
state_tracking:
  shared_impact:
    candidates:
      - owner: web/frontend/src/views/artdeco-pages/components/AnalysisIndicators.vue
        basis: shared indicator-card interaction surface
      - owner: web/frontend/src/views/artdeco-pages/market-data-tabs/useFundFlowPageData.ts
        basis: shared data-state owner for fund-flow rendering
resume:
  last_completed_step: route-inventory
  next_action: run-audit-roles
  notes:
    - downstream roles should treat DataIndicatorPage.vue as canonical page truth for /data/indicator
```

Recommended artifact set:

```text
docs/reports/quality/myweb-audit/audit-20260425-01/
├── manifests/
│   └── market-batch-01-manifest.yaml
├── findings/
│   ├── market-batch-01-raw-findings.yaml
│   └── market-batch-01-merged-findings.yaml
├── approvals/
│   └── market-batch-01-repair-approval.yaml
├── pages/
│   ├── market-market-overview-audit.md
│   ├── market-market-watchlist-audit.md
│   └── market-market-heatmap-audit.md
├── batches/
│   └── market-batch-01-audit.md
└── closeout/
    └── audit-20260425-01-closeout.md
```

## Full Mode Approval Example

Example approval summary to record in the manifest:

```yaml
repair_approval:
  status: partial
  approved_findings:
    - market-overview-functional-001
    - market-watchlist-data-state-002
  deferred_findings:
    - market-heatmap-visual-001
resume:
  last_completed_step: repair-approval
  next_action: apply-approved-fixes
  notes:
    - shared filter composable requires cross-page spot-check after fix
```

Example merged-finding package to present before editing:

```yaml
consolidated_issue_id: data-indicator-issue-01
severity: High
affected_routes:
  - /data/indicator
source_roles:
  - functional-audit
  - data-state-audit
primary_repair_target: web/frontend/src/views/data/DataIndicatorPage.vue
page_scope: page-local
frontend_fixable: true
repair_bucket: fix-now
changes_truth_sources:
  route_truth: false
  page_config: false
  shared_composable: false
  shared_component: false
  generated_artifact: false
summary: Selected indicator context does not propagate into downstream result behavior.
```

## Code-Review-Only Example

Use this fallback when the app or browser surface is unavailable.

Expected differences:

- set manifest `execution_surface: code-review-only`
- set `verification_strategy: code-review-only`
- mark each finding `verification_surface: code-review-only`
- keep verification notes explicit about the missing live surface

Example finding note:

```yaml
verification_surface: code-review-only
verification:
  required: true
  complete: false
  notes: Browser automation unavailable; interaction behavior inferred from component code only.
```

## Dirty Worktree Closeout Example

Use this rule when verification reaches the GitNexus closeout step and unrelated files are already staged.

Preferred path:

1. Temporarily isolate the current batch files in the staged set.
2. Run staged detection.
3. Record the isolated result in the manifest.
4. Restore the prior staging state.

Manifest example:

```yaml
state_tracking:
  validation_status:
    gitnexus_staged_detect: passed-low-risk
  staged_scope:
    mode: isolated-target-files
    files:
      - web/frontend/src/views/data/Advanced.vue
      - web/frontend/src/views/artdeco-pages/components/AnalysisIndicators.vue
    verdict_origin: isolated-batch-only
    notes:
      - original staged set was restored after isolated verification
```

Fallback path when isolation is not safe:

```yaml
state_tracking:
  validation_status:
    gitnexus_staged_detect: observation-only-mixed-staged
  staged_scope:
    mode: mixed-staged-observation-only
    files: []
    verdict_origin: mixed-staged-observation
    notes:
      - unrelated user-staged files were present
      - mixed staged detect was not treated as the current batch verdict
```

## Practical Guidance

- Quick Mode is for fast inspection and decision support.
- Full Mode is for resumable, repair-oriented audit work.
- Do not create file artifacts unless the user asked for files or the audit needs resumable structure.
- In Full Mode, approval should be framed around merged repair packages, not raw per-role findings.
- In dirty worktrees, isolate staged scope before citing GitNexus risk as a batch verdict; otherwise downgrade it to observation only.
