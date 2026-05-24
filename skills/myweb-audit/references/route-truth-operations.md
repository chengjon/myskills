# Route-Truth Operations

Use this file as the governance reference for `myweb-audit v2+`.

Its purpose is to keep the skill strong at finding page defects while preventing:

- rule bloat
- version confusion
- incident-ledger drift in the main skill body
- diminishing returns from repeatedly rescanning already closed routes

The operating model is:

- rule consolidation
- iteration throttling
- batch governance
- tool linkage

## 1. Rule Consolidation

The main skill is a stable rulebook, not a running incident log.

Keep the main skill focused on:

- when to use `myweb-audit`
- stable route-truth families
- workflow and verification behavior
- artifact contract and closeout expectations

Do not use the main skill body for:

- page-by-page replay
- one-off route history
- micro-version notes for already known defect families

Use these files instead:

- `route-truth-families.md`: stable family taxonomy and promotion gate
- `route-truth-casebook.md`: representative incidents
- `route-truth-coverage-matrix.md`: next-pass planning truth
- `CHANGELOG.md`: chronological skill maintenance history

## 2. Iteration Throttling

Do not bump the main skill version for every new page defect.

Promote the main skill only when at least one of these is true:

- a genuinely new stable route-truth family appears
- the audit workflow changes in a reusable way
- the verification method changes in a reusable way
- a shared primitive, store, or service boundary exposes a new systematic truth-failure class

Otherwise:

- add the incident to `route-truth-casebook.md`
- update the affected route row in `route-truth-coverage-matrix.md`
- keep the main skill version unchanged

## 3. Batch Governance

Default planning unit: defect family first, route second.

Choose the next batch by:

1. finding unresolved or lightly scanned family cells in `route-truth-coverage-matrix.md`
2. preferring high-risk families:
   - `SEL`
   - `PART`
   - `PROV`
   - `ENR`
3. preferring canonical routes with:
   - primary navigation importance
   - shared owner reuse
   - dense user interaction
   - repeated incident precedent in the casebook

Default batch shape:

- one primary family per batch
- one to three tightly related canonical routes

Expand a batch beyond one route only when:

- routes share the same owner or shared primitive
- the same defect family is clearly repeatable across those routes
- one repair would otherwise leave sibling surfaces in a half-fixed state

Do not keep rescanning a route when:

- the applicable family cells are already `R` or `S`
- there is no meaningful code drift on that route or shared owner
- the newly observed symptom is just another instance already covered by the casebook

### 3A. Blank-Layout Mini Batches

When the active scope is a blank-layout route such as `/login`, `404`, or another non-business shell, use a lightweight mini batch instead of the full canonical business-route regression stack.

Blank-layout mini batches should verify only:

- layout isolation from the default ArtDeco application shell
- selector or prior-route contamination inside the same runtime
- absence of fake snapshot fallback truth such as request badges, summary strips, or stale shell chrome
- targeted type-check confirmation
- one or more basic E2E smoke proofs

Do not route blank-layout batches through the full multi-family regression matrix unless the route now owns a shared primitive or route-family defect that clearly requires it.

### 3B. Secondary Inventory And Heuristic Phase

When canonical route-family coverage no longer has meaningful `?` cells, stop route-by-route mechanical continuation and switch to the secondary inventory phase.

In this phase:

- generate or refresh `secondary-view-inventory.md` and `secondary-view-inventory.json`
- classify unrouted view assets into:
  - `候选待审`
  - `内嵌壳层`
  - `Demo废弃`
- keep the fixed output fields:
  - page path
  - layer
  - selector presence
  - stats-strip or indicator-card presence
  - shared composable reuse
  - priority mark

Use these four fixed heuristic signals:

- hero, meta, stats-strip, or aggregate indicator surfaces
- account, symbol, watchlist, tab, period, or similar selector switching
- hardcoded fallback literals such as `|| 'N/A'`, `|| 0`, or `|| []`
- reuse of shared composables or outer wrapper shells

Any `候选待审` asset that hits one or more heuristic signals belongs in the high-priority backlog.

`内嵌壳层` assets with one or more heuristic hits belong in the medium-priority embedded-shell backlog unless they are already covered by a repaired canonical owner route.

`Demo废弃` assets default to low priority unless a user explicitly requests recovery or preservation.

Before opening a repair batch from this backlog, run one more active-usage triage:

- prefer pages with a concrete import chain into a live wrapper, shell, or canonical owner
- promote low-heuristic embedded wrappers when they sit on a live import chain and still expose placeholder migration copy in front of already-existing canonical truth
- if a wrapper is low-heuristic but fronts a live parent import chain, promote it ahead of higher-scoring orphan pages rather than waiting for a later heuristic round
- downgrade orphan legacy workbenches that only self-reference their own composable or style layer
- keep note of candidates that are still high-risk by surface shape, but treat them as "preserve or retire" questions rather than immediate route-truth repairs
- if an embedded shell is still worth preserving but does not own an independent verified live-truth contract, demote it to pure canonical orchestration instead of inventing a secondary snapshot, store, request provenance badge, or freshness strip
- if a live embedded wrapper has no semantically matching canonical owner to reuse, degrade it to an honest static shell; do not force-map it to an unrelated live route just to preserve motion, and do not keep placeholder request, sync, or summary-strip semantics
- if a live parent shell imports multiple sibling panels, split them by owner match instead of batch-forcing one uniform repair: panels with semantically matching canonical owners should delegate directly, while unmatched siblings stay in backlog for later static-shell or owner-mapping decisions
- if an unrouted legacy page still carries hardcoded pseudo-live data but has no semantically matching canonical contract, do not try to "repair" the fake metrics in place; degrade the page to an honest static legacy shell and route users toward the closest canonical owners instead
- do not treat another orphan legacy page as a canonical owner just because its filename or domain wording looks similar; if neither side has a routed or otherwise active verified-truth contract, prefer the static-shell path
- if a same-domain sibling still depends on simulated transport, mock quote data, or explicit TODO APIs, keep that sibling in the unresolved backlog; shared vocabulary alone does not promote a legacy sibling into a canonical owner
- if an unrouted legacy page already has a semantically matching canonical owner, keep the legacy file as a thin orchestration wrapper over that canonical owner instead of preserving a forked pseudo-live shell; only degrade to a static shell when no canonical truth exists to delegate to
  - recent precedents include `Dashboard.vue -> ArtDecoDashboard.vue`, `Market.vue -> trade/Portfolio.vue`, `TradeManagement.vue -> ArtDecoTradingManagement.vue`, `IndicatorLibrary.vue -> data/Advanced.vue`, `strategy/StrategyList.vue -> strategy/List.vue`, `trading/History.vue -> trade/History.vue`, and `trading/Positions.vue -> artdeco-pages/trading-tabs/ArtDecoTradingPositions.vue`
  - treat the current routed entrypoint as a valid canonical owner even when that entrypoint is itself only a thin wrapper over a deeper page; secondary legacy wrappers should delegate to the route-level owner instead of creating yet another wrapper tier
- if an unrouted legacy page has no routed canonical owner but already wraps a single active live-truth component that owns the real API/query/result contract, keep that component and delete the outer pseudo-overview, fake statistics, tab chrome, and wrapper-local summary fetches instead of degrading the whole page to a static shell
  - recent precedent: `Wencai.vue -> components/market/WencaiPanel.vue`

## 4. Tool Linkage

Treat tooling as part of the audit method, not optional documentation.

Before a batch:

- classify the suspected issue with `route-truth-families.md`
- check precedent in `route-truth-casebook.md`
- pick route scope from `route-truth-coverage-matrix.md`
- if canonical matrix coverage is effectively complete, refresh `secondary-view-inventory.*` and choose the next backlog page from the generated heuristic shortlist instead of continuing mechanically through already closed canonical rows
- for blank-layout pages, mark the batch as a mini batch and keep verification scope aligned to layout isolation, selector contamination, no-snapshot fallback, type check, and basic smoke only

During a batch:

- keep scope truth in the manifest
- normalize raw findings before deduplication
- package merged findings for repair approval
- keep route-level evidence tied to the correct defect family

After a batch:

- validate artifacts from manifest truth
- update `route-truth-casebook.md` only if the incident adds representative value
- update `route-truth-coverage-matrix.md` for the repaired or scanned family cells
- record closeout once verification evidence is complete

When changing the skill itself:

- run `npm run test:myweb-audit:skill`
- run `npm run generate:myweb-audit:secondary-inventory`
- do not treat the refactor as closed until the skill self-check passes

### 4A. GitNexus Flow For The Secondary Backlog

Do not run `gitnexus_impact` against all 232 secondary assets just because they are present in the inventory.

Use this sequence:

1. generate the inventory and shortlist
2. choose the actual high-priority candidate batch
3. inspect the chosen owner route or wrapper
4. run `gitnexus_impact` only on the concrete symbol or owner file you are about to edit
5. if shared-owner risk is high, collapse the batch around the shared owner rather than pretending each secondary page is isolated

## 5. Evidence Discipline

Do not let documentation self-certify the route.

Preferred evidence stack:

- owner/unit regression for local logic truth
- routed proof for canonical route truth
- live browser proof when the route or defect family requires runtime confirmation

When runtime harness behavior is the real failure:

- record the harness lesson in `route-truth-casebook.md`
- do not promote the main skill unless the verification method itself had to change in a reusable way

## 6. Practical Maintenance Rules

When updating the skill set:

- shrink or stabilize the main skill before adding more rules
- move page-specific history downward into casebook or batch artifacts
- keep checklist language invariant-focused
- keep batching rules aligned with matrix-first planning
- prefer one governance note over repeating the same policy in multiple references

The success condition for `myweb-audit` is not “more versions”.

The success condition is:

- stable rules
- repeatable verification
- fast route selection
- high-yield batch repair
- low-noise long-term maintenance
