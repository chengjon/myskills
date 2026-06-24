'use strict';

const fs = require('fs');
const path = require('path');
function list(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}

function many(flags, key) {
  if (!Object.prototype.hasOwnProperty.call(flags, key)) return [];
  const value = flags[key];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (value === true || value == null) return [];
  return [String(value)].filter(Boolean);
}

function one(flags, key) {
  if (!Object.prototype.hasOwnProperty.call(flags, key)) return '';
  const value = flags[key];
  if (Array.isArray(value)) return String(value[value.length - 1] || '');
  if (value === true || value == null) return '';
  return String(value);
}

function fail(message, code) {
  console.error(`ERROR ${message}`);
  process.exit(code);
}

function escapeCell(value) {
  return String(value == null ? '-' : value).replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function globToRegExp(glob) {
  let out = '^';
  for (let i = 0; i < glob.length; i += 1) {
    const ch = glob[i];
    const next = glob[i + 1];
    if (ch === '*' && next === '*') {
      out += '.*';
      i += 1;
    } else if (ch === '*') {
      out += '[^/]*';
    } else if (ch === '?') {
      out += '[^/]';
    } else {
      out += ch.replace(/[|\\{}()[\]^$+?.]/g, '\\$&');
    }
  }
  out += '$';
  return new RegExp(out);
}

function matches(pattern, file) {
  if (!pattern) return false;
  const normalizedPattern = pattern.replace(/\\/g, '/');
  const normalizedFile = file.replace(/\\/g, '/');
  if (normalizedPattern === normalizedFile) return true;
  if (normalizedPattern.endsWith('/')) return normalizedFile.startsWith(normalizedPattern);
  const re = globToRegExp(normalizedPattern);
  return re.test(normalizedFile);
}

function gateName(gate) {
  return `${gate.program || 'program'}/${gate.id || gate.node_id || 'node'}`;
}

function firstExistingPath(root, relativePaths) {
  for (const relativePath of relativePaths) {
    const absolutePath = path.join(root, relativePath);
    if (fs.existsSync(absolutePath)) return absolutePath;
  }
  return '';
}

function formatList(values) {
  return values.length ? values.map((value) => `\`${value}\``).join(', ') : 'none detected';
}

function existingPaths(root, candidates) {
  return candidates.filter((candidate) => fs.existsSync(path.join(root, candidate)));
}

function parseDuration(spec) {
  const m = /^(\d+)\s*([smhdw])$/i.exec(String(spec || '').trim());
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n) || n < 0) return null;
  const unit = m[2].toLowerCase();
  const mult = { s: 1, m: 60, h: 3600, d: 86400, w: 604800 }[unit];
  return Math.floor(n * mult);
}

function expiryFromNow(secs) {
  if (secs == null || secs <= 0) return null;
  return new Date(Date.now() + secs * 1000).toISOString();
}

function titleCase(value) {
  return String(value || '').replace(/\b[A-Za-z0-9]/g, (char) => char.toUpperCase());
}

function markdownTable(headers, rows) {
  const body = rows.length ? rows : [headers.map(() => '-')];
  return [
    `| ${headers.map(escapeCell).join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...body.map((row) => `| ${row.map(escapeCell).join(' | ')} |`),
  ].join('\n');
}

function parseTomlSectionNames(text, sectionName) {
  const names = [];
  let inSection = false;
  for (const line of String(text || '').split(/\r?\n/)) {
    if (/^\s*\[\[/.test(line)) inSection = new RegExp(`^\\s*\\[\\[\\s*${escapeRegExp(sectionName)}\\s*\\]\\]`).test(line);
    if (!inSection) continue;
    const match = line.match(/^\s*name\s*=\s*["']([^"']+)["']/);
    if (match) names.push(match[1]);
  }
  return names;
}

function parseTomlTableKeys(text, tableNames) {
  const keys = [];
  let currentTable = '';
  for (const line of String(text || '').split(/\r?\n/)) {
    const tableMatch = line.match(/^\s*\[\s*([^\]]+)\s*\]\s*$/);
    if (tableMatch) {
      currentTable = tableMatch[1].trim();
      continue;
    }
    if (!tableNames.includes(currentTable)) continue;
    const keyMatch = line.match(/^\s*([A-Za-z0-9_.-]+)\s*=/);
    if (keyMatch) keys.push(keyMatch[1]);
  }
  return keys;
}

function matchBracedDict(source, varName) {
  // Find VARNAME = { or VARNAME: type = { and extract the content between balanced braces
  // Handles: _COMMANDS = { ... } and _COMMANDS: dict[str, type] = { ... }
  const startMatch = source.match(new RegExp(`${escapeRegExp(varName)}\\s*[:=][\\s\\S]*?=\\s*\\{`));
  if (!startMatch) return null;
  // Find the actual '{' in the match
  const braceOffset = startMatch[0].lastIndexOf('{');
  const startIdx = startMatch.index + braceOffset;
  let depth = 0;
  let i = startIdx;
  for (; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}') {
      depth--;
      if (depth === 0) break;
    }
  }
  if (depth !== 0) return null;
  return source.substring(startIdx + 1, i);
}

function minimatchSimple(name, pattern) {
  if (!pattern || pattern === '*' || pattern === '') return true;
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`).test(name);
}

function slugifyCandidate(name, maxLength = 32) {
  const text = String(name || '').toLowerCase();
  // strip emojis and non-word noise, keep letters/digits/spaces/hyphens
  const cleaned = text
    .replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}]/gu, '')
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  if (!cleaned) return '';
  // truncate on word boundary
  const truncated = cleaned.length > maxLength
    ? cleaned.slice(0, maxLength).replace(/-[^-]*$/, '')
    : cleaned;
  return `cand-${truncated || 'item'}`;
}

function isTestSourceFile(file) {
  // Test directories: test/, tests/, __tests__/, spec/, specs/, fixtures/, mocks/
  if (/(^|[\/\\])(tests?|__tests__|spec|specs|fixtures?|mocks?)[\/\\]/i.test(file)) return true;
  // JS/TS convention: foo.test.ts, foo.spec.tsx (covers co-located tests like src/foo.test.ts)
  if (/\.(test|spec)\./i.test(file)) return true;
  // Python/general prefix convention: test_foo.py, test-foo.py, test.foo.py
  if (/(^|[\/\\])(test|spec)[_.-][^\/\\]*$/i.test(file)) return true;
  // Python/general suffix convention: foo_test.py, foo-spec.ts
  if (/(^|[\/\\])[^\/\\]*_(test|spec)\.[^\/\\]+$/i.test(file)) return true;
  return false;
}
module.exports = { list, many, one, fail, escapeCell, escapeRegExp, globToRegExp, matches, gateName, firstExistingPath, formatList, existingPaths, parseDuration, expiryFromNow, titleCase, markdownTable, parseTomlSectionNames, parseTomlTableKeys, matchBracedDict, minimatchSimple, isTestSourceFile, slugifyCandidate };
