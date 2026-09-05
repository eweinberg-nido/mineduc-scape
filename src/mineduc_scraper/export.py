"""Output writers: full JSON, slim JSON, per-level split, and SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from .build import refresh_totals

SLIM_OBJECTIVE_FIELDS = ("oa_id", "oa_number", "category", "code", "strand_eje", "statement")

# Metadata a client needs to identify a build, without the audit payload.
MANIFEST_FIELDS = (
    "scraped_at", "built_at", "source_url", "schema_version", "generator",
    "dataset_variant",
    "total_oas", "total_by_category", "total_subjects", "total_levels", "total_oats",
)


def summarise(database: dict) -> dict:
    """Totals a client needs for a coverage panel, computed once at build time.

    The browser must not have to load 13 MB and recount to answer "how much of
    the curriculum is here?", and it must not hardcode the answer either. These
    are the numbers the panel shows, derived from the dataset itself:

    * `offerings` counts level x subject curriculum offerings, which is **not**
      the same as subjects - 372 offerings are roughly 120 distinct subjects
      taught across several levels, and labelling them "subjects" overstates the
      dataset by a factor of three.
    * EPJA and Religión get their own lines because they are the two areas whose
      coverage the previous build could not state.
    """
    by_source: Counter = Counter()
    by_status: Counter = Counter()
    distinct_codes: set = set()
    distinct_subjects: set = set()
    offerings = 0
    epja = religion = with_indicators = 0
    offerings_without_objectives = 0

    for level_id, level in (database.get("levels") or {}).items():
        for subject_id, subject in (level.get("subjects") or {}).items():
            offerings += 1
            distinct_subjects.add(subject.get("subject_name") or subject_id)
            objectives = subject.get("learning_objectives") or []
            if not objectives:
                offerings_without_objectives += 1
            if subject_id == "religion":
                religion += len(objectives)
            if level_id.startswith("epja"):
                epja += len(objectives)
            for objective in objectives:
                if objective.get("code"):
                    distinct_codes.add(objective["code"])
                if objective.get("indicators"):
                    with_indicators += 1
                provenance = objective.get("provenance") or {}
                by_source[provenance.get("source_type") or "unknown"] += 1
                by_status[objective.get("curriculum_status") or "desconocido"] += 1

    metadata = database.get("metadata") or {}
    coverage = metadata.get("coverage") or {}
    return {
        "total_offerings": offerings,
        "distinct_subjects": len(distinct_subjects),
        "distinct_official_codes": len(distinct_codes),
        "objectives_with_indicators": with_indicators,
        "total_epja_objectives": epja,
        "total_religion_objectives": religion,
        "offerings_without_objectives": offerings_without_objectives,
        "total_by_source_type": dict(sorted(by_source.items())),
        "status_summary": dict(sorted(by_status.items())),
        "coverage": coverage,
        "prioritization": metadata.get("prioritization"),
    }


def _manifest_metadata(database: dict) -> dict:
    """The identifying subset of metadata, plus the coverage-panel summary."""
    metadata = database.get("metadata", {})
    out = {key: metadata[key] for key in MANIFEST_FIELDS if key in metadata}
    indicators = metadata.get("indicators") or {}
    if indicators:
        out["total_indicators"] = indicators.get("total_indicators")
        out["objectives_with_indicators"] = indicators.get("objectives_with_indicators")
    modules = metadata.get("tp_modules") or {}
    if modules:
        out["total_modules"] = modules.get("modules")
        out["total_criteria"] = modules.get("criteria")

    out.update(summarise(database))

    # Known limitations, stated in the manifest so the panel can show them
    # without the app having to know what they are.
    limitations: List[dict] = []
    religion = metadata.get("religion") or {}
    if religion.get("pages_annotated"):
        limitations.append({
            "area": "Religión",
            "offerings": religion["pages_annotated"],
            "kind": "source_absent",
            "summary": "Religión se rige por el Decreto N° 924: cada credo tiene su "
                       "propio programa aprobado por el Ministerio, y esos programas "
                       "no se publican en curriculumnacional.cl.",
            "source_url": (religion.get("governing_document") or {}).get("landing_url"),
        })
    epja = metadata.get("epja_bases") or {}
    if epja.get("pages_not_defined_in_bases"):
        limitations.append({
            "area": "EPJA",
            "offerings": len(epja["pages_not_defined_in_bases"]),
            "kind": "source_absent",
            "summary": "El sitio navega páginas para las que las Bases Curriculares "
                       "EPJA 2024 no definen objetivos.",
            "source_url": epja.get("landing_url"),
        })
    for gap_kind, label in (("parser_gaps", "Sin objetivos y sin razón verificada"),
                            ("offerings_not_in_dataset", "Ofertas fuera del dataset")):
        count = (metadata.get("coverage") or {}).get(
            "parser_gaps" if gap_kind == "parser_gaps" else "offerings_not_in_dataset"
        )
        if count:
            limitations.append({
                "area": label, "offerings": count, "kind": "parser_gap",
                "summary": "Requiere revisión: la fuente puede publicar objetivos "
                           "que el parser no está leyendo.",
            })
    out["known_limitations"] = limitations
    out["oat_verification"] = {
        key: value
        for key, value in (metadata.get("oat_verification") or {}).items()
        if key in ("verified_on", "bases_with_oats", "bases_without_oats", "total",
                   "differences")
    }
    return out


def write_manifest(database: dict, path: Path, data_files: Optional[dict] = None) -> Path:
    """Write a small manifest describing this build.

    A browser client fetches this - a few hundred bytes - to decide whether the
    copy it already has in IndexedDB is current, instead of re-downloading the
    whole dataset to find out.
    """
    payload = _manifest_metadata(database)
    payload["files"] = data_files or {}
    return write_json(payload, path)


def write_json(database: dict, path: Path, indent: int = 2) -> Path:
    """Write the database as UTF-8 JSON with stable key order."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(database, ensure_ascii=False, indent=indent, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def _flatten_statement(statement: str) -> str:
    """Collapse a multi-line statement onto one line for LLM context blocks."""
    lines = [line.strip() for line in (statement or "").split("\n") if line.strip()]
    if not lines:
        return ""
    head, *rest = lines
    bullets = [re.sub(r"^-\s*", "", line).rstrip(".") for line in rest]
    if not bullets:
        return head
    separator = " " if head.rstrip().endswith((":", ";")) else " - "
    return head + separator + "; ".join(bullets) + "."


def to_slim(database: dict, with_indicators: bool = False) -> dict:
    """Build the lightweight variant: OAs only, one-line statements.

    Intended for shipping into a browser bundle or an LLM prompt builder, so
    indicators (which more than double the payload) are left out unless asked
    for. Técnico-Profesional módulos are always omitted.
    """
    slim = {
        "metadata": {
            **{
                key: value
                for key, value in database.get("metadata", {}).items()
                if key in ("scraped_at", "source_url", "schema_version", "generator",
                           "coverage_notes")
            },
            "dataset_variant": "slim",
            "total_oas": 0,
        },
        "levels": {},
    }
    for level_id, level in database.get("levels", {}).items():
        subjects: Dict[str, dict] = {}
        for subject_id, subject in level.get("subjects", {}).items():
            objectives: List[dict] = []
            for objective in subject.get("learning_objectives", []):
                slim_objective = {
                    key: objective[key]
                    for key in SLIM_OBJECTIVE_FIELDS
                    if key in objective
                }
                slim_objective["statement"] = _flatten_statement(objective.get("statement", ""))
                if with_indicators and objective.get("indicators"):
                    slim_objective["indicators"] = objective["indicators"]
                objectives.append(slim_objective)
            subjects[subject_id] = {
                "subject_id": subject["subject_id"],
                "subject_name": subject["subject_name"],
                "track": subject["track"],
                "learning_objectives": objectives,
            }
        slim["levels"][level_id] = {
            "level_id": level["level_id"],
            "level_name": level["level_name"],
            "subjects": subjects,
        }
    refresh_totals(slim)
    slim["metadata"]["dataset_variant"] = "slim"
    return slim


def split_by_level(database: dict, directory: Path) -> List[Path]:
    """Write one JSON file per level plus an index, for lazy client-side loading."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    # The index is a manifest, not a dataset: it deliberately does *not* use a
    # "levels" key, so it can never be mistaken for (or validated as) one.
    index = {
        "manifest_version": "1.0.0",
        # A manifest, not a copy of the dataset metadata: the audit payload
        # (every rejected indicator row) has no business in a file whose only
        # job is to say which level files exist.
        "metadata": _manifest_metadata(database),
        "files": {},
    }
    for level_id, level in database.get("levels", {}).items():
        payload = {
            "metadata": {
                **{
                    key: value
                    for key, value in database.get("metadata", {}).items()
                    if key in ("scraped_at", "source_url", "schema_version", "generator")
                },
                "level_id": level_id,
            },
            "levels": {level_id: level},
        }
        if database.get("transversal_objectives"):
            bases = {
                subject.get("curriculum_base")
                for subject in level.get("subjects", {}).values()
            }
            payload["transversal_objectives"] = {
                base: oats
                for base, oats in database["transversal_objectives"].items()
                if base in bases
            }
        refresh_totals(payload)
        written.append(write_json(payload, directory / f"{level_id}.json"))
        index["files"][level_id] = {
            "level_id": level_id,
            "level_name": level["level_name"],
            "file": f"{level_id}.json",
            "subjects": sorted(level.get("subjects", {})),
            "total_oas": payload["metadata"]["total_oas"],
        }
    written.append(write_json(index, directory / "index.json"))
    return written


SQLITE_DDL = """
PRAGMA journal_mode = MEMORY;

CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE levels (
    level_id   TEXT PRIMARY KEY,
    level_name TEXT NOT NULL
);

CREATE TABLE subjects (
    rowid_key            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id           TEXT NOT NULL,
    level_id             TEXT NOT NULL REFERENCES levels(level_id),
    subject_name         TEXT NOT NULL,
    track                TEXT NOT NULL,
    curriculum_base      TEXT,
    curriculum_base_name TEXT,
    source_url           TEXT,
    UNIQUE (level_id, subject_id)
);

CREATE TABLE objectives (
    oa_id       TEXT PRIMARY KEY,
    level_id    TEXT NOT NULL REFERENCES levels(level_id),
    subject_id  TEXT NOT NULL,
    oa_number   INTEGER NOT NULL,
    category    TEXT NOT NULL,
    code        TEXT,
    code_slug   TEXT,
    strand_eje  TEXT,
    strand_kind TEXT,
    statement   TEXT NOT NULL,
    keywords    TEXT,
    prioritized INTEGER NOT NULL DEFAULT 0,
    source_url  TEXT
);

CREATE TABLE transversal_objectives (
    oat_id          TEXT PRIMARY KEY,
    curriculum_base TEXT NOT NULL,
    oat_number      INTEGER,
    code            TEXT,
    dimension       TEXT NOT NULL,
    title           TEXT,
    statement       TEXT NOT NULL
);

CREATE TABLE indicators (
    oa_id      TEXT NOT NULL REFERENCES objectives(oa_id),
    position   INTEGER NOT NULL,
    scope      TEXT,
    statement  TEXT NOT NULL,
    PRIMARY KEY (oa_id, position)
);

CREATE TABLE tp_modules (
    module_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    level_id     TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    module_number INTEGER NOT NULL,
    module_name  TEXT NOT NULL,
    hours        INTEGER,
    grade        TEXT,
    objective_ids TEXT
);

CREATE TABLE tp_expected_learnings (
    learning_key INTEGER PRIMARY KEY AUTOINCREMENT,
    module_key   INTEGER NOT NULL REFERENCES tp_modules(module_key),
    number       INTEGER NOT NULL,
    statement    TEXT NOT NULL,
    generic_objectives TEXT
);

CREATE TABLE tp_criteria (
    learning_key INTEGER NOT NULL REFERENCES tp_expected_learnings(learning_key),
    position     INTEGER NOT NULL,
    statement    TEXT NOT NULL,
    PRIMARY KEY (learning_key, position)
);

CREATE TABLE documents (
    level_id   TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    doc_type   TEXT,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL
);

CREATE INDEX idx_objectives_subject ON objectives(level_id, subject_id);
CREATE INDEX idx_objectives_code ON objectives(code);
CREATE INDEX idx_objectives_category ON objectives(category);
CREATE INDEX idx_indicators_oa ON indicators(oa_id);
CREATE INDEX idx_tp_modules_subject ON tp_modules(level_id, subject_id);

CREATE VIRTUAL TABLE objectives_fts USING fts5(
    oa_id UNINDEXED, code, statement, keywords, strand_eje,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE VIRTUAL TABLE indicators_fts USING fts5(
    oa_id UNINDEXED, statement,
    tokenize = "unicode61 remove_diacritics 2"
);
"""


def _write_modules(connection, level_id: str, subject_id: str, subject: dict) -> None:
    """Insert a Técnico-Profesional subject's módulos and their criteria."""
    for module in subject.get("modules") or []:
        cursor = connection.execute(
            "INSERT INTO tp_modules (level_id, subject_id, module_number, module_name, "
            "hours, grade, objective_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                level_id, subject_id, module["module_number"], module["module_name"],
                module.get("hours"), module.get("grade"),
                " ".join(module.get("objective_ids") or []),
            ),
        )
        module_key = cursor.lastrowid
        for learning in module.get("expected_learnings", []):
            cursor = connection.execute(
                "INSERT INTO tp_expected_learnings (module_key, number, statement, "
                "generic_objectives) VALUES (?, ?, ?, ?)",
                (
                    module_key, learning["number"], learning["statement"],
                    " ".join(learning.get("generic_objectives") or []),
                ),
            )
            learning_key = cursor.lastrowid
            connection.executemany(
                "INSERT INTO tp_criteria (learning_key, position, statement) "
                "VALUES (?, ?, ?)",
                [
                    (learning_key, position, criterion)
                    for position, criterion in enumerate(
                        learning.get("criteria") or [], start=1
                    )
                ],
            )


def write_sqlite(database: dict, path: Path) -> Path:
    """Write a queryable SQLite build, including an FTS5 full-text index."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SQLITE_DDL)
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [
                (key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
                for key, value in database.get("metadata", {}).items()
            ],
        )
        for level_id, level in database.get("levels", {}).items():
            connection.execute(
                "INSERT INTO levels (level_id, level_name) VALUES (?, ?)",
                (level_id, level["level_name"]),
            )
            for subject_id, subject in level.get("subjects", {}).items():
                connection.execute(
                    "INSERT INTO subjects (subject_id, level_id, subject_name, track, "
                    "curriculum_base, curriculum_base_name, source_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        subject_id, level_id, subject["subject_name"], subject["track"],
                        subject.get("curriculum_base"), subject.get("curriculum_base_name"),
                        subject.get("source_url"),
                    ),
                )
                connection.executemany(
                    "INSERT INTO documents (level_id, subject_id, doc_type, title, url) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (level_id, subject_id, d.get("doc_type"), d["title"], d["url"])
                        for d in subject.get("documents", [])
                    ],
                )
                for objective in subject.get("learning_objectives", []):
                    keywords = " ".join(objective.get("keywords") or [])
                    connection.execute(
                        "INSERT INTO objectives (oa_id, level_id, subject_id, oa_number, "
                        "category, code, code_slug, strand_eje, strand_kind, statement, "
                        "keywords, prioritized, source_url) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            objective["oa_id"], level_id, subject_id, objective["oa_number"],
                            objective["category"], objective.get("code"),
                            objective.get("code_slug"), objective.get("strand_eje"),
                            objective.get("strand_kind"), objective["statement"],
                            keywords, int(bool(objective.get("prioritized"))),
                            objective.get("source_url"),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO objectives_fts (oa_id, code, statement, keywords, strand_eje) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            objective["oa_id"], objective.get("code") or "",
                            objective["statement"], keywords,
                            objective.get("strand_eje") or "",
                        ),
                    )
                    for position, indicator in enumerate(
                        objective.get("indicators") or [], start=1
                    ):
                        connection.execute(
                            "INSERT INTO indicators (oa_id, position, scope, statement) "
                            "VALUES (?, ?, ?, ?)",
                            (objective["oa_id"], position,
                             objective.get("indicators_scope"), indicator),
                        )
                        connection.execute(
                            "INSERT INTO indicators_fts (oa_id, statement) VALUES (?, ?)",
                            (objective["oa_id"], indicator),
                        )
                _write_modules(connection, level_id, subject_id, subject)
        for base_slug, bucket in (database.get("transversal_objectives") or {}).items():
            connection.executemany(
                "INSERT INTO transversal_objectives (oat_id, curriculum_base, oat_number, "
                "code, dimension, title, statement) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        oat["oat_id"], base_slug, oat.get("oat_number"), oat.get("code"),
                        oat["dimension"], oat.get("title"), oat["statement"],
                    )
                    for oat in bucket
                ],
            )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    return path
