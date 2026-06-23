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
  ], 16);

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
  return uniqueCandidates([
    ...collectMarkdownCandidates(root, ['README.md', 'FEATURES.md', 'docs/README.md', 'docs/features.md', 'docs/FEATURES.md'], 'existing'),
  ], 16);
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
      // Only match TODOs in comment context to avoid string literal false positives
      const isCommentContext = /^\s*(#|\/\/|\/\*|<!--|;\s*|%\s*)/.test(line) ||
        /(?:#\s*|\/\/\s*|\/\*\s*|<!--\s*|;\s*|%\s*)(?:TODO|FIXME|XXX|HACK)\b/i.test(line);
      if (!isCommentContext) continue;
      const match = line.match(/\b(?:TODO|FIXME|XXX|HACK)\b[:\-\s]*(.+)$/i);
      if (!match) continue;
      const name = cleanMarkdownText(match[1]);
      if (!isUsefulCandidateName(name)) continue;
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
