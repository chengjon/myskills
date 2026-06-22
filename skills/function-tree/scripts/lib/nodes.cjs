'use strict';

const fs = require('fs');
const path = require('path');

const { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES } = require('./constants.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const TRACK_VALUES = new Set(['mainline', 'backlog', 'optimize', 'untracked']);

function loadNodes(nodesPath) {
  if (!fs.existsSync(nodesPath)) return [];
  const nodes = readJson(nodesPath);
  if (!Array.isArray(nodes)) throw new Error(`${nodesPath} must be a JSON array`);
  return nodes;
}

function saveNodes(nodesPath, nodes) {
  writeJson(nodesPath, nodes);
}

function loadAllNodes(root) {
  // Returns { byId, programs } where byId maps id -> { node, program }
  const programsDir = path.join(root, '.governance', 'programs');
  const byId = new Map();
  const programs = [];
  if (!fs.existsSync(programsDir)) return { byId, programs };
  for (const program of fs.readdirSync(programsDir)) {
    const nodesPath = path.join(programsDir, program, 'nodes.json');
    if (!fs.existsSync(nodesPath)) continue;
    const nodes = loadNodes(nodesPath);
    programs.push({ program, nodes });
    for (const node of nodes) {
      if (node && node.id) byId.set(node.id, { node, program });
    }
  }
  return { byId, programs };
}

function loadAllNodesResolved(root) {
  const { byId, programs } = loadAllNodes(root);
  const resolved = [];
  for (const { program, nodes } of programs) {
    for (const node of nodes) {
      const fields = resolveMainlineFields(node, byId);
      resolved.push({ program, node, ...fields });
    }
  }
  return { resolved, byId };
}

function loadTargetNode(root, args, commandName) {
  const program = args[0];
  const id = args[1];
  if (!program || !id) fail(`${commandName} requires <program> <node-id>`, 2);
  const programDir = requireProgramDir(root, program);
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  const node = nodes.find((candidate) => candidate.id === id);
  if (!node) fail(`node not found: ${program}/${id}`, 2);
  return { program, id, programDir, nodesPath, nodes, node };
}

function requireProgramDir(root, program) {
  const programDir = path.join(root, '.governance', 'programs', program);
  const nodesPath = path.join(programDir, 'nodes.json');
  if (!fs.existsSync(nodesPath)) fail(`program not initialized: ${program}`, 2);
  return programDir;
}

function appendTreeNode(programDir, node) {
  syncTreeMd(programDir);
}

function syncTreeMd(programDir) {
  const treePath = path.join(programDir, 'tree.md');
  if (!fs.existsSync(treePath)) return;
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  const content = readFile(treePath);

  const treeSection = renderTreeSection(nodes);
  const evidenceSection = renderEvidenceLedgerSection(nodes);

  let out = content;
  out = replaceTreeSection(out, '## Tree', treeSection);
  out = replaceTreeSection(out, '## Evidence Ledger', evidenceSection);
  writeFile(treePath, out);
}

function renderTreeSection(nodes) {
  if (!nodes.length) return '- [ ] (no nodes yet)\n';
  const lines = nodes.map((n) => {
    const typeLabel = n.node_type_input && n.node_type_input !== n.node_type
      ? `${n.node_type_input}/${n.node_type}`
      : (n.node_type || 'external');
    const checkbox = (n.status === 'closed' || n.status === 'archived') ? '[x]' : '[ ]';
    return `- ${checkbox} ${n.id}: ${n.title || n.id} [${typeLabel}] (${n.status || '-'}, FT: ${n.function_tree_ref || '-'})`;
  });
  return lines.join('\n') + '\n';
}

function renderEvidenceLedgerSection(nodes) {
  const header = '| Node | Evidence | Current HEAD | Notes |\n|------|----------|--------------|-------|';
  const rows = nodes
    .filter((n) => Array.isArray(n.evidence) && n.evidence.length)
    .map((n) => {
      const latest = n.evidence[n.evidence.length - 1];
      const evPath = latest.path || latest.note || '-';
      const head = latest.current_head || '-';
      const note = (latest.note || '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
      return `| ${n.id} | ${evPath} | \`${head}\` | ${note} |`;
    });
  if (!rows.length) return header + '\n| _no evidence recorded yet_ |  |  |  |';
  return header + '\n' + rows.join('\n');
}

function replaceTreeSection(content, header, newBody) {
  const idx = content.indexOf(header);
  if (idx < 0) return content;
  const startIdx = idx + header.length;
  // skip the trailing newline after the header
  const afterHeader = content.slice(startIdx);
  const nlMatch = afterHeader.match(/^\n*/);
  const bodyStart = startIdx + (nlMatch ? nlMatch[0].length : 0);
  // find next "## " header starting from after the newline
  const rest = content.slice(bodyStart);
  const nextMatch = rest.match(/\n## /);
  const endIdx = nextMatch ? bodyStart + nextMatch.index : content.length;
  return content.slice(0, bodyStart) + newBody + '\n' + content.slice(endIdx);
}

function assertTransitionAllowed(root, node, to, flags) {
  if (to === 'blocked') {
    if (!one(flags, 'blocker')) fail('blocked transition requires --blocker <reason>', 2);
    const target = one(flags, 'unblock-target-state');
    if (!target || !STATUSES.has(target)) fail('blocked transition requires --unblock-target-state <valid-status>', 2);
    return;
  }
  if (node.status === 'blocked') {
    if (to !== node.unblock_target_state) {
      fail(`blocked node can only transition to ${node.unblock_target_state}, not ${to}`, 2);
    }
    return;
  }
  if (to === 'archived') return;

  const allowed = {
    planning: ['evidence-prepared', 'blocked', 'archived'],
    'evidence-prepared': ['decision-prepared', 'authorization-prepared', 'blocked', 'archived'],
    'decision-prepared': ['authorization-prepared', 'blocked', 'archived'],
    'authorization-prepared': ['approved-for-implementation', 'blocked', 'archived'],
    'approved-for-implementation': ['implementation-ready', 'blocked', 'archived'],
    'implementation-ready': ['implementation-landed', 'blocked', 'archived'],
    'implementation-landed': ['closeout-prepared', 'blocked', 'archived'],
    'closeout-prepared': ['closed', 'blocked', 'archived'],
    closed: [],
    archived: [],
  };
  if (!allowed[node.status] || !allowed[node.status].includes(to)) {
    fail(`invalid transition: ${node.status} -> ${to}`, 2);
  }
  if (to === 'approved-for-implementation') {
    if (!list(node.allowed_paths).length) fail('approval requires allowed_paths from authorization', 2);
    if (!list(node.non_goals).length) fail('approval requires at least one non_goal', 2);
    const acceptance = node.acceptance || {};
    if (!list(acceptance.commit_gate).length) fail('approval requires commit_gate acceptance', 2);
    if (!list(acceptance.closeout_gate).length) fail('approval requires closeout_gate acceptance', 2);
    const stale = staleEvidenceReason(node, gitHead(root));
    if (stale) fail(stale, 2);
  }
}

function staleEvidenceReason(node, headOverride) {
  const evidence = Array.isArray(node.evidence) ? node.evidence : [];
  const latest = evidence[evidence.length - 1];
  if (!latest || !latest.current_head) return 'stale evidence: missing evidence current_head';
  const head = headOverride == null ? '' : headOverride;
  if (!head) return '';
  if (latest.current_head !== head) {
    return `stale evidence: latest evidence HEAD ${latest.current_head} does not match current HEAD ${head}`;
  }
  return '';
}

function nextGateFor(status) {
  switch (status) {
    case 'planning':
      return 'collect baseline evidence';
    case 'evidence-prepared':
      return 'prepare decision or authorization';
    case 'decision-prepared':
      return 'prepare authorization';
    case 'authorization-prepared':
      return 'review and approve implementation authorization';
    case 'approved-for-implementation':
      return 'implement within allowed_paths';
    case 'implementation-ready':
      return 'land implementation with Git evidence';
    case 'implementation-landed':
      return 'prepare closeout';
    case 'closeout-prepared':
      return 'review closeout and close node';
    case 'closed':
      return 'none';
    case 'archived':
      return 'none';
    default:
      return 'resolve blocker';
  }
}

function renderTaskCard(node) {
  const acceptance = node.acceptance || {};
  return [
    'task:',
    `  id: ${yamlString(node.id)}`,
    `  title: ${yamlString(node.title || node.id)}`,
    '',
    'scope:',
    '  allowed_paths:',
    ...yamlList(node.allowed_paths, 4),
    '  forbidden_paths:',
    ...yamlList(node.forbidden_paths, 4),
    '',
    'non_goals:',
    ...yamlList(node.non_goals, 2),
    '',
    'acceptance:',
    '  commit_gate:',
    ...yamlList(acceptance.commit_gate, 4),
    '  closeout_gate:',
    ...yamlList(acceptance.closeout_gate, 4),
    '',
    'evidence:',
    `  current_head: ${yamlString(latestEvidenceHead(node) || node.current_head || '')}`,
    '  notes: []',
    '',
  ].join('\n');
}

function yamlList(values, indent) {
  const items = list(values);
  const pad = ' '.repeat(indent);
  if (!items.length) return [`${pad}[]`];
  return items.map((value) => `${pad}- ${yamlString(value)}`);
}

function yamlString(value) {
  return JSON.stringify(String(value == null ? '' : value));
}

function latestEvidenceHead(node) {
  const evidence = Array.isArray(node.evidence) ? node.evidence : [];
  const latest = evidence[evidence.length - 1];
  return latest && latest.current_head ? latest.current_head : '';
}

function normalizeTrack(value) {
  const t = String(value || '').trim().toLowerCase();
  return TRACK_VALUES.has(t) ? t : 'untracked';
}

function normalizeDepth(value, fallback) {
  const n = Number(value);
  if (Number.isInteger(n) && n >= 0) return n;
  return fallback;
}

function normalizeStewardNodeType(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (NODE_TYPE_ALIASES[raw]) return NODE_TYPE_ALIASES[raw];
  if (!STEWARD_NODE_TYPES.has(raw)) {
    fail(
      `invalid steward node type: ${value}\n  valid: feature, capability, epic, module, component, bug, task, refactor, spike, evidence, decision, authorization, implementation, closeout, external`,
      2,
    );
  }
  return raw;
}

function resolveMainlineFields(node, nodesById) {
  const track = normalizeTrack(node.track);
  const hasParent = node.parent && nodesById && nodesById.has(node.parent);
  let depth;
  if (track === 'backlog' || track === 'optimize') {
    depth = normalizeDepth(node.depth, 99);
    if (depth !== 99) depth = 99; // force 99 for non-mainline tracks
  } else if (track === 'mainline') {
    if (node.depth === 0 || (typeof node.depth === 'undefined' && !hasParent)) {
      depth = 0;
    } else {
      depth = normalizeDepth(node.depth, hasParent ? 1 : 0);
    }
  } else {
    // untracked
    depth = normalizeDepth(node.depth, 99);
  }
  let mainlineId = node.mainline_id || null;
  if (!mainlineId) {
    if (track === 'mainline' && depth === 0) mainlineId = node.id;
    else if (track === 'mainline' && hasParent) mainlineId = resolveMainlineRoot(node.parent, nodesById);
  }
  return { track, depth, mainline_id: mainlineId };
}

function resolveMainlineRoot(startId, nodesById) {
  const visited = new Set();
  let cur = startId;
  while (cur && nodesById.has(cur) && !visited.has(cur)) {
    visited.add(cur);
    const node = nodesById.get(cur);
    const t = normalizeTrack(node.track);
    if (t === 'mainline') {
      const hasParent = node.parent && nodesById.has(node.parent);
      if (node.depth === 0 || (typeof node.depth === 'undefined' && !hasParent)) return cur;
    }
    cur = node.parent;
  }
  return null;
}

function isActiveStatus(status) {
  const s = String(status || '').toLowerCase();
  return s && s !== 'closed' && s !== 'deferred';
}

function stewardTypeFor(node) {
  if (node && node.node_type) return normalizeStewardNodeType(node.node_type);
  if (!node) return 'decision';
  if (node.source_edits_authorized === true || SOURCE_EDIT_STATUSES.has(node.status)) return 'implementation';
  if (node.status === 'closeout-prepared' || node.closeout) return 'closeout';
  if (node.status === 'authorization-prepared' || list(node.allowed_paths).length || list(node.non_goals).length) {
    return 'authorization';
  }
  if (Array.isArray(node.evidence) && node.evidence.length) return 'evidence';
  return 'decision';
}
module.exports = { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, syncTreeMd, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor };
