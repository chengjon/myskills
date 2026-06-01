# Tech Debt Report Template

Report output for `tech-debt-checker` report mode. Render this from measurement/gate JSON. Do not manually re-interpret raw command output in Markdown.

```markdown
# Tech Debt Analysis Report - {project}

Generated: {timestamp}
Mode: {mode}
Baseline: {baseline_state}
Git: {git_sha} ({branch}), dirty_worktree={dirty_worktree}
Measurement artifact: `{measurement_json_path}`
Gate artifact: `{gate_json_path}`

## Executive Summary

| Metric | Status |
|--------|--------|
| Overall Gate | **{PASS/WARN/FAIL}** |
| Hard Gates | {hard_passed}/{hard_total} passed |
| Soft Gates | {soft_regressed} regressed |
| Baseline State | {missing / candidate / compared / schema-mismatch} |
| D1 Code Quality | {A-E} |
| D2 Architecture | {A-E} |
| D3 Testing | {A-E} |
| D4 Documentation | {A-E} |
| D5 Dependencies | {A-E} |
| D6 Process/Security | {A-E} |

Key findings:

- {finding with metric ID, kind, scope, and value}
- {finding with metric ID, kind, scope, and value}
- {finding with metric ID, kind, scope, and value}
```

Rules:

- If a baseline exists, this section must mention drift/comparison and must not say "no baseline" or "create baseline".
- If no baseline exists, call the output a baseline candidate and do not claim drift.
- Do not call test pass rate "coverage"; coverage requires a coverage metric.

## Metric Source Labels

Every non-trivial metric claim must include a source label:

| Label | Meaning |
|-------|---------|
| `Measured` | Current measurement from a command/tool |
| `Inferred` | Derived from partial evidence or a calculated estimate |
| `Historical Baseline` | Approved prior baseline value used for comparison |

Example:

```markdown
- Measured: `backend_type_errors` = 0, scope: `gitnexus`, time: 2026-06-01T19:00:00Z.
- Historical Baseline: `backend_type_errors` = 0, baseline: `reports/analysis/tech-debt-baseline.json`.
```

## D1: Code Quality

```markdown
## D1: Code Quality

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `backend_type_errors` | backend | {value} | {baseline} | {drift} | hard | {status} |
| `frontend_type_errors` | frontend | {value} | {baseline} | {drift} | hard | {status} |
| `backend_lint_errors` | backend | {value} | {baseline} | {drift} | hard | {status} |
| `backend_lint_warnings` | backend | {value} | {baseline} | {drift} | soft | {status} |
| `large_file_count_backend` | backend | {value} | {baseline} | {drift} | soft | {status} |
| `large_file_count_frontend` | frontend | {value} | {baseline} | {drift} | soft | {status} |

Measurement scope:

- Backend roots: {roots}; extensions: {extensions}; excludes: {excludes}; line-count method: {method}
- Frontend roots: {roots}; extensions: {extensions}; excludes: {excludes}; line-count method: {method}

Hot files:

| Rank | File | Lines | Lint Warnings | Primary Concern |
|------|------|-------|---------------|-----------------|
| 1 | `{file}` | {lines} | {warnings} | {concern} |

### D1 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}
```

## D2: Architecture

```markdown
## D2: Architecture

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `circular_dependency_count` | repo | {value} | {baseline} | {drift} | {gate} | {status} |
| `god_file_count_backend` | backend | {value} | {baseline} | {drift} | {gate} | {status} |

God file/class candidates:

| File/Symbol | Lines/Size | Scope | Evidence |
|-------------|------------|-------|----------|
| `{path}` | {lines} | {scope} | {metric_id} |

### D2 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}
```

## D3: Testing

```markdown
## D3: Testing

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `test_total` | repo | {value} | {baseline} | {drift} | none | {status} |
| `test_passed` | repo | {value} | {baseline} | {drift} | none | {status} |
| `test_failed` | repo | {value} | {baseline} | {drift} | hard | {status} |
| `test_pending` | repo | {value} | {baseline} | {drift} | none | {status} |
| `skip_xfail_count` | repo | {value} | {baseline} | {drift} | {gate} | {status} |
| `test_placeholder_assert_count` | repo | {value} | {baseline} | {drift} | soft | {status} |
| `test_coverage_percent` | repo | {value}% | {baseline}% | {drift} | soft | {status} |

Failing tests:

| Suite/File | Count | Primary Failure |
|------------|-------|-----------------|
| `{file}` | {count} | {summary} |

Skip/xfail inventory:

| Category | Count | Notes |
|----------|-------|-------|
| {category} | {count} | {notes} |

### D3 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}. If `test_failed > 0`, D3 must be E unless this is explicitly a failing baseline candidate.
```

## D4: Documentation

```markdown
## D4: Documentation

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `docs_required_present` | repo | {value} | {baseline} | {drift} | {gate} | {status} |
| `adr_directory_present` | repo | {value} | {baseline} | {drift} | {gate} | {status} |
| `api_doc_coverage_percent` | repo | {value}% | {baseline}% | {drift} | {gate} | {status} |

### D4 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}
```

## D5: Dependencies

```markdown
## D5: Dependencies

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `outdated_deps_backend` | backend | {value} | {baseline} | {drift} | soft | {status} |
| `outdated_deps_frontend` | frontend | {value} | {baseline} | {drift} | soft | {status} |
| `critical_cve_count` | repo | {value} | {baseline} | {drift} | hard | {status} |
| `high_cve_count` | repo | {value} | {baseline} | {drift} | hard | {status} |

Notable dependency risks:

| Package | Scope | Current | Latest | Risk |
|---------|-------|---------|--------|------|
| `{package}` | {scope} | {current} | {latest} | {risk} |

### D5 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}
```

## D6: Process & Security

```markdown
## D6: Process & Security

| Metric ID | Scope | Current | Baseline | Drift | Gate | Status |
|-----------|-------|---------|----------|-------|------|--------|
| `secrets_in_code` | repo | {value} | {baseline} | {drift} | hard | {status} |
| `sast_high_count` | repo | {value} | {baseline} | {drift} | hard/soft | {status} |
| `todo_count_backend` | backend | {value} | {baseline} | {drift} | soft | {status} |
| `fixme_count_backend` | backend | {value} | {baseline} | {drift} | soft | {status} |
| `debt_exception_total` | repo | {value} | {baseline} | {drift} | none | {status} |
| `debt_exception_expired` | repo | {value} | {baseline} | {drift} | hard | {status} |
| `debt_exception_missing_owner` | repo | {value} | {baseline} | {drift} | hard | {status} |
| `debt_exception_missing_ttl` | repo | {value} | {baseline} | {drift} | hard | {status} |

### D6 Rating: {A-E}

Rationale: {deterministic rule and metric IDs}
```

## Exception Inventory

```markdown
## Debt Exception Inventory

| Metric ID | Value | Status |
|-----------|-------|--------|
| `debt_exception_total` | {value} | {status} |
| `debt_exception_expired` | {value} | {status} |
| `debt_exception_expiring_soon_30d` | {value} | {status} |
| `debt_exception_missing_owner` | {value} | {status} |
| `debt_exception_missing_ttl` | {value} | {status} |

Details:

| File | Line | Owner | TTL | Status | Reason |
|------|------|-------|-----|--------|--------|
| `{file}` | {line} | {owner} | {ttl} | {status} | {reason} |
```

## Remediation Plan

```markdown
## Governance Priorities

### P0 - Fix Immediately

| Issue | Metric ID | Scope | Action |
|-------|-----------|-------|--------|
| {issue} | `{metric_id}` | {scope} | {action} |

### P1 - Current Sprint

| Issue | Metric ID | Scope | Action |
|-------|-----------|-------|--------|
| {issue} | `{metric_id}` | {scope} | {action} |

### P2 - Next Sprint

| Issue | Metric ID | Scope | Action |
|-------|-----------|-------|--------|
| {issue} | `{metric_id}` | {scope} | {action} |

### P3 - Backlog

| Issue | Metric ID | Scope | Action |
|-------|-----------|-------|--------|
| {issue} | `{metric_id}` | {scope} | {action} |
```

## Reproducibility Appendix

```markdown
## Reproducibility

| Command ID | Tool | Scope | Exit | Status |
|------------|------|-------|------|--------|
| `{command_id}` | `{tool}` | `{scope}` | `{exit_code}` | `{status}` |

Tool versions:

| Tool | Version |
|------|---------|
| node | {version} |
| npm | {version} |
| tsc | {version} |
| eslint | {version} |

Measurement roots/excludes:

| Metric ID | Roots | Extensions | Excludes |
|-----------|-------|------------|----------|
| `{metric_id}` | `{roots}` | `{extensions}` | `{excludes}` |
```

## Artifact Self-Check

Include the self-check result in the report or adjacent gate JSON:

```markdown
## Artifact Self-Check

| Check | Status |
|-------|--------|
| Markdown metric claims map to JSON metric IDs | {pass/fail} |
| Gated metrics exist in measurement JSON | {pass/fail} |
| Baseline language matches baseline state | {pass/fail} |
| Failing tests force FAIL or failing-baseline-candidate language | {pass/fail} |
| Coverage is not confused with pass rate | {pass/fail} |
| Large-file scope declares roots/extensions/excludes/method | {pass/fail} |
| Backend/frontend metric scopes are not crossed | {pass/fail} |
| Debt exception metrics are present | {pass/fail} |
| Commands include git SHA, dirty status, tool versions, and exits | {pass/fail} |
```
