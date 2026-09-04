/**
 * Flattening and search.
 *
 * 4110 objectives and 13 705 indicators is small enough that a plain inverted
 * index built in JavaScript answers every query in well under a frame — no
 * SQLite-WASM, no search library. What matters instead is *how* text is folded:
 * teachers type "fotosintesis" and "celula" without accents, and the curriculum
 * is written with them, so every token is stored and queried NFD-folded.
 */

/** Fold to accent-free lowercase: "Fotosíntesis" -> "fotosintesis". */
export function fold(text) {
  return (text ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

const TOKEN = /[a-z0-9]+/g;

function tokenize(text) {
  return fold(text).match(TOKEN) ?? [];
}

/** One flat record per objective, with everything the UI needs to render a row. */
export function flatten(database) {
  const records = [];
  const levels = database.levels ?? {};
  let order = 0;

  for (const [levelId, level] of Object.entries(levels)) {
    for (const [subjectId, subject] of Object.entries(level.subjects ?? {})) {
      for (const objective of subject.learning_objectives ?? []) {
        records.push({
          idx: records.length,
          order: order++,
          oa_id: objective.oa_id,
          code: objective.code ?? '',
          code_slug: objective.code_slug ?? '',
          number: objective.oa_number ?? 0,
          category: objective.category,
          statement: objective.statement ?? '',
          strand: objective.strand_eje ?? '',
          strand_kind: objective.strand_kind ?? '',
          keywords: objective.keywords ?? [],
          prioritized: Boolean(objective.prioritized),
          indicators: objective.indicators ?? [],
          indicators_scope: objective.indicators_scope ?? null,
          indicators_source: objective.indicators_source ?? [],
          source_url: objective.source_url ?? '',
          levelId,
          levelName: level.level_name ?? levelId,
          subjectId,
          subjectName: subject.subject_name ?? subjectId,
          track: subject.track ?? '',
          curriculumBase: subject.curriculum_base ?? '',
          documents: subject.documents ?? [],
          modules: subject.modules ?? [],
        });
      }
    }
  }
  return records;
}

/**
 * Build the inverted index.
 *
 * Statements, codes, keywords, strand names *and* indicator text all feed it:
 * searching only objective titles would miss the 13 705 indicators, which are
 * usually the concrete wording a teacher is looking for.
 */
export function buildIndex(records) {
  const postings = new Map();
  const add = (token, idx) => {
    let list = postings.get(token);
    if (!list) postings.set(token, (list = []));
    if (list[list.length - 1] !== idx) list.push(idx);
  };

  for (const record of records) {
    const fields = [
      record.statement,
      record.code,
      record.strand,
      record.subjectName,
      record.levelName,
      record.keywords.join(' '),
      record.indicators.join(' '),
    ];
    for (const field of fields) {
      for (const token of tokenize(field)) add(token, record.idx);
    }
  }

  // Sorted postings let intersection be a linear merge.
  for (const list of postings.values()) list.sort((a, b) => a - b);
  return postings;
}

function intersect(lists) {
  lists.sort((a, b) => a.length - b.length);
  let acc = lists[0];
  for (let i = 1; i < lists.length && acc.length; i += 1) {
    const other = lists[i];
    const next = [];
    let a = 0;
    let b = 0;
    while (a < acc.length && b < other.length) {
      if (acc[a] === other[b]) { next.push(acc[a]); a += 1; b += 1; }
      else if (acc[a] < other[b]) a += 1;
      else b += 1;
    }
    acc = next;
  }
  return acc;
}

/** Prefix expansion, so "fracc" finds "fracciones" as you type. */
function expand(postings, token) {
  const exact = postings.get(token);
  if (exact && token.length < 3) return exact;
  const merged = new Set(exact ?? []);
  if (token.length >= 3) {
    for (const [candidate, list] of postings) {
      if (candidate.length > token.length && candidate.startsWith(token)) {
        for (const idx of list) merged.add(idx);
      }
    }
  }
  return [...merged].sort((a, b) => a - b);
}

/**
 * Score a hit. Deliberately simple and explainable: an official code match is
 * what someone typing "MA1M OA 01" wants above all else, then a statement hit,
 * then a keyword, then a hit that only appears in the indicators.
 */
function score(record, tokens) {
  const code = fold(record.code);
  const statement = fold(record.statement);
  const keywords = fold(record.keywords.join(' '));
  const strand = fold(record.strand);
  const indicators = fold(record.indicators.join(' '));
  let total = 0;
  for (const token of tokens) {
    if (code.includes(token)) total += 40;
    if (statement.startsWith(token)) total += 12;
    if (statement.includes(token)) total += 10;
    if (keywords.includes(token)) total += 5;
    if (strand.includes(token)) total += 3;
    if (indicators.includes(token)) total += 2;
  }
  if (record.prioritized) total += 1;
  return total;
}

export function search(records, postings, query) {
  const tokens = tokenize(query);
  if (!tokens.length) return null; // null = "no query", distinct from "no hits"

  const lists = tokens.map((token) => expand(postings, token));
  if (lists.some((list) => !list.length)) return [];

  const hits = intersect(lists);
  return hits
    .map((idx) => records[idx])
    .map((record) => ({ record, score: score(record, tokens) }))
    .sort((a, b) => b.score - a.score || a.record.order - b.record.order)
    .map((entry) => entry.record);
}

/** Highlight query tokens in a plain string, accent-insensitively. */
export function highlight(text, query) {
  const tokens = [...new Set(tokenize(query))].filter((token) => token.length >= 2);
  if (!tokens.length) return escapeHtml(text);

  const folded = fold(text);
  const spans = [];
  for (const token of tokens) {
    let from = 0;
    for (;;) {
      const at = folded.indexOf(token, from);
      if (at === -1) break;
      spans.push([at, at + token.length]);
      from = at + token.length;
    }
  }
  if (!spans.length) return escapeHtml(text);

  spans.sort((a, b) => a[0] - b[0]);
  const merged = [spans[0]];
  for (const [start, end] of spans.slice(1)) {
    const last = merged[merged.length - 1];
    if (start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }

  let out = '';
  let cursor = 0;
  for (const [start, end] of merged) {
    out += escapeHtml(text.slice(cursor, start));
    out += `<mark>${escapeHtml(text.slice(start, end))}</mark>`;
    cursor = end;
  }
  return out + escapeHtml(text.slice(cursor));
}

export function escapeHtml(text) {
  return (text ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
}
