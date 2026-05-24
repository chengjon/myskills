# Artifact Conventions

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use these conventions when an audit run writes files instead of responding inline.

## Default Output Root

Unless the user explicitly requests another location, use:

`docs/reports/quality/myweb-audit/[audit-run-id]/`

Example:

`docs/reports/quality/myweb-audit/audit-20260425-01/`

## Recommended Layout

```text
docs/reports/quality/myweb-audit/[audit-run-id]/
├── manifests/
│   └── [batch-id]-manifest.yaml
├── approvals/
│   └── [batch-id]-repair-approval.yaml
├── pages/
│   ├── [module]-[route-key]-audit.md
│   └── ...
├── batches/
│   └── [module]-batch-[nn]-audit.md
├── findings/
│   ├── [batch-id]-raw-findings.yaml
│   └── [batch-id]-merged-findings.yaml
└── closeout/
    └── [audit-run-id]-closeout.md
```

## File Format Guidance

- manifest: YAML
- manifest machine contract: `manifest-schema.json`
- raw findings: YAML or JSON matching `findings-schema.json`
- merged findings machine contract: `merged-findings-schema.json`
- merged findings: YAML or JSON matching the consolidated structure described in `findings-schema-example.md`
- repair approval packages: YAML or JSON matching `repair-approval-template.md`
- page and batch reports: Markdown
- closeout checklist result: Markdown

## Write Order

When files are emitted, write them in this order:

1. manifest
2. raw findings
3. merged findings
4. repair approval package
5. page reports
6. batch report
7. closeout checklist result

Validation helper:

- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema manifest --file <manifest-path>`
- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema findings --file <raw-findings-path>`
- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema merged --file <merged-findings-path>`
- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema approval --file <approval-path>`
- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --all --manifest <manifest-path> --findings <raw-findings-path> --merged <merged-findings-path>`
- `node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --from-manifest <manifest-path>`

Preferred operator path:

- once `artifacts.raw_findings` and `artifacts.merged_findings` are filled in the manifest, prefer `--from-manifest` so the manifest remains the single batch-truth entrypoint
- use `--all --run-id <audit-run-id> --batch-id <batch-id>` only when the run follows the default artifact layout and the manifest path is not already in hand

## Resumability Notes

- This layout is intended to make partial runs easy to inspect manually.
- Cross-session recovery is supported at a lightweight level when the manifest keeps `state_tracking`, `artifacts`, and `resume` fields current.
- This is manual or agent-assisted resumability, not a promise of fully automated workflow replay.
- If closeout depends on GitNexus staged detection, record whether the verdict came from `isolated-batch-only` scope or only a `mixed-staged-observation`.
- If a run stays inline only, no files are required.
