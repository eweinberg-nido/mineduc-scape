/**
 * Local-first helpers for the mineduc-curriculum-db dataset.
 *
 * Works with either variant:
 *   - mineduc_curriculum_slim.json  (small; OAs with one-line statements)
 *   - mineduc_curriculum_full.json  (everything: keywords, ejes, documents, OATs)
 *
 * No dependencies, no build step. Import the JSON and go.
 */

/** @typedef {{ oa_id: string, oa_number: number, category: string, code?: string,
 *              strand_eje?: string, statement: string, keywords?: string[],
 *              prioritized?: boolean }} Objective */

/** Every objective for one subject at one level. */
export function getSubjectOAs(db, levelId, subjectId) {
  return db.levels?.[levelId]?.subjects?.[subjectId]?.learning_objectives ?? [];
}

/** Objective ids are globally unique, so a flat index is the fastest lookup. */
export function buildIndex(db) {
  const byId = new Map();
  const byCode = new Map();
  for (const [levelId, level] of Object.entries(db.levels ?? {})) {
    for (const [subjectId, subject] of Object.entries(level.subjects ?? {})) {
      for (const oa of subject.learning_objectives ?? []) {
        const entry = { ...oa, levelId, subjectId, subjectName: subject.subject_name };
        byId.set(oa.oa_id, entry);
        // Official codes repeat across levels (an OA spanning 3° and 4° Medio),
        // so a code maps to a list.
        if (oa.code) {
          if (!byCode.has(oa.code)) byCode.set(oa.code, []);
          byCode.get(oa.code).push(entry);
        }
      }
    }
  }
  return { byId, byCode };
}

/** Catalogue for building level/subject pickers. */
export function listSubjects(db, levelId) {
  const subjects = db.levels?.[levelId]?.subjects ?? {};
  return Object.values(subjects).map((s) => ({
    subject_id: s.subject_id,
    subject_name: s.subject_name,
    track: s.track,
    count: (s.learning_objectives ?? []).length,
  }));
}

/**
 * Accent-insensitive substring search across statements, codes and keywords.
 * Fine for the slim dataset in memory; use the SQLite/FTS5 build for anything larger.
 */
export function search(db, query, { levelId, subjectId, category, limit = 50 } = {}) {
  const needle = fold(query);
  if (!needle) return [];
  const results = [];
  for (const [lid, level] of Object.entries(db.levels ?? {})) {
    if (levelId && lid !== levelId) continue;
    for (const [sid, subject] of Object.entries(level.subjects ?? {})) {
      if (subjectId && sid !== subjectId) continue;
      for (const oa of subject.learning_objectives ?? []) {
        if (category && oa.category !== category) continue;
        const haystack = fold(
          [oa.statement, oa.code, oa.strand_eje, (oa.keywords ?? []).join(' ')].join(' '),
        );
        if (!haystack.includes(needle)) continue;
        results.push({ ...oa, levelId: lid, subjectId: sid });
        if (results.length >= limit) return results;
      }
    }
  }
  return results;
}

function fold(text) {
  return (text ?? '')
    .toString()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

/**
 * Context block for an LLM prompt. Official codes are used as the citation
 * handle, because that is what teachers and ministry documents cite.
 */
export function buildLLMContext(db, levelId, subjectId, { category, prioritizedOnly } = {}) {
  const level = db.levels?.[levelId];
  const subject = level?.subjects?.[subjectId];
  if (!subject) return '';

  let objectives = subject.learning_objectives ?? [];
  if (category) objectives = objectives.filter((oa) => oa.category === category);
  if (prioritizedOnly) objectives = objectives.filter((oa) => oa.prioritized);

  const header = `# ${subject.subject_name} — ${level.level_name} (${subject.track})`;
  const lines = objectives.map((oa) => {
    const label = oa.code ?? oa.oa_id;
    const eje = oa.strand_eje ? ` (${oa.strand_eje})` : '';
    return `[${label}]${eje} ${oa.statement.replace(/\n/g, ' ')}`;
  });
  return [header, ...lines].join('\n');
}

/**
 * Objectives that carry Indicadores de Evaluación, with their scope.
 * `indicators_scope` is 'objective' when the Programa pairs the objective with
 * its own set, or 'unit' when one set covers a group of objectives jointly.
 */
export function withIndicators(db, levelId, subjectId, { scope } = {}) {
  return getSubjectOAs(db, levelId, subjectId).filter(
    (oa) => (oa.indicators ?? []).length && (!scope || oa.indicators_scope === scope),
  );
}

/** Prompt block that pairs each objective with its indicators. */
export function buildIndicatorContext(db, levelId, subjectId) {
  return withIndicators(db, levelId, subjectId)
    .map((oa) => {
      const head = `[${oa.code ?? oa.oa_id}] ${oa.statement.replace(/\n/g, ' ')}`;
      const items = oa.indicators.map((i) => `  - ${i}`).join('\n');
      return `${head}\n${items}`;
    })
    .join('\n\n');
}

/**
 * Técnico-Profesional módulos for a speciality. These carry Aprendizajes
 * Esperados and Criterios de Evaluación instead of per-objective indicators.
 */
export function getModules(db, levelId, subjectId) {
  return db.levels?.[levelId]?.subjects?.[subjectId]?.modules ?? [];
}

/** Every Criterio de Evaluación in a speciality, flattened. */
export function getCriteria(db, levelId, subjectId) {
  return getModules(db, levelId, subjectId).flatMap((module) =>
    (module.expected_learnings ?? []).flatMap((learning) =>
      (learning.criteria ?? []).map((criterion) => ({
        module: module.module_number,
        moduleName: module.module_name,
        expectedLearning: learning.number,
        criterion,
      })),
    ),
  );
}

/** Transversal objectives apply per curriculum base, not per subject. */
export function getTransversalObjectives(db, levelId, subjectId) {
  const base = db.levels?.[levelId]?.subjects?.[subjectId]?.curriculum_base;
  return base ? db.transversal_objectives?.[base] ?? [] : [];
}
