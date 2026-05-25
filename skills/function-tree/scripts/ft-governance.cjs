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
    '  ft-governance.cjs init <program> --ref <function-tree-node> [--description <text>] [--no-doc] [--root <repo>]',
    '  ft-governance.cjs doc [--root <repo>]',
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
    if (looksLikeFunctionTreeBody(body)) return body;
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
  const featureRows = info.featureCandidates.length
    ? info.featureCandidates.map((feature) => `| ${escapeCell(feature.name)} | ${escapeCell(feature.type)} | ${escapeCell(feature.status)} | ${escapeCell(feature.evidence)}; ${escapeCell(feature.boundary)} |`)
    : ['| - | feature candidate | 待登记 | Add README/API/product feature bullets, then rerun `doc`. |'];
  const moduleRows = info.sourceModules.length
    ? info.sourceModules.map((module) => `| \`${module.path}\` | module | 待核验 | Auto-discovered source module; map to a capability node after review. |`)
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
  const plannedRows = info.plannedCandidates.length
    ? info.plannedCandidates.map((feature) => `| ${escapeCell(feature.name)} | 待实现 | ${escapeCell(feature.evidence)} | Auto-discovered planned/unfinished item; verify scope and owner before implementation. |`)
    : ['| - | 待登记 | - | Add planned/unfinished features from roadmap, TODO, or product notes. |'];
  const programLines = programs.length
    ? programs.map((program) => `  - ${program.name} (${program.ref || 'unmapped'}): ${program.description || 'governance program'}`)
    : ['  - Add governance programs with `/ft:init` or `new-node`.'];
  const featureLines = info.featureCandidates.length
    ? info.featureCandidates.map((feature) => `  - ${feature.name} (${feature.evidence})`)
    : ['  - Existing feature candidates: 待登记'];
  const plannedLines = info.plannedCandidates.length
    ? info.plannedCandidates.map((feature) => `  - Planned/unfinished: ${feature.name} (${feature.evidence})`)
    : ['  - Planned/unfinished: 待登记'];
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
    `- ${info.name}`,
    ...featureLines,
    ...plannedLines,
    ...programLines,
    info.sourceRoots.length ? `  - Source roots: ${formatList(info.sourceRoots)}` : '  - Source roots: 待登记',
    info.docs.length ? `  - Documentation: ${formatList(info.docs)}` : '  - Documentation: 待登记',
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
    `- Initialized by function-tree for ${context.program || 'project-governance'} (${context.ref || 'unmapped'}).`,
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

  return {
    name: detectProjectName(root),
    head: gitHead(root),
    manifests: existingPaths(root, [
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
    ]),
    docs: existingPaths(root, [
      'README.md',
      'AGENTS.md',
      'CLAUDE.md',
      'CONTRIBUTING.md',
      'docs',
    ]),
    sourceRoots,
    featureCandidates: collectFeatureCandidates(root),
    plannedCandidates: collectPlannedFeatureCandidates(root),
    sourceModules: collectSourceModules(root, sourceRoots),
    commandEntries: collectCommandEntries(root),
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
  if (lines.length) lines.push('');
  return lines;
}

function collectFeatureCandidates(root) {
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'FEATURES.md', 'docs/README.md', 'docs/features.md', 'docs/FEATURES.md'], 'existing'),
  ], 16);
}

function collectPlannedFeatureCandidates(root) {
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'ROADMAP.md', 'TODO.md', 'docs/roadmap.md', 'docs/ROADMAP.md', 'docs/todo.md', 'docs/TODO.md'], 'planned'),
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

function collectSourceModules(root, sourceRoots) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const modules = [];
  for (const sourceRoot of sourceRoots) {
    const absoluteRoot = path.join(root, sourceRoot);
    if (!fs.existsSync(absoluteRoot) || !fs.statSync(absoluteRoot).isDirectory()) continue;
    for (const entry of fs.readdirSync(absoluteRoot, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      if (!entry.isDirectory() && !/\.(js|jsx|ts|tsx|py|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp)$/i.test(entry.name)) continue;
      const relativePath = `${sourceRoot}/${entry.name}${entry.isDirectory() ? '/' : ''}`;
      modules.push({ path: relativePath });
      if (modules.length >= 24) return modules;
    }
  }
  return modules;
}

function collectCommandEntries(root) {
  const commands = [];
  const packagePath = path.join(root, 'package.json');
  if (fs.existsSync(packagePath)) {
    try {
      const pkg = JSON.parse(readFile(packagePath));
      const scripts = pkg && pkg.scripts && typeof pkg.scripts === 'object' ? pkg.scripts : {};
      for (const name of Object.keys(scripts).sort()) {
        commands.push({
          command: `npm run ${name}`,
          purpose: String(scripts[name] || '').slice(0, 80) || 'package script',
          evidence: 'package.json scripts',
        });
        if (commands.length >= 16) return commands;
      }
    } catch (_) {
      // Invalid package metadata should not block FUNCTION_TREE generation.
    }
  }
  return commands;
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
