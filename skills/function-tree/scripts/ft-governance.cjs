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
      out.flags[token.slice(2, eq)] = token.slice(eq + 1);
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      out.flags[key] = next;
      i += 1;
    } else {
      out.flags[key] = true;
    }
  }
  return out;
}

function usage(code) {
  const text = [
    'Usage:',
    '  ft-governance.cjs init <program> --ref <function-tree-node> [--description <text>] [--root <repo>]',
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

function validateGovernance(root) {
  const errors = [];
  const gov = path.join(root, '.governance');
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
      nodes.forEach((node, index) => validateNodeLike(node, `${program}.nodes[${index}]`, errors, false));
    }
  }

  if (errors.length) {
    console.log(errors.map((e) => `ERROR ${e}`).join('\n'));
    process.exit(1);
  }
  console.log('governance validation passed');
}

function validateNodeLike(node, label, errors, gateMode) {
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
