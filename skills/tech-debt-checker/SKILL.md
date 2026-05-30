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

> **补充规范说明**: 本文件是技能执行提示。涉及项目治理、审批门禁时，优先遵循项目 `architecture/STANDARDS.md`。

## Overview

Systematic tech debt measurement, tracking, and gating skill based on SQALE/SonarQube methodology. Measures debt across 6 dimensions, compares against baseline, runs governance gates, and generates actionable reports with prioritized remediation plans.

## 6-Dimension Taxonomy

| Dim | Name | Focus | Cadence |
|-----|------|-------|---------|
| D1 | Code Quality | Type errors, lint, suppressions, complexity, large files | per-diff |
| D2 | Architecture | Coupling, circular deps, god classes, abstraction gaps | per-release |
| D3 | Testing | Coverage, skip/xfail, placeholder asserts, test smells | per-diff |
| D4 | Documentation | API docs, README freshness, ADR coverage | per-release |
| D5 | Dependencies | Outdated/vulnerable deps, build time, config drift | per-release |
| D6 | Process/Security | SAST issues, secrets, governance gate pass rate | per-diff |

## When to Use

- User asks to check/measure/analyze tech debt or code quality
- User mentions baseline, drift, quality gate, debt report
- Before releases or major PRs for debt assessment
- Weekly/monthly debt review cycles
- After significant refactoring to verify improvement

## Do Not Use

- Feature development or bug fixing
- Security penetration testing (use security-specific tools)
- Performance profiling (use benchmark tools)
- As a substitute for code review

## Modes

| Mode | Purpose | Mutates Code |
|------|---------|-------------|
| `analyze` | Measure current state, compare against baseline | No |
| `baseline` | Create/update/freeze baseline metrics | Baseline file only |
| `drift` | Generate drift report vs baseline | No |
| `gate` | Run governance gate (pass/fail) | No |
| `report` | Generate full markdown report | Report file only |
| `fix` | Auto-fix safe lint/formatting issues | Yes (lint only) |

Default mode: `analyze`

## Operating Rules

1. **Detect project context first** — baseline, governance charter, existing tooling
2. **Never modify code in analyze/drift/gate/report modes** — measurement only
3. **Fix mode only touches lint-formatting issues** — never refactor or change logic
4. **Baseline changes require explicit user approval** — never auto-update
5. **Gate failures are informational** — report, don't block (unless CI)
6. **Use existing project tooling when available** — wrap, don't reimplement
7. **Distinguish clearly**: new regression vs pre-existing debt vs measurement artifact
8. **Run all measurements in parallel** — independent dimensions never sequential

## Workflow

### Step 1: Environment Detection

Detect project type, existing tooling, baseline location:
- Baseline: `reports/analysis/tech-debt-baseline.json` (or project-configured path)
- Governance: `docs/standards/*governance*.md` or `docs/standards/*charter*.md`
- Gate scripts: `scripts/dev/quality_gate/` or `scripts/run_*_report.sh`
- Language stack: Python (ruff/mypy/black), TypeScript (vue-tsc/tsc/eslint), etc.
- Test framework: pytest, vitest, jest, etc.
- Config: pyproject.toml, tsconfig.json, package.json

### Step 2: Dimension Measurement (All Parallel)

Execute all applicable dimension measurements in parallel. See [references/measurement-commands.md](references/measurement-commands.md) for per-language commands.

**Core checks (always run)**:
- D1.1: Static type errors (vue-tsc / mypy / tsc --noEmit)
- D1.2: Lint issues (ruff / eslint)
- D1.3: Type suppressions (@ts-ignore, # type: ignore)
- D1.4: Large files (exceeding project line limits)
- D3.1: Test skip/xfail count
- D3.2: Placeholder assertions in tests

**Extended checks (when tooling available)**:
- D2.1: Circular dependency detection (madge / pydeps)
- D4.1: API documentation coverage
- D5.1: Outdated dependencies (npm audit / pip audit / cargo audit)
- D5.2: Vulnerable dependencies (CVE scan)
- D6.1: SAST scan results (bandit / semgrep)
- D6.2: Secrets in code (gitleaks / trufflehog)

### Step 3: Baseline Comparison

If baseline exists (see [references/baseline-schema.json](references/baseline-schema.json)):
- Compare each metric against baseline values
- Classify: ✅ improved / ⚠️ unchanged / 🔴 regressed / 🆕 new metric
- Calculate drift percentage for numeric metrics
- Flag gated metric regressions as HIGH priority

If no baseline:
- Propose baseline creation with current measurements
- Recommend which metrics to gate vs observe based on project maturity

### Step 4: Rating & Gate

Per-dimension rating (SonarQube-inspired):
- **A** (excellent): All metrics at or above target
- **B** (good): Minor issues, no regressions
- **C** (acceptable): Some issues, within tolerance
- **D** (concerning): Multiple issues or regressions
- **E** (critical): Gated metric failures or severe regressions

Gate rules: see [references/gate-rules.md](references/gate-rules.md)
- Gated metrics: MUST NOT exceed baseline (hard gate)
- Observed metrics: SHOULD NOT exceed baseline (soft gate, report only)

### Step 5: Reporting

Generate structured report using [references/report-template.md](references/report-template.md):
- Executive summary with overall gate status (PASS / WARN / FAIL)
- Per-dimension breakdown with specific findings
- Hot files (worst offenders ranked)
- Trend vs baseline (if baseline exists)
- Prioritized remediation plan (P0–P3)
- Measurement commands appendix (for reproducibility)

### Step 6: Exception Handling

When debt exceptions exist (annotations in code):
- Parse exception annotations: `// @ts-expect-error [debt-exception] owner=X ttl=YYYY-MM-DD reason="..."`
- Validate TTL not expired; flag expired exceptions as violations
- Include exception inventory in report
- See [references/exception-template.md](references/exception-template.md) for format

## Severity Model

| Level | Criteria | Action |
|-------|----------|--------|
| CRITICAL | Gated metric regression | Must fix before merge |
| HIGH | Non-gated regression or new critical lint issues | Fix in current sprint |
| MEDIUM | Pre-existing issues above threshold | Plan for next sprint |
| LOW | Minor issues, near-threshold values | Backlog |

## Project Configuration Discovery

Auto-detect from project files:
- **Python**: pyproject.toml (line-length, target-version), ruff.toml, mypy.ini
- **TypeScript**: tsconfig.json (strict), .eslintrc, package.json
- **Tests**: pytest.ini / vitest.config.ts (markers, coverage thresholds)
- **Line limits**: Python default 800, Vue/TS default 500, override from STANDARDS.md
- **Baseline**: configurable path, default `reports/analysis/tech-debt-baseline.json`
- **Governance**: configurable path, default `docs/standards/*governance*.md`

## Integration with Existing Tooling

When project has existing debt tooling, **USE IT** — do not reimplement:
- `scripts/run_tech_debt_weekly_report.sh` → use for weekly reports
- `scripts/dev/quality_gate/tech_debt_governance_gate.py` → use for gate checks
- Baseline JSON → use as authoritative source
- Drift report script → use for drift analysis

## Required Checks (Analyze Mode)

All checks must complete before report generation:

- [ ] D1.1: Static type errors
- [ ] D1.2: Lint issues with severity breakdown
- [ ] D1.3: Type suppressions count
- [ ] D1.4: Large files exceeding line limits
- [ ] D3.1: Test skip/xfail count
- [ ] D3.2: Placeholder assertions in tests
- [ ] Baseline comparison (if baseline exists)
- [ ] Gate evaluation (if governance rules exist)
- [ ] Exception inventory (if annotations found)

## Required States

| After Step | State |
|-----------|-------|
| Step 2 complete | All measurement results captured |
| Step 3 complete | Drift classification done for each metric |
| Step 4 complete | Gate status determined (PASS/WARN/FAIL) |
| Step 5 complete | Report file written to project reports directory |

## Failure Handling

- **Measurement command fails**: Skip dimension, report as "measurement unavailable", continue others
- **Baseline file missing**: Run analyze without comparison, propose baseline creation
- **Governance charter missing**: Use default gate rules from references/gate-rules.md
- **No test framework detected**: Skip D3, note in report

## Execution Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| Tech debt report | `reports/analysis/tech-debt-report-YYYY-MM-DD.md` | Full analysis report |
| Baseline file | `reports/analysis/tech-debt-baseline.json` | Metric freeze point |
| Drift report | `reports/analysis/tech-debt-baseline-drift-report.json` | Baseline comparison |

## Reference Order

1. Project governance charter (if exists)
2. Project baseline JSON (if exists)
3. Project STANDARDS.md (if exists)
4. This skill's `references/` directory
5. General best practices (SQALE/SonarQube methodology)
