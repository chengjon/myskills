'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile, slugifyCandidate } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { collectGovernancePrograms, detectNestedProjectRoots, listContainsPyFiles, readProgramTreeMeta, detectProjectName, detectPythonPackageRoots, collectStewardPrograms } = require('./programs.cjs');
// FT_REVIEW 盲区 A/B/C/D + E5 — discovery heuristics for pkg-root subpackages,
// README headings, manifest entry-points (double-evidence), untracked worktree
// files, CHANGELOG releases, and CI/Make gate candidates. Lives in a separate
// module so it can be unit-tested in isolation.
const { collectPkgManifestCandidates } = require('./scan-pkg-manifest.cjs');
const { collectSourceModules, collectPublicApiEntries, collectCommandEntries, collectPythonCliSubcommands, collectDocSystemInfo, collectExceptionHierarchy, collectConfigEntries, collectDependencyEntries, collectLanguageInfo, countExtensions, detectProjectVersion, collectOptionalDependencies, collectInlineDeps, collectDocCommandExamples, normalizeDocCommand, looksLikeRunnableProjectCommand, isSetupOnlyCommand, uniqueCommandExamples, collectMakeTargets, collectJustRecipes, collectTaskfileTasks, isPublicTaskName, uniqueNames, collectDeploymentCapabilityCandidates } = require('./scan-ecosystem.cjs');
const { collectUiEntries, collectFileBasedUiEntries, detectSubdirs, nextAppRouteFromFileRelative, nextPagesRouteFromFileRelative, svelteKitRouteFromFileRelative, collectFilesUnder, isPathlessUiSegment, collectNavigationUiEntries, isNavigationUiFile, sourceNavigationRouteMatches, collectSourceUiRouteEntries, sourceUiRouteMatches, uiEntry, normalizeUiRoute, isUsefulUiRoute, uniqueUiEntries, collectApiEntries, collectOpenApiEntries, collectSourceRouteEntries, sourceRouteMatches, apiEntry, isHttpMethod, isUsefulApiPath, uniqueApiEntries } = require('./scan-routes.cjs');
function collectProjectInfo(root) {
  const sourceRoots = existingPaths(root, [
    'src',
    'app',
    'lib',
    'packages',
    'crates',
    'services',
    'cmd',
    'internal',
    'tests',
    'test',
  ]);
  for (const pkgRoot of detectPythonPackageRoots(root)) {
    if (!sourceRoots.includes(pkgRoot)) sourceRoots.push(pkgRoot);
  }
  for (const nestedRoot of detectNestedProjectRoots(root)) {
    if (!sourceRoots.includes(nestedRoot)) sourceRoots.push(nestedRoot);
  }
  // Go projects put packages at the repo root (e.g. controller/, model/, relay/).
  // No `src/` or `cmd/` to anchor on, so we add '.' to mean "scan the root itself".
  // Same for Rust binary crates where the crate root holds lib.rs/main.rs next to Cargo.toml,
  // and for Python single-file modules (stockstats.py at repo root, no __init__.py package).
  // We gate on stack manifest presence so unknown stacks don't get a noisy full-root scan.
  const hasStackManifest = ['go.mod', 'Cargo.toml', 'pyproject.toml', 'setup.py', 'requirements.txt']
    .some((name) => fs.existsSync(path.join(root, name)));
  if (hasStackManifest && sourceRoots.length === 0) {
    sourceRoots.push('.');
  } else if (fs.existsSync(path.join(root, 'go.mod')) || fs.existsSync(path.join(root, 'Cargo.toml'))) {
    // Even when src/ exists in a Go/Rust project, also scan root for top-level packages.
    if (!sourceRoots.includes('.')) sourceRoots.push('.');
  }
  // Fix-2 (FT_SKILL_AUDIT generic): Root-level loose source files.
  // Python research repos, Ruby single-file gems, Node script collections, and
  // similar "flat" layouts put the actual source at the root (e.g. stockstats.py,
  // scraper.rb, train_pipeline.py). When ≥3 loose source files sit at the repo
  // root with no recognized sub-source dir, add '.' so they aren't invisible.
  // Threshold avoids false positives on repos that have a single root-level
  // script next to a normal src/ layout.
  if (!sourceRoots.includes('.') && countRootLevelSourceFiles(root) >= 3) {
    sourceRoots.push('.');
  }
  const manifests = existingPaths(root, [
    'package.json',
    'pyproject.toml',
    'Cargo.toml',
    'go.mod',
    'pom.xml',
    'build.gradle',
    'requirements.txt',
    'deno.json',
    'composer.json',
    'Gemfile',
  ]);
  const docs = existingPaths(root, [
    'README.md',
    'AGENTS.md',
    'CLAUDE.md',
    'CONTRIBUTING.md',
    'docs',
  ]);
  const commandEntries = collectCommandEntries(root);
  const uiEntries = collectUiEntries(root, sourceRoots);
  const apiEntries = collectApiEntries(root, sourceRoots);
  // FT_REVIEW 盲区 A/B/C/D + E5 — collect pkg-root subpackages, README H2/H3
  // + anchor links, manifest entry-points (double-evidence), CHANGELOG
  // releases, worktree untracked files, and CI/Make gate candidates. The
  // dispatcher returns featureLike + plannedLike buckets so untracked worktree
  // files end up in plannedCandidates (待实现) while everything else augments
  // featureCandidates (where 声明实现 / 代码存在 / 待核验 live).
  const pm = collectPkgManifestCandidates(root, sourceRoots);
  const featureCandidates = uniqueCandidates([
    ...collectFeatureCandidates(root),
    ...collectEntrypointFeatureCandidates(uiEntries, apiEntries, commandEntries),
    ...pm.featureLike,
  ], 48);
  const plannedCandidates = uniqueCandidates([
    ...collectPlannedFeatureCandidates(root, sourceRoots),
    ...pm.plannedLike,
  ], 32);
  const pmCoverage = { ...pm.coverage, gateCandidates: pm.gateCandidates.length };

  // FT_REVIEW MED: attach normalized `source_category` + `kind` to every
  // candidate so ft diff / ft doc --report can group by the public vocabulary
  // without breaking the legacy `source` labels that promote-* filters depend on.
  const { normalizeCandidate } = require('./candidate-classify.cjs');
  for (const c of featureCandidates) normalizeCandidate(c);
  for (const c of plannedCandidates) normalizeCandidate(c);

  return {
    name: detectProjectName(root),
    head: gitHead(root),
    manifests,
    docs,
    sourceRoots,
    featureCandidates,
    plannedCandidates,
    publicApiEntries: collectPublicApiEntries(root, sourceRoots),
    sourceModules: collectSourceModules(root, sourceRoots),
    commandEntries,
    uiEntries,
    apiEntries,
    docSystemInfo: collectDocSystemInfo(root),
    exceptionEntries: collectExceptionHierarchy(root, sourceRoots),
    configEntries: collectConfigEntries(root, sourceRoots),
    dependencyEntries: collectDependencyEntries(root),
    languages: collectLanguageInfo(root, sourceRoots),
    version: detectProjectVersion(root),
    optionalDeps: collectOptionalDependencies(root),
    // Fix-7: deployment capability entries (Dockerfile, k8s, CI, etc.)
    deploymentEntries: collectDeploymentCapabilityCandidates(root),
    // Fix-5: project-level lifecycle signals (deprecation/lock). Used to flag
    // the whole project or specific feature candidates as DEPRECATED/LOCKED.
    lifecycleSignals: collectLifecycleSignals(root),
    // FT_REVIEW: gate candidates (ci:*, make:*, just:*, task:*) surfaced as
    // authorize --commit-gate @ci hints; coverage feeds Discovery Summary.
    gateCandidates: pm.gateCandidates,
    coverage: pmCoverage,
  };
}

// Fix-5 (FT_SKILL_AUDIT generic): Detect cross-language deprecation/lock signals.
// These are generic conventions used across Python/JS/Ruby/Go/Rust repos:
//
//   - "Status: deprecated" / "Status: Deprecated" lines in README/top-of-file
//   - @deprecated JSDoc/pydoc tags
//   - Branch name patterns (*-deprecated, deprecated-*, legacy-*) — from git
//   - Commit-message keywords in recent history (deprecate/sunset/archive/EOL)
//   - LOCKED/FROZEN/DO NOT MODIFY banners in top-level handbook files
//
// Returns { deprecated: bool, locked: bool, evidence: string[] }. Callers can
// use this to override the status of feature candidates or annotate the tree.
function collectLifecycleSignals(root) {
  const signals = { deprecated: false, locked: false, evidence: [] };

  // 1. Scan README and root Markdown for explicit status banners.
  const bannerFiles = existingPaths(root, [
    'README.md', 'README.zh.md', 'README.zh-CN.md',
    'STATUS.md', 'NOTICE.md', 'DEPRECATED.md',
  ]);
  const DEPRECATION_BANNER = /(?:^|\n)\s*(?:#+\s*)?(?:Status|状态)\s*[:：]\s*(?:deprecated|废弃|已废弃|sunset|end[\s-]?of[\s-]?life|eol|archived|已归档)/i;
  const LOCK_BANNER = /(?:^|\n)\s*(?:#+\s*)?(?:LOCKED|FROZEN|DO\s+NOT\s+MODIFY|FINAL\s+RELEASE|已锁定|已冻结|最终版)/i;
  for (const file of bannerFiles) {
    let text = '';
    try { text = readFile(path.join(root, file)); } catch (_) { continue; }
    if (DEPRECATION_BANNER.test(text)) {
      signals.deprecated = true;
      signals.evidence.push(`${file}: deprecation banner`);
    }
    if (LOCK_BANNER.test(text)) {
      signals.locked = true;
      signals.evidence.push(`${file}: lock banner`);
    }
  }
  if (signals.deprecated && signals.locked) return signals;

  // 2. Check current git branch name.
  try {
    const { execSync } = require('child_process');
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (/(?:^|[-_/])(deprecated|legacy|archived|sunset|eol|abandoned)(?:[-_/]|$)/i.test(branch)) {
      signals.deprecated = true;
      signals.evidence.push(`git branch: ${branch}`);
    }
    if (/(?:^|[-_/])(locked|frozen|final)(?:[-_/]|$)/i.test(branch)) {
      signals.locked = true;
      signals.evidence.push(`git branch: ${branch}`);
    }
  } catch (_) { /* not a git repo or git missing — skip */ }

  // 3. Recent commit history (last 30 commits) for sunset/EOL messages.
  try {
    const { execSync } = require('child_process');
    const log = execSync('git log --oneline -30', { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    const DEPRECATE_COMMIT = /\b(deprecat|sunset|end[\s-]?of[\s-]?life|\bEOL\b|archiv|abandon)/i;
    if (DEPRECATE_COMMIT.test(log) && !signals.deprecated) {
      // Don't mark the whole project deprecated based on a single commit (could
      // be one subsystem). Just record the evidence; caller decides.
      const line = log.split(/\r?\n/).find((l) => DEPRECATE_COMMIT.test(l));
      if (line) signals.evidence.push(`recent commit (review): ${line.slice(0, 80)}`);
    }
  } catch (_) { /* ignore */ }

  return signals;
}

function collectFeatureCandidates(root) {
  const readmePaths = ['README.md', 'FEATURES.md', 'docs/README.md', 'docs/features.md', 'docs/FEATURES.md'];
  // Each source gets its own budget so README sub-features don't starve route/model/EE candidates.
  // README product blocks are the strongest signal (declared-implemented), so they go first.
  const readme = uniqueCandidates(collectReadmeProductCandidates(root, readmePaths), 16);
  const rails = uniqueCandidates(collectRailsNamespaceCandidates(root), 10);
  const models = uniqueCandidates(collectModelPrefixCandidates(root), 8);
  const enterprise = uniqueCandidates(collectEnterpriseFeatureCandidates(root), 8);
  // Fix-3 (FT_SKILL_AUDIT generic): file-prefix families and report families.
  // Clusters loose files by `<prefix>_<rest>.<ext>` (≥3 files) and clusters
  // `<PROJECT>_<REPORT|HANDBOOK|SUMMARY|ANALYSIS|FINAL|SPEC|DESIGN|PLAN|RFC|ADR>.md`
  // (≥2 files). No hardcoded project-specific prefixes — only generic density signals.
  const prefixFamilies = uniqueCandidates(collectFilePrefixFamilies(root), 8);
  const reportFamilies = uniqueCandidates(collectReportFamilies(root), 6);
  // Legacy bullet-list candidates as the weakest signal — keep last, small budget.
  const legacy = uniqueCandidates(collectMarkdownCandidates(root, readmePaths, 'existing'), 8);
  return uniqueCandidates([...readme, ...rails, ...models, ...enterprise, ...prefixFamilies, ...reportFamilies, ...legacy], 40);
}

// Fix-2 helper: count root-level loose source files. Only counts files whose
// extension is a recognized source language, ignoring dotfiles, READMEs, and
// config files (package.json, Cargo.toml, etc. — those are manifests, not source).
function countRootLevelSourceFiles(root) {
  const SOURCE_EXTS = new Set([
    '.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.rb', '.go', '.rs', '.java', '.kt', '.swift',
    '.php', '.cs', '.c', '.cc', '.cpp', '.h', '.hpp',
    '.scala', '.clj', '.ex', '.exs', '.erl', '.lua',
    '.sh', '.bash', '.zsh',
  ]);
  let count = 0;
  try {
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isFile()) continue;
      if (entry.name.startsWith('.')) continue;
      const ext = path.extname(entry.name).toLowerCase();
      if (SOURCE_EXTS.has(ext)) count += 1;
    }
  } catch (_) { /* ignore */ }
  return count;
}

// Fix-3 helper: cluster loose files by `<prefix>_<rest>.<ext>` across the whole
// repo (root + one level deep). A family of ≥3 files sharing a prefix is a
// strong signal of a capability boundary — verify_*, train_*, parse_*, build_*,
// scrape_*, etc. The prefix itself is generic; we don't hardcode any names.
function collectFilePrefixFamilies(root) {
  const candidates = [];
  const files = collectTopAndSecondLevelFiles(root);
  const families = new Map(); // prefix -> { files: Set, ext: string }
  for (const file of files) {
    const base = path.basename(file);
    const ext = path.extname(base);
    const stem = base.slice(0, base.length - ext.length);
    // Match `prefix_rest` or `prefix-rest` (single separator). Reject files with
    // no separator (library.js → no family) and files where the "prefix" is too
    // short to be meaningful (≥2 chars).
    const m = stem.match(/^([a-z][a-z0-9]+)[_-](.+)$/i);
    if (!m) continue;
    const prefix = m[1].toLowerCase();
    if (prefix.length < 3) continue;
    // Skip generic noise prefixes that produce meaningless families.
    if (isGenericPrefixFamily(prefix)) continue;
    if (!families.has(prefix)) families.set(prefix, { files: new Set(), exts: new Set() });
    families.get(prefix).files.add(file);
    families.get(prefix).exts.add(ext);
  }
  for (const [prefix, { files, exts }] of families.entries()) {
    if (files.size < 3) continue;
    // Single-extension families of test files are test fixtures, not capabilities.
    if (exts.size === 1 && [...exts][0] === '.test.js') continue;
    const name = titleCase(prefix.replace(/_/g, ' '));
    candidates.push({
      id: slugifyCandidate(`prefix-${prefix}`),
      name: `${name} (script family)`,
      type: 'file-prefix family',
      status: '代码存在',
      evidence: `${files.size} files sharing \`${prefix}_\` prefix: ${Array.from(files).slice(0, 4).join(', ')}${files.size > 4 ? ', ...' : ''}`,
      boundary: 'File-clustered capability; verify shared purpose (CLI commands, build steps, ETL stages) before promoting to a product feature node.',
    });
  }
  return candidates;
}

// Fix-3 helper: cluster Markdown reports by uppercase project tag + report-kind
// keyword. `<PROJECT>_<REPORT|HANDBOOK|SUMMARY|ANALYSIS|FINAL|SPEC|DESIGN|PLAN|RFC|ADR>.md`
// is a near-universal convention across research/engineering projects. ≥2 files
// is enough because reports are usually few but high-signal.
//
// The tag is the FIRST underscore/dash-separated segment before a KIND keyword.
// So `B7E_REPORT.md`, `B7E_GAP_BENCHMARK_REPORT.md`, `B7E_ST_BIAS_REPORT.md`
// all share tag `B7E`. Likewise `API_V2_SPEC.md` → tag `API` (V2 is just a
// version qualifier; we treat the bare leading project code as the family key).
function collectReportFamilies(root) {
  const candidates = [];
  const files = collectTopAndSecondLevelFiles(root);
  // Strategy: for each Markdown file, check whether its stem contains a known
  // report-kind keyword (REPORT/HANDBOOK/SPEC/...) as an uppercase token. If so,
  // the family tag is the FIRST uppercase token in the stem. So `B7E_REPORT.md`,
  // `B7E_GAP_BENCHMARK_REPORT.md`, `B7E_ST_BIAS_REPORT.md` all cluster under `B7E`.
  // `B_LINE_HANDBOOK.md` clusters under `B` (single-letter, filtered later).
  // We accept tags of length ≥2 to avoid single-letter false families.
  const KIND_RE = /(?:^|[_\-])(REPORT|HANDBOOK|SUMMARY|ANALYSIS|FINAL|SPEC|DESIGN|PLAN|RFC|ADR|RESULTS|EVALUATION|POSTMORTEM|CHANGELOG)(?:[_\-\.]|$)/;
  const GENERIC = new Set(['README', 'LICENSE', 'CONTRIBUTING', 'CHANGELOG', 'TODO', 'ROADMAP', 'DOCS', 'API']);
  const families = new Map();
  for (const file of files) {
    if (!file.toLowerCase().endsWith('.md')) continue;
    const base = path.basename(file);
    if (!KIND_RE.test(base)) continue;
    const leadMatch = base.match(/^([A-Z][A-Z0-9]+)/);
    if (!leadMatch) continue;
    const tag = leadMatch[1];
    if (tag.length < 2) continue;
    if (GENERIC.has(tag)) continue;
    if (!families.has(tag)) families.set(tag, new Set());
    families.get(tag).add(file);
  }
  for (const [tag, fileSet] of families.entries()) {
    if (fileSet.size < 2) continue;
    const name = titleCase(tag.toLowerCase().replace(/_/g, ' '));
    candidates.push({
      id: slugifyCandidate(`report-${tag.toLowerCase()}`),
      name: `${name} (report family)`,
      type: 'report-cluster',
      status: '声明实现',
      evidence: `${fileSet.size} reports: ${Array.from(fileSet).slice(0, 4).join(', ')}${fileSet.size > 4 ? ', ...' : ''}`,
      boundary: 'Document-clustered capability; reports usually indicate a research/engineering sub-project. Verify scope before promoting.',
    });
  }
  return candidates;
}

function collectTopAndSecondLevelFiles(root) {
  const out = [];
  const ignored = new Set(['.git', 'node_modules', 'dist', 'build', '.next', '.venv', '__pycache__', '.governance', 'target', 'coverage', '.cache', 'vendor']);
  try {
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const rel = entry.name;
      if (entry.isFile()) {
        out.push(rel);
      } else if (entry.isDirectory() && !ignored.has(entry.name)) {
        try {
          for (const child of fs.readdirSync(path.join(root, rel), { withFileTypes: true })) {
            if (child.name.startsWith('.')) continue;
            if (child.isFile()) out.push(`${rel}/${child.name}`);
          }
        } catch (_) { /* ignore */ }
      }
    }
  } catch (_) { /* ignore */ }
  return out;
}

function isGenericPrefixFamily(prefix) {
  // Reject prefixes that produce noisy, meaningless families across any stack.
  // These are common boilerplate/library prefixes that don't indicate a capability.
  const GENERIC = new Set([
    'index', 'main', 'app', 'init', 'config', 'util', 'utils', 'helper', 'helpers',
    'test', 'tests', 'spec', 'mock', 'mocks', 'fixture', 'fixtures', 'sample', 'samples',
    'example', 'examples', 'demo', 'demos', 'vendor', 'third', 'party',
    'readme', 'license', 'changelog', 'todo', 'makefile',
    // Common test framework boilerplate
    'setup', 'teardown', 'conftest',
  ]);
  return GENERIC.has(prefix.toLowerCase());
}

// Detect emoji-led H2/H3 product blocks in README (e.g. "### ✨ Captain – AI Agent for Support").
// Returns product-level feature candidates with status `声明实现` (declared-implemented) since
// README marketing copy is the strongest "we have this feature" signal a project can send.
function collectReadmeProductCandidates(root, relativePaths) {
  const candidates = [];
  const SKIP_HEADINGS = [
    /^(branching\s+model|translation\s+process|deployment|documentation|contributing|license|code\s+of\s+conduct|security|changelog|roadmap|todo|installation|install|setup|getting\s+started|quick\s+start|development|testing|debugging|troubleshooting|faq|support$|need\s+help|acknowledgements?|sponsors?|badge|screenshots?|table\s+of\s+contents?|overview|intro|introduction)/i,
    /^(分支模型|翻译流程|部署|文档|贡献|许可证|行为准则|安全|更新日志|路线图|待办|安装|配置|快速开始|开发|测试|调试|故障排查|常见问题|帮助|致谢|赞助|概述|简介)/,
  ];
  const PRODUCT_EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/u;
  // Product-semantic keywords — an emoji-led heading must contain at least one
  // of these to be treated as a product block rather than a process/meta section.
  // ("Quick Start", "Documentation", "Roadmap", "Key Features" all fail this gate
  // because the words are generic, not product-capability words.)
  const HEADING_HAS_PRODUCT_KEYWORD = /\b(captain|omnichannel|support\s+desk|help\s+center|help\s+centre|portal|inbox|dashboard|crm|chat|messaging|campaigns?|automation|workflow|integrations?|channels?|reporting|analytics|ai\s+agent|assistant|bot|surveys?|csat|sla|teams?|macros?|custom\s+attributes|segments?|segments?|knowledge\s+base|faq|canned\s+responses|webhooks?|api|rest\s+api|graphql|sdk|widget|live\s+chat|email|voice|whatsapp|telegram|slack|linear|shopify|notion|dialogflow|salesforce|hubspot|intercom|zendesk|freshdesk|产品|功能|能力|模块|特性|客服|对话|消息|邮件|语音|机器人|帮助中心|知识库)\b/i;
  const SUB_CATEGORY_HEADINGS = /\b(collaboration|productivity|customer\s+data|segmentation|integrations?|channels?|automation|reporting|analytics|ai|artificial\s+intelligence|features)\b/i;

  for (const relativePath of existingPaths(root, relativePaths)) {
    const text = readFile(path.join(root, relativePath));
    const lines = text.split(/\r?\n/);
    let currentProduct = null;     // {name, evidence} when inside a product block
    let currentCategory = null;    // sub-category name (e.g. "Collaboration & Productivity")
    let productLines = [];         // collected paragraph lines for currentProduct

    const flushProduct = () => {
      if (!currentProduct) return;
      const description = productLines.join(' ').trim();
      if (description) {
        currentProduct.evidence.push(`description: ${description.slice(0, 160)}`);
      }
      candidates.push({
        id: slugifyCandidate(currentProduct.name),
        name: currentProduct.name,
        type: 'product feature (README)',
        status: '声明实现',
        evidence: currentProduct.evidence.join('; '),
        boundary: 'README-marketed capability; treat as declared-implemented pending code verification.',
      });
      currentProduct = null;
      productLines = [];
    };

    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const headingMatch = line.match(/^\s{0,3}(#{2,4})\s+(.+?)\s*#*\s*$/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const raw = headingMatch[2];
        const cleaned = cleanMarkdownText(raw);

        // Process/documentation section — stop product context, skip bullets
        if (SKIP_HEADINGS.some((re) => re.test(cleaned))) {
          flushProduct();
          currentCategory = null;
          continue;
        }

        // Emoji-led H2/H3 heading => product block.
        // Two gates: emoji present AND at least one product-semantic keyword in
        // the heading. The keyword gate is what separates "✨ Captain – AI Agent"
        // (product) from "🚀 Quick Start" / "📚 Documentation" / "📖 Need Help?"
        // (process/meta sections that happen to have emojis too).
        if (level <= 3 && PRODUCT_EMOJI.test(raw) && HEADING_HAS_PRODUCT_KEYWORD.test(cleaned)) {
          flushProduct();
          currentCategory = null;
          // Strip emoji + dash separator to get clean name: "✨ Captain – AI Agent" -> "Captain"
          // Use the part before dash/em-dash/en-dash/colon if present
          const nameOnly = raw
            .replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu, '')
            .replace(/^\s*[–—\-:•]+\s*/, '')
            .split(/\s+[–—\-:]\s+|:\s+/)[0]
            .trim();
          const name = cleanMarkdownText(nameOnly) || cleaned;
          if (!isUsefulCandidateName(name)) continue;
          currentProduct = {
            name,
            evidence: [`${relativePath} > ${cleaned}`],
          };
          continue;
        }

        // H4 sub-category under a product block => bullet features are sub-capabilities
        if (level === 4 && SUB_CATEGORY_HEADINGS.test(cleaned)) {
          // Don't flush — stay in current product, but track category for bullet naming
          currentCategory = cleaned;
          continue;
        }

        // Any other heading ends product context
        flushProduct();
        currentCategory = null;
        continue;
      }

      // Paragraph text inside a product block (not a bullet, not a heading)
      if (currentProduct && line.trim() && !/^\s*(?:[-*+]|\d+[.)])\s+/.test(line)) {
        const para = cleanMarkdownText(line);
        if (para && para.length > 20 && !/^<img|^!\[|^---/.test(line)) {
          productLines.push(para);
        }
        continue;
      }

      // Bullet under a sub-category or product block
      const bulletMatch = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$/);
      if (bulletMatch && (currentProduct || currentCategory)) {
        const bulletName = cleanMarkdownText(bulletMatch[1]);
        if (!isUsefulCandidateName(bulletName)) continue;
        const scope = currentCategory || currentProduct ? `${relativePath} > ${currentCategory || currentProduct.name}` : relativePath;
        candidates.push({
          id: slugifyCandidate(bulletName),
          name: bulletName,
          type: currentCategory ? `sub-feature (${currentCategory})` : 'README-listed capability',
          status: '声明实现',
          evidence: scope,
          boundary: 'README-listed capability; verify implementation and owner before marking implemented.',
        });
      }
    }
    flushProduct();
  }
  return candidates;
}

// Parse `config/routes.rb` (Rails) and cluster top-level namespaces into feature candidates.
// `namespace :portals do`, `namespace :captain do`, etc. are strong product boundaries.
function collectRailsNamespaceCandidates(root) {
  const candidates = [];
  const routesPath = firstExistingPath(root, ['config/routes.rb']);
  if (!routesPath) return candidates;
  const text = readFile(routesPath);
  const namespaceResources = new Map(); // ns -> Set of resources
  const stack = [];
  const namespaceStack = () => stack.filter((s) => s.type === 'namespace').map((s) => s.name);

  // Tokenize line-by-line; we don't need a real Ruby parser, just `namespace :x do` / `resources :y` / `end`.
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, '');
    const nsMatch = line.match(/^\s*namespace\s+[:@]?([A-Za-z_][\w]*)/);
    const resMatch = line.match(/^\s*resources?\s+:([A-Za-z_][\w]*)/);
    const scopeMatch = line.match(/^\s*scope\s+(?:'[^']+'|"[^"]+"|:[\w]+)\s+do/);
    const endMatch = /^\s*end\b/.test(line);

    if (nsMatch) {
      stack.push({ type: 'namespace', name: nsMatch[1] });
      const topNs = namespaceStack()[0];
      if (topNs && !namespaceResources.has(topNs)) namespaceResources.set(topNs, new Set());
    } else if (resMatch) {
      const topNs = namespaceStack()[0];
      if (topNs) {
        if (!namespaceResources.has(topNs)) namespaceResources.set(topNs, new Set());
        namespaceResources.get(topNs).add(resMatch[1]);
      }
    } else if (scopeMatch) {
      stack.push({ type: 'scope' });
    }
    if (endMatch && stack.length) stack.pop();
  }

  // Filter out generic namespaces (api, v1, v2) — they are URL prefixes, not product boundaries.
  const GENERIC_NS = new Set(['api', 'v1', 'v2', 'v3', 'public', 'internal', 'admin', 'oauth', 'auth']);
  for (const [ns, resources] of namespaceResources.entries()) {
    if (GENERIC_NS.has(ns.toLowerCase())) continue;
    if (resources.size < 1) continue;
    const name = titleCase(ns.replace(/_/g, ' '));
    candidates.push({
      id: slugifyCandidate(name),
      name,
      type: 'route namespace (Rails)',
      status: '代码存在',
      evidence: `config/routes.rb > namespace :${ns} (${resources.size} resource${resources.size > 1 ? 's' : ''}: ${Array.from(resources).slice(0, 5).join(', ')}${resources.size > 5 ? ', ...' : ''})`,
      boundary: 'Route-clustered capability; verify controller/model/intent before promoting to a product feature node.',
    });
  }
  return candidates;
}

// Scan `app/models/*.rb` and cluster by business prefix.
// `csat_*` -> "CSAT Surveys", `reporting_*` -> "Reports", `working_hour*` -> "Business Hours", etc.
function collectModelPrefixCandidates(root) {
  const candidates = [];
  const modelDirs = existingPaths(root, ['app/models', 'app/models/concerns']);
  if (!modelDirs.length) return candidates;

  // Prefixes we explicitly recognize with a human label.
  const KNOWN_PREFIXES = [
    { re: /^csat_/, label: 'CSAT Surveys' },
    { re: /^reporting_/, label: 'Reports' },
    { re: /^working_?hour/, label: 'Business Hours' },
    { re: /^team/, label: 'Teams' },
    { re: /^custom_?attribute/, label: 'Custom Attributes' },
    { re: /^custom_?filter/, label: 'Custom Filters & Segments' },
    { re: /^inbox/, label: 'Inboxes' },
    { re: /^campaign/, label: 'Campaigns' },
    { re: /^webhook/, label: 'Webhooks' },
    { re: /^integration/, label: 'Integrations' },
    { re: /^dashboard_?app/, label: 'Dashboard Apps' },
    { re: /^automation_?rule/, label: 'Automation Rules' },
    { re: /^agent_?bot/, label: 'Agent Bots' },
    { re: /^captain/, label: 'Captain (AI Assistant)' },
    { re: /^portal/, label: 'Help Center Portals' },
    { re: /^article/, label: 'Help Center Articles' },
    { re: /^category/, label: 'Help Center Categories' },
    { re: /^macro/, label: 'Macros' },
    { re: /^sla/, label: 'SLA Policies' },
  ];

  const counts = new Map(); // label -> { files, prefix }
  for (const dir of modelDirs) {
    const absDir = path.isAbsolute(dir) ? dir : path.join(root, dir);
    let entries = [];
    try { entries = fs.readdirSync(absDir); } catch (_) { continue; }
    for (const file of entries) {
      if (!file.endsWith('.rb')) continue;
      const stem = file.replace(/\.rb$/, '');
      for (const { re, label } of KNOWN_PREFIXES) {
        if (re.test(stem)) {
          if (!counts.has(label)) counts.set(label, { files: new Set(), prefix: label });
          counts.get(label).files.add(file);
          break;
        }
      }
    }
  }

  for (const [label, { files }] of counts.entries()) {
    if (files.size < 1) continue;
    // For single-file clusters, only emit if the prefix is in a strong product-semantic set
    // (these prefixes almost always indicate a product capability even with one model).
    const STRONG_SINGLETON_PREFIXES = /^(CSAT|Reports?|SLA|Captain|Help Center|Macros?|Agent Bots?|Campaigns?|Webhooks?|Integrations?)/;
    if (files.size === 1 && !STRONG_SINGLETON_PREFIXES.test(label)) continue;
    candidates.push({
      id: slugifyCandidate(label),
      name: label,
      type: 'model cluster (Rails)',
      status: '代码存在',
      evidence: `app/models/ — ${files.size} file${files.size > 1 ? 's' : ''}: ${Array.from(files).slice(0, 4).join(', ')}${files.size > 4 ? ', ...' : ''}`,
      boundary: 'Model-clustered capability; verify README/route coverage before promoting to a product feature node.',
    });
  }
  return candidates;
}

// Scan `enterprise/app/<kind>/<feature>/` directories and register each as an EE-only feature.
function collectEnterpriseFeatureCandidates(root) {
  const candidates = [];
  const eeRoot = firstExistingPath(root, ['enterprise/app']);
  if (!eeRoot) return candidates;

  // Collect all sub-feature dirs across the enterprise/app/* layers.
  // voice/, sla/, companies/, onboarding/, firecrawl/, cloudflare/ each indicate a product capability
  // gated behind enterprise. The same sub-name may appear under services/, controllers/, jobs/ — dedupe by name.
  const seen = new Set();
  const GENERIC_EE = new Set(['concerns', 'helpers', 'base', 'application']);
  let layers = [];
  try { layers = fs.readdirSync(eeRoot, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name); } catch (_) { return candidates; }

  for (const layer of layers) {
    const layerPath = path.join(eeRoot, layer);
    let features = [];
    try { features = fs.readdirSync(layerPath, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name); } catch (_) { continue; }
    for (const feat of features) {
      if (GENERIC_EE.has(feat.toLowerCase())) continue;
      if (seen.has(feat)) continue;
      seen.add(feat);
      const name = titleCase(feat.replace(/_/g, ' '));
      candidates.push({
        id: slugifyCandidate(`ee-${name}`),
        name: `${name} (Enterprise)`,
        type: 'EE-only feature',
        status: '代码存在',
        evidence: `enterprise/app/${layer}/${feat}/`,
        boundary: 'Enterprise-only capability; verify licensing, feature gate, and product owner before documenting as a feature.',
      });
    }
  }
  return candidates;
}

function renderFeatureOverviewLines(feature) {
  const lines = [
    `- ${feature.name}`,
    `  - Status: ${feature.status || '待核验'}`,
    `  - Type: ${feature.type || 'feature candidate'}`,
  ];
  const evidence = splitEvidenceItems(feature.evidence);
  if (evidence.length) {
    lines.push('  - Evidence:');
    for (const item of evidence) lines.push(`    - ${item}`);
  } else {
    lines.push('  - Evidence: 待登记');
  }
  if (feature.boundary) lines.push(`  - Boundary: ${feature.boundary}`);
  return lines;
}

function splitEvidenceItems(value) {
  return String(value || '')
    .split(/;\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function collectEntrypointFeatureCandidates(uiEntries, apiEntries, commandEntries) {
  const groups = new Map();

  function ensureGroup(key, name) {
    if (!key || !isUsefulCandidateName(name)) return null;
    if (!groups.has(key)) {
      groups.set(key, {
        name,
        evidence: [],
      });
    }
    return groups.get(key);
  }

  function addEvidence(group, evidence) {
    if (!group || group.evidence.includes(evidence)) return;
    group.evidence.push(evidence);
  }

  for (const entry of uiEntries) {
    const name = humanizeRouteFeatureName(entry.route);
    const group = ensureGroup(featureKey(name), name);
    addEvidence(group, `UI route \`${entry.route}\` (${entry.evidence})`);
  }
  for (const entry of apiEntries) {
    const baseName = humanizeRouteFeatureName(entry.path);
    const baseKey = featureKey(baseName);
    const group = groups.get(baseKey) || ensureGroup(featureKey(`${baseName} API`), `${baseName} API`);
    addEvidence(group, `API route \`${entry.method} ${entry.path}\` (${entry.evidence})`);
  }
  for (const command of commandEntries) {
    const key = matchingFeatureKeyForCommand(command, groups.keys());
    if (!key) continue;
    addEvidence(groups.get(key), `Command \`${command.command}\` (${command.evidence})`);
  }

  return uniqueCandidates(Array.from(groups.values()).map((group) => ({
    id: slugifyCandidate(group.name),
    name: group.name,
    type: 'entrypoint feature',
    status: '待核验',
    evidence: group.evidence.join('; '),
    boundary: 'Entrypoint-derived capability; verify product intent, owner, contracts, and completeness before marking implemented.',
  })), 16);
}

function collectPlannedFeatureCandidates(root, sourceRoots) {
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'ROADMAP.md', 'TODO.md', 'docs/roadmap.md', 'docs/ROADMAP.md', 'docs/todo.md', 'docs/TODO.md'], 'planned'),
    ...collectSourceTodoCandidates(root, sourceRoots),
  ], 16);
}

function collectMarkdownCandidates(root, relativePaths, mode) {
  const candidates = [];
  for (const relativePath of existingPaths(root, relativePaths)) {
    const text = readFile(path.join(root, relativePath));
    let heading = '';
    for (const line of text.split(/\r?\n/)) {
      const headingMatch = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
      if (headingMatch) {
        heading = cleanMarkdownText(headingMatch[1]);
        continue;
      }
      const bulletMatch = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$/);
      if (!bulletMatch || !headingMatchesCandidateMode(heading, mode)) continue;
      const name = cleanMarkdownText(bulletMatch[1]);
      if (!isUsefulCandidateName(name)) continue;
      candidates.push({
        id: slugifyCandidate(name),
        name,
        type: mode === 'planned' ? 'planned feature' : 'feature candidate',
        status: mode === 'planned' ? '待实现' : '待核验',
        evidence: heading ? `${relativePath} > ${heading}` : relativePath,
        boundary: mode === 'planned'
          ? 'Roadmap item; do not treat as implemented until evidence is added.'
          : 'README-listed capability; verify implementation and owner before marking implemented.',
      });
    }
  }
  return candidates;
}

function headingMatchesCandidateMode(heading, mode) {
  const value = String(heading || '').toLowerCase();
  const planned = /(roadmap|todo|planned|future|backlog|later|next|计划|规划|路线图|未完成|待实现|后续)/i.test(value);
  const existing = /(feature|capabilit|function|module|功能|能力|模块|特性|产品)/i.test(value);
  return mode === 'planned' ? planned : existing && !planned;
}

function cleanMarkdownText(value) {
  return String(value || '')
    .replace(/^\[[ xX]\]\s+/, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/[：:。.,，；;]+$/g, '')
    .trim()
    .slice(0, 96);
}

function isUsefulCandidateName(value) {
  if (!value || value.length < 2) return false;
  if (/^https?:\/\//i.test(value)) return false;
  if (/^(todo|tbd|n\/a|none)$/i.test(value)) return false;
  return true;
}

function humanizeRouteFeatureName(routePath) {
  const parts = String(routePath || '')
    .split(/[?#]/)[0]
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean)
    .filter((segment) => !/^v\d+$/i.test(segment))
    .filter((segment) => !isDynamicRouteSegment(segment))
    .map(cleanRouteSegment)
    .filter(Boolean);
  if (!parts.length) return 'Home';
  return titleCase(parts.join(' '));
}

function isDynamicRouteSegment(segment) {
  return /^\[.+\]$/.test(segment)
    || /^:.+/.test(segment)
    || /^\{.+\}$/.test(segment)
    || /^\(.+\)$/.test(segment);
}

function cleanRouteSegment(segment) {
  let value = String(segment || '').replace(/^\[+|\]+$/g, '');
  try {
    value = decodeURIComponent(value);
  } catch (_) {
    // Keep the raw segment if it is not URI-encoded text.
  }
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/[^A-Za-z0-9\u4e00-\u9fff ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function featureKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/api$/i, '')
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
}

function matchingFeatureKeyForCommand(command, featureKeys) {
  const haystack = featureKey(`${command.command} ${command.purpose || ''}`);
  for (const key of featureKeys) {
    if (key.length >= 4 && haystack.includes(key)) return key;
  }
  return '';
}

function uniqueCandidates(candidates, limit) {
  const seen = new Set();
  const unique = [];
  for (const candidate of candidates) {
    const key = candidate.name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(candidate);
    if (unique.length >= limit) break;
  }
  return unique;
}

// FT_REVIEW P4: parse a TODO/FIXME line into structured fields.
//
// Heuristics, in order:
//   1. Extract component (filename-ish or module-ish token) when the text
//      mentions "in <component>" or "<component>: ..." prefixes.
//   2. Extract action verb from a leading "add|support|fix|refactor|remove|
//      migrate|update|handle|improve|extract|replace|validate|test ..." token.
//   3. The remainder becomes `object` (the thing being acted on).
//   4. `category` is derived from action — capability gap vs maintenance.
//
// All fields are best-effort: empty strings when no signal is found. Callers
// must treat missing fields as "unknown", not "no TODO".
function parseTodoStructure(text) {
  const cleaned = String(text || '').trim();
  if (!cleaned) return { component: '', action: '', object: '', category: 'unknown' };

  // Component extraction: "in foo.bar:" / "foo.bar:" / "(foo) ..."
  let component = '';
  const compMatch = cleaned.match(/^\(?\s*([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)\s*\)?:\s*(.+)$/);
  if (compMatch) {
    component = compMatch[1];
  } else {
    const inMatch = cleaned.match(/\bin\s+([A-Za-z0-9_./-]+)\b/);
    if (inMatch) component = inMatch[1];
  }

  // Action extraction.
  const ACTION_RE = /^\s*(add|support|fix|handle|refactor|remove|migrate|update|improve|extract|replace|validate|test|implement|extend|document|clean|optimi[sz]e|configure|enable|disable|drop|deprecate)\b\s*(.*)$/i;
  const actionMatch = cleaned.match(ACTION_RE);
  let action = '';
  let object = cleaned;
  if (actionMatch) {
    action = actionMatch[1].toLowerCase();
    object = actionMatch[2].trim();
  }

  // Category derivation.
  const CAPABILITY_ACTIONS = new Set(['add', 'support', 'implement', 'extend', 'enable', 'handle']);
  const MAINTENANCE_ACTIONS = new Set(['refactor', 'remove', 'clean', 'optimi', 'optimize', 'deprecate', 'drop', 'replace', 'migrate', 'update']);
  const QUALITY_ACTIONS = new Set(['test', 'validate', 'document']);
  let category = 'unknown';
  if (CAPABILITY_ACTIONS.has(action)) category = 'capability';
  else if (MAINTENANCE_ACTIONS.has(action)) category = 'maintenance';
  else if (QUALITY_ACTIONS.has(action)) category = 'quality';

  return { component, action, object, category };
}

function collectSourceTodoCandidates(root, sourceRoots) {
  // FT_SKILL_REVIEW P1#6: Aggregate TODOs by file. A file that says "TODO: support X"
  // and "TODO: support Y" twice should produce one feature candidate ("support X, Y"
  // or just "support X" — first-wins) rather than two flat-listed entries. This
  // collapses noise when a single controller has 5 cleanup TODOs.
  //
  // We also apply a stronger implementation-note filter. Phrases like "delete this",
  // "move this to", "replace this", "clean up" signal in-place refactoring — they
  // are useful to the file's maintainer but not to someone reading a project-level
  // feature tree. We keep them only when the surrounding text reads like a real
  // capability gap (e.g. "TODO: support non-stream mode" survives; "TODO delete this
  // line" doesn't).
  const REFACTOR_NOISE = /\b(?:turn this into|consider|maybe|perhaps|refactor this|fix this later|cleanup needed|delete this|remove this|move this to|replace this|clean up this|clean this up|temporary|temp fix|typo)\b/i;
  const perFile = new Map(); // file -> array of { name, line, kind }
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    const isTestFile = isTestSourceFile(file);
    const text = readFile(path.join(root, file));
    const lines = text.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const match = line.match(/\b(?:TODO|FIXME|XXX|HACK)\b\s*(?:\([^)]*\)\s*)?[:\-]\s*(.+)$/i);
      if (!match) continue;
      const name = cleanMarkdownText(match[1]);
      if (!isUsefulCandidateName(name)) continue;
      if (REFACTOR_NOISE.test(name)) continue;
      const kind = isTestFile ? 'test improvement' : 'source TODO';
      if (!perFile.has(file)) perFile.set(file, []);
      perFile.get(file).push({ name, line: index + 1, kind });
    }
  }
  const candidates = [];
  for (const [file, entries] of perFile) {
    if (entries.length === 0) continue;
    // First non-noise entry's name is the candidate title. We intentionally don't
    // concatenate all entries — that would produce unreadable composite titles.
    // Multiple TODOs in one file collapse to one candidate with a count.
    const first = entries[0];
    const isTest = first.kind === 'test improvement';
    const evidenceSuffix = entries.length > 1 ? ` (+${entries.length - 1} more in this file)` : '';
    // FT_REVIEW P4: augment (not replace) per-file aggregation with a
    // structured component/action/object/category schema. The first TODO's
    // text is parsed into these fields on a best-effort basis so downstream
    // ft diff / ft doc --report can group by category without losing the
    // original per-file aggregation behavior.
    const structured = parseTodoStructure(first.name);
    candidates.push({
      id: slugifyCandidate(first.name),
      name: first.name,
      type: first.kind,
      status: '待实现',
      evidence: `${file}:${first.line}${evidenceSuffix}`,
      boundary: isTest
        ? 'Test improvement TODO; not a product roadmap item. Verify scope before implementation.'
        : 'Source code TODO; verify intent, owner, and priority before implementation.',
      // Structured fields (additive — older readers ignore them):
      component: structured.component,
      action: structured.action,
      object: structured.object,
      category: structured.category,
      todo_count_in_file: entries.length,
    });
    if (candidates.length >= 48) break;
  }
  return candidates;
}

function renderCandidateEvidenceLines(info) {
  const lines = [];
  if (info.featureCandidates.length) {
    lines.push('- Auto-discovered existing feature candidates:');
    for (const feature of info.featureCandidates) {
      lines.push(`  - ${feature.name}: ${feature.evidence}`);
    }
  }
  if (info.plannedCandidates.length) {
    lines.push('- Auto-discovered planned/unfinished feature candidates:');
    for (const feature of info.plannedCandidates) {
      lines.push(`  - ${feature.name}: ${feature.evidence}`);
    }
  }
  if (info.sourceModules.length) {
    lines.push('- Auto-discovered source modules:');
    for (const module of info.sourceModules) {
      lines.push(`  - \`${module.path}\``);
    }
  }
  if (info.commandEntries.length) {
    lines.push('- Auto-discovered project commands:');
    for (const command of info.commandEntries) {
      lines.push(`  - \`${command.command}\`: ${command.evidence}`);
    }
  }
  if (info.uiEntries.length) {
    lines.push('- Auto-discovered UI/page routes:');
    for (const entry of info.uiEntries) {
      lines.push(`  - \`${entry.route}\`: ${entry.evidence}`);
    }
  }
  if (info.apiEntries.length) {
    lines.push('- Auto-discovered API/service routes:');
    for (const entry of info.apiEntries) {
      lines.push(`  - \`${entry.method} ${entry.path}\`: ${entry.evidence}`);
    }
  }
  if (info.publicApiEntries && info.publicApiEntries.length) {
    lines.push('- Auto-discovered public API (__all__ exports):');
    for (const entry of info.publicApiEntries) {
      lines.push(`  - \`${entry.module}\`: ${entry.count} exports (${entry.exports.slice(0, 5).join(', ')}${entry.count > 5 ? ', ...' : ''})`);
    }
  }
  if (info.docSystemInfo && info.docSystemInfo.length) {
    lines.push('- Auto-discovered documentation systems:');
    for (const entry of info.docSystemInfo) {
      lines.push(`  - ${entry.system}: ${entry.evidence} (${entry.detail})`);
    }
  }
  if (info.exceptionEntries && info.exceptionEntries.length) {
    lines.push('- Auto-discovered exception hierarchy:');
    for (const entry of info.exceptionEntries) {
      lines.push(`  - \`${entry.name}\` extends \`${entry.parent}\` (source: \`${entry.module}\`)`);
    }
  }
  if (info.configEntries && info.configEntries.length) {
    lines.push('- Auto-discovered configuration/environment:');
    for (const entry of info.configEntries) {
      lines.push(`  - [${entry.type}] \`${entry.evidence}\`: ${entry.detail}`);
    }
  }
  if (info.dependencyEntries && info.dependencyEntries.length) {
    lines.push('- Auto-discovered core dependencies:');
    for (const entry of info.dependencyEntries) {
      lines.push(`  - \`${entry.name}\` [${entry.category}]`);
    }
  }
  if (info.optionalDeps && info.optionalDeps.length) {
    lines.push('- Auto-discovered optional dependency groups:');
    for (const entry of info.optionalDeps) {
      lines.push(`  - \`${entry.group}\`: ${entry.deps.slice(0, 6).join(', ')}${entry.deps.length > 6 ? ', ...' : ''} (${entry.evidence})`);
    }
  }
  if (info.languages && info.languages.length) {
    lines.push(`- Detected languages: ${info.languages.map((l) => `${l.language} (${l.percentage}%)`).join(', ')}`);
  }
  if (lines.length) lines.push('');
  return lines;
}
module.exports = { collectProjectInfo, collectFeatureCandidates, renderFeatureOverviewLines, splitEvidenceItems, collectEntrypointFeatureCandidates, collectPlannedFeatureCandidates, collectMarkdownCandidates, headingMatchesCandidateMode, cleanMarkdownText, isUsefulCandidateName, humanizeRouteFeatureName, isDynamicRouteSegment, cleanRouteSegment, featureKey, matchingFeatureKeyForCommand, uniqueCandidates, collectSourceTodoCandidates, renderCandidateEvidenceLines, countRootLevelSourceFiles, collectFilePrefixFamilies, collectReportFamilies, collectTopAndSecondLevelFiles, isGenericPrefixFamily, collectLifecycleSignals };
