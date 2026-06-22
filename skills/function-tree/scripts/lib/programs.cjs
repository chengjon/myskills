'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
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

function detectNestedProjectRoots(root) {
  // Scan for nested sub-projects one level below the repo root. Returns relative
  // paths of sub-project source directories so existing collect* functions can
  // scan them.
  //
  // Trigger conditions for each subdir (any one adds it to roots):
  //   1. package.json present → adds <dir>/src if exists, else <dir>
  //   2. pyproject.toml present → adds <dir>
  //   3. Python source layout: subdir contains .py files or __init__.py at top
  //      level (covers cases where root manifest covers the subdir, e.g. api/
  //      and open_notebook/ in open-notebook repo).
  //
  // Boundaries: only scans one level deep to avoid expensive walks; only
  // standard layout conventions are recognized.
  const roots = [];
  const ignored = new Set(['.git', '.governance', 'node_modules', 'dist', 'build', '.next', '.venv', '__pycache__', '.omc', 'tests', 'test', 'docs', 'documentation', 'scripts', 'tools', 'assets', 'public', 'static', 'migrations']);

  let topEntries = [];
  try {
    topEntries = fs.readdirSync(root, { withFileTypes: true });
  } catch (_) { return roots; }

  for (const entry of topEntries) {
    if (!entry.isDirectory() || entry.name.startsWith('.') || ignored.has(entry.name)) continue;
    const subdir = entry.name;
    const subdirPath = path.join(root, subdir);
    const pkgJson = path.join(subdirPath, 'package.json');
    const pyproject = path.join(subdirPath, 'pyproject.toml');
    const hasInit = fs.existsSync(path.join(subdirPath, '__init__.py'));
    const hasPyFiles = listContainsPyFiles(subdirPath);

    if (fs.existsSync(pkgJson)) {
      if (fs.existsSync(path.join(subdirPath, 'src')) && !roots.includes(`${subdir}/src`)) {
        roots.push(`${subdir}/src`);
      } else if (!roots.includes(subdir)) {
        roots.push(subdir);
      }
      continue;
    }
    if (fs.existsSync(pyproject) || hasInit || hasPyFiles) {
      if (!roots.includes(subdir)) roots.push(subdir);
    }
  }
  return roots;
}

function listContainsPyFiles(dir) {
  // Returns true if directory directly contains at least one .py file (non-recursive).
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (_) { return false; }
  for (const e of entries) {
    if (e.isFile() && e.name.endsWith('.py')) return true;
  }
  return false;
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
module.exports = { collectGovernancePrograms, detectNestedProjectRoots, listContainsPyFiles, readProgramTreeMeta, detectProjectName, detectPythonPackageRoots, collectStewardPrograms };
