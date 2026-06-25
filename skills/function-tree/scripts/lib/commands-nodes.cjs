'use strict';

const fs = require('fs');
const path = require('path');

const { STATUSES, SOURCE_EDIT_STATUSES, STEWARD_NODE_TYPES, NODE_TYPE_ALIASES, STEWARD_BOUNDARIES, FEATURE_STATUS, normalizeFeatureStatus, isDeclaredFeatureStatus, isVerifiedFeatureStatus } = require('./constants.cjs');
const { refreshFunctionTreeDoc, writeFunctionTreeDoc, backupFunctionTreeDoc, extractProjectNotes, extractExistingFunctionTreeBody, extractPreservedPreviousFunctionTree, stripGeneratedFunctionTreeSection, stripFunctionTreeTitle, stripGeneratedDocPreamble, looksLikeFunctionTreeBody, isRefreshableGeneratedFunctionTreeBody, defaultProjectNotes, renderFunctionTreeDoc, renderDefaultFunctionTreeBody } = require('./doc.cjs');
const { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates } = require('./gates.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./io-utils.cjs');
const { TRACK_VALUES, loadNodes, saveNodes, loadAllNodes, loadAllNodesResolved, loadTargetNode, requireProgramDir, appendTreeNode, syncTreeMd, assertTransitionAllowed, staleEvidenceReason, nextGateFor, renderTaskCard, yamlList, yamlString, latestEvidenceHead, normalizeTrack, normalizeDepth, normalizeStewardNodeType, resolveMainlineFields, resolveMainlineRoot, isActiveStatus, stewardTypeFor } = require('./nodes.cjs');
function initProgram(root, args, flags) {
  // Program defaults to basename(root) so callers can run `ft init` with no args.
  // Validation still applies to the resolved name — if basename(root) contains
  // invalid chars (spaces, etc.), the user must pass an explicit <program>.
  let program = args[0];
  if (!program) {
    program = path.basename(path.resolve(root));
    // Fall back to a sanitized form only when the dir name is a valid id;
    // otherwise we fail so the user picks an explicit name rather than
    // silently getting something unexpected.
  }
  if (!program || !/^[a-z0-9][a-z0-9._-]*$/i.test(program)) {
    fail('init requires <program> using letters, numbers, dot, dash, or underscore (or run inside a directory whose name matches)', 2);
  }

  // ref defaults to the program id when omitted; 'unlinked' is kept as a
  // legacy sentinel only for explicit `--ref unlinked` invocations.
  const ref = String(flags.ref || program);
  const description = String(flags.description || '');
  const gov = path.join(root, '.governance');
  const programs = path.join(gov, 'programs');
  const programDir = path.join(programs, program);
  const cardsDir = path.join(programDir, 'cards');
  const head = gitHead(root);
  const createdAt = new Date().toISOString();

  ensureDir(cardsDir);

  const treePath = path.join(programDir, 'tree.md');
  const nodesPath = path.join(programDir, 'nodes.json');
  const templatePath = path.join(skillDir(), 'templates', 'program-tree.md');
  if (!fs.existsSync(treePath)) {
    const rendered = renderTemplate(readFile(templatePath), {
      PROGRAM_NAME: program,
      FT_REF: ref,
      CREATED_AT: createdAt,
      CURRENT_HEAD: head,
      DESCRIPTION: description,
    });
    writeFile(treePath, rendered);
  }
  if (!fs.existsSync(nodesPath)) writeJson(nodesPath, []);

  const activePath = path.join(gov, 'active-gates.json');
  if (!fs.existsSync(activePath)) {
    writeJson(activePath, {
      schema_version: 1,
      updated_at: createdAt,
      gates: [],
    });
  }
  syncActiveGates(root);
  const docResult = flags['no-doc'] ? null : writeFunctionTreeDoc(root, { program, ref, description });

  const output = [
    `created program: ${program}`,
    `root: ${root}`,
    `tree: ${rel(root, treePath)}`,
    `nodes: ${rel(root, nodesPath)}`,
  ];
  if (docResult) {
    output.push(`function_tree_doc: ${rel(root, docResult.docPath)}`);
    if (docResult.backupPath) output.push(`function_tree_backup: ${rel(root, docResult.backupPath)}`);
    // Discovery Summary — human-readable overview so users don't have to open
    // FUNCTION_TREE.md to see what was found. (FT_SKILL_REVIEW P1#8.)
    const summary = renderDiscoverySummary(docResult.info);
    if (summary) output.push('', summary);
  }
  output.push('', `next: run \`ft suggest-nodes\` to promote candidates into planning nodes, or record evidence then prepare authorization before source edits`);
  console.log(output.join('\n'));
}

// Discovery Summary — concise overview of what `ft init` found, grouped by
// evidence strength. Mirrors the recommendations in FT_SKILL_REVIEW.md P1#8 so
// users go from "462 lines of noise" to "5-10 lines of next-step guidance".
function renderDiscoverySummary(info) {
  if (!info) return '';
  const fc = info.featureCandidates || [];
  const pc = info.plannedCandidates || [];
  const modules = info.sourceModules || [];

  // Group feature candidates by their normalized status. Iterating the status
  // enum (instead of hard-coding labels) means new status values surface here
  // automatically, and the labels remain correct if the skill ever localizes
  // them.
  const byStatus = new Map();
  for (const c of fc) {
    const s = normalizeFeatureStatus(c && c.status);
    byStatus.set(s, (byStatus.get(s) || 0) + 1);
  }
  const declaredCount = byStatus.get(FEATURE_STATUS.DECLARED) || 0;
  const codePresentCount = byStatus.get(FEATURE_STATUS.CODE_PRESENT) || 0;
  const unverifiedCount = byStatus.get(FEATURE_STATUS.UNVERIFIED) || 0;
  const plannedCount = byStatus.get(FEATURE_STATUS.PLANNED) || 0;
  const otherCount = Math.max(0, fc.length - declaredCount - codePresentCount - unverifiedCount - plannedCount);

  const lines = [
    `Discovery Summary:`,
    `  Feature candidates: ${fc.length} total`,
    `    - ${FEATURE_STATUS.DECLARED} (README/CHANGELOG-claimed): ${declaredCount}`,
    `    - ${FEATURE_STATUS.CODE_PRESENT} (route/model evidence): ${codePresentCount}`,
    `    - ${FEATURE_STATUS.PLANNED} (TODO/roadmap): ${plannedCount}`,
    `    - ${FEATURE_STATUS.UNVERIFIED} (single-spec/grep): ${unverifiedCount}`,
  ];
  if (otherCount > 0) lines.push(`    - other: ${otherCount}`);
  lines.push(`  Source modules discovered: ${modules.length}`);
  if (pc.length) lines.push(`  Planned candidates: ${pc.length}`);
  if (info.publicApiEntries) lines.push(`  Public API entries: ${info.publicApiEntries.length}`);
  if (info.uiEntries) lines.push(`  UI/page routes: ${info.uiEntries.length}`);
  if (info.apiEntries) lines.push(`  API routes: ${info.apiEntries.length}`);

  // FT_REVIEW E1 — Coverage Hints. Numbers without context ("24 modules
  // discovered") create a false sense of completeness. Show each auto-discovered
  // candidate source alongside its promotion hint so users see what was missed
  // and the exact command that promotes it.
  const cov = info.coverage || {};
  if (cov.subpackages !== undefined || cov.readmeHeadings !== undefined
      || cov.entrypointsTotal !== undefined || cov.worktree !== undefined
      || cov.changelog !== undefined || cov.gateCandidates !== undefined) {
    lines.push('', 'Coverage hints:');
    if (cov.subpackages !== undefined) {
      lines.push(`  pkg-root subpackages: ${cov.subpackages} found (hint: \`ft suggest-nodes <program>\` to promote)`);
    }
    if (cov.readmeHeadings !== undefined) {
      lines.push(`  README H2/H3 headings: ${cov.readmeHeadings} found (hint: \`ft suggest-nodes <program>\`)`);
    }
    if (cov.entrypointsTotal !== undefined) {
      const verified = cov.entrypointsVerified || 0;
      const unverified = Math.max(0, cov.entrypointsTotal - verified);
      lines.push(`  Manifest entry-points: ${cov.entrypointsTotal} found (${verified} verified, ${unverified} 待核验)`);
    }
    if (cov.changelog !== undefined && cov.changelog > 0) {
      lines.push(`  CHANGELOG releases: ${cov.changelog} found (hint: \`ft suggest-nodes <program>\`)`);
    }
    if (cov.worktree !== undefined && cov.worktree > 0) {
      lines.push(`  Worktree untracked/staged: ${cov.worktree} found (strongest 待实现 signal)`);
    }
    if (cov.gateCandidates !== undefined && cov.gateCandidates > 0) {
      lines.push(`  Verification gate candidates: ${cov.gateCandidates} (hint: \`/ft:authorize --commit-gate @ci\`)`);
    }
  }
  return lines.join('\n');
}

function newNode(root, args, flags) {
  const program = args[0];
  const id = args[1];
  if (!program || !id) fail('new-node requires <program> <node-id>', 2);
  const title = one(flags, 'title') || id;
  const ref = one(flags, 'ref') || 'unlinked';
  const programDir = requireProgramDir(root, program);
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  if (nodes.some((node) => node.id === id)) fail(`node already exists: ${program}/${id}`, 2);

  const now = new Date().toISOString();
  const typeInput = one(flags, 'type') || 'decision';
  const node = {
    id,
    title,
    // canonical steward type drives the state machine; aliases like "capability"
    // normalize to one of the 6 canonical types (evidence/decision/authorization/
    // implementation/closeout/external) — see NODE_TYPE_ALIASES in constants.cjs.
    node_type: normalizeStewardNodeType(typeInput),
    // Preserve the user's original --type input (before alias normalization) so
    // business-semantic labels (capability, feature, bug, refactor, ...) survive
    // round-trip through the state machine. This fixes the audit gap where
    // `--type capability` silently became `external` and lost intent.
    node_type_input: typeInput,
    owner_lane: one(flags, 'owner-lane') || program,
    parent: one(flags, 'parent') || '',
    status: 'planning',
    function_tree_ref: ref,
    current_head: gitHead(root),
    freshness: one(flags, 'freshness') || 'current-head',
    source_edits_authorized: false,
    evidence: [],
    allowed_paths: [],
    forbidden_paths: [],
    non_goals: [],
    next_gate: 'collect baseline evidence',
    blocker_reason: null,
    unblock_target_state: null,
    created_at: now,
    updated_at: now,
  };
  // Phase 1: optional mainline layering fields. Only written when explicitly provided.
  const trackRaw = one(flags, 'track');
  if (trackRaw) node.track = normalizeTrack(trackRaw);
  const mainlineIdRaw = one(flags, 'mainline-id');
  if (mainlineIdRaw) node.mainline_id = mainlineIdRaw;
  const depthRaw = one(flags, 'depth');
  if (depthRaw !== undefined && depthRaw !== '') {
    const n = Number(depthRaw);
    if (Number.isInteger(n) && n >= 0) node.depth = n;
  }
  nodes.push(node);
  saveNodes(nodesPath, nodes);
  appendTreeNode(programDir, node);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`created node: ${program}/${id}`);
}

function newNodeBatch(root, args, flags) {
  const program = args[0];
  if (!program) fail('new-node-batch requires <program>', 2);
  const fromDirs = one(flags, 'from-dirs');
  if (!fromDirs) fail('new-node-batch requires --from-dirs <dir>', 2);
  const programDir = requireProgramDir(root, program);
  const nodesPath = path.join(programDir, 'nodes.json');
  const nodes = loadNodes(nodesPath);
  const existing = new Set(nodes.map((n) => n.id));

  const absRoot = path.resolve(root, fromDirs);
  if (!fs.existsSync(absRoot)) fail(`--from-dirs not found: ${absRoot}`, 2);

  const idPrefix = one(flags, 'id-prefix') || '';
  const pattern = one(flags, 'pattern') || '*';
  const parent = one(flags, 'parent') || '';
  const trackRaw = one(flags, 'track');
  const mainlineId = one(flags, 'mainline-id');
  const depthRaw = one(flags, 'depth');
  const typeRaw = one(flags, 'type') || 'external';
  const dryRun = Boolean(flags['dry-run']);

  const subdirs = fs
    .readdirSync(absRoot, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .filter((name) => minimatchSimple(name, pattern))
    .sort();

  if (!subdirs.length) {
    console.log(`no subdirectories matched under ${absRoot}`);
    return;
  }

  const created = [];
  const skipped = [];
  const now = new Date().toISOString();
  for (const name of subdirs) {
    const id = `${idPrefix}${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    if (existing.has(id)) {
      skipped.push(id);
      continue;
    }
    const node = {
      id,
      title: name,
      node_type: normalizeStewardNodeType(typeRaw),
      node_type_input: typeRaw,
      owner_lane: program,
      parent,
      status: 'planning',
      function_tree_ref: path.join(fromDirs, name),
      current_head: gitHead(root),
      freshness: 'current-head',
      source_edits_authorized: false,
      evidence: [],
      allowed_paths: [],
      forbidden_paths: [],
      non_goals: [],
      next_gate: 'collect baseline evidence',
      blocker_reason: null,
      unblock_target_state: null,
      created_at: now,
      updated_at: now,
    };
    if (trackRaw) node.track = normalizeTrack(trackRaw);
    if (mainlineId) node.mainline_id = mainlineId;
    if (depthRaw !== undefined && depthRaw !== '') {
      const n = Number(depthRaw);
      if (Number.isInteger(n) && n >= 0) node.depth = n;
    }
    nodes.push(node);
    existing.add(id);
    created.push(id);
    if (!dryRun) {
      appendTreeNode(programDir, node);
      upsertActiveGate(root, program, node);
    }
  }

  if (dryRun) {
    console.log(`[dry-run] would create ${created.length} node(s): ${created.join(', ')}`);
    if (skipped.length) console.log(`[dry-run] skipped ${skipped.length} existing: ${skipped.join(', ')}`);
    return;
  }

  saveNodes(nodesPath, nodes);
  syncActiveGates(root);
  console.log(`created ${created.length} node(s): ${created.join(', ')}`);
  if (skipped.length) console.log(`skipped ${skipped.length} existing: ${skipped.join(', ')}`);
}

function reparentNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'reparent');
  const parent = one(flags, 'parent');
  const mainlineId = one(flags, 'mainline-id');
  const depthRaw = one(flags, 'depth');
  const trackRaw = one(flags, 'track');
  if (!parent && !mainlineId && depthRaw === undefined && !trackRaw) {
    fail('reparent requires at least one of --parent / --mainline-id / --depth / --track', 2);
  }

  if (parent !== undefined) node.parent = parent;
  if (mainlineId !== undefined) node.mainline_id = mainlineId || '';
  if (depthRaw !== undefined && depthRaw !== '') {
    const n = Number(depthRaw);
    if (!Number.isInteger(n) || n < 0) fail(`invalid --depth: ${depthRaw}`, 2);
    node.depth = n;
  }
  if (trackRaw) node.track = normalizeTrack(trackRaw);
  node.updated_at = new Date().toISOString();

  saveNodes(nodesPath, nodes);
  syncTreeMd(programDir);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`reparented: ${program}/${id} (parent=${node.parent || '-'}, track=${node.track || 'untracked'}, depth=${node.depth !== undefined ? node.depth : 'inherit'})`);
}

function observeNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'observe');
  const evidence = one(flags, 'evidence');
  if (!evidence) fail('observe requires --evidence <path-or-note>', 2);
  const head = gitHead(root);
  const record = {
    kind: one(flags, 'kind') || 'baseline',
    path: evidence,
    note: one(flags, 'note') || '',
    current_head: head,
    recorded_at: new Date().toISOString(),
  };
  if (!Array.isArray(node.evidence)) node.evidence = [];
  node.evidence.push(record);
  node.current_head = head;
  if (node.status === 'planning') node.status = 'evidence-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'prepare decision or authorization';
  node.updated_at = record.recorded_at;
  saveNodes(nodesPath, nodes);
  syncTreeMd(programDir);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`observed evidence for: ${program}/${id}`);
}

function authorizeNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'authorize');
  if (!['evidence-prepared', 'decision-prepared', 'authorization-prepared'].includes(node.status)) {
    fail(`authorize requires evidence-prepared or decision-prepared status, got ${node.status}`, 2);
  }
  const allowed = many(flags, 'allowed');
  const nonGoals = many(flags, 'non-goal');
  const commitGates = many(flags, 'commit-gate');
  const closeoutGates = many(flags, 'closeout-gate');
  if (!allowed.length) fail('authorize requires at least one --allowed path', 2);
  if (!nonGoals.length) fail('authorize requires at least one --non-goal', 2);
  if (!commitGates.length) fail('authorize requires at least one --commit-gate', 2);
  if (!closeoutGates.length) fail('authorize requires at least one --closeout-gate', 2);

  node.allowed_paths = allowed;
  node.forbidden_paths = many(flags, 'forbidden');
  node.non_goals = nonGoals;
  node.acceptance = {
    commit_gate: commitGates,
    closeout_gate: closeoutGates,
  };
  node.status = 'authorization-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'review and approve implementation authorization';
  node.updated_at = new Date().toISOString();

  const cardsDir = path.join(programDir, 'cards');
  ensureDir(cardsDir);
  writeFile(path.join(cardsDir, `${safeFileName(id)}.yaml`), renderTaskCard(node));
  saveNodes(nodesPath, nodes);
  syncTreeMd(programDir);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`authorized draft: ${program}/${id}`);
}

function transitionNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'transition');
  const to = one(flags, 'to');
  if (!to || !STATUSES.has(to)) fail('transition requires --to <valid-status>', 2);
  assertTransitionAllowed(root, node, to, flags);

  const from = node.status;
  node.status = to;
  node.source_edits_authorized = SOURCE_EDIT_STATUSES.has(to);
  if (to === 'blocked') {
    node.blocker_reason = one(flags, 'blocker');
    node.unblock_target_state = one(flags, 'unblock-target-state');
    node.next_gate = `unblock to ${node.unblock_target_state}`;
  } else {
    node.blocker_reason = null;
    node.unblock_target_state = null;
    node.next_gate = nextGateFor(to);
  }
  if (!Array.isArray(node.transitions)) node.transitions = [];
  node.transitions.push({
    from,
    to,
    note: one(flags, 'note') || '',
    current_head: gitHead(root),
    transitioned_at: new Date().toISOString(),
  });
  node.updated_at = new Date().toISOString();
  saveNodes(nodesPath, nodes);
  syncTreeMd(programDir);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`transitioned ${program}/${id}: ${from} -> ${to}`);
}

function closeoutNode(root, args, flags) {
  const { program, id, nodesPath, nodes, node, programDir } = loadTargetNode(root, args, 'closeout');
  if (node.status !== 'implementation-landed') {
    fail(`closeout requires implementation-landed status, got ${node.status}`, 2);
  }
  const summary = one(flags, 'summary');
  if (!summary) fail('closeout requires --summary <path-or-note>', 2);
  node.closeout = {
    summary,
    compatibility: one(flags, 'compatibility') || '',
    gates: many(flags, 'gate'),
    current_head: gitHead(root),
    prepared_at: new Date().toISOString(),
  };
  node.status = 'closeout-prepared';
  node.source_edits_authorized = false;
  node.next_gate = 'review closeout and close node';
  node.updated_at = node.closeout.prepared_at;
  saveNodes(nodesPath, nodes);
  syncTreeMd(programDir);
  upsertActiveGate(root, program, node);
  syncActiveGates(root);
  console.log(`prepared closeout: ${program}/${id}`);
}

// suggest-nodes — turn FUNCTION_TREE.md's auto-discovered candidates into a
// reviewable list of `new-node` suggestions. Closes the gap from FT_SKILL_REVIEW
// P1#8: instead of leaving the user with "462 lines of noise + 0 nodes", this
// emits one concrete node draft per high-value candidate (README product
// features → mainline depth 0; route/model clusters → backlog depth 1) and
// offers `--yes` to batch-create them.
//
// The function deliberately does NOT auto-import. The mainline methodology
// requires human review of every planning node — `--dry-run` is the default.
function cmdSuggestNodes(root, args, flags) {
  const program = args[0];
  if (!program) fail('suggest-nodes requires <program>', 2);
  const programDir = requireProgramDir(root, program);
  require('./doc.cjs'); // ensure collectProjectInfo path is loadable indirectly
  // Lazy require: collectProjectInfo lives in scan-project.cjs; require it here
  // so commands-nodes.cjs does not pay the cost at module load time.
  const { collectProjectInfo } = require('./scan-project.cjs');
  const info = collectProjectInfo(root);
  // Candidates use `name` as the primary label; fall back to `title` for safety.
  const candidates = (info.featureCandidates || []).filter((c) => c && (c.name || c.title));

  // Bucket candidates by evidence strength using the skill-wide status helpers
  // from constants.cjs. Only evidence-backed candidates (declared / code-present
  // / planned) become node suggestions; 待核验 candidates stay as evidence
  // pointers because they don't yet have enough signal to deserve a planning
  // node. The threshold is stack-agnostic — it's about evidence strength.
  const seen = new Set();
  const suggestions = [];
  let mainlineOrder = 0;
  let backlogOrder = 0;
  for (const c of candidates) {
    const rawName = String(c.name || c.title || '').trim();
    if (!rawName) continue;
    const key = rawName.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const declared = isDeclaredFeatureStatus(c.status);
    // Only evidence-backed statuses become node suggestions. "Declared" gets
    // mainline depth 0 (product root); other verified statuses get backlog
    // depth 1 (capability candidate). Skip 待核验 entirely — too noisy.
    if (!isVerifiedFeatureStatus(c.status)) continue;
    const track = declared ? 'mainline' : 'backlog';
    const depth = declared ? 0 : 1;
    const order = declared ? ++mainlineOrder : ++backlogOrder;
    const idPrefix = declared ? 'M' : 'B';
    const id = `${idPrefix}${String(order).padStart(2, '0')}`;
    suggestions.push({
      id,
      title: rawName,
      track,
      depth,
      type: declared ? 'feature' : 'capability',
      evidence: c.evidence || '',
      status_label: normalizeFeatureStatus(c.status),
    });
  }

  // Cap output to keep the suggestion list scannable.
  const cap = 30;
  const trimmed = suggestions.slice(0, cap);

  if (flags['dry-run'] || !flags.yes) {
    const lines = [
      `Suggested nodes for program \`${program}\` (${trimmed.length} of ${suggestions.length} candidates, dry-run):`,
      '',
      '| id | title | track | depth | type | status | evidence |',
      '|---|---|---|---|---|---|---|',
    ];
    for (const s of trimmed) {
      lines.push(`| ${s.id} | ${escapeCell(s.title)} | ${s.track} | ${s.depth} | ${s.type} | ${s.status_label} | ${escapeCell(s.evidence)} |`);
    }
    lines.push('');
    lines.push('Review the list, then run `ft suggest-nodes <program> --yes` to create all entries,');
    lines.push('or pick specific ones with `ft new-node <program> <id> --title "..." --track <t> --depth <n>`.');
    console.log(lines.join('\n'));
    return;
  }

  // --yes: batch import. Reuse newNode's logic by calling it with synthesized flags.
  const nodesPath = path.join(programDir, 'nodes.json');
  const existing = loadNodes(nodesPath);
  const existingIds = new Set(existing.map((n) => n.id));
  let created = 0;
  let skipped = 0;
  for (const s of trimmed) {
    if (existingIds.has(s.id)) { skipped += 1; continue; }
    try {
      newNode(root, [program, s.id], {
        title: s.title,
        type: s.type,
        track: s.track,
        depth: String(s.depth),
        ref: program,
      });
      created += 1;
      existingIds.add(s.id);
    } catch (e) {
      console.error(`skipped ${s.id}: ${e.message}`);
      skipped += 1;
    }
  }
  console.log(`suggested-nodes import: created ${created}, skipped ${skipped}`);
}

// promote-* — source-scoped variant of suggest-nodes (FT_REVIEW S1).
// Rather than dumping every auto-discovered candidate into one huge list,
// each promote-* command filters to a single `source` so the user can work
// through one discovery channel at a time. The mapping:
//
//   promote-pkgs        → source 'pkg-root'        (盲区 A: pkg-root subpackages)
//   promote-readme      → source 'readme-heading'  (盲区 B: README H2/H3)
//   promote-entrypoints → source 'entrypoint'      (盲区 C: manifest entry-points)
//   promote-changelog   → source 'changelog'       (E5: CHANGELOG release bullets)
//   promote-untracked   → source 'untracked'       (盲区 D: git worktree ??/A)
//
// All commands share the same dry-run / --yes UX as suggest-nodes. Planned
// candidates (only promote-untracked today) land on backlog depth 1; the rest
// follow suggest-nodes's evidence-strength rule (declared → mainline d=0,
// other verified → backlog d=1).
const PROMOTE_SOURCES = {
  'promote-pkgs':        { source: 'pkg-root',       label: 'pkg-root subpackages' },
  'promote-readme':      { source: 'readme-heading', label: 'README H2/H3 headings' },
  'promote-entrypoints': { source: 'entrypoint',     label: 'manifest entry-points' },
  'promote-changelog':   { source: 'changelog',      label: 'CHANGELOG release bullets' },
  'promote-untracked':   { source: 'untracked',      label: 'worktree untracked/staged files' },
};

function cmdPromote(root, args, flags) {
  const command = flags.__promoteCommand;
  if (!command || !PROMOTE_SOURCES[command]) {
    fail(`promote: unknown variant "${command}"`, 2);
  }
  const program = args[0];
  if (!program) fail(`${command} requires <program>`, 2);
  const { source, label } = PROMOTE_SOURCES[command];
  const programDir = requireProgramDir(root, program);

  const { collectProjectInfo } = require('./scan-project.cjs');
  const info = collectProjectInfo(root);
  const pool = [
    ...(info.featureCandidates || []),
    ...(info.plannedCandidates || []),
  ].filter((c) => c && (c.name || c.title) && c.source === source);

  // Same bucketing rule as cmdSuggestNodes: declared → mainline d=0, other
  // verified → backlog d=1, 待核验/待实现 → backlog d=1 with a lighter type.
  // For untracked (待实现), every candidate becomes a backlog node — these
  // are the user's in-progress work and belong on the backlog.
  const seen = new Set();
  const suggestions = [];
  let mainlineOrder = 0;
  let backlogOrder = 0;
  for (const c of pool) {
    const rawName = String(c.name || c.title || '').trim();
    if (!rawName) continue;
    const key = rawName.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const isPlanned = c.status === FEATURE_STATUS.PLANNED;
    const declared = isDeclaredFeatureStatus(c.status);
    if (!isVerifiedFeatureStatus(c.status) && !isPlanned) continue;
    const track = (declared || isPlanned) && !isDeclaredFeatureStatus(c.status) ? 'backlog' : (declared ? 'mainline' : 'backlog');
    const depth = declared ? 0 : 1;
    const order = declared ? ++mainlineOrder : ++backlogOrder;
    const idPrefix = declared ? 'M' : 'B';
    const id = `${idPrefix}${String(order).padStart(2, '0')}`;
    suggestions.push({
      id,
      title: rawName,
      track,
      depth,
      type: declared ? 'feature' : 'capability',
      evidence: c.evidence || '',
      status_label: normalizeFeatureStatus(c.status),
    });
  }

  const cap = 30;
  const trimmed = suggestions.slice(0, cap);

  if (flags['dry-run'] || !flags.yes) {
    const lines = [
      `Promote \`${label}\` for program \`${program}\` (${trimmed.length} of ${suggestions.length} candidates, dry-run):`,
      '',
      '| id | title | track | depth | type | status | evidence |',
      '|---|---|---|---|---|---|---|',
    ];
    for (const s of trimmed) {
      lines.push(`| ${s.id} | ${escapeCell(s.title)} | ${s.track} | ${s.depth} | ${s.type} | ${s.status_label} | ${escapeCell(s.evidence)} |`);
    }
    lines.push('');
    lines.push(`Review the list, then run \`ft ${command} <program> --yes\` to create all entries,`);
    lines.push('or pick specific ones with `ft new-node <program> <id> --title "..." --track <t> --depth <n>`.');
    console.log(lines.join('\n'));
    return;
  }

  // --yes: batch import.
  const nodesPath = path.join(programDir, 'nodes.json');
  const existing = loadNodes(nodesPath);
  const existingIds = new Set(existing.map((n) => n.id));
  let created = 0;
  let skipped = 0;
  for (const s of trimmed) {
    if (existingIds.has(s.id)) { skipped += 1; continue; }
    try {
      newNode(root, [program, s.id], {
        title: s.title,
        type: s.type,
        track: s.track,
        depth: String(s.depth),
        ref: program,
      });
      created += 1;
      existingIds.add(s.id);
    } catch (e) {
      console.error(`skipped ${s.id}: ${e.message}`);
      skipped += 1;
    }
  }
  console.log(`${command} import: created ${created}, skipped ${skipped}`);
}
module.exports = { initProgram, newNode, newNodeBatch, reparentNode, observeNode, authorizeNode, transitionNode, closeoutNode, cmdSuggestNodes, cmdPromote, PROMOTE_SOURCES };
