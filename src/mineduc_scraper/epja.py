"""EPJA ingestion: fold Base Curricular PDF objectives into the dataset.

``bases_pdf`` reads the *Bases Curriculares para la Educación de Personas
Jóvenes y Adultas 2024*; this module decides where each parsed objective belongs
in the dataset and builds the records, keeping three rules that the source
imposes and the dataset must not paper over.

**Structured HTML wins.** curriculumnacional.cl publishes the objectives of one
EPJA page in HTML - Lenguaje y Comunicación, Nivel 1 de Educación Básica. Those
five records stay exactly as the HTML engine produced them; the PDF is used to
*verify* them (statement and eje must agree character for character) and then
stands aside. Re-ingesting them from the PDF would swap a structured source for
a less structured one for no gain.

**The level model is the Bases'.** Formación General subjects are defined per
(ciclo, nivel). Formación Instrumental and Formación Diferenciada
Humanístico-Científica subjects are defined once for "Educación Media, Nivel 1 y
2" - one block, not two - while the site navigates them under a Nivel 1 page and
a Nivel 2 page. Those objectives go into the combined ``epja_media`` level with
``level_scope`` naming the two site levels they cover, instead of being written
into each site level (which would duplicate every statement) or into one of them
(which would assert a split the Bases do not make).

**The Bases define more than the site navigates.** Several (asignatura, nivel)
pairs are defined in the Bases but have no page under
``/curriculum/bases-curriculares-.../<asignatura>/<nivel>``. Their objectives are
ingested and the subject is marked so a reader can see that the offering comes
from the Base document rather than from a site page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .bases_pdf import (
    EPJA_BASES_2024,
    EPJA_LEVEL_SCOPE,
    EPJA_LEVEL_TOKENS,
    BasesObjective,
    BasesSection,
)
from .normalize import canonical_oa_id, code_slug, extract_keywords, strand_id
from .provenance import status_for_base
from .taxonomy import (
    BASES,
    level_by_id,
    CATEGORY_CONOCIMIENTO,
    EPJA_FORMACION_DIFERENCIADA_HC,
    EPJA_FORMACION_DIFERENCIADA_TP,
    EPJA_FORMACION_LABEL,
    SOURCE_BASE_PDF,
    SYNTHETIC_LEVELS,
    TRACK_COMMON,
    TRACK_HC,
    TRACK_TP,
    slugify,
)

log = logging.getLogger(__name__)

BASE_SLUG = EPJA_BASES_2024["curriculum_base"]

EXTRACTION_METHOD = (
    "bases_pdf: sección 'Estructura curricular' de las Bases Curriculares "
    "(asignatura x ciclo x nivel), líneas 'OA n.' con su eje entre paréntesis"
)

# The Bases scope Formación Diferenciada subjects to a plan; General and
# Instrumental are part of every EPJA student's common plan.
_TRACK_BY_AREA = {
    EPJA_FORMACION_DIFERENCIADA_HC: TRACK_HC,
    EPJA_FORMACION_DIFERENCIADA_TP: TRACK_TP,
}


@dataclass
class EpjaReport:
    objectives_added: int = 0
    subjects_created: int = 0
    subjects_filled: int = 0
    levels_created: int = 0
    verified_against_html: int = 0
    html_mismatches: List[str] = field(default_factory=list)
    skipped_html_published: List[str] = field(default_factory=list)
    site_pages_deferred: List[dict] = field(default_factory=list)
    pages_not_defined: List[dict] = field(default_factory=list)
    sections: int = 0
    parser_problems: List[str] = field(default_factory=list)


def _subject_page_url(subject_slug: str, level_id: str) -> Optional[str]:
    """The site page for this (asignatura, nivel), when one exists."""
    from .taxonomy import LEVELS

    grade_slug = next(
        (slug for slug, level in LEVELS.items() if level.level_id == level_id), None
    )
    if grade_slug is None:
        return None
    return (
        f"https://www.curriculumnacional.cl/curriculum/{BASE_SLUG}/"
        f"{subject_slug}/{grade_slug}"
    )


def _objective_record(objective: BasesObjective, retrieved_at: str) -> dict:
    level_token = EPJA_LEVEL_TOKENS[objective.level_id]
    record = {
        "oa_id": canonical_oa_id(
            objective.subject_slug,
            level_token,
            CATEGORY_CONOCIMIENTO,
            objective.code,
            objective.number,
            objective.strand_eje,
            "Eje",
        ),
        "oa_number": objective.number,
        "category": CATEGORY_CONOCIMIENTO,
        # Exactly what the Bases print. EPJA objectives are numbered within
        # (asignatura, nivel); the site publishes a longer qualified form on the
        # one EPJA page it renders in HTML, but that abbreviation is not printed
        # in the Bases for any other asignatura and is not invented here.
        "code": objective.code,
        "code_slug": code_slug(objective.code),
        "statement": objective.statement,
        "keywords": extract_keywords(objective.statement),
        "prioritized": False,
        "source_url": EPJA_BASES_2024["landing_url"],
        "provenance": {
            "source_url": EPJA_BASES_2024["pdf_url"],
            "source_type": SOURCE_BASE_PDF,
            "source_document": EPJA_BASES_2024["title"],
            "source_page": objective.pdf_page,
            "curriculum_base": BASE_SLUG,
            "retrieved_at": retrieved_at,
            "extraction_method": EXTRACTION_METHOD,
        },
        **status_for_base(BASE_SLUG),
    }
    if objective.strand_eje:
        record["strand_eje"] = objective.strand_eje
        record["strand_id"] = strand_id(objective.strand_eje)
        record["strand_kind"] = "Eje"
    scope = EPJA_LEVEL_SCOPE.get(objective.level_id)
    if scope:
        record["level_scope"] = list(scope)
    return record


def _ensure_level(database: dict, level_id: str, report: EpjaReport) -> dict:
    """Return the level bucket, creating it if the crawl never produced one.

    Two ways a level can be absent. It can be the combined ``epja_media`` level,
    which no site page produces and only the Bases define. Or it can be a real
    site level that this particular build did not crawl - a ``--levels`` subset,
    or a nivel the Bases define an asignatura for that the site does not
    navigate. Both have to work: an objective the ministry publishes must not be
    dropped because the crawl frontier happened not to reach its level.
    """
    levels = database.setdefault("levels", {})
    if level_id in levels:
        return levels[level_id]
    known = level_by_id(level_id)
    if known is None:
        raise KeyError(f"unknown EPJA level {level_id!r}")
    report.levels_created += 1
    levels[level_id] = {
        "level_id": known.level_id,
        "level_name": known.level_name,
        "subjects": {},
    }
    if level_id in EPJA_LEVEL_SCOPE:
        levels[level_id]["level_scope"] = list(EPJA_LEVEL_SCOPE[level_id])
        levels[level_id]["level_note"] = (
            "Las Bases Curriculares EPJA 2024 definen estas asignaturas para la "
            "Educación Media como un solo bloque (Nivel 1 y 2). El sitio las navega "
            "bajo una página por nivel; aquí se publican una sola vez, indicando en "
            "level_scope los niveles del sitio a los que aplican."
        )
    return levels[level_id]


def _ensure_subject(
    level: dict, section: BasesSection, report: EpjaReport
) -> dict:
    subject_id = slugify(section.subject_slug)
    subject = level["subjects"].get(subject_id)
    page_url = _subject_page_url(section.subject_slug, section.level_id)
    if subject is None:
        report.subjects_created += 1
        subject = {
            "subject_id": subject_id,
            "subject_name": section.subject_name,
            "track": _TRACK_BY_AREA.get(section.formation_area, TRACK_COMMON),
            "curriculum_base": BASE_SLUG,
            "curriculum_base_name": BASES.get(BASE_SLUG),
            "source_url": page_url or EPJA_BASES_2024["landing_url"],
            "documents": [
                {
                    "doc_type": "Base curricular",
                    "title": EPJA_BASES_2024["title"],
                    "url": EPJA_BASES_2024["landing_url"],
                }
            ],
            "learning_objectives": [],
        }
        if page_url is None:
            subject["site_page_published"] = False
            subject["objectives_source_note"] = (
                "El sitio no publica una página para esta combinación de asignatura "
                "y nivel; los objetivos provienen de las Bases Curriculares EPJA 2024."
            )
        level["subjects"][subject_id] = subject
    else:
        report.subjects_filled += 1
        subject.setdefault("documents", []).append(
            {
                "doc_type": "Base curricular",
                "title": EPJA_BASES_2024["title"],
                "url": EPJA_BASES_2024["landing_url"],
            }
        )
        if section.formation_area in _TRACK_BY_AREA:
            subject["track"] = _TRACK_BY_AREA[section.formation_area]

    subject["formation_area"] = section.formation_area
    subject["formation_area_name"] = EPJA_FORMACION_LABEL.get(section.formation_area)
    subject["objectives_source"] = SOURCE_BASE_PDF
    subject.update(status_for_base(BASE_SLUG))
    if section.big_ideas:
        subject["big_ideas"] = section.big_ideas
    if section.essential_knowledge:
        subject["essential_knowledge"] = section.essential_knowledge
    return subject


def _verify_against_html(
    database: dict, section: BasesSection, report: EpjaReport
) -> bool:
    """Compare a PDF section with an HTML-published one; return True if it exists.

    Any disagreement is recorded rather than resolved: two official routes
    printing different text is a finding, not something a merge step should
    quietly pick a winner for.
    """
    subject = (
        database.get("levels", {})
        .get(section.level_id, {})
        .get("subjects", {})
        .get(slugify(section.subject_slug))
    )
    published = (subject or {}).get("learning_objectives") or []
    if not published:
        return False

    by_number = {obj.get("oa_number"): obj for obj in published}
    for objective in section.objectives:
        existing = by_number.get(objective.number)
        if existing is None:
            report.html_mismatches.append(
                f"{section.level_id}/{section.subject_slug} OA {objective.number}: "
                f"in the Bases (p{objective.pdf_page}) but not in the HTML page"
            )
            continue
        if existing.get("statement") != objective.statement:
            report.html_mismatches.append(
                f"{section.level_id}/{section.subject_slug} OA {objective.number}: "
                f"statement differs between the HTML page and the Bases "
                f"(p{objective.pdf_page})"
            )
        elif existing.get("strand_eje") != objective.strand_eje:
            report.html_mismatches.append(
                f"{section.level_id}/{section.subject_slug} OA {objective.number}: "
                f"eje differs ({existing.get('strand_eje')!r} in HTML, "
                f"{objective.strand_eje!r} in the Bases p{objective.pdf_page})"
            )
        else:
            report.verified_against_html += 1
    report.skipped_html_published.append(
        f"{section.level_id}/{section.subject_slug} "
        f"({len(published)} objetivos ya publicados en HTML)"
    )
    return True


def merge(
    database: dict,
    sections: List[BasesSection],
    retrieved_at: str,
    parser_problems: Optional[List[str]] = None,
) -> EpjaReport:
    """Fold parsed Base Curricular sections into the dataset."""
    report = EpjaReport(
        sections=len(sections), parser_problems=list(parser_problems or [])
    )

    for section in sections:
        if _verify_against_html(database, section, report):
            continue
        level = _ensure_level(database, section.level_id, report)
        subject = _ensure_subject(level, section, report)
        existing = {obj.get("code") for obj in subject["learning_objectives"]}
        for objective in section.objectives:
            if objective.code in existing:
                continue
            subject["learning_objectives"].append(
                _objective_record(objective, retrieved_at)
            )
            report.objectives_added += 1

    _annotate_deferred_pages(database, report)
    _annotate_undefined_pages(database, sections, report)
    return report


def _annotate_undefined_pages(
    database: dict, sections: List[BasesSection], report: EpjaReport
) -> None:
    """Record EPJA site pages the Bases define no objectives for.

    The site navigates a few (asignatura, nivel) pairs the 2024 Bases do not
    define - Ciencias Naturales has a Nivel 1 de Educación Básica page, but the
    asignatura only begins at Nivel 2. With the whole Base parsed, that is a
    fact the data can state rather than a hole to explain away: if no definition
    section exists for the pair, the ministry publishes no objectives for it.

    Derived from the parsed sections, never from a hardcoded list, so it stays
    correct when the Bases are revised.
    """
    defined = {(slugify(s.subject_slug), s.level_id) for s in sections}
    covered_levels = {
        level for levels in EPJA_LEVEL_SCOPE.values() for level in levels
    }

    for level_id, level in database.get("levels", {}).items():
        if not level_id.startswith("epja"):
            continue
        for subject_id, subject in level.get("subjects", {}).items():
            if subject.get("learning_objectives") or subject.get("no_objectives_reason"):
                continue
            if (subject_id, level_id) in defined:
                continue
            # A combined-level asignatura is handled by _annotate_deferred_pages.
            if level_id in covered_levels and any(
                subject_id == slugify(s.subject_slug) and s.level_id in EPJA_LEVEL_SCOPE
                for s in sections
            ):
                continue
            subject["no_objectives_reason"] = {
                "code": "not_defined_in_bases",
                "explanation": (
                    "El sitio navega esta página, pero las Bases Curriculares EPJA "
                    "2024 no definen objetivos de aprendizaje para esta asignatura "
                    "en este nivel: el documento no contiene una sección de "
                    "estructura curricular para esta combinación. Es ausencia de "
                    "fuente, no un fallo de extracción."
                ),
                "source_url": EPJA_BASES_2024["landing_url"],
                "source_document": EPJA_BASES_2024["title"],
                "verified_on": "2026-09-05",
            }
            subject["objectives_source"] = None
            report.pages_not_defined.append(
                {"level_id": level_id, "subject_id": subject_id}
            )


def _annotate_deferred_pages(database: dict, report: EpjaReport) -> None:
    """Explain the site pages whose objectives live in the combined level.

    A reader looking at "EPJA Nivel 1 Educación Media / Filosofía" on the site
    and finding no objectives here deserves to be told where they went, rather
    than being left to read it as a coverage hole.
    """
    for combined_id, covered in EPJA_LEVEL_SCOPE.items():
        combined = database.get("levels", {}).get(combined_id)
        if not combined:
            continue
        for subject_id in combined.get("subjects", {}):
            for level_id in covered:
                subject = (
                    database.get("levels", {})
                    .get(level_id, {})
                    .get("subjects", {})
                    .get(subject_id)
                )
                if subject is None or subject.get("learning_objectives"):
                    continue
                subject["objectives_in_level"] = combined_id
                subject["no_objectives_reason"] = {
                    "code": "objectives_defined_for_combined_level",
                    "explanation": (
                        "Las Bases Curriculares EPJA 2024 definen esta asignatura "
                        "para la Educación Media como un bloque único (Nivel 1 y 2). "
                        f"Sus objetivos se publican en el nivel {combined_id}."
                    ),
                    "source_url": EPJA_BASES_2024["landing_url"],
                    "verified_on": "2026-09-05",
                }
                report.site_pages_deferred.append(
                    {"level_id": level_id, "subject_id": subject_id,
                     "objectives_in_level": combined_id}
                )
