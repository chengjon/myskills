'use strict';

const fs = require('fs');
const path = require('path');

const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { buildFileToTrackIndex, driftAcceptancesPath, loadDriftAcceptances, saveDriftAcceptances, currentActiveMainlineId, isAcceptanceEffective, newAcceptanceId } = require('./mainline.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function cmdDriftCheck(root, flags) {
  // Source files: explicit --files a,b,c, or --staged (git diff --cached), or both.
  // Output: JSON lines per file + human-readable summary at end.
  // Exit codes (strict mode):
  //   0  all files tracked OR accepted-drift (Phase 3: file is UNTRACKED but covered by an effective acceptance)
  //   1  any file UNTRACKED with no effective acceptance
  //   2  invalid arguments
  const filesFlag = one(flags, 'files');
  const useStaged = flags.staged === true || flags['--staged'] === true;
  let files = [];
  if (filesFlag) files = filesFlag.split(',').map((s) => s.trim()).filter(Boolean);
  if (useStaged) {
    const staged = listStagedFiles(root);
    files = Array.from(new Set([...files, ...staged]));
  }
  if (!files.length) {
    console.error('drift-check requires --files <a,b,c> or --staged');
    process.exit(2);
  }
  if (!fs.existsSync(path.join(root, '.governance', 'programs'))) {
    console.log('no governance nodes; every file is UNTRACKED');
    process.exit(1);
  }
  // Ensure index is fresh
  buildFileToTrackIndex(root);
  const index = readJsonSafe(path.join(root, '.governance', 'file-to-track.json')) || { files: {} };
  const { resolved } = loadAllNodesResolved(root);
  const activeMainline = resolved.find((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  const activeMainlineId = activeMainline ? String(activeMainline.node.id) : null;

  // Phase 3: load drift acceptances once, scoped to the current active mainline.
  // isAcceptanceEffective already enforces status=active + mainline match + not-expired.
  const acceptancesData = loadDriftAcceptances(root);
  const nowMs = Date.now();
  const findEffectiveAcceptance = (rel) => {
    for (const acc of acceptancesData.acceptances) {
      if (!isAcceptanceEffective(acc, activeMainlineId, nowMs)) continue;
      const accFiles = Array.isArray(acc.files) ? acc.files : [];
      if (accFiles.includes(rel)) return acc;
    }
    return null;
  };

  let mainlineCount = 0, backlogCount = 0, optimizeCount = 0, untrackedCount = 0, acceptedCount = 0;
  for (const file of files) {
    const rel = relPath(root, file);
    const entry = index.files[rel];
    let track = 'untracked';
    let nodeInfo = null;
    let accepted = false;
    let acceptanceId = null;
    let acceptanceExpires = null;
    if (entry) {
      track = entry.track || 'untracked';
      nodeInfo = {
        node_id: entry.node_id,
        program: entry.program,
        mainline_id: entry.mainline_id || null,
        depth: entry.depth,
      };
    }
    // Phase 3: even if indexed, files that fall under backlog/optimize/mainline are governed by their node;
    // acceptance lookup applies only to UNTRACKED files (those outside any active node's allowed_paths).
    if (track === 'untracked') {
      const acc = findEffectiveAcceptance(rel);
      if (acc) {
        track = 'accepted-drift';
        accepted = true;
        acceptanceId = acc.id;
        acceptanceExpires = acc.expires_at == null ? 'permanent' : acc.expires_at;
      }
    }
    const drift = track === 'untracked';
    const record = {
      file: rel,
      track,
      drift,
      active_mainline: activeMainline ? `${activeMainline.program}/${activeMainline.node.id}` : null,
      ...(accepted ? { accepted: true, acceptance_id: acceptanceId, expires_at: acceptanceExpires } : {}),
      ...nodeInfo,
    };
    console.log(JSON.stringify(record));
    if (track === 'mainline') mainlineCount++;
    else if (track === 'backlog') backlogCount++;
    else if (track === 'optimize') optimizeCount++;
    else if (track === 'accepted-drift') acceptedCount++;
    else untrackedCount++;
  }
  console.error('---');
  console.error(`drift-check: mainline=${mainlineCount} backlog=${backlogCount} optimize=${optimizeCount} accepted-drift=${acceptedCount} untracked=${untrackedCount}`);
  if (activeMainline) {
    console.error(`active mainline: ${activeMainline.program}/${activeMainline.node.id} (${activeMainline.node.title || ''})`);
  } else {
    console.error('no active mainline; switch lock inactive');
  }
  if (acceptedCount > 0) {
    console.error(`NOTE: ${acceptedCount} file(s) are accepted-drift (explicitly opted out of mainline); review periodically and convert to backlog node when stabilized`);
  }
  if (untrackedCount > 0) {
    console.error(`HARD FAIL: ${untrackedCount} file(s) are UNTRACKED — accept drift via 'ft accept-drift --reason ... --files ...' or update node allowed_paths`);
    process.exit(1);
  }
  if (backlogCount > 0) {
    console.error(`WARN: ${backlogCount} file(s) belong to backlog; switch lock active, do not authorize until mainline closes`);
  }
  if (optimizeCount > 0) {
    console.error(`WARN: ${optimizeCount} file(s) belong to optimize; P3 priority, defer until mainline+backlog close`);
  }
  process.exit(0);
}

function cmdAcceptDrift(root, flags) {
  // Phase 3 implementation. Writes one acceptance record binding {file, mainline} tuple.
  // Flags:
  //   --reason <text>     required; audit-trail justification (non-empty)
  //   --files <a,b,c>     required; relpaths or abspaths; must exist on disk
  //   --expires <spec>    optional; default '30d'. '0' = permanent. Format: '<N><unit>' (s|m|h|d|w)
  //   --mainline <id>     optional; override current active mainline id. Use 'none' for no-active-mainline.
  //   --by <name>         optional; override accepted_by (default: $LOGNAME / 'unknown')
  const reason = one(flags, 'reason');
  const filesFlag = one(flags, 'files');
  const expiresFlag = one(flags, 'expires');
  const mainlineFlag = one(flags, 'mainline');
  const byFlag = one(flags, 'by');

  if (!reason || !reason.trim()) {
    console.error('accept-drift requires --reason <text>');
    console.error('reason is mandatory for audit trail; documents why this drift is allowed (per mainline methodology)');
    process.exit(2);
  }
  if (!filesFlag) {
    console.error('accept-drift requires --files <a,b,c>');
    process.exit(2);
  }
  const files = filesFlag.split(',').map((s) => s.trim()).filter(Boolean);
  if (!files.length) {
    console.error('accept-drift --files must list at least one path');
    process.exit(2);
  }
  for (const f of files) {
    const abs = path.isAbsolute(f) ? f : path.resolve(process.cwd(), f);
    if (!fs.existsSync(abs)) {
      console.error(`accept-drift: file not found: ${f} (resolved ${abs})`);
      console.error('cannot accept drift on a nonexistent file; create it first or fix the path');
      process.exit(2);
    }
  }

  const { resolved } = loadAllNodesResolved(root);
  let mainlineId;
  if (mainlineFlag) {
    mainlineId = mainlineFlag === 'none' ? null : mainlineFlag;
  } else {
    mainlineId = currentActiveMainlineId(resolved);
  }

  let expiresAt = null; // default permanent handled below
  if (!expiresFlag) {
    expiresAt = expiryFromNow(30 * 24 * 60 * 60); // 30 days, seconds
  } else if (expiresFlag === '0' || expiresFlag.toLowerCase() === 'permanent') {
    expiresAt = null; // explicit permanent
  } else {
    const secs = parseDuration(expiresFlag);
    if (secs == null) {
      console.error(`accept-drift: invalid --expires ${expiresFlag}; format: <N><s|m|h|d|w> or 0 for permanent`);
      process.exit(2);
    }
    expiresAt = expiryFromNow(secs);
  }

  const data = loadDriftAcceptances(root);
  const id = newAcceptanceId(data.acceptances);
  const acceptedBy = (byFlag && byFlag.trim()) || (process.env.LOGNAME && process.env.LOGNAME.trim()) || 'unknown';
  const relFiles = files.map((f) => relPath(root, f));

  const record = {
    id,
    files: relFiles,
    reason: reason.trim(),
    accepted_at: new Date().toISOString(),
    accepted_by: acceptedBy,
    mainline_at_accept: mainlineId,
    expires_at: expiresAt,
    status: 'active',
  };
  data.acceptances.push(record);
  saveDriftAcceptances(root, data);

  console.log(`accepted drift ${id}`);
  console.log(`  files:   ${relFiles.join(', ')}`);
  console.log(`  mainline: ${mainlineId == null ? '(no active mainline)' : mainlineId}`);
  console.log(`  expires: ${expiresAt == null ? 'permanent' : expiresAt}`);
  console.log(`  reason:  ${record.reason}`);
  console.log(`  by:      ${acceptedBy}`);
  console.log(`path: ${driftAcceptancesPath(root)}`);
}

function cmdRevokeDrift(root, flags) {
  // Phase 3: mark an existing acceptance as revoked (record kept for audit). Hard-fail if not found.
  const id = one(flags, 'id');
  if (!id) {
    console.error('revoke-drift requires --id <acceptance-id>');
    console.error('find ids via: cat .governance/drift-acceptances.json');
    process.exit(2);
  }
  const data = loadDriftAcceptances(root);
  const acc = data.acceptances.find((a) => a && a.id === id);
  if (!acc) {
    console.error(`revoke-drift: acceptance not found: ${id}`);
    console.error(`path: ${driftAcceptancesPath(root)}`);
    process.exit(1);
  }
  if (acc.status === 'revoked') {
    console.error(`revoke-drift: ${id} is already revoked (no change)`);
    process.exit(1);
  }
  acc.revoked_at = new Date().toISOString();
  acc.revoked_by = (process.env.LOGNAME && process.env.LOGNAME.trim()) || 'unknown';
  acc.status = 'revoked';
  saveDriftAcceptances(root, data);
  console.log(`revoked ${id}`);
  console.log(`  files:   ${(acc.files || []).join(', ')}`);
  console.log(`  mainline: ${acc.mainline_at_accept == null ? '(no active mainline at accept)' : acc.mainline_at_accept}`);
  console.log(`  reason (original): ${acc.reason}`);
  console.log(`path: ${driftAcceptancesPath(root)}`);
}
module.exports = { cmdDriftCheck, cmdAcceptDrift, cmdRevokeDrift, cmdDiff };

// FT_REVIEW MED: `ft diff` — structured Function Tree diff.
//
// Input contract (per review suggestion #5):
//   - Primary input: normalized candidate JSON snapshots persisted by ft doc
//     at .governance/programs/<program>/candidates.json (deterministic, bounded).
//   - Fallback: when a snapshot is missing for --before / --after, parse the
//     FUNCTION_TREE.md backup files via lightweight Markdown section counting.
//
// `--before` / `--after` accept:
//   - 'head'     — the current candidates.json on disk
//   - 'prev'     — the most recent candidates.json from git HEAD
//   - <sha>:path — explicit git blob
//   - <file>     — explicit local file path
//
// Output: human-readable diff of candidate counts + per-source-category deltas
// + per-kind deltas + added/removed candidate names (capped at 20 each).
function cmdDiff(root, flags) {
  const beforeRef = one(flags, 'before');
  const afterRef = one(flags, 'after');
  if (!beforeRef || !afterRef) {
    console.error('ft diff requires --before <ref> --after <ref>');
    console.error('  ref = "head" | "prev" | <sha>:<path> | <file-path>');
    process.exit(2);
  }
  const program = detectProgram(root);
  if (!program) {
    console.error('ft diff: no .governance/programs/*/ found; run `/ft:init` first');
    process.exit(1);
  }
  const before = loadSnapshotRef(root, program, beforeRef);
  const after = loadSnapshotRef(root, program, afterRef);
  if (!before || !after) {
    console.error(`ft diff: missing snapshot — before=${beforeRef} after=${afterRef}`);
    process.exit(1);
  }

  const lines = [];
  lines.push(`diff ${beforeRef} → ${afterRef} (program ${program})`);
  lines.push('');
  lines.push('Counts:');
  lines.push(`  feature candidates:  ${countOf(before, 'feature_candidates')} -> ${countOf(after, 'feature_candidates')}`);
  lines.push(`  planned candidates:  ${countOf(before, 'planned_candidates')} -> ${countOf(after, 'planned_candidates')}`);
  lines.push(`  verification gates:  ${countOf(before, 'verification_gates')} -> ${countOf(after, 'verification_gates')}`);
  lines.push('');
  lines.push('By source category:');
  const cats = new Set([
    ...Object.keys(before.by_source_category || {}),
    ...Object.keys(after.by_source_category || {}),
  ]);
  for (const cat of Array.from(cats).sort()) {
    const b = (before.by_source_category || {})[cat] || 0;
    const a = (after.by_source_category || {})[cat] || 0;
    if (b !== a) lines.push(`  ${cat}: ${b} -> ${a} (delta ${signedDelta(a - b)})`);
  }
  lines.push('');
  lines.push('By kind:');
  const kinds = new Set([
    ...Object.keys(before.by_kind || {}),
    ...Object.keys(after.by_kind || {}),
  ]);
  for (const k of Array.from(kinds).sort()) {
    const b = (before.by_kind || {})[k] || 0;
    const a = (after.by_kind || {})[k] || 0;
    if (b !== a) lines.push(`  ${k}: ${b} -> ${a} (delta ${signedDelta(a - b)})`);
  }
  lines.push('');
  const beforeIds = new Set((before.feature_candidates || []).map((c) => c.id).filter(Boolean));
  const afterIds = new Set((after.feature_candidates || []).map((c) => c.id).filter(Boolean));
  const added = (after.feature_candidates || []).filter((c) => c.id && !beforeIds.has(c.id)).slice(0, 20);
  const removed = (before.feature_candidates || []).filter((c) => c.id && !afterIds.has(c.id)).slice(0, 20);
  if (added.length) {
    lines.push('Added candidates (top 20):');
    for (const c of added) lines.push(`  + ${c.id}: ${c.name}`);
  }
  if (removed.length) {
    lines.push('Removed candidates (top 20):');
    for (const c of removed) lines.push(`  - ${c.id}: ${c.name}`);
  }
  console.log(lines.join('\n'));
}

function signedDelta(n) {
  return n >= 0 ? `+${n}` : String(n);
}

function countOf(snapshot, key) {
  return (snapshot && snapshot.counts && snapshot.counts[key]) || 0;
}

function detectProgram(root) {
  const programsDir = path.join(root, '.governance', 'programs');
  if (!fs.existsSync(programsDir)) return null;
  const dirs = fs.readdirSync(programsDir).filter((d) => {
    try { return fs.statSync(path.join(programsDir, d)).isDirectory(); } catch (_) { return false; }
  });
  return dirs.length === 1 ? dirs[0] : (dirs[0] || null);
}

function loadSnapshotRef(root, program, ref) {
  const snapshotPath = path.join(root, '.governance', 'programs', program, 'candidates.json');
  if (ref === 'head' || ref === 'current') {
    return readJsonSafe(snapshotPath);
  }
  if (ref === 'prev' || ref === 'previous') {
    // Try git HEAD version first; fall back to the most recent FUNCTION_TREE.*.md
    // backup if no candidates.json existed at HEAD.
    try {
      const out = run('git', ['-C', root, 'show', `HEAD:${rel(root, snapshotPath)}`], root);
      return JSON.parse(out);
    } catch (_) {
      return fallbackMarkdownSnapshot(root);
    }
  }
  // Explicit git ref: '<sha>:<path>'
  if (ref.indexOf(':') !== -1) {
    try {
      const out = run('git', ['-C', root, 'show', ref], root);
      return JSON.parse(out);
    } catch (_) { return null; }
  }
  // Explicit local file path.
  if (fs.existsSync(ref)) {
    if (/\.json$/i.test(ref)) return readJsonSafe(ref);
    return fallbackMarkdownSnapshot(root, ref);
  }
  return null;
}

function fallbackMarkdownSnapshot(root, explicitPath) {
  // Last-resort: count Markdown headings in a FUNCTION_TREE.md backup so users
  // can compare pre-snapshot states. Numbers will not match JSON-derived counts
  // exactly; the diff header notes this fallback so callers aren't misled.
  const target = explicitPath || (function () {
    const backupDir = path.join(root, '.governance', 'backups');
    if (!fs.existsSync(backupDir)) return null;
    const files = fs.readdirSync(backupDir)
      .filter((f) => /^FUNCTION_TREE\..*\.md$/.test(f))
      .map((f) => ({ f, t: fs.statSync(path.join(backupDir, f)).mtimeMs }))
      .sort((a, b) => b.t - a.t);
    return files.length ? path.join(backupDir, files[0].f) : null;
  })();
  if (!target || !fs.existsSync(target)) return null;
  const text = readFile(target);
  const h2 = (text.match(/^##\s+/gm) || []).length;
  const h3 = (text.match(/^###\s+/gm) || []).length;
  return {
    fallback: 'markdown-section-count',
    fallback_source: target,
    counts: { feature_candidates: h2, planned_candidates: h3, verification_gates: 0 },
    by_source_category: {},
    by_kind: {},
    feature_candidates: [],
    planned_candidates: [],
    verification_gates: [],
  };
}
