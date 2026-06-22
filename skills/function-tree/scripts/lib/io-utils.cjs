'use strict';

const fs = require('fs');
const path = require('path');
const cp = require('child_process');
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

function readJsonSafe(p) {
  try { return readJson(p); } catch (_) { return null; }
}

function renderTemplate(template, values) {
  return template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, key) => Object.prototype.hasOwnProperty.call(values, key) ? values[key] : '');
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function skillDir() {
  return path.resolve(__dirname, '..', '..');
}

function gitHead(root) {
  try {
    return run('git', ['rev-parse', 'HEAD'], root).trim();
  } catch (_) {
    return '';
  }
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function safeFileName(value) {
  return String(value).replace(/[^a-zA-Z0-9._-]/g, '-');
}

function relPath(root, file) {
  const abs = path.isAbsolute(file) ? file : path.resolve(process.cwd(), file);
  const rel = path.relative(root, abs);
  return rel.split(path.sep).join('/');
}

function rel(root, p) {
  return path.relative(root, p).replace(/\\/g, '/') || '.';
}

function listStagedFiles(root) {
  try {
    const out = run('git', ['diff', '--cached', '--name-only', '--diff-filter=ACMRTUXB'], root);
    return out.split('\n').map((s) => s.trim()).filter(Boolean);
  } catch (_) {
    return [];
  }
}

function listWorktreeFiles(root) {
  try {
    const out = run('git', ['status', '--porcelain', '--untracked-files=all'], root);
    const files = [];
    for (const line of out.split('\n')) {
      if (!line) continue;
      // Status format: first 2 chars are XY status, 3rd char is space, rest is path.
      // Rename/copy entries have " -> " separating old and new paths.
      const trimmed = line.slice(3);
      if (!trimmed) continue;
      let p = trimmed;
      const arrowIdx = p.indexOf(' -> ');
      if (arrowIdx >= 0) p = p.slice(arrowIdx + 4);
      // Strip surrounding quotes that git uses for paths with special chars.
      if (p.startsWith('"') && p.endsWith('"')) p = p.slice(1, -1);
      if (p) files.push(p);
    }
    return Array.from(new Set(files));
  } catch (_) {
    return [];
  }
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
module.exports = { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles };
