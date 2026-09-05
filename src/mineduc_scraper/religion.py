"""Religión: what the sources actually publish, recorded as a finding.

Twelve subject pages on curriculumnacional.cl offer Religión (1° a 6° Básico,
7° Básico a 2° Medio, and 3°/4° Medio Formación General) and none of them
renders an "Explorar Base Curricular" section. That was previously logged as a
page that "publishes no objectives", indistinguishable from a parser gap. It is
neither a parser gap nor an oversight, and the sources say so explicitly.

What the investigation found:

* Every Religión page carries exactly two curricular documents: **Decreto N° 924
  (1983)**, and the general *Planes de Estudio Vigentes*. No Bases Curriculares,
  no Programa de Estudio, no objectives.
* Decreto 924 art. 4 permits the teaching of *any* credo, and art. 6 states that
  Religión "se impartirá de conformidad a los programas de estudio aprobados por
  el Ministerio de Educación Pública, **a propuesta de la autoridad religiosa
  correspondiente**". So there is no single national Religión curriculum to
  ingest: there is one approved programme per religious confession, each
  proposed by that confession, and the plurality is the structure.
* Those confession-specific programmes are not published on
  curriculumnacional.cl. A JSON:API query across the site's whole `node--recurso`
  collection for titles containing "Religi" returns 16 resources - teaching
  materials, historical readings and the decreto itself - and no programme or
  base for the subject.

The right outcome is therefore *not* to invent objectives, nor to merge
different confessions' programmes into one artificial subject. It is to record,
on each Religión subject, a source-backed reason for the absence and the
programme model the decreto establishes, so the coverage report can classify
these twelve pages as **source absence** rather than parser failure.
"""

from __future__ import annotations

from typing import Dict, List

SUBJECT_ID = "religion"

DECRETO_924 = {
    "title": "Decreto N° 924 (1983): Reglamenta clases de religión en "
             "establecimientos educacionales",
    "landing_url": (
        "https://www.curriculumnacional.cl/recursos/"
        "decreto-no-924-reglamenta-clases-religion-establecimientos-educacionales"
    ),
    "pdf_url": (
        "https://www.curriculumnacional.cl/sites/default/files/adjuntos/recursos/"
        "2025-01/propertyvalues-176736_decreto.pdf"
    ),
}

# The programme model the decreto establishes. Modelled explicitly rather than
# collapsed into a single "Religión" curriculum, because the decreto's whole
# point is that there is one approved programme per confession.
PROGRAMME_MODEL = {
    "model": "por_credo",
    "governed_by": "Decreto N° 924 (1983), Ministerio de Educación",
    "approval": (
        "Los programas de estudio de Religión son propuestos por cada autoridad "
        "religiosa y aprobados por el Ministerio de Educación (art. 6). Cada credo "
        "tiene su propio programa aprobado; no existe un currículum nacional único "
        "de Religión."
    ),
    "optional_for_students": True,
    "shared_national_objectives": False,
    "published_on_curriculumnacional": False,
}

NO_OBJECTIVES_REASON = {
    "code": "governed_separately_no_published_objectives",
    "explanation": (
        "Religión no forma parte de las Bases Curriculares nacionales. Se rige por "
        "el Decreto N° 924 (1983), que permite la enseñanza de cualquier credo "
        "(art. 4) y establece que se imparte conforme a programas de estudio "
        "propuestos por cada autoridad religiosa y aprobados por el Ministerio de "
        "Educación (art. 6). Esos programas por credo no se publican en "
        "curriculumnacional.cl: las páginas de Religión del sitio solo enlazan el "
        "decreto y los Planes de Estudio vigentes, y una consulta a la JSON:API del "
        "sitio sobre toda la colección de recursos no devuelve ningún programa ni "
        "base curricular de la asignatura. Por lo tanto no hay objetivos de "
        "aprendizaje oficiales que ingerir: es ausencia de fuente, no un fallo del "
        "parser."
    ),
    "source_url": DECRETO_924["landing_url"],
    "source_document": DECRETO_924["title"],
    "evidence_urls": [
        DECRETO_924["pdf_url"],
        "https://www.curriculumnacional.cl/jsonapi/node/recurso"
        "?filter[t][condition][path]=title"
        "&filter[t][condition][operator]=CONTAINS"
        "&filter[t][condition][value]=Religi",
    ],
    "verified_on": "2026-09-05",
}


def annotate(database: dict) -> Dict[str, object]:
    """Record the Religión finding on every Religión subject in the dataset."""
    touched: List[str] = []
    with_objectives: List[str] = []

    for level_id, level in database.get("levels", {}).items():
        for subject_id, subject in level.get("subjects", {}).items():
            if subject_id != SUBJECT_ID:
                continue
            if subject.get("learning_objectives"):
                # Nothing to explain away: if the site ever starts publishing
                # them, the finding must not overwrite real data.
                with_objectives.append(f"{level_id}/{subject_id}")
                continue
            subject["programme_model"] = dict(PROGRAMME_MODEL)
            subject["no_objectives_reason"] = dict(NO_OBJECTIVES_REASON)
            subject["objectives_source"] = None
            touched.append(f"{level_id}/{subject_id}")

    return {
        "pages_annotated": len(touched),
        "pages": touched,
        "pages_with_objectives": with_objectives,
        "programme_model": dict(PROGRAMME_MODEL),
        "governing_document": DECRETO_924,
    }
