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

const STEWARD_NODE_TYPES = new Set([
  'evidence',
  'decision',
  'authorization',
  'implementation',
  'closeout',
  'external',
]);

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
      case 'doc':
        refreshFunctionTreeDoc(root);
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
      case 'steward-sync':
        syncStewardProfile(root);
        break;
      case 'validate':
        validateGovernance(root, parsed.flags);
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
    '  ft-governance.cjs init <program> --ref <function-tree-node> [--description <text>] [--no-doc] [--root <repo>]',
    '  ft-governance.cjs doc [--root <repo>]',
    '  ft-governance.cjs new-node <program> <node-id> --title <text> --ref <function-tree-node> [--type <kind>] [--owner-lane <lane>] [--parent <id>] [--freshness <policy>] [--root <repo>]',
    '  ft-governance.cjs observe <program> <node-id> --evidence <path-or-note> [--kind <kind>] [--note <text>] [--root <repo>]',
    '  ft-governance.cjs authorize <program> <node-id> --allowed <path> --non-goal <text> --commit-gate <text> --closeout-gate <text> [--root <repo>]',
    '  ft-governance.cjs transition <program> <node-id> --to <status> [--note <text>] [--blocker <text>] [--unblock-target-state <status>] [--root <repo>]',
    '  ft-governance.cjs closeout <program> <node-id> --summary <path-or-note> [--compatibility <text>] [--gate <text>] [--root <repo>]',
    '  ft-governance.cjs install-guard [--force] [--root <repo>]',
    '  ft-governance.cjs repair [--root <repo>]',
    '  ft-governance.cjs status [--root <repo>]',
    '  ft-governance.cjs gate [--verbose] [--root <repo>]',
    '  ft-governance.cjs sync [--root <repo>]',
    '  ft-governance.cjs steward-sync [--root <repo>]',
    '  ft-governance.cjs validate [--steward] [--root <repo>]',
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

function refreshFunctionTreeDoc(root) {
  const result = writeFunctionTreeDoc(root, {});
  const output = [
    result.changed ? `updated ${rel(root, result.docPath)}` : `${rel(root, result.docPath)} unchanged`,
  ];
  if (result.backupPath) output.push(`backup: ${rel(root, result.backupPath)}`);
  console.log(output.join('\n'));
}

function writeFunctionTreeDoc(root, context) {
  const gov = path.join(root, '.governance');
  ensureDir(gov);
  const docPath = path.join(root, 'FUNCTION_TREE.md');
  const existing = fs.existsSync(docPath) ? readFile(docPath) : '';
  const existingTreeBody = extractExistingFunctionTreeBody(existing);
  const notes = extractProjectNotes(existing);
  const content = renderFunctionTreeDoc(root, context, existingTreeBody, notes);
  if (existing === content) return { docPath, backupPath: '', changed: false };

  let backupPath = '';
  if (existing) {
    backupPath = backupFunctionTreeDoc(root, existing);
  }
  writeFile(docPath, content);
  return { docPath, backupPath, changed: true };
}

function backupFunctionTreeDoc(root, content) {
  const backupDir = path.join(root, '.governance', 'backups');
  ensureDir(backupDir);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  let backupPath = path.join(backupDir, `FUNCTION_TREE.${stamp}.md`);
  let suffix = 1;
  while (fs.existsSync(backupPath)) {
    backupPath = path.join(backupDir, `FUNCTION_TREE.${stamp}.${suffix}.md`);
    suffix += 1;
  }
  writeFile(backupPath, content);
  return backupPath;
}

function extractProjectNotes(existing) {
  const match = existing.match(/<!-- function-tree:project-notes:start -->([\s\S]*?)<!-- function-tree:project-notes:end -->/);
  if (match) {
    const notes = match[1].trim();
    if (!notes || extractPreservedPreviousFunctionTree(notes)) return defaultProjectNotes();
    return notes;
  }
  return defaultProjectNotes();
}

function extractExistingFunctionTreeBody(existing) {
  if (!existing || !existing.trim()) return '';
  const preserved = extractPreservedPreviousFunctionTree(existing);
  if (preserved) return stripFunctionTreeTitle(preserved);

  const generated = existing.match(/<!-- function-tree:generated:start -->([\s\S]*?)<!-- function-tree:generated:end -->/);
  if (generated) {
    const body = stripGeneratedDocPreamble(generated[1]);
    if (looksLikeFunctionTreeBody(body) && !isRefreshableGeneratedFunctionTreeBody(body)) return body;
    return '';
  }

  const withoutGenerated = stripGeneratedFunctionTreeSection(existing)
    .replace(/<!-- function-tree:project-notes:start -->[\s\S]*?<!-- function-tree:project-notes:end -->/g, '')
    .trim();
  if (!withoutGenerated) return '';
  return stripFunctionTreeTitle(withoutGenerated);
}

function extractPreservedPreviousFunctionTree(value) {
  const marker = '## Preserved Previous FUNCTION_TREE.md Content';
  const index = value.indexOf(marker);
  if (index < 0) return '';
  const rest = value.slice(index + marker.length).trim();
  return rest.replace(/^The following content came from the pre-existing `FUNCTION_TREE\.md` before function-tree generated sections were added\.\s*/i, '').trim();
}

function stripGeneratedFunctionTreeSection(existing) {
  return existing.replace(/<!-- function-tree:generated:start -->[\s\S]*?<!-- function-tree:generated:end -->/g, '').trim();
}

function stripFunctionTreeTitle(value) {
  return String(value || '').trim().replace(/^#\s+FUNCTION_TREE\s*/i, '').trim();
}

function stripGeneratedDocPreamble(value) {
  return String(value || '')
    .trim()
    .replace(/^Generated by the `function-tree` skill\.[^\n]*\n+/i, '')
    .trim();
}

function looksLikeFunctionTreeBody(value) {
  return /##\s+(功能全景图|状态注册表|模块\/命令证据展开|模块依赖关系|Feature Map|Status Registry|Dependency Map)/i.test(String(value || ''));
}

function isRefreshableGeneratedFunctionTreeBody(value) {
  const body = String(value || '');
  return (
    /\|\s*Node\s*\|\s*Type\s*\|\s*Status\s*\|\s*Evidence\s*\/\s*Notes\s*\|/i.test(body) ||
    /Auto-discovered (existing feature|planned\/unfinished|source modules|project commands)/i.test(body) ||
    /Existing feature candidates:/.test(body) ||
    /Add README\/API\/product feature bullets/.test(body)
  );
}

function defaultProjectNotes() {
  return [
    '- Add project-specific architecture notes here.',
    '- Add local build, test, release, and compliance gates here.',
    '- Keep long-lived project conventions here; keep task state in `.governance/`.',
  ].join('\n');
}

function renderFunctionTreeDoc(root, context, existingTreeBody, notes) {
  const info = collectProjectInfo(root);
  const programs = collectGovernancePrograms(root, context);
  const programRows = programs.length ? programs.map((program) => [
    program.name,
    program.ref || '-',
    program.description || '-',
    String(program.nodeCount),
    String(program.activeCount),
    program.treePath,
  ]) : [['-', '-', '-', '0', '0', '-']];
  const treeBody = existingTreeBody && looksLikeFunctionTreeBody(existingTreeBody)
    ? existingTreeBody
    : renderDefaultFunctionTreeBody(root, context, info, programs, programRows);

  return [
    '# FUNCTION_TREE',
    '',
    '<!-- function-tree:generated:start -->',
    'Generated by the `function-tree` skill. Refresh this file with `ft-governance.cjs doc --root <repo>`.',
    '',
    treeBody,
    '<!-- function-tree:generated:end -->',
    '',
    '<!-- function-tree:project-notes:start -->',
    notes,
    '<!-- function-tree:project-notes:end -->',
    '',
  ].join('\n');
}

function renderDefaultFunctionTreeBody(root, context, info, programs, programRows) {
  const logProgram = context.program || (programs[0] && programs[0].name) || 'project-governance';
  const logRef = context.ref || (programs[0] && programs[0].ref) || 'unmapped';
  const featureRows = info.featureCandidates.length
    ? info.featureCandidates.map((feature) => `| ${escapeCell(feature.name)} | ${escapeCell(feature.type)} | ${escapeCell(feature.status)} | ${escapeCell(feature.evidence)}; ${escapeCell(feature.boundary)} |`)
    : ['| - | feature candidate | 待登记 | Add README/API/product feature bullets, then rerun `doc`. |'];
  const moduleRows = info.sourceModules.length
    ? info.sourceModules.map((module) => module.fileCount
      ? `| \`${module.path}\` | module dir | 待核验 | ${module.fileCount} source files; map to capability nodes after review. |`
      : `| \`${module.path}\` | module | 待核验 | Auto-discovered source module; map to a capability node after review. |`)
    : [];
  const sourceRows = info.sourceRoots.length
    ? info.sourceRoots.map((source) => `| \`${source}\` | source root | 待登记 | Map modules under this root into capability nodes. |`)
    : ['| - | source root | 待登记 | Add source roots after project structure is known. |'];
  const docRows = info.docs.length
    ? info.docs.map((doc) => `| \`${doc}\` | documentation | 已登记 | Use as evidence when mapping feature ownership. |`)
    : ['| - | documentation | 待登记 | Add architecture, API, or operation docs as evidence. |'];
  const commandRows = info.commandEntries.length
    ? info.commandEntries.map((command) => `| \`${command.command}\` | ${escapeCell(command.purpose)} | 待核验 | Evidence: \`${command.evidence}\` |`)
    : [];
  const uiRows = info.uiEntries.length
    ? info.uiEntries.map((entry) => `| \`${entry.route}\` | ${escapeCell(entry.source)} | 待核验 | Evidence: \`${entry.evidence}\` |`)
    : ['| - | UI route | 待登记 | Add frontend page files or router definitions to register UI entrypoints. |'];
  const apiRows = info.apiEntries.length
    ? info.apiEntries.map((entry) => `| \`${entry.method} ${entry.path}\` | ${escapeCell(entry.source)} | 待核验 | Evidence: \`${entry.evidence}\` |`)
    : ['| - | API route | 待登记 | Add OpenAPI specs or route definitions to register service/API entrypoints. |'];
  const publicApiRows = info.publicApiEntries && info.publicApiEntries.length
    ? info.publicApiEntries.map((entry) => `| \`${entry.module}\` | public API | 已登记 | ${entry.count} exports: ${entry.exports.slice(0, 8).join(', ')}${entry.count > 8 ? ', ...' : ''} (evidence: \`${entry.evidence}\`) |`)
    : ['| - | public API | 待登记 | Python packages with `__all__` or JS modules with named exports will be detected. |'];
  const docSystemRows = info.docSystemInfo && info.docSystemInfo.length
    ? info.docSystemInfo.map((entry) => `| ${escapeCell(entry.system)} | doc system | 已登记 | ${escapeCell(entry.detail)} (evidence: \`${entry.evidence}\`) |`)
    : ['| - | doc system | 待登记 | Sphinx, MkDocs, Docusaurus, and other doc systems will be auto-detected. |'];
  const exceptionRows = info.exceptionEntries && info.exceptionEntries.length
    ? info.exceptionEntries.map((entry) => `| \`${entry.name}\` | exception | 已登记 | extends \`${entry.parent}\`; source: \`${entry.module}\` |`)
    : [];
  const configRows = info.configEntries && info.configEntries.length
    ? info.configEntries.map((entry) => `| \`${entry.evidence}\` | ${escapeCell(entry.type)} | 已登记 | ${escapeCell(entry.detail)} |`)
    : [];
  const depRows = info.dependencyEntries && info.dependencyEntries.length
    ? info.dependencyEntries.map((entry) => `| \`${entry.name}\` | ${escapeCell(entry.category)} | 已登记 | ${escapeCell(entry.evidence)} |`)
    : [];
  const plannedRows = info.plannedCandidates.length
    ? info.plannedCandidates.map((feature) => `| ${escapeCell(feature.name)} | 待实现 | ${escapeCell(feature.evidence)} | ${escapeCell(feature.boundary || 'Auto-discovered planned/unfinished item; verify scope and owner before implementation.')} |`)
    : ['| - | 待登记 | - | Add planned/unfinished features from roadmap, TODO, or product notes. |'];
  const programLines = programs.length
    ? programs.map((program) => `- Governance: ${program.name} (${program.ref || 'unmapped'}): ${program.description || 'governance program'}`)
    : ['- Governance: add programs with `/ft:init` or `new-node`.'];
  const featureLines = info.featureCandidates.length
    ? info.featureCandidates.flatMap(renderFeatureOverviewLines)
    : ['- Existing feature candidates: 待登记'];
  const plannedLines = info.plannedCandidates.length
    ? info.plannedCandidates.map((feature) => `- Planned/unfinished: ${feature.name} [${feature.type || 'planned'}] (${feature.evidence})`)
    : ['- Planned/unfinished: 待登记'];
  const programTable = programRows.map((row) => `| ${row.map(escapeCell).join(' | ')} |`);

  return [
    '## 注册规则',
    '',
    '- 本文件是项目功能树与功能状态注册表；不要用 issue、PR 或临时报告替代它记录长期功能状态。',
    '- 本文件描述当前/未来项目的功能树：既登记已有功能，也登记计划/未完成功能。',
    '- 本文件是开发者方向指引；新增实现、重构和规划都应回到这里校准，避免方向失联或跑偏。',
    '- 以功能/能力为主线组织内容，再挂接模块、命令、证据和依赖关系。',
    '- 状态建议使用：`已实现`、`部分实现`、`设计中`、`待实现`、`暂停`、`废弃`。',
    '- 使用 `function-tree` skill（function tree）或 `/ft:*` 命令维护治理节点、证据、授权范围和 closeout。',
    '- 生成区可由 `ft-governance.cjs doc --root <repo>` 刷新；长期项目约定写入 project-notes 区块。',
    '',
    '## 功能全景图',
    '',
    `- Project: ${info.name}`,
    ...featureLines,
    ...plannedLines,
    ...programLines,
    info.sourceRoots.length ? `- Source roots: ${formatList(info.sourceRoots)}` : '- Source roots: 待登记',
    info.docs.length ? `- Documentation: ${formatList(info.docs)}` : '- Documentation: 待登记',
    '',
    '## 状态注册表',
    '',
    '### 模块/能力节点',
    '',
    '| Node | Type | Status | Evidence / Notes |',
    '|------|------|--------|------------------|',
    `| ${escapeCell(info.name)} | project | 已登记 | HEAD: \`${info.head || 'unknown'}\`; root: \`${root}\` |`,
    ...featureRows,
    ...moduleRows,
    ...sourceRows,
    ...docRows,
    '',
    '### CLI/运营入口节点',
    '',
    '| Command | Purpose | Status | Notes |',
    '|---------|---------|--------|-------|',
    '| `/ft:init` | initialize governance and FUNCTION_TREE files | 已实现 | backs up existing `FUNCTION_TREE.md` before refresh |',
    '| `/ft:status` | show programs and active gates | 已实现 | helper: `status` |',
    '| `/ft:gate` | show current blockers and allowed scope | 已实现 | helper: `gate --verbose` |',
    '| `/ft:observe` | collect baseline evidence | 已实现 | evidence is required before authorization |',
    '| `/ft:authorize` | prepare allowed paths, non-goals, and gates | 已实现 | source edits remain disabled until approval transition |',
    '| `/ft:closeout` | record landed summary and verification gates | 已实现 | close node after review |',
    ...commandRows,
    '',
    '### UI/页面入口节点',
    '',
    '| Route | Source | Status | Notes |',
    '|-------|--------|--------|-------|',
    ...uiRows,
    '',
    '### API/服务入口节点',
    '',
    '| Endpoint | Source | Status | Notes |',
    '|----------|--------|--------|-------|',
    ...apiRows,
    '',
    '### Public API Surface (__all__ exports)',
    '',
    '| Module | Type | Status | Exports / Notes |',
    '|--------|------|--------|-----------------|',
    ...publicApiRows,
    '',
    '### Documentation System',
    '',
    '| System | Type | Status | Notes |',
    '|--------|------|--------|-------|',
    ...docSystemRows,
    '',
    ...(exceptionRows.length ? [
      '### Exception Hierarchy',
      '',
      '| Exception | Type | Status | Notes |',
      '|-----------|------|--------|-------|',
      ...exceptionRows,
      '',
    ] : []),
    ...(configRows.length ? [
      '### Configuration & Environment',
      '',
      '| Entry | Type | Status | Notes |',
      '|-------|------|--------|-------|',
      ...configRows,
      '',
    ] : []),
    ...(depRows.length ? [
      '### Core Dependencies',
      '',
      '| Package | Category | Status | Evidence |',
      '|---------|----------|--------|----------|',
      ...depRows,
      '',
    ] : []),
    '### 已设计/待实现节点',
    '',
    '| 功能节点 | 状态 | 证据 | 边界 |',
    '|---|---|---|---|',
    ...plannedRows,
    '',
    '### 治理计划/开放节点',
    '',
    '| Program | FUNCTION_TREE ref | Description | Nodes | Active gates | Tree |',
    '|---------|-------------------|-------------|-------|--------------|------|',
    ...programTable,
    '',
    '## 模块/命令证据展开',
    '',
    ...renderCandidateEvidenceLines(info),
    '- `.governance/programs/<program>/tree.md` records the program entrypoint and FUNCTION_TREE ref.',
    '- `.governance/programs/<program>/nodes.json` records node status, evidence, authorization, and closeout.',
    '- `.governance/programs/<program>/cards/*.yaml` stores generated authorization task cards.',
    '- `.governance/active-gates.json` and `.governance/active-gates.md` summarize currently open gates.',
    '',
    '## CLI 命令证据展开',
    '',
    '- `/ft:new-node <program> <node-id>` creates a planning node.',
    '- `/ft:observe <program> <node-id> --evidence <path-or-note>` records evidence at current HEAD.',
    '- `/ft:transition <program> <node-id> --to <status>` enforces the legal state machine.',
    '- `/ft:implement` runs `scope-check` against active authorization.',
    '- `/ft:doc` refreshes this document and creates backups when content changes.',
    '',
    '## 模块依赖关系',
    '',
    '- `FUNCTION_TREE.md` is the human-readable feature tree and status registry.',
    '- `.governance/active-gates.json` feeds active gate summaries and scope checks.',
    '- `.governance/programs/*/nodes.json` feeds node state, task cards, and closeout history.',
    '- Source modules and CLI entries should be attached to feature nodes as evidence is collected.',
    '',
    '## 更新日志',
    '',
    `- Initialized by function-tree for ${logProgram} (${logRef}).`,
    '',
    '## 开放事项',
    '',
    '- Replace placeholder rows with project-specific capability nodes.',
    '- Add source-module evidence as nodes move through observe and authorize gates.',
    '- Add dependency notes when feature ownership spans multiple modules or commands.',
    '',
    '## 维护规则',
    '',
    '- Keep generated governance state in `.governance/`; keep durable project conventions in project notes.',
    '- Backups of prior `FUNCTION_TREE.md` files are stored under `.governance/backups/`.',
    '- Do not hand-edit generated active gate markdown; change node state through the helper.',
  ].join('\n');
}

function collectProjectInfo(root) {
  const sourceRoots = existingPaths(root, [
    'src',
    'app',
    'lib',
    'packages',
    'crates',
    'services',
    'cmd',
    'internal',
    'tests',
    'test',
  ]);
  for (const pkgRoot of detectPythonPackageRoots(root)) {
    if (!sourceRoots.includes(pkgRoot)) sourceRoots.push(pkgRoot);
  }
  const manifests = existingPaths(root, [
    'package.json',
    'pyproject.toml',
    'Cargo.toml',
    'go.mod',
    'pom.xml',
    'build.gradle',
    'requirements.txt',
    'deno.json',
    'composer.json',
    'Gemfile',
  ]);
  const docs = existingPaths(root, [
    'README.md',
    'AGENTS.md',
    'CLAUDE.md',
    'CONTRIBUTING.md',
    'docs',
  ]);
  const commandEntries = collectCommandEntries(root);
  const uiEntries = collectUiEntries(root, sourceRoots);
  const apiEntries = collectApiEntries(root, sourceRoots);
  const featureCandidates = uniqueCandidates([
    ...collectFeatureCandidates(root),
    ...collectEntrypointFeatureCandidates(uiEntries, apiEntries, commandEntries),
  ], 16);

  return {
    name: detectProjectName(root),
    head: gitHead(root),
    manifests,
    docs,
    sourceRoots,
    featureCandidates,
    plannedCandidates: collectPlannedFeatureCandidates(root, sourceRoots),
    publicApiEntries: collectPublicApiEntries(root, sourceRoots),
    sourceModules: collectSourceModules(root, sourceRoots),
    commandEntries,
    uiEntries,
    apiEntries,
    docSystemInfo: collectDocSystemInfo(root),
    exceptionEntries: collectExceptionHierarchy(root, sourceRoots),
    configEntries: collectConfigEntries(root, sourceRoots),
    dependencyEntries: collectDependencyEntries(root),
  };
}

function renderCandidateEvidenceLines(info) {
  const lines = [];
  if (info.featureCandidates.length) {
    lines.push('- Auto-discovered existing feature candidates:');
    for (const feature of info.featureCandidates) {
      lines.push(`  - ${feature.name}: ${feature.evidence}`);
    }
  }
  if (info.plannedCandidates.length) {
    lines.push('- Auto-discovered planned/unfinished feature candidates:');
    for (const feature of info.plannedCandidates) {
      lines.push(`  - ${feature.name}: ${feature.evidence}`);
    }
  }
  if (info.sourceModules.length) {
    lines.push('- Auto-discovered source modules:');
    for (const module of info.sourceModules) {
      lines.push(`  - \`${module.path}\``);
    }
  }
  if (info.commandEntries.length) {
    lines.push('- Auto-discovered project commands:');
    for (const command of info.commandEntries) {
      lines.push(`  - \`${command.command}\`: ${command.evidence}`);
    }
  }
  if (info.uiEntries.length) {
    lines.push('- Auto-discovered UI/page routes:');
    for (const entry of info.uiEntries) {
      lines.push(`  - \`${entry.route}\`: ${entry.evidence}`);
    }
  }
  if (info.apiEntries.length) {
    lines.push('- Auto-discovered API/service routes:');
    for (const entry of info.apiEntries) {
      lines.push(`  - \`${entry.method} ${entry.path}\`: ${entry.evidence}`);
    }
  }
  if (info.publicApiEntries && info.publicApiEntries.length) {
    lines.push('- Auto-discovered public API (__all__ exports):');
    for (const entry of info.publicApiEntries) {
      lines.push(`  - \`${entry.module}\`: ${entry.count} exports (${entry.exports.slice(0, 5).join(', ')}${entry.count > 5 ? ', ...' : ''})`);
    }
  }
  if (info.docSystemInfo && info.docSystemInfo.length) {
    lines.push('- Auto-discovered documentation systems:');
    for (const entry of info.docSystemInfo) {
      lines.push(`  - ${entry.system}: ${entry.evidence} (${entry.detail})`);
    }
  }
  if (info.exceptionEntries && info.exceptionEntries.length) {
    lines.push('- Auto-discovered exception hierarchy:');
    for (const entry of info.exceptionEntries) {
      lines.push(`  - \`${entry.name}\` extends \`${entry.parent}\` (source: \`${entry.module}\`)`);
    }
  }
  if (info.configEntries && info.configEntries.length) {
    lines.push('- Auto-discovered configuration/environment:');
    for (const entry of info.configEntries) {
      lines.push(`  - [${entry.type}] \`${entry.evidence}\`: ${entry.detail}`);
    }
  }
  if (info.dependencyEntries && info.dependencyEntries.length) {
    lines.push('- Auto-discovered core dependencies:');
    for (const entry of info.dependencyEntries) {
      lines.push(`  - \`${entry.name}\` [${entry.category}]`);
    }
  }
  if (lines.length) lines.push('');
  return lines;
}

function collectFeatureCandidates(root) {
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'FEATURES.md', 'docs/README.md', 'docs/features.md', 'docs/FEATURES.md'], 'existing'),
  ], 16);
}

function renderFeatureOverviewLines(feature) {
  const lines = [
    `- ${feature.name}`,
    `  - Status: ${feature.status || '待核验'}`,
    `  - Type: ${feature.type || 'feature candidate'}`,
  ];
  const evidence = splitEvidenceItems(feature.evidence);
  if (evidence.length) {
    lines.push('  - Evidence:');
    for (const item of evidence) lines.push(`    - ${item}`);
  } else {
    lines.push('  - Evidence: 待登记');
  }
  if (feature.boundary) lines.push(`  - Boundary: ${feature.boundary}`);
  return lines;
}

function splitEvidenceItems(value) {
  return String(value || '')
    .split(/;\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function collectEntrypointFeatureCandidates(uiEntries, apiEntries, commandEntries) {
  const groups = new Map();

  function ensureGroup(key, name) {
    if (!key || !isUsefulCandidateName(name)) return null;
    if (!groups.has(key)) {
      groups.set(key, {
        name,
        evidence: [],
      });
    }
    return groups.get(key);
  }

  function addEvidence(group, evidence) {
    if (!group || group.evidence.includes(evidence)) return;
    group.evidence.push(evidence);
  }

  for (const entry of uiEntries) {
    const name = humanizeRouteFeatureName(entry.route);
    const group = ensureGroup(featureKey(name), name);
    addEvidence(group, `UI route \`${entry.route}\` (${entry.evidence})`);
  }
  for (const entry of apiEntries) {
    const baseName = humanizeRouteFeatureName(entry.path);
    const baseKey = featureKey(baseName);
    const group = groups.get(baseKey) || ensureGroup(featureKey(`${baseName} API`), `${baseName} API`);
    addEvidence(group, `API route \`${entry.method} ${entry.path}\` (${entry.evidence})`);
  }
  for (const command of commandEntries) {
    const key = matchingFeatureKeyForCommand(command, groups.keys());
    if (!key) continue;
    addEvidence(groups.get(key), `Command \`${command.command}\` (${command.evidence})`);
  }

  return uniqueCandidates(Array.from(groups.values()).map((group) => ({
    name: group.name,
    type: 'entrypoint feature',
    status: '待核验',
    evidence: group.evidence.join('; '),
    boundary: 'Entrypoint-derived capability; verify product intent, owner, contracts, and completeness before marking implemented.',
  })), 16);
}

function collectPlannedFeatureCandidates(root, sourceRoots) {
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'ROADMAP.md', 'TODO.md', 'docs/roadmap.md', 'docs/ROADMAP.md', 'docs/todo.md', 'docs/TODO.md'], 'planned'),
    ...collectSourceTodoCandidates(root, sourceRoots),
  ], 16);
}

function collectMarkdownCandidates(root, relativePaths, mode) {
  const candidates = [];
  for (const relativePath of existingPaths(root, relativePaths)) {
    const text = readFile(path.join(root, relativePath));
    let heading = '';
    for (const line of text.split(/\r?\n/)) {
      const headingMatch = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
      if (headingMatch) {
        heading = cleanMarkdownText(headingMatch[1]);
        continue;
      }
      const bulletMatch = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$/);
      if (!bulletMatch || !headingMatchesCandidateMode(heading, mode)) continue;
      const name = cleanMarkdownText(bulletMatch[1]);
      if (!isUsefulCandidateName(name)) continue;
      candidates.push({
        name,
        type: mode === 'planned' ? 'planned feature' : 'feature candidate',
        status: mode === 'planned' ? '待实现' : '待核验',
        evidence: heading ? `${relativePath} > ${heading}` : relativePath,
        boundary: mode === 'planned'
          ? 'Roadmap item; do not treat as implemented until evidence is added.'
          : 'README-listed capability; verify implementation and owner before marking implemented.',
      });
    }
  }
  return candidates;
}

function headingMatchesCandidateMode(heading, mode) {
  const value = String(heading || '').toLowerCase();
  const planned = /(roadmap|todo|planned|future|backlog|later|next|计划|规划|路线图|未完成|待实现|后续)/i.test(value);
  const existing = /(feature|capabilit|function|module|功能|能力|模块|特性|产品)/i.test(value);
  return mode === 'planned' ? planned : existing && !planned;
}

function cleanMarkdownText(value) {
  return String(value || '')
    .replace(/^\[[ xX]\]\s+/, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/[：:。.,，；;]+$/g, '')
    .trim()
    .slice(0, 96);
}

function isUsefulCandidateName(value) {
  if (!value || value.length < 2) return false;
  if (/^https?:\/\//i.test(value)) return false;
  if (/^(todo|tbd|n\/a|none)$/i.test(value)) return false;
  return true;
}

function humanizeRouteFeatureName(routePath) {
  const parts = String(routePath || '')
    .split(/[?#]/)[0]
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean)
    .filter((segment) => !/^v\d+$/i.test(segment))
    .filter((segment) => !isDynamicRouteSegment(segment))
    .map(cleanRouteSegment)
    .filter(Boolean);
  if (!parts.length) return 'Home';
  return titleCase(parts.join(' '));
}

function isDynamicRouteSegment(segment) {
  return /^\[.+\]$/.test(segment)
    || /^:.+/.test(segment)
    || /^\{.+\}$/.test(segment)
    || /^\(.+\)$/.test(segment);
}

function cleanRouteSegment(segment) {
  let value = String(segment || '').replace(/^\[+|\]+$/g, '');
  try {
    value = decodeURIComponent(value);
  } catch (_) {
    // Keep the raw segment if it is not URI-encoded text.
  }
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/[^A-Za-z0-9\u4e00-\u9fff ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function titleCase(value) {
  return String(value || '').replace(/\b[A-Za-z0-9]/g, (char) => char.toUpperCase());
}

function featureKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/api$/i, '')
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
}

function matchingFeatureKeyForCommand(command, featureKeys) {
  const haystack = featureKey(`${command.command} ${command.purpose || ''}`);
  for (const key of featureKeys) {
    if (key.length >= 4 && haystack.includes(key)) return key;
  }
  return '';
}

function uniqueCandidates(candidates, limit) {
  const seen = new Set();
  const unique = [];
  for (const candidate of candidates) {
    const key = candidate.name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(candidate);
    if (unique.length >= limit) break;
  }
  return unique;
}

function collectSourceTodoCandidates(root, sourceRoots) {
  const candidates = [];
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    const isTestFile = /(^|[\/\\])(tests?|spec|__tests__|test_)[\/\\]/i.test(file) || /[_-]test[_\.]|[_\.]spec[_\.]|[_\.]test[_\.]/i.test(file);
    const text = readFile(path.join(root, file));
    const lines = text.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      // Only match TODOs in comment context to avoid string literal false positives
      const isCommentContext = /^\s*(#|\/\/|\/\*|<!--|;\s*|%\s*)/.test(line) ||
        /(?:#\s*|\/\/\s*|\/\*\s*|<!--\s*|;\s*|%\s*)(?:TODO|FIXME|XXX|HACK)\b/i.test(line);
      if (!isCommentContext) continue;
      const match = line.match(/\b(?:TODO|FIXME|XXX|HACK)\b[:\-\s]*(.+)$/i);
      if (!match) continue;
      const name = cleanMarkdownText(match[1]);
      if (!isUsefulCandidateName(name)) continue;
      if (isTestFile) {
        candidates.push({
          name,
          type: 'test improvement',
          status: '待实现',
          evidence: `${file}:${index + 1}`,
          boundary: 'Test improvement TODO; not a product roadmap item. Verify scope before implementation.',
        });
      } else {
        candidates.push({
          name,
          type: 'source TODO',
          status: '待实现',
          evidence: `${file}:${index + 1}`,
          boundary: 'Source code TODO; verify intent, owner, and priority before implementation.',
        });
      }
      if (candidates.length >= 48) return candidates;
    }
  }
  return candidates;
}

function collectSourceFiles(root, sourceRoots, limit) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const sourceFilePattern = /\.(js|jsx|ts|tsx|py|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp)$/i;
  const files = [];

  function walk(relativeDir) {
    if (files.length >= limit) return;
    const absoluteDir = path.join(root, relativeDir);
    if (!fs.existsSync(absoluteDir) || !fs.statSync(absoluteDir).isDirectory()) return;
    for (const entry of fs.readdirSync(absoluteDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (files.length >= limit) return;
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      const relativePath = `${relativeDir}/${entry.name}`;
      if (entry.isDirectory()) {
        walk(relativePath);
      } else if (sourceFilePattern.test(entry.name)) {
        files.push(relativePath);
      }
    }
  }

  for (const sourceRoot of sourceRoots) walk(sourceRoot);
  return files;
}

function collectUiEntries(root, sourceRoots) {
  return uniqueUiEntries([
    ...collectFileBasedUiEntries(root),
    ...collectNavigationUiEntries(root, sourceRoots),
    ...collectSourceUiRouteEntries(root, sourceRoots),
  ], 32);
}

function collectFileBasedUiEntries(root) {
  const entries = [];
  for (const file of collectFilesUnder(root, 'app', 200, (name) => /^page\.(js|jsx|ts|tsx|mdx)$/i.test(name))) {
    const route = nextAppRouteFromFile(file);
    if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'Next app router'));
  }
  for (const file of collectFilesUnder(root, 'pages', 200, (name) => /\.(js|jsx|ts|tsx|mdx)$/i.test(name))) {
    const route = nextPagesRouteFromFile(file);
    if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'Next pages router'));
  }
  for (const file of collectFilesUnder(root, 'src/routes', 200, (name) => /^\+page\.(svelte|js|ts)$/i.test(name))) {
    const route = svelteKitRouteFromFile(file);
    if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'SvelteKit route'));
  }
  return entries;
}

function collectFilesUnder(root, relativeDir, limit, acceptFileName) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const files = [];

  function walk(currentDir) {
    if (files.length >= limit) return;
    const absoluteDir = path.join(root, currentDir);
    if (!fs.existsSync(absoluteDir) || !fs.statSync(absoluteDir).isDirectory()) return;
    for (const entry of fs.readdirSync(absoluteDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (files.length >= limit) return;
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      const relativePath = `${currentDir}/${entry.name}`;
      if (entry.isDirectory()) {
        walk(relativePath);
      } else if (acceptFileName(entry.name)) {
        files.push(relativePath);
      }
    }
  }

  walk(relativeDir);
  return files;
}

function nextAppRouteFromFile(relativePath) {
  const parts = relativePath.split('/').slice(1);
  const fileName = parts.pop();
  if (!fileName || !/^page\./i.test(fileName)) return '';
  const routeParts = parts.filter((part) => !isPathlessUiSegment(part));
  return normalizeUiRoute(routeParts.length ? routeParts.join('/') : '/');
}

function nextPagesRouteFromFile(relativePath) {
  const parts = relativePath.split('/').slice(1);
  if (!parts.length || /^api$/i.test(parts[0])) return '';
  const fileName = parts.pop() || '';
  const pageName = fileName.replace(/\.(js|jsx|ts|tsx|mdx)$/i, '');
  if (!pageName || pageName.startsWith('_')) return '';
  if (pageName !== 'index') parts.push(pageName);
  if (parts.some((part) => part.startsWith('_'))) return '';
  return normalizeUiRoute(parts.length ? parts.join('/') : '/');
}

function svelteKitRouteFromFile(relativePath) {
  const parts = relativePath.split('/').slice(2);
  const fileName = parts.pop();
  if (!fileName || !/^\+page\./i.test(fileName)) return '';
  const routeParts = parts.filter((part) => !isPathlessUiSegment(part));
  return normalizeUiRoute(routeParts.length ? routeParts.join('/') : '/');
}

function isPathlessUiSegment(part) {
  return /^\(.+\)$/.test(String(part || ''));
}

function collectNavigationUiEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    if (!isNavigationUiFile(file)) continue;
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const route of sourceNavigationRouteMatches(lines[index])) {
        entries.push(uiEntry(route, `${file}:${index + 1}`, 'navigation/menu'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

function isNavigationUiFile(file) {
  return /(^|[._/-])(nav|navigation|menu|sidebar|sidenav|side-nav|routes?|links?|tabs?)([._/-]|$)/i.test(String(file || ''));
}

function sourceNavigationRouteMatches(line) {
  const matches = [];
  const patterns = [
    /\b(?:href|to|url)\s*:\s*["']([^"']+)["']/g,
    /<(?:Link|NavLink|a)\b[^>]*\b(?:href|to)\s*=\s*["']([^"']+)["']/g,
    /\brouterLink\s*=\s*["']([^"']+)["']/g,
  ];
  for (const pattern of patterns) {
    for (const match of line.matchAll(pattern)) {
      if (isUsefulUiRoute(match[1])) matches.push(match[1]);
    }
  }
  return matches;
}

function collectSourceUiRouteEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 400)) {
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const route of sourceUiRouteMatches(lines[index])) {
        entries.push(uiEntry(route, `${file}:${index + 1}`, 'source router'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

function sourceUiRouteMatches(line) {
  const matches = [];
  const patterns = [
    /<Route\b[^>]*\bpath\s*=\s*["']([^"']+)["']/g,
    /\bpath\s*:\s*["']([^"']+)["']/g,
  ];
  for (const pattern of patterns) {
    for (const match of line.matchAll(pattern)) {
      if (isUsefulUiRoute(match[1])) matches.push(match[1]);
    }
  }
  return matches;
}

function uiEntry(route, evidence, source) {
  return {
    route: normalizeUiRoute(route),
    evidence,
    source,
  };
}

function normalizeUiRoute(value) {
  let route = String(value || '').trim();
  if (!route) return '';
  if (!route.startsWith('/')) route = `/${route}`;
  route = route.replace(/\/+/g, '/');
  if (route.length > 1) route = route.replace(/\/$/, '');
  return route || '/';
}

function isUsefulUiRoute(value) {
  const route = normalizeUiRoute(value);
  return route.startsWith('/')
    && !/^\/api(?:\/|$)/i.test(route)
    && !route.includes('*')
    && !route.includes('${');
}

function uniqueUiEntries(entries, limit) {
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    if (!entry.route || !isUsefulUiRoute(entry.route)) continue;
    const key = normalizeUiRoute(entry.route);
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push({ ...entry, route: key });
    if (unique.length >= limit) break;
  }
  return unique;
}

function collectApiEntries(root, sourceRoots) {
  return uniqueApiEntries([
    ...collectOpenApiEntries(root),
    ...collectSourceRouteEntries(root, sourceRoots),
  ], 32);
}

function collectOpenApiEntries(root) {
  const entries = [];
  const specs = existingPaths(root, [
    'openapi.json',
    'openapi.yaml',
    'openapi.yml',
    'docs/openapi.json',
    'docs/openapi.yaml',
    'docs/openapi.yml',
    'docs/api/openapi.json',
    'docs/api/openapi.yaml',
    'docs/api/openapi.yml',
  ]);

  for (const spec of specs) {
    const absolutePath = path.join(root, spec);
    if (/\.json$/i.test(spec)) {
      try {
        const parsed = JSON.parse(readFile(absolutePath));
        const paths = parsed && parsed.paths && typeof parsed.paths === 'object' ? parsed.paths : {};
        for (const routePath of Object.keys(paths).sort()) {
          const methods = paths[routePath] && typeof paths[routePath] === 'object' ? paths[routePath] : {};
          for (const method of Object.keys(methods).sort()) {
            if (isHttpMethod(method)) entries.push(apiEntry(method, routePath, spec, 'OpenAPI'));
          }
        }
      } catch (_) {
        // Invalid JSON should not block FUNCTION_TREE generation.
      }
      continue;
    }

    let currentPath = '';
    for (const line of readFile(absolutePath).split(/\r?\n/)) {
      const pathMatch = line.match(/^\s{1,8}["']?(\/[^"':]+)["']?\s*:\s*(?:#.*)?$/);
      if (pathMatch) {
        currentPath = pathMatch[1];
        continue;
      }
      const methodMatch = line.match(/^\s{2,10}(get|post|put|patch|delete|options|head)\s*:\s*(?:#.*)?$/i);
      if (currentPath && methodMatch) entries.push(apiEntry(methodMatch[1], currentPath, spec, 'OpenAPI'));
    }
  }
  return entries;
}

function collectSourceRouteEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 400)) {
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const match of sourceRouteMatches(lines[index])) {
        entries.push(apiEntry(match.method, match.path, `${file}:${index + 1}`, 'source route'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

function sourceRouteMatches(line) {
  const matches = [];
  const patterns = [
    /\b(?:app|router|server|fastify)\s*\.\s*(get|post|put|patch|delete|options|head)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
    /@\s*(?:app|router|api)\s*\.\s*(get|post|put|patch|delete|options|head)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
  ];
  for (const pattern of patterns) {
    for (const match of line.matchAll(pattern)) {
      if (isUsefulApiPath(match[2])) matches.push({ method: match[1], path: match[2] });
    }
  }

  const axumMatch = line.match(/\.route\s*\(\s*['"`]([^'"`]+)['"`]\s*,\s*(get|post|put|patch|delete|options|head)\s*\(/i);
  if (axumMatch && isUsefulApiPath(axumMatch[1])) matches.push({ method: axumMatch[2], path: axumMatch[1] });
  return matches;
}

function apiEntry(method, routePath, evidence, source) {
  return {
    method: String(method || '').toUpperCase(),
    path: String(routePath || '').trim(),
    evidence,
    source,
  };
}

function isHttpMethod(value) {
  return /^(get|post|put|patch|delete|options|head)$/i.test(String(value || ''));
}

function isUsefulApiPath(value) {
  const routePath = String(value || '').trim();
  return routePath.startsWith('/') && routePath.length > 1 && !routePath.includes('${');
}

function uniqueApiEntries(entries, limit) {
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    if (!entry.method || !isUsefulApiPath(entry.path)) continue;
    const key = `${entry.method} ${entry.path}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(entry);
    if (unique.length >= limit) break;
  }
  return unique;
}

function collectSourceModules(root, sourceRoots) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const modules = [];
  for (const sourceRoot of sourceRoots) {
    const absoluteRoot = path.join(root, sourceRoot);
    if (!fs.existsSync(absoluteRoot) || !fs.statSync(absoluteRoot).isDirectory()) continue;
    for (const entry of fs.readdirSync(absoluteRoot, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      const isSource = entry.isDirectory() || /\.(js|jsx|ts|tsx|py|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp)$/i.test(entry.name);
      if (!isSource) continue;
      const relativePath = `${sourceRoot}/${entry.name}${entry.isDirectory() ? '/' : ''}`;
      modules.push({ path: relativePath });
      if (modules.length >= 48) break;
    }
    if (modules.length >= 48) break;
  }
  // Aggregate lone files under same directory into one entry
  const aggregated = [];
  const byDir = {};
  for (const mod of modules) {
    if (mod.path.endsWith('/')) { aggregated.push(mod); continue; }
    const dir = mod.path.replace(/\/[^/]+$/, '/');
    if (!byDir[dir]) byDir[dir] = [];
    byDir[dir].push(mod.path);
  }
  for (const [dir, files] of Object.entries(byDir)) {
    if (files.length <= 2) {
      for (const f of files) aggregated.push({ path: f });
    } else {
      aggregated.push({ path: dir, fileCount: files.length });
    }
  }
  return aggregated;
}

function collectPublicApiEntries(root, sourceRoots) {
  const entries = [];
  const dunderAllPattern = /^__all__\s*=\s*\[([\s\S]*?)\]/m;
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    if (!file.endsWith('__init__.py')) continue;
    const text = readFile(path.join(root, file));
    const match = text.match(dunderAllPattern);
    if (!match) continue;
    const names = match[1]
      .split(/,\s*/)
      .map((item) => item.trim().replace(/^["']|["']$/g, ''))
      .filter((name) => name && !name.startsWith('_'));
    if (!names.length) continue;
    entries.push({
      module: file.replace(/\/__init__\.py$/, '').replace(/\\/g, '/'),
      exports: names,
      count: names.length,
      evidence: file,
    });
    if (entries.length >= 32) break;
  }
  return entries;
}

function collectCommandEntries(root) {
  const commands = [];
  const pushCommand = (command, purpose, evidence) => {
    if (commands.some((entry) => entry.command === command)) return;
    commands.push({ command, purpose, evidence });
  };

  const packagePath = path.join(root, 'package.json');
  if (fs.existsSync(packagePath)) {
    try {
      const pkg = JSON.parse(readFile(packagePath));
      const scripts = pkg && pkg.scripts && typeof pkg.scripts === 'object' ? pkg.scripts : {};
      for (const name of Object.keys(scripts).sort()) {
        pushCommand(`npm run ${name}`, String(scripts[name] || '').slice(0, 80) || 'package script', 'package.json scripts');
        if (commands.length >= 32) return commands;
      }
    } catch (_) {
      // Invalid package metadata should not block FUNCTION_TREE generation.
    }
  }

  const cargoPath = path.join(root, 'Cargo.toml');
  if (fs.existsSync(cargoPath)) {
    const cargo = readFile(cargoPath);
    pushCommand('cargo build', 'build Rust workspace or crate', 'Cargo.toml');
    pushCommand('cargo test', 'run Rust tests', 'Cargo.toml');
    if (fs.existsSync(path.join(root, 'src', 'main.rs')) || fs.existsSync(path.join(root, 'src', 'bin')) || /\[\[bin\]\]/.test(cargo)) {
      pushCommand('cargo run', 'run Rust binary target', 'Cargo.toml');
    }
    for (const name of parseTomlSectionNames(cargo, 'bin')) {
      pushCommand(`cargo run --bin ${name}`, `run Rust binary ${name}`, 'Cargo.toml [[bin]]');
      if (commands.length >= 32) return commands;
    }
  }

  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const pyproject = readFile(pyprojectPath);
    if (fs.existsSync(path.join(root, 'tests')) || /\[tool\.pytest[^\]]*\]/.test(pyproject)) {
      pushCommand('python -m pytest', 'run Python tests', 'pyproject.toml');
    }
    for (const name of parseTomlTableKeys(pyproject, ['project.scripts', 'tool.poetry.scripts'])) {
      pushCommand(name, `run Python entrypoint ${name}`, 'pyproject.toml scripts');
      if (commands.length >= 32) return commands;
    }
  }

  const goModPath = path.join(root, 'go.mod');
  if (fs.existsSync(goModPath)) {
    pushCommand('go test ./...', 'run Go tests', 'go.mod');
    if (fs.existsSync(path.join(root, 'main.go')) || fs.existsSync(path.join(root, 'cmd'))) {
      pushCommand('go run .', 'run Go main package', 'go.mod');
    }
  }

  for (const target of collectMakeTargets(root)) {
    pushCommand(`make ${target}`, `run Makefile target ${target}`, 'Makefile');
    if (commands.length >= 32) return commands;
  }

  for (const recipe of collectJustRecipes(root)) {
    pushCommand(`just ${recipe}`, `run Justfile recipe ${recipe}`, 'Justfile');
    if (commands.length >= 32) return commands;
  }

  for (const task of collectTaskfileTasks(root)) {
    pushCommand(`task ${task}`, `run Taskfile task ${task}`, 'Taskfile');
    if (commands.length >= 32) return commands;
  }

  for (const command of collectDocCommandExamples(root)) {
    pushCommand(command.command, 'documented command example', command.evidence);
    if (commands.length >= 48) return commands;
  }

  // Python CLI subcommand detection
  for (const sub of collectPythonCliSubcommands(root)) {
    pushCommand(sub.command, sub.purpose, sub.evidence);
    if (commands.length >= 48) return commands;
  }

  return commands;
}

function collectPythonCliSubcommands(root) {
  const subcommands = [];
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (!fs.existsSync(pyprojectPath)) return subcommands;

  const pyproject = readFile(pyprojectPath);

  // Parse [project.scripts] entries: "optuna = "optuna.cli:main"
  const scriptEntries = parseTomlTableKeys(pyproject, ['project.scripts', 'tool.poetry.scripts']);
  const entryMap = {};
  for (const key of scriptEntries) {
    // Extract value after the key
    const valueMatch = pyproject.match(new RegExp(`${escapeRegExp(key)}\\s*=\\s*["']([^"']+)["']`));
    if (valueMatch) entryMap[key] = valueMatch[1];
  }

  for (const [cliName, entryPoint] of Object.entries(entryMap)) {
    // entryPoint format: "module.path:function"
    const match = entryPoint.match(/^([\w.]+):(\w+)$/);
    if (!match) continue;
    const modulePath = match[1].replace(/\./g, '/');

    // Try to find the CLI source file
    const candidates = [
      path.join(root, modulePath + '.py'),
    ];
    // Also check inside source roots
    for (const srcRoot of existingPaths(root, ['src', 'app', 'lib'])) {
      candidates.push(path.join(root, srcRoot, modulePath + '.py'));
    }

    let cliSource = '';
    let cliFile = '';
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) {
        cliSource = readFile(candidate);
        cliFile = candidate;
        break;
      }
    }
    if (!cliSource) continue;

    // Strategy 1: Detect argparse subcommands via _COMMANDS-style dict
    // Pattern: _COMMANDS = { "cmd1": ..., "cmd2": ..., ... }
    // Use a brace-depth-aware match to handle type annotations like dict[str, type[...]]
    const commandsDictMatch = matchBracedDict(cliSource, '_COMMANDS');
    if (commandsDictMatch) {
      const cmdNames = commandsDictMatch.match(/["']([^"']+)["']\s*:/g);
      if (cmdNames) {
        for (const cmd of cmdNames) {
          const name = cmd.match(/["']([^"']+)["']/)[1];
          subcommands.push({
            command: `${cliName} ${name}`,
            purpose: `CLI subcommand: ${name}`,
            evidence: `${path.relative(root, cliFile)} _COMMANDS`,
          });
          if (subcommands.length >= 32) return subcommands;
        }
      }
    }

    // Strategy 2: Detect add_parser("subcommand-name") calls
    const addParserMatches = cliSource.matchAll(/\.add_parser\s*\(\s*["']([^"']+)["']/g);
    for (const m of addParserMatches) {
      const name = m[1];
      if (name === 'help') continue;
      if (subcommands.some((s) => s.command === `${cliName} ${name}`)) continue;
      subcommands.push({
        command: `${cliName} ${name}`,
        purpose: `CLI subcommand: ${name}`,
        evidence: `${path.relative(root, cliFile)} add_parser`,
      });
      if (subcommands.length >= 32) return subcommands;
    }

    // Strategy 3: Detect click @command / @group decorators
    const clickCmdMatches = cliSource.matchAll(/@(?:cli\.)?command\s*\(\s*["']([^"']+)["']/g);
    for (const m of clickCmdMatches) {
      const name = m[1];
      if (subcommands.some((s) => s.command === `${cliName} ${name}`)) continue;
      subcommands.push({
        command: `${cliName} ${name}`,
        purpose: `CLI subcommand: ${name}`,
        evidence: `${path.relative(root, cliFile)} click @command`,
      });
      if (subcommands.length >= 32) return subcommands;
    }
  }

  return subcommands;
}

function collectDocSystemInfo(root) {
  const systems = [];

  // Sphinx: docs/source/conf.py or docs/conf.py
  for (const confPath of existingPaths(root, ['docs/source/conf.py', 'docs/conf.py', 'doc/source/conf.py', 'doc/conf.py'])) {
    systems.push({ system: 'Sphinx', evidence: confPath, detail: 'Python documentation generator' });
    break;
  }

  // MkDocs: mkdocs.yml
  if (fs.existsSync(path.join(root, 'mkdocs.yml'))) {
    systems.push({ system: 'MkDocs', evidence: 'mkdocs.yml', detail: 'Static site generator for project documentation' });
  }

  // Docusaurus: docusaurus.config.js or docusaurus.config.ts
  for (const cfg of existingPaths(root, ['docusaurus.config.js', 'docusaurus.config.ts', 'website/docusaurus.config.js'])) {
    systems.push({ system: 'Docusaurus', evidence: cfg, detail: 'React-based documentation framework' });
    break;
  }

  // Jekyll: _config.yml with gemfile indication
  if (fs.existsSync(path.join(root, '_config.yml'))) {
    systems.push({ system: 'Jekyll', evidence: '_config.yml', detail: 'Static site generator' });
  }

  // Rustdoc: lib.rs or Cargo.toml with doc targets
  if (fs.existsSync(path.join(root, 'Cargo.toml')) && !systems.some((s) => s.system === 'Sphinx')) {
    const cargo = readFile(path.join(root, 'Cargo.toml'));
    if (/\[package\]/.test(cargo)) {
      systems.push({ system: 'rustdoc', evidence: 'Cargo.toml', detail: 'Rust documentation tool' });
    }
  }

  // Doxygen: Doxyfile
  if (fs.existsSync(path.join(root, 'Doxyfile')) || fs.existsSync(path.join(root, 'docs/Doxyfile'))) {
    systems.push({ system: 'Doxygen', evidence: 'Doxyfile', detail: 'C/C++ documentation generator' });
  }

  return systems;
}

function collectExceptionHierarchy(root, sourceRoots) {
  const exceptions = [];
  const seen = new Set();
  // Match: class XxxError(Exception): or class XxxError(BaseException): or class Xxx(YyyError):
  const classPattern = /^class\s+([A-Z]\w*(?:Error|Exception|Warning|Fault|Failure))\s*\(\s*([\w.]+)\s*\)\s*:/gm;
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    if (!file.endsWith('.py')) continue;
    const text = readFile(path.join(root, file));
    let match;
    while ((match = classPattern.exec(text)) !== null) {
      const name = match[1];
      if (seen.has(name)) continue;
      seen.add(name);
      const parent = match[2];
      exceptions.push({
        name,
        parent,
        module: file.replace(/\\/g, '/').replace(/\.py$/, ''),
        evidence: file,
      });
      if (exceptions.length >= 32) break;
    }
    if (exceptions.length >= 32) break;
  }
  return exceptions;
}

function collectConfigEntries(root, sourceRoots) {
  const entries = [];
  const seen = new Set();
  const push = (entry) => {
    if (!seen.has(entry.type + ':' + entry.evidence)) {
      seen.add(entry.type + ':' + entry.evidence);
      entries.push(entry);
    }
  };

  // .env files
  for (const envPath of existingPaths(root, ['.env', '.env.example', '.env.sample', '.env.template', '.env.local'])) {
    push({ type: 'env file', evidence: envPath, detail: 'Environment variable file' });
  }

  // Config files by convention
  for (const cfgPath of existingPaths(root, ['config', 'configs', 'settings', '.config', 'conf'])) {
    try {
      for (const entry of fs.readdirSync(path.join(root, cfgPath))) {
        if (/\.(ya?ml|json|toml|ini|cfg|py)$/.test(entry)) {
          push({ type: 'config file', evidence: `${cfgPath}/${entry}`, detail: 'Configuration file' });
        }
        if (entries.length >= 24) break;
      }
    } catch (_) {}
  }

  // pyproject.toml config sections
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const text = readFile(pyprojectPath);
    const configSections = text.match(/\[tool\.(\w+)[.\]]/g);
    if (configSections) {
      for (const section of [...new Set(configSections)]) {
        const tool = section.replace(/\[tool\./, '').replace(/[.\]]/, '');
        push({ type: 'tool config', evidence: `pyproject.toml [tool.${tool}]`, detail: `Tool configuration: ${tool}` });
      }
    }
  }

  // Environment variable references in Python source
  const envPattern = /os\.environ\[(?:["']([^"']+)["'])\]|os\.getenv\(\s*["']([^"']+)["']/g;
  const envVars = new Map();
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    if (!file.endsWith('.py')) continue;
    const text = readFile(path.join(root, file));
    let match;
    while ((match = envPattern.exec(text)) !== null) {
      const varName = match[1] || match[2];
      if (!envVars.has(varName)) {
        envVars.set(varName, file);
      }
    }
    if (envVars.size >= 32) break;
  }
  for (const [varName, file] of envVars) {
    push({ type: 'env var', evidence: varName, detail: `Referenced in ${file.replace(/\\/g, '/')}` });
  }

  return entries.slice(0, 32);
}

function collectDependencyEntries(root) {
  const deps = [];
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (!fs.existsSync(pyprojectPath)) return deps;

  const text = readFile(pyprojectPath);
  // Extract dependencies — can be inline in [project] section or in [project.dependencies]
  let depContent = '';
  // Strategy 1: Inline dependencies = [...] under [project]
  const inlineMatch = text.match(/^dependencies\s*=\s*\[([\s\S]*?)\]/m);
  if (inlineMatch) {
    depContent = inlineMatch[1];
  }
  // Strategy 2: Separate [project.dependencies] section
  if (!depContent) {
    const sectionMatch = text.match(/\[project\.dependencies\]\s*\n([\s\S]*?)(?:\n\[|\n*$)/);
    if (sectionMatch) depContent = sectionMatch[1];
  }
  if (!depContent) return deps;

  const categoryMap = {
    sqlalchemy: 'database', alembic: 'database', redis: 'database', psycopg: 'database',
    numpy: 'math', scipy: 'math', pandas: 'math', scikit: 'ml', torch: 'ml',
    matplotlib: 'visualization', plotly: 'visualization', kaleido: 'visualization',
    flask: 'web', fastapi: 'web', django: 'web', starlette: 'web',
    boto3: 'cloud', 'google-cloud': 'cloud',
    click: 'cli', argparse: 'cli',
    pytest: 'testing', moto: 'testing',
    grpcio: 'rpc', protobuf: 'rpc',
    colorlog: 'logging', tqdm: 'logging',
  };

  for (const line of depContent.split('\n')) {
    const m = line.match(/["']\s*([A-Za-z0-9_-]+)/);
    if (!m) continue;
    const name = m[1].toLowerCase();
    let category = 'runtime';
    for (const [key, cat] of Object.entries(categoryMap)) {
      if (name.includes(key) || key.includes(name)) {
        category = cat;
        break;
      }
    }
    deps.push({ name: m[1], category, evidence: 'pyproject.toml [project.dependencies]' });
    if (deps.length >= 32) break;
  }
  return deps;
}

function collectDocCommandExamples(root) {
  const examples = [];
  for (const relativePath of existingPaths(root, ['README.md', 'AGENTS.md', 'CLAUDE.md', 'docs/README.md', 'docs/usage.md', 'docs/USAGE.md'])) {
    const text = readFile(path.join(root, relativePath));
    let inFence = false;
    let fenceIsShell = false;
    let lineNumber = 0;
    for (const rawLine of text.split(/\r?\n/)) {
      lineNumber += 1;
      const fenceMatch = rawLine.match(/^\s*```\s*([A-Za-z0-9_-]*)/);
      if (fenceMatch) {
        inFence = !inFence;
        fenceIsShell = inFence && (!fenceMatch[1] || /^(bash|sh|shell|zsh|console|terminal)$/i.test(fenceMatch[1]));
        continue;
      }
      if (inFence && fenceIsShell) {
        const command = normalizeDocCommand(rawLine);
        if (command) examples.push({ command, evidence: `${relativePath}:${lineNumber}` });
      }
    }

    for (const match of text.matchAll(/`([^`\n]+)`/g)) {
      const command = normalizeDocCommand(match[1]);
      if (command) examples.push({ command, evidence: relativePath });
    }
  }
  return uniqueCommandExamples(examples, 24);
}

function normalizeDocCommand(value) {
  let command = String(value || '').trim();
  command = command.replace(/^\$\s*/, '').replace(/^>\s*/, '').trim();
  command = command.replace(/\s+#.*$/, '').trim();
  command = command.replace(/\s+\\$/, '').trim();
  if (!command || !looksLikeRunnableProjectCommand(command) || isSetupOnlyCommand(command)) return '';
  return command.slice(0, 120);
}

function looksLikeRunnableProjectCommand(command) {
  return /^(?:npm|pnpm|yarn|bun|node|npx|cargo|python|python3|uv|poetry|go|docker|docker compose|make|just|task|pytest|ruff|mypy|tox)\b/.test(command);
}

function isSetupOnlyCommand(command) {
  return /^(?:cd|export|source|alias|echo|cat|cp|mv|rm|mkdir|touch)\b/.test(command) ||
    /^(?:npm|pnpm|yarn|bun)\s+(?:install|add|remove|update)\b/.test(command) ||
    /^pip(?:3)?\s+install\b/.test(command) ||
    /^python(?:3)?\s+-m\s+pip\s+install\b/.test(command) ||
    /^poetry\s+install\b/.test(command) ||
    /^cargo\s+install\b/.test(command) ||
    /^go\s+(?:get|install)\b/.test(command) ||
    /^docker\s+(?:pull|build)\b/.test(command);
}

function uniqueCommandExamples(examples, limit) {
  const seen = new Set();
  const unique = [];
  for (const example of examples) {
    if (seen.has(example.command)) continue;
    seen.add(example.command);
    unique.push(example);
    if (unique.length >= limit) break;
  }
  return unique;
}

function collectMakeTargets(root) {
  const makefile = firstExistingPath(root, ['Makefile', 'makefile', 'GNUmakefile']);
  if (!makefile) return [];
  const targets = [];
  for (const line of readFile(makefile).split(/\r?\n/)) {
    if (/^\s/.test(line) || /^\s*(?:#|$)/.test(line) || /^\s*\./.test(line)) continue;
    const match = line.match(/^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?![=])/);
    if (!match || !isPublicTaskName(match[1])) continue;
    targets.push(match[1]);
  }
  return uniqueNames(targets, 16);
}

function collectJustRecipes(root) {
  const justfile = firstExistingPath(root, ['Justfile', 'justfile', '.justfile']);
  if (!justfile) return [];
  const recipes = [];
  for (const line of readFile(justfile).split(/\r?\n/)) {
    if (/^\s/.test(line) || /^\s*(?:#|$|set\s|export\s|alias\s)/.test(line)) continue;
    const match = line.match(/^@?([A-Za-z0-9][A-Za-z0-9_.-]*)\b[^:=]*:/);
    if (!match || !isPublicTaskName(match[1])) continue;
    recipes.push(match[1]);
  }
  return uniqueNames(recipes, 16);
}

function collectTaskfileTasks(root) {
  const taskfile = firstExistingPath(root, ['Taskfile.yml', 'Taskfile.yaml', 'taskfile.yml', 'taskfile.yaml']);
  if (!taskfile) return [];
  const tasks = [];
  let inTasks = false;
  for (const line of readFile(taskfile).split(/\r?\n/)) {
    if (/^\s*tasks\s*:\s*(?:#.*)?$/.test(line)) {
      inTasks = true;
      continue;
    }
    if (!inTasks) continue;
    if (/^\S/.test(line) && !/^\s*tasks\s*:/.test(line)) break;
    const match = line.match(/^\s{2}([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:\s*(?:#.*)?$/);
    if (!match || !isPublicTaskName(match[1])) continue;
    tasks.push(match[1]);
  }
  return uniqueNames(tasks, 16);
}

function firstExistingPath(root, relativePaths) {
  for (const relativePath of relativePaths) {
    const absolutePath = path.join(root, relativePath);
    if (fs.existsSync(absolutePath)) return absolutePath;
  }
  return '';
}

function isPublicTaskName(value) {
  return /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(String(value || '')) && !String(value).startsWith('_');
}

function uniqueNames(values, limit) {
  const seen = new Set();
  const names = [];
  for (const value of values) {
    if (seen.has(value)) continue;
    seen.add(value);
    names.push(value);
    if (names.length >= limit) break;
  }
  return names;
}

function parseTomlSectionNames(text, sectionName) {
  const names = [];
  let inSection = false;
  for (const line of String(text || '').split(/\r?\n/)) {
    if (/^\s*\[\[/.test(line)) inSection = new RegExp(`^\\s*\\[\\[\\s*${escapeRegExp(sectionName)}\\s*\\]\\]`).test(line);
    if (!inSection) continue;
    const match = line.match(/^\s*name\s*=\s*["']([^"']+)["']/);
    if (match) names.push(match[1]);
  }
  return names;
}

function parseTomlTableKeys(text, tableNames) {
  const keys = [];
  let currentTable = '';
  for (const line of String(text || '').split(/\r?\n/)) {
    const tableMatch = line.match(/^\s*\[\s*([^\]]+)\s*\]\s*$/);
    if (tableMatch) {
      currentTable = tableMatch[1].trim();
      continue;
    }
    if (!tableNames.includes(currentTable)) continue;
    const keyMatch = line.match(/^\s*([A-Za-z0-9_.-]+)\s*=/);
    if (keyMatch) keys.push(keyMatch[1]);
  }
  return keys;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function matchBracedDict(source, varName) {
  // Find VARNAME = { or VARNAME: type = { and extract the content between balanced braces
  // Handles: _COMMANDS = { ... } and _COMMANDS: dict[str, type] = { ... }
  const startMatch = source.match(new RegExp(`${escapeRegExp(varName)}\\s*[:=][\\s\\S]*?=\\s*\\{`));
  if (!startMatch) return null;
  // Find the actual '{' in the match
  const braceOffset = startMatch[0].lastIndexOf('{');
  const startIdx = startMatch.index + braceOffset;
  let depth = 0;
  let i = startIdx;
  for (; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}') {
      depth--;
      if (depth === 0) break;
    }
  }
  if (depth !== 0) return null;
  return source.substring(startIdx + 1, i);
}

function detectProjectName(root) {
  const packagePath = path.join(root, 'package.json');
  if (fs.existsSync(packagePath)) {
    try {
      const pkg = JSON.parse(readFile(packagePath));
      if (pkg && typeof pkg.name === 'string' && pkg.name.trim()) return pkg.name.trim();
    } catch (_) {
      // Fall back to the directory name when package metadata is not valid JSON.
    }
  }

  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const match = readFile(pyprojectPath).match(/^\s*name\s*=\s*["']([^"']+)["']/m);
    if (match) return match[1];
  }

  const goModPath = path.join(root, 'go.mod');
  if (fs.existsSync(goModPath)) {
    const match = readFile(goModPath).match(/^\s*module\s+(\S+)/m);
    if (match) return match[1].split('/').pop();
  }

  return path.basename(root);
}

function detectPythonPackageRoots(root) {
  const roots = [];
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (!fs.existsSync(pyprojectPath)) return roots;

  const text = readFile(pyprojectPath);

  // Check [tool.setuptools.packages.find] include patterns
  const findMatch = text.match(/\[tool\.setuptools\.packages\.find\][\s\S]*?include\s*=\s*\[([^\]]+)\]/);
  if (findMatch) {
    const patterns = findMatch[1].match(/["']([^"']+)["']/g);
    if (patterns) {
      for (const raw of patterns) {
        const clean = raw.replace(/["']/g, '');
        if (clean.endsWith('*')) {
          const prefix = clean.slice(0, -1);
          try {
            for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
              if (entry.isDirectory() && entry.name.startsWith(prefix) && fs.existsSync(path.join(root, entry.name, '__init__.py'))) {
                if (!roots.includes(entry.name)) roots.push(entry.name);
              }
            }
          } catch (_) { /* ignore readdir errors */ }
        } else if (fs.existsSync(path.join(root, clean, '__init__.py'))) {
          if (!roots.includes(clean)) roots.push(clean);
        }
      }
    }
  }

  // Fallback: check if a directory matching project name exists with __init__.py
  if (!roots.length) {
    const projectName = detectProjectName(root);
    const pkgDir = path.join(root, projectName);
    if (fs.existsSync(path.join(pkgDir, '__init__.py')) && !roots.includes(projectName)) {
      roots.push(projectName);
    }
    // Also check src/<project> layout
    const srcPkgDir = path.join(root, 'src', projectName);
    if (fs.existsSync(path.join(srcPkgDir, '__init__.py')) && !roots.includes('src')) {
      roots.push('src');
    }
  }

  return roots.filter((r) => fs.existsSync(path.join(root, r)));
}

function collectGovernancePrograms(root, context) {
  const programsDir = path.join(root, '.governance', 'programs');
  if (!fs.existsSync(programsDir)) return [];
  return fs.readdirSync(programsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const programDir = path.join(programsDir, entry.name);
      const meta = readProgramTreeMeta(programDir);
      const nodes = loadNodes(path.join(programDir, 'nodes.json'));
      const firstNode = nodes.find((node) => node && node.function_tree_ref);
      return {
        name: entry.name,
        ref: entry.name === context.program ? context.ref : (meta.ref || (firstNode ? firstNode.function_tree_ref : '')),
        description: entry.name === context.program ? context.description : meta.description,
        nodeCount: nodes.length,
        activeCount: nodes.filter((node) => node && !['closed', 'archived'].includes(node.status)).length,
        treePath: rel(root, path.join(programDir, 'tree.md')),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

function readProgramTreeMeta(programDir) {
  const treePath = path.join(programDir, 'tree.md');
  if (!fs.existsSync(treePath)) return { ref: '', description: '' };
  const tree = readFile(treePath);
  const ref = tree.match(/^>[ \t]*Function tree ref:[ \t]*`([^`]+)`/m);
  const description = tree.match(/^>[ \t]*Description:[ \t]*(.*)$/m);
  return {
    ref: ref ? ref[1].trim() : '',
    description: description ? description[1].trim() : '',
  };
}

function existingPaths(root, candidates) {
  return candidates.filter((candidate) => fs.existsSync(path.join(root, candidate)));
}

function formatList(values) {
  return values.length ? values.map((value) => `\`${value}\``).join(', ') : 'none detected';
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

function collectStewardPrograms(root) {
  const programsDir = path.join(root, '.governance', 'programs');
  if (!fs.existsSync(programsDir)) return [];
  return fs.readdirSync(programsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const nodesPath = path.join(programsDir, entry.name, 'nodes.json');
      return {
        name: entry.name,
        nodes: fs.existsSync(nodesPath) ? loadNodes(nodesPath) : [],
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
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

function markdownTable(headers, rows) {
  const body = rows.length ? rows : [headers.map(() => '-')];
  return [
    `| ${headers.map(escapeCell).join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...body.map((row) => `| ${row.map(escapeCell).join(' | ')} |`),
  ].join('\n');
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

function normalizeStewardNodeType(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (!STEWARD_NODE_TYPES.has(normalized)) {
    fail(`invalid steward node type: ${value}`, 2);
  }
  return normalized;
}

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

function validateGovernance(root, flags = {}) {
  const errors = [];
  const warnings = [];
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
      nodes.forEach((node, index) => {
        validateNodeLike(node, `${program}.nodes[${index}]`, errors, false, currentHead);
        if (flags.steward) validateStewardNode(node, `${program}.nodes[${index}]`, warnings);
      });
    }
  }

  if (errors.length) {
    console.log(errors.map((e) => `ERROR ${e}`).join('\n'));
    process.exit(1);
  }
  if (warnings.length) console.log(warnings.map((e) => `WARN ${e}`).join('\n'));
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
  if (!gateMode && node.node_type && !STEWARD_NODE_TYPES.has(String(node.node_type).toLowerCase())) {
    errors.push(`${label} has unknown node_type: ${node.node_type}`);
  }
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

function validateStewardNode(node, label, warnings) {
  if (!node.next_gate) warnings.push(`${label} missing next_gate`);
  if (!node.owner_lane) warnings.push(`${label} missing owner_lane`);
  if (!node.freshness) warnings.push(`${label} missing freshness policy`);
  if (stewardTypeFor(node) === 'implementation' && !list(node.allowed_paths).length) {
    warnings.push(`${label} implementation node missing allowed_paths`);
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
