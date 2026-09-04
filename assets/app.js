/**
 * Currículum Nacional navigator.
 *
 * A static, dependency-free app over the dataset this repository builds.
 * Three panes — filters, results, detail — plus a selection basket. State lives
 * in the URL hash, so every view and every objective is a shareable link.
 */

import { loadDataset, clearCache } from './store.js';
import { flatten, buildIndex, search, highlight, escapeHtml, fold } from './index.js';
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
};

const NARROW = matchMedia('(max-width: 62rem)');

const state = {
  records: [],
  postings: null,
  byId: new Map(),
  byCodeSlug: new Map(),
  levels: [],
  query: '',
  filters: { level: '', subject: '', strand: '', category: '', track: '' },
  only: { prioritized: false, indicators: false },
  sort: 'relevance',
  shown: PAGE,
  results: [],
  selected: null,
  basket: [],
};

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

  state.query = params.get('q') ?? '';
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

/** Point the filters at one objective's own level and subject. */
function focusOn(record) {
  state.selected = record.oa_id;
  state.filters.level = record.levelId;
  // The subject filter is keyed on the display name, because that is what the
  // <select> offers and what usefully spans curriculum bases.
  state.filters.subject = record.subjectName;
  state.filters.strand = '';
  state.filters.category = '';
  state.filters.track = '';
  state.only = { prioritized: false, indicators: false };
  state.query = '';
}

function writeHash({ replace = false } = {}) {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
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
  const { level, subject, strand, category, track } = state.filters;
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
  const found = search(state.records, state.postings, state.query);
  const pool = found ?? state.records;
  let results = pool.filter(matches);

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

function renderFilters() {
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
  el.sort.value = state.sort;
  el.q.value = state.query;
  el.clearQ.hidden = !state.query;
}

function fillSelect(select, allLabel, values, current, key) {
  select.replaceChildren();
  const all = document.createElement('option');
  all.value = '';
  all.textContent = allLabel;
  select.append(all);
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  select.value = values.includes(current) ? current : '';
  // The active value can fall out of range when another filter narrows things;
  // drop it rather than leaving a filter applied that the UI cannot show.
  if (current && select.value !== current) state.filters[key] = '';
}

function renderMeta(manifest) {
  const rows = [
    ['Objetivos', manifest.total_oas?.toLocaleString('es-CL')],
    ['Indicadores', manifest.total_indicators?.toLocaleString('es-CL')],
    ['Criterios TP', manifest.total_criteria?.toLocaleString('es-CL')],
    ['Asignaturas', manifest.total_subjects?.toLocaleString('es-CL')],
    ['Actualizado', manifest.scraped_at?.slice(0, 10)],
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
  el.count.textContent = total
    ? `${total.toLocaleString('es-CL')} objetivo${total === 1 ? '' : 's'}`
    : '';
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
  if (record.category !== 'conocimiento') {
    badges.push(`<span class="badge cat-${record.category}">${CATEGORY_LABEL[record.category]}</span>`);
  }
  if (record.prioritized) badges.push('<span class="badge prio">Priorizado</span>');
  if (record.indicators.length) {
    badges.push(`<span class="badge ind">${record.indicators.length} indicador${record.indicators.length === 1 ? '' : 'es'}</span>`);
  }

  button.innerHTML = `
    <span class="row-top">
      <span class="code">${highlight(record.code, state.query)}</span>
      <span class="row-where">${escapeHtml(record.levelName)} · ${escapeHtml(record.subjectName)}${record.strand ? ` · ${escapeHtml(record.strand)}` : ''}</span>
    </span>
    <p class="row-statement">${highlight(statementFirstLine(record.statement), state.query)}</p>
    ${badges.length ? `<span class="row-meta">${badges.join('')}</span>` : ''}
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

function renderDetail() {
  const record = state.byId.get(state.selected);
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
      ${record.prioritized ? ' · <strong>Priorización curricular</strong>' : ''}
    </p>
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

  el.detail.querySelector('[data-act="basket"]')?.addEventListener('click', () => {
    toggleBasket(record.oa_id);
    renderDetail();
  });
  el.detail.querySelector('[data-act="copy"]')?.addEventListener('click', () => {
    copy(formatOne(record), 'Objetivo copiado');
  });
  el.detail.querySelector('[data-act="link"]')?.addEventListener('click', () => {
    copy(`${location.origin}${location.pathname}#${encodeURIComponent(record.code_slug || record.oa_id)}`,
      'Enlace copiado');
  });
  for (const button of el.detail.querySelectorAll('[data-goto]')) {
    button.addEventListener('click', () => select(button.dataset.goto, { reveal: true }));
  }
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

  for (const [node, key] of [[el.subject, 'subject'], [el.strand, 'strand']]) {
    node.addEventListener('change', () => {
      state.filters[key] = node.value;
      if (key === 'subject') state.filters.strand = '';
      state.shown = PAGE;
      render();
      writeHash();
    });
  }
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
    state.filters = { level: '', subject: '', strand: '', category: '', track: '' };
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
      if (!el.basket.hidden) {
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
  state.records = flatten(data);
  state.postings = buildIndex(state.records);
  for (const record of state.records) {
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

  renderMeta({ ...(data.metadata ?? {}), ...(manifest ?? {}) });
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
