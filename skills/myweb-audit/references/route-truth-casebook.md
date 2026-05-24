# Route-Truth Casebook

This casebook groups representative repaired incidents by stable defect family.

Use it to:

- find the closest prior route before designing a new fix
- verify whether a new finding is another replay of an existing family
- keep page-specific history out of the main skill body

This file is a representative precedent library, not a full batch ledger.

Add entries only when they contribute reusable pattern value across routes, owners, or verification methods.

## Operational Precedents

- `/login` + `404`
  - blank-layout routes should be handled as lightweight mini batches that verify shell isolation, stale-route contamination, no snapshot fallback truth, targeted type checks, and basic smoke only; they should not be forced through the full canonical business-route family regression stack unless they now own a shared route-truth defect.
- `secondary inventory phase`
  - once the canonical route matrix no longer contains meaningful `?` cells, route selection should switch to the generated secondary inventory and fixed heuristic shortlist instead of continuing mechanically through already closed canonical rows.
  - a first-pass active-usage triage is still required after the heuristic shortlist is generated: many `候选待审` pages with selector and stats-strip hits can be orphaned legacy workbenches with no live import chain, while lower-ranked embedded shells may still be active inside a canonical owner.
- `ArtDecoTradingManagement.vue`
  - secondary embedded shells that do not own a verified live-truth contract should be demoted to pure orchestration: strip shell-level `REQ_ID/SYNC/summary` chrome, embed canonical `/trade/*` pages where verified truth already exists, and downgrade unsupported tabs to static explanatory shells instead of inventing a new snapshot/store.
- `ArtDecoTradingCenter.vue` active trading wrappers
  - low-heuristic embedded wrappers can still be high-priority repairs when a live parent shell imports them directly; once canonical `/trade/history` or `/trade/portfolio` truth already exists, placeholder migration panels in those active wrappers should be replaced with direct canonical embedding instead of preserving wrapper-local placeholder cards.
- `TradingDecisionCenter.vue` active decision wrappers
  - live parent shells may front decision panels that already have semantically matching canonical `/trade/portfolio` and `/trade/positions` owners; delegate those panels directly to canonical owners instead of preserving local pseudo-live cards or refresh controls, and leave only unmatched siblings for later static-shell or owner-mapping decisions.
- `TradingDecisionCenter.vue` unmatched decision-order panel
  - once the owner-matched decision panels have been delegated away, any remaining sibling such as `DecisionOrders.vue` still needs an explicit end state; if no semantically matching `/trade/orders` or `/trade/execution` owner exists, degrade that active panel to an honest static shell instead of preserving local search, submit, refresh, or order-history chrome.
- `ArtDecoTradingCenter.vue` active monitor wrappers
  - live parent shells may still front placeholder monitor wrappers even when canonical `/market/realtime` and `/risk/management` truth already exists; the wrapper should be reduced to pure delegation instead of carrying its own migration copy.
- `ArtDecoTradingCenter.vue` active market shells
  - when a live embedded wrapper has no semantically matching canonical owner, do not remap it to an unrelated market route just to keep motion on screen; replace the panel with an honest static shell that explicitly removes request, freshness, sync, and summary-strip semantics.
- `monitoring/MonitoringDashboard.vue`
  - an unrouted legacy page with hardcoded pseudo-live summary cards, alert panels, and table rows should not be preserved as a fake runtime dashboard just because it still looks high-value in the heuristic scan; if no semantically matching canonical monitoring contract exists, degrade it to an explicit static legacy shell and point users to the closest canonical routes instead.
- `system/DatabaseMonitor.vue`
  - a legacy system database-monitor page with hardcoded health counts, routing distribution, and migration-history summaries should not keep pseudo-live shell semantics when no verified canonical owner exists; degrade it to an honest static shell and point users to the closest verified `/system/health`, `/system/resources`, and `/system/data` routes instead.
- `system/PerformanceMonitor.vue`
  - a legacy system performance-monitor page with hardcoded Core Web Vitals, performance budgets, trend placeholders, and suggestion cards should not keep pseudo-live shell semantics when no verified canonical owner exists; degrade it to an honest static shell and point users to the closest verified `/system/health`, `/system/resources`, and `/system/api` routes instead.
- `TaskManagement.vue`
  - a legacy task-management workbench with local task stats, task tables, import/export controls, and history dialogs should not keep pseudo-live shell semantics when no semantically matching canonical owner exists; degrade it to an honest static shell and point users to the closest verified `/strategy/backtest`, `/trade/terminal`, and `/system/health` routes instead.
- `BacktestWizard.vue`
  - a legacy backtest wizard that only owns local template cards, parameter comparisons, faux KPI results, and a wrapper-local chart/composable chain should not be force-mapped onto the canonical `/strategy/backtest` route; when no one-to-one wizard owner exists, degrade the page to an honest static shell and retire the local pseudo-live composable instead of inventing a second backtest truth contract.
- `PortfolioManagement.vue`
  - a legacy portfolio-management workbench that locally mixes watchlists, portfolio scoring, alert summaries, stock-edit forms, and radar/detail dialogs should not be force-mapped onto any single canonical `/watchlist/*`, `/trade/*`, or `/risk/*` owner; when no one-to-one owner exists, degrade the page to an honest static shell and retire the local pseudo-live composable chain instead of inventing a combined portfolio truth contract.
- `Stocks.vue`
  - a legacy stocks workbench that locally mixes filter bars, stock-list rows, refresh actions, and detail-analysis affordances should not be force-mapped onto any single canonical `/watchlist/*`, `/market/*`, or `/detail/*` owner; when no one-to-one owner exists, degrade the page to an honest static shell instead of inventing a second stock-list truth contract.
- `AdvancedAnalysis.vue`
  - a legacy advanced-analysis workbench that locally mixes analysis configuration, batch-run controls, Kronos prediction, health cards, and result panels should not be force-mapped onto any single canonical `/data/*`, `/detail/*`, or `/strategy/*` owner; when no one-to-one owner exists, degrade the page to an honest static shell and retire its local page-only composable chain instead of inventing a second advanced-analysis truth contract.
- `advanced-analysis/*` child pages
  - once the parent legacy advanced-analysis workbench has been degraded to an honest static shell, orphan child pages must not keep local fallback values, default scores, indicator cards, trading signal counts, or investment advice; degrade those children to static explanatory shells unless a verified canonical child-page owner is explicitly established.
- `IndustryConceptAnalysis.vue`
  - a legacy industry-concept analysis workbench that locally mixes analysis tabs, selector filters, summary cards, charts, stock tables, and export actions should not be force-mapped onto any single canonical `/data/industry`, `/data/concept`, or `/data/fund-flow` owner; when no one-to-one owner exists, degrade the page to an honest static shell and retire its local page-only composable/style chain instead of inventing a second industry-concept truth contract.
- `market/CapitalFlow.vue` and `market/Concepts.vue`
  - market-domain legacy pages that still preserve duplicate refresh buttons, overview cards, ranking chrome, or detail shells should delegate directly to the semantically matching canonical `/data/fund-flow` and `/data/concept` owners when those routes already own the verified truth; do not keep a second market-facing pseudo-live shell in front of the data-domain owners.
- `market/Auction.vue` and `market/Etf.vue`
  - unresolved legacy market subpages should not be force-mapped to embedded sibling tabs or legacy market-data modules just because names overlap; if no one-to-one verified canonical auction or ETF owner exists, degrade the page to an honest static shell and remove local metrics, refresh controls, selector tables, rankings, and hardcoded sample rows.
- `MarketData.vue` and `market/MarketDataView.vue`
  - legacy market-data aggregate pages that combine fund-flow, ETF, chip-race, and LHB tabs should not keep a second aggregate truth surface when those semantics belong to split canonical `/market/*` and `/data/*` routes; if no verified aggregate owner exists, degrade the aggregate to an honest static shell instead of mounting old market widgets with component-local requests.
- `Dashboard.vue`
  - an unrouted legacy page with a semantically matching canonical dashboard owner should not keep a forked pseudo-live shell; keep it as a thin orchestration wrapper over the canonical owner instead of preserving duplicate summary cards, heat panels, or tables.
- `Market.vue`
  - an unrouted legacy page whose visible semantics are really portfolio assets, positions, and trade history should delegate to the canonical `/trade/portfolio` owner instead of preserving a forked pseudo-live "market overview" shell with local asset stats and faux refresh controls.
- `TradeManagement.vue`
  - an unrouted legacy page whose visible semantics are already covered by the active trading orchestration shell should delegate to `ArtDecoTradingManagement.vue` instead of preserving its own pseudo-live positions, trade-history, and statistics workbench shell.
- `IndicatorLibrary.vue`
  - an unrouted legacy page whose visible semantics are really indicator registry, filtering, and indicator detail should delegate to the canonical `/data/indicator` owner instead of preserving a forked pseudo-live indicator library shell with local totals and filter chrome.
- `strategy/StrategyList.vue`
  - a nested legacy strategy-list page that still renders its own pseudo-live definition grid should delegate to the canonical strategy-repo owner `views/strategy/List.vue` instead of preserving local refresh, filter, and run-results shell semantics.
- `trading/History.vue` and `trading/Positions.vue`
  - nested legacy placeholder pages should not preserve `Coming Soon` shells once a semantically matching canonical trade owner exists; delegate to the current route entrypoint even when that route entrypoint is itself a thin wrapper over a deeper canonical owner, instead of introducing a new placeholder variant or a secondary snapshot.
- `trading/Orders.vue` and `trading/Execution.vue`
  - nested legacy trading pages that still show `Coming Soon` but have no semantically matching routed or otherwise active canonical owner should degrade to honest static shells rather than being force-mapped onto nearby `/trade/*` routes with different semantics.
- `Settings.vue`
  - an unrouted legacy page with a semantically matching canonical system-config owner should not keep a forked pseudo-live settings shell; keep it as a thin orchestration wrapper over the canonical `/system/config` owner instead of preserving local forms, faux database rows, or faux log-summary cards.
- `EnhancedRiskMonitor.vue`
  - an unrouted legacy page with a semantically matching canonical `/risk/management` owner should not keep faux stop-loss, alert, websocket, GPU, or tabbed risk-control shell semantics; keep it as a thin orchestration wrapper over the canonical owner instead of preserving a second pseudo-live risk workbench.
- `Analysis.vue`
  - an unrouted legacy analysis workbench with local mock form state, signal summaries, and export surfaces should not preserve those pseudo-live semantics when no semantically matching canonical owner exists; degrade it to an honest static shell and point users to the closest canonical analysis routes.
- `TechnicalAnalysis.vue`
  - a top-level legacy technical-analysis workbench should not delegate to another orphan legacy page just because the names look similar; if there is no routed or otherwise active canonical owner, degrade it to an honest static shell and point users to the nearest verified chart, market-technical, and indicator routes.
- `technical/TechnicalAnalysis.vue`
  - a nested legacy technical-analysis workbench with local indicator totals, signal tables, chart chrome, and batch-calculation controls should follow the same honest static-shell path when the only similarly named alternatives are also orphaned legacy assets; sibling legacy files are not a canonical truth source.
- `StockDetail.vue`
  - a legacy stock-detail page that blends quote, chart, technical, news, and trade-operation semantics without a one-to-one canonical owner should not force delegation to any single route; degrade it to an honest static shell and hand users off to the split canonical detail and trade routes instead.
- `TdxMarket.vue`
  - a legacy TDX market page must not delegate to a same-domain sibling when that sibling still relies on simulated transport, mock quote data, or TODO APIs; unresolved legacy siblings are not canonical truth sources, so the repair should fall back to an honest static shell.
- `market/Tdx.vue`
  - a nested legacy TDX data-interface page must not keep simulated connection status, random response/session metrics, mock quote rows, hardcoded server metadata, or K-line loading controls when no verified canonical TDX owner exists; degrade it to an honest static shell and remove page-local pseudo-live composables/styles once their only consumer is retired.
- `monitor.vue`
  - a legacy system monitor page must not keep page-local refresh controls, generated service status, history rows, or hardcoded endpoint metadata when no verified one-to-one canonical monitoring owner exists; degrade it to an honest static shell and remove page-local pseudo-live composables/styles once their only consumer is retired.
- `RealTimeMonitor.vue`
  - a legacy realtime/SSE monitor page must not keep SSE demo widget mounting, local status requests, push-test actions, or fallback connection counts when no verified one-to-one canonical SSE owner exists; degrade it to an honest static shell and remove page-local orphan styles once the live demo surface is retired.
- `StockAnalysisDemo.vue` / `stock-analysis/*Tab.vue`
  - a legacy stock-analysis demo shell must not keep selector-driven child tabs, local TDX parsing examples, strategy snippets, RQAlpha metrics, realtime ticker cards, or integration-status claims when no verified aggregate stock-analysis owner exists; degrade the parent to an honest static shell and remove page-local orphan tab components/styles once their only consumer is retired.
- `strategy/BatchScan.vue` / `ResultsQuery.vue` / `SingleRun.vue` / `StatsAnalysis.vue`
  - unrouted legacy strategy workbench pages must not keep selector-owned execution, result query/export, auto-refresh, or aggregate metric truth when their only API facade is deprecated; degrade them to honest static shells and remove page-local orphan styles instead of reviving retired execution contracts.
- `trading-decision/DecisionHeader.vue`
  - a secondary header must not keep local quick actions, panel selector state, custom refresh events, timers, or stale component imports after its sibling panels have canonical/static owners; degrade it to an honest static shell and hand users back to verified `/trade/*` routes.
- `advanced-analysis/*View.vue`
  - orphan advanced-analysis child pages must not keep placeholder module descriptions, prop-fed result summaries, aggregate scoring, local metric extraction, or Element Plus status tags when the parent workbench has already been degraded to an honest static shell; keep all children under one static-shell regression so partial child coverage does not leave residual pseudo-analysis truth.
- `settings/*` / `TestPage.vue`
  - unrouted settings child placeholders and orphan test pages must not keep Element Plus placeholder alerts, local test buttons/cards, or console side effects when canonical `/system/config` and `/dashboard` owners already exist; degrade them to honest static shells and guard against placeholder/test UI returning.
- `Wencai.vue`
  - an unrouted legacy page may still have a semantically matching live truth component even when there is no routed canonical owner; in that case keep the inner live component, but delete the outer pseudo-overview, fake statistics, tab chrome, and wrapper-local fetch summary so the page becomes a thin wrapper over the real query/result contract instead of duplicating truth.
- `system/Architecture.vue`
  - a legacy architecture dashboard that only exposes hardcoded migration progress, topology counts, and stack summaries should not preserve those pseudo-live metrics when no verified canonical owner exists; degrade it to an honest static shell and hand users back to verified `/system/*` routes.

## Numeric Truth

- `/data/industry`
  - KPI strip and rank column leaked `10.00`, `1.00`, and shared `+0%` semantics for count-only and ordinal surfaces.
- `/trade/portfolio`
  - first-load portfolio summary cards and rebalance surfaces leaked faux zero balances and synthetic policy truth before any verified snapshot existed; the thin `/risk/pnl` wrapper inherited the same owner behavior.
- `/market/lhb`
  - count card and rank column leaked exact-decimal pseudo precision on list-size and ranking surfaces.
- `/strategy/backtest`
  - shared KPI wrapper inherited `+0%`, flat dots, and `0.00` precision until the route-local wrapper forced plain-string KPI truth.
- `/dashboard`
  - description-only capital-flow summary cards inherited shared stat-card delta chrome even though the live slice exposed no comparison baseline for them.
- `/system/config`
  - the default `数据源` tab surfaced `0 / 0` source counts before any verified config snapshot existed; unresolved first-load source stats had to degrade to `-- / --` while keeping static write-capability truth visible.
- `/system/api`
  - the observability deck surfaced `N/A / N/A / 3` for service name, version, and middleware count before any verified system probe snapshot existed; unresolved first-load labels had to degrade to `-- / -- / --` while keeping route-level status at `UNKNOWN`.
- `/system/data`
  - the top-level data-source stats strip surfaced `0 / 0` before any verified config snapshot existed; unresolved first-load count cards had to degrade to `-- / --` while keeping static write-capability truth visible.
- `/system/resources`
  - the resource observatory surfaced `0 / 0 / 0` process, alert, and dependency counts before any verified resource snapshot existed; unresolved first-load count cards and section headers had to degrade to `-- / -- / --` while keeping the route shell visible.
  - the same pending shell also surfaced `NODE: N/A` before any verified resource snapshot existed; unresolved first-load node labels had to degrade to `--` until the first real node snapshot landed.
- `/system/health`
  - the health matrix surfaced `N/A / N/A / 3` for service name, version, and middleware count before any verified probe snapshot existed; unresolved first-load labels had to degrade to `-- / -- / --` while keeping route-level status at `UNKNOWN`.
- `/trade/reconciliation`
  - same-instance account switches leaked the previous account's local import metadata into a new unresolved shell, so hero `IMPORT_BATCH / ROWS` looked like current-account truth until the account-scoped import context was cleared.
  - same-instance account switches also leaked the previous account's verified request provenance and freshness into a newly selected unresolved shell, so hero `REQ_ID / UPDATED` had to be bound to the current visible reconciliation snapshot and degrade to `N/A / --` whenever the new account had not yet produced its own verified state.
  - same-instance account switches also leaked faux zero reconciliation result metrics into a newly selected unresolved shell, so `已匹配 / 差异 / 缺少券商记录` had to degrade to `-- / -- / --` until the current account produced its own verified result snapshot.

## Request-Provenance Truth

- `/market/realtime`
  - later refresh failure overwrote visible `TRACE_ID` until the route pinned hero provenance to the last verified preset snapshot.
- `/trade/portfolio`
  - first-load failures and later refresh failures both leaked the latest request id into the hero until provenance was pinned to the currently visible verified portfolio snapshot; `/risk/pnl` inherits the same owner truth through the wrapper route.
- `/data/fund-flow`
  - hero `REQ` and ranking summary followed the latest request instead of the currently visible verified ranking rows.
- `/system/api`
  - top-level `REQ_ID` followed the latest `useArtDecoApi` transport attempt instead of the visible verified probe snapshot.
- `/system/resources`
  - unresolved first-load resource polling needed to keep `REQ_ID: N/A` until the first verified snapshot existed, instead of implying current node provenance from a pending transport.
- `/market/lhb`
  - failed refresh request IDs leaked into the hero while the old verified list remained visible.
- `/risk/news`
  - first-load failures needed to preserve `REQ_ID: N/A`, while later refresh failures needed to retain the last verified request ID and visible announcement rows.
  - browser proof for `/api/announcement/list` needed a broad `context.route("**/api/announcement/list**")`; page-level overrides and exact query matchers could miss the worker/context request path and create false provenance failures.
- `/data/concept`
  - manual-refresh provenance proofs needed to gate `refreshOnly` failures on "has already served a verified concept snapshot" instead of naive request-count thresholds; otherwise the harness could fail the first visible shell before the user-triggered refresh path even started.
- `Phase 4 system/detail routed harness`
  - when a suite already installs broad `context.route(...)` defaults, later proof-specific overrides for `/api/health`, `/api/v1/data-sources/config/`, or announcement stats must stay at context scope and the suite should block service workers; otherwise the runtime can bypass `page.route(...)` and create false request-provenance or selector-pending regressions.

## Freshness Truth

- `/data/indicator`
  - failed refresh advanced `UPDATED` to the current time while the old analysis workspace remained visible.
- `/strategy/backtest`
  - queued/running task-state and rejected actions advanced hero freshness before any new verified report or result existed.
- `/risk/management`
  - initial shell seeded `最后一次更新` before any verified live snapshot.
- `/system/resources`
  - the resource observatory had to keep `UPDATED: N/A` until the first verified snapshot existed; the pending resource poll could not surface fake current freshness.

## Partial-Slice Truth

- `/dashboard`
  - later industry refresh failure needed to preserve the verified industry slice while degrading aggregate `DATA/SYNC` to `MIXED/DEGRADED`.
- `/risk/overview`
  - `rules` and `alerts` needed independent verified snapshots so one failed slice would not collapse the whole route into `no verified overview`.
- `/risk/alerts`
  - `alert-rules` and `alerts` needed separate verified retention so the rules table could remain visible through alert-record failures.
- `/detail/news/:symbol`
  - dedicated stats slice failures needed to degrade only the sibling stat cluster while the primary announcement rows remained visible.
- `/trade/terminal`
  - later single-slice refresh failures needed route-level feedback to degrade from global `数据已刷新` success toast to explicit partial-refresh warning text that names the failed slice.
  - browser proof for runtime slice failures needed `serviceWorkers: block`; otherwise the runtime demo worker could bypass `page.route()` and reintroduce false lightweight shells during verification.

## Selector-Scoped Snapshot Truth

- `/watchlist/manage`
  - switching to a new watchlist while the new stocks slice was unresolved leaked old rows into the new active tab shell.
- `/strategy/signals`
  - same-instance `strategyId` switch leaked old rows, `COUNT`, and `REQ_ID` under the new selector.
- `/strategy/parameters`
  - same-instance `strategyId` switch leaked old parameter cards and hero process metadata.
- `/strategy/opt`
  - same-instance `strategyId` switch leaked previous optimization rows, request metadata, and candidate hints.
- `/market/lhb`
  - switching the trade-date selector leaked rows and request provenance from the previously verified date.
- `/market/realtime`
  - switching the preset leaked old quote rows and sample counts into the new preset shell.
- `/detail/news/:symbol`
  - symbol switches leaked old announcement rows, stats, or auxiliary rule/trigger rows into the new detail shell.
- `/detail/graphics/:symbol`
  - symbol and `period` switches leaked old primary/enrichment snapshots into the new chart shell.
- `/trade/reconciliation`
  - same-instance `accountId` switches leaked old statement rows, imported reconciliation result rows, and local import-batch context into a newly selected unresolved account shell.

## Local-Action And Execution Truth

- `/strategy/backtest`
  - local generated hints, progress panels, run logs, tasks, KPI summaries, and report tables all required `strategyId`-scoped execution truth instead of route-global caches.
- `/data/indicator`
  - `runScreening()` from failed-first-load state could not be allowed to synthesize a fresh verified result shell.
- `trade-management/components/*`
  - orphan child components that are no longer imported by the active orchestration shell must not preserve independent trading execution truth; local portfolio fixtures, direct trade API calls, fallback position rows, chart-generated statistics, history pagination, and order submission forms should degrade to static shells with canonical `/trade/*` handoff links.
- `stocks/{Activity,Concept,Industry,Watchlist}.vue`
  - orphan stocks pages with no route owner or importing shell must not preserve mock selector snapshots, random refresh mutation, favorite/remove actions, or hardcoded market rows; degrade to static shells and hand off to canonical `/trade/history`, `/data/concept`, `/data/industry`, or `/watchlist/manage`.
- `stocks/Portfolio.vue`
  - orphan portfolio pages with no route owner or importing shell must not preserve mock portfolio metrics, example positions, random refresh mutation, add-position actions, or performance chart placeholders; degrade to a static shell and hand off to canonical `/trade/portfolio`.
- `risk/{Portfolio,Positions}.vue`
  - orphan risk child pages with no route owner or importing shell must not preserve standalone Phase roadmap placeholders as if they were independent risk entries; degrade to static shells and hand off to canonical `/risk/management` or `/risk/position`.
- `artdeco-pages/ArtDecoTechnicalAnalysis.vue`
  - orphan ArtDeco pages with no route owner or importing shell must not mix partial service calls with random trend/equity series, local GPU/load badges, or delayed mock backtest stats; degrade to a static shell and hand off to canonical `/market/technical`, `/data/indicator`, or `/strategy/backtest`.

## Enrichment And Auxiliary-Slice Truth

- `/detail/graphics/:symbol`
  - primary K-line snapshot and technical-indicators slice needed independent truth: first-load indicator failure shows primary-only truth, later refresh failure retains the last verified enrichment values with stale copy.
- `/dashboard`
  - auxiliary slices such as technical indicators and monitoring needed real unavailable/stale semantics instead of fake `真实接口待接入...`.
- `/strategy/gpu`
  - route banner had to distinguish full success from partial sync when only one of the primary GPU/runtime slices verified.
