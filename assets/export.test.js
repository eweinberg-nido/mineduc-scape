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
  curriculumBase: '7o-basico-2o-medio',
  status: 'vigente',
};

const OAT = {
  kind: 'oat',
  oa_id: 'CL_OAT_1A6B_FISICA_01',
  code: 'OAT 1',
  dimension: 'Dimensión física',
  curriculumBase: '1o-6o-basico',
  curriculumBaseName: 'Bases Curriculares de 1° a 6° Básico',
  statement: 'Favorecer el desarrollo físico personal y el autocuidado.',
  status: 'vigente',
  provenance: { source_type: 'jsonapi', source_url: 'https://example.test/jsonapi' },
  indicators: [],
  keywords: [],
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
  curriculumBase: '7o-basico-2o-medio',
  status: 'vigente',
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
  const out = formatOne(PLAIN);
  assert.match(out, /^\[MA1M OA 01\] Calcular operaciones con números racionales\./);
  assert.ok(!out.includes('Indicadores'));
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
  assert.equal(rows[0],
    'kind,code,level,subject,strand,category,curriculum_base,status,statement,indicators');
  assert.match(rows[1], /^"oa","MA1M OA 02","1° Medio","Matemática","Números"/);
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
  assert.equal(first.kind, 'oa');
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


/*
 * Transversal objectives in the selection.
 *
 * An OAT is defined once per curriculum base rather than per subject, so it has
 * no level, no subject and no eje. A mixed export has to place it accurately
 * instead of emitting three empty columns, which would read as missing data
 * rather than as data that does not apply.
 */
test('a mixed selection exports in every format without losing either kind', () => {
  for (const format of Object.keys(FORMATS)) {
    const out = exportRecords([BULLETED, OAT], format);
    assert.ok(out.includes('MA1M OA 02'), `${format} dropped the objective`);
    assert.ok(out.includes('OAT 1'), `${format} dropped the transversal objective`);
  }
});

test('csv marks each row with its kind and leaves level and subject empty for an OAT', () => {
  const rows = toCsv([BULLETED, OAT]).split('\n');
  assert.equal(rows.length, 3);
  assert.match(rows[2], /^"oat","OAT 1","",""/);
  assert.match(rows[2], /"Dimensión física","transversal","Bases Curriculares de 1° a 6° Básico"/);
});

test('json gives an OAT its own shape rather than blank objective fields', () => {
  const [record] = JSON.parse(toJson([OAT]));
  assert.equal(record.kind, 'oat');
  assert.equal(record.oat_id, 'CL_OAT_1A6B_FISICA_01');
  assert.equal(record.dimension, 'Dimensión física');
  assert.equal(record.curriculum_base, '1o-6o-basico');
  assert.equal(record.provenance.source_type, 'jsonapi');
  assert.ok(!('level' in record), 'an OAT has no level to report');
  assert.ok(!('subject' in record), 'an OAT has no subject to report');
});

test('markdown heads an OAT with its dimension and curriculum base', () => {
  const out = toMarkdown([OAT]);
  assert.match(out, /^### OAT 1 — Dimensión física\n/);
  assert.match(out, /\*Objetivo transversal · Bases Curriculares de 1° a 6° Básico\*/);
});

test('the LLM block says an OAT is transversal and which base it belongs to', () => {
  const out = toPrompt([BULLETED, OAT]);
  assert.match(out, /de asignatura y transversales/);
  assert.match(out, /\[OAT 1\] Objetivo de Aprendizaje Transversal · Dimensión física/);
});

test('the LLM block header stays plain when nothing transversal is selected', () => {
  assert.match(toPrompt([BULLETED]), /Objetivos seleccionados:/);
});

test('plain text says where each record comes from', () => {
  assert.match(formatOne(BULLETED), /\n {2}Matemática · 1° Medio/);
  assert.match(formatOne(OAT), /\n {2}Objetivo de Aprendizaje Transversal · Dimensión física/);
});

test('csv carries the curriculum status of both kinds', () => {
  const rows = toCsv([BULLETED, OAT]).split('\n');
  assert.ok(rows[0].includes('status'));
  assert.ok(rows[1].includes('"vigente"'));
  assert.ok(rows[2].includes('"vigente"'));
});
