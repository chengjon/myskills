#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function checkPlugin(entry, configDir) {
  const issues = [];

  // Integrity: installPath exists
  if (entry.installPath && entry.installPath !== '(binary)') {
    if (!fs.existsSync(entry.installPath)) {
      issues.push({
        severity: 'error',
        category: 'integrity',
        message: `Install path does not exist: ${entry.installPath}`,
        fixable: false,
        fixAction: null,
      });
    } else {
      // Integrity: version file present
      const hasPkg = fs.existsSync(path.join(entry.installPath, 'package.json'));
      const hasVersion = fs.existsSync(path.join(entry.installPath, 'VERSION'));
      const hasSkillMd = entry.type === 'skill' && fs.existsSync(path.join(entry.installPath, 'SKILL.md'));
      if (!hasPkg && !hasVersion && !hasSkillMd) {
        issues.push({
          severity: 'error',
          category: 'integrity',
          message: `No package.json, VERSION, or SKILL.md in ${path.basename(entry.installPath)}`,
          fixable: false,
          fixAction: null,
        });
      }
    }
  }

  // Config: skill frontmatter required fields
  if (entry.type === 'skill' && entry.installPath) {
    const skillMd = path.join(entry.installPath, 'SKILL.md');
    if (fs.existsSync(skillMd)) {
      try {
        const content = fs.readFileSync(skillMd, 'utf8');
        const fm = content.match(/^---\n([\s\S]*?)\n---/);
        if (fm) {
          const missing = [];
          if (!/^name:/m.test(fm[1])) missing.push('name');
          if (!/^description:/m.test(fm[1])) missing.push('description');
          if (missing.length > 0) {
            issues.push({
              severity: 'warn',
              category: 'config',
              message: `SKILL.md frontmatter missing: ${missing.join(', ')}`,
              fixable: false,
              fixAction: null,
            });
          }
        }
      } catch { /* ignore */ }
    }
  }

  // Cache: multiple version dirs for same plugin
  if (entry.type === 'plugin' && entry.marketplace && entry.installPath && entry.installPath !== '(binary)') {
    const cacheBase = path.dirname(entry.installPath);
    try {
      const dirs = fs.readdirSync(cacheBase, { withFileTypes: true })
        .filter(d => d.isDirectory())
        .map(d => d.name);
      if (dirs.length > 1) {
        issues.push({
          severity: 'warn',
          category: 'cache',
          message: `${dirs.length} version dirs in ${path.basename(cacheBase)}: ${dirs.join(', ')}`,
          fixable: true,
          fixAction: 'clear-old-cache',
        });
      }
    } catch { /* ignore */ }
  }

  // Cache: install-counts-cache.json staleness (once per runtime, attach to first plugin)
  if (configDir && entry.type === 'plugin') {
    const icPath = path.join(configDir, 'plugins', 'install-counts-cache.json');
    if (fs.existsSync(icPath)) {
      try {
        const ageDays = (Date.now() - fs.statSync(icPath).mtimeMs) / (1000 * 60 * 60 * 24);
        if (ageDays > 30) {
          issues.push({
            severity: 'info',
            category: 'cache',
            message: `install-counts-cache.json ${Math.round(ageDays)}d old`,
            fixable: true,
            fixAction: 'refresh-install-counts',
          });
        }
      } catch { /* ignore */ }
    }
  }

  let health = 'healthy';
  if (issues.some(i => i.severity === 'error')) health = 'error';
  else if (issues.some(i => i.severity === 'warn' || i.severity === 'info')) health = 'warn';

  return { ...entry, health, issues };
}

function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { input += chunk; });
  process.stdin.on('end', () => {
    let data;
    try { data = JSON.parse(input); }
    catch (e) {
      process.stderr.write('Error: Invalid JSON input\n');
      process.exit(1);
    }

    for (const runtime of data.runtimes) {
      runtime.plugins = runtime.plugins.map(entry => checkPlugin(entry, runtime.configDir));
    }

    process.stdout.write(JSON.stringify(data, null, 2) + '\n');
  });
}

main();
