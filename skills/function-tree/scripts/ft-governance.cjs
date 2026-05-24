#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const cp = require('child_process');

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

function main() {
  try {
    const parsed = parseArgs(process.argv.slice(2));
    if (!parsed.command || parsed.command === 'help' || parsed.flags.help) {
      usage(0);
      return;
    }

    const root = resolveRoot(parsed.flags);
    switch (parsed.command) {
      case 'init':
        initProgram(root, parsed.args, parsed.flags);
        break;
      case 'new-node':
        newNode(root, parsed.args, parsed.flags);
        break;
      case 'observe':
        observeNode(root, parsed.args, parsed.flags);
        break;
      case 'authorize':
        authorizeNode(root, parsed.args, parsed.flags);
        break;
      case 'transition':
        transitionNode(root, parsed.args, parsed.flags);
        break;
      case 'closeout':
        closeoutNode(root, parsed.args, parsed.flags);
        break;
      case 'install-guard':
        installGuard(root, parsed.flags);
        break;
      case 'repair':
        repairActiveGates(root);
        break;
      case 'status':
        printStatus(root);
        break;
      case 'gate':
        printGate(root, Boolean(parsed.flags.verbose));
        break;
      case 'sync':
        syncActiveGates(root);
        break;
      case 'validate':
        validateGovernance(root);
        break;
      case 'scope-check':
        scopeCheck(root, parsed.flags);
        break;
      default:
        fail(`unknown command: ${parsed.command}`, 2);
    }
  } catch (error) {
    fail(error && error.message ? error.message : String(error), 1);
  }
}

function parseArgs(argv) {
  if (argv[0] && argv[0].startsWith('--')) {
    return { command: null, args: [], flags: { [argv[0].slice(2)]: true } };
  }
  const out = { command: argv[0], args: [], flags: {} };
  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      out.args.push(token);
      continue;
    }

    const eq = token.indexOf('=');
    if (eq !== -1) {
      assignFlag(out.flags, token.slice(2, eq), token.slice(eq + 1));
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      assignFlag(out.flags, key, next);
      i += 1;
    } else {
      assignFlag(out.flags, key, true);
    }
  }
  return out;
}

function assignFlag(flags, key, value) {
  if (Object.prototype.hasOwnProperty.call(flags, key)) {
    if (Array.isArray(flags[key])) flags[key].push(value);
    else flags[key] = [flags[key], value];
  } else {
    flags[key] = value;
  }
}

function usage(code) {
  const text = [
    'Usage:',
    '  ft-governance.cjs init <program> --ref <function-tree-node> [--description <text>] [--root <repo>]',
    '  ft-governance.cjs new-node <program> <node-id> --title <text> --ref <function-tree-node> [--root <repo>]',
    '  ft-governance.cjs observe <program> <node-id> --evidence <path-or-note> [--kind <kind>] [--note <text>] [--root <repo>]',
    '  ft-governance.cjs authorize <program> <node-id> --allowed <path> --non-goal <text> --commit-gate <text> --closeout-gate <text> [--root <repo>]',
    '  ft-governance.cjs transition <program> <node-id> --to <status> [--note <text>] [--blocker <text>] [--unblock-target-state <status>] [--root <repo>]',
    '  ft-governance.cjs closeout <program> <node-id> --summary <path-or-note> [--compatibility <text>] [--gate <text>] [--root <repo>]',
    '  ft-governance.cjs install-guard [--force] [--root <repo>]',
    '  ft-governance.cjs repair [--root <repo>]',
    '  ft-governance.cjs status [--root <repo>]',
    '  ft-governance.cjs gate [--verbose] [--root <repo>]',
    '  ft-governance.cjs sync [--root <repo>]',
    '  ft-governance.cjs validate [--root <repo>]',
    '  ft-governance.cjs scope-check [--files a,b,c] [--root <repo>]',
  ].join('\n');
  console.log(text);
  process.exit(code);
}

function resolveRoot(flags) {
  if (flags.root) return path.resolve(String(flags.root));
  try {
    return run('git', ['rev-parse', '--show-toplevel'], process.cwd()).trim();
  } catch (_) {
    return process.cwd();
  }
}

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

  console.log([
    `created program: ${program}`,
    `root: ${root}`,
    `tree: ${rel(root, treePath)}`,
    `nodes: ${rel(root, nodesPath)}`,
    `next: record evidence, then prepare authorization before source edits`,
  ].join('\n'));
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
    status: 'planning',
    function_tree_ref: ref,
    current_head: gitHead(root),
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
  nodes.push(node);
  saveNodes(nodesPath, nodes);
  appendTreeNode(programDir, node);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`created node: ${program}/${id}`);
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

function printStatus(root) {
  const gov = path.join(root, '.governance');
  const active = loadActiveGates(root);
  const programsDir = path.join(gov, 'programs');
  const programs = fs.existsSync(programsDir)
    ? fs.readdirSync(programsDir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name).sort()
    : [];
  const gates = normalizeGates(active);
  console.log([
    `root: ${root}`,
    `programs: ${programs.length ? programs.join(', ') : '(none)'}`,
    `active gates: ${gates.length}`,
  ].join('\n'));
}

function printGate(root, verbose) {
  const gates = normalizeGates(loadActiveGates(root));
  if (!gates.length) {
    console.log('active gates: none');
    return;
  }
  const rows = gates.map((gate) => {
    const id = gate.id || gate.node_id || '-';
    const program = gate.program || '-';
    const status = gate.status || gate.gate || '-';
    const next = gate.next_allowed || gate.next_gate || '-';
    if (!verbose) return `${program}/${id}: ${status} -> ${next}`;
    const allowed = list(gate.allowed_paths).join(', ') || '-';
    const forbidden = list(gate.forbidden_paths).join(', ') || '-';
    const blocker = gate.current_blocker || gate.blocker_reason || '-';
    return `${program}/${id}: ${status}\n  next: ${next}\n  blocker: ${blocker}\n  allowed: ${allowed}\n  forbidden: ${forbidden}`;
  });
  console.log(rows.join('\n'));
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

function installGuard(root, flags) {
  const guardPath = path.join(root, '.governance', 'guards', 'ft-scope-check.sh');
  if (fs.existsSync(guardPath) && !flags.force) {
    fail(`${rel(root, guardPath)} already exists; rerun with --force to overwrite`, 2);
  }
  const scriptPath = path.join(skillDir(), 'scripts', 'ft-governance.cjs');
  const content = [
    '#!/usr/bin/env bash',
    'set -euo pipefail',
    '',
    `FT_GOVERNANCE_SCRIPT=${shellQuote(scriptPath)}`,
    'export FT_GOVERNANCE_SCRIPT',
    'exec node "$FT_GOVERNANCE_SCRIPT" scope-check --root "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" "$@"',
    '',
  ].join('\n');
  writeFile(guardPath, content);
  fs.chmodSync(guardPath, 0o755);
  console.log([
    `installed guard: ${rel(root, guardPath)}`,
    'hook snippet:',
    '{',
    '  "hooks": {',
    '    "PostToolUse": [{',
    '      "matcher": "Edit|MultiEdit|Write",',
    '      "command": "bash .governance/guards/ft-scope-check.sh",',
    '      "description": "Check file edits against active FUNCTION_TREE governance authorization"',
    '    }]',
    '  }',
    '}',
  ].join('\n'));
}

function repairActiveGates(root) {
  const gov = path.join(root, '.governance');
  ensureDir(gov);
  const active = {
    schema_version: 1,
    updated_at: new Date().toISOString(),
    gates: [],
  };
  const programsDir = path.join(gov, 'programs');
  if (fs.existsSync(programsDir)) {
    for (const program of fs.readdirSync(programsDir).sort()) {
      const nodesPath = path.join(programsDir, program, 'nodes.json');
      if (!fs.existsSync(nodesPath)) continue;
      const nodes = loadNodes(nodesPath);
      for (const node of nodes) {
        if (!node || !node.id || ['closed', 'archived'].includes(node.status)) continue;
        active.gates.push(activeGateFromNode(program, node));
      }
    }
  }
  writeJson(path.join(gov, 'active-gates.json'), active);
  syncActiveGates(root);
  console.log(`rebuilt active gates: ${active.gates.length}`);
}

function activeGateFromNode(program, node) {
  return {
    program,
    id: node.id,
    title: node.title || node.id,
    status: node.status || 'planning',
    source_edits_authorized: node.source_edits_authorized === true,
    current_blocker: node.blocker_reason || '',
    next_allowed: node.next_gate || nextGateFor(node.status),
    function_tree_ref: node.function_tree_ref || '',
    allowed_paths: list(node.allowed_paths),
    forbidden_paths: list(node.forbidden_paths),
    updated_at: node.updated_at || new Date().toISOString(),
  };
}

function validateGovernance(root) {
  const errors = [];
  const gov = path.join(root, '.governance');
  const currentHead = gitHead(root);
  const activePath = path.join(gov, 'active-gates.json');
  if (fs.existsSync(activePath)) {
    const active = readJson(activePath);
    const gates = normalizeGates(active);
    gates.forEach((gate, index) => validateNodeLike(gate, `active-gates[${index}]`, errors, true));
  }

  const programsDir = path.join(gov, 'programs');
  if (fs.existsSync(programsDir)) {
    for (const program of fs.readdirSync(programsDir)) {
      const nodesPath = path.join(programsDir, program, 'nodes.json');
      if (!fs.existsSync(nodesPath)) continue;
      const nodes = readJson(nodesPath);
      if (!Array.isArray(nodes)) {
        errors.push(`${rel(root, nodesPath)} must be a JSON array`);
        continue;
      }
      nodes.forEach((node, index) => validateNodeLike(node, `${program}.nodes[${index}]`, errors, false, currentHead));
    }
  }

  if (errors.length) {
    console.log(errors.map((e) => `ERROR ${e}`).join('\n'));
    process.exit(1);
  }
  console.log('governance validation passed');
}

function validateNodeLike(node, label, errors, gateMode, currentHead) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    errors.push(`${label} must be an object`);
    return;
  }
  const status = node.status || node.gate;
  if (status && !STATUSES.has(status)) errors.push(`${label} has unknown status: ${status}`);
  if (!gateMode && !node.id) errors.push(`${label} missing id`);
  if (node.status === 'blocked') {
    if (!node.blocker_reason) errors.push(`${label} blocked missing blocker_reason`);
    if (!node.unblock_target_state) errors.push(`${label} blocked missing unblock_target_state`);
    if (node.source_edits_authorized !== false) errors.push(`${label} blocked must set source_edits_authorized=false`);
  }
  if (node.source_edits_authorized === true && status && !SOURCE_EDIT_STATUSES.has(status)) {
    errors.push(`${label} authorizes source edits from non-implementation status: ${status}`);
  }
  if (!gateMode && Array.isArray(node.non_goals) && node.status === 'authorization-prepared' && node.non_goals.length === 0) {
    errors.push(`${label} authorization-prepared requires at least one non_goal`);
  }
  if (!gateMode && SOURCE_EDIT_STATUSES.has(node.status)) {
    const stale = staleEvidenceReason(node, currentHead || '');
    if (stale) errors.push(`${label} ${stale}`);
  }
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

function loadNodes(nodesPath) {
  if (!fs.existsSync(nodesPath)) return [];
  const nodes = readJson(nodesPath);
  if (!Array.isArray(nodes)) throw new Error(`${nodesPath} must be a JSON array`);
  return nodes;
}

function saveNodes(nodesPath, nodes) {
  writeJson(nodesPath, nodes);
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
      status: node.status,
      source_edits_authorized: node.source_edits_authorized === true,
      current_blocker: node.blocker_reason || '',
      next_allowed: node.next_gate || nextGateFor(node.status),
      function_tree_ref: node.function_tree_ref || '',
      allowed_paths: list(node.allowed_paths),
      forbidden_paths: list(node.forbidden_paths),
      updated_at: node.updated_at || active.updated_at,
    });
  }
  writeJson(activePath, active);
}

function appendTreeNode(programDir, node) {
  const treePath = path.join(programDir, 'tree.md');
  if (!fs.existsSync(treePath)) return;
  const line = `- [ ] ${node.id}: ${node.title || node.id} (${node.status}, FT: ${node.function_tree_ref || '-'})`;
  const content = readFile(treePath);
  if (content.includes(`${node.id}:`)) return;
  writeFile(treePath, `${content.trimEnd()}\n${line}\n`);
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

function safeFileName(value) {
  return String(value).replace(/[^a-zA-Z0-9._-]/g, '-');
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function scopeCheck(root, flags) {
  const files = changedFiles(root, flags).filter((file) => file && !file.endsWith('/'));
  if (!files.length) {
    console.log('scope-check: no changed files');
    return;
  }

  const gates = normalizeGates(loadActiveGates(root)).filter((gate) =>
    gate.source_edits_authorized === true ||
    SOURCE_EDIT_STATUSES.has(gate.status || gate.gate)
  );

  if (!gates.length) {
    console.log(`scope-check: no active source-edit authorization; inspected ${files.length} changed file(s)`);
    return;
  }

  const violations = [];
  for (const file of files) {
    if (file.startsWith('.governance/')) continue;
    const forbiddenGate = gates.find((gate) => list(gate.forbidden_paths).some((pattern) => matches(pattern, file)));
    if (forbiddenGate) {
      violations.push(`${file} matches forbidden_paths in ${gateName(forbiddenGate)}`);
      continue;
    }
    const allowed = gates.some((gate) => {
      const allowedPaths = list(gate.allowed_paths);
      return allowedPaths.length > 0 && allowedPaths.some((pattern) => matches(pattern, file));
    });
    if (!allowed) violations.push(`${file} is outside active allowed_paths`);
  }

  if (violations.length) {
    console.log(violations.map((v) => `ERROR ${v}`).join('\n'));
    process.exit(1);
  }
  console.log(`scope-check: ${files.length} changed file(s) within active authorization`);
}

function changedFiles(root, flags) {
  if (flags.files) {
    return String(flags.files).split(',').map((s) => s.trim()).filter(Boolean);
  }
  const commands = [
    ['diff', '--name-only'],
    ['diff', '--name-only', '--cached'],
    ['ls-files', '--others', '--exclude-standard'],
  ];
  const seen = new Set();
  for (const args of commands) {
    try {
      for (const line of run('git', args, root).split(/\r?\n/)) {
        const value = line.trim();
        if (value) seen.add(value);
      }
    } catch (_) {
      // If git is unavailable, fall back to an empty set. The caller can pass --files.
    }
  }
  return Array.from(seen).sort();
}

function normalizeGates(active) {
  if (!active) return [];
  if (Array.isArray(active)) return active;
  if (Array.isArray(active.gates)) return active.gates;
  return [];
}

function loadActiveGates(root) {
  const p = path.join(root, '.governance', 'active-gates.json');
  if (!fs.existsSync(p)) return { schema_version: 1, gates: [] };
  return readJson(p);
}

function gitHead(root) {
  try {
    return run('git', ['rev-parse', 'HEAD'], root).trim();
  } catch (_) {
    return '';
  }
}

function run(cmd, args, cwd) {
  return cp.execFileSync(cmd, args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

function readFile(p) {
  return fs.readFileSync(p, 'utf8');
}

function writeFile(p, value) {
  ensureDir(path.dirname(p));
  fs.writeFileSync(p, value.endsWith('\n') ? value : `${value}\n`, 'utf8');
}

function readJson(p) {
  try {
    return JSON.parse(readFile(p));
  } catch (error) {
    throw new Error(`${p}: invalid JSON: ${error.message}`);
  }
}

function writeJson(p, value) {
  writeFile(p, `${JSON.stringify(value, null, 2)}\n`);
}

function renderTemplate(template, values) {
  return template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key) => Object.prototype.hasOwnProperty.call(values, key) ? values[key] : '');
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function skillDir() {
  return path.resolve(__dirname, '..');
}

function list(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}

function many(flags, key) {
  if (!Object.prototype.hasOwnProperty.call(flags, key)) return [];
  const value = flags[key];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (value === true || value == null) return [];
  return [String(value)].filter(Boolean);
}

function one(flags, key) {
  if (!Object.prototype.hasOwnProperty.call(flags, key)) return '';
  const value = flags[key];
  if (Array.isArray(value)) return String(value[value.length - 1] || '');
  if (value === true || value == null) return '';
  return String(value);
}

function gateName(gate) {
  return `${gate.program || 'program'}/${gate.id || gate.node_id || 'node'}`;
}

function matches(pattern, file) {
  if (!pattern) return false;
  const normalizedPattern = pattern.replace(/\\/g, '/');
  const normalizedFile = file.replace(/\\/g, '/');
  if (normalizedPattern === normalizedFile) return true;
  if (normalizedPattern.endsWith('/')) return normalizedFile.startsWith(normalizedPattern);
  const re = globToRegExp(normalizedPattern);
  return re.test(normalizedFile);
}

function globToRegExp(glob) {
  let out = '^';
  for (let i = 0; i < glob.length; i += 1) {
    const ch = glob[i];
    const next = glob[i + 1];
    if (ch === '*' && next === '*') {
      out += '.*';
      i += 1;
    } else if (ch === '*') {
      out += '[^/]*';
    } else if (ch === '?') {
      out += '[^/]';
    } else {
      out += ch.replace(/[|\\{}()[\]^$+?.]/g, '\\$&');
    }
  }
  out += '$';
  return new RegExp(out);
}

function escapeCell(value) {
  return String(value == null ? '-' : value).replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

function rel(root, p) {
  return path.relative(root, p).replace(/\\/g, '/') || '.';
}

function fail(message, code) {
  console.error(`ERROR ${message}`);
  process.exit(code);
}

main();
