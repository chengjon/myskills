# MyWeb Audit Changelog

> **权威来源声明**:
> 本文件是专题说明或状态说明，不是仓库共享规则的唯一事实来源。
> 若涉及仓库级共享规则、审批门禁或治理口径，请优先阅读 `architecture/STANDARDS.md`；若涉及执行入口、提案流程或当前实现事实，再分别参考根目录 `AGENTS.md`、根目录 `CLAUDE.md`、`openspec/AGENTS.md` 与当前代码。

## v2.0 - 2026-05-06

- Reorganized `myweb-audit` around stable route-truth defect families instead of continuing the page-by-page micro-version ladder in the main skill body
- Added `route-truth-families.md` as the canonical family taxonomy and promotion gate reference
- Added `route-truth-casebook.md` for representative repaired incidents grouped by defect family
- Added `route-truth-coverage-matrix.md` so future audit passes can be planned from canonical route coverage rather than changelog archaeology
- Declared that page-specific incidents should update the casebook and coverage matrix by default; only workflow changes, new stable families, or verification-method changes should promote the main skill structure

## v2.1 - 2026-05-07

- Added `route-truth-operations.md` as the governance reference for rule consolidation, iteration throttling, family-first batch planning, stop conditions, and tool-linked closeout flow
- Slimmed the main `SKILL.md` by replacing the inlined `v1.x` incident ladder with a stable archival pointer to `CHANGELOG.md`
- Aligned `batching-rules.md`, `audit-checklist.md`, and `ARTIFACT_QUICK_REFERENCE.md` with the `v2` operating model so future growth happens through family taxonomy, casebook, coverage matrix, and machine-validated artifacts instead of further main-skill version sprawl
- Aligned `route-inventory` and the fixed audit-role agent prompts with the same `v2` operations policy so route selection, precedent reuse, and repeated-family triage now follow the same throttled governance path as the main skill
- Added `scripts/dev/tools/validate-myweb-audit-skill.mjs` and `npm run validate:myweb-audit:skill` so the skill's own `SKILL / operations / casebook / matrix / agents` linkage has a repeatable self-check path instead of relying on manual inspection
- Added `npm run test:myweb-audit:skill`, a path-scoped GitHub workflow at `.github/workflows/myweb-audit-skill-governance.yml`, and validator checks for package/workflow tool linkage so the skill self-check now behaves like an actual automation gate rather than a local-only helper
- Added blank-layout mini batch rules, the secondary inventory phase, and a generated `secondary-view-inventory.md/json` snapshot so the audit campaign can cleanly transition from canonical matrix closure into heuristic backlog governance without reintroducing main-skill rule sprawl

## v1.71 - 2026-05-05

- Added selected-row context truth checks so canonical workbench and detail routes cannot keep an old selector-owned context panel, entity chip, or local detail summary visible after a verified refresh has already replaced the underlying row set with a different universe
- Required routes to either rebind that selected-row context to the refreshed row snapshot or clear it back to neutral baseline truth when the previously selected entity no longer exists in the current verified row set

## v1.70 - 2026-05-05

- Added selector-owned execution-state truth checks so routed task and workbench pages cannot let a previous selector's progress panel, completed-stage copy, or run logs remain visible after the same mounted route switches to a different selector without its own verified execution context
- Required same-instance selector or query switches to either restore the new selector's own verified execution snapshot or degrade execution surfaces back to neutral baseline truth such as `等待任务`, `0%`, and selector-safe log copy instead of leaking old `100%` or stale success logs

## v1.69 - 2026-05-05

- Added implicit selector-discovery truth checks so routed pages that derive their active entity from another live slice such as a primary watchlist cannot reuse the previous selector's verified rows, counts, or request provenance after that derived selector changes
- Required routes to either keep the visible selector chrome pinned to the last verified selector snapshot or degrade selector-owned surfaces to placeholder truth such as `REQ_ID: N/A`, `COUNT: --`, and zero rows until the newly derived selector has its own verified snapshot

## v1.68 - 2026-05-05

- Added selector-scoped verified-snapshot truth checks so query-scoped routed workbenches cannot treat an older verified snapshot as proof for a newly requested selector and thereby leak old rows, counts, or request provenance under the new selector chrome
- Required same-instance selector or query switches to either render the new selector's own verified snapshot or degrade back to selector-local placeholders or unavailable truth until that selector verifies

## v1.66 - 2026-05-05

- Added selector-scoped row-provenance truth checks so routed pages that switch between watchlists, tabs, portfolios, or similar selector-owned row sets cannot leave old verified rows visible under the newly requested selector when that later selector refresh fails
- Required routes that retain the previous verified selector rows after a failed selector refresh to keep or revert the visible selector chrome to the last verified selector snapshot and pair it with explicit stale-refresh messaging instead of a generic first-load failure shell

## v1.67 - 2026-05-05

- Added selector-local action truth checks so routed workbench and detail pages cannot leak a previous selector's generated snapshot hint, banner, or similar local artifact after the route query or selector switches to a different entity without its own verified local context
- Required routes to either rebind those local action surfaces to the current selector's verified local artifact or degrade to neutral selector-local baseline copy plus context-switched messaging instead of keeping old selector-local copy visible

## v1.65 - 2026-05-05

- Added auxiliary-slice sync-state truth checks so routed dashboards and workbenches cannot degrade real live secondary slices such as technical indicators or monitoring panels to fake `真实接口待接入...` capability copy when those slices fail before the first verified snapshot
- Required later auxiliary-slice refresh failures to retain the last verified slice values with explicit stale or unavailable copy, and required route-local services/helpers to preserve `success: false` or `ok: false` semantics so auxiliary slices do not silently collapse into empty-success placeholder rows

## v1.64 - 2026-05-05

- Added chart-slice sync-state truth checks so routed chart or time-series slices with real live contracts cannot fall back to generic `待接入`-style capability copy when the real state is unresolved first load, first-load failure, or stale refresh retention
- Required stale chart or trend retention copy to include both truths together: the current refresh is unavailable and the page is still showing the last verified snapshot; retention-only copy without the failure truth now counts as incomplete

## v1.63 - 2026-05-05

- Added service-normalizer envelope truth checks so route-local services and helpers cannot swallow resolved `success: false` envelopes into empty arrays, zero rows, or other success-looking defaults before the page owner applies stale-slice or unavailable-state logic
- Required later slice-refresh defects to be traced through the service/helper boundary when page-local retention appears correct in unit tests but the real route still degrades to empty-success rendering, and to fix that envelope gate upstream before re-verifying the routed stale-state UX

## v1.62 - 2026-05-05

- Added retained-primary-slice aggregate-truth checks so routed dashboards and multi-slice workbenches cannot keep an already verified primary slice visible after a later slice-refresh failure while still advertising optimistic aggregate `DATA`, `SYNC`, or equivalent route-level all-green semantics
- Required later primary-slice refresh failures to pair last-known-good slice retention with explicit aggregate degraded or partial-shell truth such as `MIXED`, `DEGRADED`, or route-level stale alerts until a new verified slice snapshot exists

## v1.61 - 2026-05-05

- Added queued-task freshness truth checks so routed task and workbench pages cannot let queued or running task-state updates stamp hero `UPDATED`, `LAST UPDATED`, or similar freshness surfaces before any new verified result or report snapshot exists
- Required task rows, banners, logs, and progress panels to update independently from hero freshness; route-level freshness must remain pinned to the last verified snapshot or explicit placeholder truth such as `--` until a new verified snapshot is actually synchronized

## v1.60 - 2026-05-05

- Added detail enrichment-slice partial-failure truth checks so canonical detail routes cannot collapse a failed sibling enrichment slice such as indicators, annotations, or derived detail metrics back into generic empty-state copy while a verified primary snapshot remains visible
- Required detail routes to distinguish first-load enrichment failure from stale-enrichment retention: before any verified enrichment snapshot they must say only the primary snapshot is verified, and after a later enrichment refresh failure they must keep the last verified enrichment values with explicit stale-enrichment messaging

## v1.59 - 2026-05-04

- Added partial-sync banner truth checks so routed runtime, monitoring, or workbench pages cannot describe a partial primary-slice refresh as a generic full `最近同步` route sync
- Required route-level freshness or runtime banners to explicitly degrade to partial-sync wording whenever one primary slice is still pending on first load or remains on a retained last-known-good snapshot after a later partial refresh

## v1.58 - 2026-05-04

- Added KPI-wrapper numeric-cluster truth checks so routed KPI strips that pass absolute or count-only values into shared stat-card primitives cannot leak default `+0%`, flat-change dots, or exact-decimal pseudo precision such as `0.00`
- Required audits to treat same-strip shared numeric leaks as one cluster: if one card leaks faux delta or precision semantics, adjacent KPI cards on that routed strip must be reviewed and repaired in the same pass

## v1.57 - 2026-05-04

- Added summary-card delta-chrome truth checks so routed live summary slices cannot let description-only cards inherit shared flat-change dots, arrows, `+0`, or `+0%` when the current contract proves only absolute values plus supporting copy
- Required routed pages to keep change chrome only on cards that have a verified comparison baseline; monthly totals, ratios, or explanatory summary cards must explicitly suppress shared delta chrome instead of masquerading as live movement surfaces

## v1.56 - 2026-05-04

- Added shared-refresh binding truth checks so routed pages cannot leave a visible manual refresh control bound to a cleared or null callback after bootstrap resets, summary clears, or first-load placeholder transitions
- Required route-local reset paths to preserve or immediately rebind the current page-owned refresh action whenever the route still renders a visible `刷新数据` or equivalent manual refresh control

## v1.55 - 2026-05-04

- Added slice-refresh fallback-retention truth checks so transport-backed or route-local multi-slice workbench pages cannot overwrite an already visible verified slice with synthetic fallback or boot defaults when only that slice fails on a later refresh
- Required later slice-refresh failures to preserve the last verified slice values and slice-local freshness or provenance surfaces whenever the page still shows explicit stale or degraded-state messaging; fallback zeros, `未知`, or empty-shell placeholders are only acceptable before the first verified slice snapshot exists

## v1.54 - 2026-05-04

- Added action-triggered freshness truth checks so routed pages cannot let rejected or no-op manual actions stamp hero `UPDATED`, `LAST UPDATED`, or similar freshness surfaces with the local current clock before any new verified snapshot exists
- Required unresolved-context action paths to preserve the last verified freshness value or explicit placeholder truth such as `--` even when warning banners, local logs, or other local-only UI feedback still update

## v1.53 - 2026-05-04

- Added stats-refresh stale-summary truth checks so routed pages cannot silently preserve old sibling stat-card counts after a dedicated live stats or summary slice fails on a later refresh
- Required routed pages without explicit slice-local stale-summary UX to degrade those failed sibling stat cards back to placeholder truth such as `--` while allowing unrelated verified rows or tables to remain visible

## v1.52 - 2026-05-04

- Added refresh-cadence truth checks so routed pages cannot claim a fixed polling or auto-refresh interval in visible copy unless the route actually owns a verified scheduler, push subscription, or equivalent refresh mechanism
- Required cadence-copy audits to degrade unsupported footer or hero wording to neutral route-sync semantics when the page only updates on initial load, tab-local reload, explicit user action, or generic page-sync completion

## v1.51 - 2026-05-04

- Added slice-local summary truth checks so routed stat clusters that mix multiple live or store-backed slices cannot let one verified slice promote adjacent unresolved sibling cards from placeholder truth to faux `0` success
- Added first-load completion truth checks so routed pages that depend on local `hasLoaded`-style flags still land in a visible error shell when store refreshes, collection extractors, or route mappers throw on the first load

## v1.50 - 2026-05-04

- Added sibling-stats contract truth checks so routed pages cannot request a live stats contract with multiple verified count fields and then render only one card while leaving adjacent stat cards as static labels, empty shells, or unresolved `0` fallbacks
- Required first-load or failed stats slices to degrade every affected sibling card to explicit placeholder truth such as `--` until a verified stats snapshot exists, instead of presenting partial live coverage as if missing cards were real zero counts

## v1.49 - 2026-05-04

- Added summary-delta truth checks so routed holdings or exposure pages cannot reuse aggregate profit ratios or zero placeholders as if they were verified secondary change baselines for unrelated cards such as total-assets change or day-change surfaces
- Required holdings-backed summary grids to degrade unsupported secondary delta rows to explicit pending or unverified copy whenever the live payload only proves absolute totals and does not expose dedicated comparison-baseline fields

## v1.48 - 2026-05-04

- Added row-level result freshness provenance checks so routed report tables and result ledgers cannot backfill missing `generatedAt`, `updatedAt`, `completed_at`, or similar completion metadata with the local current clock
- Required result/report verification to prove that valid rows without completion metadata degrade that timestamp cell to explicit placeholder truth such as `--` instead of masquerading as newly generated backend output

## v1.47 - 2026-05-04

- Added initial-freshness placeholder truth checks so routed pages and workbench fallback builders cannot seed hero `UPDATED`, `LAST UPDATED`, or similar freshness surfaces from the local current clock before the first verified live snapshot exists
- Required first-load failure verification to prove that freshness metadata degrades to explicit placeholder truth such as `--` until a verified live snapshot actually arrives, instead of masquerading as a just-synced page through mount-time or boot-time timestamps

## v1.46 - 2026-05-03

- Added refresh-timestamp provenance checks so routed pages cannot advance hero `UPDATED`, `LAST SYNCED`, or similar freshness metadata on failed manual refreshes while the page is still displaying the previous verified snapshot
- Required stale-refresh verification to prove that last-known-good content and its freshness timestamp remain aligned, with explicit warning copy instead of silently jumping the timestamp to the failed retry time or local current clock

## v1.45 - 2026-05-03

- Added detail-primary snapshot provenance checks so canonical detail routes cannot let secondary enrichment requests or failed-later primary refreshes overwrite hero `REQ / REQ_ID / TIME / POINTS / ROWS` surfaces that are supposed to describe the currently visible primary snapshot
- Required detail-route verification to cover unresolved first-load, first-load failure, and `success -> refresh fail` paths, proving that primary request metadata and visible samples degrade honestly before first verification and stay pinned to the last verified primary snapshot after later failures

## v1.44 - 2026-05-03

- Added aggregate-request provenance checks so multi-request dashboards and workbenches cannot let auxiliary or background requests overwrite a single top-level `REQ / REQ_ID / TIME` surface while the visible aggregate shell is still defined by older verified primary slices
- Required first-load-failure and auxiliary-success verification on aggregate routes to prove that top-level request metadata degrades to explicit unavailable placeholders until a new primary snapshot is actually verified

## v1.43 - 2026-05-02

- Added shared-store refresh snapshot-provenance checks so routed pages cannot bind hero `REQ / REQ_ID / TIME`, count meta, or visible rows directly to the latest shared-store refresh attempt when the routed shell is still showing an older verified snapshot
- Required manual-refresh audits on store-backed routes to cover `success -> refresh fail` paths, preserving the last verified request metadata and visible rows with stale-state messaging instead of leaking failed-refresh IDs or collapsing back to faux unavailable truth

## v1.42 - 2026-05-02

- Added store-transform envelope-erasure checks so routed pages cannot keep relying on shared Pinia-store transforms or collection extractors that strip `success: false` failure truth before the route can classify unavailable versus real empty-success state
- Required routed owners to preserve failure envelopes before the transform boundary or switch to page-local raw-contract fetching whenever the shared store path would otherwise collapse a failed slice into empty arrays, zero rows, or other success-looking secondary views

## v1.41 - 2026-05-01

- Added store-backed resolved-envelope parity checks so routed pages that consume Pinia or realtime-store refresh results cannot assume all first-load failures arrive as rejected promises
- Required verification mocks for store-backed routes to cover resolved `success: false` transport envelopes, preventing unit-green but browser-red regressions where real pages collapse failure payloads into empty-success rendering

## v1.40 - 2026-05-01

- Added aggregate-provenance truth checks so multi-request routed dashboards and workbenches cannot hardcode optimistic `DATA` or `SYNC` labels while primary routed slices are still pending, degraded, or unavailable
- Added resolved-error-envelope truth checks so routed pages and their verification mocks must treat `success: false` transport envelopes as failure truth instead of collapsing failed slices into empty-success rendering or false green aggregate meta

## v1.39 - 2026-04-30

- Added worker-transport interception handling so live audits cannot rely on `page.route()` alone when worker, service-worker, or replayed second-request paths bypass page-scoped browser hooks
- Required targeted browser verification to escalate to browser-context interception and block service workers when safe before treating a loading or error-state reproduction as route-truth evidence

## v1.38 - 2026-04-30

- Added unresolved first-load numeric truth checks so routed KPI or summary-card surfaces cannot present zero-initialized loading placeholders as live metric truth before the first successful payload arrives
- Required shared stat cards to degrade unresolved first-load numeric surfaces to explicit placeholder, loading-aware, or pending semantics and suppress fabricated `0.00`, `+0%`, and flat-change chrome until current payload evidence exists

## v1.37 - 2026-04-29

- Added numeric-coherence cluster handling so audits must expand from the first shared numeric renderer leak to adjacent KPI strips, tables, or grids on the same routed page instead of closing after a single faux precision or delta finding
- Required pages that combine shared stat cards with shared tables or grids to be reviewed as one numeric-truth surface cluster because fabricated count deltas and ordinal pseudo decimals frequently co-occur on the same route

## v1.36 - 2026-04-29

- Added ordinal-precision truth checks so routed tables cannot render discrete priority, rank, step, or sequence values with shared exact-decimal formatting when the live contract only proves whole-number ordering semantics
- Required routed pages to override generic numeric formatters for discrete policy fields instead of leaking fabricated `1.00` or `2.00` precision into primary live surfaces

## v1.35 - 2026-04-29

- Added unsupported-tab slice truth checks so routed tabs without a real single-entity or action contract must degrade subtitle, panel, CTA, and feedback copy to explicit pending-integration semantics instead of promising actionable analysis
- Added tab-button semantics checks so custom routed tab controls must stay non-submitting and live-browser operable; code-review or component-test green status is not enough if the real page still sticks on the default tab

## v1.34 - 2026-04-29

- Added tab-slice contract truth checks so multi-tab routed pages cannot leave a default or user-facing tab on embedded sample KPI cards, sample rows, or inherited sibling-tab provenance once that tab already has a real route-level contract
- Required source, registry, config, or similar tab-local surfaces to request and render from their own live contract or degrade honestly to explicit unavailable or pending semantics instead of keeping sample inventory truth

## v1.33 - 2026-04-29

- Added probe-envelope truth checks so routed health and readiness pages cannot discard successful plain-object probe payloads merely because the local wrapper expects a `UnifiedResponse` envelope
- Tightened audit-method guidance so unit and component test doubles must preserve real transport-envelope semantics instead of silently accepting payload shapes that production code would reject

## v1.32 - 2026-04-29

- Added count-kpi delta truth checks so routed count or label KPI cards cannot inherit shared stat-card delta chrome or exact-decimal precision when the current payload only proves plain counts or text
- Required plain count surfaces to suppress fabricated `+0%`, flat-change dots, arrows, and `2.00`-style pseudo precision unless a real delta or fractional baseline is actually available on the routed page

## v1.31 - 2026-04-29

- Added partial-runtime metric truth checks so routed GPU, runtime, or telemetry pages cannot coerce absent sensor or benchmark fields into exact zero-valued live metrics
- Required unsupported thermals, clocks, fan speed, power, speedup, and benchmark surfaces to degrade to explicit unverified or pending-benchmark semantics instead of rendering fabricated `0°C`, `0x`, `-100%`, `0 MHz`, or similar exact values

## v1.30 - 2026-04-28

- Added lightweight-runtime demo truth checks so routed runtime or terminal pages cannot present successful demo availability payloads as live trading-session, healthy-risk, or production market truth
- Required no-session demo payloads to degrade session IDs, KPI cards, risk badges, and action guidance to explicit demo or pending-runtime copy instead of borrowing credibility from `200` responses alone

## v1.29 - 2026-04-28

- Added threshold-policy truth checks so routed stop-loss or distance-to-trigger pages cannot treat watchlist-plus-quote payloads as active monitoring when real threshold inputs such as `stop_loss_price` are missing
- Required status copy, distance math, stop-price cells, and triggered or critical badges to degrade to explicit pending-policy or unverified states until the routed source exposes real threshold policy inputs

## v1.28 - 2026-04-28

- Added mock-transport verification handling so live audits must recognize when env-level mock routing or in-process clients such as `mockApiClient` bypass browser network interception entirely
- Required targeted browser verification to fall back to a documented in-page module override or equivalent controlled hook instead of misclassifying missing intercepted requests as route-failure evidence

## v1.27 - 2026-04-28

- Added donor-route semantic truth checks so canonical routes that reuse shared pages cannot leak titles, hero copy, focus labels, or workflow promises from another route family
- Required reused surfaces to degrade to explicit pending-integration wording whenever route-specific linkage or filtering is not actually implemented and the current payload only proves a broader shared feed

## v1.23 - 2026-04-28

- Added holdings-derived truth checks so routed portfolio pages cannot keep static sector mixes, concentration thresholds, or secondary risk-ratio numbers once the primary page surface is backed by a live positions payload
- Required derived holdings slices to compute only from fields actually present in the current payload, or degrade to explicit pending or unverified states when sector or higher-order analytics inputs are absent

## v1.26 - 2026-04-28

- Added signal-surface truth checks so routed signal pages cannot fabricate row IDs, trigger reasons, confidence, strength, or executable action labels when the current live payload only returns current signal rows
- Required `HOLD` or observation-only rows to remain non-executable and clarified that execution history, quality metrics, type accuracy, and similar analytics must degrade to explicit pending or unverified states until verified execution or per-signal detail exists

## v1.25 - 2026-04-28

- Added alert-policy truth checks so routed holdings or exposure pages cannot present locally inferred rows as real alerts, stop-loss states, or action recommendations when no alert-policy inputs are present
- Required exposure-only risk surfaces to degrade to explicit observation, review, or unverified states instead of impersonating the behavior of dedicated alert-engine routes

## v1.24 - 2026-04-28

- Added policy-derived action truth checks so routed portfolio and holdings pages cannot fabricate rebalance targets, action amounts, or recommendation copy from holdings-only payloads
- Required rebalance or allocation advice surfaces to degrade to explicit pending or unverified states until real target-weight or portfolio-constraint inputs are available from the live routed source

## v1.22 - 2026-04-28

- Added hybrid live-surface truth checks so routed pages cannot keep embedded alert copy, KPI numbers, or overview metrics on the same primary surface once one adjacent slice is already backed by real live API data
- Required uncovered slices on mixed live pages to degrade to explicit empty, unverified, or pending-integration states instead of borrowing credibility from nearby live rules, configs, or metadata

## v1.21 - 2026-04-28

- Added automation false-positive handling so live audits must rerun routes in a fresh authenticated page or context before filing defects triggered only by same-tab readiness-shell aborts or `page.goto()` timing artifacts
- Clarified that global readiness fallback banners seen only during automation navigation are environment evidence first, not route truth by default

## v1.20 - 2026-04-28

- Added payload-normalization truth checks so endpoint-oriented routed pages do not collapse multiple live endpoint rows into repeated source placeholders when `name` or `url` fields are absent
- Required endpoint-level config and registry surfaces to prefer live endpoint descriptions and stable identifiers such as `endpoint_name` over generic `N/A` endpoint cells when those are the real contract fields

## v1.19 - 2026-04-28

- Added runtime-status truth checks so routed pages cannot keep middleware or operational labels in `enabled` or `active` states after the real runtime probe fails
- Required live runtime status surfaces to degrade to explicit unverified or config-only states when no current runtime evidence exists

## v1.18 - 2026-04-27

- Added trace-truth checks so routed pages cannot present local synthetic `REQ_ID` placeholders as if they were backend tracing truth
- Required request-id surfaces to use real wrapper metadata or show an explicit unavailable state instead of fabricating correlation tokens

## v1.17 - 2026-04-27

- Added example-telemetry truth checks so routed monitor pages do not keep embedded sample rows on the same primary surface after real runtime requests fail
- Required explicit non-live labeling and segregation when example telemetry is intentionally retained for structure preview

## v1.16 - 2026-04-27

- Added workflow-truth audit checks so agents must distinguish `not yet run` result states from true `no matches` result states
- Added checks against default hydrated datasets being mislabeled as already executed screening, query, or analysis results

## v1.15 - 2026-04-27

- Tightened single-request stale-refresh checks so agents must verify that retained last-known-good content stays visible together with the warning state instead of being replaced by it
- Clarified that refresh-failure handling must be audited separately from first-load failure handling on routed workbench pages

## v1.14 - 2026-04-27

- Added explicit stale-refresh audit checks so manual refresh failures on single-request pages must be reviewed for last-known-good data retention and visible stale-data messaging

## v1.13 - 2026-04-27

- Added explicit partial-success audit checks for multi-request pages so agents must verify that failed sub-surfaces are called out instead of being silently masked by successful sibling data

## v1.12 - 2026-04-27

- Added explicit capability-truth audit checks so stat cards, summary KPIs, and status copy are reviewed for unsupported or placeholder-only product claims
- Tightened the `code-review-only` rules to flag permanently-zero metrics that still imply a real user workflow exists

## v1.11 - 2026-04-26

- Extended the artifact validator so `approval` payloads can be schema-checked directly and arrays of approval packages validate the same way as findings collections
- Added `validate:myweb-audit:approval` npm shortcuts in both root and frontend package manifests
- Promoted the approval artifact into the quick reference and validation helper command lists

## v1.10 - 2026-04-26

- Added `repair-approval-template.md` so the merged-findings-to-user-approval handoff now has a dedicated reusable reference instead of only inline examples
- Extended artifact conventions and example audit layout to support an optional `approvals/[batch-id]-repair-approval.yaml` artifact

## v1.9 - 2026-04-26

- Added a minimal `route-inventory` output example so `batch_suggestion`, `shared_owner_watchlist`, truth-mismatch notes, and priority notes are shown inline where scope setup work is performed
- Completed the "contract + inline example" coverage across all fixed `myweb-audit` agents

## v1.8 - 2026-04-26

- Added minimal raw-finding examples to all finding-producing audit agents so field shape, `primary_owner`, `dedupe_key`, and verification-surface expectations are shown inline where agents execute
- Re-aligned agent examples around current `data`-domain audit patterns to reduce drift between skill instructions and recent artifact truth

## v1.7 - 2026-04-26

- Added `Agent Normalization Minimums` to the main skill so merge inputs now require `issue_type`, `evidence.kind`, `repair_target.primary_owner`, `dedupe_key`, shared-impact hints, and verification-surface truth
- Tightened all finding-producing audit agents so their Output Contracts explicitly carry `issue_type`, `shared_impact_candidate`, `cross_page_impact`, and `dedupe_key`
- Tightened all finding-producing audit agents so `repair_target` must resolve to a concrete `primary_owner` instead of vague repair-area wording
- Tightened `route-inventory` so `shared-owner watchlist` entries must include concrete owner path, related routes, and watchlist basis
- Added operator guidance to prefer manifest-truth validation entrypoints during batch closeout and report writing

## v1.6 - 2026-04-25

- Added explicit dirty-worktree rules for isolating staged scope before using GitNexus staged detection as a batch verdict
- Added manifest fields for `staged_scope.verdict_origin` and notes so mixed staged observations cannot be mistaken for isolated batch proof
- Updated closeout and report templates to distinguish isolated staged verdicts from mixed staged observations
- Added example audit guidance for dirty-worktree closeout and observation-only fallback behavior
- Clarified artifact conventions so resumable outputs preserve GitNexus verdict provenance
- Added `manifest-schema.json` so batch manifests now have a machine-readable validation contract alongside the human template
- Added `scripts/dev/tools/validate-myweb-audit-artifacts.mjs` so manifest and raw findings artifacts can be schema-checked directly from the repo
- Added `merged-findings-schema.json` and validator support for merged findings so all core `myweb-audit` structured artifacts now have a machine validation path
- Added `--all` validation mode and npm script entrypoints so manifest/raw/merged artifacts can be checked together with one command
- Added `ARTIFACT_QUICK_REFERENCE.md` as a compact operator guide for lifecycle, contracts, and validation commands
- Added `--run-id` + `--batch-id` auto-resolution for aggregate validation so current batch artifacts can be checked without spelling out three file paths
- Added `--from-manifest` so aggregate validation can resolve raw and merged artifact paths directly from manifest truth

## v1.5 - 2026-04-25

- Added explicit merge and triage rules for deduplication, highest-severity consolidation, and shared-impact packaging
- Added repair-approval state-machine guidance and repair-target ownership rules to the main skill
- Added `shared-owner watchlist` responsibility to `route-inventory`
- Required all audit-role prompts to choose the smallest stable `repair_target` owner
- Re-aligned agent Output Contracts to always include `can_fix_frontend`
- Extended findings examples and machine schema with `repair_target.primary_owner`
- Re-aligned manifest and artifact conventions around manual or agent-assisted cross-session resumability
- Updated example audit flow to package approvals around merged repair decisions rather than raw findings
- Updated report templates to record `primary owner`, repair bucket, and approval accounting
- Updated batching rules to account for `shared-owner watchlist` and shared-impact spot-check closure

## v1.4 - 2026-04-25

- Added dedicated agent specs for all fixed audit roles
- Added environment prerequisites, execution surfaces, and environment fallback rules
- Added Quick Mode guidance for single-page checks
- Added explicit repair approval gate before fixes
- Aligned responsive checks to desktop-supported widths: `1920`, `1440`, `1280`
- Added structured manifest fields for execution surface, verification strategy, and repair approval
- Added shared-impact fields and `dedupe_key` guidance to the findings schema example
- Added formal `findings-schema.json` for machine validation
- Added closeout severity-resolution note and approval-record check
- Added artifact output conventions for file-based audit runs
