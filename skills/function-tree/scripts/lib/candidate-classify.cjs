'use strict';

// FT_REVIEW MED: Source vocabulary translation layer.
//
// Existing in-code `source` labels emitted by the scanners:
//   pkg-root, readme-heading, entrypoint, changelog, untracked
//   (see scan-pkg-manifest.cjs:154..625)
//
// Proposed public vocabulary (per optimization plan §"Proposed Candidate Model"):
//   manifest, readme, ci, source, route, changelog, git-status, test, config,
//   dependency
//
// The plan promises backward compatibility. We deliver that by:
//   1. Keeping the existing source labels intact (no rename, no breaking change).
//   2. Adding a `source_category` field via normalizeCandidate() that maps each
//      legacy label to the public vocabulary.
//   3. Exposing normalizeSourceCategory(label) for promote-* filters that want
//      to consume the public vocabulary without a release-note migration.
//
// Migration policy: ADDITIVE. Old persisted candidate state in nodes.json keeps
// using whatever `source` it was saved with; newly-created candidates gain a
// `source_category` field that downstream tooling (ft diff, ft doc --report)
// reads preferentially.

const SOURCE_CATEGORY_MAP = {
  'pkg-root':       'manifest',
  'readme-heading': 'readme',
  'entrypoint':     'manifest',
  'changelog':      'changelog',
  'untracked':      'git-status',
  // Additional direct categories scanners may emit in the future:
  'manifest':       'manifest',
  'readme':         'readme',
  'ci':             'ci',
  'ci-job':         'ci',
  'source':         'source',
  'source-todo':    'source',
  'route':          'route',
  'api-route':      'route',
  'ui-route':       'route',
  'test':           'test',
  'config':         'config',
  'dependency':     'dependency',
};

const SOURCE_CATEGORY_VALUES = Array.from(new Set(Object.values(SOURCE_CATEGORY_MAP)));

function normalizeSourceCategory(label) {
  if (!label || typeof label !== 'string') return 'source';
  const mapped = SOURCE_CATEGORY_MAP[label.toLowerCase()];
  return mapped || 'source';
}

// Attach `source_category` + a stable `kind` to a candidate object, in place.
// Returns the same object so callers can chain.
function normalizeCandidate(candidate) {
  if (!candidate || typeof candidate !== 'object') return candidate;
  if (!candidate.source_category) {
    candidate.source_category = normalizeSourceCategory(candidate.source);
  }
  // Kind taxonomy (per plan §"Heading-kind vocabulary" + "TODO candidate cleanup"):
  //   product-feature | installation-doc | build-doc | api-doc | community-doc
  //   security-doc | ops-doc | platform-doc | config-doc | release-doc
  //   usage-example | source-todo | test-improvement | unknown-doc
  //
  // Existing scanners emit a free-form `type` field (e.g. 'source TODO',
  // 'test improvement', '声明实现'). We preserve that value untouched and
  // derive a normalized `kind` only when the candidate matches a known rule.
  // This keeps normalizeCandidate() idempotent on already-classified candidates.
  if (!candidate.kind) {
    candidate.kind = deriveKind(candidate);
  }
  return candidate;
}

function deriveKind(candidate) {
  const t = String(candidate.type || candidate.status || '').toLowerCase();
  if (t.includes('test')) return 'test-improvement';
  if (t.includes('todo')) return 'source-todo';
  // Document kinds are derived from README heading text — see classifyReadmeHeading()
  // in doc.cjs when the candidate flows through that path. normalizeCandidate()
  // leaves the document-kind assignment to that specialized classifier.
  return t || 'product-feature';
}

module.exports = {
  SOURCE_CATEGORY_MAP,
  SOURCE_CATEGORY_VALUES,
  normalizeSourceCategory,
  normalizeCandidate,
};
