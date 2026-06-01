#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');

const skillRoot = path.resolve(__dirname, '..');

function read(relativePath) {
  return fs.readFileSync(path.join(skillRoot, relativePath), 'utf8');
}

test('baseline schema is valid JSON and uses metric-object contract', () => {
  const schema = JSON.parse(read('references/baseline-schema.json'));

  assert.equal(schema.title, 'Tech Debt Baseline');
  assert.ok(schema.required.includes('metrics'));
  assert.ok(schema.required.includes('gate_defaults'));
  assert.equal(schema.properties.metrics.type, 'array');

  const metric = schema.definitions.metric;
  for (const field of [
    'id',
    'dimension',
    'scope',
    'kind',
    'value',
    'unit',
    'tool',
    'command_id',
    'source_roots',
    'excludes',
    'measured_at',
    'git_sha',
    'dirty_worktree',
    'gate',
    'status',
  ]) {
    assert.ok(metric.required.includes(field), `metric contract must require ${field}`);
  }
});

test('skill docs require baseline state discipline and artifact self-check', () => {
  const skill = read('SKILL.md');

  assert.match(skill, /If a baseline exists, every non-`init-baseline` report MUST compare against it/);
  assert.match(skill, /Markdown is a presentation layer/);
  assert.match(skill, /Each metric in JSON MUST be an object/);
  assert.match(skill, /Artifact Self-Check/);
  assert.match(skill, /Do not call a metric "coverage" unless it is code coverage/);
  assert.match(skill, /Split backend\/frontend\/repo metrics/);
});

test('gate rules hard-gate release-critical failures', () => {
  const rules = read('references/gate-rules.md');

  for (const required of [
    '`test_failed`',
    '`secrets_in_code`',
    '`critical_cve_count`',
    '`high_cve_count`',
    '`debt_exception_expired`',
    '`debt_exception_missing_owner`',
    '`debt_exception_missing_ttl`',
  ]) {
    assert.match(rules, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.match(rules, /Any hard gate failure in a dimension makes that dimension `E`/);
  assert.match(rules, /`test_failed > 0` makes D3 `E`/);
});

test('report template requires JSON traceability and reproducibility metadata', () => {
  const template = read('references/report-template.md');

  assert.match(template, /Measurement artifact/);
  assert.match(template, /Every non-trivial metric claim must include a source label/);
  assert.match(template, /Artifact Self-Check/);
  assert.match(template, /Coverage is not confused with pass rate/);
  assert.match(template, /Commands include git SHA, dirty status, tool versions, and exits/);
});
