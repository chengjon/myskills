'use strict';

// Discovery heuristics added in response to FUNCTION_TREE_REVIEW.md (盲区 A/B/C/D + E5).
// These five blind spots were observed on the qlib repo but abstract to any project:
//
//   A. pkg-root projects (`<pkg>/__init__.py` at repo root) — first-level subpackages
//      were swallowed because the package dir itself was treated as source root.
//   B. README H2/H3 + internal anchor links were not extracted — README-declared
//      capabilities never reached the candidate pool.
//   C. entry-points declared in pyproject.toml / setup.cfg / package.json / Cargo.toml
//      were marked 待核验 even when the target module + function existed (double evidence).
//   D. untracked / staged worktree files — the strongest signal for "planned/unfinished
//      work" — were invisible because init only scans committed files.
//   E5. CHANGELOG version blocks were ignored as a "已实现" candidate source.
//
// Each function returns the same candidate shape used by scan-project.cjs, plus an
// extra `source` field (`pkg-root` / `readme-heading` / `entrypoint` / `untracked`
// / `changelog`) so the planned promote-* subcommand family (S1) can filter by origin.
//
// These functions are language-agnostic — judgement is based on "does this look like
// a sub-module/entry-point/section", not on path names.

const fs = require('fs');
const path = require('path');

const { existingPaths, slugifyCandidate } = require('./helpers.cjs');
// firstExistingPath returns an ABSOLUTE path; we need relative paths here so
// we can re-join against `root` without double-prefixing. Wrap existingPaths.
function firstRelative(root, candidates) {
  const list = existingPaths(root, candidates);
  return list.length ? list[0] : '';
}
const { readFile } = require('./io-utils.cjs');

// Local copy of cleanMarkdownText / isUsefulCandidateName — kept here to avoid
// a circular require with scan-project.cjs. The text-cleaning rules match the
// scan-project.cjs versions exactly so heading text is normalized identically.
function cleanName(value) {
  return String(value || '')
    .replace(/^\[[ xX]\]\s+/, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/[：:。.,，；;]+$/g, '')
    .trim()
    .slice(0, 96);
}

function isUsefulName(value) {
  if (!value || value.length < 2) return false;
  if (/^https?:\/\//i.test(value)) return false;
  if (/^(todo|tbd|n\/a|none)$/i.test(value)) return false;
  return true;
}

// ---------- 盲区 A: pkg-root first-level subpackages ------------------------

// Detect whether a source root is itself a package/module (has a primary manifest
// file inside it). Returns one of: 'python' | 'node' | 'rust' | 'go' | null.
function detectRootPackageKind(rootDir) {
  if (!fs.existsSync(rootDir)) return null;
  if (fs.existsSync(path.join(rootDir, '__init__.py'))) return 'python';
  // Node: package.json with "main" or "exports", OR index.{js,ts}
  const pkgJson = path.join(rootDir, 'package.json');
  if (fs.existsSync(pkgJson)) {
    try {
      const pkg = JSON.parse(readFile(pkgJson));
      if (pkg && (pkg.main || pkg.exports || pkg.module)) return 'node';
    } catch (_) { /* malformed package.json — skip */ }
  }
  for (const idx of ['index.js', 'index.ts', 'index.mjs', 'index.cjs']) {
    if (fs.existsSync(path.join(rootDir, idx))) return 'node';
  }
  // Rust: Cargo.toml containing [lib] (crate root, not workspace root)
  if (fs.existsSync(path.join(rootDir, 'Cargo.toml'))) {
    const cargo = readFile(path.join(rootDir, 'Cargo.toml'));
    if (/\[lib\]/.test(cargo)) return 'rust';
  }
  // Go: any .go file declaring `package <name>`
  try {
    for (const entry of fs.readdirSync(rootDir)) {
      if (!entry.endsWith('.go')) continue;
      const text = readFile(path.join(rootDir, entry));
      if (/^\s*package\s+[A-Za-z_][\w]*\s*$/m.test(text)) return 'go';
    }
  } catch (_) { /* not a directory or unreadable */ }
  return null;
}

// A first-level subdir qualifies as a sub-module when it carries the language's
// primary manifest file. The check is per-language so we don't promote random
// asset/doc directories.
function subdirQualifiesAsModule(absSubdir, parentKind) {
  if (!fs.existsSync(absSubdir) || !fs.statSync(absSubdir).isDirectory()) return false;
  switch (parentKind) {
    case 'python':
      return fs.existsSync(path.join(absSubdir, '__init__.py'));
    case 'node':
      if (fs.existsSync(path.join(absSubdir, 'package.json'))) return true;
      for (const idx of ['index.js', 'index.ts', 'index.mjs', 'index.cjs']) {
        if (fs.existsSync(path.join(absSubdir, idx))) return true;
      }
      return false;
    case 'rust':
      if (fs.existsSync(path.join(absSubdir, 'Cargo.toml'))) return true;
      if (fs.existsSync(path.join(absSubdir, 'mod.rs'))) return true;
      return false;
    case 'go':
      try {
        for (const entry of fs.readdirSync(absSubdir)) {
          if (!entry.endsWith('.go')) continue;
          const text = readFile(path.join(absSubdir, entry));
          if (/^\s*package\s+[A-Za-z_][\w]*\s*$/m.test(text)) return true;
        }
      } catch (_) { /* ignore */ }
      return false;
    default:
      return false;
  }
}

// FT_REVIEW 盲区 A — promote first-level subpackages of a pkg-root source root.
// `sourceRoots` is the list returned by collectProjectInfo (already includes
// Python package roots, src/, etc.). For each root that is itself a package,
// enumerate its first-level subdirectories and emit one candidate per qualifying
// sub-module.
function collectPkgRootSubpackages(root, sourceRoots) {
  const candidates = [];
  const seen = new Set();
  for (const rel of sourceRoots) {
    const absRoot = path.join(root, rel);
    const kind = detectRootPackageKind(absRoot);
    if (!kind) continue;
    let entries = [];
    try { entries = fs.readdirSync(absRoot, { withFileTypes: true }); } catch (_) { continue; }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      // Skip generic non-capability directories. Generic enough to apply across
      // stacks: tests/examples/docs/benchmarks/build artifacts are universal.
      if (isGenericAuxDir(entry.name)) continue;
      const absSub = path.join(absRoot, entry.name);
      if (!subdirQualifiesAsModule(absSub, kind)) continue;
      const key = `${rel}/${entry.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const title = titleCaseSpaced(entry.name);
      candidates.push({
        id: slugifyCandidate(`pkg-${title}`),
        name: title,
        type: `pkg-root subpackage (${kind})`,
        status: '代码存在',
        evidence: `${rel}/${entry.name}/`,
        boundary: 'First-level subpackage of a pkg-root source; promote to a capability node after README/route verification.',
        source: 'pkg-root',
      });
    }
  }
  return candidates;
}

function isGenericAuxDir(name) {
  const lower = name.toLowerCase();
  return [
    'tests', 'test', '__tests__', '__mocks__', 'specs', 'spec',
    'examples', 'example', 'demo', 'demos', 'samples', 'sample',
    'docs', 'doc', 'documentation',
    'benchmarks', 'benchmark', 'bench',
    'build', 'dist', 'out', 'target', 'node_modules', '__pycache__',
    '.venv', 'venv', 'env', '.git', '.github', '.gitlab', '.idea', '.vscode',
    'scripts', 'tools', 'ci',
  ].includes(lower);
}

function titleCaseSpaced(name) {
  // kebab/snake -> Title Case, preserving common identifiers like "api", "http".
  return String(name || '')
    .replace(/[-_.]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .slice(0, 64) || String(name);
}

// ---------- 盲区 B: README H2/H3 + anchor links ----------------------------

// Section headings that are clearly process/meta, not capability declarations.
// Matches SKIP_HEADINGS in collectReadmeProductCandidates so this stays aligned.
const SKIP_README_HEADINGS = /^(branching\s+model|translation\s+process|deployment|documentation|contributing|license|code\s+of\s+conduct|security|changelog|roadmap|todo|installation|install|setup|getting\s+started|quick\s+start|development|testing|debugging|troubleshooting|faq|support$|need\s+help|acknowledgements?|sponsors?|badge|screenshots?|table\s+of\s+contents?|overview|intro|introduction|目录|简介|概述|安装|配置|快速开始|开发|测试|调试|故障排查|常见问题|帮助|致谢|赞助|许可证|行为准则|安全|更新日志|路线图|待办)/i;

// Synonym merge — "Features" / "Feature List" / "Key Features" all roll up to
// the same canonical section so we don't emit three near-duplicate candidates.
function canonicalHeading(value) {
  const v = String(value || '').toLowerCase().trim();
  if (/(^|\s)features?$/.test(v) || /key\s+features?/.test(v) || /feature\s+list/.test(v) || /功能列表/.test(v) || /核心功能/.test(v) || /主要功能/.test(v)) return 'Features';
  if (/modules?/.test(v) || /模块/.test(v)) return 'Modules';
  if (/components?/.test(v) || /组件/.test(v)) return 'Components';
  if (/capabilities?/.test(v) || /能力/.test(v)) return 'Capabilities';
  if (/quick\s+start/.test(v) || /快速开始/.test(v)) return 'Quick Start';
  return value;
}

// FT_REVIEW 盲区 B — extract every H2/H3 heading as a 声明实现 candidate, plus
// resolve internal/relative anchor links to file/dir evidence when the target
// exists in the repo. Section names are canonicalized so synonyms merge.
function collectReadmeHeadingCandidates(root) {
  const candidates = [];
  const readmePaths = existingPaths(root, ['README.md', 'README.zh.md', 'README.zh-CN.md', 'FEATURES.md', 'docs/README.md']);
  const seen = new Set();
  for (const rel of readmePaths) {
    let text = '';
    try { text = readFile(path.join(root, rel)); } catch (_) { continue; }
    const lines = text.split(/\r?\n/);
    const linkPattern = /\[([^\]]+)\]\(([^)]+)\)/g;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const headingMatch = line.match(/^\s{0,3}(#{2,3})\s+(.+?)\s*#*\s*$/);
      if (!headingMatch) continue;
      const raw = headingMatch[2];
      const cleaned = cleanName(raw);
      if (!cleaned || SKIP_README_HEADINGS.test(cleaned)) continue;
      // Collect any anchor links inside this heading line + the 8 following lines
      // (typical README pattern: heading → intro paragraph → bullet list with links).
      const windowLines = lines.slice(i, Math.min(i + 12, lines.length)).join('\n');
      const evidenceLinks = [];
      let m;
      while ((m = linkPattern.exec(windowLines)) !== null) {
        const label = cleanName(m[1]);
        const href = m[2];
        if (!label) continue;
        const resolved = resolveReadmeLink(root, href);
        if (resolved) evidenceLinks.push(`${label} → ${resolved}`);
      }
      const canonical = canonicalHeading(cleaned);
      const key = canonical.toLowerCase();
      if (seen.has(key)) {
        // Merge new evidence into the existing entry rather than emitting a dup.
        const existing = candidates.find((c) => c.name === canonical);
        if (existing && evidenceLinks.length) {
          for (const ev of evidenceLinks) {
            if (!existing.evidence.includes(ev)) existing.evidence += `; ${ev}`;
          }
        }
        continue;
      }
      seen.add(key);
      candidates.push({
        id: slugifyCandidate(`readme-${canonical}`),
        name: canonical,
        type: 'README heading',
        status: '声明实现',
        evidence: evidenceLinks.length ? `${rel} > ${cleaned}; ${evidenceLinks.slice(0, 4).join('; ')}` : `${rel} > ${cleaned}`,
        boundary: 'README-declared section; verify implementation before promoting to a product feature node.',
        source: 'readme-heading',
      });
    }
  }
  return candidates;
}

// Resolve a README anchor / relative link to a repo path when it exists.
// Returns the relative repo path (string) or '' if not resolvable.
function resolveReadmeLink(root, href) {
  const raw = String(href || '').trim();
  if (!raw || /^(https?:|mailto:|ftp:)/i.test(raw)) return '';
  // Strip #fragment and ?query so we can map to a file path.
  const hashIdx = raw.indexOf('#');
  if (hashIdx === 0) return ''; // pure in-page anchor — no file evidence
  const pathPart = (hashIdx === -1 ? raw : raw.slice(0, hashIdx)).trim();
  if (!pathPart) return '';
  const abs = path.join(root, pathPart);
  if (fs.existsSync(abs)) return pathPart;
  return '';
}

// ---------- 盲区 C: manifest entry-points with double evidence ---------------

// Parse `[project.scripts]` / `[tool.poetry.scripts]` / `[project.entry-points.*]`
// from pyproject.toml. Returns a list of { name, target, kind } where target is
// `module.path:func`.
function parsePyprojectEntryPoints(text) {
  const out = [];
  const seen = new Set();
  // scripts: foo = "mod:fn"
  const sections = ['project.scripts', 'tool.poetry.scripts'];
  for (const section of sections) {
    const block = matchTomlTable(text, section);
    if (!block) continue;
    const re = /^([\w.-]+)\s*=\s*["']([^"']+)["']/gm;
    let m;
    while ((m = re.exec(block)) !== null) {
      const key = `${section}:${m[1]}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ name: m[1], target: m[2], kind: 'py-script' });
    }
  }
  // entry-points group: [project.entry-points."some.group"] → one block per group
  const epRe = /\[project\.entry-points\.("[^"]+"|'[^']+'|[^\]]+)\]([\s\S]*?)(?=\n\[|$)/g;
  let em;
  while ((em = epRe.exec(text)) !== null) {
    const groupRaw = em[1].replace(/^["']|["']$/g, '');
    const block = em[2];
    const re = /^([\w.-]+)\s*=\s*["']([^"']+)["']/gm;
    let m;
    while ((m = re.exec(block)) !== null) {
      const key = `entry:${groupRaw}:${m[1]}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ name: m[1], target: m[2], kind: 'py-entrypoint', group: groupRaw });
    }
  }
  return out;
}

// Minimal TOML table matcher: returns the inner text of `[section]` up to the
// next top-level `[`. Section can be dotted (`project.scripts`).
//
// Implementation note: the lookahead must NOT use `$` with the `m` flag —
// `$` matches end-of-line under `m`, which lets the lazy `[\s\S]*?` short-
// circuit to the empty string at the first `\n` (the immediate end-of-line
// after `]`). We use `\n\[` (next table header) as the only terminator; for
// the last table in the file this still works because there's always at least
// a trailing newline or another section after real TOML content.
function matchTomlTable(text, section) {
  const escaped = section.replace(/[.]/g, '\\.');
  const re = new RegExp(`\\[\\s*${escaped}\\s*\\]([\\s\\S]*?)(?=\\n\\s*\\[)`);
  const m = text.match(re);
  return m ? m[1] : '';
}

// Resolve `module.path:func` to a (file, lineHint) pair when both exist.
// Returns { file, symbol, evidence } when the module file exists AND the symbol
// is defined in it (def/class/assignment); null otherwise.
function resolvePythonEntryPoint(root, target) {
  const m = String(target || '').match(/^([\w.]+):([A-Za-z_][\w]*)$/);
  if (!m) return null;
  const modulePath = m[1].replace(/\./g, '/');
  const symbol = m[2];
  const candidates = [
    path.join(root, `${modulePath}.py`),
    path.join(root, 'src', `${modulePath}.py`),
  ];
  for (const cand of candidates) {
    if (!fs.existsSync(cand)) continue;
    // Strong evidence: a def/class/assignment to `symbol` appears in the file.
    const text = readFile(cand);
    const defRe = new RegExp(`^(?:async\\s+)?(?:def|class)\\s+${escapeRe(symbol)}\\b|^${escapeRe(symbol)}\\s*=`, 'm');
    const relPath = path.relative(root, cand);
    if (defRe.test(text)) {
      return { file: relPath, symbol, evidence: `${relPath} defines ${symbol}` };
    }
    // Module exists but symbol not located — still counts as single-evidence (待核验).
    return { file: relPath, symbol, evidence: `${relPath} (symbol ${symbol} not located by name)` };
  }
  return null;
}

function escapeRe(s) { return String(s || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// Parse package.json `bin` / `exports` / `main` — returns one entry per bin/export.
function parsePackageJsonEntryPoints(text) {
  const out = [];
  let pkg;
  try { pkg = JSON.parse(text); } catch (_) { return out; }
  const push = (name, target, kind) => out.push({ name, target, kind });
  if (pkg.bin && typeof pkg.bin === 'object') {
    for (const k of Object.keys(pkg.bin)) push(k, pkg.bin[k], 'js-bin');
  } else if (typeof pkg.bin === 'string') {
    push(pkg.name || 'bin', pkg.bin, 'js-bin');
  }
  if (pkg.exports && typeof pkg.exports === 'object') {
    for (const k of Object.keys(pkg.exports)) push(k, pkg.exports[k], 'js-export');
  }
  if (pkg.main) push('main', pkg.main, 'js-main');
  return out;
}

function resolveJsEntryPoint(root, target) {
  const tgt = String(target || '');
  // exports can be objects — bail to single-evidence if so.
  if (typeof tgt !== 'string') return null;
  const rel = tgt.replace(/^\.\//, '');
  const abs = path.join(root, rel);
  if (fs.existsSync(abs)) {
    return { file: rel, evidence: `${rel} exists` };
  }
  // Try index.js inside directory targets.
  if (fs.existsSync(path.join(abs, 'index.js'))) {
    return { file: `${rel}/index.js`, evidence: `${rel}/index.js exists` };
  }
  return null;
}

// Parse Cargo.toml `[[bin]]` entries — name + path.
function parseCargoBinEntries(text) {
  const out = [];
  const re = /\[\[bin\]\]([\s\S]*?)(?=\n\[|$)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const block = m[1];
    const name = block.match(/^name\s*=\s*"([^"]+)"/m);
    const pathVal = block.match(/^path\s*=\s*"([^"]+)"/m);
    if (name) out.push({ name: name[1], target: pathVal ? pathVal[1] : '', kind: 'cargo-bin' });
  }
  return out;
}

// FT_REVIEW 盲区 C — manifest entry-points with double evidence.
// `已实现` when (1) declared in manifest AND (2) target module file exists AND
// (3) target symbol can be located by name. `待核验` when only (1) holds.
function collectManifestEntryPoints(root) {
  const candidates = [];

  // Python — pyproject.toml + setup.cfg + setup.py
  const pyproject = firstRelative(root, ['pyproject.toml']);
  if (pyproject) {
    const text = readFile(path.join(root, pyproject));
    for (const ep of parsePyprojectEntryPoints(text)) {
      const resolved = resolvePythonEntryPoint(root, ep.target);
      const verified = resolved && /defines /.test(resolved.evidence);
      candidates.push({
        id: slugifyCandidate(`ep-${ep.name}`),
        name: ep.name,
        type: ep.kind === 'py-entrypoint' ? `Python entry-point (${ep.group})` : 'Python script (pyproject)',
        status: verified ? '声明实现' : '待核验',
        evidence: `pyproject.toml ${ep.name} = "${ep.target}"${resolved ? `; ${resolved.evidence}` : ' (target module not found)'}`,
        boundary: verified
          ? 'Double-evidenced (manifest declaration + module defines the target).'
          : 'Declared in manifest only; locate the target module/function before promoting.',
        source: 'entrypoint',
        entrypoint_kind: ep.kind,
      });
    }
  }

  // setup.cfg [entry_points] — console_scripts / gui_scripts
  const setupCfg = firstRelative(root, ['setup.cfg']);
  if (setupCfg) {
    const text = readFile(path.join(root, setupCfg));
    const block = matchTomlTable(text, 'entry_points');
    if (block) {
      const re = /^([\w.-]+)\s*=\s*([\w.]+:[A-Za-z_][\w]*)\s*$/gm;
      let m;
      while ((m = re.exec(block)) !== null) {
        const resolved = resolvePythonEntryPoint(root, m[2]);
        const verified = resolved && /defines /.test(resolved.evidence);
        candidates.push({
          id: slugifyCandidate(`ep-${m[1]}`),
          name: m[1],
          type: 'Python script (setup.cfg)',
          status: verified ? '声明实现' : '待核验',
          evidence: `setup.cfg [entry_points] ${m[1]} = "${m[2]}"${resolved ? `; ${resolved.evidence}` : ''}`,
          boundary: verified ? 'Double-evidenced (manifest + module).' : 'Declared only.',
          source: 'entrypoint',
        });
      }
    }
  }

  // Node — package.json
  const pkgJson = firstRelative(root, ['package.json']);
  if (pkgJson) {
    const text = readFile(path.join(root, pkgJson));
    for (const ep of parsePackageJsonEntryPoints(text)) {
      const resolved = resolveJsEntryPoint(root, ep.target);
      candidates.push({
        id: slugifyCandidate(`ep-${ep.name}`),
        name: ep.name,
        type: `Node ${ep.kind}`,
        status: resolved ? '声明实现' : '待核验',
        evidence: `package.json ${ep.kind} ${ep.name} → ${ep.target}${resolved ? `; ${resolved.evidence}` : ''}`,
        boundary: resolved ? 'Manifest + target file exists.' : 'Declared only.',
        source: 'entrypoint',
      });
    }
  }

  // Rust — Cargo.toml [[bin]]
  const cargo = firstRelative(root, ['Cargo.toml']);
  if (cargo) {
    const text = readFile(path.join(root, cargo));
    for (const ep of parseCargoBinEntries(text)) {
      let resolved = null;
      if (ep.target) {
        const abs = path.join(root, ep.target);
        if (fs.existsSync(abs)) resolved = { evidence: `${ep.target} exists` };
      }
      candidates.push({
        id: slugifyCandidate(`ep-${ep.name}`),
        name: ep.name,
        type: 'Rust binary (Cargo)',
        status: resolved ? '声明实现' : '待核验',
        evidence: `Cargo.toml [[bin]] ${ep.name}${ep.target ? ` → ${ep.target}` : ''}${resolved ? `; ${resolved.evidence}` : ''}`,
        boundary: resolved ? 'Manifest + target file exists.' : 'Declared only.',
        source: 'entrypoint',
      });
    }
  }

  return candidates;
}

// ---------- 盲区 D: untracked / staged worktree files ----------------------

// FT_REVIEW 盲区 D — surface worktree-local state as `待实现` candidates.
// Uses git status --porcelain so it works in any git repo. Categories:
//   ??  untracked          → `待实现` candidate
//   A   staged-add         → `待实现` candidate (stronger; already on its way)
//   M   modified-tracked   → not a candidate by itself, but flagged via
//                            `worktree_state` metadata on the candidate
//                            derived from that file's directory (caller's job).
function collectWorktreeCandidates(root) {
  const candidates = [];
  let out = '';
  try {
    const { execSync } = require('child_process');
    // maxBuffer: 16 MB. Repos with large untracked trees (e.g. sibling tooling
    // dropped into the worktree) blow past the default 1 MB and cause ENOBUFS,
    // which would silently swallow ALL worktree signal — the worst possible
    // failure mode for "find in-progress work".
    out = execSync('git status --porcelain --untracked-files=all', {
      cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 16 * 1024 * 1024,
    });
  } catch (e) {
    // ENOBUFS or non-git: surface ENOBUFS as a sentinel candidate so the user
    // knows the discovery channel failed (rather than silently returning 0).
    if (e && /ENOBUFS/.test(String(e.message || e))) {
      candidates.push({
        id: 'wt-overflow',
        name: 'worktree-scan-overflow',
        type: 'discovery-warning',
        status: '待实现',
        evidence: 'git status output exceeded 16 MB; promote-untracked could not enumerate',
        boundary: 'Discovery-channel failure — too many untracked files to enumerate.',
        source: 'untracked',
        worktree_state: 'overflow',
      });
    }
    return candidates; /* not a git repo, or output too large */
  }
  const lines = String(out || '').split(/\r?\n/).filter(Boolean);
  for (const line of lines) {
    const status = line.slice(0, 2);
    const fileRaw = line.slice(3);
    const file = fileRaw.replace(/^"|"$/g, '');
    if (!file) continue;
    // Skip files inside .governance/ / .claude/ / node_modules — they're either
    // governance state itself or third-party noise.
    if (/^(?:\.governance|\.claude|node_modules)\//.test(file)) continue;
    if (status === '??') {
      candidates.push({
        id: slugifyCandidate(`wt-${file}`),
        name: worktreeCandidateName(file),
        type: 'untracked worktree file',
        status: '待实现',
        evidence: `git status: ?? ${file} (untracked file in worktree)`,
        boundary: 'Untracked worktree file — strongest in-progress signal. Verify intent before promoting.',
        source: 'untracked',
        worktree_state: 'untracked',
        file,
      });
    } else if (status === 'A ' || status === 'A') {
      candidates.push({
        id: slugifyCandidate(`wt-${file}`),
        name: worktreeCandidateName(file),
        type: 'staged worktree file',
        status: '待实现',
        evidence: `git status: A ${file} (staged for next commit)`,
        boundary: 'Staged worktree file — in-flight implementation. Verify scope before promoting.',
        source: 'untracked',
        worktree_state: 'staged',
        file,
      });
    }
    // M (modified) is not promoted on its own — see the audit note.
  }
  // Cap to keep noise bounded; user can `ft suggest-nodes` for finer control.
  return candidates.slice(0, 32);
}

function worktreeCandidateName(file) {
  // Derive a readable name from a path: use the file stem or the directory name
  // for files like `scripts/foo.py`. Stays language-agnostic.
  const parts = String(file || '').split('/');
  const last = parts[parts.length - 1] || file;
  const stem = last.replace(/\.[^.]+$/, '');
  return titleCaseSpaced(stem);
}

// ---------- E5: CHANGELOG version blocks ------------------------------------

// Recognized CHANGELOG file names across ecosystems.
const CHANGELOG_FILES = [
  'CHANGELOG.md', 'CHANGES.md', 'CHANGELOG.rst', 'CHANGES.rst',
  'HISTORY.md', 'HISTORY.rst', 'RELEASES.md', 'NEWS.md', 'CHANGES.txt',
];

// FT_REVIEW E5 — extract CHANGELOG version blocks as `声明实现` candidates.
// Each `## x.y.z` / `## Version x.y.z` / `# x.y.z` heading with its bullets
// becomes one candidate; bullets aggregate under the version name so we don't
// spam the pool with 30 micro-candidates per release.
function collectChangelogCandidates(root) {
  const candidates = [];
  const files = existingPaths(root, CHANGELOG_FILES);
  for (const rel of files) {
    let text = '';
    try { text = readFile(path.join(root, rel)); } catch (_) { continue; }
    const lines = text.split(/\r?\n/);
    let currentVersion = '';
    let bullets = [];
    const flush = () => {
      if (!currentVersion) return;
      if (!bullets.length) { currentVersion = ''; bullets = []; return; }
      const preview = bullets.slice(0, 3).join('; ');
      candidates.push({
        id: slugifyCandidate(`cl-${currentVersion}`),
        name: `${currentVersion} (CHANGELOG)`,
        type: 'released version',
        status: '声明实现',
        evidence: `${rel} > ${currentVersion}: ${preview}${bullets.length > 3 ? ` (+${bullets.length - 3} more)` : ''}`,
        boundary: 'CHANGELOG-declared release; treat as shipped unless explicit deprecation.',
        source: 'changelog',
      });
      currentVersion = '';
      bullets = [];
    };
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      // Headings like ## 1.2.3 / ## v1.2.3 / ## Version 1.2.3 / # 1.2.3 (2026-06-25)
      const hm = line.match(/^\s{0,3}#{1,3}\s+(?:Version\s+|v)?(\d+\.\d+(?:\.\d+)?(?:[\w.-]*))\b/i);
      if (hm) {
        flush();
        currentVersion = hm[1];
        bullets = [];
        continue;
      }
      // RST-style: `Version 1.2.3` followed by an underline of `-` or `=`.
      const rstMatch = line.match(/^\s*(?:Version\s+|v)?(\d+\.\d+(?:\.\d+)?(?:[\w.-]*))\s*$/i);
      const nextLine = lines[i + 1] || '';
      const rstUnderline = nextLine.match(/^\s*([-=~])\1+\s*$/);
      if (rstMatch && rstUnderline) {
        flush();
        currentVersion = rstMatch[1];
        bullets = [];
        continue;
      }
      if (!currentVersion) continue;
      const bm = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$/);
      if (bm) {
        const cleaned = cleanName(bm[1]);
        if (cleaned && isUsefulName(cleaned)) bullets.push(cleaned);
      }
    }
    flush();
  }
  return candidates.slice(0, 16);
}

// ---------- E4: CI / Makefile gate candidates -------------------------------

// FT_REVIEW E4 — surface CI workflow + Make/Just/Task targets as gate
// candidates so authorize --commit-gate @ci can reference the whole set.
// Returns plain strings (gate names) — these are NOT feature candidates, the
// caller renders them under a dedicated "Verification Gate Candidates" section.
function collectVerificationGateCandidates(root) {
  const gates = [];

  // GitHub Actions: parse `name:` of each workflow + per-job names.
  const workflowsDir = path.join(root, '.github', 'workflows');
  if (fs.existsSync(workflowsDir)) {
    let files = [];
    try { files = fs.readdirSync(workflowsDir); } catch (_) { files = []; }
    for (const f of files) {
      if (!/\.(ya?ml)$/i.test(f)) continue;
      let text = '';
      try { text = readFile(path.join(workflowsDir, f)); } catch (_) { continue; }
      const nameMatch = text.match(/^name:\s*(.+?)\s*$/m);
      if (nameMatch) gates.push(`ci:${nameMatch[1].replace(/^["']|["']$/g, '')}`);
      const jobRe = /^\s{2,}([A-Za-z0-9_-]+)\s*:/gm;
      let m;
      while ((m = jobRe.exec(text)) !== null) {
        if (/^(name|on|jobs|env|runs-on|steps|permissions|concurrency)$/.test(m[1])) continue;
        gates.push(`ci-job:${m[1]}`);
        if (gates.length >= 32) break;
      }
    }
  }

  // Makefile targets — reuse existing parser to stay aligned.
  try {
    const { collectMakeTargets, collectJustRecipes, collectTaskfileTasks } = require('./scan-ecosystem.cjs');
    for (const t of collectMakeTargets(root)) gates.push(`make:${t}`);
    for (const r of collectJustRecipes(root)) gates.push(`just:${r}`);
    for (const task of collectTaskfileTasks(root)) gates.push(`task:${task}`);
  } catch (_) { /* scan-ecosystem missing — skip */ }

  // Filter to "verification-like" names — those that match the audit's
  // keyword set. Generic names like `all` / `clean` are noise for gates.
  const VERIFICATION_RE = /^(ci:|ci-job:|.*(?:test|lint|check|verify|build|quality|spec))/i;
  const filtered = gates.filter((g) => VERIFICATION_RE.test(g));
  return Array.from(new Set(filtered)).slice(0, 24);
}

// ---------- Aggregate dispatcher -------------------------------------------

// FT_REVIEW dispatcher — called by scan-project.collectProjectInfo. Returns
// every new candidate kind. The caller merges them into featureCandidates /
// plannedCandidates (preserving each candidate's `source` for promote-* later).
function collectPkgManifestCandidates(root, sourceRoots) {
  const featureLike = [];
  const plannedLike = [];

  const subpackages = collectPkgRootSubpackages(root, sourceRoots);
  const headings = collectReadmeHeadingCandidates(root);
  const entrypoints = collectManifestEntryPoints(root);
  const changelog = collectChangelogCandidates(root);

  featureLike.push(...subpackages, ...headings, ...entrypoints, ...changelog);

  const worktree = collectWorktreeCandidates(root);
  plannedLike.push(...worktree);

  return {
    featureLike,
    plannedLike,
    gateCandidates: collectVerificationGateCandidates(root),
    // Counts used by the Discovery Summary (E1) — caller does not need to
    // re-derive these from the candidate arrays.
    coverage: {
      subpackages: subpackages.length,
      readmeHeadings: headings.length,
      entrypointsTotal: entrypoints.length,
      entrypointsVerified: entrypoints.filter((c) => c.status === '声明实现').length,
      changelog: changelog.length,
      worktree: worktree.length,
      gateCandidates: 0, // filled by caller after merging gateCandidates
    },
  };
}

module.exports = {
  collectPkgManifestCandidates,
  collectPkgRootSubpackages,
  collectReadmeHeadingCandidates,
  collectManifestEntryPoints,
  collectWorktreeCandidates,
  collectChangelogCandidates,
  collectVerificationGateCandidates,
  // exposed for tests
  _internal: {
    detectRootPackageKind,
    subdirQualifiesAsModule,
    resolvePythonEntryPoint,
    resolveReadmeLink,
    parsePyprojectEntryPoints,
    parsePackageJsonEntryPoints,
    parseCargoBinEntries,
    canonicalHeading,
  },
};
