'use strict';

const fs = require('fs');
const path = require('path');
const STATUSES = new Set([
  'planning',
  'evidence-prepared',
  'decision-prepared',
  'authorization-prepared',
  'approved-for-implementation',
  'implementation-ready',
  'implementation-landed',
  'closeout-prepared',
  'closed',
  'blocked',
  'archived',
]);

const SOURCE_EDIT_STATUSES = new Set([
  'approved-for-implementation',
  'implementation-ready',
]);

const STEWARD_NODE_TYPES = new Set([
  'evidence',
  'decision',
  'authorization',
  'implementation',
  'closeout',
  'external',
]);

const NODE_TYPE_ALIASES = {
  feature: 'external',
  capability: 'external',
  epic: 'external',
  module: 'external',
  component: 'external',
  bug: 'external',
  task: 'decision',
  refactor: 'external',
  spike: 'evidence',
};

const STEWARD_BOUNDARIES = [
  {
    system: 'context-mode',
    primary_responsibility: 'Keep command output, searches, counts, and analysis searchable without flooding context',
    relationship: 'Feed concise analysis into steward evidence; never become durable repo truth',
  },
  {
    system: 'GitNexus',
    primary_responsibility: 'Code graph, symbol context, impact analysis, and staged change blast-radius checks',
    relationship: 'Required before source edits; steward tree records the risk result and next gate',
  },
  {
    system: 'GitHub PR / issue',
    primary_responsibility: 'Delivery review, merge decision, issue labels, discussion, and branch state',
    relationship: 'Steward tree records PR state and next action; it cannot merge or approve by itself',
  },
  {
    system: 'Graphiti',
    primary_responsibility: 'Cross-session memory digest of accepted decisions and milestone summaries',
    relationship: 'Steward tree records what should be remembered; Graphiti remains digest-only',
  },
  {
    system: 'OpenSpec',
    primary_responsibility: 'Proposal, capability delta, task checklist, approval, and archive authority',
    relationship: 'Steward tree routes architecture changes through OpenSpec and records approval state',
  },
  {
    system: 'Reports',
    primary_responsibility: 'Human-readable evidence, verification, closeout, and review notes',
    relationship: 'Steward tree indexes reports and distinguishes accepted fact from review input',
  },
  {
    system: 'Source / tests / runtime probes',
    primary_responsibility: 'Actual implementation truth',
    relationship: 'Steward tree must defer to current verification when report snapshots are stale',
  },
];

// Feature-candidate status vocabulary (auto-discovered by `ft init` / `ft doc`).
// These labels are the skill's global contract: every project gets the same
// labels regardless of language/stack, so user-facing commands can rely
// on them for grouping (Discovery Summary, suggest-nodes, etc.).
// The English forms are kept as aliases so non-Chinese callers can still match.
const FEATURE_STATUS = {
  DECLARED: '声明实现',        // README/CHANGELOG-claimed product feature
  CODE_PRESENT: '代码存在',    // has code-level evidence (route/model/dir), not in README
  UNVERIFIED: '待核验',        // single grep hit, single spec — needs human eyes
  PLANNED: '待实现',           // explicit TODO/roadmap reference
  // Fix-5 (FT_SKILL_AUDIT generic): lifecycle states every project has but the
  // original four-label vocabulary couldn't express. These are detected from
  // generic cross-language signals (Status: deprecated lines, @deprecated tags,
  // branch name patterns like *-deprecated / legacy-*, sunset/EOL commit
  // messages, LOCKED handbooks). They prevent the tree from mislabeling a
  // dead/archived capability as a live feature.
  DEPRECATED: '已废弃',        // sunset/EOL/deprecated — present in code but not maintained
  LOCKED: '已锁定',            // frozen at a specific version, no further changes expected
};
// Set of every "evidence-backed" status (everything except 待核验). Used by
// suggest-nodes to decide which candidates become node drafts vs. evidence.
const FEATURE_STATUS_VERIFIED = new Set([FEATURE_STATUS.DECLARED, FEATURE_STATUS.CODE_PRESENT, FEATURE_STATUS.PLANNED, FEATURE_STATUS.DEPRECATED, FEATURE_STATUS.LOCKED]);
const FEATURE_STATUS_ALIASES = {
  'declared-implemented': FEATURE_STATUS.DECLARED,
  'code-present': FEATURE_STATUS.CODE_PRESENT,
  unverified: FEATURE_STATUS.UNVERIFIED,
  planned: FEATURE_STATUS.PLANNED,
  deprecated: FEATURE_STATUS.DEPRECATED,
  sunset: FEATURE_STATUS.DEPRECATED,
  eol: FEATURE_STATUS.DEPRECATED,
  archived: FEATURE_STATUS.DEPRECATED,
  'end-of-life': FEATURE_STATUS.DEPRECATED,
  locked: FEATURE_STATUS.LOCKED,
  frozen: FEATURE_STATUS.LOCKED,
};

function normalizeFeatureStatus(s) {
  if (!s) return FEATURE_STATUS.UNVERIFIED;
  if (Object.values(FEATURE_STATUS).includes(s)) return s;
  return FEATURE_STATUS_ALIASES[s] || FEATURE_STATUS.UNVERIFIED;
}

function isDeclaredFeatureStatus(s) {
  return normalizeFeatureStatus(s) === FEATURE_STATUS.DECLARED;
}

function isVerifiedFeatureStatus(s) {
  return FEATURE_STATUS_VERIFIED.has(normalizeFeatureStatus(s));
}

module.exports = {
  STATUSES,
  SOURCE_EDIT_STATUSES,
  STEWARD_NODE_TYPES,
  NODE_TYPE_ALIASES,
  STEWARD_BOUNDARIES,
  FEATURE_STATUS,
  FEATURE_STATUS_VERIFIED,
  FEATURE_STATUS_ALIASES,
  normalizeFeatureStatus,
  isDeclaredFeatureStatus,
  isVerifiedFeatureStatus,
};
