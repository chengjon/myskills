'use strict';

const fs = require('fs');
const path = require('path');

const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const DEFAULT_CONFIG = {
  drift_check_mode: 'hard',
  hooks_mode: 'on',
  mainline_warning: true,
  auto_accept_suggest: true,
};

const VALID_DRIFT_MODES = new Set(['hard', 'soft', 'off']);

const VALID_HOOK_MODES = new Set(['on', 'off']);

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
module.exports = { DEFAULT_CONFIG, VALID_DRIFT_MODES, VALID_HOOK_MODES, governanceConfigPath, loadConfig, saveConfig };
