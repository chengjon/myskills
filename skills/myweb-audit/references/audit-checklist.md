# Audit Checklist

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

Use this checklist for every audited page.

## v2 Operator Note

Before starting a new batch:

- classify the defect with `route-truth-families.md`
- look for a representative precedent in `route-truth-casebook.md`
- use `route-truth-coverage-matrix.md` to choose the next canonical route or uncovered family
- follow `route-truth-operations.md` for batch throttling, stop conditions, and tool-linked closeout behavior

The checklist remains invariant-focused. Do not keep expanding it with one-off page history when the same rule already exists in the family taxonomy.

When the canonical coverage matrix no longer has meaningful `?` cells:

- stop mechanical route-by-route continuation
- refresh `secondary-view-inventory.md/json`
- choose the next backlog page from the heuristic shortlist
- use blank-layout mini batch mode for `/login`, `404`, and similar shell routes

## Blank-Layout Mini Batch Gate

For blank-layout routes, the default audit gate is intentionally smaller than the canonical business-route gate.

Validate only:

- layout isolation from the default ArtDeco application shell
- selector or prior-route contamination inside the same runtime
- absence of fake request, snapshot, or summary-strip fallback truth
- targeted type-check confirmation
- one or more basic E2E smoke proofs

Do not force blank-layout routes through unrelated family regressions unless the route now owns a shared owner or route-family defect that requires broader coverage.

## 1. Structure

Check whether the page has the expected regions and hierarchy:

- title/header area
- filter/search/control area
- content area
- action area
- table, chart, card, or detail panel
- pagination or load-more behavior when applicable
- modal/drawer/popup entry and close path when applicable

Flag issues when regions are missing, merged confusingly, visually collapsed, or structurally inconsistent with similar pages.

Also check:

- whether the page is composed from the appropriate existing page family structure and shared ArtDeco components, rather than drifting into one-off local component patterns
- whether the page follows the existing container width, page padding, workbench margin, and module-wrapper conventions used by its page family

## 2. Functional Interaction

Check whether the page can complete user tasks:

- buttons are clickable and correctly labeled
- links navigate to the expected route
- tabs switch content correctly
- custom tab buttons behave as non-submitting controls in a live browser and do not silently reload, re-enter, or stick on the default tab because of implicit submit semantics
- filters, sorting, and pagination work as intended
- forms accept input, validate, submit, reset, and cancel correctly
- dialogs open, close, and preserve or reset state correctly
- back/return flows are clear and usable

Flag issues when the user cannot complete the primary task or when interactions are misleading.

Also check interaction feedback:

- action buttons show appropriate loading or disabled feedback during async work
- success, warning, or failure feedback is visible when the action completes
- repeated clicks are not silently accepted when the action should be locked
- dialog submit and cancel actions provide clear result feedback

In `code-review-only` runs, also check:

- whether click handlers or row-click handlers are empty or no-op
- whether emitted events have a meaningful downstream consumer
- whether visible controls actually affect query params, filtered rows, tab content, or submitted payloads

## 3. Data / API / State

Check whether requests and rendered content are aligned:

- API URL and method are appropriate for the page action
- request trigger timing is correct
- request parameters match UI state
- visible content matches returned data
- loading state is visible and not misleading
- empty state is explicit and understandable
- error state is visible and actionable
- disabled/no-permission state is explicit
- extreme-data state does not break the layout or meaning

Flag issues when visible values disagree with API data, when states are missing, or when state transitions are unclear.

Also check refresh behavior:

- changing filters, sorting, tabs, or pagination triggers the correct data refresh path
- returning to the page does not leave obviously stale data without visual indication
- page-level refresh actions and auto-refresh indicators, if present, remain consistent with visible data
- when a routed workbench or detail page exposes a local selected-row context panel, entity chip, or similar selector-owned detail surface, a verified refresh that replaces the current row set must either rebind that surface to the refreshed selected row or clear it back to neutral baseline truth when the previously selected entity no longer exists
- fixed cadence or auto-refresh wording such as `每5分钟自动更新`, `auto refresh every N minutes`, or equivalent hero/footer copy is only shown when the active route actually owns a verified scheduler, push subscription, or equivalent refresh mechanism
- on multi-request pages, partial-success states explicitly identify which data surface failed while preserving the surfaces that did refresh successfully
- on single-request pages, a failed manual refresh after a successful load should preserve the last-known-good surface, keep that retained content visible, and show explicit stale-data messaging unless a hard reset is the approved product behavior
- result surfaces distinguish `not yet run` from `ran but returned no matches` instead of collapsing both into one empty-state message
- default hydrated datasets are not mislabeled as executed screening, query, report, or analysis results before the user triggers that workflow

Also check display-format correctness:

- dates, times, percentages, prices, quantities, and precision-sensitive numbers are rendered in a format that matches the data meaning
- rounding, truncation, separators, and units do not distort the returned data
- ordinal, rank, priority, sequence, and other discrete policy fields do not inherit exact-decimal formatting such as `1.00` or `2.00` when the live contract only proves whole-number ordering semantics
- count, inventory, tally, and label-only KPI cards do not render exact-decimal precision or change chrome unless the current routed payload exposes a real fractional value or comparison baseline
- when a routed KPI strip or page-local KPI wrapper passes absolute or count-only values into shared stat-card primitives, those cards explicitly suppress shared change chrome and preserve whole-count semantics as plain strings or honest integers rather than inherited `0.00`-style pseudo precision
- when a routed page composes a live summary slice from shared stat-card primitives, description-only cards that show only absolute totals plus supporting copy such as monthly totals, ratios, or explanatory subtitles explicitly disable shared change chrome; only cards backed by verified comparison baselines may render arrows, flat-change dots, `+0`, or `+0%`
- when a routed page has not yet completed its first successful live load, zero-initialized summary cards or KPI strips do not present `0.00`, `+0%`, or flat-change chrome as if they were verified live metrics; unresolved first-load numeric surfaces should degrade to explicit placeholder, loading-aware, or pending semantics until current payload evidence exists
- when a routed page requests a dedicated live stats or summary endpoint that already exposes multiple sibling count fields for a stat cluster, each visible sibling card either renders its verified contract field or explicitly degrades to placeholder truth such as `--`; one live count card must not sit beside label-only siblings or unresolved `0` fallbacks that masquerade as real zero-count truth
- when a routed page keeps an independent list, table, or detail surface visible after a dedicated sibling stats or summary slice fails on refresh, the failed stat cluster must either show explicit slice-local stale-state UX or degrade those sibling cards back to placeholder truth such as `--`; previously verified counts must not silently remain on screen as if the stats slice refreshed successfully
- when a transport-backed or route-local multi-slice workbench page already has a verified slice snapshot, a later failure of that same slice must not replace the visible slice with synthetic fallback values, boot defaults, `未知`, or local empty-state placeholders; if the page shows explicit stale or degraded-state messaging, the last verified slice values and slice-local freshness or provenance surfaces must remain pinned until a new verified slice snapshot exists
- when a routed dashboard or multi-slice workbench keeps an already verified primary slice visible after that same slice fails on a later refresh, the route must also degrade aggregate provenance meta and route-level alerts to explicit partial or degraded shell truth; retaining the slice alone is incomplete if `DATA`, `SYNC`, or equivalent aggregate labels still claim full success
- when one routed summary strip or stat cluster mixes multiple live or store-backed slices such as a verified collection list plus unresolved row-detail counts, each visible sibling card must derive truth from its own verified slice; one verified slice must not promote adjacent unresolved cards from `--` to faux `0` success
- when a routed page lets the user switch tabs, watchlists, portfolios, or other selector-scoped row sets, a later failure of the newly requested selector slice must not leave the previously verified rows visible under the new selector label; if the old rows are retained, the visible active selector must stay pinned to or explicitly revert to the last verified selector snapshot and pair that retained view with stale-refresh messaging
- when a routed page switches to a new selector or query entity inside the same mounted page instance, global route-local verification flags must not promote the previous selector's rows, counts, or request provenance into the new selector shell; until the new selector has its own verified snapshot, the route should degrade back to selector-local placeholder or unavailable truth such as `REQ_ID: N/A`, `COUNT: --`, and zero visible selector-owned rows
- when a routed page derives its active selector indirectly from another live slice such as the current primary watchlist, a later selector-discovery success must not let the previous selector's verified rows, counts, or request provenance remain visible under the newly derived selector if that selector's dependent row slice has never verified; the route must either stay pinned to the last verified selector chrome or degrade to selector-local placeholders for the newly derived selector
- when a routed page exposes selector- or query-scoped local action output such as generated snapshots, context banners, or hint chips, switching to a new selector or entity without its own verified local artifact must clear the previous selector's local-action copy; the route must either render the current selector's verified local artifact or degrade to neutral selector-local baseline copy plus optional context-switched messaging
- when a routed task or workbench page exposes selector- or query-owned execution surfaces such as progress panels, run logs, task-stage summaries, or similar execution-state shells, same-instance selector switches must not leave the previous selector's completed-stage copy, `100%`, or stale success logs visible under the new selector shell; the route must either restore the new selector's own verified execution snapshot or degrade back to neutral baseline execution truth such as `等待任务`, `0%`, and selector-safe log copy
- when any shared numeric surface on the routed primary page leaks fabricated precision or delta semantics, adjacent shared KPI strips, tables, or grids on the same route are audited in the same pass so sibling numeric truth defects do not remain hidden behind the first detected leak
- when a routed KPI strip already proves one shared-wrapper numeric leak such as `+0%`, flat-change dots, or `0.00`, adjacent cards on that same strip are reviewed as a single numeric cluster so count-only, percentage, and absolute cards do not retain mixed faux semantics after the first repair
- when a routed dashboard or workbench exposes aggregate provenance meta such as `DATA`, `SYNC`, `REQ`, or similar top-level route status labels, those labels are derived from the current truth of the primary routed slices and are not hardcoded to optimistic `REAL`, `READY`, or equivalent all-green semantics while any primary slice is still pending, degraded, or unavailable
- when a multi-slice routed dashboard or workbench retains a failed primary slice from the last verified snapshot, aggregate provenance meta and route-level alerting must also acknowledge that retained failure condition; preserved slice values paired with optimistic aggregate `READY` or `REAL` truth still count as a route-truth defect
- when a multi-request routed dashboard or workbench exposes a single top-level `REQ`, `REQ_ID`, `TIME`, or similar trace surface, that metadata must stay aligned with the verified primary-slice snapshot that currently defines the aggregate shell; later auxiliary, background, or non-primary request completions must not overwrite the visible aggregate request provenance
- when a canonical detail route mixes a primary snapshot request such as K-line, row, or time-series data with secondary enrichment requests such as indicators, annotations, or related metadata, hero/request surfaces such as `REQ`, `REQ_ID`, `TIME`, `POINTS`, or `ROWS` must stay aligned with the verified primary snapshot; secondary success must not create faux primary provenance before the first verified primary snapshot, and later failed primary refreshes must preserve the visible verified primary sample with stale-state messaging
- when a canonical detail route keeps a verified primary snapshot visible while a sibling enrichment slice such as indicators, annotations, or derived detail metrics fails, the enrichment surface must not collapse to generic empty-state truth; before any verified enrichment snapshot it should show explicit partial-failure copy that only the primary snapshot is verified, and after a later enrichment refresh failure it should retain the last verified enrichment values with explicit stale-enrichment messaging
- when the page's request wrapper or service layer resolves HTTP failures into `success: false` envelopes instead of throwing, the audited route still treats those envelopes as failure truth; an empty-looking render after `success: false` must be verified as an intentional degraded state rather than a swallowed request failure
- when a route-local service or helper normalizes live slice payloads before the page owner applies stale-state or unavailable-state logic, verify that the service preserves resolved `success: false` envelope truth instead of collapsing the failed slice into `[]`, `0`, or similar success-looking defaults before the route can classify the failure
- when a routed page is backed by a Pinia store, realtime store, or other wrapper that returns resolved payloads, at least one verification path must use a resolved `success: false` envelope that matches the real transport behavior; reject-only mocks are not sufficient evidence if production interceptors can resolve failure payloads as ordinary values
- when a shared Pinia store, collection extractor, or route mapper would otherwise collapse a resolved `success: false` payload into empty arrays, zero rows, or other success-looking secondary views, the routed page must classify that failure envelope before the transform boundary or use a page-local raw-contract path that preserves explicit unavailable semantics and verified request provenance
- when a routed page relies on local completion flags such as `hasLoaded` while store refreshes, collection extractors, or route mappers can throw on first-load failure, that failure path must still advance the route into a visible error shell instead of leaving it stuck between loading and empty semantics merely because the thrown failure prevented the completion flag from flipping
- when a routed page consumes shared-store request metadata such as `lastRequestId` or `lastProcessTime`, a failed manual refresh after prior success must preserve the last verified `REQ / REQ_ID / TIME`, count surfaces, and visible rows; the current routed shell must not switch to failed-refresh IDs, faux empty state, or unavailable semantics while it is still showing the older verified snapshot
- when a routed page exposes freshness metadata such as `UPDATED`, `LAST SYNCED`, or similar timestamps, failed manual refreshes must not advance that freshness surface unless a new verified snapshot is actually visible; if the route keeps the previous verified content on screen, the freshness timestamp must remain pinned to that same snapshot and pair with explicit stale-refresh copy
- when a routed runtime, monitoring, or workbench page summarizes multiple primary slices behind one visible freshness or runtime-status banner, that banner must not claim a generic full sync such as `最近同步` if only some primary slices verified on the current refresh; partial first-load or later partial-refresh paths must explicitly identify the missing, pending, or retained slice instead
- when a routed chart, trend, or other route-owned time-series slice already uses a live contract, unresolved first-load, first-load failure, and later stale-refresh states must use explicit sync-state copy such as `同步中`, `暂不可用`, or `当前仍显示上次成功同步的...`; generic capability-copy such as `待接入真实...` is only valid when the route truly lacks a live contract for that slice
- when a routed chart or time-series slice keeps the last verified chart visible after a later refresh fails, the visible note must surface both truths together: the current refresh failed and the previous verified snapshot is still being shown; retention-only copy without the failure truth is incomplete
- when a routed dashboard or workbench already owns real auxiliary live slices such as technical indicators, monitoring panels, annotations, or similar secondary surfaces, first-load failure on those slices must not fall back to fake capability copy such as `真实接口待接入...`; the slice should show explicit unavailable-plus-no-verified-snapshot truth until it verifies once
- when a routed auxiliary live slice previously verified and a later refresh fails, the route should retain the last verified auxiliary values and pair them with explicit stale or unavailable copy instead of reverting to placeholder rows, generic empty copy, or faux integration notes
- when a routed page offers manual actions that depend on verified route context such as a selected strategy, entity, or snapshot, rejected or no-op action paths from pending or failed-first-load state must not advance hero freshness metadata; warning banners and local logs may change, but `UPDATED`-style surfaces must stay on the last verified timestamp or explicit placeholder truth such as `--`
- when a routed task, workbench, or execution page starts or resumes a queued or running task before a new verified result or report snapshot exists, task rows, logs, progress panels, and warning banners may update immediately, but hero freshness metadata such as `UPDATED`, `LAST UPDATED`, or `LAST SYNCED` must stay pinned to the last verified snapshot or explicit placeholder truth such as `--`
- when a routed page renders a visible manual refresh control through a shared header, layout, or helper store, verify that bootstrap resets or summary clears do not silently detach the page-owned refresh callback; a visible `刷新数据` or equivalent control must still trigger a real second request cycle after the first verified snapshot exists
- when a routed page shows visible cadence or auto-refresh copy in a footer, hero, or helper surface, verify that the claimed interval is backed by an actual route-owned scheduler, push subscription, or equivalent refresh mechanism; if the route only updates on initial load, tab-local reload, explicit user action, or generic page-sync completion, the copy must degrade to honest non-cadence wording
- when a routed page, workbench, or route-local fallback builder seeds an initial shell before the first verified live snapshot exists, hero freshness metadata such as `UPDATED`, `LAST UPDATED`, or similar timestamps must remain on explicit placeholder truth such as `--`; local current time, mount time, or placeholder-builder timestamps must not be presented as if the page had already synced real data
- when a routed report table, result ledger, or similar row-level freshness surface shows fields such as `generatedAt`, `updatedAt`, `completed_at`, or `completedAt`, missing completion metadata must degrade that cell to explicit placeholder truth such as `--`; the page must not substitute the local current clock for row-level result freshness
- when a routed holdings, exposure, or portfolio summary grid shows a secondary `% change`, trend, or delta row beneath an absolute total card, that secondary delta must be backed by a dedicated live comparison-baseline field for that same card; aggregate PnL ratios, unrelated totals, or zero placeholders must not be re-labeled as total-assets change, day-change, or similar summary-delta truth
- stat cards, hero KPIs, and summary badges describe real currently available capability rather than a planned or permanently-zero placeholder feature
- when one routed page slice is backed by a real live API, adjacent alert lists, overview tables, or KPI cards on the same primary surface must not keep embedded placeholder numbers or messages; uncovered slices should degrade to explicit empty, unverified, or pending-integration states
- when a routed holdings page derives sector, concentration, or risk-ratio panels from live positions, each derived slice must use only fields actually present in the current payload; if sector or analytic inputs are missing, the page should degrade that slice to explicit pending or unverified copy instead of reusing embedded sample allocations or thresholds
- when a routed portfolio page presents rebalance, allocation, or other action-oriented strategy advice, the visible targets, gap math, and recommendation copy must be backed by current live target-weight or policy inputs; holdings-only payloads should degrade those strategy surfaces to explicit pending or unverified states instead of fabricating equal-weight or sample actions
- when a routed holdings or exposure page shows alert-style rows, stop-loss states, or risk-action buttons, those surfaces must be backed by current alert-policy inputs; if the page only has position or exposure truth, it should degrade to observation, review, or unverified states instead of presenting inferred heuristics as true alerts
- when a routed stop-loss, threshold, or distance-to-trigger page lacks real threshold inputs such as `stop_loss_price`, it must not present `triggered`, `critical`, `watching`, or other active-monitoring semantics; quote-only or watchlist-only surfaces should degrade to explicit pending-policy, unverified, or empty copy instead of showing threshold math placeholders as live monitoring
- when a routed signals page only returns current signal rows, per-row IDs, reasons, confidence, strength, and action buttons must be backed by current live fields; missing signal detail should degrade to explicit source-only, observation, or unverified states, and `HOLD` rows must remain non-executable instead of being relabeled as sell or other actionable rows
- when a routed signals page lacks verified execution or per-signal analytics inputs, execution history, win-loss stats, type-accuracy panels, and high-confidence or quality surfaces must not be synthesized from the current list alone; only direct live count or direction summaries may be derived locally, while unsupported analytics degrade to explicit pending or unverified copy
- when a canonical route wraps or reuses a shared page surface from another domain, the visible title, subtitle, hero labels, focus labels, and workflow descriptions must reflect the active route semantics; donor-route nouns or promises should not leak across routed surfaces
- if a reused surface still depends on a broader global feed and lacks true route-specific linkage, the route copy must explicitly say that the route-level association or filtering is pending instead of claiming a route-local workbench context the current payload does not prove
- when a routed runtime, terminal, or monitoring page consumes lightweight availability endpoints or demo runtime payloads, a successful `200` response alone must not upgrade the surface to live-session truth; no-session demo payloads should degrade session IDs, risk labels, KPI cards, and action guidance to explicit demo, pending-runtime, or `待接入` semantics
- when a routed GPU, runtime, or telemetry page shows exact thermals, clocks, fan speed, power, speedup, or benchmark metrics, each number must be backed by a real current payload field; missing or placeholder sensor fields should degrade to explicit `未校验`, `待接入`, or empty states instead of rendering fabricated `0°C`, `0x`, `-100%`, `0 MHz`, or similar exact values
- embedded example telemetry, monitor rows, or API performance samples are not left on the primary live data surface after real runtime requests fail
- if example telemetry is intentionally kept for structural preview, it is explicitly labeled non-live and visually separated from real runtime status
- visible request IDs, trace IDs, or correlation IDs come from real request-tracing metadata and are not locally fabricated placeholders that look like backend truth
- runtime-status rows, middleware badges, or operational labels do not remain `enabled`, `active`, or equivalent verified-running claims after the backing probe fails or reports an unhealthy state
- routed health, readiness, or similar probe surfaces do not treat a successful plain-object probe payload as unavailable merely because a generic request wrapper expects a `UnifiedResponse` envelope; successful probe payloads should be normalized before wrapper-level success checks
- endpoint-oriented config, registry, or catalog rows preserve endpoint-level identity when the live contract omits friendly `name` or `url` fields by using real descriptions or stable identifiers instead of collapsing multiple rows into repeated source-level placeholders or generic `N/A` endpoint cells
- on multi-tab routed pages, each visible default or user-facing tab slice uses its own live contract and tab-local provenance; one tab must not keep sample KPI cards, sample rows, or inherited sibling-tab `DATA` truth when the route already exposes a real contract for that slice
- if a routed tab has no real current contract for single-entity analysis, actions, or detail surfaces yet, the subtitle, panel copy, CTA, and feedback messaging must explicitly declare pending integration instead of promising a live actionable slice that the current route cannot fulfill

Also check state transitions:

- loading -> empty
- loading -> success
- loading -> error
- error -> retry -> success
- disabled/no-permission -> restored access when applicable

State changes should not leave stale content, broken placeholders, or misleading feedback behind.

For `live-audit` runs that use browser automation, also check verification provenance:

- if the first pass is blocked by the global readiness shell or shows an automation-fallback banner with an aborted or timing-related message, rerun the route in a fresh authenticated page, tab, or browser context before classifying the route as broken
- do not record a route defect from a same-tab `page.goto()` timeout alone when second-pass DOM and network evidence show the route actually loaded and rendered correctly
- if the page is using env-level mock routing or a module-local mock transport such as `mockApiClient`, note that browser network interception may be bypassed; verify refresh or error transitions with an in-page module override or equivalent controlled hook instead of treating missing intercepted requests as proof that the page never loaded data
- if `page.route()` or another page-scoped interception hook is bypassed by a second request or a worker/service-worker transport path, rerun the verification with browser-context interception and block service workers when safe before classifying the route's loading or error truth
- if test doubles or local harness adapters normalize payloads more permissively than the real runtime transport, record that verification gap and tighten the mock before treating unit green status as route-truth evidence
- if a store-backed route receives resolved `success: false` envelopes in real transport but local tests only exercise rejected promises, tighten the mock to cover resolved-envelope failure before accepting the route as verified

In `code-review-only` runs, also check:

- whether one failed request incorrectly clears other successfully loaded data surfaces
- whether related pages normalize equivalent API payload shapes consistently
- whether route meta, generated page config, and actual service calls disagree on the page's API truth
- whether stat cards or KPI labels claim capabilities that the current routed page does not actually expose

## 4. Visual Quality

Check visual structure and proportion:

- heading hierarchy is clear
- card/table/chart proportions are appropriate
- font sizes fit the page density
- spacing inside modules is consistent
- spacing between modules reflects hierarchy
- alignment is stable across columns and blocks
- buttons and controls use consistent heights and padding
- borders, dividers, and shadows are restrained and intentional

Flag issues when the page feels crowded, weakly grouped, visually noisy, or inconsistent with related pages.

Also check token compliance:

- typography, color, spacing, border, glow, and transition choices should follow existing project tokens or shared ArtDeco styles
- avoid local hardcoded values when an established token or shared component already exists

Also check breakpoint-level visual consistency:

- the page should preserve the same visual family across breakpoints
- font treatment, spacing rhythm, control density, and module grouping should remain coherent when the layout compresses

## 5. Responsive

Check at `1920`, `1440`, and `1280`.

Optional informational-only observation may be recorded at `1024`, but it is not a defect baseline for this project.

At required desktop breakpoints, check:

- no horizontal overflow unless explicitly justified
- no clipped text or controls
- no overlapping sections
- stacked layouts remain readable
- dense tables/charts degrade gracefully
- control groups remain usable on narrow widths

Flag issues when layout breaks, key actions disappear, or the page becomes hard to use at supported desktop widths.

In `code-review-only` runs, also flag architecture-level responsive redlines:

- mobile-width media queries that contradict the desktop-only support policy
- layout branches primarily designed for widths below the supported baseline

## 6. Accessibility

Check practical accessibility basics:

- text contrast is sufficient for reading
- focus state is visible
- disabled state is distinguishable
- clickable areas are large enough
- labels or contextual text exist for form controls
- icon-only buttons remain understandable

Flag issues when users cannot confidently identify, focus, read, or activate controls.

Also check keyboard operability:

- interactive controls can be reached in a sensible tab order
- Enter or Space works where appropriate
- keyboard focus is not lost inside dialogs, drawers, or tab flows

## 7. Design Consistency

Check whether the page matches established project patterns:

- same page family uses similar header and control structure
- cards, tables, filters, and actions follow existing component patterns
- tokens and style choices do not drift locally
- no isolated one-off styling without clear reason

Flag issues when a page visually diverges from its page family or reimplements common patterns inconsistently.

Also check shared-component consistency:

- the same shared button, card, badge, dialog, table, or status pattern should not drift in style or interaction across pages without a clear approved reason

## 8. Required States

Each page must be checked for:

- default
- loading
- empty
- error
- disabled/no-permission
- extreme-data

Do not stop at the default success path.

Note:
This project is a desktop-first workbench. Responsive checks are for layout stability and usability, not for promising a separate mobile product experience.
Widths below `1280` should not be treated as required responsive targets unless the user explicitly requests exploratory observation.
