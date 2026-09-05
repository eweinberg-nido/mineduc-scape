/**
 * Currículum Nacional navigator.
 *
 * A static, dependency-free app over the dataset this repository builds.
 * Three panes — filters, results, detail — plus a selection basket. State lives
 * in the URL hash, so every view and every objective is a shareable link.
 */

import { loadDataset, clearCache } from './store.js';
import {
  flatten, flattenOats, buildIndex, buildOatIndex, search, highlight, escapeHtml,
  fold, explainMatch,
} from './index.js';
import { FORMATS, exportRecords, formatOne } from './export.js';

const PAGE = 60;
const CATEGORY_LABEL = {
  conocimiento: 'Conocimiento',
  habilidad: 'Habilidad',
  actitud: 'Actitud',
};
const TRACK_LABEL = {
  plan_comun: 'Plan común',
  plan_diferenciado_hc: 'Diferenciado HC',
  plan_diferenciado_tp: 'Técnico-Profesional',
};
const STATUS_LABEL = {
  vigente: 'Vigente',
  propuesta: 'Propuesta',
  en_implementacion: 'En implementación',
  historico: 'Histórico',
  desconocido: 'Estado no verificado',
};
const STATUS_NOTE = {
  vigente: 'Una fuente oficial declara este currículum vigente.',
  propuesta: 'El Ministerio publica este currículum como propuesta, en paralelo al '
           + 'currículum en vigor. No es el currículum vigente.',
  en_implementacion: 'Currículum aprobado y publicado, con entrada en aula gradual.',
  historico: 'Material superado o de un periodo cerrado.',
  desconocido: 'Este proyecto no ha verificado con una fuente oficial si este '
             + 'currículum está vigente. La existencia de la página no lo acredita.',
};
const SCOPE_NOTE = {
  objective: 'El Programa de Estudio publica estos indicadores para este objetivo.',
  unit: 'Estos indicadores provienen de una Actividad de Evaluación que evalúa '
      + 'varios objetivos en conjunto, no solo este.',
  mixed: 'Parte de estos indicadores corresponde a este objetivo y parte proviene '
       + 'de una Actividad de Evaluación que evalúa varios objetivos en conjunto.',
};

const $ = (selector) => document.querySelector(selector);

const el = {
  status: $('#status'),
  app: $('#app'),
  q: $('#q'),
  clearQ: $('#clear-q'),
  level: $('#f-level'),
  subject: $('#f-subject'),
  strand: $('#f-strand'),
  category: $('#f-category'),
  track: $('#f-track'),
  prioritized: $('#f-prioritized'),
  hasIndicators: $('#f-indicators'),
  reset: $('#reset'),
  meta: $('#meta'),
  count: $('#result-count'),
  sort: $('#sort'),
  list: $('#list'),
  more: $('#more'),
  moreWrap: $('#more-wrap'),
  empty: $('#empty'),
  detail: $('#detail'),
  basket: $('#basket'),
  basketToggle: $('#basket-toggle'),
  basketCount: $('#basket-count'),
  basketList: $('#basket-list'),
  basketClear: $('#basket-clear'),
  basketClose: $('#basket-close'),
  basketCopy: $('#basket-copy'),
  basketDownload: $('#basket-download'),
  exportFormat: $('#export-format'),
  themeToggle: $('#theme-toggle'),
  filters: $('.filters'),
  filtersToggle: $('#filters-toggle'),
  modeOa: $('#mode-oa'),
  modeOat: $('#mode-oat'),
  modeOaN: $('#mode-oa-n'),
  modeOatN: $('#mode-oat-n'),
  base: $('#f-base'),
  dimension: $('#f-dimension'),
  statusFilter: $('#f-status'),
  about: $('#about'),
  aboutBody: $('#about-body'),
  aboutToggle: $('#about-toggle'),
  aboutOpen: $('#about-open'),
  aboutClose: $('#about-close'),
  oaOnly: document.querySelectorAll('.oa-only'),
  oatOnly: document.querySelectorAll('.oat-only'),
};

const NARROW = matchMedia('(max-width: 62rem)');

const state = {
  // Two record sets, deliberately not merged. An OAT is defined per curriculum
  // base, not per subject, so it has no level, subject or eje to filter on;
  // flattening the two into one list would either invent those fields or leave
  // the filters lying about what they cover. They share `byId`, the basket and
  // the export path, which are the places the two genuinely behave alike.
  mode: 'oa',
  records: [],
  postings: null,
  oats: [],
  oatPostings: null,
  byId: new Map(),
  byCodeSlug: new Map(),
  levels: [],
  manifest: {},
  query: '',
  filters: { level: '', subject: '', strand: '', category: '', track: '', status: '' },
  oatFilters: { base: '', dimension: '' },
  only: { prioritized: false, indicators: false },
  sort: 'relevance',
  shown: PAGE,
  results: [],
  why: new Map(),
  selected: null,
  basket: [],
};

const isOat = (record) => record?.kind === 'oat';
const activeRecords = () => (state.mode === 'oat' ? state.oats : state.records);
const activePostings = () => (state.mode === 'oat' ? state.oatPostings : state.postings);

/* ------------------------------------------------------------------ theme */
function initTheme() {
  const saved = localStorage.getItem('cn-theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.dataset.theme = saved;
  }
  el.themeToggle.addEventListener('click', () => {
    const current = document.documentElement.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('cn-theme', next); } catch { /* private mode */ }
  });
}

/* ------------------------------------------------------------- URL state */
function readHash() {
  const hash = location.hash.replace(/^#/, '');
  if (!hash) return;
  const params = new URLSearchParams(hash);

  // A bare "#code" or "#CL_..." is treated as a deep link to one objective.
  if (!hash.includes('=')) {
    const key = decodeURIComponent(hash);
    const record = state.byId.get(key)
      || state.byCodeSlug.get(fold(key).replace(/[^a-z0-9]+/g, '-'));
    if (record) focusOn(record);
    return;
  }

  state.mode = params.get('mode') === 'oat' ? 'oat' : 'oa';
  state.query = params.get('q') ?? '';
  state.oatFilters.base = params.get('base') ?? '';
  state.oatFilters.dimension = params.get('dim') ?? '';
  state.filters.status = params.get('status') ?? '';
  state.filters.level = params.get('level') ?? '';
  state.filters.subject = params.get('subject') ?? '';
  state.filters.strand = params.get('strand') ?? '';
  state.filters.category = params.get('cat') ?? '';
  state.filters.track = params.get('track') ?? '';
  state.only.prioritized = params.get('prio') === '1';
  state.only.indicators = params.get('ind') === '1';
  state.sort = params.get('sort') ?? 'relevance';
  state.selected = params.get('oa') ?? null;

  // A link that names only an objective should land on it in context, rather
  // than selecting it and leaving the reader to find it among 4110 rows. A
  // link that also carries filters is respected as written.
  const onlyObjective = [...params.keys()].every((key) => key === 'oa');
  if (state.selected && onlyObjective) {
    const record = state.byId.get(state.selected);
    if (record) focusOn(record);
  }
}

/** Point the filters at one record's own context, whichever kind it is. */
function focusOn(record) {
  state.selected = record.oa_id;
  if (isOat(record)) {
    state.mode = 'oat';
    state.oatFilters = { base: record.curriculumBase, dimension: '' };
    state.query = '';
    return;
  }
  state.mode = 'oa';
  state.filters.level = record.levelId;
  // The subject filter is keyed on the display name, because that is what the
  // <select> offers and what usefully spans curriculum bases.
  state.filters.subject = record.subjectName;
  state.filters.strand = '';
  state.filters.category = '';
  state.filters.track = '';
  state.filters.status = '';
  state.only = { prioritized: false, indicators: false };
  state.query = '';
}

function writeHash({ replace = false } = {}) {
  const params = new URLSearchParams();
  if (state.mode !== 'oa') params.set('mode', state.mode);
  if (state.query) params.set('q', state.query);
  if (state.oatFilters.base) params.set('base', state.oatFilters.base);
  if (state.oatFilters.dimension) params.set('dim', state.oatFilters.dimension);
  if (state.filters.status) params.set('status', state.filters.status);
  if (state.filters.level) params.set('level', state.filters.level);
  if (state.filters.subject) params.set('subject', state.filters.subject);
  if (state.filters.strand) params.set('strand', state.filters.strand);
  if (state.filters.category) params.set('cat', state.filters.category);
  if (state.filters.track) params.set('track', state.filters.track);
  if (state.only.prioritized) params.set('prio', '1');
  if (state.only.indicators) params.set('ind', '1');
  if (state.sort !== 'relevance') params.set('sort', state.sort);
  if (state.selected) params.set('oa', state.selected);

  const hash = `#${params.toString()}`;
  if (hash === location.hash) return;
  if (replace) history.replaceState(null, '', hash);
  else history.pushState(null, '', hash);
}

/* --------------------------------------------------------------- filters */
function matches(record) {
  if (isOat(record)) {
    const { base, dimension } = state.oatFilters;
    if (base && record.curriculumBase !== base) return false;
    if (dimension && record.dimension !== dimension) return false;
    if (state.filters.status && record.status !== state.filters.status) return false;
    return true;
  }
  const { level, subject, strand, category, track, status } = state.filters;
  if (status && record.status !== status) return false;
  if (level && record.levelId !== level) return false;
  if (subject && record.subjectName !== subject) return false;
  if (strand && record.strand !== strand) return false;
  if (category && record.category !== category) return false;
  if (track && record.track !== track) return false;
  if (state.only.prioritized && !record.prioritized) return false;
  if (state.only.indicators && !record.indicators.length) return false;
  return true;
}

function compute() {
  const records = activeRecords();
  const found = search(records, activePostings(), state.query);
  const pool = found ?? records;
  let results = pool.filter(matches);

  // Why each visible result matched, so a card can say "matched only in an
  // indicator" rather than looking like a false positive. Computed for the
  // result set, not the whole dataset, so it stays cheap.
  state.why = new Map();
  if (state.query) {
    for (const record of results.slice(0, state.shown + PAGE)) {
      const why = explainMatch(record, state.query);
      if (why) state.why.set(record.oa_id, why);
    }
  }

  const sorters = {
    curriculum: (a, b) => a.order - b.order,
    code: (a, b) => a.code.localeCompare(b.code, 'es', { numeric: true }),
    indicators: (a, b) => b.indicators.length - a.indicators.length || a.order - b.order,
  };
  if (state.sort === 'relevance') {
    // With no query there is no relevance to speak of, so fall back to the
    // order the curriculum itself is published in.
    if (!found) results = [...results].sort(sorters.curriculum);
  } else {
    results = [...results].sort(sorters[state.sort]);
  }
  state.results = results;
}

/* --------------------------------------------------------------- chrome  */
function chip(container, value, label, count, key, { disabled = false, title = '' } = {}) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'chip';
  button.dataset.value = value;
  button.setAttribute('aria-pressed', String(state.filters[key] === value));
  if (disabled) {
    button.disabled = true;
    button.title = title;
  }
  button.innerHTML = `${escapeHtml(label)}${count == null ? '' : `<span class="n">${count}</span>`}`;
  button.addEventListener('click', () => {
    state.filters[key] = state.filters[key] === value ? '' : value;
    if (key === 'level' || key === 'subject') state.filters.strand = '';
    state.shown = PAGE;
    render();
    writeHash();
  });
  container.append(button);
}

function statusBadge(record) {
  const status = record.status ?? 'desconocido';
  return `<span class="badge status st-${escapeHtml(status)}"`
    + ` title="${escapeHtml(STATUS_NOTE[status] ?? '')}">`
    + `${escapeHtml(STATUS_LABEL[status] ?? status)}</span>`;
}

/**
 * The prioritization badge.
 *
 * It used to read "Priorizado", present tense, which is a claim the data never
 * supported: the flag records membership of the Priorización Curricular
 * published for 2023-2025. The label now carries the period, and the detail
 * pane says in words that it is historical.
 */
function priorityBadge(record) {
  const info = record.prioritization;
  if (!record.prioritized && !info) return '';
  const period = info?.period ?? '2023-2025';
  return `<span class="badge prio" title="${escapeHtml(info?.note ?? '')}">`
    + `Priorización ${escapeHtml(period.replace('-', '–'))}</span>`;
}

function renderModeBar() {
  el.modeOaN.textContent = state.records.length.toLocaleString('es-CL');
  el.modeOatN.textContent = state.oats.length.toLocaleString('es-CL');
  el.modeOa.setAttribute('aria-pressed', String(state.mode === 'oa'));
  el.modeOat.setAttribute('aria-pressed', String(state.mode === 'oat'));
  for (const node of el.oaOnly) node.hidden = state.mode !== 'oa';
  for (const node of el.oatOnly) node.hidden = state.mode !== 'oat';
}

function renderOatFilters() {
  const bases = new Map();
  for (const record of state.oats) bases.set(record.curriculumBase, record.curriculumBaseName);
  fillSelect(el.base, 'Todas las bases curriculares',
    [...bases.keys()].sort((a, b) => (bases.get(a) ?? a).localeCompare(bases.get(b) ?? b, 'es')),
    state.oatFilters.base, 'base', (value) => bases.get(value) ?? value);

  const reachable = state.oatFilters.base
    ? state.oats.filter((r) => r.curriculumBase === state.oatFilters.base)
    : state.oats;
  fillSelect(el.dimension, 'Todas las dimensiones',
    [...new Set(reachable.map((r) => r.dimension).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, 'es')),
    state.oatFilters.dimension, 'dimension');
}

function renderStatusFilter() {
  const counts = new Map();
  for (const record of activeRecords()) {
    counts.set(record.status, (counts.get(record.status) ?? 0) + 1);
  }
  fillSelect(el.statusFilter, 'Todos los estados',
    [...counts.keys()].sort(),
    state.filters.status, 'status',
    (value) => `${STATUS_LABEL[value] ?? value} (${counts.get(value).toLocaleString('es-CL')})`);
}

function renderFilters() {
  renderModeBar();
  el.q.value = state.query;
  el.clearQ.hidden = !state.query;
  el.sort.value = state.sort;
  renderStatusFilter();
  if (state.mode === 'oat') {
    renderOatFilters();
    return;
  }
  el.level.replaceChildren();
  for (const level of state.levels) {
    chip(el.level, level.id, level.short, level.count, 'level', {
      disabled: level.count === 0,
      title: level.count === 0
        ? 'Este nivel no publica objetivos en HTML: su currículum solo existe en PDF.'
        : '',
    });
  }

  el.category.replaceChildren();
  for (const [value, label] of Object.entries(CATEGORY_LABEL)) {
    chip(el.category, value, label, null, 'category');
  }

  el.track.replaceChildren();
  for (const [value, label] of Object.entries(TRACK_LABEL)) {
    chip(el.track, value, label, null, 'track');
  }

  // Subject and eje options depend on the other filters, so they are rebuilt
  // from whatever is currently reachable rather than from the whole dataset.
  const reachable = state.records.filter((record) => {
    const { level, category, track } = state.filters;
    if (level && record.levelId !== level) return false;
    if (category && record.category !== category) return false;
    if (track && record.track !== track) return false;
    return true;
  });

  fillSelect(el.subject, 'Todas las asignaturas',
    [...new Set(reachable.map((r) => r.subjectName))].sort((a, b) => a.localeCompare(b, 'es')),
    state.filters.subject, 'subject');

  const strandPool = state.filters.subject
    ? reachable.filter((r) => r.subjectName === state.filters.subject)
    : reachable;
  fillSelect(el.strand, 'Todos los ejes',
    [...new Set(strandPool.map((r) => r.strand).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es')),
    state.filters.strand, 'strand');

  el.prioritized.checked = state.only.prioritized;
  el.hasIndicators.checked = state.only.indicators;
}

function fillSelect(select, allLabel, values, current, key, labelOf = (v) => v) {
  select.replaceChildren();
  const all = document.createElement('option');
  all.value = '';
  all.textContent = allLabel;
  select.append(all);
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = labelOf(value);
    select.append(option);
  }
  select.value = values.includes(current) ? current : '';
  // The active value can fall out of range when another filter narrows things;
  // drop it rather than leaving a filter applied that the UI cannot show.
  if (current && select.value !== current) {
    const bag = key in state.oatFilters ? state.oatFilters : state.filters;
    bag[key] = '';
  }
}

/**
 * The "Acerca de los datos" panel.
 *
 * Every number here comes from the manifest the build writes, not from a
 * constant in this file and not from recounting the dataset in the browser.
 * Two distinctions the panel exists to make, because the previous version made
 * neither:
 *
 * * **offerings are not subjects.** 372 level x subject curriculum offerings
 *   are about 129 distinct subjects taught across several levels. Calling the
 *   first number "asignaturas" overstated the dataset threefold.
 * * **absent at source is not a parser gap.** An offering with no objectives
 *   because the ministry publishes none is a fact about the curriculum; one
 *   with no objectives and no verified reason is a defect here. They are
 *   counted, and labelled, separately.
 */
const NUMBER = (value) => (value ?? 0).toLocaleString('es-CL');

function renderAbout(manifest) {
  const coverage = manifest.coverage ?? {};
  const byStatus = coverage.by_status ?? {};
  const statuses = manifest.status_summary ?? {};
  const sources = manifest.total_by_source_type ?? {};
  const oat = manifest.oat_verification ?? {};

  const stat = (label, value, note = '') => `
    <div class="stat">
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(NUMBER(value))}</dd>
      ${note ? `<p>${escapeHtml(note)}</p>` : ''}
    </div>`;

  const SOURCE_LABEL = {
    html_curriculum_page: 'Páginas de currículum (HTML)',
    base_curricular_pdf: 'Bases Curriculares (PDF)',
    programa_estudio_pdf: 'Programas de Estudio (PDF)',
    jsonapi: 'JSON:API del sitio',
  };
  const COVERAGE_LABEL = {
    ingested: 'Con objetivos ingeridos',
    source_absent: 'Sin objetivos en la fuente oficial',
    defined_elsewhere: 'Definidos en un nivel combinado',
    parser_gap: 'Sin objetivos y sin razón verificada',
    missing_from_dataset: 'En el índice oficial, fuera del dataset',
  };

  el.aboutBody.innerHTML = `
    <p class="about-lede">
      Construido el <strong>${escapeHtml((manifest.built_at ?? '').slice(0, 10))}</strong>
      a partir de un rastreo del sitio del
      ${escapeHtml((manifest.scraped_at ?? '').slice(0, 10))}.
      Esquema ${escapeHtml(manifest.schema_version ?? '?')}.
      La cobertura se calcula contra el inventario oficial de fuentes, no contra
      el total de una construcción anterior.
    </p>

    <h3>Registros</h3>
    <dl class="stats">
      ${stat('Objetivos por nivel y asignatura', manifest.total_oas)}
      ${stat('Códigos oficiales distintos', manifest.distinct_official_codes,
             'Un OA de 3° y 4° Medio se publica bajo ambos cursos.')}
      ${stat('Objetivos transversales (OAT)', manifest.total_oats,
             'Definidos por base curricular, no por asignatura.')}
      ${stat('Ofertas curriculares (nivel × asignatura)', manifest.total_offerings)}
      ${stat('Asignaturas distintas', manifest.distinct_subjects,
             'Cada una se imparte en varios niveles.')}
      ${stat('Con indicadores de evaluación', manifest.objectives_with_indicators)}
      ${stat('Indicadores de evaluación', manifest.total_indicators)}
      ${stat('Criterios de evaluación (TP)', manifest.total_criteria)}
    </dl>

    <h3>EPJA y Religión</h3>
    <dl class="stats">
      ${stat('Objetivos EPJA', manifest.total_epja_objectives,
             'Leídos de las Bases Curriculares EPJA 2024 salvo los publicados en HTML.')}
      ${stat('Objetivos de Religión', manifest.total_religion_objectives,
             'El Decreto N° 924 establece un programa por credo; no se publican aquí.')}
    </dl>

    <h3>Cobertura frente al inventario oficial</h3>
    <ul class="cov">
      ${Object.entries(byStatus).map(([key, value]) => `
        <li class="cov-${escapeHtml(key)}">
          <span>${escapeHtml(COVERAGE_LABEL[key] ?? key)}</span>
          <strong>${escapeHtml(NUMBER(value))}</strong>
        </li>`).join('')}
    </ul>
    <p class="about-note">
      ${coverage.parser_gaps
        ? `${escapeHtml(NUMBER(coverage.parser_gaps))} oferta(s) sin objetivos y sin
           razón verificada: puede haber contenido que el lector no está extrayendo.`
        : 'Ninguna oferta queda sin objetivos y sin una razón verificada registrada.'}
    </p>

    <h3>Estado del currículum</h3>
    <ul class="cov">
      ${Object.entries(statuses).map(([key, value]) => `
        <li><span>${escapeHtml(STATUS_LABEL[key] ?? key)}</span>
          <strong>${escapeHtml(NUMBER(value))}</strong></li>`).join('')}
    </ul>
    <p class="about-note">
      Un estado distinto de «no verificado» siempre va acompañado de la fuente
      oficial que lo respalda. Que una página exista no acredita vigencia.
    </p>

    <h3>Origen de los registros</h3>
    <ul class="cov">
      ${Object.entries(sources).map(([key, value]) => `
        <li><span>${escapeHtml(SOURCE_LABEL[key] ?? key)}</span>
          <strong>${escapeHtml(NUMBER(value))}</strong></li>`).join('')}
    </ul>

    <h3>Objetivos transversales</h3>
    <ul class="cov">
      ${Object.entries(oat.bases_with_oats ?? {}).map(([base, count]) => `
        <li><span>${escapeHtml(base)}</span>
          <strong>${escapeHtml(NUMBER(count))}</strong></li>`).join('')}
    </ul>
    ${Object.entries(oat.bases_without_oats ?? {}).map(([base, why]) => `
      <p class="about-note"><strong>${escapeHtml(base)}:</strong> ${escapeHtml(why)}</p>`).join('')}
    ${oat.verified_on ? `<p class="about-note">OAT verificados contra la JSON:API
      del Ministerio el ${escapeHtml(oat.verified_on.slice(0, 10))};
      ${escapeHtml(NUMBER((oat.differences ?? []).length))} diferencias.</p>` : ''}

    <h3>Limitaciones conocidas</h3>
    ${(manifest.known_limitations ?? []).length
      ? `<ul class="lims">${manifest.known_limitations.map((limit) => `
          <li class="lim-${escapeHtml(limit.kind)}">
            <strong>${escapeHtml(limit.area)}</strong>
            <span class="lim-n">${escapeHtml(NUMBER(limit.offerings))} oferta(s)</span>
            <p>${escapeHtml(limit.summary)}</p>
            ${limit.source_url ? `<a href="${escapeHtml(limit.source_url)}"
              target="_blank" rel="noopener">Fuente</a>` : ''}
          </li>`).join('')}</ul>`
      : '<p class="about-note">Ninguna registrada.</p>'}

    <h3>Priorización curricular</h3>
    <p class="about-note">
      ${escapeHtml(manifest.prioritization?.note
        ?? 'La marca de priorización es un dato histórico.')}
    </p>
  `;
}

function renderMeta(manifest) {
  // "Asignaturas" deliberately shows the count of distinct subjects, not the
  // count of level x subject pages: those are different numbers and the second
  // one is nearly three times the first.
  const rows = [
    ['Objetivos', manifest.total_oas?.toLocaleString('es-CL')],
    ['Transversales', manifest.total_oats?.toLocaleString('es-CL')],
    ['Indicadores', manifest.total_indicators?.toLocaleString('es-CL')],
    ['Criterios TP', manifest.total_criteria?.toLocaleString('es-CL')],
    ['Asignaturas', manifest.distinct_subjects?.toLocaleString('es-CL')],
    ['Ofertas nivel × asignatura', manifest.total_offerings?.toLocaleString('es-CL')],
    ['Construido', manifest.built_at?.slice(0, 10) ?? manifest.scraped_at?.slice(0, 10)],
  ].filter(([, value]) => value);
  el.meta.innerHTML = rows
    .map(([term, value]) => `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(String(value))}</dd>`)
    .join('');
}

/* --------------------------------------------------------------- results */
function statementFirstLine(statement) {
  const [head] = statement.split('\n');
  return head;
}

function renderResults() {
  const total = state.results.length;
  const noun = state.mode === 'oat'
    ? (total === 1 ? 'objetivo transversal' : 'objetivos transversales')
    : (total === 1 ? 'objetivo' : 'objetivos');
  el.count.textContent = total ? `${total.toLocaleString('es-CL')} ${noun}` : '';
  el.empty.hidden = total > 0;
  if (!total) {
    el.empty.textContent = state.query
      ? `Sin resultados para “${state.query}”. Prueba con menos palabras o quita filtros.`
      : 'Ningún objetivo coincide con estos filtros.';
    el.list.replaceChildren();
    el.moreWrap.hidden = true;
    return;
  }

  const slice = state.results.slice(0, state.shown);
  const fragment = document.createDocumentFragment();
  for (const record of slice) fragment.append(renderRow(record));
  el.list.replaceChildren(fragment);
  el.moreWrap.hidden = state.shown >= total;
  el.more.textContent = `Mostrar más (${(total - state.shown).toLocaleString('es-CL')} restantes)`;
}

function renderRow(record) {
  const item = document.createElement('li');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'row';
  button.dataset.oa = record.oa_id;
  if (state.selected === record.oa_id) button.setAttribute('aria-current', 'true');

  const badges = [];
  if (isOat(record)) {
    badges.push('<span class="badge cat-transversal">Transversal</span>');
  } else {
    if (record.category !== 'conocimiento') {
      badges.push(`<span class="badge cat-${record.category}">${CATEGORY_LABEL[record.category]}</span>`);
    }
    badges.push(priorityBadge(record));
    if (record.indicators.length) {
      badges.push(`<span class="badge ind">${record.indicators.length} indicador${record.indicators.length === 1 ? '' : 'es'}</span>`);
    }
  }
  if (record.status && record.status !== 'vigente') badges.push(statusBadge(record));

  const where = isOat(record)
    ? `${escapeHtml(record.dimension)} · ${escapeHtml(record.curriculumBaseName)}`
    : `${escapeHtml(record.levelName)} · ${escapeHtml(record.subjectName)}`
      + (record.strand ? ` · ${escapeHtml(record.strand)}` : '');

  // A stored objective that is a stem plus a list must not read as a truncated
  // one. The card shows the stem and says how much it is holding back.
  const more = record.components > 0
    ? `<span class="more-parts">+ ${record.components} componente${record.components === 1 ? '' : 's'}</span>`
    : '';

  const why = state.why.get(record.oa_id);
  const explain = why?.indicatorOnly
    ? `<p class="why">Coincide solo en un indicador de evaluación:
         <span class="why-x">${highlight(why.excerpt, state.query)}</span></p>`
    : '';

  button.innerHTML = `
    <span class="row-top">
      <span class="code">${highlight(record.code, state.query)}</span>
      <span class="row-where">${where}</span>
    </span>
    <p class="row-statement">${highlight(statementFirstLine(record.statement), state.query)}${more}</p>
    ${explain}
    ${badges.filter(Boolean).length ? `<span class="row-meta">${badges.filter(Boolean).join('')}</span>` : ''}
  `;
  button.addEventListener('click', () => select(record.oa_id));
  item.append(button);
  return item;
}

/* ---------------------------------------------------------------- detail */
function statementHtml(statement, query) {
  const lines = statement.split('\n');
  const head = highlight(lines[0], query);
  const bullets = lines.slice(1).filter((line) => line.trim());
  if (!bullets.length) return `<p>${head}</p>`;
  const items = bullets
    .map((line) => `<li>${highlight(line.replace(/^-\s*/, ''), query)}</li>`)
    .join('');
  return `<p>${head}</p><ul>${items}</ul>`;
}

function progression(record) {
  // Objectives that share an official code across grades (the 3°/4° medio
  // pairs), plus the same eje and number in another level — the "how does this
  // strand develop" question the PDFs make almost impossible to answer.
  const sameCode = state.records.filter(
    (other) => other.code === record.code && other.oa_id !== record.oa_id,
  );
  const sameStrand = record.strand
    ? state.records.filter(
      (other) => other.strand === record.strand
        && other.subjectName === record.subjectName
        && other.levelId !== record.levelId
        && other.number === record.number,
    )
    : [];
  const seen = new Set([record.oa_id]);
  return [...sameCode, ...sameStrand]
    .filter((other) => !seen.has(other.oa_id) && seen.add(other.oa_id))
    .sort((a, b) => a.order - b.order);
}

/** Where a record came from, in the words the provenance record uses. */
function provenanceHtml(record) {
  const p = record.provenance;
  if (!p) return '';
  const kind = {
    html_curriculum_page: 'Página de currículum (HTML)',
    jsonapi: 'JSON:API de curriculumnacional.cl',
    base_curricular_pdf: 'Bases Curriculares (PDF)',
    programa_estudio_pdf: 'Programa de Estudio (PDF)',
  }[p.source_type] ?? p.source_type;
  const rows = [
    ['Tipo de fuente', kind],
    ['Documento', p.source_document],
    ['Página del PDF', p.source_page],
    ['Base curricular', p.curriculum_base],
    ['Extracción', p.extraction_method],
    ['Obtenido', (p.retrieved_at ?? '').slice(0, 10)],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '');
  return `<h3>Procedencia</h3>
    <dl class="prov">${rows.map(([term, value]) =>
      `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('')}</dl>
    <p class="prov-link"><a href="${escapeHtml(p.source_url)}" target="_blank" rel="noopener">
      Abrir la fuente exacta</a></p>`;
}

function statusHtml(record) {
  const status = record.status ?? 'desconocido';
  const source = record.statusSource;
  return `<h3>Estado del currículum</h3>
    <p class="status-line">${statusBadge(record)}
      <span>${escapeHtml(STATUS_NOTE[status] ?? '')}</span></p>
    ${source?.url ? `<p class="scope-note">${escapeHtml(source.note ?? '')}
      <a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">Fuente</a>
      ${source.verified_on ? `· verificado el ${escapeHtml(source.verified_on)}` : ''}</p>` : ''}`;
}

function correctionHtml(record) {
  const c = record.correction;
  if (!c) return '';
  return `<h3>Corrección aplicada</h3>
    <p class="scope-note">${escapeHtml(c.explanation)}</p>
    <p class="scope-note"><strong>Texto publicado en la fuente conflictiva:</strong>
      «${escapeHtml(c.original_value)}»</p>
    <p class="prov-link"><a href="${escapeHtml(c.authoritative_source_url)}"
      target="_blank" rel="noopener">Fuente autorizada${
        c.authoritative_source_page ? `, p. ${c.authoritative_source_page}` : ''}</a>
      ${c.verified_on ? `· verificado el ${escapeHtml(c.verified_on)}` : ''}</p>`;
}

function renderOatDetail(record) {
  const inBasket = state.basket.includes(record.oa_id);
  const siblings = state.oats.filter(
    (other) => other.dimension === record.dimension
      && other.curriculumBase === record.curriculumBase
      && other.oa_id !== record.oa_id,
  );
  const parts = [`
    <span class="d-code">${escapeHtml(record.code)}</span>
    <h2>${escapeHtml(record.dimension)}</h2>
    <p class="d-where">Objetivo de Aprendizaje Transversal ·
      ${escapeHtml(record.curriculumBaseName)}</p>
    <div class="d-actions">
      <button class="ghost" data-act="basket">${inBasket ? 'Quitar de la selección' : 'Añadir a la selección'}</button>
      <button class="ghost" data-act="copy">Copiar</button>
      <button class="ghost" data-act="link">Copiar enlace</button>
    </div>
    ${record.title ? `<p class="oat-title">${escapeHtml(record.title)}</p>` : ''}
    <div class="statement">${statementHtml(record.statement, state.query)}</div>
  `];
  if (record.dimensionDescription) {
    parts.push(`<h3>Sobre esta dimensión</h3>
      <p class="scope-note">${escapeHtml(record.dimensionDescription)}</p>`);
  }
  parts.push(statusHtml(record));
  parts.push(provenanceHtml(record));
  if (siblings.length) {
    parts.push(`<h3>Otros OAT de esta dimensión (${siblings.length})</h3>`);
    parts.push(`<ul class="prog">${siblings.map((other) => `
      <li><button type="button" data-goto="${escapeHtml(other.oa_id)}">
        <span class="prog-lvl">${escapeHtml(other.code)}</span>
        <span class="prog-st">${escapeHtml(statementFirstLine(other.statement))}</span>
      </button></li>`).join('')}</ul>`);
  }
  el.detail.innerHTML = parts.join('');
  wireDetailActions(record);
}

function wireDetailActions(record) {
  el.detail.querySelector('[data-act="basket"]')?.addEventListener('click', () => {
    toggleBasket(record.oa_id);
    renderDetail();
  });
  el.detail.querySelector('[data-act="copy"]')?.addEventListener('click', () => {
    copy(formatOne(record), 'Objetivo copiado');
  });
  el.detail.querySelector('[data-act="link"]')?.addEventListener('click', () => {
    const params = new URLSearchParams();
    if (isOat(record)) params.set('mode', 'oat');
    params.set('oa', record.oa_id);
    copy(`${location.origin}${location.pathname}#${params.toString()}`, 'Enlace copiado');
  });
  for (const button of el.detail.querySelectorAll('[data-goto]')) {
    button.addEventListener('click', () => select(button.dataset.goto, { reveal: true }));
  }
}

function renderDetail() {
  const record = state.byId.get(state.selected);
  if (record && isOat(record)) {
    renderOatDetail(record);
    return;
  }
  if (!record) {
    el.detail.innerHTML = '<p class="detail-placeholder">Selecciona un objetivo para ver '
      + 'su detalle, sus indicadores de evaluación y su progresión entre cursos.</p>';
    return;
  }

  const inBasket = state.basket.includes(record.oa_id);
  const programa = record.documents.find((doc) => doc.doc_type === 'Programa de estudio');
  const related = progression(record);

  const parts = [];
  parts.push(`
    <span class="d-code">${escapeHtml(record.code)}</span>
    <h2>${escapeHtml(record.subjectName)} · ${escapeHtml(record.levelName)}</h2>
    <p class="d-where">
      ${escapeHtml(TRACK_LABEL[record.track] ?? record.track)}
      ${record.strand ? ` · ${escapeHtml(record.strand_kind || 'Eje')}: ${escapeHtml(record.strand)}` : ''}
      · ${escapeHtml(CATEGORY_LABEL[record.category] ?? record.category)}
      ${record.formationArea ? ` · ${escapeHtml(record.formationArea)}` : ''}
    </p>
    <p class="d-badges">${[statusBadge(record), priorityBadge(record)].filter(Boolean).join('')}</p>
    ${record.prioritization ? `<p class="scope-note">${escapeHtml(record.prioritization.note)}</p>` : ''}
    ${record.levelScope?.length ? `<p class="scope-note">Las Bases definen este objetivo
      para un nivel combinado; aplica a: ${escapeHtml(record.levelScope.join(', '))}.</p>` : ''}
    <div class="d-actions">
      <button class="ghost" data-act="basket">${inBasket ? 'Quitar de la selección' : 'Añadir a la selección'}</button>
      <button class="ghost" data-act="copy">Copiar</button>
      <button class="ghost" data-act="link">Copiar enlace</button>
    </div>
    <div class="statement">${statementHtml(record.statement, state.query)}</div>
  `);

  if (record.indicators.length) {
    parts.push(`<h3>Indicadores de evaluación (${record.indicators.length})</h3>`);
    if (record.indicators_scope && SCOPE_NOTE[record.indicators_scope]) {
      parts.push(`<p class="scope-note">${escapeHtml(SCOPE_NOTE[record.indicators_scope])}</p>`);
    }
    parts.push(`<ul class="indicators">${record.indicators
      .map((indicator) => `<li>${highlight(indicator, state.query)}</li>`).join('')}</ul>`);
  } else {
    parts.push('<h3>Indicadores de evaluación</h3>');
    parts.push(`<p class="scope-note">${record.track === 'plan_diferenciado_tp'
      ? 'Los Programas Técnico-Profesionales no publican indicadores por objetivo: '
        + 'entregan módulos con Aprendizajes Esperados y Criterios de Evaluación.'
      : programa
        ? 'El Programa de Estudio de esta asignatura no tabula indicadores para este objetivo.'
        : 'Esta asignatura no tiene Programa de Estudio publicado en el sitio.'}</p>`);
  }

  if (record.modules.length) {
    parts.push(`<h3>Módulos de la especialidad (${record.modules.length})</h3>`);
    for (const module of record.modules) {
      const criteria = module.expected_learnings
        .reduce((sum, learning) => sum + (learning.criteria?.length ?? 0), 0);
      parts.push(`
        <details class="module"${module.objective_ids?.includes(record.oa_id) ? ' open' : ''}>
          <summary>Módulo ${module.module_number}: ${escapeHtml(module.module_name)}
            <span class="oag"> — ${module.hours ?? '?'} h · ${escapeHtml(module.grade ?? '')} · ${criteria} criterios</span>
          </summary>
          <div class="module-body">
            ${module.expected_learnings.map((learning) => `
              <div class="ae">
                <p>${learning.number}. ${escapeHtml(learning.statement)}</p>
                <ul>${(learning.criteria ?? []).map((criterion) => `<li>${escapeHtml(criterion)}</li>`).join('')}</ul>
                ${learning.generic_objectives?.length
                  ? `<p class="oag">OAG: ${learning.generic_objectives.join(', ')}</p>` : ''}
              </div>`).join('')}
          </div>
        </details>`);
    }
  }

  if (related.length) {
    parts.push(`<h3>Progresión y equivalentes (${related.length})</h3>`);
    parts.push(`<ul class="prog">${related.map((other) => `
      <li><button type="button" data-goto="${escapeHtml(other.oa_id)}">
        <span class="prog-lvl">${escapeHtml(other.levelName)} · ${escapeHtml(other.code)}</span>
        <span class="prog-st">${escapeHtml(statementFirstLine(other.statement))}</span>
      </button></li>`).join('')}</ul>`);
  }

  parts.push(correctionHtml(record));
  parts.push(statusHtml(record));
  parts.push(provenanceHtml(record));

  if (record.keywords.length) {
    parts.push('<h3>Etiquetas</h3>');
    parts.push(`<div class="kw">${record.keywords
      .map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join('')}</div>`);
  }

  const docs = [
    ...(record.source_url
      ? [{ doc_type: 'Ficha oficial', title: 'Ver en curriculumnacional.cl', url: record.source_url }]
      : []),
    ...record.documents,
    ...record.indicators_source.map((url) => ({
      doc_type: 'PDF de origen', title: 'Programa de Estudio (PDF)', url,
    })),
  ];
  if (docs.length) {
    parts.push('<h3>Fuentes</h3>');
    parts.push(`<ul class="docs">${docs.map((doc) => `
      <li><span class="dtype">${escapeHtml(doc.doc_type ?? '')}</span><br>
        <a href="${escapeHtml(doc.url)}" target="_blank" rel="noopener">${escapeHtml(doc.title)}</a></li>`).join('')}</ul>`);
  }

  el.detail.innerHTML = parts.join('');
  wireDetailActions(record);
}

/* --------------------------------------------------------------- basket  */
function toggleBasket(id) {
  const at = state.basket.indexOf(id);
  if (at === -1) state.basket.push(id);
  else state.basket.splice(at, 1);
  try { localStorage.setItem('cn-basket', JSON.stringify(state.basket)); } catch { /* ignore */ }
  renderBasket();
}

function renderBasket() {
  el.basketCount.textContent = String(state.basket.length);
  if (!state.basket.length) {
    el.basketList.innerHTML = '<li class="basket-empty">Añade objetivos desde el panel de detalle '
      + 'para copiarlos o exportarlos juntos.</li>';
    return;
  }
  el.basketList.replaceChildren(...state.basket.map((id) => {
    const record = state.byId.get(id);
    const item = document.createElement('li');
    if (!record) { item.textContent = id; return item; }
    item.innerHTML = `
      <span class="b-code">${escapeHtml(record.code)}</span>
      <span class="b-st">${escapeHtml(statementFirstLine(record.statement))}</span>`;
    const remove = document.createElement('button');
    remove.className = 'ghost icon';
    remove.type = 'button';
    remove.innerHTML = '&times;';
    remove.setAttribute('aria-label', `Quitar ${record.code}`);
    remove.addEventListener('click', () => toggleBasket(id));
    item.append(remove);
    return item;
  }));
}

function exportBasket(format) {
  const records = state.basket.map((id) => state.byId.get(id)).filter(Boolean);
  return exportRecords(records, format);
}

async function copy(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    flash(message);
  } catch {
    flash('No se pudo copiar (permiso denegado)', true);
  }
}

let flashTimer = null;
function flash(message, isError = false) {
  el.status.hidden = false;
  el.status.textContent = message;
  el.status.classList.toggle('error', isError);
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { el.status.hidden = true; }, 2600);
}

/* ------------------------------------------------------------- selection */
function select(id, { reveal = false } = {}) {
  state.selected = id;
  const target = state.byId.get(id);
  if (target && isOat(target) !== (state.mode === 'oat')) {
    state.mode = isOat(target) ? 'oat' : 'oa';
    render();
  }
  if (reveal && !state.results.some((candidate) => candidate.oa_id === id)) {
    // The target is filtered out; widen just enough to show it.
    const record = state.byId.get(id);
    if (record) {
      focusOn(record);
      compute();
      renderFilters();
      renderResults();
    }
  }
  for (const row of el.list.querySelectorAll('.row')) {
    if (row.dataset.oa === id) row.setAttribute('aria-current', 'true');
    else row.removeAttribute('aria-current');
  }
  renderDetail();
  el.detail.scrollTop = 0;
  // Stacked on a phone, the detail pane sits below the whole result list, so
  // selecting something has to take the reader there.
  if (NARROW.matches) el.detail.scrollIntoView({ behavior: 'smooth', block: 'start' });
  writeHash();
}

/* ---------------------------------------------------------------- render */
function render() {
  compute();
  renderFilters();
  renderResults();
  renderDetail();
}

/* ------------------------------------------------------------------ boot */
function wire() {
  // The filter column is only collapsible on narrow screens; on desktop it is
  // the sidebar and the button is hidden by CSS.
  const applyNarrow = () => {
    el.filters.dataset.collapsed = String(NARROW.matches);
    el.filtersToggle.setAttribute('aria-expanded', String(!NARROW.matches));
  };
  applyNarrow();
  NARROW.addEventListener('change', applyNarrow);
  el.filtersToggle.addEventListener('click', () => {
    const collapsed = el.filters.dataset.collapsed === 'true';
    el.filters.dataset.collapsed = String(!collapsed);
    el.filtersToggle.setAttribute('aria-expanded', String(collapsed));
  });

  let debounce = null;
  el.q.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.query = el.q.value.trim();
      state.shown = PAGE;
      el.clearQ.hidden = !state.query;
      compute();
      renderResults();
      writeHash({ replace: true });
    }, 120);
  });
  el.q.closest('form').addEventListener('submit', (event) => event.preventDefault());
  el.clearQ.addEventListener('click', () => {
    state.query = '';
    el.q.value = '';
    el.q.focus();
    state.shown = PAGE;
    render();
    writeHash({ replace: true });
  });

  for (const [node, key] of [[el.subject, 'subject'], [el.strand, 'strand'],
    [el.statusFilter, 'status']]) {
    node.addEventListener('change', () => {
      state.filters[key] = node.value;
      if (key === 'subject') state.filters.strand = '';
      state.shown = PAGE;
      render();
      writeHash();
    });
  }
  for (const [node, key] of [[el.base, 'base'], [el.dimension, 'dimension']]) {
    node.addEventListener('change', () => {
      state.oatFilters[key] = node.value;
      if (key === 'base') state.oatFilters.dimension = '';
      state.shown = PAGE;
      render();
      writeHash();
    });
  }

  for (const [node, mode] of [[el.modeOa, 'oa'], [el.modeOat, 'oat']]) {
    node.addEventListener('click', () => {
      if (state.mode === mode) return;
      state.mode = mode;
      state.shown = PAGE;
      // The selection basket spans both modes, but a selected record from the
      // other mode has no row here to be current, so it is let go.
      if (state.byId.get(state.selected)?.kind !== (mode === 'oat' ? 'oat' : 'oa')) {
        state.selected = null;
      }
      render();
      writeHash();
    });
  }

  const showAbout = (open) => {
    el.about.hidden = !open;
    el.aboutToggle.setAttribute('aria-expanded', String(open));
    if (open) el.about.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  el.aboutToggle.addEventListener('click', () => showAbout(el.about.hidden));
  el.aboutOpen.addEventListener('click', () => showAbout(true));
  el.aboutClose.addEventListener('click', () => showAbout(false));
  for (const [node, key] of [[el.prioritized, 'prioritized'], [el.hasIndicators, 'indicators']]) {
    node.addEventListener('change', () => {
      state.only[key] = node.checked;
      state.shown = PAGE;
      render();
      writeHash();
    });
  }
  el.sort.addEventListener('change', () => {
    state.sort = el.sort.value;
    state.shown = PAGE;
    compute();
    renderResults();
    writeHash();
  });
  el.more.addEventListener('click', () => {
    state.shown += PAGE;
    renderResults();
  });
  el.reset.addEventListener('click', () => {
    state.query = '';
    state.filters = {
      level: '', subject: '', strand: '', category: '', track: '', status: '',
    };
    state.oatFilters = { base: '', dimension: '' };
    state.only = { prioritized: false, indicators: false };
    state.shown = PAGE;
    render();
    writeHash();
  });

  el.basketToggle.addEventListener('click', () => {
    const open = el.basket.hidden;
    el.basket.hidden = !open;
    el.basketToggle.setAttribute('aria-expanded', String(open));
  });
  el.basketClose.addEventListener('click', () => {
    el.basket.hidden = true;
    el.basketToggle.setAttribute('aria-expanded', 'false');
  });
  el.basketClear.addEventListener('click', () => {
    state.basket = [];
    try { localStorage.setItem('cn-basket', '[]'); } catch { /* ignore */ }
    renderBasket();
    renderDetail();
  });
  el.basketCopy.addEventListener('click', () => {
    const text = exportBasket(el.exportFormat.value);
    if (text) copy(text, `${state.basket.length} objetivo(s) copiados`);
  });
  el.basketDownload.addEventListener('click', () => {
    const format = el.exportFormat.value;
    const text = exportBasket(format);
    if (!text) return;
    const extension = FORMATS[format]?.extension ?? 'txt';
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `objetivos-seleccionados.${extension}`;
    anchor.click();
    URL.revokeObjectURL(url);
  });

  addEventListener('hashchange', () => {
    readHash();
    render();
  });
  addEventListener('keydown', (event) => {
    if (event.key === '/' && document.activeElement !== el.q) {
      event.preventDefault();
      el.q.focus();
      el.q.select();
    } else if (event.key === 'Escape') {
      if (!el.about.hidden) {
        el.about.hidden = true;
        el.aboutToggle.setAttribute('aria-expanded', 'false');
      } else if (!el.basket.hidden) {
        el.basket.hidden = true;
        el.basketToggle.setAttribute('aria-expanded', 'false');
      } else if (document.activeElement === el.q) {
        el.q.blur();
      }
    }
  });
}

async function boot() {
  initTheme();
  try {
    state.basket = JSON.parse(localStorage.getItem('cn-basket') ?? '[]');
  } catch { state.basket = []; }

  const messages = {
    manifest: 'Comprobando versión del dataset…',
    cache: 'Cargando desde la copia local…',
    download: 'Descargando el currículum (≈1,3 MB comprimido, solo la primera vez)…',
    ready: 'Indexando…',
  };

  let payload;
  try {
    payload = await loadDataset((stage) => {
      el.status.textContent = messages[stage] ?? 'Cargando…';
    });
  } catch (error) {
    el.status.classList.add('error');
    el.status.innerHTML = `No se pudo cargar el dataset: ${escapeHtml(String(error.message ?? error))}.
      <br>Esta aplicación necesita servirse por HTTP — <code>fetch()</code> está bloqueado en
      <code>file://</code>. Prueba <code>python3 -m http.server</code> en la raíz del repositorio.`;
    return;
  }

  const { data, source, manifest } = payload;
  const baseNames = {};
  for (const level of Object.values(data.levels ?? {})) {
    for (const subject of Object.values(level.subjects ?? {})) {
      if (subject.curriculum_base) {
        baseNames[subject.curriculum_base] = subject.curriculum_base_name
          ?? subject.curriculum_base;
      }
    }
  }

  state.records = flatten(data);
  state.postings = buildIndex(state.records);
  state.oats = flattenOats(data, baseNames);
  state.oatPostings = buildOatIndex(state.oats);
  for (const record of [...state.records, ...state.oats]) {
    state.byId.set(record.oa_id, record);
    if (record.code_slug && !state.byCodeSlug.has(record.code_slug)) {
      state.byCodeSlug.set(record.code_slug, record);
    }
  }

  const counts = new Map();
  for (const record of state.records) {
    counts.set(record.levelId, (counts.get(record.levelId) ?? 0) + 1);
  }
  state.levels = Object.entries(data.levels ?? {}).map(([id, level]) => ({
    id,
    name: level.level_name,
    short: level.level_name
      .replace('EPJA Nivel', 'EPJA')
      .replace(' Educación Básica', ' Bás.')
      .replace(' Educación Media', ' Med.')
      .replace(/\s*\([^)]*\)/, ''),
    count: counts.get(id) ?? 0,
  }));

  state.manifest = { ...(data.metadata ?? {}), ...(manifest ?? {}) };
  renderMeta(state.manifest);
  renderAbout(state.manifest);
  wire();
  readHash();
  render();
  renderBasket();

  el.app.hidden = false;
  el.status.hidden = true;
  if (source === 'cache-stale') {
    flash('Sin conexión: mostrando la última copia descargada.');
  }
  if (new URLSearchParams(location.search).has('reset-cache')) {
    await clearCache();
    flash('Copia local borrada. Recarga para descargar de nuevo.');
  }
}

boot();
