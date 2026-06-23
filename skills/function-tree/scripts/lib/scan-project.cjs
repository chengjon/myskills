'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile, slugifyCandidate } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { collectGovernancePrograms, detectNestedProjectRoots, listContainsPyFiles, readProgramTreeMeta, detectProjectName, detectPythonPackageRoots, collectStewardPrograms } = require('./programs.cjs');
const { collectSourceModules, collectPublicApiEntries, collectCommandEntries, collectPythonCliSubcommands, collectDocSystemInfo, collectExceptionHierarchy, collectConfigEntries, collectDependencyEntries, collectLanguageInfo, countExtensions, detectProjectVersion, collectOptionalDependencies, collectInlineDeps, collectDocCommandExamples, normalizeDocCommand, looksLikeRunnableProjectCommand, isSetupOnlyCommand, uniqueCommandExamples, collectMakeTargets, collectJustRecipes, collectTaskfileTasks, isPublicTaskName, uniqueNames } = require('./scan-ecosystem.cjs');
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
  const featureCandidates = uniqueCandidates([
    ...collectFeatureCandidates(root),
    ...collectEntrypointFeatureCandidates(uiEntries, apiEntries, commandEntries),
  ], 48);

  return {
    name: detectProjectName(root),
    head: gitHead(root),
    manifests,
    docs,
    sourceRoots,
    featureCandidates,
    plannedCandidates: collectPlannedFeatureCandidates(root, sourceRoots),
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
  };
}

function collectFeatureCandidates(root) {
  const readmePaths = ['README.md', 'FEATURES.md', 'docs/README.md', 'docs/features.md', 'docs/FEATURES.md'];
  // Each source gets its own budget so README sub-features don't starve route/model/EE candidates.
  // README product blocks are the strongest signal (declared-implemented), so they go first.
  const readme = uniqueCandidates(collectReadmeProductCandidates(root, readmePaths), 16);
  const rails = uniqueCandidates(collectRailsNamespaceCandidates(root), 10);
  const models = uniqueCandidates(collectModelPrefixCandidates(root), 8);
  const enterprise = uniqueCandidates(collectEnterpriseFeatureCandidates(root), 8);
  // Legacy bullet-list candidates as the weakest signal — keep last, small budget.
  const legacy = uniqueCandidates(collectMarkdownCandidates(root, readmePaths, 'existing'), 8);
  return uniqueCandidates([...readme, ...rails, ...models, ...enterprise, ...legacy], 40);
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

        // Emoji-led H2/H3 heading => product block
        if (level <= 3 && PRODUCT_EMOJI.test(raw)) {
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

function collectSourceTodoCandidates(root, sourceRoots) {
  const candidates = [];
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    const isTestFile = isTestSourceFile(file);
    const text = readFile(path.join(root, file));
    const lines = text.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      // Only accept labeled TODO/FIXME/XXX/HACK markers: must be followed by
      // either `(...)` (owner/tag) or `:` (explicit label). This excludes
      // inline "TODO turn this into..." free-form comments that are usually
      // implementation notes, not roadmap items.
      const match = line.match(/\b(?:TODO|FIXME|XXX|HACK)\b\s*(?:\([^)]*\)\s*)?[:\-]\s*(.+)$/i);
      if (!match) continue;
      const name = cleanMarkdownText(match[1]);
      if (!isUsefulCandidateName(name)) continue;
      // Skip vague implementation notes that aren't product-level features
      if (/\b(?:turn this into|consider|maybe|perhaps|refactor this|fix this later|cleanup needed)\b/i.test(name)) continue;
      if (isTestFile) {
        candidates.push({
          id: slugifyCandidate(name),
          name,
          type: 'test improvement',
          status: '待实现',
          evidence: `${file}:${index + 1}`,
          boundary: 'Test improvement TODO; not a product roadmap item. Verify scope before implementation.',
        });
      } else {
        candidates.push({
          id: slugifyCandidate(name),
          name,
          type: 'source TODO',
          status: '待实现',
          evidence: `${file}:${index + 1}`,
          boundary: 'Source code TODO; verify intent, owner, and priority before implementation.',
        });
      }
      if (candidates.length >= 48) return candidates;
    }
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
module.exports = { collectProjectInfo, collectFeatureCandidates, renderFeatureOverviewLines, splitEvidenceItems, collectEntrypointFeatureCandidates, collectPlannedFeatureCandidates, collectMarkdownCandidates, headingMatchesCandidateMode, cleanMarkdownText, isUsefulCandidateName, humanizeRouteFeatureName, isDynamicRouteSegment, cleanRouteSegment, featureKey, matchingFeatureKeyForCommand, uniqueCandidates, collectSourceTodoCandidates, renderCandidateEvidenceLines };
