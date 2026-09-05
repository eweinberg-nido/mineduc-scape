"""Crawl orchestration: discovery -> extraction -> normalization -> assembly."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import SCHEMA_VERSION, SOURCE_URL, __version__
from .extract import BASE_URL, RawObjective, RawPage, parse_index_page, parse_subject_page
from .http import PoliteClient
from .normalize import canonical_oa_id, code_slug, extract_keywords, objective_number, strand_id
from .oat import fetch_transversal_objectives
from .provenance import (
    HTML_METHOD,
    PRIORITIZATION,
    make_provenance,
    status_for_base,
    status_for_subject,
)
from .taxonomy import BASES, SOURCE_HTML, level_for, slugify, track_for

log = logging.getLogger(__name__)

INDEX_PATH = "/curriculum/ambitos-y-asignaturas"

# Evaluation indicators (indicadores de evaluacion) are published only inside
# the "Programa de Estudio" PDFs, never in the site's HTML or JSON:API. The
# links to those PDFs are captured per subject in `documents`.
INDICATOR_NOTE = (
    "Los indicadores de evaluación no se publican en HTML ni en la JSON:API de "
    "curriculumnacional.cl: sólo existen dentro de los PDF de los Programas de "
    "Estudio, cuyos enlaces quedan registrados en subjects[].documents. "
    "Ejecute `mineduc-scraper indicators` para extraerlos e incorporarlos."
)

# Replaces INDICATOR_NOTE once the indicator pass has run.
INDICATOR_SOURCE_NOTE = (
    "Los indicadores de evaluación provienen de los PDF de los Programas de "
    "Estudio publicados en curriculumnacional.cl; cada objetivo registra su "
    "PDF de origen en indicators_source. La correspondencia se verifica "
    "comparando el enunciado impreso en el PDF con el publicado en HTML, "
    "porque los Programas de 1° a 6° Básico numeran los objetivos según un "
    "decreto anterior al vigente."
)

# Added once the Técnico-Profesional module pass has run.
TP_MODULE_NOTE = (
    "Los Programas de Estudio Técnico-Profesional no publican indicadores de "
    "evaluación por objetivo: organizan cada especialidad en módulos con "
    "Aprendizajes Esperados y Criterios de Evaluación. Esa estructura se "
    "entrega en subjects[].modules."
)


# Added once the Bases Curriculares EPJA pass has run.
EPJA_BASES_NOTE = (
    "Los objetivos de la Educación de Personas Jóvenes y Adultas (EPJA) provienen "
    "de las Bases Curriculares EPJA 2024, publicadas solo en PDF: el sitio publica "
    "en HTML una única página EPJA con objetivos (Lenguaje y Comunicación, Nivel 1 "
    "de Educación Básica), que se conserva tal cual y se usa para verificar el "
    "lector de PDF. Cada objetivo registra el documento y la página de origen."
)

# Added once the Religión finding has been recorded.
RELIGION_NOTE = (
    "Religión no forma parte de las Bases Curriculares nacionales: se rige por el "
    "Decreto N° 924 (1983), que establece un programa de estudio por credo, "
    "propuesto por cada autoridad religiosa y aprobado por el Ministerio. Esos "
    "programas no se publican en curriculumnacional.cl, por lo que las páginas de "
    "Religión conservan sus documentos y registran la ausencia de objetivos como "
    "una propiedad de la fuente, no como un fallo de extracción."
)


def discover_pages(client: PoliteClient) -> List[str]:
    """Return every subject/grade page path, from the site's own master index."""
    html = client.get_text(BASE_URL + INDEX_PATH)
    paths = parse_index_page(html, BASE_URL + INDEX_PATH)
    log.info("discovered %d subject/grade pages", len(paths))
    return sorted(paths)


def _select(paths: Sequence[str], level_tokens: Optional[Iterable[str]]) -> List[str]:
    if not level_tokens:
        return list(paths)
    wanted = set(level_tokens)
    selected = []
    for path in paths:
        grade_slug = path.strip("/").split("/")[3]
        level = level_for(grade_slug)
        if level is None:
            log.warning("skipping %s: unknown grade slug %r", path, grade_slug)
            continue
        if level.cli in wanted:
            selected.append(path)
    return selected


def _objective_record(
    raw: RawObjective,
    subject_slug: str,
    level_token: str,
    position: int,
    page_url: str,
    base_slug: Optional[str] = None,
    retrieved_at: Optional[str] = None,
) -> dict:
    number = objective_number(raw.code, position)
    record = {
        "oa_id": canonical_oa_id(
            subject_slug, level_token, raw.category, raw.code, number,
            raw.strand_name, raw.strand_kind,
        ),
        "oa_number": number,
        "category": raw.category,
        "code": raw.code,
        "code_slug": code_slug(raw.code),
        "statement": raw.statement,
        "keywords": extract_keywords(raw.statement),
        "prioritized": raw.prioritized,
        "source_url": raw.detail_url or page_url,
        # Provenance is recorded by the engine that did the extraction, not
        # bolted on afterwards: this is the only place that knows for certain
        # which URL and which selector produced this text.
        "provenance": make_provenance(
            source_url=raw.detail_url or page_url,
            source_type=SOURCE_HTML,
            curriculum_base=base_slug,
            retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            extraction_method=HTML_METHOD,
        ),
        **status_for_base(base_slug),
    }
    if raw.prioritized:
        # Never a bare boolean: the flag records membership of one dated
        # programme, and a consumer must be able to see which.
        record["prioritization"] = dict(PRIORITIZATION)
    if raw.strand_name:
        record["strand_eje"] = raw.strand_name
        record["strand_id"] = strand_id(raw.strand_name)
        record["strand_kind"] = raw.strand_kind
    return record


def _subject_record(page: RawPage, level_token: str,
                    retrieved_at: Optional[str] = None) -> dict:
    subject_id = slugify(page.subject_slug)
    objectives: List[dict] = []
    per_group: Counter = Counter()
    for raw in page.objectives:
        group = (raw.category, raw.strand_name)
        per_group[group] += 1
        objectives.append(
            _objective_record(
                raw, page.subject_slug, level_token, per_group[group], page.url,
                base_slug=page.base_slug, retrieved_at=retrieved_at,
            )
        )
    return {
        "subject_id": subject_id,
        "subject_name": page.subject_name or page.page_title,
        "track": track_for(page.base_slug, page.grade_slug),
        "curriculum_base": page.base_slug,
        "curriculum_base_name": BASES.get(page.base_slug, page.base_name),
        "source_url": page.url,
        "source_ids": {
            "base": page.source_base_id,
            "subject": page.source_subject_id,
            "grade": page.source_grade_id,
        },
        "documents": [
            {"doc_type": d.doc_type, "title": d.title, "url": d.url}
            for d in page.documents
        ],
        "learning_objectives": objectives,
        **status_for_base(page.base_slug),
    }


def _insert_subject(
    subjects: Dict[str, dict], subject: dict
) -> Tuple[str, Optional[str]]:
    """Add a subject to a level, resolving subjects reachable by two routes.

    A handful of subjects are published under two curriculum bases - Lengua y
    Cultura de los Pueblos Originarios appears both under 1° a 6° Básico and
    under its own base, where the page renders no objectives. Keep the
    populated route, record the other as an alias, and only fall back to
    qualifying the key by curriculum base when both routes carry content.

    Returns ``(outcome, dropped_url)`` where outcome is "new", "deduplicated"
    or "qualified", and ``dropped_url`` is the route that was folded away.
    """
    key = subject["subject_id"]
    existing = subjects.get(key)
    if existing is None:
        subjects[key] = subject
        return "new", None

    incoming_has = bool(subject["learning_objectives"])
    existing_has = bool(existing["learning_objectives"])
    if existing_has and not incoming_has:
        existing.setdefault("alias_urls", []).append(subject["source_url"])
        return "deduplicated", subject["source_url"]
    if incoming_has and not existing_has:
        dropped = existing["source_url"]
        subject.setdefault("alias_urls", []).append(dropped)
        subjects[key] = subject
        return "deduplicated", dropped

    qualified = f"{key}__{slugify(subject['curriculum_base'])}"
    subject["subject_id"] = qualified
    subjects[qualified] = subject
    log.info("subject %r exists at this level under two bases; stored second as %r",
             key, qualified)
    return "qualified", None


def _dedupe_oa_ids(database: dict) -> List[str]:
    """Make canonical ids globally unique, deterministically.

    Ids are built from (subject, level, strand, category, official number), so
    collisions are not expected; when the source does produce one, a stable
    ``__2`` suffix is appended and the collision is reported.
    """
    seen: Dict[str, int] = {}
    collisions: List[str] = []
    for level in database["levels"].values():
        for subject in level["subjects"].values():
            for objective in subject["learning_objectives"]:
                oa_id = objective["oa_id"]
                if oa_id in seen:
                    seen[oa_id] += 1
                    objective["oa_id"] = f"{oa_id}__{seen[oa_id]}"
                    collisions.append(f"{oa_id} -> {objective['oa_id']} ({objective['code']})")
                else:
                    seen[oa_id] = 1
    return collisions


def build(
    client: PoliteClient,
    level_tokens: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    include_oats: bool = True,
) -> dict:
    """Scrape the selected levels and assemble the full database."""
    paths = _select(discover_pages(client), level_tokens)
    if limit:
        paths = paths[:limit]
    log.info("scraping %d pages", len(paths))
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    levels: Dict[str, dict] = {}
    order: Dict[str, int] = {}
    failures: List[dict] = []
    empty_pages: List[str] = []
    duplicate_routes: List[dict] = []

    for index, path in enumerate(paths, start=1):
        url = BASE_URL + path
        try:
            page = parse_subject_page(client.get_text(url), url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not kill the run
            log.error("failed %s: %s", url, exc)
            failures.append({"url": url, "error": str(exc)})
            continue

        level = level_for(page.grade_slug)
        if level is None:
            log.warning("skipping %s: unknown grade slug %r", url, page.grade_slug)
            failures.append({"url": url, "error": f"unknown grade slug {page.grade_slug!r}"})
            continue

        bucket = levels.setdefault(
            level.level_id,
            {"level_id": level.level_id, "level_name": level.level_name, "subjects": {}},
        )
        order[level.level_id] = level.order

        subject = _subject_record(page, level.token, retrieved_at)
        override = status_for_subject(subject)
        if override:
            subject.update(override)
            for objective in subject["learning_objectives"]:
                objective.update(override)
        outcome, dropped_url = _insert_subject(bucket["subjects"], subject)
        if outcome == "deduplicated":
            kept = bucket["subjects"][subject["subject_id"]]
            duplicate_routes.append({"dropped": dropped_url, "kept": kept["source_url"]})
        elif not subject["learning_objectives"]:
            empty_pages.append(url)

        if index % 25 == 0 or index == len(paths):
            log.info("  %d/%d pages", index, len(paths))

    database = {
        "metadata": {
            "scraped_at": retrieved_at,
            "built_at": retrieved_at,
            "source_url": SOURCE_URL,
            "schema_version": SCHEMA_VERSION,
            "generator": f"mineduc-scraper/{__version__}",
            "dataset_variant": "full",
            "total_oas": 0,
            "total_by_category": {},
            "total_subjects": 0,
            "total_levels": 0,
            "total_oats": 0,
            "coverage_notes": [INDICATOR_NOTE],
            "failed_pages": failures,
            "pages_without_objectives": empty_pages,
            "duplicate_routes": duplicate_routes,
        },
        "levels": {
            level_id: levels[level_id]
            for level_id in sorted(levels, key=lambda k: order[k])
        },
    }

    if include_oats:
        log.info("fetching transversal objectives (OAT) from JSON:API")
        try:
            database["transversal_objectives"] = fetch_transversal_objectives(client)
        except Exception as exc:  # noqa: BLE001
            log.error("OAT fetch failed: %s", exc)
            database["transversal_objectives"] = {}
            database["metadata"]["coverage_notes"].append(f"OAT fetch failed: {exc}")
    else:
        database["transversal_objectives"] = {}

    collisions = _dedupe_oa_ids(database)
    if collisions:
        database["metadata"]["id_collisions"] = collisions
        log.warning("%d canonical id collisions were disambiguated", len(collisions))

    refresh_totals(database)
    return database


def refresh_totals(database: dict) -> dict:
    """Recompute the metadata counters from the actual contents."""
    by_category: Counter = Counter()
    total_oas = 0
    subjects = 0
    for level in database.get("levels", {}).values():
        for subject in level.get("subjects", {}).values():
            subjects += 1
            for objective in subject.get("learning_objectives", []):
                total_oas += 1
                by_category[objective["category"]] += 1
    metadata = database.setdefault("metadata", {})
    metadata["total_oas"] = total_oas
    metadata["total_by_category"] = dict(sorted(by_category.items()))
    metadata["total_subjects"] = subjects
    metadata["total_levels"] = len(database.get("levels", {}))
    metadata["prioritization"] = dict(PRIORITIZATION)
    metadata["total_oats"] = sum(
        len(v) for v in (database.get("transversal_objectives") or {}).values()
    )
    return database
