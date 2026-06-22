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
module.exports = { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES };
