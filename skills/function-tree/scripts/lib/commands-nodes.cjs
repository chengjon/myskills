'use strict';

const fs = require('fs');
const path = require('path');

const { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES } = require('./constants.cjs');
const { refreshFunctionTreeDoc, writeFunctionTreeDoc, backupFunctionTreeDoc, extractProjectNotes, extractExistingFunctionTreeBody, extractPreservedPreviousFunctionTree, stripGeneratedFunctionTreeSection, stripFunctionTreeTitle, stripGeneratedDocPreamble, looksLikeFunctionTreeBody, isRefreshableGeneratedFunctionTreeBody, defaultProjectNotes, renderFunctionTreeDoc, renderDefaultFunctionTreeBody } = require('./doc.cjs');
const { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates } = require('./gates.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function initProgram(root, args, flags) {
  const program = args[0];
  if (!program || !/^[a-z0-9][a-z0-9._-]*$/i.test(program)) {
    fail('init requires <program> using letters, numbers, dot, dash, or underscore', 2);
  }

  const ref = String(flags.ref || 'unlinked');
  const description = String(flags.description || '');
  const gov = path.join(root, '.governance');
  const programs = path.join(gov, 'programs');
  const programDir = path.join(programs, program);
  const cardsDir = path.join(programDir, 'cards');
  const head = gitHead(root);
  const createdAt = new Date().toISOString();

  ensureDir(cardsDir);

  const treePath = path.join(programDir, 'tree.md');
  const nodesPath = path.join(programDir, 'nodes.json');
  const templatePath = path.join(skillDir(), 'templates', 'program-tree.md');
  if (!fs.existsSync(treePath)) {
    const rendered = renderTemplate(readFile(templatePath), {
      PROGRAM_NAME: program,
      FT_REF: ref,
      CREATED_AT: createdAt,
      CURRENT_HEAD: head,
      DESCRIPTION: description,
    });
    writeFile(treePath, rendered);
  }
  if (!fs.existsSync(nodesPath)) writeJson(nodesPath, []);

  const activePath = path.join(gov, 'active-gates.json');
  if (!fs.existsSync(activePath)) {
    writeJson(activePath, {
      schema_version: 1,
      updated_at: createdAt,
      gates: [],
    });
  }
  syncActiveGates(root);
  const docResult = flags['no-doc'] ? null : writeFunctionTreeDoc(root, { program, ref, description });

  const output = [
    `created program: ${program}`,
    `root: ${root}`,
    `tree: ${rel(root, treePath)}`,
    `nodes: ${rel(root, nodesPath)}`,
  ];
  if (docResult) {
    output.push(`function_tree_doc: ${rel(root, docResult.docPath)}`);
    if (docResult.backupPath) output.push(`function_tree_backup: ${rel(root, docResult.backupPath)}`);
  }
  output.push(`next: record evidence, then prepare authorization before source edits`);
  console.log(output.join('\n'));
}

function newNode(root, args, flags) {
  const program = args[0];
  const id = args[1];
  if (!program || !id) fail('new-node requires <program> <node-id>', 2);
  const title = one(flags, 'title') || id;
  const ref = one(flags, 'ref') || 'unlinked';
  const programDir = requireProgramDir(root, program);
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  if (nodes.some((node) => node.id === id)) fail(`node already exists: ${program}/${id}`, 2);

  const now = new Date().toISOString();
  const node = {
    id,
    title,
    node_type: normalizeStewardNodeType(one(flags, 'type') || 'decision'),
    owner_lane: one(flags, 'owner-lane') || program,
    parent: one(flags, 'parent') || '',
    status: 'planning',
    function_tree_ref: ref,
    current_head: gitHead(root),
    freshness: one(flags, 'freshness') || 'current-head',
    source_edits_authorized: false,
    evidence: [],
    allowed_paths: [],
    forbidden_paths: [],
    non_goals: [],
    next_gate: 'collect baseline evidence',
    blocker_reason: null,
    unblock_target_state: null,
    created_at: now,
    updated_at: now,
  };
  // Phase 1: optional mainline layering fields. Only written when explicitly provided.
  const trackRaw = one(flags, 'track');
  if (trackRaw) node.track = normalizeTrack(trackRaw);
  const mainlineIdRaw = one(flags, 'mainline-id');
  if (mainlineIdRaw) node.mainline_id = mainlineIdRaw;
  const depthRaw = one(flags, 'depth');
  if (depthRaw !== undefined && depthRaw !== '') {
    const n = Number(depthRaw);
    if (Number.isInteger(n) && n >= 0) node.depth = n;
  }
  nodes.push(node);
  saveNodes(nodesPath, nodes);
  appendTreeNode(programDir, node);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`created node: ${program}/${id}`);
}

function newNodeBatch(root, args, flags) {
  const program = args[0];
  if (!program) fail('new-node-batch requires <program>', 2);
  const fromDirs = one(flags, 'from-dirs');
  if (!fromDirs) fail('new-node-batch requires --from-dirs <dir>', 2);
  const programDir = requireProgramDir(root, program);
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  const existing = new Set(nodes.map((n) => n.id));

  const absRoot = path.resolve(root, fromDirs);
  if (!fs.existsSync(absRoot)) fail(`--from-dirs not found: ${absRoot}`, 2);

  const idPrefix = one(flags, 'id-prefix') || '';
  const pattern = one(flags, 'pattern') || '*';
  const parent = one(flags, 'parent') || '';
  const trackRaw = one(flags, 'track');
  const mainlineId = one(flags, 'mainline-id');
  const depthRaw = one(flags, 'depth');
  const typeRaw = one(flags, 'type') || 'external';
  const dryRun = Boolean(flags['dry-run']);

  const subdirs = fs
    .readdirSync(absRoot, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .filter((name) => minimatchSimple(name, pattern))
    .sort();

  if (!subdirs.length) {
    console.log(`no subdirectories matched under ${absRoot}`);
    return;
  }

  const created = [];
  const skipped = [];
  const now = new Date().toISOString();
  for (const name of subdirs) {
    const id = `${idPrefix}${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    if (existing.has(id)) {
      skipped.push(id);
      continue;
    }
    const node = {
      id,
      title: name,
      node_type: normalizeStewardNodeType(typeRaw),
      owner_lane: program,
      parent,
      status: 'planning',
      function_tree_ref: path.join(fromDirs, name),
      current_head: gitHead(root),
      freshness: 'current-head',
      source_edits_authorized: false,
      evidence: [],
      allowed_paths: [],
      forbidden_paths: [],
      non_goals: [],
      next_gate: 'collect baseline evidence',
      blocker_reason: null,
      unblock_target_state: null,
      created_at: now,
      updated_at: now,
    };
    if (trackRaw) node.track = normalizeTrack(trackRaw);
    if (mainlineId) node.mainline_id = mainlineId;
    if (depthRaw !== undefined && depthRaw !== '') {
      const n = Number(depthRaw);
      if (Number.isInteger(n) && n >= 0) node.depth = n;
    }
    nodes.push(node);
    existing.add(id);
    created.push(id);
    if (!dryRun) {
      appendTreeNode(programDir, node);
      upsertActiveGate(root, program, node);
    }
  }

  if (dryRun) {
    console.log(`[dry-run] would create ${created.length} node(s): ${created.join(', ')}`);
    if (skipped.length) console.log(`[dry-run] skipped ${skipped.length} existing: ${skipped.join(', ')}`);
    return;
  }

  saveNodes(nodesPath, nodes);
  syncActiveGates(root);
  console.log(`created ${created.length} node(s): ${created.join(', ')}`);
  if (skipped.length) console.log(`skipped ${skipped.length} existing: ${skipped.join(', ')}`);
}

function reparentNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node } = loadTargetNode(root, args, 'reparent');
  const parent = one(flags, 'parent');
  const mainlineId = one(flags, 'mainline-id');
  const depthRaw = one(flags, 'depth');
  const trackRaw = one(flags, 'track');
  if (!parent && !mainlineId && depthRaw === undefined && !trackRaw) {
    fail('reparent requires at least one of --parent / --mainline-id / --depth / --track', 2);
  }

  if (parent !== undefined) node.parent = parent;
  if (mainlineId !== undefined) node.mainline_id = mainlineId || '';
  if (depthRaw !== undefined && depthRaw !== '') {
    const n = Number(depthRaw);
    if (!Number.isInteger(n) || n < 0) fail(`invalid --depth: ${depthRaw}`, 2);
    node.depth = n;
  }
  if (trackRaw) node.track = normalizeTrack(trackRaw);
  node.updated_at = new Date().toISOString();

  saveNodes(nodesPath, nodes);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`reparented: ${program}/${id} (parent=${node.parent || '-'}, track=${node.track || 'untracked'}, depth=${node.depth !== undefined ? node.depth : 'inherit'})`);
}

function observeNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node } = loadTargetNode(root, args, 'observe');
  const evidence = one(flags, 'evidence');
  if (!evidence) fail('observe requires --evidence <path-or-note>', 2);
  const head = gitHead(root);
  const record = {
    kind: one(flags, 'kind') || 'baseline',
    path: evidence,
    note: one(flags, 'note') || '',
    current_head: head,
    recorded_at: new Date().toISOString(),
  };
  if (!Array.isArray(node.evidence)) node.evidence = [];
  node.evidence.push(record);
  node.current_head = head;
  if (node.status === 'planning') node.status = 'evidence-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'prepare decision or authorization';
  node.updated_at = record.recorded_at;
  saveNodes(nodesPath, nodes);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`observed evidence for: ${program}/${id}`);
}

function authorizeNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'authorize');
  if (!['evidence-prepared', 'decision-prepared', 'authorization-prepared'].includes(node.status)) {
    fail(`authorize requires evidence-prepared or decision-prepared status, got ${node.status}`, 2);
  }
  const allowed = many(flags, 'allowed');
  const nonGoals = many(flags, 'non-goal');
  const commitGates = many(flags, 'commit-gate');
  const closeoutGates = many(flags, 'closeout-gate');
  if (!allowed.length) fail('authorize requires at least one --allowed path', 2);
  if (!nonGoals.length) fail('authorize requires at least one --non-goal', 2);
  if (!commitGates.length) fail('authorize requires at least one --commit-gate', 2);
  if (!closeoutGates.length) fail('authorize requires at least one --closeout-gate', 2);

  node.allowed_paths = allowed;
  node.forbidden_paths = many(flags, 'forbidden');
  node.non_goals = nonGoals;
  node.acceptance = {
    commit_gate: commitGates,
    closeout_gate: closeoutGates,
  };
  node.status = 'authorization-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'review and approve implementation authorization';
  node.updated_at = new Date().toISOString();

  const cardsDir = path.join(programDir, 'cards');
  ensureDir(cardsDir);
  writeFile(path.join(cardsDir, `${safeFileName(id)}.yaml`), renderTaskCard(node));
  saveNodes(nodesPath, nodes);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`authorized draft: ${program}/${id}`);
}

function transitionNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node } = loadTargetNode(root, args, 'transition');
  const to = one(flags, 'to');
  if (!to || !STATUSES.has(to)) fail('transition requires --to <valid-status>', 2);
  assertTransitionAllowed(root, node, to, flags);

  const from = node.status;
  node.status = to;
  node.source_edits_authorized = SOURCE_EDIT_STATUSES.has(to);
  if (to === 'blocked') {
    node.blocker_reason = one(flags, 'blocker');
    node.unblock_target_state = one(flags, 'unblock-target-state');
    node.next_gate = `unblock to ${node.unblock_target_state}`;
  } else {
    node.blocker_reason = null;
    node.unblock_target_state = null;
    node.next_gate = nextGateFor(to);
  }
  if (!Array.isArray(node.transitions)) node.transitions = [];
  node.transitions.push({
    from,
    to,
    note: one(flags, 'note') || '',
    current_head: gitHead(root),
    transitioned_at: new Date().toISOString(),
  });
  node.updated_at = new Date().toISOString();
  saveNodes(nodesPath, nodes);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`transitioned ${program}/${id}: ${from} -> ${to}`);
}

function closeoutNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node } = loadTargetNode(root, args, 'closeout');
  if (node.status !== 'implementation-landed') {
    fail(`closeout requires implementation-landed status, got ${node.status}`, 2);
  }
  const summary = one(flags, 'summary');
  if (!summary) fail('closeout requires --summary <path-or-note>', 2);
  node.closeout = {
    summary,
    compatibility: one(flags, 'compatibility') || '',
    gates: many(flags, 'gate'),
    current_head: gitHead(root),
    prepared_at: new Date().toISOString(),
  };
  node.status = 'closeout-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'review closeout and close node';
  node.updated_at = node.closeout.prepared_at;
  saveNodes(nodesPath, nodes);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`prepared closeout: ${program}/${id}`);
}
module.exports = { initProgram, newNode, newNodeBatch, reparentNode, observeNode, authorizeNode, transitionNode, closeoutNode };
