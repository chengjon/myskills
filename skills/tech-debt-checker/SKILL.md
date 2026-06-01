---
name: tech-debt-checker
description: >
  Measure, track, and gate technical debt across 6 dimensions (code quality, architecture,
  testing, documentation, dependencies, process/security). Supports baseline management,
  drift detection, governance gating, and auto-fix of safe issues. Use when: user mentions
  "tech debt", "technical debt", "code quality", "baseline check", "debt report",
  "quality gate", "skip/xfail count", "type errors", "lint issues", "large files",
  or wants to assess project health. Triggers: "run debt check", "tech debt analysis",
  "baseline drift", "governance gate", "tech debt report", "measure debt", "debt audit".
  Do NOT use for: feature development, bug fixing, refactoring, or security audit.
---

# Tech Debt Checker

> **补充规范说明**: 本文件是技能执行提示。涉及项目治理、审批门禁时，优先遵循项目 `architecture/STANDARDS.md`、`DEVELOPMENT_RULES.md`、`AGENTS.md` 或同等本地治理文件。

## Overview

Use this skill as a reproducible measurement protocol, not just a report-writing checklist. Measure current state into machine-readable JSON first, compare that JSON to any approved baseline, compute gate/rating results from deterministic rules, then render Markdown from those artifacts.

Markdown is a presentation layer. The JSON measurement artifact and approved baseline are the sources of truth.

## 6-Dimension Taxonomy

| Dim | Name | Focus | Cadence |
|-----|------|-------|---------|
| D1 | Code Quality | Type errors, lint, suppressions, complexity, large files | per-diff |
| D2 | Architecture | Coupling, circular deps, god classes, abstraction gaps | per-release |
| D3 | Testing | Failing tests, coverage, skip/xfail, placeholder asserts, test smells | per-diff |
| D4 | Documentation | API docs, README freshness, ADR coverage | per-release |
| D5 | Dependencies | Outdated/vulnerable deps, build time, config drift | per-release |
| D6 | Process/Security | SAST issues, secrets, governance gate pass rate, debt exceptions | per-diff |

## When to Use

- User asks to check, measure, analyze, baseline, gate, or report tech debt or code quality.
- User mentions baseline drift, quality gate, skip/xfail count, type errors, lint issues, large files, coverage, dependency risk, or release health.
- Before releases, major PRs, weekly/monthly debt reviews, or after significant refactoring to verify improvement.

## Do Not Use

- Feature development or bug fixing.
- Security penetration testing; use a security-specific workflow.
- Performance profiling; use benchmark/profiler tools.
- As a substitute for code review.

## Modes

| Mode | Purpose | Writes |
|------|---------|--------|
| `analyze` | Measure current state and, if a baseline exists, compare against it | measurement/report artifacts only |
| `init-baseline` | Create the first approved baseline from current measurements | baseline file only after explicit approval |
| `drift` | Compare current measurements against an existing baseline | drift/report artifacts only |
| `gate` | Compute PASS/WARN/FAIL from current measurements and baseline/gate rules | gate artifact only |
| `report` | Render Markdown from existing measurement/gate JSON | report file only |
| `fix` | Auto-fix safe lint/formatting issues | code files, lint-only |

Default mode: `analyze`.

State rules:

- If a baseline exists, every non-`init-baseline` report MUST compare against it. Do not write "no baseline" or "create baseline" language.
- If no baseline exists, write "baseline candidate" language and propose baseline creation. Do not invent drift.
- Updating or replacing a baseline requires explicit user approval. Never auto-update it.
- `report` mode must render from measurement/gate JSON; it must not manually re-interpret raw command output.
- `fix` mode may only apply formatter/linter safe fixes. Do not refactor or change behavior.

## Output Contract

Generate artifacts in this order:

1. Current measurements JSON: `reports/analysis/tech-debt-measurements-YYYY-MM-DD.json`
2. Gate/drift JSON when applicable: `reports/analysis/tech-debt-gate-YYYY-MM-DD.json`
3. Markdown report: `reports/analysis/tech-debt-report-YYYY-MM-DD.md`
4. Baseline JSON only in `init-baseline` mode and only after approval: `reports/analysis/tech-debt-baseline.json`

Each metric in JSON MUST be an object with these fields:

| Field | Required | Meaning |
|-------|----------|---------|
| `id` | yes | Stable metric key, scoped by area where needed, for example `backend_type_errors` |
| `dimension` | yes | `D1` through `D6` |
| `scope` | yes | Project area such as `backend`, `frontend`, `repo`, or a package name |
| `kind` | yes | `Measured`, `Inferred`, or `Historical Baseline` |
| `value` | yes | Numeric, boolean, string, array, or object value |
| `unit` | yes | `count`, `percent`, `status`, `files`, etc. |
| `tool` | yes | Tool or script that produced the value |
| `command_id` | yes | Stable ID for the reproducibility command |
| `source_roots` | yes | Paths included in the measurement |
| `extensions` | when file-based | Extensions included, for example `.ts`, `.tsx`, `.vue` |
| `excludes` | yes | Excluded paths/globs |
| `measured_at` | yes | ISO timestamp |
| `git_sha` | yes | Commit measured |
| `dirty_worktree` | yes | Whether uncommitted changes affected measurement |
| `gate` | yes | `hard`, `soft`, or `none` |
| `target` | when gated | Desired threshold, for example `0` |
| `baseline_value` | when baseline exists | Approved baseline value |
| `drift` | when baseline exists | Numeric or structured delta |
| `status` | yes | `pass`, `warn`, `fail`, `unavailable`, or `not_applicable` |

Rules:

- Split backend/frontend/repo metrics. Do not store backend measurements under frontend keys.
- File counts MUST declare roots, extensions, excludes, and line-count method.
- Test pass rate and code coverage are different metrics. Never describe pass rate as coverage.
- Historical baseline values must not be described as current state.
- Every Markdown metric claim must be traceable to a JSON metric ID.

## Core Measurements

Run all independent measurements in parallel where safe. Use existing project tooling first; wrap it rather than replacing it.

Required checks:

- D1.1: Type errors per scope (`tsc --noEmit`, `vue-tsc --noEmit`, `mypy`, etc.).
- D1.2: Lint errors and warnings with severity breakdown.
- D1.3: Type suppressions and debt suppressions.
- D1.4: Large files by explicit roots/extensions/line limit.
- D3.1: Test totals, passed, failed, pending/skipped/todo/xfail counts.
- D3.2: Placeholder assertions or no-op tests.
- D3.3: Coverage percentage when tooling exists.
- D5.1: Outdated dependencies.
- D5.2: Vulnerable dependencies.
- D6.1: Secrets and SAST findings when tooling exists.
- D6.2: Debt exception inventory and expiry state.

Extended checks:

- D2.1: Circular dependency detection.
- D2.2: God class/file candidates.
- D4.1: API or operator documentation coverage.
- D4.2: ADR/governance documentation presence and freshness.

See [references/measurement-commands.md](references/measurement-commands.md) for command patterns.

## Baseline, Drift, And Gate

If baseline exists:

- Compare every current metric with its matching baseline metric ID.
- Classify each metric as improved, unchanged, regressed, new, removed, unavailable, or not_applicable.
- Missing gated current metrics are gate failures unless the report explicitly marks the metric not_applicable with evidence.
- Produce drift percentages for numeric metrics where meaningful.

If no baseline exists:

- Generate current measurements and a baseline candidate.
- Recommend hard/soft/observed gates.
- Do not claim PASS/WARN/FAIL against a missing baseline unless using absolute hard targets such as secrets = 0.

Default hard gates:

| Metric Pattern | Target |
|----------------|--------|
| `*_type_errors` | `0` |
| `*_lint_errors` | `0` unless project governance says otherwise |
| `test_failed` | `0` |
| `secrets_in_code` | `0` |
| `critical_cve_count` / `high_cve_count` | `0` |
| `debt_exception_expired` | `0` |
| `debt_exception_missing_owner` | `0` |
| `debt_exception_missing_ttl` | `0` |
| gated suppressions and skip/xfail counts | must not exceed approved baseline |

Default soft/observed metrics:

- Lint warnings.
- Large file counts.
- TODO/FIXME/HACK/XXX marker counts.
- Outdated dependencies without known CVEs.
- Coverage percentage.
- Documentation completeness.

Gate status:

- `PASS`: all hard gates pass and no critical findings exist.
- `WARN`: hard gates pass, but soft/observed metrics regressed or ratings declined.
- `FAIL`: any hard gate fails, required gated metric is unavailable, secrets are found, critical/high CVEs exist, expired/malformed exceptions exist, or `test_failed > 0`.

## Deterministic Ratings

Use these rules before applying dimension-specific nuance:

- `E`: any hard gate fails in the dimension, secrets are found, critical/high CVEs exist, expired exceptions exist, or tests fail in D3.
- `D`: no hard gate failure, but release-critical observed metrics regressed or debt is far above target.
- `C`: debt is high but stable and documented.
- `B`: minor observed debt, no hard gate failure, no important regression.
- `A`: all hard gates pass, observed debt is below target, and no expired exceptions exist.

Do not rate D3 as A/B when `test_failed > 0`. Do not rate D5 as A/B when critical/high CVEs exist. Do not rate D6 as A/B when secrets or expired exceptions exist.

## Reporting

Generate the Markdown report from [references/report-template.md](references/report-template.md). It must include:

- Mode and baseline state.
- Overall gate status with hard/soft gate counts.
- Per-dimension ratings and the metric IDs behind them.
- Current vs baseline drift when a baseline exists.
- Hot files or hot packages, with measurement scope.
- Exception inventory.
- Reproducibility appendix listing command IDs, not ad-hoc shell fragments.
- Prioritized remediation plan.

Report language constraints:

- If baseline exists, never say "no baseline" or "create baseline" unless recommending a separate replacement baseline after approval.
- Use `Measured`, `Inferred`, and `Historical Baseline` labels for metric claims when project governance requires metric-source separation.
- Do not call a metric "coverage" unless it is code coverage, not pass rate.

## Artifact Self-Check

Before finishing, run a self-check over generated artifacts. The work is incomplete if any check fails:

- Every Markdown metric claim maps to a JSON metric ID.
- Every gated metric exists in the measurement JSON and has a current value or justified `not_applicable` status.
- If baseline exists, report contains drift status and does not contain stale "no baseline" or "create baseline" language.
- If `test_failed > 0`, overall gate is `FAIL` or the report explicitly states it is a failing historical baseline candidate.
- If coverage is mentioned, it comes from a coverage metric, not pass rate.
- Large-file counts include declared roots, extensions, excludes, and line-count method.
- Backend and frontend metrics are not stored under the wrong scope.
- Debt exception totals and expired/malformed counts are present.
- Measurement commands include git SHA, dirty status, tool versions, command IDs, and exit/unavailable states.

## Exception Handling

When debt exceptions exist:

- Parse annotations such as `// @ts-expect-error [debt-exception] owner=X ttl=YYYY-MM-DD reason="..."`.
- Validate owner, TTL, reason, issue/remediation fields when required by project policy.
- Count total, expired, expiring soon, missing owner, missing TTL, and malformed exceptions.
- Treat expired or malformed exceptions as hard gate failures.
- Include exception inventory in measurement JSON and report.

See [references/exception-template.md](references/exception-template.md).

## Project Configuration Discovery

Auto-detect from project files:

- Governance: `AGENTS.md`, `CLAUDE.md`, `DEVELOPMENT_RULES.md`, `docs/standards/*governance*.md`, `docs/standards/*charter*.md`.
- Python: `pyproject.toml`, `ruff.toml`, `mypy.ini`.
- TypeScript: `tsconfig.json`, `vite.config.*`, `.eslintrc*`, `eslint.config.*`, `package.json`.
- Tests: `pytest.ini`, `vitest.config.*`, `jest.config.*`, coverage config.
- Baseline: configurable path, default `reports/analysis/tech-debt-baseline.json`.
- Existing debt tooling: `scripts/run_tech_debt_weekly_report.sh`, `scripts/dev/quality_gate/`, or project-specific report scripts.

## Failure Handling

- Measurement command fails: mark that metric `unavailable`, capture exit status and reason, continue unrelated metrics.
- Required hard-gate metric is unavailable: gate `FAIL` unless project policy explicitly marks it not_applicable.
- Baseline file missing: run current measurement only and produce a baseline candidate.
- Baseline schema mismatch: do not silently compare. Report schema mismatch and recommend migration.
- Governance charter missing: use default gate rules from [references/gate-rules.md](references/gate-rules.md).
- No test framework detected: mark D3 not_applicable with evidence; do not invent passing test state.

## Execution Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| Measurement JSON | `reports/analysis/tech-debt-measurements-YYYY-MM-DD.json` | Current measured state |
| Gate JSON | `reports/analysis/tech-debt-gate-YYYY-MM-DD.json` | Computed gate/drift result |
| Tech debt report | `reports/analysis/tech-debt-report-YYYY-MM-DD.md` | Human-readable report |
| Baseline file | `reports/analysis/tech-debt-baseline.json` | Approved freeze point |
| Baseline candidate | `reports/analysis/tech-debt-baseline-candidate-YYYY-MM-DD.json` | Proposed baseline awaiting approval |

## Reference Order

1. Project governance charter or agent instructions.
2. Project baseline JSON.
3. Project measurement/gate scripts.
4. This skill's `references/` directory.
5. General SQALE/SonarQube-style best practices.
