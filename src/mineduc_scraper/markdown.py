"""Markdown export: the curriculum as documents, grouped for a 50-source notebook.

Why this exists as a separate output rather than a re-encoding of the JSON:
tools like NotebookLM take Markdown, not JSON, and cap a notebook at **50
sources**. The full dataset is one 14 MB file, so it is unusable there twice
over. This writes the same canonical data as a set of subject documents that
fits inside that budget.

The binding constraint is the *file count*, not the size: the whole curriculum
is about 536 000 words and a single source may hold roughly 500 000, so files
can be generous as long as there are few enough of them. The default layout
lands at ~41:

* **Plan común / Formación General** - one file per subject. Grade-suffixed
  variants of one subject ("Matemática 3º Medio", "Inglés 4º Medio") fold into
  the subject they belong to, which is a mechanical read of the published name
  rather than an editorial judgement about which subjects are alike.
* **Formación Diferenciada Humanístico-Científica** - one file. 27 electives,
  21 000 words between them.
* **Técnico-Profesional** - one file per *sector económico*. The 15 sectors are
  MINEDUC's own grouping, read from the site index by `sectors.py` and stored on
  each subject, not invented here.
* **Educación Parvularia** and **EPJA** - one file each.

What the documents carry, and why each of it survives:

* statements keep their **subordinate lists** as lists. Flattening
  "…comprenden las fracciones:\\n- a\\n- b" onto one line silently truncates 518
  objectives at the colon, which is the exact failure the integrity audit
  exists to catch;
* the Técnico-Profesional **Criterios de Evaluación** (5 024 of them) hang off
  an Aprendizaje Esperado, and are written under it;
* **curriculum status** is printed as its label, never defaulted to "Vigente";
* **prioritization** is printed with its period, never as a bare "Priorizado";
* a subject with no objectives prints **why**, from the recorded reason, so
  Religión reads as a documented property of the source rather than an
  unexplained empty file.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .taxonomy import (
    EPJA_FORMACION_LABEL,
    STATUS_LABEL,
    TRACK_HC,
    TRACK_TP,
    level_by_id,
    slugify,
)

CATEGORY_LABEL = {
    "conocimiento": "Conocimiento",
    "habilidad": "Habilidad",
    "actitud": "Actitud",
}

SOURCE_TYPE_LABEL = {
    "html_curriculum_page": "Página de currículum (HTML)",
    "jsonapi": "JSON:API de curriculumnacional.cl",
    "base_curricular_pdf": "Bases Curriculares (PDF)",
    "programa_estudio_pdf": "Programa de Estudio (PDF)",
}

# Areas, in the order the index lists them.
AREA_GENERAL = "Plan Común y Formación General"
AREA_HC = "Formación Diferenciada Humanístico-Científica"
AREA_TP = "Formación Diferenciada Técnico-Profesional"
AREA_PARVULARIA = "Educación Parvularia"
AREA_EPJA = "Educación de Personas Jóvenes y Adultas (EPJA)"

AREA_ORDER = [AREA_PARVULARIA, AREA_GENERAL, AREA_HC, AREA_TP, AREA_EPJA]

# A trailing grade qualifier on a subject name: "Matemática 3º Medio",
# "Educación Ciudadana 4° Medio", "Educación Física y Salud 1". The site prints
# these for subjects whose 3°/4° Medio pages are published separately; they are
# the same asignatura, so the qualifier is stripped to keep one file per subject.
# A stored sub-item already carries its "- " marker; re-adding one produces
# "- - item".
_BULLET_PREFIX = re.compile(r"^-\s*")

_GRADE_SUFFIX = re.compile(
    r"\s+(?:[1-8]\s*[º°]?\s*(?:Básico|Medio)|[12])\s*$", re.IGNORECASE
)


def canonical_subject_name(name: str) -> str:
    """Fold a grade-suffixed subject name back onto the subject itself."""
    folded = _GRADE_SUFFIX.sub("", name or "").strip()
    return folded or (name or "").strip()


def area_of(level_id: str, subject: dict) -> str:
    if level_id.startswith("epja"):
        return AREA_EPJA
    if subject.get("curriculum_base") == "educacion-parvularia":
        return AREA_PARVULARIA
    track = subject.get("track")
    if track == TRACK_TP:
        return AREA_TP
    if track == TRACK_HC:
        return AREA_HC
    return AREA_GENERAL


def group_key(level_id: str, subject: dict) -> Tuple[str, str, str]:
    """Return ``(area, file_slug, document_title)`` for one subject.

    One file per subject in the Plan Común, one per sector in TP, and one for
    each of the areas whose whole content comfortably fits a single source.
    """
    area = area_of(level_id, subject)
    name = subject.get("subject_name") or subject.get("subject_id", "")

    if area == AREA_GENERAL:
        canonical = canonical_subject_name(name)
        return area, slugify(canonical, "_"), canonical
    if area == AREA_TP:
        sector = subject.get("tp_sector")
        if sector:
            return area, f"TP_{slugify(sector, '_')}", f"Técnico-Profesional — Sector {sector}"
        # A speciality the index did not place: its own file, so it is visible
        # rather than quietly folded into another sector.
        canonical = canonical_subject_name(name)
        return area, f"TP_{slugify(canonical, '_')}", f"Técnico-Profesional — {canonical}"
    if area == AREA_HC:
        return area, "Formacion_Diferenciada_HC", AREA_HC
    if area == AREA_PARVULARIA:
        return area, "Educacion_Parvularia", AREA_PARVULARIA
    return area, "EPJA", AREA_EPJA


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _level_order(level_id: str) -> int:
    level = level_by_id(level_id)
    return level.order if level else 999


def statement_markdown(statement: str, indent: str = "") -> str:
    """Render a statement, keeping a stem-plus-list objective as a list.

    This is the whole reason the exporter does not simply collapse whitespace:
    518 objectives are a stem introducing a list, and joining their lines turns
    a complete objective into one that reads as truncated at its colon.
    """
    lines = [line.strip() for line in (statement or "").split("\n") if line.strip()]
    if not lines:
        return ""
    head, *rest = lines
    out = [f"{indent}{head}"]
    for line in rest:
        out.append(f"{indent}- {_BULLET_PREFIX.sub('', line)}")
    return "\n".join(out)


def render_objective(objective: dict) -> str:
    code = objective.get("code") or f"OA {objective.get('oa_number', '')}"
    lines = [f"#### {code}", ""]

    facts = [f"**Categoría:** {CATEGORY_LABEL.get(objective.get('category'), objective.get('category'))}"]
    if objective.get("strand_eje"):
        kind = objective.get("strand_kind") or "Eje"
        facts.append(f"**{kind}:** {objective['strand_eje']}")

    status = objective.get("curriculum_status")
    if status:
        facts.append(f"**Estado del currículum:** {STATUS_LABEL.get(status, status)}")

    # Never a bare "Priorizado": the flag records one dated programme.
    priority = objective.get("prioritization")
    if priority:
        facts.append(
            f"**Priorización:** {priority.get('programme', 'Priorización Curricular')} "
            f"{priority.get('period', '')} (dato histórico)".strip()
        )
    elif objective.get("prioritized"):
        facts.append("**Priorización:** marcado como priorizado (dato histórico)")

    if objective.get("level_scope"):
        facts.append(
            "**Aplica a los niveles:** " + ", ".join(objective["level_scope"])
        )
    lines.append(" · ".join(facts))
    lines.append("")

    body = statement_markdown(objective.get("statement", ""))
    if body:
        first, *rest = body.split("\n")
        lines.append(f"> {first}")
        for line in rest:
            lines.append(f"> {line}")
        lines.append("")

    indicators = objective.get("indicators") or []
    if indicators:
        scope = objective.get("indicators_scope")
        note = " (evaluación conjunta de varios objetivos)" if scope == "unit" else ""
        lines.append(f"**Indicadores de evaluación ({len(indicators)}){note}:**")
        lines.append("")
        for indicator in indicators:
            lines.append(f"- {' '.join(str(indicator).split())}")
        lines.append("")

    correction = objective.get("correction")
    if correction:
        lines.append(
            f"**Corrección aplicada.** El texto publicado en la fuente conflictiva era: "
            f"«{correction.get('original_value', '')}». {correction.get('explanation', '')} "
            f"Fuente autorizada: {correction.get('authoritative_source_url', '')}"
            + (f", p. {correction['authoritative_source_page']}"
               if correction.get("authoritative_source_page") else "")
        )
        lines.append("")

    provenance = objective.get("provenance") or {}
    if provenance:
        kind = SOURCE_TYPE_LABEL.get(provenance.get("source_type"), provenance.get("source_type"))
        page = f", p. {provenance['source_page']}" if provenance.get("source_page") else ""
        document = f" — {provenance['source_document']}" if provenance.get("source_document") else ""
        lines.append(f"*Fuente: {kind}{document}{page} · {provenance.get('source_url', '')}*")
        lines.append("")
    return "\n".join(lines)


def render_module(module: dict) -> str:
    lines = [
        f"#### Módulo {module.get('module_number', '')}: {module.get('module_name', '')}".rstrip(),
        "",
    ]
    facts = []
    if module.get("hours"):
        facts.append(f"**Horas:** {module['hours']}")
    if module.get("grade"):
        facts.append(f"**Curso:** {module['grade']}")
    if module.get("objective_codes"):
        facts.append(f"**Objetivos que aborda:** {', '.join(module['objective_codes'])}")
    if facts:
        lines.extend([" · ".join(facts), ""])

    for learning in module.get("expected_learnings") or []:
        lines.append(
            f"**Aprendizaje Esperado {learning.get('number', '')}.** "
            f"{' '.join(str(learning.get('statement', '')).split())}"
        )
        lines.append("")
        # `criteria` is the field the schema defines. Reading a different name
        # here would silently drop all 5 024 Criterios de Evaluación, which is
        # the single largest thing this document type carries.
        criteria = learning.get("criteria") or []
        if criteria:
            lines.append(f"*Criterios de evaluación ({len(criteria)}):*")
            lines.append("")
            for criterion in criteria:
                lines.append(f"- {' '.join(str(criterion).split())}")
            lines.append("")
        if learning.get("generic_objectives"):
            lines.append(
                f"*Objetivos de Aprendizaje Genéricos: "
                f"{', '.join(learning['generic_objectives'])}*"
            )
            lines.append("")
    return "\n".join(lines)


def render_subject(level_name: str, subject: dict) -> str:
    lines = [f"### {subject.get('subject_name', '')} — {level_name}", ""]

    facts = []
    if subject.get("curriculum_base_name"):
        facts.append(f"**Base curricular:** {subject['curriculum_base_name']}")
    status = subject.get("curriculum_status")
    if status:
        facts.append(f"**Estado:** {STATUS_LABEL.get(status, status)}")
    if subject.get("formation_area"):
        facts.append(
            f"**Ámbito de formación:** "
            f"{EPJA_FORMACION_LABEL.get(subject['formation_area'], subject['formation_area'])}"
        )
    if subject.get("tp_sector"):
        facts.append(f"**Sector económico:** {subject['tp_sector']}")
    if subject.get("source_url"):
        facts.append(f"**Ficha oficial:** {subject['source_url']}")
    if facts:
        lines.extend([" · ".join(facts), ""])

    objectives = subject.get("learning_objectives") or []
    if not objectives:
        # Never an unexplained empty section: the dataset records why.
        reason = subject.get("no_objectives_reason") or {}
        elsewhere = subject.get("objectives_in_level")
        if elsewhere:
            lines.append(
                f"> Los objetivos de esta asignatura se publican en el nivel "
                f"`{elsewhere}`, porque las Bases los definen para un nivel combinado."
            )
        elif reason:
            lines.append(f"> **Sin objetivos de aprendizaje publicados.** {reason.get('explanation', '')}")
            if reason.get("source_url"):
                lines.append(">")
                lines.append(f"> Fuente: {reason['source_url']}")
        else:
            lines.append("> Esta oferta no registra objetivos de aprendizaje.")
        lines.append("")
        return "\n".join(lines)

    by_strand: Dict[str, List[dict]] = defaultdict(list)
    for objective in objectives:
        by_strand[objective.get("strand_eje") or ""].append(objective)

    for strand, group in by_strand.items():
        if strand:
            kind = group[0].get("strand_kind") or "Eje"
            lines.extend([f"##### {kind}: {strand}", ""])
        for objective in group:
            lines.append(render_objective(objective))

    for module in subject.get("modules") or []:
        lines.append(render_module(module))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def collect(database: dict) -> Dict[str, dict]:
    """Group every subject into the document it belongs to."""
    documents: Dict[str, dict] = {}
    for level_id, level in (database.get("levels") or {}).items():
        for subject in (level.get("subjects") or {}).values():
            area, slug, title = group_key(level_id, subject)
            document = documents.setdefault(slug, {
                "slug": slug, "title": title, "area": area, "entries": [],
            })
            document["entries"].append({
                "level_id": level_id,
                "level_name": level.get("level_name", level_id),
                "subject": subject,
            })
    for document in documents.values():
        document["entries"].sort(
            key=lambda e: (_level_order(e["level_id"]),
                           e["subject"].get("subject_name", ""))
        )
    return documents


def _counts(document: dict) -> dict:
    objectives = indicators = criteria = modules = 0
    for entry in document["entries"]:
        subject = entry["subject"]
        found = subject.get("learning_objectives") or []
        objectives += len(found)
        for objective in found:
            indicators += len(objective.get("indicators") or [])
        for module in subject.get("modules") or []:
            modules += 1
            for learning in module.get("expected_learnings") or []:
                criteria += len(learning.get("criteria") or [])
    return {"objectives": objectives, "indicators": indicators,
            "criteria": criteria, "modules": modules,
            "offerings": len(document["entries"])}


def render_document(document: dict, metadata: dict) -> str:
    counts = _counts(document)
    lines = [
        f"# {document['title']}",
        "",
        f"**Área:** {document['area']}  ",
        "**Fuente:** Ministerio de Educación de Chile, Unidad de Currículum y "
        "Evaluación — curriculumnacional.cl  ",
        f"**Construido:** {(metadata.get('built_at') or '')[:10]} "
        f"(rastreo del sitio: {(metadata.get('scraped_at') or '')[:10]})  ",
        f"**Contenido:** {counts['objectives']} objetivos de aprendizaje · "
        f"{counts['indicators']} indicadores de evaluación"
        + (f" · {counts['modules']} módulos con {counts['criteria']} criterios"
           if counts["modules"] else "")
        + f" · {counts['offerings']} ofertas (nivel × asignatura)",
        "",
        "> Documento generado a partir del dataset `mineduc_curriculum_full.json`. "
        "El texto de cada objetivo es el publicado oficialmente; cada uno indica su "
        "fuente exacta, su estado curricular y, cuando corresponde, la corrección "
        "aplicada.",
        "",
        "---",
        "",
        "## Contenido",
        "",
    ]
    for entry in document["entries"]:
        subject = entry["subject"]
        count = len(subject.get("learning_objectives") or [])
        lines.append(
            f"- {subject.get('subject_name', '')} — {entry['level_name']} "
            f"({count} objetivo{'' if count == 1 else 's'})"
        )
    lines.extend(["", "---", ""])

    for entry in document["entries"]:
        lines.append(render_subject(entry["level_name"], entry["subject"]))
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_index(documents: Dict[str, dict], metadata: dict, written: Dict[str, int]) -> str:
    total = sum(_counts(d)["objectives"] for d in documents.values())
    lines = [
        "# Currículum Nacional de Chile — índice de documentos Markdown",
        "",
        "**Fuente:** Ministerio de Educación de Chile, Unidad de Currículum y "
        "Evaluación — curriculumnacional.cl  ",
        f"**Construido:** {(metadata.get('built_at') or '')[:10]}  ",
        f"**Documentos:** {len(documents)} · **Objetivos de aprendizaje:** {total}",
        "",
        "Estos archivos son una vista en Markdown del dataset que construye este "
        "repositorio, pensada para herramientas que no aceptan JSON y que limitan el "
        "número de fuentes por cuaderno (NotebookLM admite 50). El agrupamiento "
        "mantiene el total por debajo de ese límite: una asignatura por archivo en el "
        "plan común, un archivo por sector económico en Técnico-Profesional, y un "
        "archivo por área en el resto.",
        "",
        "| Documento | Área | Ofertas | Objetivos | Indicadores | Criterios TP | Tamaño |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    ordered = sorted(
        documents.values(),
        key=lambda d: (AREA_ORDER.index(d["area"]) if d["area"] in AREA_ORDER else 99,
                       d["title"]),
    )
    for document in ordered:
        counts = _counts(document)
        size = written.get(document["slug"], 0)
        lines.append(
            f"| `{document['slug']}.md` | {document['area']} | {counts['offerings']} | "
            f"{counts['objectives']} | {counts['indicators']} | "
            f"{counts['criteria'] or '—'} | {size / 1024:.0f} KB |"
        )
    lines.extend([
        "",
        "## Notas de uso",
        "",
        "- Cada objetivo indica su **fuente exacta**, de modo que una respuesta puede "
        "rastrearse hasta la página o el PDF del que se extrajo.",
        "- El **estado del currículum** aparece explícito. La asignatura «Inglés "
        "(Propuesta)» es una propuesta, no el currículum vigente, y sus objetivos lo "
        "señalan.",
        "- La marca de **priorización** corresponde a la Priorización Curricular "
        "2023–2025 y es un dato histórico.",
        "- **Religión** no tiene objetivos publicados: se rige por el Decreto N° 924, "
        "que establece un programa por credo aprobado por el Ministerio. El archivo "
        "correspondiente lo explica en lugar de quedar vacío.",
        "",
    ])
    return "\n".join(lines)


def write_markdown(database: dict, directory: Path) -> List[Path]:
    """Write one Markdown document per group, plus an index."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = database.get("metadata") or {}

    documents = collect(database)
    written: Dict[str, int] = {}
    paths: List[Path] = []
    for slug, document in documents.items():
        path = directory / f"{slug}.md"
        path.write_text(render_document(document, metadata), encoding="utf-8")
        written[slug] = path.stat().st_size
        paths.append(path)

    index = directory / "00_indice.md"
    index.write_text(render_index(documents, metadata, written), encoding="utf-8")
    paths.append(index)
    return paths
