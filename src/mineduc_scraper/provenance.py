"""Provenance, curriculum status and historical prioritization.

Three properties that the first version of this dataset either left implicit or
stated more confidently than the sources support:

**Provenance.** Every objective already carried a ``source_url``. That is not
enough to reproduce or audit a record: the same URL can be an HTML page, a
JSON:API resource or a link to a PDF, and a record read out of page 92 of a
Base Curricular has to say so. ``provenance`` makes all of it explicit and
uniform - source type, document, page, retrieval date, curriculum base, and the
extraction method that produced the text.

**Curriculum status.** ``vigente`` is a legal claim. A page being live on
curriculumnacional.cl today, or a scrape having run this morning, is evidence of
neither: the site publishes proposals, material in phased implementation and
superseded curricula on the same URLs and in the same markup. So status is never
inferred from reachability. Each curriculum base is assigned a status only where
an official source states one, that source is recorded next to it, and
everything else stays ``desconocido``.

**Prioritization.** ``prioritized: true`` read as a timeless property of an
objective, which it never was: it recorded membership of the *Priorización
Curricular* published for 2023-2025. The boolean is kept for backward
compatibility, but every flagged objective now also carries a ``prioritization``
object naming the programme, its period and its historical status, so a consumer
cannot render it as a bare, present-tense "Priorizado".
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .taxonomy import (
    SOURCE_BASE_PDF,
    SOURCE_HTML,
    SOURCE_JSONAPI,
    STATUS_DESCONOCIDO,
    STATUS_EN_IMPLEMENTACION,
    STATUS_HISTORICO,
    STATUS_PROPUESTA,
    STATUS_VIGENTE,
)

# --------------------------------------------------------------------------- #
# Curriculum status, per curriculum base
# --------------------------------------------------------------------------- #
# Every entry has to name the official source that states the status. A base
# with no such source is deliberately absent from this table and ends up
# `desconocido` - which is a weaker claim than the site's own presentation, and
# the honest one.
BASE_STATUS: Dict[str, dict] = {
    "educacion-parvularia": {
        "status": STATUS_VIGENTE,
        "source_url": "https://www.curriculumnacional.cl/recursos/educacion-parvularia-vigentes-2019",
        "note": "Bases Curriculares de Educación Parvularia, vigentes desde 2019 "
                "según la propia ficha del documento en curriculumnacional.cl.",
        "verified_on": "2026-09-05",
    },
    "1o-6o-basico": {
        "status": STATUS_VIGENTE,
        "source_url": "https://www.curriculumnacional.cl/curriculum/1o-6o-basico",
        "note": "Bases Curriculares de 1° a 6° Básico publicadas como bases "
                "curriculares vigentes en el índice de Bases Curriculares del sitio.",
        "verified_on": "2026-09-05",
    },
    "7o-basico-2o-medio": {
        "status": STATUS_VIGENTE,
        "source_url": "https://www.curriculumnacional.cl/curriculum/7o-basico-2o-medio",
        "note": "Bases Curriculares de 7° Básico a 2° Medio publicadas como bases "
                "curriculares vigentes en el índice de Bases Curriculares del sitio.",
        "verified_on": "2026-09-05",
    },
    "3o-4o-medio": {
        "status": STATUS_VIGENTE,
        "source_url": "https://www.curriculumnacional.cl/curriculum/3o-4o-medio",
        "note": "Bases Curriculares de 3° y 4° Medio publicadas como bases "
                "curriculares vigentes en el índice de Bases Curriculares del sitio.",
        "verified_on": "2026-09-05",
    },
    "3o-4o-medio-tecnico-profesional": {
        "status": STATUS_VIGENTE,
        "source_url": (
            "https://www.curriculumnacional.cl/curriculum/"
            "3o-4o-medio-tecnico-profesional"
        ),
        "note": "Bases Curriculares de la Formación Diferenciada Técnico-Profesional "
                "de 3° y 4° Medio publicadas como bases curriculares vigentes.",
        "verified_on": "2026-09-05",
    },
    "bases-curriculares-educacion-personas-jovenes-adultas-epja": {
        "status": STATUS_EN_IMPLEMENTACION,
        "source_url": (
            "https://www.curriculumnacional.cl/recursos/"
            "bases-curriculares-educacion-personas-jovenes-adultas-2024"
        ),
        "note": "Bases Curriculares EPJA 2024. El documento es el aprobado y "
                "publicado por la Unidad de Currículum y Evaluación; su entrada en "
                "aula es gradual, por lo que se registra como en implementación y "
                "no como vigente.",
        "verified_on": "2026-09-05",
    },
}

# The Lengua y Cultura base is published on the site but carries no statement of
# force that this project has verified, so it is left `desconocido` on purpose
# rather than assumed to match its host base.

PRIORITIZATION = {
    "programme": "Priorización Curricular",
    "period": "2023-2025",
    "status": STATUS_HISTORICO,
    "source_url": "https://www.curriculumnacional.cl/curriculum/priorizacion-curricular",
    "note": "Marca de pertenencia a la Priorización Curricular 2023-2025. Es un "
            "dato histórico: no significa que el objetivo forme parte de un "
            "subconjunto priorizado vigente.",
}


# --------------------------------------------------------------------------- #
# Status overrides that the site states at the subject level
# --------------------------------------------------------------------------- #
# curriculumnacional.cl publishes a parallel "Inglés (Propuesta)" subject
# alongside the in-force Inglés, across ten levels. The word is the ministry's
# own, printed in the subject name and in the URL slug: this is a proposed
# curriculum, not the one in force, and inheriting the curriculum base's
# `vigente` would have asserted the opposite of what the source says. The rule
# keys on the site's own naming rather than on a hardcoded subject list, so a
# future "(Propuesta)" subject is picked up without a code change.
SUBJECT_STATUS_MARKERS = (
    ("(propuesta)", "-propuesta", STATUS_PROPUESTA,
     "El sitio publica esta asignatura rotulada explícitamente como "
     "\"(Propuesta)\", en paralelo a la asignatura vigente del mismo nombre. Es "
     "una propuesta curricular, no el currículum en vigor."),
)


def status_for_subject(subject: dict) -> Optional[dict]:
    """A status the site states for this subject specifically, or ``None``.

    Only returns a status when the ministry itself labels the subject; there is
    no inference from a page merely existing.
    """
    name = (subject.get("subject_name") or "").lower()
    url = (subject.get("source_url") or "").lower()
    for name_marker, url_marker, status, note in SUBJECT_STATUS_MARKERS:
        if name_marker in name or url_marker in url:
            return {
                "curriculum_status": status,
                "status_source": {
                    "url": subject.get("source_url") or "",
                    "note": note,
                    "verified_on": "2026-09-05",
                },
            }
    return None


def status_for_base(base_slug: Optional[str]) -> dict:
    """Return ``{"curriculum_status", "status_source"}`` for a curriculum base."""
    entry = BASE_STATUS.get(base_slug or "")
    if entry is None:
        return {"curriculum_status": STATUS_DESCONOCIDO, "status_source": None}
    return {
        "curriculum_status": entry["status"],
        "status_source": {
            "url": entry["source_url"],
            "note": entry["note"],
            "verified_on": entry["verified_on"],
        },
    }


def make_provenance(
    *,
    source_url: str,
    source_type: str,
    curriculum_base: Optional[str],
    retrieved_at: str,
    extraction_method: str,
    source_document: Optional[str] = None,
    source_page: Optional[int] = None,
) -> dict:
    """Build one provenance record. All fields except the PDF ones are required."""
    record = {
        "source_url": source_url,
        "source_type": source_type,
        "curriculum_base": curriculum_base,
        "retrieved_at": retrieved_at,
        "extraction_method": extraction_method,
    }
    if source_document:
        record["source_document"] = source_document
    if source_page is not None:
        record["source_page"] = source_page
    return record


# --------------------------------------------------------------------------- #
# Backfill over an already-built dataset
# --------------------------------------------------------------------------- #
HTML_METHOD = "selectolax: div.items-wrapper > div.item-wrapper > span.oa-title"
JSONAPI_METHOD = "Drupal JSON:API paragraph/dimension -> paragraph/oat"


def annotate(database: dict) -> dict:
    """Attach provenance, status and prioritization metadata to every record.

    Idempotent, and never overwrites what an ingestion engine already recorded:
    an EPJA objective read from a Base Curricular PDF arrives with its own
    provenance (document, page, method) and keeps it. What this fills in is the
    records that predate the provenance model - the HTML-scraped objectives and
    the JSON:API OATs - whose source facts are known exactly from how the
    pipeline produced them.
    """
    metadata = database.setdefault("metadata", {})
    retrieved_at = metadata.get("scraped_at") or date.today().isoformat()

    counts = {
        "objectives": 0, "oats": 0, "already_had_provenance": 0,
        "prioritized": 0, "subject_status_overrides": 0,
    }

    for level in database.get("levels", {}).values():
        for subject in level.get("subjects", {}).values():
            base = subject.get("curriculum_base")
            # A status the site states for this subject beats the one inherited
            # from its curriculum base.
            override = status_for_subject(subject)
            if override:
                counts["subject_status_overrides"] += 1
            subject.update(override or status_for_base(base))
            for objective in subject.get("learning_objectives", []):
                counts["objectives"] += 1
                if objective.get("provenance"):
                    counts["already_had_provenance"] += 1
                else:
                    objective["provenance"] = make_provenance(
                        source_url=objective.get("source_url")
                        or subject.get("source_url", ""),
                        source_type=SOURCE_HTML,
                        curriculum_base=base,
                        retrieved_at=retrieved_at,
                        extraction_method=HTML_METHOD,
                    )
                objective.setdefault(
                    "curriculum_status",
                    subject.get("curriculum_status", STATUS_DESCONOCIDO),
                )
                if objective.get("status_source") is None:
                    objective["status_source"] = subject.get("status_source")
                if objective.get("prioritized"):
                    counts["prioritized"] += 1
                    objective["prioritization"] = dict(PRIORITIZATION)

    for base_slug, bucket in (database.get("transversal_objectives") or {}).items():
        status = status_for_base(base_slug)
        for oat in bucket:
            counts["oats"] += 1
            if not oat.get("provenance"):
                oat["provenance"] = make_provenance(
                    source_url="https://www.curriculumnacional.cl/jsonapi/paragraph/oat",
                    source_type=SOURCE_JSONAPI,
                    curriculum_base=base_slug,
                    retrieved_at=retrieved_at,
                    extraction_method=JSONAPI_METHOD,
                )
            oat.setdefault("curriculum_status", status["curriculum_status"])
            if oat.get("status_source") is None:
                oat["status_source"] = status["status_source"]

    metadata["prioritization"] = dict(PRIORITIZATION)
    return counts


__all__ = [
    "BASE_STATUS",
    "PRIORITIZATION",
    "annotate",
    "make_provenance",
    "status_for_base",
    "status_for_subject",
    "SOURCE_BASE_PDF",
]
