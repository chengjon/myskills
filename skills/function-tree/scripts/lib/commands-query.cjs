'use strict';

const fs = require('fs');
const path = require('path');

const { DEFAULT_CONFIG, VALID_DRIFT_MODES, VALID_HOOK_MODES, governanceConfigPath, loadConfig, saveConfig } = require('./config.cjs');
const { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates } = require('./gates.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { buildFileToTrackIndex, driftAcceptancesPath, loadDriftAcceptances, saveDriftAcceptances, currentActiveMainlineId, isAcceptanceEffective, newAcceptanceId } = require('./mainline.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function printStatus(root) {
  const gov = path.join(root, '.governance');
  const active = loadActiveGates(root);
  const programsDir = path.join(gov, 'programs');
  const programs = fs.existsSync(programsDir)
    ? fs.readdirSync(programsDir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name).sort()
    : [];
  const gates = normalizeGates(active);
  console.log([
    `root: ${root}`,
    `programs: ${programs.length ? programs.join(', ') : '(none)'}`,
    `active gates: ${gates.length}`,
  ].join('\n'));
}

function printGate(root, verbose) {
  const gates = normalizeGates(loadActiveGates(root));
  if (!gates.length) {
    console.log('active gates: none');
    return;
  }
  const rows = gates.map((gate) => {
    const id = gate.id || gate.node_id || '-';
    const program = gate.program || '-';
    const status = gate.status || gate.gate || '-';
    const next = gate.next_allowed || gate.next_gate || '-';
    if (!verbose) return `${program}/${id}: ${status} -> ${next}`;
    const allowed = list(gate.allowed_paths).join(', ') || '-';
    const forbidden = list(gate.forbidden_paths).join(', ') || '-';
    const blocker = gate.current_blocker || gate.blocker_reason || '-';
    return `${program}/${id}: ${status}\n  next: ${next}\n  blocker: ${blocker}\n  allowed: ${allowed}\n  forbidden: ${forbidden}`;
  });
  console.log(rows.join('\n'));
}

function cmdConfig(root, args, flags) {
  const sub = args[0] || 'list';
  const key = one(flags, 'key') || (args[1] && !args[0].startsWith('-') ? args[1] : null);
  const value = one(flags, 'value');

  if (sub === 'list') {
    const config = loadConfig(root);
    // For project_profile=auto, also print the resolved value so users can
    // see what detection picked without a separate command.
    const { resolveProjectProfile } = require('./config.cjs');
    const resolved = resolveProjectProfile(root, config);
    console.log(JSON.stringify({ ...config, project_profile_resolved: resolved }, null, 2));
    return;
  }
  if (sub === 'get') {
    if (!key) { console.error('config get requires --key <name>'); process.exit(2); }
    const config = loadConfig(root);
    console.log(String(config[key] ?? ''));
    return;
  }
  if (sub === 'set') {
    if (!key) { console.error('config set requires --key <name>'); process.exit(2); }
    if (value == null) { console.error('config set requires --value <text>'); process.exit(2); }
    let normalized = value;
    if (key === 'drift_check_mode' || key === 'hooks_mode') {
      normalized = value.toLowerCase();
      if (key === 'drift_check_mode' && !VALID_DRIFT_MODES.has(normalized)) {
        console.error(`invalid drift_check_mode: ${value}; valid: hard, soft, off`); process.exit(2);
      }
      if (key === 'hooks_mode' && !VALID_HOOK_MODES.has(normalized)) {
        console.error(`invalid hooks_mode: ${value}; valid: on, off`); process.exit(2);
      }
    } else if (key === 'mainline_warning' || key === 'auto_accept_suggest') {
      normalized = (value === '1' || value.toLowerCase() === 'true');
    } else if (key === 'project_profile') {
      normalized = value.toLowerCase();
      const { VALID_PROFILES } = require('./config.cjs');
      if (!VALID_PROFILES.has(normalized)) {
        console.error(`invalid project_profile: ${value}; valid: ${Array.from(VALID_PROFILES).join(', ')}`);
        process.exit(2);
      }
    } else if (!Object.prototype.hasOwnProperty.call(DEFAULT_CONFIG, key)) {
      console.error(`unknown config key: ${key}; valid: ${Object.keys(DEFAULT_CONFIG).join(', ')}`); process.exit(2);
    }
    const config = loadConfig(root);
    config[key] = normalized;
    saveConfig(root, config);
    console.log(`config ${key} = ${normalized}`);
    return;
  }
  console.error(`unknown config subcommand: ${sub}; valid: list, get, set`);
  process.exit(2);
}

function cmdMainline(root) {
  const { resolved } = loadAllNodesResolved(root);
  if (!resolved.length) {
    console.log('no governance nodes found; run `/ft:init` first');
    return;
  }
  // Find active mainline root(s)
  const mainlineRoots = resolved.filter((e) => e.track === 'mainline' && e.depth === 0);
  const activeRoots = mainlineRoots.filter((e) => isActiveStatus(e.node.status));
  const backlogNodes = resolved.filter((e) => e.track === 'backlog');

  if (!activeRoots.length) {
    console.log('no active mainline node (depth=0, track=mainline) found.');
    console.log('所有节点 track=untracked 或已 closeout。');
    if (mainlineRoots.length) {
      console.log(`\n存在 ${mainlineRoots.length} 条已关闭的主线（参考）：`);
      for (const r of mainlineRoots) {
        console.log(`  - ${r.node.id} ${r.node.title || ''} [${r.node.status}]`);
      }
    }
    return;
  }

  if (activeRoots.length > 1) {
    console.log(`WARN: 检测到 ${activeRoots.length} 条并行主线（违反主线唯一性，Phase 2 将强制校验）：`);
    for (const r of activeRoots) console.log(`  - ${r.node.id} ${r.node.title || ''}`);
    console.log('');
  }

  for (const r of activeRoots) {
    console.log(`当前主线：${r.node.id} ${r.node.title || ''} [${r.node.status}]`);
    const children1 = resolved.filter((e) => e.track === 'mainline' && e.depth === 1 && e.mainline_id === r.node.id);
    const children2 = resolved.filter((e) => e.track === 'mainline' && e.depth === 2 && e.mainline_id === r.node.id);
    if (children1.length) {
      console.log('  depth=1 子任务：');
      for (const c of children1) {
        const marker = c.node.status === 'landed' ? '✅ landed'
          : c.node.status === 'approved' || c.node.source_edits_authorized ? '🔵 authorized'
          : c.node.status === 'planning' ? '⚪ planning'
          : `[${c.node.status}]`;
        console.log(`    - ${c.node.id} ${c.node.title || ''} ${marker}`);
      }
    }
    if (children2.length) {
      console.log('  depth=2 子任务：');
      for (const c of children2) {
        console.log(`    - ${c.node.id} ${c.node.title || ''} [${c.node.status}]`);
      }
    }
    const myBacklog = backlogNodes.filter((e) => e.mainline_id === r.node.id);
    if (myBacklog.length) {
      console.log('  关联 Backlog（未达准入条件，禁止启动）：');
      for (const b of myBacklog) console.log(`    - ${b.node.id} ${b.node.title || ''} [${b.node.status}]`);
    }
    console.log('  切换锁：active（mainline 未闭合，backlog/optimize 任务不可授权）');
    console.log('');
  }
}

function cmdLocate(root, args) {
  const target = args[0];
  if (!target) fail('locate requires <file-path>', 2);
  const index = buildFileToTrackIndex(root);
  // Normalize target to repo-relative
  const abs = path.isAbsolute(target) ? target : path.resolve(process.cwd(), target);
  const repoAbs = path.resolve(root);
  let rel = abs.startsWith(repoAbs) ? abs.slice(repoAbs.length).replace(/^[/\\]+/, '') : target;
  rel = rel.replace(/\\/g, '/');

  const entry = index.files[rel];
  if (!entry) {
    const { resolved } = loadAllNodesResolved(root);
    const activeRoots = resolved.filter((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
    console.log(`File: ${rel}`);
    console.log('Track: UNTRACKED ⚠️');
    console.log('原因：该文件未挂接到任何 active 节点的 allowed_paths');
    if (activeRoots.length) {
      console.log(`当前主线：${activeRoots[0].node.id} ${activeRoots[0].node.title || ''}`);
    }
    console.log('提示：此修改属于支线治理，建议进入 Backlog');
    console.log('  （Phase 3 将支持 ft accept-drift --reason "..." 留痕）');
    return;
  }
  const { resolved, byId } = loadAllNodesResolved(root);
  const nodeRec = resolved.find((r) => r.node.id === entry.node_id);
  const mainlineRoot = entry.mainline_id && byId.has(entry.mainline_id) ? byId.get(entry.mainline_id).node : null;
  console.log(`File: ${rel}`);
  console.log(`Track: ${entry.track} ${entry.track === 'mainline' ? '✅' : ''}`);
  if (mainlineRoot) console.log(`Mainline: ${mainlineRoot.id} ${mainlineRoot.title || ''} [${mainlineRoot.status}]`);
  console.log(`Depth: ${entry.depth} ${entry.depth === 0 ? '(主线根节点)' : entry.depth === 1 ? '(一级子任务)' : entry.depth === 2 ? '(二级子任务)' : '(非主线)'}`);
  if (nodeRec) console.log(`Node: ${nodeRec.node.id} ${nodeRec.node.title || ''}`);
}

function cmdMap(root) {
  const index = buildFileToTrackIndex(root);
  const counts = { mainline: 0, backlog: 0, optimize: 0 };
  for (const k of Object.keys(index.files)) {
    const t = index.files[k].track;
    if (counts[t] !== undefined) counts[t]++;
  }
  console.log(`indexed ${Object.keys(index.files).length} files:`);
  console.log(`  mainline: ${counts.mainline}`);
  console.log(`  backlog:  ${counts.backlog}`);
  console.log(`  optimize: ${counts.optimize}`);
  console.log(`path: ${path.join(root, '.governance', 'file-to-track.json')}`);
}

function installGuard(root, flags) {
  const guardsDir = path.join(root, '.governance', 'guards');
  ensureDir(guardsDir);
  const guardPath = path.join(guardsDir, 'ft-scope-check.sh');
  const preCommitPath = path.join(guardsDir, 'pre-commit');
  if (fs.existsSync(guardPath) && !flags.force) {
    fail(`${rel(root, guardPath)} already exists; rerun with --force to overwrite`, 2);
  }
  if (fs.existsSync(preCommitPath) && !flags.force) {
    fail(`${rel(root, preCommitPath)} already exists; rerun with --force to overwrite`, 2);
  }
  const scriptPath = path.join(skillDir(), 'scripts', 'ft-governance.cjs');

  // PostToolUse guard (existing) — runs scope-check after Edit/Write/MultiEdit.
  const guardContent = [
    '#!/usr/bin/env bash',
    'set -euo pipefail',
    '',
    `FT_GOVERNANCE_SCRIPT=${shellQuote(scriptPath)}`,
    'export FT_GOVERNANCE_SCRIPT',
    'exec node "$FT_GOVERNANCE_SCRIPT" scope-check --root "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" "$@"',
    '',
  ].join('\n');
  writeFile(guardPath, guardContent);
  fs.chmodSync(guardPath, 0o755);

  // pre-commit guard (Phase 4) — runs drift-check --staged; exit code honors drift_check_mode.
  // hard (default): UNTRACKED w/o acceptance -> exit 1, blocks commit.
  // soft: prints warning, exits 0.
  // off: skips entirely.
  const preCommitContent = [
    '#!/usr/bin/env bash',
    'set -euo pipefail',
    '',
    `FT_GOVERNANCE_SCRIPT=${shellQuote(scriptPath)}`,
    'export FT_GOVERNANCE_SCRIPT',
    'REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"',
    'MODE="$(node "$FT_GOVERNANCE_SCRIPT" config get --key drift_check_mode --root "$REPO_ROOT" 2>/dev/null || echo hard)"',
    'if [[ "$MODE" == "off" ]]; then',
    '  echo "[ft] drift_check_mode=off, skipping drift-check" >&2',
    '  exit 0',
    'fi',
    'OUT_FILE="$(mktemp)"',
    'set +e',
    'node "$FT_GOVERNANCE_SCRIPT" drift-check --staged --root "$REPO_ROOT" >"$OUT_FILE" 2>&1',
    'STATUS=$?',
    'set -e',
    'cat "$OUT_FILE" >&2',
    'rm -f "$OUT_FILE"',
    'if [[ "$STATUS" -ne 0 ]]; then',
    '  if [[ "$MODE" == "soft" ]]; then',
    '    echo "[ft] drift-check found UNTRACKED files (soft mode, commit allowed)" >&2',
    '    exit 0',
    '  fi',
    '  echo "[ft] commit blocked: UNTRACKED files without effective drift acceptance" >&2',
    '  echo "[ft] fix: ft accept-drift --reason ... --files ...  OR  ft authorize to add to backlog" >&2',
    '  exit 1',
    'fi',
    'exit 0',
    '',
  ].join('\n');
  writeFile(preCommitPath, preCommitContent);
  fs.chmodSync(preCommitPath, 0o755);

  console.log([
    `installed guards:`,
    `  ${rel(root, guardPath)}        (PostToolUse: scope-check)`,
    `  ${rel(root, preCommitPath)}  (pre-commit: drift-check --staged)`,
    '',
    'integration options (pick one):',
    '',
    'A. git core.hooksPath (simplest):',
    '  git config core.hooksPath .governance/guards',
    '  # note: this makes .governance/guards the hooks dir for ALL hooks;',
    '  # only pre-commit is shipped, others (pre-push, etc.) will be silent',
    '',
    'B. symlink into .git/hooks (only pre-commit):',
    '  ln -sf ../../.governance/guards/pre-commit .git/hooks/pre-commit',
    '',
    'C. husky / lefthook (recommended for shared repos):',
    '  # husky: add to .husky/pre-commit:',
    '  #   bash .governance/guards/pre-commit',
    '  # lefthook.yml: pre-commit: commands: ft-drift:',
    '  #     run: bash .governance/guards/pre-commit',
    '',
    'Claude Code PostToolUse snippet (add to .claude/settings.json):',
    '{',
    '  "hooks": {',
    '    "PostToolUse": [{',
    '      "matcher": "Edit|MultiEdit|Write",',
    '      "command": "bash .governance/guards/ft-scope-check.sh",',
    '      "description": "Check file edits against active FUNCTION_TREE governance authorization"',
    '    }],',
    '    "PreToolUse": [{',
    '      "matcher": "Edit|MultiEdit|Write",',
    '      "command": "node $FT_GOVERNANCE_SCRIPT pre-edit --files {file}",',
    '      "description": "Phase 4 drift-check + accept-drift suggestion before edit"',
    '    }]',
    '  }',
    '}',
  ].join('\n'));
}

function repairActiveGates(root) {
  const gov = path.join(root, '.governance');
  ensureDir(gov);
  const active = {
    schema_version: 1,
    updated_at: new Date().toISOString(),
    gates: [],
  };
  const programsDir = path.join(gov, 'programs');
  if (fs.existsSync(programsDir)) {
    for (const program of fs.readdirSync(programsDir).sort()) {
      const nodesPath = path.join(programsDir, program, 'nodes.json');
      if (!fs.existsSync(nodesPath)) continue;
      const nodes = loadNodes(nodesPath);
      for (const node of nodes) {
        if (!node || !node.id || ['closed', 'archived'].includes(node.status)) continue;
        active.gates.push(activeGateFromNode(program, node));
      }
    }
  }
  writeJson(path.join(gov, 'active-gates.json'), active);
  syncActiveGates(root);
  console.log(`rebuilt active gates: ${active.gates.length}`);
}
module.exports = { printStatus, printGate, cmdConfig, cmdMainline, cmdLocate, cmdMap, installGuard, repairActiveGates };
