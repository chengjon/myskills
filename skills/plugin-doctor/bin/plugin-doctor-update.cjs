#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function parseArgs(argv) {
  const args = { all: false, id: null, runtime: null, dryRun: false, json: false, input: null };
  let i = 2;
  while (i < argv.length) {
    switch (argv[i]) {
      case '--all': args.all = true; break;
      case '--id': args.id = argv[++i]; break;
      case '--runtime': args.runtime = argv[++i]; break;
      case '--dry-run': args.dryRun = true; break;
      case '--json': args.json = true; break;
      case '--input': args.input = argv[++i]; break;
      default: process.stderr.write(`Unknown: ${argv[i]}\n`); process.exit(1);
    }
    i++;
  }
  return args;
}

const RUNTIME_FLAGS = { 'claude-code': '--claude', 'codex': '--codex', 'opencode': '--opencode' };
const NPM_PACKAGES = { 'claude-code': '@anthropic-ai/claude-code', 'codex': '@openai/codex', 'opencode': 'opencode' };

function safeExec(cmd, opts = {}) {
  try {
    return execSync(cmd, { encoding: 'utf8', timeout: 180000, stdio: ['pipe', 'pipe', 'pipe'], ...opts }).trim();
  } catch (e) {
    throw new Error(e.message.split('\n')[0]);
  }
}

function updatePlugin(entry, runtime, dryRun) {
  if (dryRun) return { id: entry.id, action: 'would-update', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: `Would run: claude plugins update ${entry.name}` };
  try {
    safeExec(`claude plugins update ${entry.name}`, { timeout: 180000 });
    return { id: entry.id, action: 'updated', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: null };
  } catch (e) { return { id: entry.id, action: 'failed', fromVersion: entry.installedVersion, toVersion: null, success: false, message: e.message }; }
}

function updateGSD(entry, runtime, dryRun) {
  const flag = RUNTIME_FLAGS[runtime.runtime] || '--claude';
  if (dryRun) return { id: entry.id, action: 'would-update', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: `Would update GSD via npx` };
  try {
    safeExec(`npx -y --package=get-shit-done-cc@latest -- get-shit-done-cc ${flag} --global`, { timeout: 300000 });
    return { id: entry.id, action: 'updated', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: null };
  } catch (e) { return { id: entry.id, action: 'failed', fromVersion: entry.installedVersion, toVersion: null, success: false, message: e.message }; }
}

function updateSkill(entry, runtime, dryRun) {
  if (!entry.installPath || !fs.existsSync(path.join(entry.installPath, '.git'))) {
    return { id: entry.id, action: 'skipped', fromVersion: entry.installedVersion, toVersion: null, success: true, message: 'Not a git repo' };
  }
  if (dryRun) return { id: entry.id, action: 'would-update', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: `Would git pull ${entry.installPath}` };
  try {
    safeExec('git pull --ff-only', { cwd: entry.installPath, timeout: 60000 });
    return { id: entry.id, action: 'updated', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: null };
  } catch (e) { return { id: entry.id, action: 'failed', fromVersion: entry.installedVersion, toVersion: null, success: false, message: e.message }; }
}

function updateRuntime(entry, runtime, dryRun) {
  const pkg = NPM_PACKAGES[runtime.runtime];
  if (!pkg) return { id: entry.id, action: 'skipped', fromVersion: entry.installedVersion, toVersion: null, success: true, message: 'No known update method' };
  if (dryRun) return { id: entry.id, action: 'would-update', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: `Would run: npm update -g ${pkg}` };
  try {
    safeExec(`npm update -g ${pkg}`, { timeout: 300000 });
    return { id: entry.id, action: 'updated', fromVersion: entry.installedVersion, toVersion: entry.latestVersion, success: true, message: null };
  } catch (e) { return { id: entry.id, action: 'failed', fromVersion: entry.installedVersion, toVersion: null, success: false, message: e.message }; }
}

const UPDATERS = { plugin: updatePlugin, gsd: updateGSD, skill: updateSkill, runtime: updateRuntime };

function main() {
  const args = parseArgs(process.argv);
  if (!args.all && !args.id) {
    process.stderr.write('Usage: plugin-doctor-update --all | --id <id> [--runtime <name>] [--dry-run]\n');
    process.exit(1);
  }

  let scanData;
  if (args.input) {
    scanData = JSON.parse(fs.readFileSync(args.input, 'utf8'));
  } else {
    const scanScript = path.join(__dirname, 'plugin-doctor-scan.cjs');
    scanData = JSON.parse(safeExec(`node "${scanScript}" --json`, { timeout: 60000 }));
  }

  const results = [];
  for (const runtime of scanData.runtimes) {
    if (args.runtime && runtime.runtime !== args.runtime) continue;
    let targets = args.id
      ? runtime.plugins.filter(p => p.id === args.id)
      : runtime.plugins.filter(p => p.status === 'outdated');

    for (const entry of targets) {
      const updater = UPDATERS[entry.type] || (() => ({ id: entry.id, action: 'skipped', fromVersion: entry.installedVersion, toVersion: null, success: false, message: `Unknown type: ${entry.type}` }));
      results.push(updater(entry, runtime, args.dryRun));
    }
  }

  if (args.json) {
    process.stdout.write(JSON.stringify({ results }, null, 2) + '\n');
  } else {
    for (const r of results) {
      const icon = r.success ? (r.action === 'updated' ? '✔' : r.action === 'would-update' ? '?' : '⊘') : '✘';
      const ver = r.toVersion ? `${r.fromVersion} -> ${r.toVersion}` : `(${r.message || r.action})`;
      process.stdout.write(`  ${icon} ${r.id}  ${ver}\n`);
    }
    const updated = results.filter(r => r.action === 'updated' || r.action === 'would-update').length;
    const failed = results.filter(r => !r.success).length;
    process.stdout.write(`\n  Updated: ${updated} | Failed: ${failed} | Total: ${results.length}\n`);
  }
}

main();
