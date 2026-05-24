#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const test = require('node:test');

const script = path.resolve(__dirname, '..', 'scripts', 'ft-governance.cjs');

function run(args, cwd) {
  return cp.execFileSync('node', [script, ...args], {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function runFail(args, cwd) {
  try {
    run(args, cwd);
  } catch (error) {
    return `${error.stdout || ''}${error.stderr || ''}`;
  }
  throw new Error(`expected command to fail: ${args.join(' ')}`);
}

function git(root, args) {
  return cp.execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
}

function makeRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-governance-test-'));
  git(root, ['init', '-b', 'main']);
  git(root, ['config', 'user.email', 'test@example.com']);
  git(root, ['config', 'user.name', 'Test User']);
  fs.writeFileSync(path.join(root, 'README.md'), 'seed\n');
  git(root, ['add', 'README.md']);
  git(root, ['commit', '-m', 'seed']);
  return root;
}

function readJson(root, relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), 'utf8'));
}

test('new-node creates a planning node and active gate', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run([
    'new-node',
    'handlers-split',
    'H3.1',
    '--title',
    'Split trade handlers',
    '--ref',
    'cli/handlers/trade',
    '--root',
    root,
  ], root);

  const nodes = readJson(root, '.governance/programs/handlers-split/nodes.json');
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].id, 'H3.1');
  assert.equal(nodes[0].title, 'Split trade handlers');
  assert.equal(nodes[0].status, 'planning');
  assert.equal(nodes[0].function_tree_ref, 'cli/handlers/trade');
  assert.equal(nodes[0].source_edits_authorized, false);

  const active = readJson(root, '.governance/active-gates.json');
  assert.equal(active.gates.length, 1);
  assert.equal(active.gates[0].id, 'H3.1');
  assert.equal(active.gates[0].program, 'handlers-split');
});

test('observe records evidence and moves the node to evidence-prepared', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.1', '--title', 'Split trade handlers', '--ref', 'cli/handlers/trade', '--root', root], root);
  run([
    'observe',
    'handlers-split',
    'H3.1',
    '--evidence',
    'reports/baseline.md',
    '--kind',
    'baseline',
    '--note',
    'baseline collected',
    '--root',
    root,
  ], root);

  const [node] = readJson(root, '.governance/programs/handlers-split/nodes.json');
  assert.equal(node.status, 'evidence-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.equal(node.evidence.length, 1);
  assert.equal(node.evidence[0].path, 'reports/baseline.md');
  assert.equal(node.evidence[0].kind, 'baseline');
  assert.equal(node.evidence[0].current_head, git(root, ['rev-parse', 'HEAD']));
});

test('authorize creates a task card and keeps source edits disabled', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.1', '--title', 'Split trade handlers', '--ref', 'cli/handlers/trade', '--root', root], root);
  run(['observe', 'handlers-split', 'H3.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run([
    'authorize',
    'handlers-split',
    'H3.1',
    '--allowed',
    'src/cli/handlers/trade_handler.rs',
    '--allowed',
    'src/cli/handlers/mod.rs',
    '--forbidden',
    'tests/**',
    '--non-goal',
    'Do not change account handlers',
    '--commit-gate',
    'cargo check passes',
    '--closeout-gate',
    'cargo test passes',
    '--root',
    root,
  ], root);

  const [node] = readJson(root, '.governance/programs/handlers-split/nodes.json');
  assert.equal(node.status, 'authorization-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.deepEqual(node.allowed_paths, ['src/cli/handlers/trade_handler.rs', 'src/cli/handlers/mod.rs']);
  assert.deepEqual(node.non_goals, ['Do not change account handlers']);

  const card = fs.readFileSync(path.join(root, '.governance/programs/handlers-split/cards/H3.1.yaml'), 'utf8');
  assert.match(card, /Split trade handlers/);
  assert.match(card, /src\/cli\/handlers\/trade_handler\.rs/);
  assert.match(card, /cargo test passes/);
});

test('transition blocks implementation approval when evidence is stale', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.1', '--title', 'Split trade handlers', '--ref', 'cli/handlers/trade', '--root', root], root);
  run(['observe', 'handlers-split', 'H3.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run(['authorize', 'handlers-split', 'H3.1', '--allowed', 'src/cli/handlers/trade_handler.rs', '--non-goal', 'No account changes', '--commit-gate', 'cargo check passes', '--closeout-gate', 'cargo test passes', '--root', root], root);

  fs.writeFileSync(path.join(root, 'README.md'), 'changed\n');
  git(root, ['add', 'README.md']);
  git(root, ['commit', '-m', 'advance head']);

  const output = runFail(['transition', 'handlers-split', 'H3.1', '--to', 'approved-for-implementation', '--root', root], root);
  assert.match(output, /stale evidence/i);
});

test('transition approves fresh authorization and closeout records closure evidence', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.1', '--title', 'Split trade handlers', '--ref', 'cli/handlers/trade', '--root', root], root);
  run(['observe', 'handlers-split', 'H3.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run(['authorize', 'handlers-split', 'H3.1', '--allowed', 'src/cli/handlers/trade_handler.rs', '--non-goal', 'No account changes', '--commit-gate', 'cargo check passes', '--closeout-gate', 'cargo test passes', '--root', root], root);
  run(['transition', 'handlers-split', 'H3.1', '--to', 'approved-for-implementation', '--root', root], root);

  let [node] = readJson(root, '.governance/programs/handlers-split/nodes.json');
  assert.equal(node.status, 'approved-for-implementation');
  assert.equal(node.source_edits_authorized, true);

  run(['transition', 'handlers-split', 'H3.1', '--to', 'implementation-ready', '--note', 'implementation prepared', '--root', root], root);
  run(['transition', 'handlers-split', 'H3.1', '--to', 'implementation-landed', '--note', 'merged locally', '--root', root], root);
  run(['closeout', 'handlers-split', 'H3.1', '--summary', 'reports/closeout.md', '--compatibility', 'pub use preserved', '--gate', 'cargo test passes', '--root', root], root);

  [node] = readJson(root, '.governance/programs/handlers-split/nodes.json');
  assert.equal(node.status, 'closeout-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.equal(node.closeout.summary, 'reports/closeout.md');
  assert.deepEqual(node.closeout.gates, ['cargo test passes']);
});

test('install-guard writes a repo-local wrapper without overwriting by default', () => {
  const root = makeRepo();
  const output = run(['install-guard', '--root', root], root);
  assert.match(output, /installed guard/i);
  assert.match(output, /PostToolUse/);

  const guardPath = path.join(root, '.governance/guards/ft-scope-check.sh');
  const guard = fs.readFileSync(guardPath, 'utf8');
  assert.match(guard, /FT_GOVERNANCE_SCRIPT/);
  assert.match(guard, /ft-governance\.cjs/);
  assert.equal(fs.statSync(guardPath).mode & 0o111, 0o111);

  const second = runFail(['install-guard', '--root', root], root);
  assert.match(second, /already exists/i);
});

test('repair rebuilds active gates from nodes and drops closed nodes', () => {
  const root = makeRepo();
  run(['init', 'handlers-split', '--ref', 'cli/handlers', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.1', '--title', 'Split trade handlers', '--ref', 'cli/handlers/trade', '--root', root], root);
  run(['new-node', 'handlers-split', 'H3.2', '--title', 'Closed node', '--ref', 'cli/handlers/closed', '--root', root], root);

  const nodesPath = path.join(root, '.governance/programs/handlers-split/nodes.json');
  const nodes = readJson(root, '.governance/programs/handlers-split/nodes.json');
  nodes[0].status = 'authorization-prepared';
  nodes[0].allowed_paths = ['src/cli/handlers/trade_handler.rs'];
  nodes[0].non_goals = ['No account changes'];
  nodes[0].next_gate = 'review authorization';
  nodes[1].status = 'closed';
  fs.writeFileSync(nodesPath, `${JSON.stringify(nodes, null, 2)}\n`);

  fs.writeFileSync(path.join(root, '.governance/active-gates.json'), JSON.stringify({
    schema_version: 1,
    updated_at: 'stale',
    gates: [
      { program: 'stale', id: 'OLD', status: 'planning' },
      { program: 'handlers-split', id: 'H3.2', status: 'closed' },
    ],
  }, null, 2));

  const output = run(['repair', '--root', root], root);
  assert.match(output, /rebuilt active gates/i);

  const active = readJson(root, '.governance/active-gates.json');
  assert.equal(active.gates.length, 1);
  assert.equal(active.gates[0].program, 'handlers-split');
  assert.equal(active.gates[0].id, 'H3.1');
  assert.equal(active.gates[0].status, 'authorization-prepared');

  const md = fs.readFileSync(path.join(root, '.governance/active-gates.md'), 'utf8');
  assert.match(md, /H3\.1/);
  assert.doesNotMatch(md, /OLD/);
  assert.doesNotMatch(md, /H3\.2/);
});
