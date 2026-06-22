'use strict';

const fs = require('fs');
const path = require('path');

const { cmdDriftCheck, cmdAcceptDrift, cmdRevokeDrift } = require('./lib/commands-drift.cjs');
const { cmdSessionStart, cmdPreEdit } = require('./lib/commands-hooks.cjs');
const { initProgram, newNode, newNodeBatch, reparentNode, observeNode, authorizeNode, transitionNode, closeoutNode } = require('./lib/commands-nodes.cjs');
const { printStatus, printGate, cmdConfig, cmdMainline, cmdLocate, cmdMap, installGuard, repairActiveGates } = require('./lib/commands-query.cjs');
const { refreshFunctionTreeDoc, writeFunctionTreeDoc, backupFunctionTreeDoc, extractProjectNotes, extractExistingFunctionTreeBody, extractPreservedPreviousFunctionTree, stripGeneratedFunctionTreeSection, stripFunctionTreeTitle, stripGeneratedDocPreamble, looksLikeFunctionTreeBody, isRefreshableGeneratedFunctionTreeBody, defaultProjectNotes, renderFunctionTreeDoc, renderDefaultFunctionTreeBody } = require('./lib/doc.cjs');
const { activeGateFromNode, upsertActiveGate, syncActiveGates, loadActiveGates, normalizeGates } = require('./lib/gates.cjs');
const { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile } = require('./lib/helpers.cjs');
const { run, readFile, writeFile, readJson, writeJson, readJsonSafe, renderTemplate, ensureDir, skillDir, gitHead, shellQuote, safeFileName, relPath, rel, listStagedFiles, listWorktreeFiles, collectSourceFiles } = require('./lib/io-utils.cjs');
const { syncStewardProfile, buildStewardIndex, stewardNode, stewardEvidence, renderStewardGates, renderStewardEvidenceIndex, renderStewardTrack } = require('./lib/steward.cjs');
const { validateGovernance, validateCapabilityCrossReference, validatePortConflicts, validateDocConsistency, validateNodeLike, validateStewardNode, validateMainlineUnique, validateMainlineOrphan, validateBacklogSwitchLock, validateDepthConsistency, validateAcceptanceExpired, scopeCheck, changedFiles } = require('./lib/validate.cjs');
function main() {
  try {
    const parsed = parseArgs(process.argv.slice(2));
    if (!parsed.command || parsed.command === 'help' || parsed.flags.help) {
      usage(0);
      return;
    }

    const root = resolveRoot(parsed.flags);
    switch (parsed.command) {
      case 'init':
        initProgram(root, parsed.args, parsed.flags);
        break;
      case 'doc':
        refreshFunctionTreeDoc(root);
        break;
      case 'new-node':
        newNode(root, parsed.args, parsed.flags);
        break;
      case 'new-node-batch':
        newNodeBatch(root, parsed.args, parsed.flags);
        break;
      case 'reparent':
        reparentNode(root, parsed.args, parsed.flags);
        break;
      case 'observe':
        observeNode(root, parsed.args, parsed.flags);
        break;
      case 'authorize':
        authorizeNode(root, parsed.args, parsed.flags);
        break;
      case 'transition':
        transitionNode(root, parsed.args, parsed.flags);
        break;
      case 'closeout':
        closeoutNode(root, parsed.args, parsed.flags);
        break;
      case 'install-guard':
        installGuard(root, parsed.flags);
        break;
      case 'repair':
        repairActiveGates(root);
        break;
      case 'status':
        printStatus(root);
        break;
      case 'gate':
        printGate(root, Boolean(parsed.flags.verbose));
        break;
      case 'sync':
        syncActiveGates(root);
        break;
      case 'steward-sync':
        syncStewardProfile(root);
        break;
      case 'validate':
        validateGovernance(root, parsed.flags, parsed.args);
        break;
      case 'scope-check':
        scopeCheck(root, parsed.flags);
        break;
      case 'mainline':
        cmdMainline(root);
        break;
      case 'locate':
        cmdLocate(root, parsed.args);
        break;
      case 'map':
        cmdMap(root);
        break;
      case 'drift-check':
        cmdDriftCheck(root, parsed.flags, parsed.args);
        break;
      case 'accept-drift':
        cmdAcceptDrift(root, parsed.flags, parsed.args);
        break;
      case 'revoke-drift':
        cmdRevokeDrift(root, parsed.flags, parsed.args);
        break;
      case 'config':
        cmdConfig(root, parsed.args, parsed.flags);
        break;
      case 'session-start':
        cmdSessionStart(root);
        break;
      case 'pre-edit':
        cmdPreEdit(root, parsed.flags);
        break;
      default:
        fail(`unknown command: ${parsed.command}`, 2);
    }
  } catch (error) {
    fail(error && error.message ? error.message : String(error), 1);
  }
}

function usage(code) {
  const text = [
    'Usage:',
    '  ft-governance.cjs init [<program>] [--ref <function-tree-node>] [--description <text>] [--no-doc] [--root <repo>]',
    '       <program> defaults to basename(root); --ref defaults to <program>',
    '  ft-governance.cjs doc [--root <repo>]',
    '  ft-governance.cjs new-node <program> <node-id> --title <text> --ref <function-tree-node> [--type <kind>] [--owner-lane <lane>] [--parent <id>] [--freshness <policy>] [--track <mainline|backlog|optimize|untracked>] [--mainline-id <id>] [--depth <0|1|2|99>] [--root <repo>]',
    '       --type accepts: feature, capability, epic, module, component, bug, task, refactor, spike, evidence, decision, authorization, implementation, closeout, external',
    '  ft-governance.cjs new-node-batch <program> --from-dirs <dir> [--id-prefix <text>] [--pattern <glob>] [--parent <id>] [--track <t>] [--mainline-id <id>] [--depth <n>] [--type <kind>] [--dry-run] [--root <repo>]',
    '       walks <dir> one level deep and creates one node per subdir; node id = <id-prefix><subdir>, title = subdir, ref = <dir>/<subdir>',
    '  ft-governance.cjs reparent <program> <node-id> --parent <id> [--mainline-id <id>] [--depth <n>] [--track <t>] [--root <repo>]',
    '       atomically reparent an existing node without hand-editing nodes.json (fixes parallel-mainline violations)',
    '  ft-governance.cjs observe <program> <node-id> --evidence <path-or-note> [--kind <kind>] [--note <text>] [--root <repo>]',
    '  ft-governance.cjs authorize <program> <node-id> --allowed <path> --non-goal <text> --commit-gate <text> --closeout-gate <text> [--root <repo>]',
    '  ft-governance.cjs transition <program> <node-id> --to <status> [--note <text>] [--blocker <text>] [--unblock-target-state <status>] [--root <repo>]',
    '  ft-governance.cjs closeout <program> <node-id> --summary <path-or-note> [--compatibility <text>] [--gate <text>] [--root <repo>]',
    '  ft-governance.cjs install-guard [--force] [--root <repo>]',
    '  ft-governance.cjs repair [--root <repo>]',
    '  ft-governance.cjs status [--root <repo>]',
    '  ft-governance.cjs gate [--verbose] [--root <repo>]',
    '  ft-governance.cjs sync [--root <repo>]',
    '  ft-governance.cjs steward-sync [--root <repo>]',
    '  ft-governance.cjs validate [full] [--steward] [--root <repo>]',
    '  ft-governance.cjs scope-check [--files a,b,c] [--root <repo>]',
    '  ft-governance.cjs mainline [--root <repo>]',
    '  ft-governance.cjs locate <file-path> [--root <repo>]',
    '  ft-governance.cjs map [--root <repo>]',
    '  ft-governance.cjs drift-check --files <a,b,c> | --staged [--root <repo>]',
    '  ft-governance.cjs accept-drift --reason <text> --files <a,b,c> [--expires <spec>] [--mainline <id|none>] [--by <name>] [--root <repo>]',
    '       --expires default 30d; pass "0" for permanent; format: <N><s|m|h|d|w>',
    '  ft-governance.cjs revoke-drift --id <acceptance-id> [--root <repo>]',
    '  ft-governance.cjs config [list|get|set] [--key <name>] [--value <text>] [--root <repo>]',
    '  ft-governance.cjs session-start [--root <repo>]',
    '  ft-governance.cjs pre-edit --files <a,b,c> [--root <repo>]',
  ].join('\n');
  console.log(text);
  process.exit(code);
}

function parseArgs(argv) {
  if (argv[0] && argv[0].startsWith('--')) {
    return { command: null, args: [], flags: { [argv[0].slice(2)]: true } };
  }
  const out = { command: argv[0], args: [], flags: {} };
  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      out.args.push(token);
      continue;
    }

    const eq = token.indexOf('=');
    if (eq !== -1) {
      assignFlag(out.flags, token.slice(2, eq), token.slice(eq + 1));
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      assignFlag(out.flags, key, next);
      i += 1;
    } else {
      assignFlag(out.flags, key, true);
    }
  }
  return out;
}

function assignFlag(flags, key, value) {
  if (Object.prototype.hasOwnProperty.call(flags, key)) {
    if (Array.isArray(flags[key])) flags[key].push(value);
    else flags[key] = [flags[key], value];
  } else {
    flags[key] = value;
  }
}

function resolveRoot(flags) {
  if (flags.root) return path.resolve(String(flags.root));
  try {
    return run('git', ['rev-parse', '--show-toplevel'], process.cwd()).trim();
  } catch (_) {
    return process.cwd();
  }
}
main();
