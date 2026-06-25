'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
function collectUiEntries(root, sourceRoots) {
  return uniqueUiEntries([
    ...collectFileBasedUiEntries(root),
    ...collectNavigationUiEntries(root, sourceRoots),
    ...collectSourceUiRouteEntries(root, sourceRoots),
  ], 32);
}

function collectFileBasedUiEntries(root) {
  const entries = [];
  // Next.js App Router: scan both top-level `app/` and nested layouts like
  // `<sub>/src/app/` or `<sub>/app/` (monorepo / non-standard roots).
  const appDirs = ['app'];
  for (const sub of detectSubdirs(root)) {
    if (fs.existsSync(path.join(root, sub, 'src', 'app'))) appDirs.push(`${sub}/src/app`);
    if (fs.existsSync(path.join(root, sub, 'app'))) appDirs.push(`${sub}/app`);
  }
  for (const appDir of appDirs) {
    for (const file of collectFilesUnder(root, appDir, 200, (name) => /^page\.(js|jsx|ts|tsx|mdx)$/i.test(name))) {
      const route = nextAppRouteFromFileRelative(file, appDir);
      if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'Next app router'));
    }
  }
  // Next.js Pages Router: top-level `pages/` and nested `<sub>/pages/`.
  const pagesDirs = ['pages'];
  for (const sub of detectSubdirs(root)) {
    if (fs.existsSync(path.join(root, sub, 'pages'))) pagesDirs.push(`${sub}/pages`);
    if (fs.existsSync(path.join(root, sub, 'src', 'pages'))) pagesDirs.push(`${sub}/src/pages`);
  }
  for (const pagesDir of pagesDirs) {
    for (const file of collectFilesUnder(root, pagesDir, 200, (name) => /\.(js|jsx|ts|tsx|mdx)$/i.test(name))) {
      const route = nextPagesRouteFromFileRelative(file, pagesDir);
      if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'Next pages router'));
    }
  }
  // SvelteKit: top-level `src/routes` and nested.
  const svelteDirs = ['src/routes'];
  for (const sub of detectSubdirs(root)) {
    if (fs.existsSync(path.join(root, sub, 'src', 'routes'))) svelteDirs.push(`${sub}/src/routes`);
  }
  for (const svelteDir of svelteDirs) {
    for (const file of collectFilesUnder(root, svelteDir, 200, (name) => /^\+page\.(svelte|js|ts)$/i.test(name))) {
      const route = svelteKitRouteFromFileRelative(file, svelteDir);
      if (isUsefulUiRoute(route)) entries.push(uiEntry(route, file, 'SvelteKit route'));
    }
  }
  return entries;
}

function detectSubdirs(root) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'dist', 'build', '.next', '.venv', '__pycache__', '.omc', 'target', 'coverage']);
  const out = [];
  try {
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      out.push(entry.name);
    }
  } catch (_) { /* ignore */ }
  return out;
}

function nextAppRouteFromFileRelative(relativePath, baseDir) {
  const prefix = baseDir.endsWith('/') ? baseDir : baseDir + '/';
  if (!relativePath.startsWith(prefix)) return '';
  const rest = relativePath.slice(prefix.length);
  const parts = rest.split('/');
  const fileName = parts.pop();
  if (!fileName || !/^page\./i.test(fileName)) return '';
  const routeParts = parts.filter((part) => !isPathlessUiSegment(part));
  return normalizeUiRoute(routeParts.length ? routeParts.join('/') : '/');
}

function nextPagesRouteFromFileRelative(relativePath, baseDir) {
  const prefix = baseDir.endsWith('/') ? baseDir : baseDir + '/';
  if (!relativePath.startsWith(prefix)) return '';
  const parts = relativePath.slice(prefix.length).split('/');
  if (!parts.length || /^api$/i.test(parts[0])) return '';
  const fileName = parts.pop() || '';
  const pageName = fileName.replace(/\.(js|jsx|ts|tsx|mdx)$/i, '');
  if (!pageName || pageName.startsWith('_')) return '';
  if (pageName !== 'index') parts.push(pageName);
  if (parts.some((part) => part.startsWith('_'))) return '';
  return normalizeUiRoute(parts.length ? parts.join('/') : '/');
}

function svelteKitRouteFromFileRelative(relativePath, baseDir) {
  const prefix = baseDir.endsWith('/') ? baseDir : baseDir + '/';
  if (!relativePath.startsWith(prefix)) return '';
  const parts = relativePath.slice(prefix.length).split('/');
  const fileName = parts.pop();
  if (!fileName || !/^\+page\./i.test(fileName)) return '';
  const routeParts = parts.filter((part) => !isPathlessUiSegment(part));
  return normalizeUiRoute(routeParts.length ? routeParts.join('/') : '/');
}

function collectFilesUnder(root, relativeDir, limit, acceptFileName) {
  const ignored = new Set(['.git', '.governance', 'node_modules', 'target', 'dist', 'build', 'coverage', '__pycache__']);
  const files = [];

  function walk(currentDir) {
    if (files.length >= limit) return;
    const absoluteDir = path.join(root, currentDir);
    if (!fs.existsSync(absoluteDir) || !fs.statSync(absoluteDir).isDirectory()) return;
    for (const entry of fs.readdirSync(absoluteDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (files.length >= limit) return;
      if (entry.name.startsWith('.') || ignored.has(entry.name)) continue;
      const relativePath = `${currentDir}/${entry.name}`;
      if (entry.isDirectory()) {
        walk(relativePath);
      } else if (acceptFileName(entry.name)) {
        files.push(relativePath);
      }
    }
  }

  walk(relativeDir);
  return files;
}

function isPathlessUiSegment(part) {
  return /^\(.+\)$/.test(String(part || ''));
}

function collectNavigationUiEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 600)) {
    if (!isNavigationUiFile(file)) continue;
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const route of sourceNavigationRouteMatches(lines[index])) {
        entries.push(uiEntry(route, `${file}:${index + 1}`, 'navigation/menu'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

function isNavigationUiFile(file) {
  return /(^|[._/-])(nav|navigation|menu|sidebar|sidenav|side-nav|routes?|links?|tabs?)([._/-]|$)/i.test(String(file || ''));
}

function sourceNavigationRouteMatches(line) {
  const matches = [];
  const patterns = [
    /\b(?:href|to|url)\s*:\s*["']([^"']+)["']/g,
    /<(?:Link|NavLink|a)\b[^>]*\b(?:href|to)\s*=\s*["']([^"']+)["']/g,
    /\brouterLink\s*=\s*["']([^"']+)["']/g,
  ];
  for (const pattern of patterns) {
    for (const match of line.matchAll(pattern)) {
      if (isUsefulUiRoute(match[1])) matches.push(match[1]);
    }
  }
  return matches;
}

function collectSourceUiRouteEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 400)) {
    // Skip test/spec files: their route-looking literals are fixtures, not
    // application UI routes. (e.g. test/sentinels.test.ts has `config: { path:
    // "/hooks/deploy" }` and `toolArgs: { path: "src/index.ts" }` as test data.)
    if (isTestSourceFile(file)) continue;
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const route of sourceUiRouteMatches(lines[index])) {
        entries.push(uiEntry(route, `${file}:${index + 1}`, 'source router'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

function sourceUiRouteMatches(line) {
  const matches = [];
  // JSX router: <Route path="/foo" ...>
  for (const match of line.matchAll(/<Route\b[^>]*\bpath\s*=\s*["']([^"']+)["']/g)) {
    if (isUsefulUiRoute(match[1])) matches.push(match[1]);
  }
  // Object-literal router entry. The previous bare `path:` pattern matched any
  // object property named `path` — state mutations (`{ path: "updatedAt" }`),
  // tool args (`toolArgs: { path: "src/index.ts" }`), webhook configs
  // (`config: { path: "/hooks/deploy" }`) all slipped through and polluted the
  // UI route table. Now we require:
  //   1. the captured value starts with `/` (rejects `updatedAt`, `src/index.ts`)
  //   2. a router-framework sibling key on the same line — element/component/
  //      handler/page/screen/render — which real route tables always carry and
  //      the false-positive sources never do.
  const routerMarker = /\b(?:element|component|handler|page|screen|render)\s*:/;
  for (const match of line.matchAll(/\bpath\s*:\s*["'](\/[^"']+)["']/g)) {
    if (routerMarker.test(line) && isUsefulUiRoute(match[1])) {
      matches.push(match[1]);
    }
  }
  return matches;
}

function uiEntry(route, evidence, source) {
  return {
    route: normalizeUiRoute(route),
    evidence,
    source,
  };
}

function normalizeUiRoute(value) {
  let route = String(value || '').trim();
  if (!route) return '';
  if (!route.startsWith('/')) route = `/${route}`;
  route = route.replace(/\/+/g, '/');
  if (route.length > 1) route = route.replace(/\/$/, '');
  return route || '/';
}

function isUsefulUiRoute(value) {
  const route = normalizeUiRoute(value);
  if (!route.startsWith('/') || route.length === 0) return false;
  if (/^\/api(?:\/|$)/i.test(route)) return false;
  if (route.includes('*') || route.includes('${')) return false;
  // Reject code-file extensions — `/src/index.ts` etc. are file paths that
  // leaked through `path:` matching, not real routes.
  if (/\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|swift|rb|php|cs|c|cc|cpp|h|hpp)$/i.test(route)) return false;
  // Reject single-character routes — almost always test fixtures like `/a`.
  // (Root route `/` still passes: it has zero chars after the slash.)
  if (/^\/.$/.test(route)) return false;
  return true;
}

function uniqueUiEntries(entries, limit) {
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    if (!entry.route || !isUsefulUiRoute(entry.route)) continue;
    const key = normalizeUiRoute(entry.route);
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push({ ...entry, route: key });
    if (unique.length >= limit) break;
  }
  return unique;
}

function collectApiEntries(root, sourceRoots) {
  return uniqueApiEntries([
    ...collectOpenApiEntries(root),
    ...collectSourceRouteEntries(root, sourceRoots),
  ], 32);
}

function collectOpenApiEntries(root) {
  const entries = [];
  const specs = existingPaths(root, [
    'openapi.json',
    'openapi.yaml',
    'openapi.yml',
    'docs/openapi.json',
    'docs/openapi.yaml',
    'docs/openapi.yml',
    'docs/api/openapi.json',
    'docs/api/openapi.yaml',
    'docs/api/openapi.yml',
  ]);

  for (const spec of specs) {
    const absolutePath = path.join(root, spec);
    if (/\.json$/i.test(spec)) {
      try {
        const parsed = JSON.parse(readFile(absolutePath));
        const paths = parsed && parsed.paths && typeof parsed.paths === 'object' ? parsed.paths : {};
        for (const routePath of Object.keys(paths).sort()) {
          const methods = paths[routePath] && typeof paths[routePath] === 'object' ? paths[routePath] : {};
          for (const method of Object.keys(methods).sort()) {
            if (isHttpMethod(method)) entries.push(apiEntry(method, routePath, spec, 'OpenAPI'));
          }
        }
      } catch (_) {
        // Invalid JSON should not block FUNCTION_TREE generation.
      }
      continue;
    }

    let currentPath = '';
    for (const line of readFile(absolutePath).split(/\r?\n/)) {
      const pathMatch = line.match(/^\s{1,8}["']?(\/[^"':]+)["']?\s*:\s*(?:#.*)?$/);
      if (pathMatch) {
        currentPath = pathMatch[1];
        continue;
      }
      const methodMatch = line.match(/^\s{2,10}(get|post|put|patch|delete|options|head)\s*:\s*(?:#.*)?$/i);
      if (currentPath && methodMatch) entries.push(apiEntry(methodMatch[1], currentPath, spec, 'OpenAPI'));
    }
  }
  return entries;
}

function collectSourceRouteEntries(root, sourceRoots) {
  const entries = [];
  for (const file of collectSourceFiles(root, sourceRoots, 400)) {
    const lines = readFile(path.join(root, file)).split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      for (const match of sourceRouteMatches(lines[index], file)) {
        entries.push(apiEntry(match.method, match.path, `${file}:${index + 1}`, match.framework || 'source route'));
        if (entries.length >= 64) return entries;
      }
    }
  }
  return entries;
}

// Web framework detector registry. Each entry is a self-contained detector that
// knows its own routing syntax, scope constraints (e.g. Django only in urls.py),
// and method-resolution rules. New frameworks plug in here without touching the
// main loop. (FT_SKILL_AUDIT Fix-1: replaces hardcoded Express/Fastify regex.)
const WEB_FRAMEWORK_DETECTORS = [
  {
    name: 'fastapi',
    routePatterns: [
      /@\s*(?:app|router|api_router|api)\s*\.\s*(get|post|put|patch|delete|options|head)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
    ],
  },
  {
    name: 'flask',
    routePatterns: [
      /@\s*(?:app|bp|router|blueprint|api)\s*\.\s*route\s*\(\s*['"`]([^'"`]+)['"`]\s*(?:,\s*methods\s*=\s*\[([^\]]+)\])?/ig,
    ],
    defaultMethod: 'GET',
    parseMethods: (methodsArg) => methodsArg ? methodsArg.match(/['"`](\w+)['"`]/g)?.map((s) => s.replace(/['"`]/g, '').toUpperCase()) : null,
  },
  {
    name: 'django',
    routePatterns: [
      /\b(?:path|re_path|url|register)\s*\(\s*[r]?['"`]([^'"`]+)['"`]/ig,
    ],
    defaultMethod: 'GET',
    scopeFile: /(?:^|[\\/])urls\.py$/,
  },
  {
    name: 'express-fastify-koa',
    routePatterns: [
      /\b(?:app|router|server|fastify)\s*\.\s*(get|post|put|patch|delete|options|head)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
    ],
  },
  {
    name: 'nestjs',
    routePatterns: [
      /@(?:Get|Post|Put|Patch|Delete|Head|Options|All)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
    ],
    defaultMethod: null, // method derived from decorator name via capture group below
    methodFromDecorator: true,
  },
  {
    name: 'spring',
    routePatterns: [
      /@(?:Request(?:Get|Post|Put|Patch|Delete|Head|Options)?Mapping|RequestMapping)\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?["']([^"']+)['"]/ig,
    ],
    defaultMethod: 'GET',
    methodFromDecorator: true, // @GetMapping → GET, @PostMapping → POST
  },
  {
    name: 'gin-echo-chi',
    routePatterns: [
      /\b(?:r|router|e|echo|mux)\s*\.\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*['"`]([^'"`]+)['"`]/ig,
    ],
  },
  {
    name: 'axum-actix',
    routePatterns: [
      /\.route\s*\(\s*['"`]([^'"`]+)['"`]\s*,\s*(get|post|put|patch|delete|options|head)\s*\(/ig,
    ],
    methodInGroup: 2,
    pathGroup: 1,
  },
  {
    name: 'rails',
    routePatterns: [
      /\b(?:get|post|put|patch|delete)\s+['"]([^'"]+)['"]\s*(?:=>|,\s*to:)/ig,
      /\bmatch\s+['"]([^'"]+)['"]\s*,\s*(?:via:\s*\[([^\]]+)\]|to:)/ig,
    ],
    defaultMethod: 'GET',
  },
];

function sourceRouteMatches(line, filePath) {
  const matches = [];
  for (const fw of WEB_FRAMEWORK_DETECTORS) {
    if (fw.scopeFile && filePath && !fw.scopeFile.test(filePath)) continue;
    for (const pattern of fw.routePatterns) {
      pattern.lastIndex = 0;
      for (const m of line.matchAll(pattern)) {
        const pathGroup = fw.pathGroup || (fw.methodFromDecorator ? 1 : 2);
        const path = m[pathGroup];
        if (!path || !isUsefulApiPath(path)) continue;

        let method = fw.defaultMethod || 'GET';
        if (fw.parseMethods && m[2]) {
          const parsed = fw.parseMethods(m[2]);
          if (parsed && parsed.length > 0) method = parsed[0];
        } else if (fw.methodFromDecorator) {
          // Derive method from decorator name: @GetMapping → GET, @PostMapping → POST
          const decoratorMatch = m[0].match(/@(Get|Post|Put|Patch|Delete|Head|Options|All|Request(?:Get|Post|Put|Patch|Delete|Head|Options)?Mapping)/i);
          if (decoratorMatch) {
            const dn = decoratorMatch[1].toLowerCase();
            const methodMatch = dn.match(/(get|post|put|patch|delete|head|options)/);
            if (methodMatch) method = methodMatch[1].toUpperCase();
          }
        } else if (fw.methodInGroup) {
          method = m[fw.methodInGroup].toUpperCase();
        } else if (m[1] && isHttpMethod(m[1])) {
          method = m[1].toUpperCase();
        }
        matches.push({ method, path, framework: fw.name });
      }
    }
  }
  return matches;
}

function apiEntry(method, routePath, evidence, source) {
  return {
    method: String(method || '').toUpperCase(),
    path: String(routePath || '').trim(),
    evidence,
    source,
  };
}

function isHttpMethod(value) {
  return /^(get|post|put|patch|delete|options|head)$/i.test(String(value || ''));
}

function isUsefulApiPath(value) {
  const routePath = String(value || '').trim();
  return routePath.startsWith('/') && routePath.length > 1 && !routePath.includes('${');
}

function uniqueApiEntries(entries, limit) {
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    if (!entry.method || !isUsefulApiPath(entry.path)) continue;
    const key = `${entry.method} ${entry.path}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(entry);
    if (unique.length >= limit) break;
  }
  return unique;
}
module.exports = { collectUiEntries, collectFileBasedUiEntries, detectSubdirs, nextAppRouteFromFileRelative, nextPagesRouteFromFileRelative, svelteKitRouteFromFileRelative, collectFilesUnder, isPathlessUiSegment, collectNavigationUiEntries, isNavigationUiFile, sourceNavigationRouteMatches, collectSourceUiRouteEntries, sourceUiRouteMatches, uiEntry, normalizeUiRoute, isUsefulUiRoute, uniqueUiEntries, collectApiEntries, collectOpenApiEntries, collectSourceRouteEntries, sourceRouteMatches, apiEntry, isHttpMethod, isUsefulApiPath, uniqueApiEntries };
