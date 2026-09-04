/**
 * node --test assets/export.test.js
 *
 * The export formats are what leaves the app and lands in someone's lesson
 * plan or prompt, so they are worth pinning down.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FORMATS, exportRecords, formatOne, toCsv, toJson, toMarkdown, toPrompt,
} from './export.js';

const BULLETED = {
  oa_id: 'CL_MAT_1M_NMRS_OA02',
  code: 'MA1M OA 02',
  levelName: '1° Medio',
  subjectName: 'Matemática',
  strand: 'Números',
  strand_kind: 'Eje',
  category: 'conocimiento',
  track: 'plan_comun',
  statement: 'Mostrar que comprenden las potencias:\n- Transfiriendo propiedades.\n- Buscando patrones.',
  indicators: ['Aplican las propiedades.', 'Resuelven problemas de la vida diaria.'],
  source_url: 'https://example.test/oa',
};

const PLAIN = {
  oa_id: 'CL_MAT_1M_NMRS_OA01',
  code: 'MA1M OA 01',
  levelName: '1° Medio',
  subjectName: 'Matemática',
  strand: '',
  strand_kind: '',
  category: 'habilidad',
  track: 'plan_comun',
  statement: 'Calcular operaciones con números racionales.',
  indicators: [],
  source_url: 'https://example.test/oa1',
};

test('empty selection exports nothing, in every format', () => {
  for (const format of Object.keys(FORMATS)) {
    assert.equal(exportRecords([], format), '');
  }
});

test('plain text keeps the bullet structure and lists indicators', () => {
  const out = formatOne(BULLETED);
  assert.match(out, /^\[MA1M OA 02\] Mostrar que comprenden las potencias:/);
  assert.match(out, /\n {2}- Transfiriendo propiedades\./);
  assert.match(out, /Indicadores de evaluación:/);
  assert.match(out, /\n {2}- Aplican las propiedades\./);
});

test('an objective without indicators gets no indicator heading', () => {
  assert.equal(formatOne(PLAIN), '[MA1M OA 01] Calcular operaciones con números racionales.');
});

test('markdown renders a heading, the eje, and the bullets as a list', () => {
  const out = toMarkdown([BULLETED]);
  assert.match(out, /^### MA1M OA 02 — Matemática, 1° Medio\n/);
  assert.match(out, /\*Eje: Números\*/);
  assert.match(out, /\n- Transfiriendo propiedades\./);
  assert.match(out, /\*\*Indicadores de evaluación\*\*/);
});

test('markdown separates multiple objectives with a rule', () => {
  assert.equal(toMarkdown([BULLETED, PLAIN]).split('\n---\n').length, 2);
});

test('the LLM block is single-line per objective, with no markup', () => {
  const out = toPrompt([BULLETED]);
  assert.ok(!out.includes('\n- '), 'bullets should be inlined for a prompt');
  assert.match(out, /\[MA1M OA 02\] Matemática · 1° Medio · Plan común/);
  assert.match(out, /Mostrar que comprenden las potencias:; Transfiriendo propiedades\.; Buscando patrones\./);
  assert.match(out, /Fuente: curriculumnacional\.cl$/);
});

test('csv has a header, one row per objective, and quotes doubled', () => {
  const rows = toCsv([BULLETED, PLAIN]).split('\n');
  assert.equal(rows.length, 3);
  assert.equal(rows[0], 'code,level,subject,strand,category,statement,indicators');
  assert.match(rows[1], /^"MA1M OA 02","1° Medio","Matemática","Números"/);
  assert.match(rows[1], /Aplican las propiedades\. \| Resuelven problemas/);
  // statements are flattened so a row never spans lines
  assert.ok(!rows[1].includes('\n'));
});

test('csv escapes embedded double quotes', () => {
  const tricky = { ...PLAIN, statement: 'Usar la regla "de tres" simple.' };
  assert.match(toCsv([tricky]), /"Usar la regla ""de tres"" simple\."/);
});

test('json keeps the identifiers a consumer needs to join back', () => {
  const [first] = JSON.parse(toJson([BULLETED]));
  assert.equal(first.oa_id, 'CL_MAT_1M_NMRS_OA02');
  assert.equal(first.code, 'MA1M OA 02');
  assert.deepEqual(first.indicators, BULLETED.indicators);
  assert.equal(first.source_url, 'https://example.test/oa');
  // the newline structure survives, unlike in the CSV
  assert.ok(first.statement.includes('\n- '));
});

test('unknown formats fall back to plain text rather than throwing', () => {
  assert.equal(exportRecords([PLAIN], 'no-such-format'), formatOne(PLAIN));
});
