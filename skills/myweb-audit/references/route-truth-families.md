# Route-Truth Families

`myweb-audit v2` treats route defects as a small set of stable frontend truth families.

Use this file to:

- classify new findings before naming a new batch pattern
- decide whether a route defect is genuinely new or another instance of an existing family
- decide whether a change deserves a main-skill update or only a casebook entry

## Promotion Gate

Promote the main skill only when at least one of these is true:

- a genuinely new route-truth family appears
- the verification method changes in a reusable way
- a shared primitive, store, or service boundary introduces a new class of systematic truth failure

Otherwise:

- record the incident in `route-truth-casebook.md`
- update `route-truth-coverage-matrix.md`
- do not extend the main skill body with another micro-version note

## 1. Numeric Truth

Meaning:

- visible numbers, counts, ranks, KPI values, and summary-card decorations must match the semantics actually proved by the current verified payload

Common symptoms:

- `+0%` or flat-change chrome on count-only cards
- `0.00` or `1.00` pseudo precision on whole numbers, ranks, priorities, or counts
- one live stats card beside sibling cards that silently show `0`

Verify:

- shared stat cards explicitly suppress change chrome when no comparison baseline exists
- ordinal or discrete fields use whole-number formatting
- sibling summary cards degrade to `--` when their dedicated slice is unresolved or failed

Representative routes:

- `/data/industry`
- `/market/lhb`
- `/strategy/backtest`
- `/dashboard`
- `/system/api`
- `/system/health`
- `/system/resources`

## 2. Request-Provenance Truth

Meaning:

- hero `REQ`, `REQ_ID`, `TRACE_ID`, `TIME`, or similar provenance surfaces must describe the currently visible verified snapshot rather than the last attempted transport call

Common symptoms:

- failed refresh request ID replacing the request ID of the still-visible old data
- unresolved first load showing a real-looking request token
- secondary request overwriting primary-snapshot provenance

Verify:

- unresolved first load degrades to `N/A` or equivalent placeholder
- `success -> refresh fail` keeps the last verified provenance if the old snapshot stays visible
- aggregate routes derive provenance from their primary slices

Representative routes:

- `/market/realtime`
- `/system/api`
- `/data/fund-flow`
- `/market/lhb`
- `/system/resources`

## 3. Freshness Truth

Meaning:

- `UPDATED`, `LAST UPDATED`, `LAST SYNCED`, generated-at, or similar freshness surfaces must move only when a new verified snapshot or result actually exists

Common symptoms:

- failed refresh stamps the current clock into a page that is still showing old data
- queued or running task-state updates advance route freshness
- placeholder builders seed current time before any verified payload exists

Verify:

- first load pending or failed states keep freshness at `--`
- stale-refresh retention keeps the older verified timestamp
- local actions, queued tasks, and no-op actions do not rewrite freshness

Representative routes:

- `/data/indicator`
- `/strategy/backtest`
- `/risk/management`
- `/system/resources`

## 4. Partial-Slice Truth

Meaning:

- multi-request routes must expose which slice failed while preserving slices that already verified successfully

Common symptoms:

- one failed slice clears the whole page
- aggregate shell keeps claiming `REAL/READY` while one primary slice is degraded
- dedicated stats slice fails but old sibling cards remain as if refresh succeeded

Verify:

- partial failure is visible at both slice level and route-shell level when applicable
- successfully verified slices remain visible
- failed slice either degrades to placeholder truth or explicit stale-state UX

Representative routes:

- `/dashboard`
- `/risk/overview`
- `/risk/alerts`
- `/detail/graphics/:symbol`

## 5. Selector-Scoped Snapshot Truth

Meaning:

- rows, counts, request provenance, and selector-owned panels must stay scoped to the current tab, symbol, period, watchlist, strategy, or query entity

Common symptoms:

- same-instance route switch leaks old rows into the new selector shell
- active selector label changes but old request ID or summary remains
- pending new selector still shows the previous selector's verified content

Verify:

- unresolved new selector degrades to selector-local placeholders
- if old rows are retained after a selector failure, visible selector chrome stays pinned to the last verified selector
- selector-owned context panels clear or rebind when refreshed rows change

Representative routes:

- `/watchlist/manage`
- `/strategy/signals`
- `/strategy/parameters`
- `/strategy/opt`
- `/market/lhb`
- `/market/realtime`
- `/detail/news/:symbol`
- `/detail/graphics/:symbol`

## 6. Local-Action And Execution Truth

Meaning:

- generated hints, task progress, execution logs, queued/running states, or other local action outputs must not masquerade as verified result truth

Common symptoms:

- clicking an action from unresolved state rewrites `UPDATED`
- queued task state implies completed result truth
- selector switch leaves old execution logs or local context banners visible

Verify:

- no-op or rejected actions do not advance freshness
- queued/running state updates only the execution shell, not verified result surfaces
- selector-owned execution state resets or degrades correctly on same-instance route switches

Representative routes:

- `/strategy/backtest`
- `/data/indicator`

## 7. Enrichment And Auxiliary-Slice Truth

Meaning:

- secondary panels such as indicators, annotations, monitoring, or auxiliary stats must expose their own verification truth instead of collapsing into fake empty/integration copy

Common symptoms:

- failed enrichment slice falls back to `待接入真实...`
- verified auxiliary slice disappears on later refresh fail
- detail route keeps primary snapshot but shows generic empty copy for the failed enrichment slice

Verify:

- before any verified auxiliary snapshot exists, show explicit unavailable or pending truth
- after later failure, retain last verified auxiliary values with explicit stale copy
- do not let service/store normalization erase `success: false` semantics before the route sees them

Representative routes:

- `/detail/graphics/:symbol`
- `/dashboard`
- `/strategy/gpu`
