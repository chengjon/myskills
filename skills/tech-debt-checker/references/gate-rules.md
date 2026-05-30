# Gate Rules Reference

## Gate Model

The tech debt governance gate uses an AND model across gated dimensions. ALL gated metrics must pass for overall gate status PASS.

### Gate Status Values

| Status | Meaning |
|--------|---------|
| **PASS** | All gated metrics ≤ baseline, no critical findings |
| **WARN** | All gated metrics pass, but observed metrics regressed or ratings declined |
| **FAIL** | One or more gated metrics exceed baseline |

## Default Gated Metrics

These metrics are hard-gated by default (must NOT exceed baseline):

| Metric Key | Dimension | Threshold Rule |
|-----------|-----------|---------------|
| `frontend_type_errors` | D1 | Must equal 0, or not exceed baseline |
| `frontend_suppressions_count` | D1 | Must not exceed baseline |
| `skip_xfail_count` | D3 | Must not exceed baseline |
| `backend_api_documentation.total_issues` | D4 | Must not exceed baseline |

## Default Observed Metrics

These metrics are tracked but NOT hard-gated (regressions reported but non-blocking):

| Metric Key | Dimension | Typical Threshold |
|-----------|-----------|------------------|
| `backend_todo_count` | D6 | Track trend, flag if >20% increase |
| `backend_placeholder_count` | D1 | Track trend, flag if >20% increase |
| `test_placeholder_assert_count` | D3 | Track trend, flag if >20% increase |
| `backend_lint_errors` | D1 | Track trend, flag if >20% increase |
| `backend_lint_warnings` | D1 | Track trend, flag if >30% increase |
| `backend_type_suppressions` | D1 | Track trend, flag if >20% increase |
| `large_file_count_python` | D1 | Track trend, flag if increasing |
| `large_file_count_frontend` | D1 | Track trend, flag if increasing |

## Project-Specific Override

Projects can override gate rules via their governance charter or baseline JSON:
- Add/remove metrics from gated/observed lists
- Set custom thresholds (e.g., "skip_xfail must be < 20" regardless of baseline)
- Define dimension-specific passing criteria

## Dimension Rating Rules

### D1: Code Quality
- **A**: 0 type errors, 0 suppressions, 0 large files
- **B**: 0 type errors, ≤5 suppressions, ≤3 large files
- **C**: 0 type errors, ≤10 suppressions, ≤7 large files
- **D**: >0 type errors or >10 suppressions or >7 large files
- **E**: >5 type errors or gated metric regression

### D3: Testing
- **A**: 0 skip/xfail, 0 placeholder asserts, coverage >80%
- **B**: ≤5 skip/xfail, ≤10 placeholders, coverage >60%
- **C**: ≤15 skip/xfail, ≤30 placeholders, coverage >40%
- **D**: ≤30 skip/xfail or coverage >20%
- **E**: >30 skip/xfail or gated metric regression

### D4: Documentation
- **A**: 100% API doc coverage, all endpoints have examples
- **B**: >95% API doc coverage, >90% examples
- **C**: >80% API doc coverage, >70% examples
- **D**: >60% API doc coverage
- **E**: <60% API doc coverage or gated metric regression

### D5: Dependencies
- **A**: 0 vulnerable deps, 0 outdated critical deps
- **B**: 0 vulnerable deps, ≤5 outdated non-critical
- **C**: 0 critical CVEs, ≤10 outdated
- **D**: ≤2 critical CVEs
- **E**: >2 critical CVEs or >20 outdated

### D6: Process & Security
- **A**: 0 SAST high/critical, 0 secrets, governance gate always passes
- **B**: 0 SAST critical, ≤5 high, 0 secrets
- **C**: ≤2 SAST critical, ≤10 high, 0 secrets
- **D**: ≤5 SAST critical
- **E**: >5 SAST critical or secrets found or governance gate always fails

## New-Code vs Overall-Code Distinction

Following SonarQube's model:
- **New code** (since last baseline): Stricter thresholds, zero-tolerance for regressions
- **Overall code**: Track trends, allow gradual improvement plans

When gating:
- New regressions in new code → automatic FAIL (regardless of severity)
- Pre-existing issues in overall code → WARN with remediation plan

## Exception Handling

Debt exceptions are allowed with:
- **Owner**: Responsible developer
- **TTL**: Expiration date (auto-flagged when expired)
- **Reason**: Justification
- **Issue**: Tracking issue number
- **Remediation plan**: How and when to fix

Expired exceptions count as violations in the gate check.
