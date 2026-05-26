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

function readText(root, relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

function walkFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) return walkFiles(fullPath);
    return fullPath;
  });
}

test('public skill docs avoid project-specific bindings', () => {
  const repoRoot = path.resolve(__dirname, '..', '..', '..');
  const skillRoot = path.resolve(__dirname, '..');
  const files = [
    path.join(repoRoot, 'README.md'),
    ...walkFiles(skillRoot).filter((file) => {
      const rel = path.relative(skillRoot, file);
      return (
        rel === 'SKILL.md' ||
        rel.startsWith(`references${path.sep}`) ||
        rel.startsWith(`templates${path.sep}`)
      );
    }),
  ];
  const forbidden = [
    new RegExp(['quan', 'tix'].join(''), 'i'),
    new RegExp(['Git', 'Nexus'].join('')),
    new RegExp(`\\b${['car', 'go'].join('')}\\b`),
    new RegExp(`\\b${['Ru', 'st'].join('')}\\b`),
    new RegExp(['market', '_cli'].join('')),
    new RegExp(['handlers', '-split'].join('')),
    new RegExp(['trade', '_handler'].join('')),
  ];

  for (const file of files) {
    const rel = path.relative(repoRoot, file);
    const haystack = `${rel}\n${fs.readFileSync(file, 'utf8')}`;
    for (const pattern of forbidden) {
      assert.doesNotMatch(haystack, pattern, `${rel} should stay project-neutral`);
    }
  }
});

test('init creates a project FUNCTION_TREE.md with collected project context and triggers', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'package.json'), `${JSON.stringify({
    name: 'sample-web',
    scripts: {
      dev: 'vite --host 0.0.0.0',
      'sync-prices': 'node scripts/sync-prices.js',
    },
  }, null, 2)}\n`);
  fs.writeFileSync(path.join(root, 'README.md'), [
    '# Sample Web',
    '',
    '## Features',
    '',
    '- Checkout flow',
    '- Payment retry',
    '',
    '## Roadmap',
    '',
    '- Coupon rules',
    '',
  ].join('\n'));
  fs.mkdirSync(path.join(root, 'src', 'checkout'), { recursive: true });
  fs.mkdirSync(path.join(root, 'src', 'payments'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'checkout', 'index.ts'), 'export const checkout = true;\n');
  fs.writeFileSync(path.join(root, 'src', 'payments', 'adapter.ts'), 'export const payments = true;\n');

  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--description', 'Checkout governance', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /^# FUNCTION_TREE/m);
  assert.match(doc, /sample-web/);
  assert.match(doc, /checkout-flow/);
  assert.match(doc, /checkout\/payment/);
  assert.match(doc, /Checkout governance/);
  assert.match(doc, /## 注册规则/);
  assert.match(doc, /已有功能/);
  assert.match(doc, /计划\/未完成功能/);
  assert.match(doc, /开发者.*方向指引/);
  assert.match(doc, /避免.*跑偏/);
  assert.match(doc, /## 功能全景图/);
  assert.match(doc, /## 状态注册表/);
  assert.match(doc, /### 模块\/能力节点/);
  assert.match(doc, /### CLI\/运营入口节点/);
  assert.match(doc, /## 模块\/命令证据展开/);
  assert.match(doc, /## 模块依赖关系/);
  assert.match(doc, /\/ft:init/);
  assert.match(doc, /function tree/i);
  assert.match(doc, /README\.md/);
  assert.match(doc, /Checkout flow/);
  assert.match(doc, /Payment retry/);
  assert.match(doc, /Coupon rules/);
  assert.match(doc, /src\/checkout/);
  assert.match(doc, /src\/payments/);
  assert.match(doc, /npm run sync-prices/);
  assert.match(doc, new RegExp(git(root, ['rev-parse', 'HEAD'])));
  assert.doesNotMatch(doc, /## Project Snapshot/);
  assert.doesNotMatch(doc, /## Skill Activation/);
  assert.doesNotMatch(doc, /## Governance Programs/);
  assert.doesNotMatch(doc, /## Operating Loop/);
  assert.doesNotMatch(doc, /## State Files/);
});

test('init discovers ecosystem commands and source TODO candidates', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'Cargo.toml'), [
    '[package]',
    'name = "portfolio-engine"',
    'version = "0.1.0"',
    '',
    '[[bin]]',
    'name = "portfolio-worker"',
    'path = "src/bin/worker.rs"',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'pyproject.toml'), [
    '[project]',
    'name = "portfolio-engine"',
    '',
    '[project.scripts]',
    'portfolio-admin = "portfolio.cli:main"',
    '',
    '[tool.pytest.ini_options]',
    'testpaths = ["tests"]',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'go.mod'), 'module example.com/portfolio-engine\n');
  fs.mkdirSync(path.join(root, 'src', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'lib.rs'), '// TODO: Add reconciliation dashboard\n');
  fs.writeFileSync(path.join(root, 'src', 'bin', 'worker.rs'), 'fn main() {}\n');
  fs.writeFileSync(path.join(root, 'main.go'), 'package main\nfunc main() {}\n');

  run(['init', 'portfolio-governance', '--ref', 'portfolio/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /cargo test/);
  assert.match(doc, /cargo run --bin portfolio-worker/);
  assert.match(doc, /python -m pytest/);
  assert.match(doc, /portfolio-admin/);
  assert.ok(doc.includes('go test ./...'));
  assert.ok(doc.includes('go run .'));
  assert.match(doc, /Add reconciliation dashboard/);
  assert.ok(doc.includes('src/lib.rs:1'));
});

test('init discovers generic task-runner commands', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'Makefile'), [
    'smoke:',
    '\t./scripts/smoke.sh',
    '.PHONY: smoke clean',
    'clean:',
    '\trm -rf dist',
    '_internal:',
    '\ttrue',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'Justfile'), [
    'release-check:',
    '    ./scripts/release-check.sh',
    '',
    '_private:',
    '    true',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'Taskfile.yml'), [
    'version: "3"',
    'tasks:',
    '  deploy:',
    '    cmds:',
    '      - ./scripts/deploy.sh',
    '  _internal:',
    '    cmds:',
    '      - true',
    '',
  ].join('\n'));

  run(['init', 'ops-governance', '--ref', 'ops/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /make smoke/);
  assert.match(doc, /make clean/);
  assert.match(doc, /just release-check/);
  assert.match(doc, /task deploy/);
  assert.doesNotMatch(doc, /make _internal/);
  assert.doesNotMatch(doc, /just _private/);
  assert.doesNotMatch(doc, /task _internal/);
});

test('init discovers runnable commands from docs while filtering setup noise', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'README.md'), [
    '# Demo',
    '',
    '## Build & Run',
    '',
    '```bash',
    'cd demo',
    'export API_TOKEN=secret',
    'npm install',
    'pnpm test',
    'docker compose up -d',
    'cargo run -- serve --port 3000',
    '```',
    '',
    '## Usage',
    '',
    'Run `python -m demo.cli reconcile --dry-run` before release.',
    '',
  ].join('\n'));

  run(['init', 'docs-governance', '--ref', 'docs/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /pnpm test/);
  assert.match(doc, /docker compose up -d/);
  assert.match(doc, /cargo run -- serve --port 3000/);
  assert.match(doc, /python -m demo\.cli reconcile --dry-run/);
  assert.doesNotMatch(doc, /\bcd demo\b/);
  assert.doesNotMatch(doc, /\bexport API_TOKEN/);
  assert.doesNotMatch(doc, /\bnpm install\b/);
});

test('init discovers API and service route entries', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'openapi.yaml'), [
    'openapi: 3.0.0',
    'paths:',
    '  /health:',
    '    get:',
    '      summary: Health check',
    '  /v1/orders:',
    '    post:',
    '      summary: Create order',
    '',
  ].join('\n'));
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'server.ts'), [
    "app.get('/api/users', listUsers);",
    'router.post("/api/users", createUser);',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'src', 'api.py'), [
    '@router.get("/jobs")',
    'def list_jobs():',
    '    pass',
    '',
  ].join('\n'));

  run(['init', 'api-governance', '--ref', 'api/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /### API\/服务入口节点/);
  assert.match(doc, /GET \/health/);
  assert.match(doc, /POST \/v1\/orders/);
  assert.match(doc, /GET \/api\/users/);
  assert.match(doc, /POST \/api\/users/);
  assert.match(doc, /GET \/jobs/);
  assert.match(doc, /openapi\.yaml/);
  assert.match(doc, /src\/server\.ts/);
  assert.match(doc, /src\/api\.py/);
});

test('init discovers frontend page and UI route entries', () => {
  const root = makeRepo();
  fs.mkdirSync(path.join(root, 'app', 'dashboard'), { recursive: true });
  fs.mkdirSync(path.join(root, 'app', 'users', '[id]'), { recursive: true });
  fs.mkdirSync(path.join(root, 'pages'), { recursive: true });
  fs.mkdirSync(path.join(root, 'src', 'routes', 'admin'), { recursive: true });
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(path.join(root, 'app', 'page.tsx'), 'export default function Home() { return null; }\n');
  fs.writeFileSync(
    path.join(root, 'app', 'dashboard', 'page.tsx'),
    'export default function Dashboard() { return null; }\n',
  );
  fs.writeFileSync(
    path.join(root, 'app', 'users', '[id]', 'page.tsx'),
    'export default function User() { return null; }\n',
  );
  fs.writeFileSync(path.join(root, 'pages', 'settings.tsx'), 'export default function Settings() { return null; }\n');
  fs.writeFileSync(path.join(root, 'src', 'routes', 'admin', '+page.svelte'), '<h1>Admin</h1>\n');
  fs.writeFileSync(path.join(root, 'src', 'router.tsx'), [
    '<Route path="/reports" element={<Reports />} />',
    "{ path: '/billing', element: <Billing /> },",
    '',
  ].join('\n'));

  run(['init', 'ui-governance', '--ref', 'ui/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /### UI\/页面入口节点/);
  assert.ok(doc.includes('`/`'));
  assert.match(doc, /\/dashboard/);
  assert.match(doc, /\/users\/\[id\]/);
  assert.match(doc, /\/settings/);
  assert.match(doc, /\/admin/);
  assert.match(doc, /\/reports/);
  assert.match(doc, /\/billing/);
  assert.match(doc, /app\/dashboard\/page\.tsx/);
  assert.match(doc, /pages\/settings\.tsx/);
  assert.match(doc, /src\/routes\/admin\/\+page\.svelte/);
  assert.match(doc, /src\/router\.tsx/);
});

test('init discovers navigation and menu links as UI entries', () => {
  const root = makeRepo();
  fs.mkdirSync(path.join(root, 'src', 'components'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'navigation.ts'), [
    'export const mainNav = [',
    "  { title: 'Portfolio', href: '/portfolio' },",
    "  { label: 'Risk Center', to: '/risk' },",
    "  { name: 'Billing', url: '/billing' },",
    "  { title: 'External Docs', href: 'https://example.com/docs' },",
    "  { title: 'Users API', href: '/api/users' },",
    '];',
    '',
  ].join('\n'));
  fs.writeFileSync(path.join(root, 'src', 'components', 'sidebar.tsx'), [
    'export function Sidebar() {',
    '  return <nav><Link href="/settings">Settings</Link><NavLink to="/reports">Reports</NavLink></nav>;',
    '}',
    '',
  ].join('\n'));

  run(['init', 'nav-governance', '--ref', 'ui/navigation', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /### UI\/页面入口节点/);
  assert.match(doc, /\/portfolio/);
  assert.match(doc, /\/risk/);
  assert.match(doc, /\/billing/);
  assert.match(doc, /\/settings/);
  assert.match(doc, /\/reports/);
  assert.match(doc, /src\/navigation\.ts/);
  assert.match(doc, /src\/components\/sidebar\.tsx/);
  assert.doesNotMatch(doc, /https:\/\/example\.com\/docs/);
  assert.doesNotMatch(doc, /\/api\/users/);
});

test('init derives feature candidates from discovered entrypoints', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'openapi.yaml'), [
    'openapi: 3.0.0',
    'paths:',
    '  /v1/orders:',
    '    get:',
    '      summary: List orders',
    '',
  ].join('\n'));
  fs.mkdirSync(path.join(root, 'app', 'dashboard'), { recursive: true });
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(
    path.join(root, 'app', 'dashboard', 'page.tsx'),
    'export default function Dashboard() { return null; }\n',
  );
  fs.writeFileSync(path.join(root, 'src', 'navigation.ts'), [
    'export const nav = [',
    "  { title: 'Portfolio', href: '/portfolio' },",
    '];',
    '',
  ].join('\n'));

  run(['init', 'entrypoint-features', '--ref', 'feature/root', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /\| Dashboard \| entrypoint feature \| 待核验 \| UI route `\/dashboard`/);
  assert.match(doc, /\| Portfolio \| entrypoint feature \| 待核验 \| UI route `\/portfolio`/);
  assert.match(doc, /\| Orders API \| entrypoint feature \| 待核验 \| API route `GET \/v1\/orders`/);
  assert.match(doc, /Auto-discovered existing feature candidates:/);
  assert.doesNotMatch(doc, /Add README\/API\/product feature bullets/);
});

test('init merges related UI API and command entrypoints into one feature candidate', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'package.json'), `${JSON.stringify({
    scripts: {
      'sync-orders': 'node scripts/sync-orders.js',
      dev: 'vite',
    },
  }, null, 2)}\n`);
  fs.writeFileSync(path.join(root, 'openapi.yaml'), [
    'openapi: 3.0.0',
    'paths:',
    '  /v1/orders:',
    '    post:',
    '      summary: Create order',
    '',
  ].join('\n'));
  fs.mkdirSync(path.join(root, 'app', 'orders'), { recursive: true });
  fs.writeFileSync(
    path.join(root, 'app', 'orders', 'page.tsx'),
    'export default function Orders() { return null; }\n',
  );

  run(['init', 'merged-entrypoints', '--ref', 'feature/orders', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /\| Orders \| entrypoint feature \| 待核验 \| UI route `\/orders`/);
  assert.match(doc, /\| Orders \| entrypoint feature \| 待核验 \|.*API route `POST \/v1\/orders`/);
  assert.match(doc, /\| Orders \| entrypoint feature \| 待核验 \|.*Command `npm run sync-orders`/);
  assert.doesNotMatch(doc, /\| Orders API \| entrypoint feature \|/);
  assert.doesNotMatch(doc, /\| Dev \| entrypoint feature \|/);
});

test('init backs up an existing FUNCTION_TREE.md before updating it', () => {
  const root = makeRepo();
  fs.writeFileSync(path.join(root, 'FUNCTION_TREE.md'), [
    '# FUNCTION_TREE',
    '',
    '## 注册规则',
    '',
    '- legacy rule',
    '',
    '## 功能全景图',
    '',
    '- legacy feature tree',
    '',
  ].join('\n'));

  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);

  const doc = readText(root, 'FUNCTION_TREE.md');
  assert.match(doc, /^# FUNCTION_TREE/m);
  assert.match(doc, /legacy rule/);
  assert.match(doc, /legacy feature tree/);
  assert.doesNotMatch(doc, /Preserved Previous FUNCTION_TREE\.md Content/);
  assert.doesNotMatch(doc, /## Project Snapshot/);

  const backupDir = path.join(root, '.governance/backups');
  const backups = fs.readdirSync(backupDir).filter((name) => /^FUNCTION_TREE\..+\.md$/.test(name));
  assert.equal(backups.length, 1);
  const backup = fs.readFileSync(path.join(backupDir, backups[0]), 'utf8');
  assert.match(backup, /legacy rule/);
});

test('doc refresh preserves project notes and avoids unchanged backups', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  const docPath = path.join(root, 'FUNCTION_TREE.md');
  const withNotes = fs.readFileSync(docPath, 'utf8').replace(
    /<!-- function-tree:project-notes:start -->[\s\S]*?<!-- function-tree:project-notes:end -->/,
    '<!-- function-tree:project-notes:start -->\n- Keep checkout ownership notes here.\n<!-- function-tree:project-notes:end -->',
  );
  fs.writeFileSync(docPath, withNotes);

  const output = run(['doc', '--root', root], root);
  assert.match(output, /unchanged/);
  const refreshed = fs.readFileSync(docPath, 'utf8');
  assert.match(refreshed, /Keep checkout ownership notes here/);
  const backupDir = path.join(root, '.governance/backups');
  assert.equal(fs.existsSync(backupDir), false);
});

test('doc refresh updates generated candidate evidence after project evidence changes', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  const docPath = path.join(root, 'FUNCTION_TREE.md');
  const withNotes = fs.readFileSync(docPath, 'utf8').replace(
    /<!-- function-tree:project-notes:start -->[\s\S]*?<!-- function-tree:project-notes:end -->/,
    '<!-- function-tree:project-notes:start -->\n- Keep checkout ownership notes here.\n<!-- function-tree:project-notes:end -->',
  );
  fs.writeFileSync(docPath, withNotes);
  fs.writeFileSync(path.join(root, 'README.md'), [
    '# Checkout',
    '',
    '## Features',
    '',
    '- Refund workflow',
    '',
    '## Roadmap',
    '',
    '- Subscription billing',
    '',
  ].join('\n'));
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'payments.ts'), '// TODO: Add fraud review queue\n');

  const output = run(['doc', '--root', root], root);

  assert.match(output, /updated FUNCTION_TREE\.md/);
  assert.match(output, /backup:/);
  const refreshed = fs.readFileSync(docPath, 'utf8');
  assert.match(refreshed, /Refund workflow/);
  assert.match(refreshed, /Subscription billing/);
  assert.match(refreshed, /Add fraud review queue/);
  assert.ok(refreshed.includes('src/payments.ts:1'));
  assert.match(refreshed, /Keep checkout ownership notes here/);
  const backupDir = path.join(root, '.governance/backups');
  const backups = fs.readdirSync(backupDir).filter((name) => /^FUNCTION_TREE\..+\.md$/.test(name));
  assert.equal(backups.length, 1);
});

test('new-node creates a planning node and active gate', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run([
    'new-node',
    'checkout-flow',
    'C1.1',
    '--title',
    'Add payment confirmation',
    '--ref',
    'checkout/payment/confirmation',
    '--root',
    root,
  ], root);

  const nodes = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].id, 'C1.1');
  assert.equal(nodes[0].title, 'Add payment confirmation');
  assert.equal(nodes[0].status, 'planning');
  assert.equal(nodes[0].function_tree_ref, 'checkout/payment/confirmation');
  assert.equal(nodes[0].source_edits_authorized, false);

  const active = readJson(root, '.governance/active-gates.json');
  assert.equal(active.gates.length, 1);
  assert.equal(active.gates[0].id, 'C1.1');
  assert.equal(active.gates[0].program, 'checkout-flow');
});

test('observe records evidence and moves the node to evidence-prepared', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.1', '--title', 'Add payment confirmation', '--ref', 'checkout/payment/confirmation', '--root', root], root);
  run([
    'observe',
    'checkout-flow',
    'C1.1',
    '--evidence',
    'reports/baseline.md',
    '--kind',
    'baseline',
    '--note',
    'baseline collected',
    '--root',
    root,
  ], root);

  const [node] = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  assert.equal(node.status, 'evidence-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.equal(node.evidence.length, 1);
  assert.equal(node.evidence[0].path, 'reports/baseline.md');
  assert.equal(node.evidence[0].kind, 'baseline');
  assert.equal(node.evidence[0].current_head, git(root, ['rev-parse', 'HEAD']));
});

test('authorize creates a task card and keeps source edits disabled', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.1', '--title', 'Add payment confirmation', '--ref', 'checkout/payment/confirmation', '--root', root], root);
  run(['observe', 'checkout-flow', 'C1.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run([
    'authorize',
    'checkout-flow',
    'C1.1',
    '--allowed',
    'src/checkout/payment-service.js',
    '--allowed',
    'src/checkout/index.js',
    '--forbidden',
    'tests/**',
    '--non-goal',
    'Do not change account settings',
    '--commit-gate',
    'project build passes',
    '--closeout-gate',
    'project test suite passes',
    '--root',
    root,
  ], root);

  const [node] = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  assert.equal(node.status, 'authorization-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.deepEqual(node.allowed_paths, ['src/checkout/payment-service.js', 'src/checkout/index.js']);
  assert.deepEqual(node.non_goals, ['Do not change account settings']);

  const card = fs.readFileSync(path.join(root, '.governance/programs/checkout-flow/cards/C1.1.yaml'), 'utf8');
  assert.match(card, /Add payment confirmation/);
  assert.match(card, /src\/checkout\/payment-service\.js/);
  assert.match(card, /project test suite passes/);
});

test('transition blocks implementation approval when evidence is stale', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.1', '--title', 'Add payment confirmation', '--ref', 'checkout/payment/confirmation', '--root', root], root);
  run(['observe', 'checkout-flow', 'C1.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run(['authorize', 'checkout-flow', 'C1.1', '--allowed', 'src/checkout/payment-service.js', '--non-goal', 'No account changes', '--commit-gate', 'project build passes', '--closeout-gate', 'project test suite passes', '--root', root], root);

  fs.writeFileSync(path.join(root, 'README.md'), 'changed\n');
  git(root, ['add', 'README.md']);
  git(root, ['commit', '-m', 'advance head']);

  const output = runFail(['transition', 'checkout-flow', 'C1.1', '--to', 'approved-for-implementation', '--root', root], root);
  assert.match(output, /stale evidence/i);
});

test('transition approves fresh authorization and closeout records closure evidence', () => {
  const root = makeRepo();
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.1', '--title', 'Add payment confirmation', '--ref', 'checkout/payment/confirmation', '--root', root], root);
  run(['observe', 'checkout-flow', 'C1.1', '--evidence', 'reports/baseline.md', '--root', root], root);
  run(['authorize', 'checkout-flow', 'C1.1', '--allowed', 'src/checkout/payment-service.js', '--non-goal', 'No account changes', '--commit-gate', 'project build passes', '--closeout-gate', 'project test suite passes', '--root', root], root);
  run(['transition', 'checkout-flow', 'C1.1', '--to', 'approved-for-implementation', '--root', root], root);

  let [node] = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  assert.equal(node.status, 'approved-for-implementation');
  assert.equal(node.source_edits_authorized, true);

  run(['transition', 'checkout-flow', 'C1.1', '--to', 'implementation-ready', '--note', 'implementation prepared', '--root', root], root);
  run(['transition', 'checkout-flow', 'C1.1', '--to', 'implementation-landed', '--note', 'merged locally', '--root', root], root);
  run(['closeout', 'checkout-flow', 'C1.1', '--summary', 'reports/closeout.md', '--compatibility', 'public API unchanged', '--gate', 'project test suite passes', '--root', root], root);

  [node] = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  assert.equal(node.status, 'closeout-prepared');
  assert.equal(node.source_edits_authorized, false);
  assert.equal(node.closeout.summary, 'reports/closeout.md');
  assert.deepEqual(node.closeout.gates, ['project test suite passes']);
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
  run(['init', 'checkout-flow', '--ref', 'checkout/payment', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.1', '--title', 'Add payment confirmation', '--ref', 'checkout/payment/confirmation', '--root', root], root);
  run(['new-node', 'checkout-flow', 'C1.2', '--title', 'Closed node', '--ref', 'checkout/payment/closed', '--root', root], root);

  const nodesPath = path.join(root, '.governance/programs/checkout-flow/nodes.json');
  const nodes = readJson(root, '.governance/programs/checkout-flow/nodes.json');
  nodes[0].status = 'authorization-prepared';
  nodes[0].allowed_paths = ['src/checkout/payment-service.js'];
  nodes[0].non_goals = ['No account changes'];
  nodes[0].next_gate = 'review authorization';
  nodes[1].status = 'closed';
  fs.writeFileSync(nodesPath, `${JSON.stringify(nodes, null, 2)}\n`);

  fs.writeFileSync(path.join(root, '.governance/active-gates.json'), JSON.stringify({
    schema_version: 1,
    updated_at: 'stale',
    gates: [
      { program: 'stale', id: 'OLD', status: 'planning' },
      { program: 'checkout-flow', id: 'C1.2', status: 'closed' },
    ],
  }, null, 2));

  const output = run(['repair', '--root', root], root);
  assert.match(output, /rebuilt active gates/i);

  const active = readJson(root, '.governance/active-gates.json');
  assert.equal(active.gates.length, 1);
  assert.equal(active.gates[0].program, 'checkout-flow');
  assert.equal(active.gates[0].id, 'C1.1');
  assert.equal(active.gates[0].status, 'authorization-prepared');

  const md = fs.readFileSync(path.join(root, '.governance/active-gates.md'), 'utf8');
  assert.match(md, /C1\.1/);
  assert.doesNotMatch(md, /OLD/);
  assert.doesNotMatch(md, /C1\.2/);
});
