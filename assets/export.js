/**
 * Export formatting for the selection basket.
 *
 * Kept as pure functions over plain records so the formats can be tested
 * without a browser: `node --test assets/export.test.js`.
 */

const TRACK_LABEL = {
  plan_comun: 'Plan común',
  plan_diferenciado_hc: 'Diferenciado HC',
  plan_diferenciado_tp: 'Técnico-Profesional',
};

export const FORMATS = {
  markdown: { label: 'Markdown', extension: 'md' },
  text: { label: 'Texto plano', extension: 'txt' },
  prompt: { label: 'Bloque para LLM', extension: 'txt' },
  csv: { label: 'CSV', extension: 'csv' },
  json: { label: 'JSON', extension: 'json' },
};

/** One objective as indented plain text, indicators included. */
export function formatOne(record) {
  const lines = [`[${record.code}] ${record.statement.replace(/\n/g, '\n  ')}`];
  if (record.indicators?.length) {
    lines.push('Indicadores de evaluación:');
    for (const indicator of record.indicators) lines.push(`  - ${indicator}`);
  }
  return lines.join('\n');
}

function csvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

export function toCsv(records) {
  const header = ['code', 'level', 'subject', 'strand', 'category', 'statement', 'indicators'];
  const rows = records.map((record) => [
    record.code,
    record.levelName,
    record.subjectName,
    record.strand,
    record.category,
    record.statement.replace(/\n/g, ' '),
    (record.indicators ?? []).join(' | '),
  ].map(csvCell).join(','));
  return [header.join(','), ...rows].join('\n');
}

export function toJson(records) {
  return JSON.stringify(records.map((record) => ({
    oa_id: record.oa_id,
    code: record.code,
    level: record.levelName,
    subject: record.subjectName,
    strand: record.strand,
    category: record.category,
    statement: record.statement,
    indicators: record.indicators ?? [],
    source_url: record.source_url,
  })), null, 2);
}

export function toMarkdown(records) {
  return records.map((record) => {
    const head = `### ${record.code} — ${record.subjectName}, ${record.levelName}`;
    const where = record.strand
      ? `*${record.strand_kind || 'Eje'}: ${record.strand}*\n`
      : '';
    const statement = record.statement
      .split('\n')
      .map((line, at) => (at === 0 ? line : line.replace(/^-\s*/, '- ')))
      .join('\n');
    const indicators = record.indicators?.length
      ? `\n**Indicadores de evaluación**\n${record.indicators.map((i) => `- ${i}`).join('\n')}\n`
      : '';
    return `${head}\n${where}\n${statement}\n${indicators}`;
  }).join('\n---\n\n');
}

/** A context block for an LLM prompt: one line per objective, no markup. */
export function toPrompt(records) {
  return [
    'Currículum nacional chileno (MINEDUC). Objetivos de Aprendizaje seleccionados:',
    '',
    ...records.map((record) => {
      const head = `[${record.code}] ${record.subjectName} · ${record.levelName}`
        + ` · ${TRACK_LABEL[record.track] ?? record.track}`;
      const statement = record.statement.replace(/\n\s*-\s*/g, '; ').replace(/\n/g, ' ');
      const indicators = record.indicators?.length
        ? `\nIndicadores: ${record.indicators.join(' ')}`
        : '';
      return `${head}\n${statement}${indicators}`;
    }),
    '',
    'Fuente: curriculumnacional.cl',
  ].join('\n');
}

export function toText(records) {
  return records.map(formatOne).join('\n\n');
}

export function exportRecords(records, format) {
  if (!records.length) return '';
  switch (format) {
    case 'json': return toJson(records);
    case 'csv': return toCsv(records);
    case 'prompt': return toPrompt(records);
    case 'markdown': return toMarkdown(records);
    default: return toText(records);
  }
}
