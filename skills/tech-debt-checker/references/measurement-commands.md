# Measurement Commands Reference

Commands are examples for deriving metric JSON. Prefer an existing project script when available. Run commands from the repository root or use absolute paths/subshells. Do not rely on stateful `cd` chains in report appendices.

## Reproducibility Requirements

Every command result should record:

- `command_id`
- tool name and version
- source roots
- extensions
- excludes
- exit code
- status: `pass`, `warn`, `fail`, `unavailable`, or `not_applicable`
- git SHA and dirty worktree state
- timestamp

Recommended metadata commands:

```bash
git rev-parse HEAD
git status --short
node --version
npm --version
```

## Root-Safe Patterns

Use subshells when a package-specific working directory is required:

```bash
(cd gitnexus && npx tsc --noEmit)
(cd gitnexus-web && npx tsc --noEmit)
```

Avoid this in reproducibility appendices because later commands inherit unexpected state:

```bash
cd gitnexus && npx tsc --noEmit
cd gitnexus-web && npm outdated
```

## D1: Code Quality

### Type Errors

```bash
# Backend TypeScript
(cd gitnexus && npx tsc --noEmit)

# Frontend TypeScript/Vue/React
(cd gitnexus-web && npx tsc --noEmit)
(cd gitnexus-web && npx vue-tsc --noEmit)
```

Emit separate metrics such as `backend_type_errors` and `frontend_type_errors`. Do not store backend results under frontend keys.

### Lint Errors And Warnings

Prefer JSON output and parse severity counts:

```bash
(cd gitnexus && npx eslint "src/**/*.ts" --format json)
(cd gitnexus-web && npx eslint "src/**/*.{ts,tsx,vue}" --format json)
```

Emit separate metrics for errors and warnings, for example `backend_lint_errors`, `backend_lint_warnings`, `frontend_lint_errors`, `frontend_lint_warnings`.

### Type Suppressions

Scan only declared source roots and extensions:

```bash
rg -n "@ts-ignore|@ts-expect-error|@ts-nocheck" gitnexus/src -g "*.ts"
rg -n "@ts-ignore|@ts-expect-error|@ts-nocheck" gitnexus-web/src -g "*.ts" -g "*.tsx" -g "*.vue"
```

Also scan for debt-exception metadata:

```bash
rg -n "debt-exception" .
```

### Large Files

Large-file metrics must record roots, extensions, excludes, threshold, and line-count method.

Example roots/extensions:

```json
{
  "backend": {
    "roots": ["gitnexus/src"],
    "extensions": [".ts"],
    "excludes": ["node_modules", "dist", "coverage"],
    "threshold_lines": 500
  },
  "frontend": {
    "roots": ["gitnexus-web/src"],
    "extensions": [".ts", ".tsx", ".vue"],
    "excludes": ["node_modules", "dist", "coverage"],
    "threshold_lines": 500
  }
}
```

Use a small script to avoid shell precedence bugs in `find`:

```bash
node scripts/dev/collect-large-files.mjs --root gitnexus/src --ext .ts --limit 500
node scripts/dev/collect-large-files.mjs --root gitnexus-web/src --ext .ts,.tsx,.vue --limit 500
```

If no project script exists, derive the count in a sandboxed script and print JSON only.

## D2: Architecture

### Circular Dependencies

```bash
(cd gitnexus && npx madge src --extensions ts --circular --json)
(cd gitnexus-web && npx madge src --extensions ts,tsx --circular --json)
```

If no circular-dependency tool exists, mark the metric `unavailable` rather than inventing a value.

### God File/Class Candidates

Large-file output can feed god-file metrics. Use additional symbol-level tools only when available.

## D3: Testing

### Test Totals And Failures

Prefer machine-readable output:

```bash
(cd gitnexus && npx vitest run --reporter=json)
(cd gitnexus-web && npx vitest run --reporter=json)
pytest --json-report
```

Emit at least:

- `test_total`
- `test_passed`
- `test_failed`
- `test_pending`
- `test_duration_ms` when available

`test_failed` is a hard gate with target `0`.

### Skip/Xfail/Todo Counts

Examples:

```bash
rg -n "test\\.skip|it\\.skip|describe\\.skip|test\\.todo|it\\.todo|skipIf\\s*\\(" gitnexus/test -g "*.ts"
rg -n "@pytest\\.mark\\.(skip|skipif|xfail)|pytest\\.skip\\(" tests -g "*.py"
```

Categorize environmental skips separately from unconditional skips when possible, but keep the total count in a metric.

### Placeholder Assertions

Examples:

```bash
rg -n "expect\\(true\\)\\.toBe\\(true\\)|assert True|pass\\s*$|TODO" test tests gitnexus/test gitnexus-web/src -g "*.ts" -g "*.tsx" -g "*.py"
```

### Coverage

Coverage must come from coverage tooling, not test pass rate:

```bash
(cd gitnexus && npx vitest run --coverage)
(cd gitnexus-web && npx vitest run --coverage)
pytest --cov --cov-report=json
```

## D4: Documentation

Measure required documentation from project governance first. Common metrics:

- required docs present/missing
- API doc coverage
- ADR directory present
- stale docs count

Record each required file set in the metric metadata.

## D5: Dependencies

### Outdated Dependencies

```bash
(cd gitnexus && npm outdated --json)
(cd gitnexus-web && npm outdated --json)
cargo outdated --format json
pip list --outdated --format=json
```

### Vulnerabilities

```bash
(cd gitnexus && npm audit --json)
(cd gitnexus-web && npm audit --json)
cargo audit --json
pip-audit --format json
```

Emit:

- `critical_cve_count`
- `high_cve_count`
- `medium_cve_count`
- `low_cve_count`

Critical/high CVEs are hard gates by default.

## D6: Process & Security

### Secrets

```bash
gitleaks detect --source . --report-format json --report-path reports/analysis/gitleaks.json
```

If no secrets tool is installed, mark the metric `unavailable`. Do not claim `0` secrets from an unrun scan.

### SAST

```bash
semgrep --config auto --json
bandit -r . -f json
```

### TODO/FIXME/HACK/XXX

Emit separate metrics by marker and scope:

```bash
rg -n "TODO|FIXME|HACK|XXX" gitnexus/src -g "*.ts"
rg -n "TODO|FIXME|HACK|XXX" gitnexus-web/src -g "*.ts" -g "*.tsx" -g "*.vue"
```

Recommended metric IDs:

- `todo_count_backend`
- `fixme_count_backend`
- `hack_count_backend`
- `xxx_count_backend`
- `todo_count_frontend`
- `fixme_count_frontend`
- `hack_count_frontend`
- `xxx_count_frontend`

### Debt Exceptions

```bash
rg -n "debt-exception" . -g "*.ts" -g "*.tsx" -g "*.vue" -g "*.py" -g "*.rs" -g "*.go"
```

Emit:

- `debt_exception_total`
- `debt_exception_expired`
- `debt_exception_expiring_soon_30d`
- `debt_exception_missing_owner`
- `debt_exception_missing_ttl`
- `debt_exception_malformed`

Expired or malformed exceptions are hard gate failures by default.
