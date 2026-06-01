# Gate Rules Reference

This reference defines deterministic default rules. Project governance may tighten these rules, but reports must clearly state any override.

## Gate Model

Hard gates decide FAIL. Soft gates decide WARN. Observed metrics provide context and remediation priority.

| Gate | Meaning |
|------|---------|
| `hard` | Must pass absolute target or must not regress beyond approved baseline |
| `soft` | Should not regress; regression produces WARN unless project policy escalates |
| `none` | Informational metric only |

## Gate Status Values

| Status | Meaning |
|--------|---------|
| `PASS` | All hard gates pass and no critical findings exist |
| `WARN` | Hard gates pass, but soft/observed metrics regressed or ratings declined |
| `FAIL` | Any hard gate fails, required gated metric is unavailable, or critical finding exists |

## Default Hard Gates

Use these by default unless the project has stricter governance.

| Metric Pattern | Dimension | Rule |
|----------------|-----------|------|
| `*_type_errors` | D1 | Must equal `0` |
| `*_lint_errors` | D1 | Must equal `0` unless the project explicitly baselines lint errors |
| `test_failed` | D3 | Must equal `0` |
| `secrets_in_code` | D6 | Must equal `0` |
| `critical_cve_count` | D5 | Must equal `0` |
| `high_cve_count` | D5 | Must equal `0` unless project policy defines a temporary exception |
| `debt_exception_expired` | D6 | Must equal `0` |
| `debt_exception_missing_owner` | D6 | Must equal `0` |
| `debt_exception_missing_ttl` | D6 | Must equal `0` |
| gated suppression counts | D1/D3 | Must not exceed approved baseline |
| gated skip/xfail counts | D3 | Must not exceed approved baseline |

Required hard-gate metrics that are unavailable cause `FAIL` unless the metric is explicitly `not_applicable` with evidence, such as "no test framework configured".

## Default Soft/Observed Metrics

| Metric Pattern | Dimension | Rule |
|----------------|-----------|------|
| `*_lint_warnings` | D1 | Warn when above baseline or target |
| `large_file_count_*` | D1/D2 | Warn when above baseline or target |
| `god_file_count_*` | D2 | Warn when above baseline or target |
| `skip_xfail_count` when not hard-gated | D3 | Warn when above baseline |
| `test_coverage_percent` | D3 | Warn when below baseline or target |
| `todo_count_*`, `fixme_count_*`, `hack_count_*`, `xxx_count_*` | D6 | Warn when above baseline |
| `outdated_deps_*` | D5 | Warn when above baseline or contains major upgrades |
| documentation completeness metrics | D4 | Warn when below target |

## Baseline Comparison

When a baseline exists:

- Match metrics by `id`.
- Compare current `value` to `baseline_value`.
- Record `drift` and `status` for every metric.
- Mark new metrics as `new`; removed baseline metrics as `removed`.
- Do not write "no baseline" language.
- Do not use historical baseline values as current measurements.

When no baseline exists:

- Produce measurements and a baseline candidate.
- Apply absolute hard targets where possible, such as secrets = 0 and failing tests = 0.
- Do not claim drift.

## Dimension Rating Rules

Ratings are deterministic before any narrative interpretation.

### Global Overrides

- Any hard gate failure in a dimension makes that dimension `E`.
- Any unavailable required hard-gate metric makes that dimension `E`.
- `test_failed > 0` makes D3 `E`.
- Any secrets finding makes D6 `E`.
- Any critical/high CVE finding makes D5 `E`.
- Any expired or malformed debt exception makes D6 `E`.

### D1: Code Quality

- `A`: 0 type errors, 0 lint errors, no suppression regressions, no large-file regression.
- `B`: hard gates pass; only minor warning debt.
- `C`: hard gates pass; significant stable warning/large-file debt.
- `D`: hard gates pass; major observed regression.
- `E`: type/lint hard gate failure or unavailable required hard-gate metric.

### D2: Architecture

- `A`: no circular deps, no god-file/class candidates above target.
- `B`: minor stable structural debt.
- `C`: significant stable structural debt.
- `D`: major structural regression or unmanaged god-file growth.
- `E`: architecture hard gate fails if configured.

### D3: Testing

- `A`: 0 failing tests, no skip/xfail regression, coverage at/above target.
- `B`: 0 failing tests; minor observed testing debt.
- `C`: 0 failing tests; low but stable coverage or high stable skips.
- `D`: 0 failing tests; testing debt regressed materially.
- `E`: any failing test, unavailable required test metric, or hard-gated skip/xfail regression.

Do not describe pass rate as coverage.

### D4: Documentation

- `A`: required operator/API/governance docs present and current.
- `B`: minor documentation gaps.
- `C`: important but non-blocking gaps.
- `D`: stale or missing release-critical docs.
- `E`: documentation hard gate fails if configured.

### D5: Dependencies

- `A`: 0 known CVEs, no major unmanaged outdated dependency risk.
- `B`: 0 known CVEs, minor upgrade lag.
- `C`: 0 high/critical CVEs, significant managed upgrade lag.
- `D`: non-critical vulnerability debt or unmanaged major migration risk.
- `E`: critical/high CVE hard gate failure.

### D6: Process & Security

- `A`: 0 secrets, 0 expired/malformed exceptions, no SAST high/critical findings.
- `B`: hard gates pass; minor process debt.
- `C`: hard gates pass; significant but stable process debt.
- `D`: process/security observed metrics regressed materially.
- `E`: secrets, expired/malformed exceptions, SAST hard gate, or governance hard gate failure.

## Exception Handling

Debt exceptions require:

- Owner.
- TTL.
- Reason.
- Issue or remediation tracking when project policy requires it.

Expired, missing-owner, missing-TTL, or malformed exceptions are hard gate failures by default.

## Project-Specific Override

Projects may override rules in governance files or baseline metadata. Reports must name the source and show the effective rule. Example:

```json
{
  "gate_defaults": {
    "hard": ["backend_type_errors", "frontend_type_errors", "test_failed", "secrets_in_code"],
    "soft": ["backend_lint_warnings", "large_file_count_backend", "test_coverage_percent"]
  }
}
```
