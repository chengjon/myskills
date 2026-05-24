# MyWeb Audit Artifact Quick Reference

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use this page when you need the shortest possible reminder for `myweb-audit` artifact flow and validation commands.

For batch-selection policy, stop conditions, and version-throttling rules, pair this file with `route-truth-operations.md`.

## Lifecycle

1. Create batch manifest.
2. Run `route-inventory` and copy canonical scope truth into the manifest.
3. Write raw findings.
4. Merge findings.
5. Package merged findings for repair approval.
6. Write page reports.
7. Write batch report.
8. Write closeout.

## Core Contracts

- Manifest template: `references/manifest-template.md`
- Manifest schema: `references/manifest-schema.json`
- Raw findings example: `references/findings-schema-example.md`
- Raw findings schema: `references/findings-schema.json`
- Merged findings schema: `references/merged-findings-schema.json`
- Repair approval template: `references/repair-approval-template.md`
- Report templates: `references/report-template.md`
- Closeout checklist: `references/closeout-checklist.md`

## Common Commands

Single artifact validation:

```bash
node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema manifest --file <manifest-path>
node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema findings --file <raw-findings-path>
node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --schema merged --file <merged-findings-path>
```

Aggregate validation:

```bash
node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --all \
  --manifest <manifest-path> \
  --findings <raw-findings-path> \
  --merged <merged-findings-path>

node scripts/dev/tools/validate-myweb-audit-artifacts.mjs --all \
  --run-id <audit-run-id> \
  --batch-id <batch-id>

node scripts/dev/tools/validate-myweb-audit-artifacts.mjs \
  --from-manifest <manifest-path>
```

NPM shortcuts:

```bash
npm run validate:myweb-audit:manifest -- --file <manifest-path>
npm run validate:myweb-audit:findings -- --file <raw-findings-path>
npm run validate:myweb-audit:merged -- --file <merged-findings-path>
npm run validate:myweb-audit:approval -- --file <approval-path>
npm run validate:myweb-audit:all -- \
  --manifest <manifest-path> \
  --findings <raw-findings-path> \
  --merged <merged-findings-path>

npm run validate:myweb-audit:all -- \
  --run-id <audit-run-id> \
  --batch-id <batch-id>

npm run validate:myweb-audit:from-manifest -- \
  <manifest-path>
```

Skill-structure self-check:

```bash
npm run test:myweb-audit:skill
```

## Current Best Practice

- Let `route-inventory` establish canonical entry truth and shared-owner watchlist before the finding-producing roles start.
- Validate manifest before repair approval moves out of `pending`.
- Validate raw findings before deduplication is treated as final.
- Validate merged findings before batch report and closeout are marked complete.
- Present repair approval as merged packages with one primary owner, not as unmerged per-role finding lists.
- In dirty worktrees, keep GitNexus verdict provenance explicit:
  - `isolated-batch-only`
  - `mixed-staged-observation`
