'use strict';

const fs = require('fs');
const path = require('path');

const { DEFAULT_CONFIG, VALID_DRIFT_MODES, VALID_HOOK_MODES, governanceConfigPath, loadConfig, saveConfig } = require('./config.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { buildFileToTrackIndex, driftAcceptancesPath, loadDriftAcceptances, saveDriftAcceptances, currentActiveMainlineId, isAcceptanceEffective, newAcceptanceId } = require('./mainline.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function cmdSessionStart(root) {
  const config = loadConfig(root);
  const lines = [];
  lines.push('[function-tree session-start]');

  const programsDir = path.join(root, '.governance', 'programs');
  if (!fs.existsSync(programsDir)) {
    lines.push('no governance programs initialized; run `ft init <program> --ref <node>` to start');
    console.log(lines.join('\n'));
    return;
  }

  const { resolved } = loadAllNodesResolved(root);
  const mainline = resolved.find((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  const mainlineId = mainline ? String(mainline.node.id) : null;

  lines.push('');
  if (mainline) {
    lines.push(`active mainline: ${mainline.program}/${mainline.node.id} — ${mainline.node.title || '(untitled)'}`);
    const children = resolved.filter((e) => e.track === 'mainline' && (e.depth === 1 || e.depth === 2) && isActiveStatus(e.node.status));
    lines.push(`  active mainline descendants: ${children.length}`);
  } else {
    lines.push('active mainline: (none — switch lock inactive, backlog can be authorized)');
  }

  // Drift scan via `git status --porcelain` (fast path).
  const files = listWorktreeFiles(root);
  let ml = 0, bl = 0, op = 0, ac = 0, ut = 0;
  const untrackedFiles = [];
  if (files.length) {
    buildFileToTrackIndex(root);
    const index = readJsonSafe(path.join(root, '.governance', 'file-to-track.json')) || { files: {} };
    const acceptancesData = loadDriftAcceptances(root);
    const nowMs = Date.now();
    const findAcc = (rel) => {
      for (const a of acceptancesData.acceptances) {
        if (!isAcceptanceEffective(a, mainlineId, nowMs)) continue;
        if (Array.isArray(a.files) && a.files.includes(rel)) return a;
      }
      return null;
    };
    for (const f of files) {
      const rel = relPath(root, f);
      const entry = index.files[rel];
      const track = entry?.track || 'untracked';
      if (track === 'mainline') ml++;
      else if (track === 'backlog') bl++;
      else if (track === 'optimize') op++;
      else if (track === 'untracked') {
        if (findAcc(rel)) ac++;
        else { ut++; untrackedFiles.push(rel); }
      }
    }
  }

  lines.push('');
  lines.push(`worktree drift (git status, ${files.length} changed): mainline=${ml} backlog=${bl} optimize=${op} accepted-drift=${ac} untracked=${ut}`);
  if (untrackedFiles.length) {
    const preview = untrackedFiles.slice(0, 5).map((f) => `  - ${f}`).join('\n');
    const more = untrackedFiles.length > 5 ? `\n  - ... and ${untrackedFiles.length - 5} more` : '';
    lines.push(`untracked preview:`);
    lines.push(preview + more);
  }

  // Active acceptances summary (status='active', not bound to current mainline necessarily).
  const acceptancesData = loadDriftAcceptances(root);
  const activeAcc = acceptancesData.acceptances.filter((a) => a && a.status === 'active');
  lines.push('');
  if (activeAcc.length) {
    let nearest = null;
    for (const a of activeAcc) {
      if (a.expires_at == null) continue;
      const exp = Date.parse(a.expires_at);
      if (!Number.isNaN(exp) && (nearest == null || exp < nearest)) nearest = exp;
    }
    const nearestTxt = nearest == null
      ? '(all permanent or malformed)'
      : new Date(nearest).toISOString();
    lines.push(`active acceptances: ${activeAcc.length} (nearest expiry: ${nearestTxt})`);
  } else {
    lines.push('active acceptances: 0');
  }

  // Next-gate suggestion based on state.
  lines.push('');
  if (config.hooks_mode === 'off') {
    lines.push('hooks_mode=off — SessionStart/pre-edit/pre-commit hooks inactive');
  }
  if (ut > 0) {
    if (config.drift_check_mode === 'hard') {
      lines.push(`NEXT: ${ut} file(s) UNTRACKED will block commit (hard mode); run \`ft accept-drift --reason <text> --files <list>\` or add to a backlog node`);
    } else if (config.drift_check_mode === 'soft') {
      lines.push(`NEXT: ${ut} file(s) UNTRACKED (soft mode — commit allowed but review recommended); run \`ft accept-drift\` or \`ft authorize\``);
    } else {
      lines.push(`NEXT: drift_check_mode=off; UNTRACKED files present but enforcement disabled`);
    }
  } else if (ml === 0 && files.length === 0) {
    lines.push('NEXT: clean tree on the active mainline; consider `ft gate` for the next gate or `ft status` for program overview');
  } else {
    lines.push('NEXT: no UNTRACKED drift; continue mainline work or run `ft gate` for next gate');
  }

  console.log(lines.join('\n'));
}

function cmdPreEdit(root, flags) {
  const filesFlag = one(flags, 'files');
  if (!filesFlag) {
    console.log(JSON.stringify({ decision: 'approve', reason: 'pre-edit: no --files provided, skipping' }));
    return;
  }
  const files = filesFlag.split(',').map((s) => s.trim()).filter(Boolean);
  const config = loadConfig(root);
  if (config.hooks_mode === 'off') {
    console.log(JSON.stringify({ decision: 'approve', reason: 'hooks_mode=off' }));
    return;
  }

  // If no governance programs, nothing to check against.
  if (!fs.existsSync(path.join(root, '.governance', 'programs'))) {
    console.log(JSON.stringify({ decision: 'approve', reason: 'no governance programs initialized' }));
    return;
  }

  buildFileToTrackIndex(root);
  const index = readJsonSafe(path.join(root, '.governance', 'file-to-track.json')) || { files: {} };
  const { resolved } = loadAllNodesResolved(root);
  const mainline = resolved.find((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  const mainlineId = mainline ? String(mainline.node.id) : null;
  const acceptancesData = loadDriftAcceptances(root);
  const nowMs = Date.now();
  const findAcc = (rel) => {
    for (const a of acceptancesData.acceptances) {
      if (!isAcceptanceEffective(a, mainlineId, nowMs)) continue;
      if (Array.isArray(a.files) && a.files.includes(rel)) return a;
    }
    return null;
  };

  const untracked = [];
  for (const f of files) {
    const rel = relPath(root, f);
    const entry = index.files[rel];
    const track = entry?.track || 'untracked';
    if (track === 'untracked' && !findAcc(rel)) {
      untracked.push(rel);
    }
  }

  if (untracked.length === 0) {
    console.log(JSON.stringify({ decision: 'approve' }));
    return;
  }

  // Build actionable suggestion.
  const fileList = untracked.join(',');
  const acceptCmd = `ft accept-drift --reason "<mandatory audit text>" --files ${fileList}`;
  const authorizeCmd = `ft authorize <program> <node-id> --allowed <path> ...`;

  const reasonLines = [
    `${untracked.length} file(s) about to be edited are UNTRACKED by any active mainline/backlog/optimize node and have no effective drift acceptance:`,
    ...untracked.slice(0, 10).map((f) => `  - ${f}`),
    untracked.length > 10 ? `  - ... and ${untracked.length - 10} more` : '',
    '',
    'Options:',
    `  1. Temporary opt-out (recommended for one-off/exploratory edits): ${acceptCmd}`,
    `  2. Permanent binding to backlog node: ${authorizeCmd}`,
    `  3. Skip this check for the session: export FT_HOOKS_MODE=off`,
  ].filter(Boolean);

  const context = {
    untracked_files: untracked,
    active_mainline: mainline ? `${mainline.program}/${mainline.node.id}` : null,
    drift_check_mode: config.drift_check_mode,
    suggestion_accept: acceptCmd,
    suggestion_authorize: authorizeCmd,
  };

  if (config.drift_check_mode === 'hard') {
    console.log(JSON.stringify({
      decision: 'block',
      reason: reasonLines.join('\n'),
      context,
    }));
    process.exit(1);
  } else if (config.drift_check_mode === 'soft') {
    console.log(JSON.stringify({
      decision: 'approve',
      reason: 'soft mode — edit allowed with drift warning',
      context: { ...context, warning: reasonLines.join('\n') },
    }));
  } else {
    // off (shouldn't reach here due to earlier check, but be defensive)
    console.log(JSON.stringify({ decision: 'approve', reason: 'drift_check_mode=off' }));
  }
}
module.exports = { cmdSessionStart, cmdPreEdit };
