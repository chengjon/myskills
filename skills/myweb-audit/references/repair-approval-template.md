# Repair Approval Package Template

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use this template after merged findings are ready and before any repair edit starts.

## Minimal Package Shape

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
dependency: null
shared_impact:
  candidate: false
  basis: null
  related_routes: []
approval_status: pending
```

## Field Notes

- `consolidated_issue_id`: stable merged-issue identifier, not a raw finding id
- `affected_routes`: concrete routes touched by the issue
- `source_roles`: all roles that contributed to the merged issue
- `primary_repair_target`: the single owner that should be edited first
- `page_scope`: use `page-local` or `shared-impact`
- `frontend_fixable`: whether the fix can land in the approved frontend batch
- `repair_bucket`: use `fix-now`, `fix-with-shared-impact-review`, or `defer`
- `changes_truth_sources`: mark whether the proposed repair touches route truth, page config, shared composables, shared components, or generated artifacts
- `dependency`: must be explicit when `frontend_fixable` is `false` or the bucket is `defer`
- `shared_impact.candidate`: pre-repair orchestrator verdict, not only a role hint
- `approval_status`: start at `pending` when presented to the user; update the manifest after user decision

## Usage Notes

- Present approval packages grouped by repair bucket, not by source role.
- Use one package per consolidated issue.
- If multiple routes share the same root cause, keep one package and list all affected routes.
- If the proposed change touches a shared owner, prefer `page_scope: shared-impact` even when only one current page visibly fails.
