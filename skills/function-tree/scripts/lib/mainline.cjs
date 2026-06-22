'use strict';

const fs = require('fs');
const path = require('path');

const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function buildFileToTrackIndex(root) {
  // Reads all nodes' allowed_paths and produces a reverse index:
  //   { "<relpath>": { track, mainline_id, depth, node_id, program } }
  // untracked files are not listed (absence == untracked).
  const indexPath = path.join(root, '.governance', 'file-to-track.json');
  const cached = fs.existsSync(indexPath) ? readJsonSafe(indexPath) : { files: {} };
  const cachedFiles = (cached && cached.files) || {};

  const { resolved } = loadAllNodesResolved(root);
  const index = { schema_version: 1, generated_at: new Date().toISOString(), files: {} };
  const touchedFiles = new Set();

  for (const entry of resolved) {
    const { node, track, mainline_id, depth, program } = entry;
    if (!node.allowed_paths || !Array.isArray(node.allowed_paths)) continue;
    for (const p of node.allowed_paths) {
      const rel = String(p || '').trim();
      if (!rel) continue;
      touchedFiles.add(rel);
      // Skip cache reuse for non-active nodes (state may change). Active nodes
      // with unchanged allowed_paths reuse cached metadata to keep rebuild fast.
      const cacheKey = `${node.id}:${node.updated_at || ''}:${track}:${depth}`;
      const cachedEntry = cachedFiles[rel];
      if (cachedEntry && cachedEntry._cache_key === cacheKey) {
        index.files[rel] = { ...cachedEntry };
        delete index.files[rel]._cache_key;
        index.files[rel]._cache_key = cacheKey;
        continue;
      }
      index.files[rel] = {
        track,
        mainline_id,
        depth,
        node_id: node.id,
        program,
        _cache_key: cacheKey,
      };
    }
  }

  writeJson(indexPath, index);
  return index;
}

function driftAcceptancesPath(root) {
  return path.join(root, '.governance', 'drift-acceptances.json');
}

function loadDriftAcceptances(root) {
  const data = readJsonSafe(driftAcceptancesPath(root));
  if (!data || !Array.isArray(data.acceptances)) {
    return { version: 1, acceptances: [] };
  }
  return { version: 1, acceptances: data.acceptances.slice() };
}

function saveDriftAcceptances(root, data) {
  const payload = {
    version: 1,
    generated_at: new Date().toISOString(),
    acceptances: data.acceptances,
  };
  writeJson(driftAcceptancesPath(root), payload);
}

function currentActiveMainlineId(resolved) {
  const r = resolved.find((e) => e.track === 'mainline' && e.depth === 0 && isActiveStatus(e.node.status));
  return r ? String(r.node.id) : null;
}

function isAcceptanceEffective(acc, mainlineId, nowMs) {
  if (!acc || acc.status !== 'active') return false;
  if (String(acc.mainline_at_accept || null) !== String(mainlineId || null)) return false;
  if (acc.expires_at == null || acc.expires_at === '') return true; // permanent
  const exp = Date.parse(acc.expires_at);
  if (Number.isNaN(exp)) return false; // malformed expiry = not effective (safer)
  return exp > nowMs;
}

function newAcceptanceId(existing) {
  const now = new Date();
  const ymd = now.toISOString().slice(0, 10); // YYYY-MM-DD
  const prefix = `drift-${ymd}-`;
  let max = 0;
  for (const a of existing) {
    if (a && typeof a.id === 'string' && a.id.startsWith(prefix)) {
      const tail = Number(a.id.slice(prefix.length));
      if (!Number.isNaN(tail) && tail > max) max = tail;
    }
  }
  return `${prefix}${String(max + 1).padStart(3, '0')}`;
}
module.exports = { buildFileToTrackIndex, driftAcceptancesPath, loadDriftAcceptances, saveDriftAcceptances, currentActiveMainlineId, isAcceptanceEffective, newAcceptanceId };
