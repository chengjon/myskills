'use strict';

const fs = require('fs');
const path = require('path');

const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const DEFAULT_CONFIG = {
  drift_check_mode: 'hard',
  hooks_mode: 'on',
  mainline_warning: true,
  auto_accept_suggest: true,
  project_profile: 'auto',
};

const VALID_DRIFT_MODES = new Set(['hard', 'soft', 'off']);

const VALID_HOOK_MODES = new Set(['on', 'off']);

// FT_REVIEW MED: project_profile enum + storage contract.
//
// Storage: .governance/config.json (same file as other config keys).
// Default: 'auto' — detected per-repo via detectProjectProfile() at read time.
//         Explicit value (one of the enum below) overrides detection.
// Persistence: `ft config set --key project_profile --value <enum>` writes
//         the explicit value; `--value auto` restores dynamic detection.
//
// Profiles with defined high-weight signals:
//   library, web-app, service-api, cli-tool, monorepo (covered by detection).
// Profiles recognized but with weaker signals (printed as suggestions, low
// confidence detection): mobile-app, data-pipeline, ml-project,
// documentation-site, infra-repo, desktop-app.
const VALID_PROFILES = new Set([
  'auto', 'library', 'web-app', 'service-api', 'cli-tool', 'monorepo',
  'mobile-app', 'data-pipeline', 'ml-project', 'documentation-site',
  'infra-repo', 'desktop-app',
]);

function governanceConfigPath(root) {
  return path.join(root, '.governance', 'config.json');
}

function loadConfig(root) {
  const merged = Object.assign({}, DEFAULT_CONFIG);
  const raw = readJsonSafe(governanceConfigPath(root));
  if (raw && typeof raw === 'object') {
    for (const k of Object.keys(DEFAULT_CONFIG)) {
      if (k in raw && raw[k] != null) merged[k] = raw[k];
    }
  }
  if (process.env.FT_DRIFT_CHECK_MODE && VALID_DRIFT_MODES.has(process.env.FT_DRIFT_CHECK_MODE)) {
    merged.drift_check_mode = process.env.FT_DRIFT_CHECK_MODE;
  }
  if (process.env.FT_HOOKS_MODE && VALID_HOOK_MODES.has(process.env.FT_HOOKS_MODE)) {
    merged.hooks_mode = process.env.FT_HOOKS_MODE;
  }
  if (process.env.FT_MAINLINE_WARNING != null) {
    merged.mainline_warning = process.env.FT_MAINLINE_WARNING === '1' || process.env.FT_MAINLINE_WARNING === 'true';
  }
  if (process.env.FT_AUTO_ACCEPT_SUGGEST != null) {
    merged.auto_accept_suggest = process.env.FT_AUTO_ACCEPT_SUGGEST === '1' || process.env.FT_AUTO_ACCEPT_SUGGEST === 'true';
  }
  if (process.env.FT_PROJECT_PROFILE && VALID_PROFILES.has(process.env.FT_PROJECT_PROFILE)) {
    merged.project_profile = process.env.FT_PROJECT_PROFILE;
  }
  return merged;
}

function saveConfig(root, config) {
  const payload = {
    version: 1,
    generated_at: new Date().toISOString(),
    ...config,
  };
  writeJson(governanceConfigPath(root), payload);
}

// detectProjectProfile(root): returns one of VALID_PROFILES.
//
// Detection weights (additive, first match wins on ties in declared order):
//   - package.json with `bin` or `[project.scripts]` and no web framework → cli-tool
//   - package.json with dependency on react/vue/next/svelte → web-app
//   - pyproject.toml/setup.py with [project.scripts] and no web dep → cli-tool or library
//   - fastapi/flask/django dependency → service-api
//   - Cargo.toml with [[bin]] only → cli-tool
//   - Cargo.toml with [lib] only → library
//   - workspaces field in package.json OR member dirs in Cargo.toml → monorepo
//   - README mentions Android/iOS / has *.kt/*.swift majority → mobile-app
//   - README mentions kubernetes/terraform → infra-repo
//   - Jupyter/requirements has pandas/tensorflow/torch → ml-project
//   - airflow/prefect/dagster → data-pipeline
//   - Only *.md and no source files → documentation-site
//   - Fallback → library
function detectProjectProfile(root) {
  const score = {};
  const bump = (k, n = 1) => { score[k] = (score[k] || 0) + n; };

  try {
    const pkg = readJson(path.join(root, 'package.json'));
    if (pkg) {
      const deps = Object.assign({}, pkg.dependencies || {}, pkg.devDependencies || {});
      if (deps.react || deps.vue || deps.next || deps.svelte || deps.nuxt || deps['@angular/core']) bump('web-app', 3);
      if (deps.fastapi || deps.flask || deps.django || deps.express && !deps.react) bump('service-api', 2);
      if (pkg.bin) bump('cli-tool', 2);
      if (pkg.workspaces && pkg.workspaces.length) bump('monorepo', 3);
    }
  } catch (_) { /* not a JS project */ }

  try {
    const fsSync = require('fs');
    const cargoPath = path.join(root, 'Cargo.toml');
    if (fsSync.existsSync(cargoPath)) {
      const cargo = readFile(cargoPath);
      if (/\[\[bin\]\]/.test(cargo) && !/\[lib\]/.test(cargo)) bump('cli-tool', 2);
      if (/\[lib\]/.test(cargo) && !/\[\[bin\]\]/.test(cargo)) bump('library', 2);
      if (/members\s*=/.test(cargo) || /\[workspace\]/.test(cargo)) bump('monorepo', 3);
    }
  } catch (_) { /* not a Rust project */ }

  try {
    const fsSync = require('fs');
    for (const p of ['pyproject.toml', 'setup.py']) {
      const full = path.join(root, p);
      if (fsSync.existsSync(full)) {
        const text = readFile(full);
        if (/\[project\.scripts\]/.test(text)) bump('cli-tool', 2);
        if (/fastapi|flask|django|starlette|litestar/i.test(text)) bump('service-api', 2);
        bump('library', 1);
        break;
      }
    }
  } catch (_) { /* not a Python project */ }

  // Documentation-site: only *.md and no source.
  try {
    const fsSync = require('fs');
    const entries = fsSync.readdirSync(root, { withFileTypes: true })
      .filter((e) => e.isFile())
      .map((e) => e.name);
    const hasMd = entries.some((n) => /\.md$/i.test(n));
    const hasSource = entries.some((n) => /\.(py|js|ts|rs|go|rb|java|c|cpp|kt|swift)$/i.test(n));
    if (hasMd && !hasSource && !score['web-app']) bump('documentation-site', 2);
  } catch (_) { /* empty dir */ }

  // Pick highest score, fallback to library.
  let best = 'library';
  let bestScore = -1;
  for (const k of Object.keys(score)) {
    if (score[k] > bestScore) {
      bestScore = score[k];
      best = k;
    }
  }
  return best;
}

// resolveProjectProfile(root, config): returns the effective profile.
// When config.project_profile === 'auto', runs detection. Otherwise returns
// the explicit value (already validated against VALID_PROFILES).
function resolveProjectProfile(root, config) {
  const declared = (config && config.project_profile) || 'auto';
  if (declared === 'auto') return detectProjectProfile(root);
  return declared;
}

module.exports = {
  DEFAULT_CONFIG,
  VALID_DRIFT_MODES,
  VALID_HOOK_MODES,
  VALID_PROFILES,
  governanceConfigPath,
  loadConfig,
  saveConfig,
  detectProjectProfile,
  resolveProjectProfile,
};

