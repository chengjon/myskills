# Debt Exception Template

Debt exceptions are temporary, owned waivers. They must be measurable and must expire.

## Annotation Format

### TypeScript / Vue

```ts
// @ts-expect-error [debt-exception] owner=team-platform ttl=2026-07-01 issue=GNX-123 reason="third-party type is wrong until upstream fix lands"
```

### Python

```py
# type: ignore[import-untyped]  # [debt-exception] owner=team-platform ttl=2026-07-01 issue=GNX-123 reason="vendor lacks stubs"
```

### pytest skip/xfail

```py
@pytest.mark.xfail(reason="[debt-exception] owner=team-platform ttl=2026-07-01 issue=GNX-123 reason='known flaky external service'")
```

## Required Fields

| Field | Required | Meaning |
|-------|----------|---------|
| `owner` | yes | Person or team responsible for removal |
| `ttl` | yes | Expiration date in `YYYY-MM-DD` |
| `reason` | yes | Concrete reason for the temporary exception |
| `issue` | recommended | Tracking issue, ticket, or milestone |
| `remediation` | recommended | Short removal plan if not obvious |

## Validation Metrics

Emit these metrics in measurement JSON:

| Metric ID | Gate | Meaning |
|-----------|------|---------|
| `debt_exception_total` | none | All exception annotations found |
| `debt_exception_expired` | hard | TTL earlier than the measurement date |
| `debt_exception_expiring_soon_30d` | soft | TTL within 30 days |
| `debt_exception_missing_owner` | hard | Missing owner |
| `debt_exception_missing_ttl` | hard | Missing TTL |
| `debt_exception_malformed` | hard | Annotation cannot be parsed |

## Validation Rules

- TTL must parse as an ISO date.
- Expired means `ttl < measured_date`.
- Missing owner, missing TTL, malformed syntax, and expired TTL are hard gate failures by default.
- Exceptions without issue/remediation are warnings unless project governance makes them hard failures.
- Generated or vendored files may be excluded only when the metric metadata lists the exclude rule.

## Report Integration

Reports must include an exception inventory table:

| File | Line | Owner | TTL | Status | Issue | Reason |
|------|------|-------|-----|--------|-------|--------|
| `src/example.ts` | 42 | team-platform | 2026-07-01 | active | GNX-123 | vendor type issue |

If no exceptions are found, still emit `debt_exception_total = 0` and hard-gate exception metrics with value `0`. Do not omit the metrics.

## Lifecycle

1. Add exception only with owner, TTL, and reason.
2. Track in issue/remediation plan when the exception will last more than one sprint.
3. Review expiring-soon exceptions during debt review.
4. Remove exception or renew with explicit approval before TTL.
5. Expired exceptions fail the tech debt gate.
