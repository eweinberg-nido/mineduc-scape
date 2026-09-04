"""Schema validation plus curriculum-specific integrity audits."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import jsonschema

from .oat import BASE_ID_TO_SLUG, EXPECTED_OAT_COUNTS
from .taxonomy import LEVELS

SCHEMA_PATH = Path(__file__).parent / "schema" / "mineduc_curriculum.schema.json"

# Independent ground truth: the counts MINEDUC's own JSON:API reports for its
# curriculum entities. Used as a coverage cross-check, not as a hard gate --
# the API counts every stored revision-visible entity, including bases whose
# objectives are PDF-only, so the HTML crawl is expected to land near, not on,
# these numbers.
JSONAPI_COUNTS = {
    "cn_learning_objective": 3139,
    "cn_skill": 27,
    "cn_attitude": 22,
    "cn_grade": 32,
    "cn_subject": 147,
    "paragraph/oat": 75,
}

# 75 OAT paragraphs exist, but one belongs to a superseded draft dimension that
# the published pages do not render; 74 is the live total.
EXPECTED_OAT_TOTAL = sum(EXPECTED_OAT_COUNTS.values())


def load_schema() -> dict:
    """Load the bundled JSON Schema."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_schema(database: dict) -> List[str]:
    """Return every schema violation, as human-readable strings."""
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = []
    for error in sorted(validator.iter_errors(database), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in error.path) or "<root>"
        errors.append(f"{path}: {error.message}")
    return errors


def _shape_errors(database: object) -> List[str]:
    """Reject input that is not a curriculum dataset, before auditing it.

    `validate` is pointed at arbitrary files (including the manifest written by
    `split`), so a wrong shape must produce a clear error rather than a
    traceback from deep inside the audit.
    """
    if not isinstance(database, dict):
        return ["root: expected a JSON object"]
    errors: List[str] = []
    levels = database.get("levels")
    if levels is None:
        errors.append(
            "root: no 'levels' key - this does not look like a curriculum dataset "
            "(the file written by `split` is a manifest, not a dataset)"
        )
        return errors
    if not isinstance(levels, dict):
        return ["levels: expected an object keyed by level_id"]
    for level_id, level in levels.items():
        if not isinstance(level, dict):
            errors.append(f"levels.{level_id}: expected an object")
            continue
        subjects = level.get("subjects")
        if not isinstance(subjects, dict):
            errors.append(f"levels.{level_id}.subjects: expected an object keyed by subject_id")
            continue
        for subject_id, subject in subjects.items():
            if not isinstance(subject, dict):
                errors.append(f"levels.{level_id}.subjects.{subject_id}: expected an object")
            elif not isinstance(subject.get("learning_objectives", []), list):
                errors.append(
                    f"levels.{level_id}.subjects.{subject_id}.learning_objectives: "
                    "expected an array"
                )
    return errors


def audit(database: dict) -> Tuple[List[str], List[str], Dict[str, object]]:
    """Run integrity assertions.

    Returns ``(errors, warnings, report)``. Errors mean the dataset is wrong
    (empty text, duplicate ids, broken counters); warnings mean it is
    incomplete in a way the source itself explains.
    """
    shape_errors = _shape_errors(database)
    if shape_errors:
        return shape_errors, [], {
            "total_objectives": 0, "by_category": {}, "by_level": {}, "levels": 0,
            "subjects": 0, "prioritized": 0, "with_strand": 0, "with_indicators": 0,
            "transversal_objectives": 0, "unique_oa_ids": 0,
            "distinct_official_codes": 0, "expected_oat_total": EXPECTED_OAT_TOTAL,
            "jsonapi_reference_counts": JSONAPI_COUNTS,
        }

    errors: List[str] = []
    warnings: List[str] = []

    oa_ids: Counter = Counter()
    distinct_codes: set = set()
    codes_per_subject: Dict[str, Counter] = defaultdict(Counter)
    by_category: Counter = Counter()
    by_level: Dict[str, int] = {}
    empty_subjects: List[str] = []
    total = 0
    prioritized = 0
    with_strand = 0
    with_indicators = 0
    indicator_count = 0
    tp_modules = 0
    tp_criteria = 0

    for level_id, level in database.get("levels", {}).items():
        if level.get("level_id") != level_id:
            errors.append(
                f"levels.{level_id}: level_id mismatch ({level.get('level_id')!r})"
            )
        known_level_ids = {lvl.level_id for lvl in LEVELS.values()}
        if level_id not in known_level_ids:
            warnings.append(f"levels.{level_id}: level not present in the taxonomy")

        level_count = 0
        for subject_id, subject in level.get("subjects", {}).items():
            if subject.get("subject_id") != subject_id:
                errors.append(
                    f"levels.{level_id}.subjects.{subject_id}: subject_id mismatch"
                )
            for module in subject.get("modules") or []:
                tp_modules += 1
                for learning in module.get("expected_learnings", []):
                    tp_criteria += len(learning.get("criteria") or [])
                    if not (learning.get("statement") or "").strip():
                        errors.append(
                            f"{level_id}/{subject_id}/módulo "
                            f"{module.get('module_number')}: empty aprendizaje esperado"
                        )
            objectives = subject.get("learning_objectives") or []
            if not objectives:
                empty_subjects.append(f"{level_id}/{subject_id}")
            for objective in objectives:
                total += 1
                level_count += 1
                where = f"{level_id}/{subject_id}/{objective.get('oa_id')}"
                oa_ids[objective.get("oa_id")] += 1
                by_category[objective.get("category")] += 1
                if objective.get("code"):
                    codes_per_subject[f"{level_id}/{subject_id}"][objective["code"]] += 1
                    distinct_codes.add(objective["code"])
                if not (objective.get("statement") or "").strip():
                    errors.append(f"{where}: empty statement")
                if not objective.get("code"):
                    errors.append(f"{where}: missing official code")
                if objective.get("oa_number", 0) < 1:
                    errors.append(f"{where}: oa_number must be >= 1")
                if objective.get("prioritized"):
                    prioritized += 1
                if objective.get("strand_eje"):
                    with_strand += 1
                if objective.get("indicators"):
                    with_indicators += 1
                    indicator_count += len(objective["indicators"])
                    if any(not str(i).strip() for i in objective["indicators"]):
                        errors.append(f"{where}: blank indicator text")
        by_level[level_id] = level_count

    for oa_id, count in oa_ids.items():
        if count > 1:
            errors.append(f"duplicate oa_id {oa_id!r} appears {count} times")

    for scope, codes in codes_per_subject.items():
        dupes = [code for code, count in codes.items() if count > 1]
        if dupes:
            warnings.append(
                f"{scope}: official code repeated within the subject: {', '.join(sorted(dupes))}"
            )

    metadata = database.get("metadata", {})
    if metadata.get("total_oas") != total:
        errors.append(
            f"metadata.total_oas={metadata.get('total_oas')} but {total} objectives found"
        )
    if metadata.get("total_by_category") and dict(by_category) != metadata["total_by_category"]:
        errors.append(
            f"metadata.total_by_category={metadata['total_by_category']} "
            f"but counted {dict(sorted(by_category.items()))}"
        )

    if empty_subjects:
        warnings.append(
            f"{len(empty_subjects)} subject page(s) publish no objectives in HTML "
            f"(their curriculum is PDF-only): {', '.join(empty_subjects[:8])}"
            + (" ..." if len(empty_subjects) > 8 else "")
        )
    for failure in metadata.get("failed_pages") or []:
        errors.append(f"page failed during scrape: {failure['url']} ({failure['error']})")

    # OAT audit
    oats = database.get("transversal_objectives") or {}
    oat_ids: Counter = Counter()
    oat_total = 0
    for base_slug, bucket in oats.items():
        if base_slug not in set(BASE_ID_TO_SLUG.values()):
            warnings.append(f"transversal_objectives.{base_slug}: unknown curriculum base")
        for oat in bucket:
            oat_total += 1
            oat_ids[oat.get("oat_id")] += 1
            if not (oat.get("statement") or "").strip():
                errors.append(f"OAT {oat.get('oat_id')}: empty statement")
    for oat_id, count in oat_ids.items():
        if count > 1:
            errors.append(f"duplicate oat_id {oat_id!r} appears {count} times")
    for base_slug, expected in EXPECTED_OAT_COUNTS.items():
        if base_slug not in oats:
            continue
        got = len(oats[base_slug])
        if got != expected:
            errors.append(
                f"transversal_objectives.{base_slug}: {got} OATs but the base "
                f"landing page publishes {expected}"
            )
    if oat_total and set(oats) >= set(EXPECTED_OAT_COUNTS) and oat_total != EXPECTED_OAT_TOTAL:
        errors.append(f"collected {oat_total} OATs, expected {EXPECTED_OAT_TOTAL}")

    if with_indicators == 0 and total:
        warnings.append(
            "no objective carries evaluation indicators: they live only in the "
            "Programa de Estudio PDFs - run `mineduc-scraper indicators`"
        )

    report = {
        "total_objectives": total,
        "by_category": dict(sorted(by_category.items())),
        "by_level": by_level,
        "levels": len(database.get("levels", {})),
        "subjects": sum(len(l.get("subjects", {})) for l in database.get("levels", {}).values()),
        "prioritized": prioritized,
        "with_strand": with_strand,
        "with_indicators": with_indicators,
        "indicators": indicator_count,
        "tp_modules": tp_modules,
        "tp_criteria": tp_criteria,
        "transversal_objectives": oat_total,
        "unique_oa_ids": len(oa_ids),
        "distinct_official_codes": len(distinct_codes),
        "expected_oat_total": EXPECTED_OAT_TOTAL,
        "jsonapi_reference_counts": JSONAPI_COUNTS,
    }
    return errors, warnings, report


def validate(database: dict) -> Tuple[List[str], List[str], Dict[str, object]]:
    """Schema validation followed by the integrity audit."""
    errors = [f"schema: {e}" for e in validate_schema(database)]
    audit_errors, warnings, report = audit(database)
    return errors + audit_errors, warnings, report
