# Route-Truth Coverage Matrix

This matrix tracks canonical route coverage by stable defect family.

Treat it as next-pass planning truth, not as a free-form changelog.

Legend:

- `R`: repaired and verified during the audit campaign
- `S`: deliberately scanned and no active issue found in that family
- `?`: not yet deliberately swept for that family
- `-`: family not currently applicable or not meaningful for that route

Family columns:

- `NUM`: numeric-truth
- `PROV`: request-provenance-truth
- `FRESH`: freshness-truth
- `PART`: partial-slice-truth
- `SEL`: selector-scoped-snapshot-truth
- `EXEC`: local-action-and-execution-truth
- `ENR`: enrichment-and-auxiliary-slice-truth

## Dashboard / Market / Data

| Route | NUM | PROV | FRESH | PART | SEL | EXEC | ENR | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/dashboard` | R | R | S | R | R | - | R | aggregate shell, capital-flow tabs, auxiliary slices |
| `/market/realtime` | R | R | S | - | R | - | - | preset-scoped quote snapshot |
| `/market/technical` | S | R | S | - | - | - | - | primary K-line sample truth |
| `/market/lhb` | R | R | S | - | R | - | - | trade-date selector and rank/count truth |
| `/data/industry` | R | R | R | - | - | - | - | first-load provenance and KPI truth |
| `/data/concept` | R | R | R | - | - | - | - | first-load placeholder truth and request provenance retention |
| `/data/fund-flow` | R | R | R | - | - | - | - | ranking request provenance and row meta |
| `/data/indicator` | - | - | R | - | R | R | - | category selector and action-triggered freshness; no request-provenance surface |

## Watchlist / Strategy / Trade

| Route | NUM | PROV | FRESH | PART | SEL | EXEC | ENR | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/watchlist/manage` | - | - | R | - | R | - | - | selector-scoped watchlist rows with honest pending and stale stock-shell states |
| `/watchlist/signals` | R | R | R | - | - | - | - | shared signal summary strip |
| `/watchlist/screener` | - | R | R | - | - | - | - | resolved failure envelope and request truth |
| `/strategy/repo` | R | R | R | - | S | - | - | stale-refresh retention on list shell |
| `/strategy/parameters` | R | R | R | - | R | - | - | selector-scoped cards and hero meta |
| `/strategy/signals` | R | R | R | - | R | - | - | selector-scoped rows/count/request |
| `/strategy/backtest` | R | S | R | - | R | R | R | reports, tasks, logs, KPI, optimize tab |
| `/strategy/gpu` | - | - | S | R | - | - | R | partial-sync runtime banner; no request-provenance surface |
| `/strategy/opt` | R | R | R | - | R | - | - | selector-scoped optimization rows |
| `/strategy/pos` | - | R | R | - | - | - | - | shared positions owner with trade |
| `/trade/positions` | - | R | R | - | - | - | - | verified positions snapshot provenance |
| `/trade/terminal` | - | - | R | R | - | - | R | per-slice stale retention and route-level degraded freshness truth across the workbench |
| `/trade/signals` | R | R | R | - | - | - | - | store-refresh provenance retention |
| `/trade/portfolio` | R | R | R | - | - | - | - | portfolio summary, request provenance, and rebalance-policy truth; shared wrapper `/risk/pnl` inherits the same owner |
| `/trade/history` | R | R | R | - | - | - | - | request/time/rows truth across first-load states |
| `/trade/reconciliation` | R | R | R | - | R | - | - | account-scoped rows, import metadata, result metrics, request provenance, and verified freshness now clear on unresolved same-instance account switches |

## Risk / System / Detail

| Route | NUM | PROV | FRESH | PART | SEL | EXEC | ENR | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/risk/overview` | R | R | S | R | - | - | - | rules and alerts split into independent verified slices |
| `/risk/pnl` | R | R | R | - | - | - | - | thin wrapper over the canonical trade portfolio owner |
| `/risk/management` | S | - | R | - | - | - | - | freshness footer and cadence truth |
| `/risk/stop-loss` | - | R | S | - | R | - | - | implicit selector watchlist truth |
| `/risk/alerts` | R | R | S | R | - | - | - | rules vs alerts partial-truth split |
| `/risk/news` | R | R | R | - | - | - | - | first-load and stale-refresh request truth on announcement shell |
| `/system/config` | R | R | - | - | R | - | - | active-tab request provenance plus source-tab unresolved count truth |
| `/system/health` | R | R | - | - | - | - | - | health snapshot request provenance plus unresolved first-load summary labels |
| `/system/api` | R | R | - | - | - | - | - | probe snapshot request provenance plus unresolved first-load summary labels |
| `/system/resources` | R | R | R | - | - | - | - | unresolved first-load resource counts and node label now degrade to `--` while hero provenance/freshness stays `N/A` until the first verified snapshot exists |
| `/system/data` | R | R | - | - | - | - | - | config snapshot request provenance and unresolved count-card truth |
| `/detail/graphics/:symbol` | - | R | S | R | R | - | R | symbol+period scoped K-line and indicators |
| `/detail/news/:symbol` | R | S | S | R | R | - | R | rows, stats, and auxiliary selector truth |

## Use

- Pick the next route from rows that still contain `?` in high-risk families such as `SEL`, `PART`, `PROV`, or `ENR`.
- If a family is repeatedly repaired across domains but still appears as `?` on many canonical routes, batch the next pass by family rather than by page.
- Update only the affected row cells after each completed batch; do not use this matrix as a free-form changelog.

## Blank Layout Routes

These routes are audited as lightweight blank-layout mini batches rather than full canonical business-route family rows.

| Route | Status | Notes |
| --- | --- | --- |
| `/login` | R | blank shell isolated from shared stats and request chrome; smoke route for unauthenticated shell |
| `/:pathMatch(.*)*` | R | 404 shell isolated from shared stats and request chrome; recovery action now uses canonical `HOME_ROUTE_PATH` |
