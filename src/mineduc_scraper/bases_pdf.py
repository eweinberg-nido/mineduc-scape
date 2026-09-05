"""Base Curricular PDF ingestion.

A *third* extraction engine, kept deliberately separate from the two that
already exist:

* ``extract.py``      reads the HTML curriculum pages (OA / OAH / OAA)
* ``indicators.py``   reads the **Programa de Estudio** PDFs (indicadores)
* ``bases_pdf.py``    reads the **Bases Curriculares** PDFs (the objectives)

The distinction between the last two matters and is not cosmetic. A Programa de
Estudio is a companion document that tabulates indicators against objectives in
a multi-column table read geometrically; a Base Curricular *defines* the
objectives, in running prose, one section per (asignatura, ciclo, nivel).
Pushing a Base through the Programa parser would find no indicator columns and
report a source gap that is not there, so it gets its own adapter.

Only one Base Curricular is read here today: the **Bases Curriculares para la
Educación de Personas Jóvenes y Adultas (EPJA) 2024**. Every other curriculum
base publishes its objectives as structured HTML, and structured HTML wins over
a PDF whenever both exist.

Layout of an EPJA definition section (one per asignatura × nivel)::

    <Asignatura>
    Educación Básica | Educación Media          <- ciclo
    Nivel 2 | Nivel 1 y 2                        <- nivel (may span two)
    En el Nivel ... se espera que ... comprendan que:
    1. <gran idea>
    ...
    Objetivos de Aprendizaje
    Conocimientos esenciales
    Se espera que los y las estudiantes sean capaces de:
    OA 1. <enunciado>. (<Eje>)
    OA 2. ...
    <TAB>y <conocimiento esencial>              <- bullets, subject-wide

The OA block is read in reading order, which is safe here because the
objectives occupy a single column that runs to the first "conocimientos
esenciales" bullet. Every parsed objective is required to carry its eje in
trailing parentheses; one that does not is reported rather than guessed at,
because a missing eje is the signal that the column flow was misread.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .http import PoliteClient

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# The source document
# --------------------------------------------------------------------------- #
EPJA_BASE_SLUG = "bases-curriculares-educacion-personas-jovenes-adultas-epja"

EPJA_BASES_2024 = {
    "title": "Bases Curriculares para la Educación de Personas Jóvenes y Adultas 2024",
    "landing_url": (
        "https://www.curriculumnacional.cl/recursos/"
        "bases-curriculares-educacion-personas-jovenes-adultas-2024"
    ),
    "pdf_url": (
        "https://www.curriculumnacional.cl/sites/default/files/adjuntos/recursos/"
        "2026-07/WEB_bbcc%20EPJA_v16_0.pdf"
    ),
    "curriculum_base": EPJA_BASE_SLUG,
}

# --------------------------------------------------------------------------- #
# Section markers
# --------------------------------------------------------------------------- #
_OA_LINE = re.compile(r"^OA\s*(\d+)\.\s*(.*)$")
_NIVEL = re.compile(r"^Nivel\s+(\d+)(?:\s*y\s*(\d+))?$", re.IGNORECASE)
_CICLO = re.compile(r"^Educación\s+(Básica|Media)$", re.IGNORECASE)
_CAPACES = "Se espera que los y las estudiantes sean capaces de:"
_CONOCIMIENTOS = "Conocimientos esenciales"
_OBJETIVOS_HEADING = "Objetivos de Aprendizaje"
# The Bases set every list item as TAB + the theme font's bullet glyph, which
# text extraction renders as the letter "y". Matching that exact two-character
# prefix - rather than "a line starting with y" - is what keeps it from
# swallowing the many statements that legitimately open with the conjunction.
_BULLET = "\ty"

# Pages that repeat the objectives in a comparison grid rather than defining
# them. Ingesting these would duplicate every statement several times over and
# attribute each copy to the wrong nivel, so they are skipped by title.
_NOT_A_DEFINITION = (
    "Visión panorámica",
    "Matriz de tributación",
    "OA/ Ámbitos de las Habilidades",
)

# Ámbito de formación, taken from the running header the Bases print on every
# page of a part ("Asignaturas de Formación General", ...).
_FORMACION_HEADER = re.compile(
    r"Asignaturas de\s+Formación\s+(General|Instrumental|"
    r"Diferenciada Humanístico-Científica|Diferenciada Técnico-Profesional)",
    re.IGNORECASE,
)

from .taxonomy import (  # noqa: E402  (kept next to the constants it feeds)
    EPJA_FORMACION_DIFERENCIADA_HC,
    EPJA_FORMACION_DIFERENCIADA_TP,
    EPJA_FORMACION_GENERAL,
    EPJA_FORMACION_INSTRUMENTAL,
)

# Keyed on the accent-folded header text, because that is what `_norm` yields.
_FORMACION_KEY = {
    "general": EPJA_FORMACION_GENERAL,
    "instrumental": EPJA_FORMACION_INSTRUMENTAL,
    "diferenciada humanistico-cientifica": EPJA_FORMACION_DIFERENCIADA_HC,
    "diferenciada tecnico-profesional": EPJA_FORMACION_DIFERENCIADA_TP,
}

# --------------------------------------------------------------------------- #
# Asignatura -> the site's own subject slug and display name.
#
# The Bases title several sections with a double name ("Lenguaje y Comunicación
# / Lengua y Literatura") because the asignatura is renamed between ciclos. The
# site publishes one slug for both, so the mapping is stated explicitly rather
# than slugified from whichever half the PDF happens to print.
# --------------------------------------------------------------------------- #
EPJA_SUBJECTS: Dict[str, Tuple[str, str]] = {
    "lenguaje y comunicación / lengua y literatura":
        ("lenguaje-comunicacion", "Lenguaje y Comunicación"),
    "matemática": ("matematica", "Matemática"),
    "historia, geografía y ciencias sociales / educación ciudadana":
        ("historia-geografia-ciencias-sociales", "Historia, Geografía y Ciencias Sociales"),
    "ciencias naturales": ("ciencias-naturales", "Ciencias Naturales"),
    "inglés": ("ingles", "Inglés"),
    "emprendimiento y empleabilidad":
        ("emprendimiento-empleabilidad", "Emprendimiento y Empleabilidad"),
    "educación financiera": ("educacion-financiera", "Educación Financiera"),
    "responsabilidad personal y social":
        ("responsabilidad-personal-social", "Responsabilidad Personal y Social"),
    "pensamiento computacional":
        ("pensamiento-computacional", "Pensamiento Computacional"),
    "artes visuales": ("artes-visuales", "Artes Visuales"),
    "educación física y salud": ("educacion-fisica-salud", "Educación Física y Salud"),
    "filosofía": ("filosofia", "Filosofía"),
}

# (ciclo, nivel) -> level_id. "Nivel 1 y 2" of Educación Media is a single
# combined level in the Bases; see taxonomy.SYNTHETIC_LEVELS for why it is not
# split across the site's two Nivel pages.
EPJA_LEVEL_IDS: Dict[Tuple[str, str], str] = {
    ("basica", "1"): "epja_n1_basica",
    ("basica", "2"): "epja_n2_basica",
    ("basica", "3"): "epja_n3_basica",
    ("media", "1"): "epja_n1_media",
    ("media", "2"): "epja_n2_media",
    ("media", "1y2"): "epja_media",
}

EPJA_LEVEL_TOKENS: Dict[str, str] = {
    "epja_n1_basica": "E1B",
    "epja_n2_basica": "E2B",
    "epja_n3_basica": "E3B",
    "epja_n1_media": "E1M",
    "epja_n2_media": "E2M",
    "epja_media": "EM",
}

# A combined level applies to the site levels it spans. Recorded per objective
# as `level_scope` so a consumer can answer "does this apply in Nivel 2 Media?"
# without having to know the Bases' internal structure.
EPJA_LEVEL_SCOPE: Dict[str, List[str]] = {
    "epja_media": ["epja_n1_media", "epja_n2_media"],
}


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class BasesObjective:
    """One objective as printed in a Base Curricular."""

    number: int
    code: str
    statement: str
    strand_eje: Optional[str]
    subject_slug: str
    subject_name: str
    level_id: str
    formation_area: str
    pdf_page: int  # 1-based, as a reader would cite it


@dataclass
class BasesSection:
    """One (asignatura, ciclo, nivel) definition section of a Base Curricular."""

    subject_slug: str
    subject_name: str
    level_id: str
    formation_area: str
    pdf_page: int
    big_ideas: List[str] = field(default_factory=list)
    essential_knowledge: List[str] = field(default_factory=list)
    objectives: List[BasesObjective] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


@dataclass
class BasesReport:
    sections: List[BasesSection] = field(default_factory=list)
    pages_scanned: int = 0
    pages_skipped_not_definition: int = 0
    unmapped_subjects: List[str] = field(default_factory=list)
    unmapped_levels: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    @property
    def objectives(self) -> List[BasesObjective]:
        return [o for section in self.sections for o in section.objectives]


# --------------------------------------------------------------------------- #
# Text hygiene
# --------------------------------------------------------------------------- #
def clean_text(text: str) -> str:
    """Repair the artefacts PDF text extraction leaves behind.

    Three of them matter for these Bases, in this order:

    * soft hyphens and line-wrap hyphenation (``habili-\\ndades``) - joined,
      because the hyphen is typography, not orthography;
    * the private-use bullet glyph the layout uses for list markers;
    * runs of whitespace, including the tabs the numbered lists are set with.

    A statement is *never* otherwise reworded: what the ministry printed is
    what gets stored.
    """
    text = text.replace("­", "")
    # Join a word broken across a line: "habili-\ndades" -> "habilidades".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"^\s*" + re.escape(_BULLET) + r"\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _norm(text: str) -> str:
    """Fold for lookup: accent-free, lowercase, single-spaced."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"\s+", " ", folded).strip().lower()


def _subject_key(title: str) -> str:
    """Normalise an asignatura heading for the EPJA_SUBJECTS lookup."""
    return re.sub(r"\s*/\s*", " / ", re.sub(r"\s+", " ", title)).strip().lower()


# --------------------------------------------------------------------------- #
# Page parsing
# --------------------------------------------------------------------------- #
def _split_statement_and_eje(body: str) -> Tuple[str, Optional[str]]:
    """Split ``"... con respeto. (Expresión oral)"`` into statement and eje.

    The eje is printed in parentheses at the very end of every objective. Only a
    *trailing* parenthetical counts: statements contain plenty of inline ones
    ("(orales, escritos y audiovisuales)"), and treating those as ejes would
    truncate the statement.
    """
    body = body.strip()
    match = re.search(r"\(([^()]{2,80})\)\s*$", body)
    if not match:
        return body, None
    eje = match.group(1).strip()
    # An eje is a short label, never a sentence.
    if len(eje.split()) > 6 or eje.endswith("."):
        return body, None
    statement = body[: match.start()].strip()
    return statement, eje


def _is_bullet(line: str) -> bool:
    """True for a conocimiento-esencial / sub-item marker line.

    The Bases set every list item with a tab followed by the private-use glyph
    the theme font maps to a bullet. Matching the glyph rather than "a line that
    starts with y" matters: plenty of statements begin with the conjunction.
    """
    return line.startswith(_BULLET)


def _strip_bullet(line: str) -> str:
    return line[len(_BULLET):].strip() if _is_bullet(line) else line.strip()


def _assemble(parts: List[Tuple[str, str]]) -> Tuple[str, Optional[str]]:
    """Turn an objective's parsed parts into ``(statement, eje)``.

    Sub-items keep their own lines with a leading ``- ``, matching how the HTML
    extractor stores the same shape, so a statement that reads "..., considerando:"
    is stored *with* the list it introduces instead of being silently truncated
    at the colon.
    """
    eje: Optional[str] = None
    if parts and parts[-1][0] == "eje":
        eje = parts[-1][1]
        parts = parts[:-1]

    lines: List[str] = []
    for kind, text in parts:
        text = clean_text(text)
        if not text:
            continue
        if kind == "bullet":
            lines.append(f"- {text}")
        elif lines:
            # A plain line following anything is a wrapped continuation of it -
            # of the stem, or of the sub-item just above. Starting a new line
            # here would split a sentence in half mid-word-wrap.
            lines[-1] = f"{lines[-1]} {text}".strip()
        else:
            lines.append(text)

    if not lines:
        return "", eje
    if eje is None:
        lines[-1], eje = _split_statement_and_eje(lines[-1])
        if not lines[-1]:
            lines.pop()
    return "\n".join(lines).strip(), eje


def parse_page(text: str, page_number: int) -> Optional[BasesSection]:
    """Parse one page of a Base Curricular into a definition section.

    Returns ``None`` for any page that is not an objective *definition*.
    Three kinds of page look like one and are not:

    * the **progression grids** and the **tributación annexes**, which repeat
      every objective in a comparison table (excluded by their own headings);
    * the worked **examples** in "¿Cómo se implementan las Bases Curriculares
      en el aula?", which reproduce a real nivel's objectives verbatim inside an
      illustration - the same facsimile trap the Programa parser has to dodge.
      A real definition page always carries the "Asignaturas de Formación ..."
      running header of the part it belongs to; the example pages sit before
      those parts begin and carry none, which is what tells them apart.
    """
    # A definition page is identified by its two column captions. The
    # "Se espera ..." lead-in is *not* part of the test: Responsabilidad
    # Personal y Social omits it, and requiring it silently dropped that
    # asignatura's only definition page.
    if not text or _OBJETIVOS_HEADING not in text or _CONOCIMIENTOS not in text:
        return None
    if any(marker in text for marker in _NOT_A_DEFINITION):
        return None

    header = _FORMACION_HEADER.search(text)
    if header is None:
        return None
    area = _FORMACION_KEY.get(_norm(header.group(1)), "")

    lines = [line.rstrip() for line in text.split("\n")]
    stripped = [line.strip() for line in lines]

    # Locate the ciclo / nivel pair. The section header prints them on their own
    # consecutive lines, which is what distinguishes them from the same words
    # appearing mid-sentence in the surrounding prose.
    ciclo = nivel_key = None
    for index, line in enumerate(stripped):
        ciclo_match = _CICLO.match(line)
        if not ciclo_match:
            continue
        for candidate in stripped[index + 1: index + 3]:
            nivel_match = _NIVEL.match(candidate)
            if nivel_match:
                ciclo = _norm(ciclo_match.group(1))
                first, second = nivel_match.group(1), nivel_match.group(2)
                nivel_key = f"{first}y{second}" if second else first
                break
        if ciclo:
            break
    if ciclo is None or nivel_key is None:
        return None

    subject_title = next(
        (line for line in stripped if _subject_key(line) in EPJA_SUBJECTS), None
    )
    if subject_title is None:
        return None
    subject_slug, subject_name = EPJA_SUBJECTS[_subject_key(subject_title)]

    level_id = EPJA_LEVEL_IDS.get((ciclo, nivel_key))
    section = BasesSection(
        subject_slug=subject_slug,
        subject_name=subject_name,
        level_id=level_id or "",
        formation_area=area,
        pdf_page=page_number,
    )
    if level_id is None:
        section.problems.append(
            f"p{page_number}: unmapped nivel {ciclo!r}/{nivel_key!r} for {subject_name}"
        )
        return section

    oa_indices = [i for i, line in enumerate(stripped) if _OA_LINE.match(line)]
    if not oa_indices:
        section.problems.append(f"p{page_number}: no 'OA n.' line found")
        return section
    start, last_oa = oa_indices[0], oa_indices[-1]

    # Where the *conocimientos esenciales* column begins.
    #
    # Bullets appear in two places: inside an objective that introduces a list
    # ("... considerando:"), and in the subject-wide conocimientos esenciales
    # block. Reading order puts the second lot after every objective, so the
    # boundary is the first bullet that follows the last "OA n." line - which
    # leaves an objective's own sub-items where they belong, inside it.
    boundary = next(
        (i for i in range(last_oa + 1, len(lines)) if _is_bullet(lines[i])), len(lines)
    )

    # -- big ideas: the numbered list between "comprendan que:" and the heading
    ideas_from = next(
        (i for i, line in enumerate(stripped) if line.endswith("comprendan que:")), None
    )
    if ideas_from is not None:
        for line in stripped[ideas_from + 1: start]:
            idea = re.match(r"^\d+\.\s*(.+)$", line)
            if idea:
                section.big_ideas.append(clean_text(idea.group(1)))

    # -- objectives --------------------------------------------------------
    parsed: List[Tuple[int, List[Tuple[str, str]]]] = []
    parts: List[Tuple[str, str]] = []
    current: Optional[int] = None

    def flush() -> None:
        if current is not None:
            parsed.append((current, parts))

    for raw, line in zip(lines[start:boundary], stripped[start:boundary]):
        match = _OA_LINE.match(line)
        if match:
            flush()
            current = int(match.group(1))
            parts = [("text", match.group(2))]
            continue
        if current is None or not line or line == _CAPACES:
            continue
        if _is_bullet(raw):
            parts.append(("bullet", _strip_bullet(raw)))
        elif line.startswith("(") and line.endswith(")"):
            # A standalone eje line, printed under an objective whose statement
            # ended in a sub-item list.
            parts.append(("eje", line[1:-1].strip()))
        else:
            parts.append(("text", line))
    flush()

    for number, objective_parts in parsed:
        statement, eje = _assemble(list(objective_parts))
        if not statement:
            section.problems.append(
                f"p{page_number}: OA {number} parsed to an empty statement"
            )
            continue
        if eje is None:
            # Every EPJA objective prints its eje. A missing one means the
            # column flow was misread, so it is reported instead of guessed.
            section.problems.append(
                f"p{page_number}: OA {number} ({subject_name}) has no trailing eje"
            )
        section.objectives.append(
            BasesObjective(
                number=number,
                code=f"OA {number}",
                statement=statement,
                strand_eje=eje,
                subject_slug=subject_slug,
                subject_name=subject_name,
                level_id=level_id,
                formation_area=area,
                pdf_page=page_number,
            )
        )

    numbers = [o.number for o in section.objectives]
    if numbers != sorted(set(numbers)) or (numbers and numbers[0] != 1):
        section.problems.append(
            f"p{page_number}: {subject_name} objective numbers are not 1..n: {numbers}"
        )

    # -- conocimientos esenciales -----------------------------------------
    knowledge: List[str] = []
    for raw in lines[boundary:]:
        if _is_bullet(raw):
            knowledge.append(_strip_bullet(raw))
        elif knowledge and raw.strip():
            knowledge[-1] = f"{knowledge[-1]} {raw.strip()}"
    section.essential_knowledge = [clean_text(item) for item in knowledge if item.strip()]

    return section


def parse_document(pages: Sequence[str]) -> BasesReport:
    """Parse a whole Base Curricular, given its pages as extracted text."""
    report = BasesReport(pages_scanned=len(pages))
    for index, text in enumerate(pages, start=1):
        section = parse_page(text or "", index)
        if section is None:
            report.pages_skipped_not_definition += 1
            continue
        report.problems.extend(section.problems)
        if not section.level_id:
            continue
        report.sections.append(section)
    return report


def read_pdf(path: Path) -> List[str]:
    """Extract the text of every page of a PDF, in reading order."""
    import pymupdf  # imported lazily: the HTML pipeline never needs it

    with pymupdf.open(path) as document:
        return [page.get_text() for page in document]


def fetch_epja_bases(client: PoliteClient, pdf_cache: Path) -> Tuple[Path, List[str]]:
    """Download (or reuse) the EPJA Bases PDF and return its pages."""
    pdf_cache = Path(pdf_cache)
    destination = pdf_cache / "bases_epja_2024.pdf"
    client.download(EPJA_BASES_2024["pdf_url"], destination)
    return destination, read_pdf(destination)
