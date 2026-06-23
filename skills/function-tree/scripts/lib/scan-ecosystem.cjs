'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
function collectSourceModules(root, sourceRoots) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const sourceExt = /\.(js|jsx|ts|tsx|py|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp)$/i;
  const modules = [];
  for (const sourceRoot of sourceRoots) {
    const absoluteRoot = path.join(root, sourceRoot);
    if (!fs.existsSync(absoluteRoot) || !fs.statSync(absoluteRoot).isDirectory()) continue;
    const topEntries = fs.readdirSync(absoluteRoot, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of topEntries) {
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      const isSource = entry.isDirectory() || sourceExt.test(entry.name);
      if (!isSource) continue;
      // Skip empty __init__.py — it's a package marker, not a real module
      if (entry.isFile() && entry.name === '__init__.py') {
        const initPath = path.join(absoluteRoot, entry.name);
        if (fs.statSync(initPath).size === 0) continue;
      }
      const relativePath = `${sourceRoot}/${entry.name}${entry.isDirectory() ? '/' : ''}`;
      modules.push({ path: relativePath });
      // Drill one level deeper for top-level directories so submodules are visible
      if (entry.isDirectory()) {
        const subPath = path.join(absoluteRoot, entry.name);
        try {
          const subEntries = fs.readdirSync(subPath, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
          for (const sub of subEntries) {
            if (sub.name.startsWith('.') || ignored.has(sub.name)) continue;
            const subIsSource = sub.isDirectory() || sourceExt.test(sub.name);
            if (!subIsSource) continue;
            if (sub.isFile() && sub.name === '__init__.py') {
              const initPath = path.join(subPath, sub.name);
              if (fs.statSync(initPath).size === 0) continue;
            }
            const subRelative = `${relativePath}${sub.name}${sub.isDirectory() ? '/' : ''}`;
            modules.push({ path: subRelative });
            if (modules.length >= 48) break;
          }
        } catch (_) { /* permission issue, skip */ }
      }
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
  const seen = new Set();
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

  function categorize(name) {
    const lower = name.toLowerCase();
    for (const [key, cat] of Object.entries(categoryMap)) {
      if (lower.includes(key) || key.includes(lower)) return cat;
    }
    return 'runtime';
  }

  function pushDep(name, evidence) {
    if (seen.has(name)) return;
    seen.add(name);
    deps.push({ name, category: categorize(name), evidence });
  }

  // Source 1: pyproject.toml
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const text = readFile(pyprojectPath);
    let depContent = '';
    const inlineMatch = text.match(/^dependencies\s*=\s*\[([\s\S]*?)\]/m);
    if (inlineMatch) depContent = inlineMatch[1];
    if (!depContent) {
      const sectionMatch = text.match(/\[project\.dependencies\]\s*\n([\s\S]*?)(?:\n\[|\n*$)/);
      if (sectionMatch) depContent = sectionMatch[1];
    }
    if (depContent) {
      for (const line of depContent.split('\n')) {
        const m = line.match(/["']\s*([A-Za-z0-9_-]+)/);
        if (m) pushDep(m[1], 'pyproject.toml [project.dependencies]');
        if (deps.length >= 32) break;
      }
    }
  }

  // Source 2: requirements.txt
  if (deps.length < 32) {
    const reqPath = path.join(root, 'requirements.txt');
    if (fs.existsSync(reqPath)) {
      for (const line of readFile(reqPath).split('\n')) {
        const m = line.match(/^\s*([A-Za-z0-9_-]+)/);
        if (m && m[1].length > 1) pushDep(m[1], 'requirements.txt');
        if (deps.length >= 32) break;
      }
    }
  }

  // Source 3: package.json
  if (deps.length < 32) {
    const pkgPath = path.join(root, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(readFile(pkgPath));
        for (const name of Object.keys(pkg.dependencies || {})) {
          pushDep(name, 'package.json dependencies');
          if (deps.length >= 32) break;
        }
      } catch (_) {}
    }
  }

  // Source 4: Cargo.toml
  if (deps.length < 32) {
    const cargoPath = path.join(root, 'Cargo.toml');
    if (fs.existsSync(cargoPath)) {
      const text = readFile(cargoPath);
      const sectionMatch = text.match(/\[dependencies\]\s*\n([\s\S]*?)(?:\n\[|\n*$)/);
      if (sectionMatch) {
        for (const line of sectionMatch[1].split('\n')) {
          const m = line.match(/^\s*([A-Za-z0-9_-]+)\s*[=]/);
          if (m) pushDep(m[1], 'Cargo.toml [dependencies]');
          if (deps.length >= 32) break;
        }
      }
    }
  }

  // Source 5: go.mod
  if (deps.length < 32) {
    const goModPath = path.join(root, 'go.mod');
    if (fs.existsSync(goModPath)) {
      let inRequire = false;
      for (const line of readFile(goModPath).split('\n')) {
        if (/^\s*require\s*\(/.test(line)) { inRequire = true; continue; }
        if (/^\s*\)/.test(line)) { inRequire = false; continue; }
        if (inRequire || /^\s*require\s+/.test(line)) {
          const m = line.match(/^\s*(\S+)\s+v/);
          if (m) {
            const pkgName = m[1].split('/').pop();
            if (pkgName && pkgName.length > 1) pushDep(pkgName, 'go.mod require');
          }
          if (deps.length >= 32) break;
        }
      }
    }
  }

  return deps;
}

function collectLanguageInfo(root, sourceRoots) {
  const extCounts = new Map();
  const dirs = sourceRoots.length ? sourceRoots : ['.'];
  for (const dir of dirs) {
    const absDir = path.join(root, dir);
    if (!fs.existsSync(absDir)) continue;
    try {
      countExtensions(absDir, extCounts, 3);
    } catch (_) { /* ignore */ }
  }
  // Map extensions to languages
  const extToLang = {
    '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.rs': 'Rust', '.go': 'Go', '.java': 'Java', '.kt': 'Kotlin', '.scala': 'Scala',
    '.rb': 'Ruby', '.php': 'PHP', '.cs': 'C#', '.cpp': 'C++', '.c': 'C', '.h': 'C/C++',
    '.swift': 'Swift', '.m': 'Objective-C', '.lua': 'Lua', '.r': 'R', '.R': 'R',
  };
  const langTotals = new Map();
  for (const [ext, count] of extCounts) {
    const lang = extToLang[ext];
    if (lang) langTotals.set(lang, (langTotals.get(lang) || 0) + count);
  }
  // Sort by count descending
  const sorted = [...langTotals.entries()].sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return [];

  const totalFiles = sorted.reduce((s, e) => s + e[1], 0);
  return sorted.map(([lang, count]) => ({
    language: lang,
    percentage: Math.round((count / totalFiles) * 100),
    files: count,
  }));
}

function countExtensions(dir, extCounts, maxDepth) {
  if (maxDepth <= 0) return;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (_) { return; }
  for (const entry of entries) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === '__pycache__' || entry.name === '.git') continue;
    if (entry.isDirectory()) {
      countExtensions(path.join(dir, entry.name), extCounts, maxDepth - 1);
    } else {
      const ext = path.extname(entry.name);
      if (ext) extCounts.set(ext, (extCounts.get(ext) || 0) + 1);
    }
  }
}

function detectProjectVersion(root) {
  // pyproject.toml: version = "X.Y.Z" or dynamic version
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const text = readFile(pyprojectPath);
    const v = text.match(/^\s*version\s*=\s*["']([^"']+)["']/m);
    if (v) return v[1];
    // Dynamic version — report that
    const dyn = text.match(/^\s*dynamic\s*=\s*\[([^\]]*version[^\]]*)\]/m);
    if (dyn) return 'dynamic';
  }
  // package.json
  const pkgPath = path.join(root, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(readFile(pkgPath));
      if (pkg.version) return pkg.version;
    } catch (_) {}
  }
  // Cargo.toml
  const cargoPath = path.join(root, 'Cargo.toml');
  if (fs.existsSync(cargoPath)) {
    const m = readFile(cargoPath).match(/^version\s*=\s*"([^"]+)"/m);
    if (m) return m[1];
  }
  return '';
}

function collectOptionalDependencies(root) {
  const groups = [];
  const pyprojectPath = path.join(root, 'pyproject.toml');
  if (fs.existsSync(pyprojectPath)) {
    const text = readFile(pyprojectPath);

    // Style 1: [project.optional-dependencies.GROUPNAME] (per-group section)
    const sectionRegex = /\[project\.optional-dependencies\.([A-Za-z0-9_-]+)\]\s*\n([\s\S]*?)(?=\n\[|\n*$)/g;
    let match;
    while ((match = sectionRegex.exec(text)) !== null) {
      const groupName = match[1];
      const content = match[2];
      const depNames = [];
      for (const line of content.split('\n')) {
        const m = line.match(/["']?\s*([A-Za-z0-9_-]+)/);
        if (m && m[1].length > 1) depNames.push(m[1]);
      }
      if (depNames.length) {
        groups.push({ group: groupName, deps: depNames.slice(0, 12), evidence: 'pyproject.toml' });
      }
      if (groups.length >= 16) break;
    }

    // Style 2: [project.optional-dependencies] with inline name = [...] entries
    if (groups.length < 16) {
      const baseSection = text.match(/\[project\.optional-dependencies\]\s*\n([\s\S]*?)(?=\n\[|\n*$)/);
      if (baseSection) {
        const sectionText = baseSection[1];
        let currentGroup = '';
        let currentDeps = [];
        for (const line of sectionText.split('\n')) {
          // Group header: groupname = [
          const groupMatch = line.match(/^([A-Za-z0-9_-]+)\s*=\s*\[/);
          if (groupMatch) {
            // Flush previous group
            if (currentGroup && currentDeps.length) {
              groups.push({ group: currentGroup, deps: currentDeps.slice(0, 12), evidence: 'pyproject.toml' });
            }
            currentGroup = groupMatch[1];
            currentDeps = [];
            // Collect deps on this line and subsequent lines until ]
            const rest = line.slice(line.indexOf('[') + 1);
            collectInlineDeps(rest, currentDeps);
            if (rest.includes(']')) {
              if (currentDeps.length) groups.push({ group: currentGroup, deps: currentDeps.slice(0, 12), evidence: 'pyproject.toml' });
              currentGroup = '';
              currentDeps = [];
            }
            continue;
          }
          // Continuation lines
          if (currentGroup) {
            collectInlineDeps(line, currentDeps);
            if (line.includes(']')) {
              if (currentDeps.length) groups.push({ group: currentGroup, deps: currentDeps.slice(0, 12), evidence: 'pyproject.toml' });
              currentGroup = '';
              currentDeps = [];
            }
          }
          if (groups.length >= 16) break;
        }
        // Flush last group
        if (currentGroup && currentDeps.length) {
          groups.push({ group: currentGroup, deps: currentDeps.slice(0, 12), evidence: 'pyproject.toml' });
        }
      }
    }
  }
  // requirements-*.txt
  try {
    for (const entry of fs.readdirSync(root)) {
      const reqMatch = entry.match(/^requirements[-.]([A-Za-z0-9_-]+)\.txt$/);
      if (reqMatch) {
        const groupName = reqMatch[1];
        const content = readFile(path.join(root, entry));
        const depNames = [];
        for (const line of content.split('\n')) {
          const m = line.match(/^\s*([A-Za-z0-9_-]+)/);
          if (m && m[1].length > 1) depNames.push(m[1]);
        }
        if (depNames.length) {
          groups.push({ group: groupName, deps: depNames.slice(0, 12), evidence: entry });
        }
        if (groups.length >= 16) break;
      }
    }
  } catch (_) {}
  // package.json optionalDependencies
  const pkgPath = path.join(root, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(readFile(pkgPath));
      for (const section of ['optionalDependencies', 'devDependencies']) {
        const deps = pkg[section];
        if (deps && typeof deps === 'object') {
          const names = Object.keys(deps);
          if (names.length) {
            groups.push({ group: section, deps: names.slice(0, 12), evidence: 'package.json' });
          }
        }
      }
    } catch (_) {}
  }
  return groups;
}

function collectInlineDeps(line, deps) {
  const re = /["']([A-Za-z0-9_-]+(?:\[.*?\])?)\s*(?:[><=!]+|;|@)/g;
  let m;
  while ((m = re.exec(line)) !== null) {
    const name = m[1].replace(/\[.*\]/, '');
    if (name.length > 1 && !deps.includes(name)) deps.push(name);
  }
  // Also match simple quoted names without version spec
  const simpleRe = /["']([A-Za-z0-9_-]+)["']/g;
  while ((m = simpleRe.exec(line)) !== null) {
    if (m[1].length > 1 && !deps.includes(m[1])) deps.push(m[1]);
  }
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
module.exports = { collectSourceModules, collectPublicApiEntries, collectCommandEntries, collectPythonCliSubcommands, collectDocSystemInfo, collectExceptionHierarchy, collectConfigEntries, collectDependencyEntries, collectLanguageInfo, countExtensions, detectProjectVersion, collectOptionalDependencies, collectInlineDeps, collectDocCommandExamples, normalizeDocCommand, looksLikeRunnableProjectCommand, isSetupOnlyCommand, uniqueCommandExamples, collectMakeTargets, collectJustRecipes, collectTaskfileTasks, isPublicTaskName, uniqueNames };
