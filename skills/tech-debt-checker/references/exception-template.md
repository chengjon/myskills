# Debt Exception Template

## Annotation Format

### TypeScript / Vue

```typescript
// @ts-expect-error [debt-exception] owner={username} issue={ISSUE-KEY} ttl={YYYY-MM-DD} reason="{justification}"
```

### Python

```python
# type: ignore[{error-code}]  # [debt-exception] owner={username} issue={ISSUE-KEY} ttl={YYYY-MM-DD} reason="{justification}"
```

### pytest skip/xfail

```python
@pytest.mark.skip(reason="[debt-exception] owner={username} issue={ISSUE-KEY} ttl={YYYY-MM-DD}")
def test_something():
    ...
```

## Field Definitions

| Field | Required | Format | Description |
|-------|----------|--------|-------------|
| `owner` | Yes | username | Developer responsible for resolution |
| `issue` | Yes | ISSUE-KEY | Tracking issue (GitHub Issue, Jira, etc.) |
| `ttl` | Yes | YYYY-MM-DD | Expiration date; auto-flagged when past |
| `reason` | Yes | Free text | Why the debt is acceptable temporarily |

## Validation Rules

1. **TTL must be set** — no indefinite exceptions
2. **TTL maximum**: 90 days from annotation date
3. **Issue must exist** — validate issue number is real
4. **Owner must be active** — developer with repo access
5. **Reason must be specific** — "temporary", "fix later", "won't fix" are rejected

## Exception Lifecycle

```
Created → Active → Approaching TTL (warn at 7 days) → Expired (flagged as violation) → Resolved
```

## Report Integration

When generating tech debt reports:
1. Scan codebase for all `[debt-exception]` annotations
2. Parse owner, issue, TTL, reason from each
3. Check TTL against current date
4. Categorize: Active / Approaching TTL / Expired
5. Include in report's "Debt Exception Inventory" section

## Governance Gate Behavior

- **Active exceptions**: Do NOT count toward gated metric violations
- **Expired exceptions**: Count as violations (same as un-annotated issues)
- **Malformed exceptions**: Count as violations (annotation is invalid)
- **Missing TTL**: Count as violations (no expiration = no exception)

## Batch Exception Template

For project-wide temporary exceptions (e.g., framework migration):

```markdown
## Batch Exception Declaration

**Scope**: {files/patterns affected}
**Reason**: {migration/refactor description}
**Owner**: {lead developer}
**Issue**: {tracking issue}
**TTL**: {expiration date}
**Expected resolution**: {description of end state}

### Affected Metrics
- {metric_key}: baseline {n} → temporary threshold {n}
- {metric_key}: baseline {n} → temporary threshold {n}

### Affected Files
- {glob pattern or file list}
```

Store batch exception declarations in project documentation (e.g., `docs/standards/debt-exceptions.md`).
