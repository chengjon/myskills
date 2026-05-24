#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// --- Runtime definitions ---
const RUNTIMES = [
  {
    id: 'claude-code',
    envVar: 'CLAUDE_CONFIG_DIR',
    defaultPaths: ['.claude'],
    versionCommand: 'claude --version',
  },
  {
    id: 'codex',
    envVar: 'CODEX_HOME',
    defaultPaths: ['.codex'],
    versionCommand: 'codex --version',
  },
  {
    id: 'opencode',
    envVar: 'OPENCODE_CONFIG_DIR',
    defaultPaths: ['.config/opencode', '.opencode'],
    versionCommand: 'opencode --version',
  },
];

function resolveHome(p) {
  if (p.startsWith('~/')) return path.join(os.homedir(), p.slice(2));
  return p;
}

function resolveConfigDir(runtime) {
  if (process.env[runtime.envVar]) {
    const p = resolveHome(process.env[runtime.envVar]);
    if (fs.existsSync(p)) return p;
  }
  for (const rel of runtime.defaultPaths) {
    const p = path.join(os.homedir(), rel);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function safeExec(cmd, opts = {}) {
  try {
    return execSync(cmd, {
      encoding: 'utf8',
      timeout: opts.timeout || 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
      ...opts,
    }).trim();
  } catch {
    return null;
  }
}

function getRuntimeVersion(runtime) {
  const out = safeExec(runtime.versionCommand);
  if (!out) return null;
  const match = out.match(/(\d+\.\d+\.\d+[^\s]*)/);
  return match ? match[1] : out.split('\n')[0];
}

function compareSemVer(a, b) {
  const pa = (a || '0').replace(/^v/, '').split('.').map(Number);
  const pb = (b || '0').replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) < (pb[i] || 0)) return -1;
    if ((pa[i] || 0) > (pb[i] || 0)) return 1;
  }
  return 0;
}

function computeStatus(installed, latest) {
  if (!latest || !installed) return 'unknown';
  if (compareSemVer(installed, latest) < 0) return 'outdated';
  return 'current';
}

// --- Scan source: installed_plugins.json ---

function resolveLatestPluginVersion(configDir, pluginName, marketplaceId) {
  const mpDir = path.join(configDir, 'plugins', 'marketplaces', marketplaceId);
  if (!fs.existsSync(mpDir)) return null;

  // Multi-plugin layout: marketplaces/<id>/plugins/<name>/package.json
  const pluginPkg = path.join(mpDir, 'plugins', pluginName, 'package.json');
  if (fs.existsSync(pluginPkg)) {
    try { return JSON.parse(fs.readFileSync(pluginPkg, 'utf8')).version || null; }
    catch { return null; }
  }

  // Single-package layout: marketplaces/<id>/package.json (marketplace IS the plugin)
  const rootPkg = path.join(mpDir, 'package.json');
  if (fs.existsSync(rootPkg)) {
    try { return JSON.parse(fs.readFileSync(rootPkg, 'utf8')).version || null; }
    catch { return null; }
  }

  return null;
}

function scanPlugins(configDir) {
  const plugins = [];
  const ipPath = path.join(configDir, 'plugins', 'installed_plugins.json');
  if (!fs.existsSync(ipPath)) return plugins;

  let installed;
  try { installed = JSON.parse(fs.readFileSync(ipPath, 'utf8')); }
  catch { return plugins; }

  // Load marketplace source info
  let marketplaces = {};
  const kmPath = path.join(configDir, 'plugins', 'known_marketplaces.json');
  if (fs.existsSync(kmPath)) {
    try { marketplaces = JSON.parse(fs.readFileSync(kmPath, 'utf8')); }
    catch { /* ignore */ }
  }

  for (const [key, installs] of Object.entries(installed.plugins || {})) {
    const atIdx = key.indexOf('@');
    const name = key.substring(0, atIdx);
    const marketplace = key.substring(atIdx + 1);

    for (const inst of installs) {
      const entry = {
        id: key,
        name,
        marketplace,
        type: 'plugin',
        scope: inst.scope || 'user',
        enabled: true,
        installPath: inst.installPath,
        installedVersion: inst.version,
        latestVersion: null,
        status: 'unknown',
        installedAt: inst.installedAt || null,
        lastUpdated: inst.lastUpdated || null,
        gitCommitSha: inst.gitCommitSha || null,
        source: (marketplaces[marketplace] || {}).source || null,
      };

      // Verify install path
      if (entry.installPath && !fs.existsSync(entry.installPath)) {
        entry.status = 'error';
      } else {
        entry.latestVersion = resolveLatestPluginVersion(configDir, name, marketplace);
        entry.status = computeStatus(entry.installedVersion, entry.latestVersion);
      }

      plugins.push(entry);
    }
  }
  return plugins;
}

// --- Individual check: GSD ---

function scanGSD(configDir) {
  const versionFile = path.join(configDir, 'get-shit-done', 'VERSION');
  if (!fs.existsSync(versionFile)) return null;

  let installedVersion;
  try { installedVersion = fs.readFileSync(versionFile, 'utf8').trim(); }
  catch { return null; }

  let latestVersion = null;
  const checkScript = path.join(configDir, 'get-shit-done', 'bin', 'check-latest-version.cjs');
  if (fs.existsSync(checkScript)) {
    const out = safeExec(`node "${checkScript}" --json`, { timeout: 30000 });
    if (out) {
      try {
        const result = JSON.parse(out);
        if (result.ok && result.version) latestVersion = result.version;
      } catch { /* ignore */ }
    }
  }

  return {
    id: 'gsd',
    name: 'gsd',
    marketplace: '',
    type: 'gsd',
    scope: 'user',
    enabled: true,
    installPath: path.join(configDir, 'get-shit-done'),
    installedVersion,
    latestVersion,
    status: computeStatus(installedVersion, latestVersion),
    installedAt: null,
    lastUpdated: null,
    gitCommitSha: null,
    source: { type: 'npm', package: 'get-shit-done-cc' },
  };
}

// --- Scan source: skills/*/SKILL.md ---

function scanSkills(configDir) {
  const skillsDir = path.join(configDir, 'skills');
  if (!fs.existsSync(skillsDir)) return [];

  const plugins = [];
  let entries;
  try { entries = fs.readdirSync(skillsDir, { withFileTypes: true }); }
  catch { return []; }

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const skillDir = path.join(skillsDir, entry.name);
    if (!fs.existsSync(path.join(skillDir, 'SKILL.md'))) continue;

    let version = null;

    const pkgPath = path.join(skillDir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try { version = JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version || null; }
      catch { /* ignore */ }
    }

    if (!version) {
      const sha = safeExec('git rev-parse --short HEAD', { cwd: skillDir, timeout: 5000 });
      if (sha) version = sha;
    }

    plugins.push({
      id: `${entry.name} (skill)`,
      name: entry.name,
      marketplace: '',
      type: 'skill',
      scope: 'user',
      enabled: true,
      installPath: skillDir,
      installedVersion: version,
      latestVersion: null,
      status: version ? 'unknown' : 'unknown',
      installedAt: null,
      lastUpdated: null,
      gitCommitSha: version,
      source: null,
    });
  }
  return plugins;
}

// --- Individual check: runtime binary ---

function scanRuntime(runtime) {
  const version = getRuntimeVersion(runtime);
  if (!version) return null;

  const npmPackages = {
    'claude-code': '@anthropic-ai/claude-code',
    'codex': '@openai/codex',
    'opencode': 'opencode',
  };

  let latestVersion = null;
  const pkg = npmPackages[runtime.id];
  if (pkg) {
    const out = safeExec(`npm view ${pkg} version`, { timeout: 15000 });
    if (out) latestVersion = out.split('\n')[0].trim();
  }

  return {
    id: `${runtime.id}-runtime`,
    name: `${runtime.id}-runtime`,
    marketplace: '',
    type: 'runtime',
    scope: 'user',
    enabled: true,
    installPath: '(binary)',
    installedVersion: version,
    latestVersion,
    status: computeStatus(version, latestVersion),
    installedAt: null,
    lastUpdated: null,
    gitCommitSha: null,
    source: pkg ? { type: 'npm', package: pkg } : null,
  };
}

// --- Main ---

function main() {
  const output = {
    scanTime: new Date().toISOString(),
    runtimes: [],
  };

  for (const runtime of RUNTIMES) {
    const configDir = resolveConfigDir(runtime);
    const runtimeEntry = {
      runtime: runtime.id,
      runtimeVersion: null,
      configDir: configDir || '',
      plugins: [],
    };

    if (configDir) {
      runtimeEntry.runtimeVersion = getRuntimeVersion(runtime);
      runtimeEntry.plugins.push(...scanPlugins(configDir));
      const gsd = scanGSD(configDir);
      if (gsd) runtimeEntry.plugins.push(gsd);
      runtimeEntry.plugins.push(...scanSkills(configDir));
      const rt = scanRuntime(runtime);
      if (rt) runtimeEntry.plugins.push(rt);
    }

    output.runtimes.push(runtimeEntry);
  }

  process.stdout.write(JSON.stringify(output, null, 2) + '\n');
}

main();
