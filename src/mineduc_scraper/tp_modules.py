"""Módulos, Aprendizajes Esperados and Criterios de Evaluación from TP Programas.

The Técnico-Profesional Programas de Estudio are organised differently from
every other Programa: they do not publish *Indicadores de Evaluación* per
objective at all. Instead each speciality is broken into **módulos**, and each
módulo declares

  * the speciality objectives (OA) it addresses,
  * a set of **Aprendizajes Esperados** (numbered ``1.``, ``2.``, ...), and
  * for each of those, **Criterios de Evaluación** (numbered ``1.1``, ``1.2``),
    plus the **Objetivos de Aprendizaje Genéricos** (OAG, single letters) they
    develop.

Criterios de Evaluación play the same role indicators do elsewhere - observable,
evaluable descriptions of performance - but they hang off an Aprendizaje
Esperado rather than off an objective, so they are stored as their own
structure instead of being flattened into ``Objective.indicators``.

The three columns are told apart by their numbering rather than by geometry:
the column positions shift from page to page, but ``1.`` is always an
Aprendizaje Esperado and ``1.1`` always one of its Criterios.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .indicators import _clean, _is_furniture

log = logging.getLogger(__name__)

_SECTION_HEADER = re.compile(
    r"aprendizajes\s+esperados.{0,40}criterios\s+de\s+evaluaci", re.I | re.S
)
# "MóDULO 3 · ELABORACIÓN DE PROYECTOS ELÉCTRICOS 228 Horas Tercero Medio".
# DOTALL because long módulo names wrap across lines; the hour count is what
# terminates the name, and every módulo header carries one.
_MODULE_HEADER = re.compile(
    r"M[oó]dulo\s+(\d+)\s*[·:.\u2022\-]\s*(.{1,160}?)\s+(\d+)\s*Horas",
    re.I | re.S,
)
_MODULE_GRADE = re.compile(r"(Tercero|Cuarto)\s+[Mm]edio", re.I)
_OA_LINE = re.compile(r"^OA\s*([0-9]{1,2}|[A-Za-z])\s+(.*)$", re.S)
_CRITERION = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+")
# An Aprendizaje Esperado is numbered "4." - but not always: some Programas
# print it bare ("4 Analiza funcionamiento de equipos ..."). The bare form is
# only accepted before a capital letter, so page furniture like
# "4 horas pedagógicas" is not mistaken for one.
# The optional repeat absorbs a typo the Programas contain more than once:
# "5. 5. Empaqueta artículos textiles ...".
_EXPECTED_PATTERNS = (
    re.compile(r"^(\d{1,2})[.)]\s+(?:\d{1,2}[.)]\s+)?(?=\D)"),
    re.compile(r"^(\d{1,2})\s+(?=[A-ZÁÉÍÓÚÑ])"),
)
# Some Programas put the Aprendizaje Esperado's number in its own cell and its
# text in the next one: a block reading just "3." followed by "Aplica técnicas
# de limpieza ...".
_EXPECTED_NUMBER_ONLY = re.compile(r"^(\d{1,2})[.)]$")
_STATEMENT_START = re.compile(r"^[A-ZÁÉÍÓÚÑ]")

# OAG letters appear in either case depending on the Programa.
_OAG = re.compile(r"^([A-Za-z])$")

MIN_TEXT_LEN = 12
SAME_ROW_TOLERANCE = 6.0  # pt; a number cell and its text share a baseline
# No módulo has anything like this many Aprendizajes Esperados. The guard keeps
# page footers, which begin with the page number ("76 Especialidad ..."), from
# being read as one.
MAX_EXPECTED_NUMBER = 30


@dataclass
class ExpectedLearning:
    number: int
    statement: str = ""
    criteria: List[str] = field(default_factory=list)
    generic_objectives: List[str] = field(default_factory=list)


@dataclass
class Module:
    number: int
    name: str = ""
    hours: Optional[int] = None
    grade: Optional[str] = None
    objective_codes: List[str] = field(default_factory=list)
    objective_statements: Dict[str, str] = field(default_factory=dict)
    expected_learnings: Dict[int, ExpectedLearning] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "module_number": self.number,
            "module_name": self.name,
            "hours": self.hours,
            "grade": self.grade,
            "objective_codes": [f"OA {code}" for code in self.objective_codes],
            "expected_learnings": [
                {
                    "number": learning.number,
                    "statement": learning.statement,
                    "criteria": learning.criteria,
                    "generic_objectives": learning.generic_objectives,
                }
                for learning in sorted(self.expected_learnings.values(),
                                       key=lambda item: item.number)
            ],
        }


@dataclass
class TpProgramme:
    """Every módulo in one speciality's Programa, keyed by (grade, number, name).

    Not by number alone: a speciality with menciones restarts its módulo
    numbering for each one, so Administración has three "Módulo 1" - the common
    Tercero medio one plus a Cuarto medio one per mención. Keying on the number
    would silently merge them.
    """

    pdf_url: str
    pages: int = 0
    modules: Dict[Tuple[str, int, str], Module] = field(default_factory=dict)

    @staticmethod
    def key(module: Module) -> Tuple[str, int, str]:
        return (module.grade or "", module.number, module.name)

    @property
    def total_criteria(self) -> int:
        return sum(
            len(learning.criteria)
            for module in self.modules.values()
            for learning in module.expected_learnings.values()
        )

    @property
    def total_expected_learnings(self) -> int:
        return sum(len(m.expected_learnings) for m in self.modules.values())

    def ordered(self) -> List[Module]:
        """Módulos in publication order: Tercero medio first, then by number."""
        return sorted(
            self.modules.values(),
            key=lambda m: (0 if (m.grade or "").lower().startswith("tercero") else 1,
                           m.number, m.name),
        )

    def as_list(self) -> List[dict]:
        return [m.as_dict() for m in self.ordered()]


def _module_from_text(text: str) -> Optional[Module]:
    match = _MODULE_HEADER.search(text)
    if not match:
        return None
    module = Module(
        number=int(match.group(1)),
        name=_clean(match.group(2)).strip(" ·-:"),
        hours=int(match.group(3)),
    )
    grade = _MODULE_GRADE.search(text[match.end():match.end() + 60])
    if grade:
        module.grade = f"{grade.group(1).capitalize()} medio"
    return module


def extract_tp_programme(path: Path, pdf_url: str = "") -> TpProgramme:
    """Read every módulo's Aprendizajes Esperados and Criterios de Evaluación."""
    import fitz

    fitz.TOOLS.mupdf_display_errors(False)
    programme = TpProgramme(pdf_url=pdf_url)
    document = fitz.open(path)
    programme.pages = document.page_count

    current: Optional[Module] = None
    current_learning: Optional[int] = None
    try:
        for index in range(document.page_count):
            page_text = document[index].get_text()
            if not _SECTION_HEADER.search(page_text):
                # Leaving the Aprendizajes Esperados section closes the módulo,
                # so later chapters cannot bleed into it.
                if current is not None and _MODULE_HEADER.search(page_text) is None:
                    current = None
                    current_learning = None
                continue

            found = _module_from_text(page_text)
            if found is not None:
                current = programme.modules.setdefault(
                    TpProgramme.key(found), found
                )
                current.hours = current.hours or found.hours
                current_learning = None
            if current is None:
                continue

            current_learning = consume_page(
                current, document[index].get_text("blocks"), current_learning
            )
    finally:
        document.close()

    # Drop anything that yielded nothing usable.
    for module in programme.modules.values():
        module.expected_learnings = {
            number: learning for number, learning in module.expected_learnings.items()
            if learning.statement or learning.criteria
        }
    programme.modules = {
        key: module for key, module in programme.modules.items()
        if module.expected_learnings
    }
    return programme


def consume_page(
    module: Module, blocks: List[tuple], current_learning: Optional[int] = None
) -> Optional[int]:
    """Feed one page's blocks into a módulo. Returns the still-open AE number.

    Kept separate from PDF handling so it can be driven by block layouts
    captured from a real Programa.
    """
    cleaned = [(block, _clean(block[4])) for block in blocks]
    cleaned = [(block, text) for block, text in cleaned if text]

    skip_next = False
    for position, (block, text) in enumerate(cleaned):
        if skip_next:
            skip_next = False
            continue

        number_only = _EXPECTED_NUMBER_ONLY.match(text)
        if number_only:
            # A cell holding just "3." opens an Aprendizaje Esperado only if its
            # text sits in the next cell on the same baseline. Rotated page tabs
            # ("7." down the page edge) look identical but stand alone, and must
            # not create an empty entry.
            pair = cleaned[position + 1] if position + 1 < len(cleaned) else None
            if pair is not None and _is_statement_cell(block, *pair):
                number = int(number_only.group(1))
                learning = module.expected_learnings.setdefault(
                    number, ExpectedLearning(number=number)
                )
                if not learning.statement:
                    learning.statement = pair[1]
                current_learning = number
                skip_next = True
            continue

        current_learning = _consume_block(module, text, current_learning)
    return current_learning


def _is_statement_cell(number_block: tuple, block: tuple, text: str) -> bool:
    """Whether ``block`` is the statement belonging to a lone number cell."""
    same_row = abs(block[1] - number_block[1]) <= SAME_ROW_TOLERANCE
    to_the_right = block[0] > number_block[0]
    return bool(
        same_row
        and to_the_right
        and len(text) >= MIN_TEXT_LEN
        and _STATEMENT_START.match(text)
        and not _CRITERION.match(text)
        and not _OA_LINE.match(text)
        and not _EXPECTED_NUMBER_ONLY.match(text)
    )


def module_from_text(text: str) -> Optional[Module]:
    """Public alias: read a módulo header ("MóDULO 3 · NAME 228 Horas ...")."""
    return _module_from_text(text)


def _consume_block(module: Module, text: str, current_learning: Optional[int]) -> Optional[int]:
    """Route one text block to the módulo structure. Returns the open AE number."""
    oa = _OA_LINE.match(text)
    if oa:
        code, statement = oa.group(1), _clean(oa.group(2))
        if code not in module.objective_codes:
            module.objective_codes.append(code)
        if len(statement) >= MIN_TEXT_LEN:
            module.objective_statements[code] = statement
        return current_learning

    criterion = _CRITERION.match(text)
    if criterion:
        parent = int(criterion.group(1))
        if parent > MAX_EXPECTED_NUMBER:
            return current_learning
        body = _clean(text[criterion.end():])
        if len(body) >= MIN_TEXT_LEN:
            learning = module.expected_learnings.setdefault(
                parent, ExpectedLearning(number=parent)
            )
            label = f"{criterion.group(1)}.{criterion.group(2)}"
            entry = f"{label} {body}"
            if entry not in learning.criteria:
                learning.criteria.append(entry)
        return parent

    expected = next(
        (match for match in (p.match(text) for p in _EXPECTED_PATTERNS) if match),
        None,
    )
    if expected:
        number = int(expected.group(1))
        if number > MAX_EXPECTED_NUMBER:
            return current_learning
        body = _clean(text[expected.end():])
        if len(body) >= MIN_TEXT_LEN and not _is_furniture(body):
            learning = module.expected_learnings.setdefault(
                number, ExpectedLearning(number=number)
            )
            if not learning.statement:
                learning.statement = body
            return number
        return current_learning

    oag = _OAG.match(text)
    if oag and current_learning is not None:
        learning = module.expected_learnings.get(current_learning)
        letter = oag.group(1).upper()
        if learning is not None and letter not in learning.generic_objectives:
            learning.generic_objectives.append(letter)
    return current_learning


# --------------------------------------------------------------------------- #
# joining onto the dataset
# --------------------------------------------------------------------------- #
from dataclasses import dataclass as _dataclass  # noqa: E402

from .indicators import (  # noqa: E402
    MATCH_THRESHOLD,
    _pdf_filename,
    programa_documents,
    resolve_pdf_url,
    statement_similarity,
)

TP_TRACK = "plan_diferenciado_tp"

# A speciality's Programa covers the whole 3°-4° Medio cycle and labels each
# módulo with the year it belongs to, so each grade only gets its own.
GRADE_TO_LEVEL = {"tercero medio": "3_medio", "cuarto medio": "4_medio"}


@_dataclass
class TpReport:
    pdfs_read: int = 0
    pdfs_failed: List[dict] = field(default_factory=list)
    subjects_enriched: int = 0
    modules: int = 0
    expected_learnings: int = 0
    criteria: int = 0
    objective_links: int = 0
    unresolved_objective_codes: List[str] = field(default_factory=list)


def _link_objectives(
    subject: dict, module: Module, threshold: float
) -> List[str]:
    """Resolve a módulo's speciality objectives to this subject's oa_ids.

    Matched by statement, for the same reason the indicator join is: the code
    printed in the Programa cannot be trusted to line up with the code the site
    publishes today.
    """
    resolved: List[str] = []
    for code in module.objective_codes:
        statement = module.objective_statements.get(code, "")
        if not statement:
            continue
        best_score, best = 0.0, None
        for objective in subject.get("learning_objectives", []):
            score = statement_similarity(statement, objective["statement"])
            if score > best_score:
                best_score, best = score, objective
        if best is not None and best_score >= threshold:
            if best["oa_id"] not in resolved:
                resolved.append(best["oa_id"])
    return resolved


def enrich(
    client,
    database: dict,
    pdf_cache: Path,
    limit: Optional[int] = None,
    threshold: float = MATCH_THRESHOLD,
) -> TpReport:
    """Attach módulo / Aprendizaje Esperado / Criterio data to TP subjects."""
    report = TpReport()
    citations = programa_documents(database)
    tp_pages = {
        url: [
            (level_id, subject) for level_id, subject in subjects
            if subject.get("track") == TP_TRACK
        ]
        for url, subjects in citations.items()
    }
    tp_pages = {url: subjects for url, subjects in tp_pages.items() if subjects}

    pages = sorted(tp_pages)
    if limit:
        pages = pages[:limit]
    log.info("%d Técnico-Profesional Programas to process", len(pages))

    for position, page_url in enumerate(pages, start=1):
        try:
            pdf_url = resolve_pdf_url(client.get_text(page_url), page_url)
            if not pdf_url:
                report.pdfs_failed.append({"url": page_url, "error": "no PDF link on page"})
                continue
            path = client.download(pdf_url, pdf_cache / _pdf_filename(pdf_url))
            programme = extract_tp_programme(path, pdf_url=pdf_url)
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run
            log.error("TP module pass failed for %s: %s", page_url, exc)
            report.pdfs_failed.append({"url": page_url, "error": str(exc)})
            continue

        report.pdfs_read += 1
        if not programme.modules:
            continue

        for level_id, subject in tp_pages[page_url]:
            payload = []
            for module in programme.ordered():
                declared = GRADE_TO_LEVEL.get((module.grade or "").lower())
                if declared is not None and declared != level_id:
                    continue
                entry = module.as_dict()
                linked = _link_objectives(subject, module, threshold)
                entry["objective_ids"] = linked
                report.objective_links += len(linked)
                missing = [
                    f"{subject['subject_id']}/módulo {module.number}/OA {code}"
                    for code in module.objective_codes
                    if not module.objective_statements.get(code)
                ]
                report.unresolved_objective_codes.extend(missing)
                payload.append(entry)
            subject["modules"] = payload
            subject["modules_source"] = pdf_url
            if len({s["subject_id"] for _l, s in tp_pages[page_url]}) > 1:
                # One Programa serves a speciality and its menciones. It marks
                # which year each módulo belongs to but not which mención, so
                # the list spans them; say so rather than guess.
                subject["modules_shared_programme"] = True
            report.subjects_enriched += 1
            report.modules += len(payload)
            report.expected_learnings += sum(
                len(m["expected_learnings"]) for m in payload
            )
            report.criteria += sum(
                len(learning["criteria"])
                for m in payload for learning in m["expected_learnings"]
            )

        if position % 10 == 0 or position == len(pages):
            log.info("  %d/%d TP Programas (%d módulos, %d criterios)",
                     position, len(pages), report.modules, report.criteria)
    return report


def coverage(database: dict) -> dict:
    """Count TP module coverage across the dataset."""
    tp_subjects = 0
    with_modules = 0
    modules = 0
    expected = 0
    criteria = 0
    for level in database.get("levels", {}).values():
        for subject in level.get("subjects", {}).values():
            if subject.get("track") != TP_TRACK:
                continue
            tp_subjects += 1
            entries = subject.get("modules") or []
            if entries:
                with_modules += 1
            modules += len(entries)
            for module in entries:
                expected += len(module.get("expected_learnings", []))
                criteria += sum(
                    len(learning.get("criteria", []))
                    for learning in module.get("expected_learnings", [])
                )
    return {
        "tp_subjects": tp_subjects,
        "tp_subjects_with_modules": with_modules,
        "modules": modules,
        "expected_learnings": expected,
        "criteria": criteria,
    }
