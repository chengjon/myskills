# Candidate Classification Reference

This reference documents how auto-discovered candidates are labeled before they
become planning nodes. Read it when:
- adding a new `promote-*` variant,
- changing a scanner that emits candidates,
- interpreting `ft diff` output that groups by `source_category` / `kind`, or
- deciding whether to widen the `kind` vocabulary.

The classification layer is **additive** — it attaches two normalized fields
(`source_category`, `kind`) on top of the existing in-code `source` label that
`promote-*` filters consume. Nothing about the existing `source` vocabulary is
renamed, removed, or migrated.

## Field vocabulary

### `source` (legacy, unchanged)

Values emitted by scanners today:

| Source label     | Emitted by                                | promote-* filter            |
|------------------|-------------------------------------------|-----------------------------|
| `pkg-root`       | scan-pkg-manifest.collectPkgRootSubpackages | `/ft:promote-pkgs`         |
| `readme-heading` | scan-pkg-manifest.collectReadmeHeadingCandidates | `/ft:promote-readme`  |
| `entrypoint`     | scan-pkg-manifest.collectManifestEntryPoints | `/ft:promote-entrypoints` |
| `changelog`      | scan-pkg-manifest.collectChangelogCandidates | `/ft:promote-changelog`   |
| `untracked`      | scan-pkg-manifest.collectWorktreeCandidates | `/ft:promote-untracked`   |

These labels are the **persisted contract**. Old `nodes.json` state, old test
fixtures, and any external automation reading `source` continue to work.

### `source_category` (normalized, public vocabulary)

A coarser grouping derived from `source` via `normalizeSourceCategory()`
in `scripts/lib/candidate-classify.cjs`. Used by `ft diff` and
`ft doc --report` so cross-source rollups are stable even when a new scanner
introduces a new label.

| `source` value     | `source_category` |
|--------------------|-------------------|
| `pkg-root`         | `manifest`        |
| `entrypoint`       | `manifest`        |
| `readme-heading`   | `readme`          |
| `changelog`        | `changelog`       |
| `untracked`        | `git-status`      |
| (any `ci:` / `ci-job:` gate) | `ci`     |
| (any source-route scanner)   | `route`  |
| (any source TODO scanner)    | `source` |
| (test improvement TODO)      | `test`   |
| (config entries)             | `config` |
| (dependency entries)         | `dependency` |
| unknown                      | `source` (fallback) |

### `kind` (normalized candidate kind)

A best-effort taxonomy applied by `normalizeCandidate()`. Existing scanners
emit a free-form `type` (e.g. `'source TODO'`, `'test improvement'`,
`'声明实现'`); we preserve that value untouched and derive `kind` only when
the candidate matches a known rule.

| `kind`             | Rule                                                  |
|--------------------|-------------------------------------------------------|
| `product-feature`  | default for non-TODO feature candidates               |
| `source-todo`      | candidate `type` mentions `todo`                      |
| `test-improvement` | candidate `type` mentions `test`                      |
| `installation-doc` | README heading classified as install/setup            |
| `build-doc`        | README heading classified as build/CI                 |
| `api-doc`          | README heading classified as API reference            |
| `community-doc`    | README heading classified as contributing/code-of-conduct |
| `security-doc`     | README heading classified as security policy          |
| `ops-doc`          | README heading classified as ops/deployment           |
| `platform-doc`     | (reserved)                                            |
| `config-doc`       | (reserved)                                            |
| `release-doc`      | (reserved)                                            |
| `usage-example`    | (reserved)                                            |
| `unknown-doc`      | (reserved)                                            |

Reserved kinds are declared in the vocabulary so `ft diff` columns are stable,
but no scanner emits them yet. Trimming the vocabulary vs. adding rules is a
project-level decision — see "Extending the vocabulary" below.

## TODO structured schema

In addition to `kind`, TODO candidates get four extra fields parsed from the
line text by `parseTodoStructure()` in `scan-project.cjs`:

| Field      | Derivation                                           |
|------------|------------------------------------------------------|
| `component`| Filename-ish prefix (e.g. `foo.bar:` or `in foo.bar`) |
| `action`   | Leading verb (`add`, `support`, `fix`, `refactor`, ...) |
| `object`   | Remainder of the line after `action`                 |
| `category` | Derived from `action`: `capability`, `maintenance`, `quality`, `unknown` |
| `todo_count_in_file` | Number of TODO entries collapsed into this candidate (existing per-file aggregation) |

These fields are additive. They do not replace the existing per-file aggregation
(one candidate per file, with `+N more in this file` in `evidence`).

## Migration policy

**Additive, non-breaking.**

- Old `nodes.json` files: keep their original `source` value. `source_category`
  and `kind` are attached at read time by `normalizeCandidate()` when the
  candidate is re-collected. No persisted migration step is required.
- Old persisted `source` labels (`pkg-root`, `readme-heading`, `entrypoint`,
  `changelog`, `untracked`) are NOT renamed. Future scanners may emit the new
  vocabulary directly (`manifest`, `readme`, `route`, ...); both shapes are
  accepted.
- `promote-*` commands continue to filter on the legacy `source` values they
  were originally written against. There is no plan to switch them to
  `source_category` filtering — that would be a breaking change.

## Extending the vocabulary

When you add a new scanner or candidate type:

1. Pick the existing `source` label that fits, or add a new label. Adding a
   new label does not break anything — `normalizeSourceCategory()` falls back
   to `'source'`.
2. If the new label should map to a specific `source_category`, add an entry
   to `SOURCE_CATEGORY_MAP` in `candidate-classify.cjs`. Otherwise leave it
   unmapped.
3. If the candidate has a structured `kind` (e.g. a new doc-kind), add a rule
   to `deriveKind()` and update the table above. Otherwise the default
   `'product-feature'` applies.
4. If you add a TODO-like scanner, call `parseTodoStructure()` on the title
   to populate the structured fields, and reuse the existing aggregation
   pattern (one candidate per file, with count).
5. Document any new vocabulary in this file under the appropriate table.

## Test fixtures

The existing test layout is a single file at `tests/ft-governance.test.cjs`.
There is no `tests/fixtures/<profile>/` directory today; future cross-profile
forward-testing (Phase 6 of the optimization plan) will introduce fixtures
under that path. Until then, classify and validate new vocabulary via the
existing inline test cases.
