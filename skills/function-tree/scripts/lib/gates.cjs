'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function activeGateFromNode(program, node) {
  return {
    program,
    id: node.id,
    title: node.title || node.id,
    node_type: stewardTypeFor(node),
    owner_lane: node.owner_lane || program,
    parent: node.parent || '',
    status: node.status || 'planning',
    source_edits_authorized: node.source_edits_authorized === true,
    current_blocker: node.blocker_reason || '',
    next_allowed: node.next_gate || nextGateFor(node.status),
    function_tree_ref: node.function_tree_ref || '',
    freshness: node.freshness || 'current-head',
    allowed_paths: list(node.allowed_paths),
    forbidden_paths: list(node.forbidden_paths),
    updated_at: node.updated_at || new Date().toISOString(),
  };
}

function upsertActiveGate(root, program, node) {
  const activePath = path.join(root, '.governance', 'active-gates.json');
  const active = loadActiveGates(root);
  active.schema_version = active.schema_version || 1;
  active.updated_at = new Date().toISOString();
  active.gates = normalizeGates(active).filter((gate) => !(gate.program === program && (gate.id || gate.node_id) === node.id));
  if (!['closed', 'archived'].includes(node.status)) {
    active.gates.push({
      program,
      id: node.id,
      title: node.title || node.id,
      node_type: stewardTypeFor(node),
      owner_lane: node.owner_lane || program,
      parent: node.parent || '',
      status: node.status,
      source_edits_authorized: node.source_edits_authorized === true,
      current_blocker: node.blocker_reason || '',
      next_allowed: node.next_gate || nextGateFor(node.status),
      function_tree_ref: node.function_tree_ref || '',
      freshness: node.freshness || 'current-head',
      allowed_paths: list(node.allowed_paths),
      forbidden_paths: list(node.forbidden_paths),
      updated_at: node.updated_at || active.updated_at,
    });
  }
  writeJson(activePath, active);
}

function syncActiveGates(root) {
  const gov = path.join(root, '.governance');
  ensureDir(gov);
  const activePath = path.join(gov, 'active-gates.json');
  if (!fs.existsSync(activePath)) {
    writeJson(activePath, { schema_version: 1, updated_at: new Date().toISOString(), gates: [] });
  }
  const active = loadActiveGates(root);
  const gates = normalizeGates(active);
  const md = [
    '# Active Gates',
    '',
    '| Program | Node | Status | Current blocker | Next allowed | FT ref |',
    '|---------|------|--------|-----------------|--------------|--------|',
    ...gates.map((gate) => [
      gate.program || '-',
      gate.id || gate.node_id || '-',
      gate.status || gate.gate || '-',
      gate.current_blocker || gate.blocker_reason || '-',
      gate.next_allowed || gate.next_gate || '-',
      gate.function_tree_ref || gate.ft_ref || '-',
    ].map(escapeCell).join(' | ')).map((row) => `| ${row} |`),
    '',
    '_Generated from `.governance/active-gates.json`._',
    '',
  ].join('\n');
  writeFile(path.join(gov, 'active-gates.md'), md);
  console.log(`synced ${rel(root, path.join(gov, 'active-gates.md'))}`);
}

function loadActiveGates(root) {
  const p = path.join(root, '.governance', 'active-gates.json');
  if (!fs.existsSync(p)) return { schema_version: 1, gates: [] };
  return readJson(p);
}

function normalizeGates(active) {
  if (!active) return [];
  if (Array.isArray(active)) return active;
  if (Array.isArray(active.gates)) return active.gates;
  return [];
}
module.exports = { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates };
