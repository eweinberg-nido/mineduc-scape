-- Cookbook for the SQLite build:
--   mineduc-scraper export-sqlite -f data/mineduc_curriculum_full.json \
--       -o data/mineduc_curriculum.db
-- Runs unchanged under sqlite3 and SQLite-WASM.

-- What is in here?
SELECT key, value FROM metadata WHERE key LIKE 'total%';

-- Every objective for one subject at one level, in curriculum order.
SELECT code, strand_eje, statement
FROM objectives
WHERE level_id = '1_medio' AND subject_id = 'matematica'
ORDER BY category, strand_eje, oa_number;

-- Full-text search. The index uses unicode61/remove_diacritics=2,
-- so 'celula' also matches 'célula'.
SELECT o.code, o.level_id, o.subject_id, substr(o.statement, 1, 120) AS statement
FROM objectives_fts f
JOIN objectives o USING (oa_id)
WHERE objectives_fts MATCH 'fotosintesis OR respiracion'
ORDER BY rank
LIMIT 20;

-- Look up one official MINEDUC code across every level that uses it.
SELECT oa_id, level_id, subject_id, statement
FROM objectives
WHERE code = 'MA1M OA 01';

-- Coverage by level and category.
SELECT level_id, category, COUNT(*) AS n
FROM objectives
GROUP BY level_id, category
ORDER BY level_id, category;

-- Which subjects have the most objectives flagged for Priorización Curricular?
SELECT s.level_id, s.subject_name,
       SUM(o.prioritized) AS prioritized,
       COUNT(*)            AS total
FROM objectives o
JOIN subjects s ON s.level_id = o.level_id AND s.subject_id = o.subject_id
GROUP BY s.level_id, s.subject_id
HAVING prioritized > 0
ORDER BY prioritized DESC
LIMIT 15;

-- Skills (OAH) and attitudes (OAA) for a subject.
SELECT category, code, strand_eje, statement
FROM objectives
WHERE level_id = '1_medio' AND subject_id = 'matematica'
  AND category IN ('habilidad', 'actitud')
ORDER BY category, oa_number;

-- Transversal objectives that apply to a given subject.
SELECT t.code, t.dimension, t.statement
FROM transversal_objectives t
JOIN subjects s ON s.curriculum_base = t.curriculum_base
WHERE s.level_id = '1_medio' AND s.subject_id = 'matematica'
ORDER BY t.oat_number;

-- Evaluation indicators for one objective, in printed order.
SELECT i.position, i.scope, i.statement
FROM indicators i
JOIN objectives o USING (oa_id)
WHERE o.code = 'MA1M OA 01'
ORDER BY i.position;

-- Full-text search over the indicators, not just the objectives.
SELECT o.code, o.level_id, o.subject_id, substr(f.statement, 1, 120) AS indicator
FROM indicators_fts f
JOIN objectives o USING (oa_id)
WHERE indicators_fts MATCH 'fraccion OR fracciones'
LIMIT 20;

-- Indicator coverage by level: how much of each level is backed by a Programa?
SELECT o.level_id,
       COUNT(DISTINCT o.oa_id)                        AS objectives,
       COUNT(DISTINCT i.oa_id)                        AS with_indicators,
       COUNT(i.oa_id)                                 AS indicators
FROM objectives o
LEFT JOIN indicators i USING (oa_id)
GROUP BY o.level_id
ORDER BY o.level_id;

-- Objectives whose indicators are only attributed at unit level.
SELECT DISTINCT o.level_id, o.subject_id, o.code
FROM objectives o
JOIN indicators i USING (oa_id)
WHERE i.scope = 'unit'
LIMIT 15;

-- Técnico-Profesional: a speciality's módulos with their criteria counts.
SELECT m.module_number, m.module_name, m.hours, m.grade,
       COUNT(DISTINCT e.learning_key) AS aprendizajes_esperados,
       COUNT(c.position)              AS criterios
FROM tp_modules m
LEFT JOIN tp_expected_learnings e USING (module_key)
LEFT JOIN tp_criteria c USING (learning_key)
WHERE m.subject_id = 'especialidad_electricidad' AND m.level_id = '3_medio'
GROUP BY m.module_key
ORDER BY m.module_number;

-- Every Criterio de Evaluación for one Aprendizaje Esperado.
SELECT e.number, e.statement, c.position, c.statement AS criterio
FROM tp_expected_learnings e
JOIN tp_criteria c USING (learning_key)
JOIN tp_modules m USING (module_key)
WHERE m.subject_id = 'especialidad_electricidad' AND m.module_number = 1
ORDER BY e.number, c.position;

-- The source PDFs, if you want to check anything against the original.
SELECT level_id, subject_id, title, url
FROM documents
WHERE doc_type = 'Programa de estudio'
ORDER BY level_id, subject_id;
