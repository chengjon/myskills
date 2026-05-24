# Plugin Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-script skill that scans, health-checks, and updates all installed plugins, skills, GSD, and runtimes across Claude Code, Codex, and OpenCode.

**Architecture:** Three independent Node.js CJS scripts communicating via structured JSON on stdout. `scan.cjs` reads the filesystem and outputs a runtime-grouped plugin list. `health.cjs` augments that list with diagnostics. `update.cjs` executes version updates using each runtime's official CLI.

**Tech Stack:** Node.js (CJS), no external dependencies — uses only `fs`, `path`, `child_process`, `os`, `stream`.

**Design Spec:** `~/.claude/skills/plugin-doctor/DESIGN.md`

---

## File Structure

```
~/.claude/skills/plugin-doctor/
├── SKILL.md                       # Skill definition (already exists)
├── DESIGN.md                      # Design spec (already exists)
├── PLAN.md                        # This plan
└── bin/
    ├── plugin-doctor-scan.cjs     # Task 1
    ├── plugin-doctor-health.cjs   # Task 2
    └── plugin-doctor-update.cjs   # Task 3
```

---

### Task 1: scan.cjs — Plugin Discovery and Version Resolution

**Files:**
- Create: `~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs`

This script reads all installed items from the filesystem and outputs structured JSON. It has 2 scan sources (containers with multiple items) and 2 individual checks:

- **Sources** (yield multiple entries): `installed_plugins.json` (plugins), `skills/*/` (manual skills)
- **Individual checks** (yield one entry each): GSD framework (`get-shit-done/VERSION`), runtime binary

All four produce entries in the same `PluginEntry[]` list. Latest versions are resolved by reading the local marketplace git repos (no network fetch — relies on whatever state `git fetch` left them in).

- [ ] **Step 1: Create the script skeleton with runtime detection**

Create `~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs`:

```javascript
#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// --- Runtime detection ---
// Each runtime has: id, envVar (for config dir), defaultPaths, versionCommand
const RUNTIMES = [
  {
    id: 'claude-code',
    envVar: 'CLAUDE_CONFIG_DIR',
    defaultPaths: ['.claude'],
    versionCommand: 'claude --version',
    updateCommand: 'claude plugins update',
  },
  {
    id: 'codex',
    envVar: 'CODEX_HOME',
    defaultPaths: ['.codex'],
    versionCommand: 'codex --version',
    updateCommand: null, // Codex update mechanism TBD
  },
  {
    id: 'opencode',
    envVar: 'OPENCODE_CONFIG_DIR',
    defaultPaths: ['.config/opencode', '.opencode'],
    versionCommand: 'opencode --version',
    updateCommand: null, // OpenCode update mechanism TBD
  },
];

function resolveConfigDir(runtime) {
  // Environment variable takes priority
  if (process.env[runtime.envVar]) {
    const p = resolveHome(process.env[runtime.envVar]);
    if (fs.existsSync(p)) return p;
  }
  // Check default paths
  for (const rel of runtime.defaultPaths) {
    const p = path.join(os.homedir(), rel);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function resolveHome(p) {
  if (p.startsWith('~/')) return path.join(os.homedir(), p.slice(2));
  return p;
}

function getRuntimeVersion(runtime) {
  try {
    const out = execSync(runtime.versionCommand, {
      encoding: 'utf8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
    // Parse version number from output like "claude 4.7.0" or just "4.7.0"
    const match = out.match(/(\d+\.\d+\.\d+[^\s]*)/);
    return match ? match[1] : out.split('\n')[0];
  } catch {
    return null;
  }
}

// --- Scan sources ---

function scanPlugins(configDir, runtime) {
  const plugins = [];
  const ipPath = path.join(configDir, 'plugins', 'installed_plugins.json');
  if (!fs.existsSync(ipPath)) return plugins;

  let installed;
  try {
    installed = JSON.parse(fs.readFileSync(ipPath, 'utf8'));
  } catch {
    return plugins;
  }

  const entries = installed.plugins || {};
  for (const [key, installs] of Object.entries(entries)) {
    for (const inst of installs) {
      const [name, marketplace] = key.split('@');
      const entry = {
        id: key,
        name,
        marketplace: marketplace || '',
        type: 'plugin',
        scope: inst.scope || 'user',
        enabled: true, // Will be refined later if needed
        installPath: inst.installPath,
        installedVersion: inst.version,
        latestVersion: null,
        status: 'unknown',
        installedAt: inst.installedAt,
        lastUpdated: inst.lastUpdated,
        gitCommitSha: inst.gitCommitSha || null,
        source: null,
      };

      // Try to get source from known_marketplaces.json
      const kmPath = path.join(configDir, 'plugins', 'known_marketplaces.json');
      if (fs.existsSync(kmPath)) {
        try {
          const km = JSON.parse(fs.readFileSync(kmPath, 'utf8'));
          const mp = km[marketplace];
          if (mp && mp.source) {
            entry.source = mp.source;
          }
        } catch { /* ignore */ }
      }

      // Try to read version from install path package.json
      const pkgPath = path.join(inst.installPath, 'package.json');
      if (fs.existsSync(pkgPath)) {
        try {
          const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
          if (pkg.version && !entry.installedVersion) {
            entry.installedVersion = pkg.version;
          }
        } catch { /* ignore */ }
      }

      // Resolve latest version from local marketplace repo
      entry.latestVersion = resolveLatestPluginVersion(configDir, name, marketplace);
      entry.status = computeStatus(entry.installedVersion, entry.latestVersion);

      // Check install path existence
      if (!fs.existsSync(inst.installPath)) {
        entry.status = 'error';
      }

      plugins.push(entry);
    }
  }
  return plugins;
}

function resolveLatestPluginVersion(configDir, pluginName, marketplaceId) {
  // Look in the marketplace local repo for the plugin's package.json
  const mpDir = path.join(configDir, 'plugins', 'marketplaces', marketplaceId);
  if (!fs.existsSync(mpDir)) return null;

  // Try multi-plugin layout: marketplaces/<id>/plugins/<name>/package.json
  const pluginPkg = path.join(mpDir, 'plugins', pluginName, 'package.json');
  if (fs.existsSync(pluginPkg)) {
    try {
      return JSON.parse(fs.readFileSync(pluginPkg, 'utf8')).version || null;
    } catch { return null; }
  }

  // Try single-package layout: marketplaces/<id>/package.json (marketplace IS the plugin)
  const rootPkg = path.join(mpDir, 'package.json');
  if (fs.existsSync(rootPkg)) {
    try {
      const pkg = JSON.parse(fs.readFileSync(rootPkg, 'utf8'));
      // Only use root package.json if this marketplace is the source for this plugin
      // Check by matching marketplace name to plugin marketplace id
      return pkg.version || null;
    } catch { return null; }
  }

  return null;
}

function computeStatus(installed, latest) {
  if (!latest) return 'unknown';
  if (!installed) return 'unknown';
  if (installed === latest) return 'current';
  // Simple semver comparison
  const iParts = installed.replace(/^v/, '').split('.').map(Number);
  const lParts = latest.replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const iv = iParts[i] || 0;
    const lv = lParts[i] || 0;
    if (iv < lv) return 'outdated';
    if (iv > lv) return 'current'; // dev install ahead of release
  }
  return 'current';
}

function scanGSD(configDir) {
  const versionFile = path.join(configDir, 'get-shit-done', 'VERSION');
  if (!fs.existsSync(versionFile)) return null;

  let installedVersion;
  try {
    installedVersion = fs.readFileSync(versionFile, 'utf8').trim();
  } catch {
    return null;
  }

  // Check latest via the bundled script
  let latestVersion = null;
  const checkScript = path.join(configDir, 'get-shit-done', 'bin', 'check-latest-version.cjs');
  if (fs.existsSync(checkScript)) {
    try {
      const out = execSync(`node "${checkScript}" --json`, {
        encoding: 'utf8',
        timeout: 30000,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).trim();
      const result = JSON.parse(out);
      if (result.ok && result.version) {
        latestVersion = result.version;
      }
    } catch { /* ignore */ }
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

function scanSkills(configDir) {
  const skillsDir = path.join(configDir, 'skills');
  if (!fs.existsSync(skillsDir)) return [];

  const plugins = [];
  const entries = fs.readdirSync(skillsDir, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const skillDir = path.join(skillsDir, entry.name);
    const skillFile = path.join(skillDir, 'SKILL.md');
    if (!fs.existsSync(skillFile)) continue;

    let version = null;
    let latestVersion = null;

    // Try package.json
    const pkgPath = path.join(skillDir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try {
        version = JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version || null;
      } catch { /* ignore */ }
    }

    // Try git SHA as version
    if (!version) {
      try {
        version = execSync('git rev-parse --short HEAD', {
          cwd: skillDir,
          encoding: 'utf8',
          timeout: 5000,
          stdio: ['pipe', 'pipe', 'pipe'],
        }).trim();
      } catch { /* ignore */ }
    }

    // Try git remote HEAD for latest
    try {
      const remote = execSync('git ls-remote HEAD HEAD', {
        cwd: skillDir,
        encoding: 'utf8',
        timeout: 10000,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).trim();
      if (remote) {
        latestVersion = remote.split('\t')[0].substring(0, 7);
      }
    } catch { /* ignore */ }

    plugins.push({
      id: `${entry.name} (skill)`,
      name: entry.name,
      marketplace: '',
      type: 'skill',
      scope: 'user',
      enabled: true,
      installPath: skillDir,
      installedVersion: version,
      latestVersion,
      status: version ? (latestVersion ? (version === latestVersion ? 'current' : 'unknown') : 'unknown') : 'unknown',
      installedAt: null,
      lastUpdated: null,
      gitCommitSha: version,
      source: null,
    });
  }
  return plugins;
}

function scanRuntime(runtime) {
  const version = getRuntimeVersion(runtime);
  if (!version) return null;

  // Try to get latest version from npm
  let latestVersion = null;
  const npmPackages = {
    'claude-code': '@anthropic-ai/claude-code',
    'codex': '@openai/codex',
    'opencode': 'opencode',
  };
  const pkg = npmPackages[runtime.id];
  if (pkg) {
    try {
      latestVersion = execSync(`npm view ${pkg} version`, {
        encoding: 'utf8',
        timeout: 15000,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).trim();
    } catch { /* ignore */ }
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

      // Scan plugins from installed_plugins.json
      runtimeEntry.plugins.push(...scanPlugins(configDir, runtime));

      // Scan GSD
      const gsd = scanGSD(configDir);
      if (gsd) runtimeEntry.plugins.push(gsd);

      // Scan manual skills
      runtimeEntry.plugins.push(...scanSkills(configDir));

      // Scan runtime itself
      const rt = scanRuntime(runtime);
      if (rt) runtimeEntry.plugins.push(rt);
    }

    output.runtimes.push(runtimeEntry);
  }

  if (process.argv.includes('--json')) {
    process.stdout.write(JSON.stringify(output, null, 2) + '\n');
  } else {
    process.stdout.write(JSON.stringify(output) + '\n');
  }
}

main();
```

- [ ] **Step 2: Test scan.cjs manually**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs --json | python3 -m json.tool | head -60`
Expected: Valid JSON with `scanTime`, `runtimes` array, Claude Code section with 27+ plugins, GSD entry, skills, and runtime entry. Codex and OpenCode sections with empty plugins.

- [ ] **Step 3: Verify version resolution works**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for rt in data['runtimes']:
    print(f'Runtime: {rt[\"runtime\"]} (v{rt[\"runtimeVersion\"]})')
    outdated = [p for p in rt['plugins'] if p['status'] == 'outdated']
    current = [p for p in rt['plugins'] if p['status'] == 'current']
    unknown = [p for p in rt['plugins'] if p['status'] == 'unknown']
    errors = [p for p in rt['plugins'] if p['status'] == 'error']
    print(f'  Plugins: {len(rt[\"plugins\"])} | Current: {len(current)} | Outdated: {len(outdated)} | Unknown: {len(unknown)} | Error: {len(errors)}')
    for p in outdated[:5]:
        print(f'    OUTDATED: {p[\"id\"]} {p[\"installedVersion\"]} -> {p[\"latestVersion\"]}')
    print()
"`
Expected: Claude Code shows 27+ plugins with status breakdown. Outdated plugins show version gap.

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/skills/plugin-doctor
git init 2>/dev/null || true
git add bin/plugin-doctor-scan.cjs
git commit -m "feat(plugin-doctor): add scan module for plugin discovery and version resolution"
```

---

### Task 2: health.cjs — Health Diagnostics

**Files:**
- Create: `~/.claude/skills/plugin-doctor/bin/plugin-doctor-health.cjs`

This script reads scan output from stdin, checks each plugin entry for integrity, config, and cache issues, and outputs augmented JSON.

- [ ] **Step 1: Create the health check script**

Create `~/.claude/skills/plugin-doctor/bin/plugin-doctor-health.cjs`:

```javascript
#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function checkPlugin(entry, configDir) {
  const issues = [];

  // --- Integrity checks ---

  // Check 1: installPath directory exists
  if (entry.installPath && entry.installPath !== '(binary)') {
    if (!fs.existsSync(entry.installPath)) {
      issues.push({
        severity: 'error',
        category: 'integrity',
        message: `Install path does not exist: ${entry.installPath}`,
        fixable: false,
        fixAction: null,
      });
    } else {
      // Check 2: package.json or VERSION file present
      const hasPkg = fs.existsSync(path.join(entry.installPath, 'package.json'));
      const hasVersion = fs.existsSync(path.join(entry.installPath, 'VERSION'));
      const hasSkillMd = entry.type === 'skill' && fs.existsSync(path.join(entry.installPath, 'SKILL.md'));

      if (!hasPkg && !hasVersion && !hasSkillMd) {
        issues.push({
          severity: 'error',
          category: 'integrity',
          message: `No package.json, VERSION, or SKILL.md found in ${entry.installPath}`,
          fixable: false,
          fixAction: null,
        });
      }
    }
  }

  // --- Config checks ---

  // Check 3: Skill frontmatter has required fields
  if (entry.type === 'skill' && entry.installPath) {
    const skillMd = path.join(entry.installPath, 'SKILL.md');
    if (fs.existsSync(skillMd)) {
      try {
        const content = fs.readFileSync(skillMd, 'utf8');
        const frontmatter = content.match(/^---\n([\s\S]*?)\n---/);
        if (frontmatter) {
          const fm = frontmatter[1];
          const hasName = /^name:/m.test(fm);
          const hasDesc = /^description:/m.test(fm);
          if (!hasName || !hasDesc) {
            issues.push({
              severity: 'warn',
              category: 'config',
              message: `Skill SKILL.md missing ${!hasName ? 'name' : ''}${!hasName && !hasDesc ? ' and ' : ''}${!hasDesc ? 'description' : ''} in frontmatter`,
              fixable: false,
              fixAction: null,
            });
          }
        }
      } catch { /* ignore */ }
    }
  }

  // --- Cache checks ---

  // Check 4: Multiple version directories for same plugin
  if (entry.type === 'plugin' && entry.marketplace && entry.installPath) {
    const cacheBase = path.dirname(entry.installPath);
    if (fs.existsSync(cacheBase)) {
      try {
        const dirs = fs.readdirSync(cacheBase, { withFileTypes: true })
          .filter(d => d.isDirectory())
          .map(d => d.name);
        if (dirs.length > 1) {
          issues.push({
            severity: 'warn',
            category: 'cache',
            message: `${dirs.length} version directories found for ${entry.name} in ${cacheBase}: ${dirs.join(', ')}`,
            fixable: true,
            fixAction: 'clear-old-cache',
          });
        }
      } catch { /* ignore */ }
    }
  }

  // Check 5: Disabled plugin still has cache directory
  // (We don't have enable/disable info from scan, skip for now unless we add it)

  // Check 6: install-counts-cache.json staleness
  if (configDir && entry.type === 'plugin') {
    const icPath = path.join(configDir, 'plugins', 'install-counts-cache.json');
    if (fs.existsSync(icPath)) {
      try {
        const stat = fs.statSync(icPath);
        const ageDays = (Date.now() - stat.mtimeMs) / (1000 * 60 * 60 * 24);
        if (ageDays > 30) {
          issues.push({
            severity: 'info',
            category: 'cache',
            message: `install-counts-cache.json is ${Math.round(ageDays)} days old`,
            fixable: true,
            fixAction: 'refresh-install-counts',
          });
        }
      } catch { /* ignore */ }
    }
  }

  // Compute overall health
  let health = 'healthy';
  if (issues.some(i => i.severity === 'error')) health = 'error';
  else if (issues.some(i => i.severity === 'warn')) health = 'warn';
  else if (issues.some(i => i.severity === 'info')) health = 'warn';

  return {
    ...entry,
    health,
    issues,
  };
}

function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { input += chunk; });
  process.stdin.on('end', () => {
    let data;
    try {
      data = JSON.parse(input);
    } catch (e) {
      process.stderr.write('Error: Invalid JSON input\n');
      process.exit(1);
    }

    for (const runtime of data.runtimes) {
      runtime.plugins = runtime.plugins.map(entry =>
        checkPlugin(entry, runtime.configDir)
      );
    }

    process.stdout.write(JSON.stringify(data, null, 2) + '\n');
  });
}

main();
```

- [ ] **Step 2: Test health.cjs with scan output**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs --json | node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-health.cjs | python3 -c "
import json, sys
data = json.load(sys.stdin)
total_issues = 0
for rt in data['runtimes']:
    for p in rt['plugins']:
        if p.get('issues'):
            total_issues += len(p['issues'])
            for i in p['issues']:
                print(f'  {i[\"severity\"]} [{i[\"category\"]}] {p[\"id\"]}: {i[\"message\"]}')
print(f'Total issues: {total_issues}')
"`
Expected: Lists integrity, cache, and config issues found. Zero crashes.

- [ ] **Step 3: Commit**

```bash
cd ~/.claude/skills/plugin-doctor
git add bin/plugin-doctor-health.cjs
git commit -m "feat(plugin-doctor): add health diagnostics module"
```

---

### Task 3: update.cjs — Plugin Update Execution

**Files:**
- Create: `~/.claude/skills/plugin-doctor/bin/plugin-doctor-update.cjs`

This script takes command-line arguments, reads scan output from stdin (or re-scans), and executes updates for each selected plugin using the appropriate method per type and runtime.

- [ ] **Step 1: Create the update script**

Create `~/.claude/skills/plugin-doctor/bin/plugin-doctor-update.cjs`:

```javascript
#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// --- Argument parsing ---
function parseArgs(argv) {
  const args = {
    all: false,
    id: null,
    runtime: null,
    dryRun: false,
    json: false,
    input: null,  // Path to scan JSON file (optional, re-scans if not provided)
  };

  let i = 2; // skip node and script
  while (i < argv.length) {
    switch (argv[i]) {
      case '--all': args.all = true; break;
      case '--id': args.id = argv[++i]; break;
      case '--runtime': args.runtime = argv[++i]; break;
      case '--dry-run': args.dryRun = true; break;
      case '--json': args.json = true; break;
      case '--input': args.input = argv[++i]; break;
      default:
        process.stderr.write(`Unknown argument: ${argv[i]}\n`);
        process.exit(1);
    }
    i++;
  }
  return args;
}

// --- Update methods ---
function updatePlugin(entry, runtime, dryRun) {
  const runtimeFlag = {
    'claude-code': '--claude',
    'codex': '--codex',
    'opencode': '--opencode',
  }[runtime.runtime] || '--claude';

  // Plugin name without @marketplace for CLI
  const pluginRef = entry.name;

  if (dryRun) {
    return {
      id: entry.id,
      action: 'would-update',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: `Would run: claude plugins update ${pluginRef}`,
    };
  }

  try {
    const cmd = `claude plugins update ${pluginRef}`;
    const out = execSync(cmd, {
      encoding: 'utf8',
      timeout: 180000,
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
    // Parse the output to determine new version
    const match = out.match(/(\d+\.\d+\.\d+)/g);
    const newVersion = match ? match[match.length - 1] : entry.latestVersion;
    return {
      id: entry.id,
      action: 'updated',
      fromVersion: entry.installedVersion,
      toVersion: newVersion,
      success: true,
      message: null,
    };
  } catch (e) {
    return {
      id: entry.id,
      action: 'failed',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: false,
      message: e.message.split('\n')[0],
    };
  }
}

function updateGSD(entry, runtime, dryRun) {
  const runtimeFlag = {
    'claude-code': '--claude',
    'codex': '--codex',
    'opencode': '--opencode',
  }[runtime.runtime] || '--claude';

  if (dryRun) {
    return {
      id: entry.id,
      action: 'would-update',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: `Would run: npx get-shit-done-cc ${runtimeFlag} --global`,
    };
  }

  try {
    const cmd = `npx -y --package=get-shit-done-cc@latest -- get-shit-done-cc ${runtimeFlag} --global`;
    execSync(cmd, {
      encoding: 'utf8',
      timeout: 300000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return {
      id: entry.id,
      action: 'updated',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: null,
    };
  } catch (e) {
    return {
      id: entry.id,
      action: 'failed',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: false,
      message: e.message.split('\n')[0],
    };
  }
}

function updateSkill(entry, runtime, dryRun) {
  if (!entry.installPath || !fs.existsSync(entry.installPath)) {
    return {
      id: entry.id,
      action: 'skipped',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: false,
      message: 'Install path not found',
    };
  }

  // Check if it's a git repo
  const gitDir = path.join(entry.installPath, '.git');
  if (!fs.existsSync(gitDir)) {
    return {
      id: entry.id,
      action: 'skipped',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: true,
      message: 'Not a git repository, cannot auto-update',
    };
  }

  if (dryRun) {
    return {
      id: entry.id,
      action: 'would-update',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: `Would run: git -C ${entry.installPath} pull --ff-only`,
    };
  }

  try {
    execSync('git pull --ff-only', {
      cwd: entry.installPath,
      encoding: 'utf8',
      timeout: 60000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return {
      id: entry.id,
      action: 'updated',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: null,
    };
  } catch (e) {
    return {
      id: entry.id,
      action: 'failed',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: false,
      message: `git pull failed: ${e.message.split('\n')[0]}`,
    };
  }
}

function updateRuntime(entry, runtime, dryRun) {
  const npmPackages = {
    'claude-code': '@anthropic-ai/claude-code',
    'codex': '@openai/codex',
    'opencode': 'opencode',
  };
  const pkg = npmPackages[runtime.runtime];
  if (!pkg) {
    return {
      id: entry.id,
      action: 'skipped',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: true,
      message: 'No known update method for this runtime',
    };
  }

  if (dryRun) {
    return {
      id: entry.id,
      action: 'would-update',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: `Would run: npm update -g ${pkg}`,
    };
  }

  try {
    execSync(`npm update -g ${pkg}`, {
      encoding: 'utf8',
      timeout: 300000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return {
      id: entry.id,
      action: 'updated',
      fromVersion: entry.installedVersion,
      toVersion: entry.latestVersion,
      success: true,
      message: null,
    };
  } catch (e) {
    return {
      id: entry.id,
      action: 'failed',
      fromVersion: entry.installedVersion,
      toVersion: null,
      success: false,
      message: e.message.split('\n')[0],
    };
  }
}

function updateEntry(entry, runtime, dryRun) {
  switch (entry.type) {
    case 'plugin': return updatePlugin(entry, runtime, dryRun);
    case 'gsd': return updateGSD(entry, runtime, dryRun);
    case 'skill': return updateSkill(entry, runtime, dryRun);
    case 'runtime': return updateRuntime(entry, runtime, dryRun);
    default:
      return {
        id: entry.id,
        action: 'skipped',
        fromVersion: entry.installedVersion,
        toVersion: null,
        success: false,
        message: `Unknown type: ${entry.type}`,
      };
  }
}

// --- Main ---
function main() {
  const args = parseArgs(process.argv);

  if (!args.all && !args.id) {
    process.stderr.write('Usage: plugin-doctor-update --all | --id <pluginId> [--runtime <name>] [--dry-run] [--json] [--input <file>]\n');
    process.exit(1);
  }

  // Get scan data
  let scanData;
  if (args.input) {
    scanData = JSON.parse(fs.readFileSync(args.input, 'utf8'));
  } else {
    // Re-run scan
    const scanScript = path.join(__dirname, 'plugin-doctor-scan.cjs');
    const scanOut = execSync(`node "${scanScript}" --json`, {
      encoding: 'utf8',
      timeout: 60000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    scanData = JSON.parse(scanOut);
  }

  const results = [];

  for (const runtime of scanData.runtimes) {
    // Filter by runtime if specified
    if (args.runtime && runtime.runtime !== args.runtime) continue;

    // Select entries to update
    let targets;
    if (args.id) {
      targets = runtime.plugins.filter(p => p.id === args.id);
    } else if (args.all) {
      targets = runtime.plugins.filter(p => p.status === 'outdated');
    } else {
      targets = [];
    }

    for (const entry of targets) {
      const result = updateEntry(entry, runtime, args.dryRun);
      results.push(result);
    }
  }

  const output = { results };

  if (args.json) {
    process.stdout.write(JSON.stringify(output, null, 2) + '\n');
  } else {
    // Human-readable output
    const updated = results.filter(r => r.action === 'updated');
    const skipped = results.filter(r => r.action === 'skipped');
    const failed = results.filter(r => r.action === 'failed');
    const dry = results.filter(r => r.action === 'would-update');

    for (const r of results) {
      const icon = r.success ? (r.action === 'updated' ? '✔' : r.action === 'would-update' ? '?' : '⊘') : '✘';
      const ver = r.toVersion ? `${r.fromVersion} → ${r.toVersion}` : `(${r.message || r.action})`;
      process.stdout.write(`  ${icon} ${r.id}  ${ver}\n`);
    }

    process.stdout.write(`\n`);
    process.stdout.write(`  Updated: ${updated.length + dry.length} | Skipped: ${skipped.length} | Failed: ${failed.length}\n`);
  }
}

main();
```

- [ ] **Step 2: Test update.cjs in dry-run mode**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-update.cjs --all --dry-run`
Expected: Lists what would be updated for all outdated plugins, without making changes.

- [ ] **Step 3: Test single plugin dry-run**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-update.cjs --id "gsd" --dry-run`
Expected: Shows the GSD update command that would run.

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/skills/plugin-doctor
git add bin/plugin-doctor-update.cjs
git commit -m "feat(plugin-doctor): add update execution module"
```

---

### Task 4: End-to-End Integration Test

**Files:**
- No new files — tests existing scripts in combination

- [ ] **Step 1: Run full scan → health pipeline**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-scan.cjs --json | node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-health.cjs > /tmp/plugin-doctor-report.json 2>&1 && echo "SUCCESS" || echo "FAILED"`
Expected: `SUCCESS` and valid JSON in `/tmp/plugin-doctor-report.json`.

- [ ] **Step 2: Verify report structure**

Run: `python3 -c "
import json
data = json.load(open('/tmp/plugin-doctor-report.json'))
print(f'Scan time: {data[\"scanTime\"]}')
print(f'Runtimes: {len(data[\"runtimes\"])}')
for rt in data['runtimes']:
    print(f'  {rt[\"runtime\"]}: {len(rt[\"plugins\"])} plugins')
    outdated = [p for p in rt['plugins'] if p['status'] == 'outdated']
    issues = sum(len(p.get('issues', [])) for p in rt['plugins'])
    healthy = sum(1 for p in rt['plugins'] if p.get('health') == 'healthy')
    print(f'    Outdated: {len(outdated)} | Issues: {issues} | Healthy: {healthy}')
    for p in outdated:
        print(f'    - {p[\"id\"]}: {p[\"installedVersion\"]} -> {p[\"latestVersion\"]}')
"`
Expected: Claude Code runtime with 30+ entries, summary showing outdated/issue counts.

- [ ] **Step 3: Verify update dry-run with scan input**

Run: `node ~/.claude/skills/plugin-doctor/bin/plugin-doctor-update.cjs --all --dry-run --input /tmp/plugin-doctor-report.json`
Expected: Lists would-be updates for all outdated items without errors.

---

### Task 5: SKILL.md Verification

**Files:**
- Modify: `~/.claude/skills/plugin-doctor/SKILL.md` (if needed)

- [ ] **Step 1: Test skill invocation via /plugin-doctor**

Type `/plugin-doctor` in a new Claude Code session and verify:
- Scan runs without error
- Health checks produce valid results
- Output displays as grouped table with all 3 runtimes
- Summary line shows correct counts

- [ ] **Step 2: Fix any output formatting issues in SKILL.md**

If the display doesn't match the expected format in DESIGN.md, adjust the table formatting logic in SKILL.md's Step 3.

- [ ] **Step 3: Final commit**

```bash
cd ~/.claude/skills/plugin-doctor
git add -A
git commit -m "feat(plugin-doctor): complete skill with scan, health, and update modules"
```
