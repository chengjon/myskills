'use strict';

const fs = require('fs');
const path = require('path');

const { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES } = require('./constants.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
const { collectGovernancePrograms, detectNestedProjectRoots, listContainsPyFiles, readProgramTreeMeta, detectProjectName, detectPythonPackageRoots, collectStewardPrograms } = require('./programs.cjs');
function syncStewardProfile(root) {
  const index = buildStewardIndex(root);
  const stewardDir = path.join(root, '.governance', 'steward');
  const tracksDir = path.join(stewardDir, 'tracks');
  ensureDir(tracksDir);
  writeJson(path.join(stewardDir, 'steward-index.json'), index);
  writeFile(path.join(stewardDir, 'current-next-gates.md'), renderStewardGates(index));
  writeFile(path.join(stewardDir, 'evidence-index.md'), renderStewardEvidenceIndex(index));
  for (const program of index.programs) {
    const nodes = index.nodes.filter((node) => node.program === program.name);
    writeFile(path.join(tracksDir, `${safeFileName(program.name)}.md`), renderStewardTrack(program, nodes));
  }
  console.log([
    'steward profile synced',
    `index: ${rel(root, path.join(stewardDir, 'steward-index.json'))}`,
    `gates: ${rel(root, path.join(stewardDir, 'current-next-gates.md'))}`,
    `evidence: ${rel(root, path.join(stewardDir, 'evidence-index.md'))}`,
    `tracks: ${index.programs.length}`,
  ].join('\n'));
}

function buildStewardIndex(root) {
  const currentHead = gitHead(root);
  const programs = collectStewardPrograms(root);
  const nodes = programs.flatMap((program) => program.nodes.map((node) => stewardNode(program.name, node, currentHead)));
  return {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    current_head: currentHead,
    contract: {
      role: 'relationship index between function-tree governance, external delivery systems, evidence, and implementation truth',
      source_of_truth: 'derived from .governance/programs/*/nodes.json plus current repository HEAD',
    },
    boundaries: STEWARD_BOUNDARIES,
    programs: programs.map((program) => ({
      name: program.name,
      node_count: program.nodes.length,
      active_count: program.nodes.filter((node) => node && !['closed', 'archived'].includes(node.status)).length,
      tree_path: rel(root, path.join(root, '.governance', 'programs', program.name, 'tree.md')),
    })),
    nodes,
  };
}

function stewardNode(program, node, currentHead) {
  const acceptance = node.acceptance || {};
  const stale = staleEvidenceReason(node, currentHead || '');
  return {
    program,
    id: node.id || '',
    title: node.title || node.id || '',
    type: stewardTypeFor(node),
    state: node.status || 'planning',
    status: node.status || 'planning',
    owner_lane: node.owner_lane || program,
    parent: node.parent || '',
    function_tree_ref: node.function_tree_ref || '',
    evidence: stewardEvidence(node),
    allowed_scope: {
      paths: list(node.allowed_paths),
      commit_gates: list(acceptance.commit_gate),
    },
    forbidden_scope: {
      paths: list(node.forbidden_paths),
      non_goals: list(node.non_goals),
    },
    source_edit_authority: node.source_edits_authorized === true,
    current_head: node.current_head || '',
    freshness: {
      policy: node.freshness || 'current-head',
      current_head: node.current_head || '',
      repository_head: currentHead || '',
      stale: Boolean(stale),
      stale_reason: stale || '',
    },
    next_gate: node.next_gate || nextGateFor(node.status),
  };
}

function stewardEvidence(node) {
  return Array.isArray(node.evidence) ? node.evidence.map((item) => ({
    kind: item.kind || 'evidence',
    path: item.path || '',
    note: item.note || '',
    current_head: item.current_head || '',
    recorded_at: item.recorded_at || '',
  })) : [];
}

function renderStewardGates(index) {
  const active = index.nodes.filter((node) => !['closed', 'archived'].includes(node.state));
  const rows = active.map((node) => [
    node.program,
    node.id,
    node.type,
    node.state,
    node.owner_lane,
    node.next_gate,
    node.source_edit_authority ? 'yes' : 'no',
  ]);
  return [
    '# Current Next Gates',
    '',
    `Generated at: ${index.generated_at}`,
    `Repository HEAD: ${index.current_head || '-'}`,
    '',
    markdownTable(['Program', 'Node', 'Type', 'State', 'Owner lane', 'Next gate', 'Source edits'], rows),
    '',
  ].join('\n');
}

function renderStewardEvidenceIndex(index) {
  const rows = [];
  for (const node of index.nodes) {
    for (const evidence of node.evidence) {
      rows.push([
        node.program,
        node.id,
        evidence.kind,
        evidence.path,
        evidence.current_head,
        evidence.note,
      ]);
    }
  }
  return [
    '# Evidence Index',
    '',
    `Generated at: ${index.generated_at}`,
    '',
    markdownTable(['Program', 'Node', 'Kind', 'Evidence', 'HEAD', 'Note'], rows),
    '',
  ].join('\n');
}

function renderStewardTrack(program, nodes) {
  const rows = nodes.map((node) => [
    node.id,
    node.title,
    node.type,
    node.state,
    node.owner_lane,
    node.next_gate,
    node.freshness.stale ? 'stale' : node.freshness.policy,
  ]);
  return [
    `# Steward Track: ${program.name}`,
    '',
    `Tree: ${program.tree_path}`,
    `Nodes: ${program.node_count}`,
    `Active: ${program.active_count}`,
    '',
    markdownTable(['Node', 'Title', 'Type', 'State', 'Owner lane', 'Next gate', 'Freshness'], rows),
    '',
  ].join('\n');
}
module.exports = { syncStewardProfile, buildStewardIndex, stewardNode, stewardEvidence, renderStewardGates, renderStewardEvidenceIndex, renderStewardTrack };
