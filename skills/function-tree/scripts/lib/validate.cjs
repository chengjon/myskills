'use strict';

const fs = require('fs');
const path = require('path');

const { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES } = require('./constants.cjs');
const { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates } = require('./gates.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { buildFileToTrackIndex, driftAcceptancesPath, loadDriftAcceptances, saveDriftAcceptances, currentActiveMainlineId, isAcceptanceEffective, newAcceptanceId } = require('./mainline.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
const { collectProjectInfo, collectFeatureCandidates, renderFeatureOverviewLines, splitEvidenceItems, collectEntrypointFeatureCandidates, collectPlannedFeatureCandidates, collectMarkdownCandidates, headingMatchesCandidateMode, cleanMarkdownText, isUsefulCandidateName, humanizeRouteFeatureName, isDynamicRouteSegment, cleanRouteSegment, featureKey, matchingFeatureKeyForCommand, uniqueCandidates, collectSourceTodoCandidates, renderCandidateEvidenceLines } = require('./scan-project.cjs');
function validateGovernance(root, flags = {}, args = []) {
  const errors = [];
  const warnings = [];
  const gov = path.join(root, '.governance');
  const currentHead = gitHead(root);
  const activePath = path.join(gov, 'active-gates.json');
  if (fs.existsSync(activePath)) {
    const active = readJson(activePath);
    const gates = normalizeGates(active);
    gates.forEach((gate, index) => validateNodeLike(gate, `active-gates[${index}]`, errors, true));
  }

  const programsDir = path.join(gov, 'programs');
  const allNodes = [];
  if (fs.existsSync(programsDir)) {
    for (const program of fs.readdirSync(programsDir)) {
      const nodesPath = path.join(programsDir, program, 'nodes.json');
      if (!fs.existsSync(nodesPath)) continue;
      const nodes = readJson(nodesPath);
      if (!Array.isArray(nodes)) {
        errors.push(`${rel(root, nodesPath)} must be a JSON array`);
        continue;
      }
      nodes.forEach((node, index) => {
        validateNodeLike(node, `${program}.nodes[${index}]`, errors, false, currentHead);
        if (flags.steward) validateStewardNode(node, `${program}.nodes[${index}]`, warnings);
        if (node && typeof node === 'object') {
          allNodes.push({ program, node, label: `${program}.nodes[${index}]` });
        }
      });
    }
  }

  const isFull = args.includes('full');
  if (isFull) {
    const docPath = path.join(root, 'FUNCTION_TREE.md');
    const info = fs.existsSync(docPath) ? collectProjectInfo(root) : null;
    validateCapabilityCrossReference(allNodes, info, warnings);
    validatePortConflicts(root, warnings);
    validateDocConsistency(docPath, info, root, errors, warnings);
    // Phase 2: mainline layering rules
    if (fs.existsSync(path.join(root, '.governance', 'programs'))) {
      const { resolved } = loadAllNodesResolved(root);
      validateMainlineUnique(resolved, errors);
      validateMainlineOrphan(resolved, errors);
      validateBacklogSwitchLock(resolved, errors, warnings);
      validateDepthConsistency(resolved, errors);
    }
    // Phase 3: drift-acceptance hygiene runs regardless of programs/ existence
    validateAcceptanceExpired(root, warnings);
  }

  if (errors.length) {
    console.log(errors.map((e) => `ERROR ${e}`).join('\n'));
    process.exit(1);
  }
  if (warnings.length) console.log(warnings.map((e) => `WARN ${e}`).join('\n'));
  console.log(isFull ? 'governance validation (full) passed' : 'governance validation passed');
}

function validateCapabilityCrossReference(nodeRecords, info, warnings) {
  if (!info) return;
  // Each governance node whose node_type references a capability (ui/api/cli/module)
  // should have evidence that the capability exists in the scanned project info.
  const capabilityKinds = new Set(['ui', 'api', 'cli', 'module', 'feature']);
  const uiRoutes = new Set((info.uiEntries || []).map((e) => e.route));
  const apiRoutes = new Set((info.apiEntries || []).map((e) => `${e.method} ${e.path}`));
  const commands = new Set((info.commandEntries || []).map((e) => e.command));
  const modules = new Set((info.sourceModules || []).map((m) => m.path));
  for (const rec of nodeRecords) {
    const nt = String(rec.node.node_type || '').toLowerCase();
    if (!capabilityKinds.has(nt)) continue;
    const ref = rec.node.function_tree_ref || rec.node.ref || '';
    if (!ref) {
      warnings.push(`${rec.label} capability node missing function_tree_ref`);
      continue;
    }
    if (nt === 'ui' && uiRoutes.size && !uiRoutes.has(ref)) {
      warnings.push(`${rec.label} references UI route \`${ref}\` not present in scanned UI entries`);
    }
    if (nt === 'api' && apiRoutes.size && !apiRoutes.has(ref)) {
      warnings.push(`${rec.label} references API endpoint \`${ref}\` not present in scanned API entries`);
    }
    if (nt === 'cli' && commands.size && !commands.has(ref)) {
      warnings.push(`${rec.label} references CLI command \`${ref}\` not present in scanned command entries`);
    }
    if (nt === 'module' && modules.size && !modules.has(ref)) {
      warnings.push(`${rec.label} references module \`${ref}\` not present in scanned source modules`);
    }
  }
}

function validatePortConflicts(root, warnings) {
  // Scan FUNCTION_TREE.md project-notes and root manifests/Makefile/docker-compose for declared
  // listening ports, then flag duplicates.
  const ports = new Map(); // port -> [sources]
  const docPath = path.join(root, 'FUNCTION_TREE.md');
  if (fs.existsSync(docPath)) {
    const text = readFile(docPath);
    const portRe = /\b(\d{4,5})\b/g;
    let m;
    while ((m = portRe.exec(text)) !== null) {
      const p = m[1];
      const lineStart = text.lastIndexOf('\n', m.index) + 1;
      const lineEnd = text.indexOf('\n', m.index);
      const line = text.slice(lineStart, lineEnd === -1 ? undefined : lineEnd);
      if (/port|listen|服务|frontend|backend|api|surreal|database|监听/i.test(line)) {
        if (!ports.has(p)) ports.set(p, []);
        ports.get(p).push('FUNCTION_TREE.md');
      }
    }
  }
  for (const fname of ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml', 'Makefile']) {
    const fpath = path.join(root, fname);
    if (!fs.existsSync(fpath)) continue;
    const text = readFile(fpath);
    const exposedRe = /(?:ports|expose|EXPOSE|listen|--port)[^\n]*?(\d{4,5})\b/g;
    let em;
    while ((em = exposedRe.exec(text)) !== null) {
      const p = em[1];
      if (!ports.has(p)) ports.set(p, []);
      ports.get(p).push(fname);
    }
  }
  for (const [port, sources] of ports) {
    const uniqSources = [...new Set(sources)];
    if (uniqSources.length > 1) {
      warnings.push(`port ${port} declared in multiple sources: ${uniqSources.join(', ')} (verify no real listener conflict)`);
    }
  }
}

function validateDocConsistency(docPath, info, root, errors, warnings) {
  if (!fs.existsSync(docPath)) {
    warnings.push(`${rel(root, docPath)} missing; run \`ft doc\` to generate`);
    return;
  }
  if (!info) return;
  const text = readFile(docPath);
  // Doc should mention at least one of each detected entry type.
  if ((info.uiEntries || []).length && !/UI|页面|route/i.test(text)) {
    warnings.push('FUNCTION_TREE.md missing UI/page section despite detected UI entries');
  }
  if ((info.apiEntries || []).length && !/API|服务|endpoint/i.test(text)) {
    warnings.push('FUNCTION_TREE.md missing API/service section despite detected API entries');
  }
  // Doc must still carry auto-scan marker if any structured/free notes exist.
  if (!/<!--\s*ft:auto-scan/.test(text) && /<!--\s*ft:(structured-notes|free-notes)/.test(text)) {
    errors.push('FUNCTION_TREE.md structured/free-notes blocks present without ft:auto-scan block (corrupted doc)');
  }
}

function validateNodeLike(node, label, errors, gateMode, currentHead) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    errors.push(`${label} must be an object`);
    return;
  }
  const status = node.status || node.gate;
  if (status && !STATUSES.has(status)) errors.push(`${label} has unknown status: ${status}`);
  if (!gateMode && !node.id) errors.push(`${label} missing id`);
  if (!gateMode && node.node_type && !STEWARD_NODE_TYPES.has(String(node.node_type).toLowerCase())) {
    errors.push(`${label} has unknown node_type: ${node.node_type}`);
  }
  if (node.status === 'blocked') {
    if (!node.blocker_reason) errors.push(`${label} blocked missing blocker_reason`);
    if (!node.unblock_target_state) errors.push(`${label} blocked missing unblock_target_state`);
    if (node.source_edits_authorized !== false) errors.push(`${label} blocked must set source_edits_authorized=false`);
  }
  if (node.source_edits_authorized === true && status && !SOURCE_EDIT_STATUSES.has(status)) {
    errors.push(`${label} authorizes source edits from non-implementation status: ${status}`);
  }
  if (!gateMode && Array.isArray(node.non_goals) && node.status === 'authorization-prepared' && node.non_goals.length === 0) {
    errors.push(`${label} authorization-prepared requires at least one non_goal`);
  }
  if (!gateMode && SOURCE_EDIT_STATUSES.has(node.status)) {
    const stale = staleEvidenceReason(node, currentHead || '');
    if (stale) errors.push(`${label} ${stale}`);
  }
}

function validateStewardNode(node, label, warnings) {
  if (!node.next_gate) warnings.push(`${label} missing next_gate`);
  if (!node.owner_lane) warnings.push(`${label} missing owner_lane`);
  if (!node.freshness) warnings.push(`${label} missing freshness policy`);
  if (stewardTypeFor(node) === 'implementation' && !list(node.allowed_paths).length) {
    warnings.push(`${label} implementation node missing allowed_paths`);
  }
}

function validateMainlineUnique(resolved, errors) {
  const activeRoots = resolved.filter((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  if (activeRoots.length > 1) {
    const list = activeRoots.map((r) => `${r.program}/${r.node.id}`).join(', ');
    errors.push(`V-MAINLINE-UNIQUE: ${activeRoots.length} active mainline roots found (${list}); at most one active depth=0 mainline node is allowed at a time`);
  }
}

function validateMainlineOrphan(resolved, errors) {
  const byId = new Map(resolved.map((r) => [`${r.program}/${r.node.id}`, r]));
  const validMainlineRoots = new Set(
    resolved
      .filter((e) => e.track === 'mainline' && e.depth === 0)
      .map((e) => `${e.program}/${e.node.id}`)
  );
  for (const entry of resolved) {
    if (entry.track !== 'mainline') continue;
    if (entry.depth === 0 || entry.depth === 99) continue;
    const parentKey = entry.mainline_id ? `${entry.program}/${entry.mainline_id}` : null;
    if (!parentKey || !validMainlineRoots.has(parentKey)) {
      const hint = parentKey && byId.has(parentKey)
        ? `parent ${parentKey} exists but is not a mainline root (track=${byId.get(parentKey).track}, depth=${byId.get(parentKey).depth})`
        : `parent ${parentKey || '(missing mainline_id)'} not found among mainline roots`;
      errors.push(`V-MAINLINE-ORPHAN: ${entry.program}/${entry.node.id} (depth=${entry.depth}) references ${hint}`);
    }
  }
}

function validateBacklogSwitchLock(resolved, errors, warnings) {
  const activeMainlineRoot = resolved.find((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  if (!activeMainlineRoot) return; // no lock when no active mainline
  const violationStatuses = ['authorized', 'implementation'];
  for (const entry of resolved) {
    if (entry.track !== 'backlog' && entry.track !== 'optimize') continue;
    const status = entry.node.status || '';
    if (violationStatuses.includes(status)) {
      errors.push(`V-BACKLOG-LOCK: ${entry.program}/${entry.node.id} (track=${entry.track}) is in status=${status} while active mainline ${activeMainlineRoot.program}/${activeMainlineRoot.node.id} exists; switch lock forbids authorizing backlog/optimize work until mainline closes`);
    } else if (status === 'planning') {
      warnings.push(`V-BACKLOG-LOCK: ${entry.program}/${entry.node.id} (track=${entry.track}) is in planning; switch lock active, do not advance to authorized until mainline closes`);
    }
  }
}

function validateDepthConsistency(resolved, errors) {
  for (const entry of resolved) {
    if (entry.track !== 'mainline') continue;
    const nodeId = `${entry.program}/${entry.node.id}`;
    if (entry.depth === 0) {
      const selfId = entry.node.mainline_id || '';
      if (selfId && selfId !== entry.node.id) {
        errors.push(`V-DEPTH-MISMATCH: ${nodeId} has depth=0 but mainline_id=${selfId}; depth=0 roots must have mainline_id equal to self or omitted`);
      }
    } else if (entry.depth === 1 || entry.depth === 2) {
      const selfId = entry.node.mainline_id || '';
      if (selfId === entry.node.id) {
        errors.push(`V-DEPTH-MISMATCH: ${nodeId} has depth=${entry.depth} but mainline_id equals self.id; only depth=0 roots may self-reference`);
      }
      if (!selfId) {
        errors.push(`V-DEPTH-MISMATCH: ${nodeId} has depth=${entry.depth} but mainline_id is missing; child nodes must reference their parent root`);
      }
    }
  }
}

function validateAcceptanceExpired(root, warnings) {
  const data = loadDriftAcceptances(root);
  const nowMs = Date.now();
  let expiredCount = 0;
  for (const acc of data.acceptances) {
    if (!acc || acc.status !== 'active') continue;
    if (acc.expires_at == null || acc.expires_at === '') continue; // permanent
    const exp = Date.parse(acc.expires_at);
    if (Number.isNaN(exp)) {
      warnings.push(`V-ACCEPTANCE-MALFORMED: ${acc.id} has unparsable expires_at="${acc.expires_at}"; drift-check will treat as ineffective — revoke or fix`);
      continue;
    }
    if (exp <= nowMs) {
      expiredCount += 1;
      warnings.push(`V-ACCEPTANCE-EXPIRED: ${acc.id} (mainline=${acc.mainline_at_accept == null ? '(none)' : acc.mainline_at_accept}, files=${(acc.files || []).length}) expired at ${acc.expires_at}; drift-check treats it as ineffective — revoke (ft revoke-drift --id ${acc.id}) or re-accept with new expiry`);
    }
  }
  return expiredCount;
}

function scopeCheck(root, flags) {
  const files = changedFiles(root, flags).filter((file) => file && !file.endsWith('/'));
  if (!files.length) {
    console.log('scope-check: no changed files');
    return;
  }

  const gates = normalizeGates(loadActiveGates(root)).filter((gate) =>
    gate.source_edits_authorized === true ||
    SOURCE_EDIT_STATUSES.has(gate.status || gate.gate)
  );

  if (!gates.length) {
    console.log(`scope-check: no active source-edit authorization; inspected ${files.length} changed file(s)`);
    return;
  }

  const violations = [];
  for (const file of files) {
    if (file.startsWith('.governance/')) continue;
    const forbiddenGate = gates.find((gate) => list(gate.forbidden_paths).some((pattern) => matches(pattern, file)));
    if (forbiddenGate) {
      violations.push(`${file} matches forbidden_paths in ${gateName(forbiddenGate)}`);
      continue;
    }
    const allowed = gates.some((gate) => {
      const allowedPaths = list(gate.allowed_paths);
      return allowedPaths.length > 0 && allowedPaths.some((pattern) => matches(pattern, file));
    });
    if (!allowed) violations.push(`${file} is outside active allowed_paths`);
  }

  if (violations.length) {
    console.log(violations.map((v) => `ERROR ${v}`).join('\n'));
    process.exit(1);
  }
  console.log(`scope-check: ${files.length} changed file(s) within active authorization`);
}

function changedFiles(root, flags) {
  if (flags.files) {
    return String(flags.files).split(',').map((s) => s.trim()).filter(Boolean);
  }
  const commands = [
    ['diff', '--name-only'],
    ['diff', '--name-only', '--cached'],
    ['ls-files', '--others', '--exclude-standard'],
  ];
  const seen = new Set();
  for (const args of commands) {
    try {
      for (const line of run('git', args, root).split(/\r?\n/)) {
        const value = line.trim();
        if (value) seen.add(value);
      }
    } catch (_) {
      // If git is unavailable, fall back to an empty set. The caller can pass --files.
    }
  }
  return Array.from(seen).sort();
}
module.exports = { validateGovernance, validateCapabilityCrossReference, validatePortConflicts, validateDocConsistency, validateNodeLike, validateStewardNode, validateMainlineUnique, validateMainlineOrphan, validateBacklogSwitchLock, validateDepthConsistency, validateAcceptanceExpired, scopeCheck, changedFiles };
