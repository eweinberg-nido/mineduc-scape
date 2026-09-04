"""Evaluation indicators (*Indicadores de Evaluación*) from Programa de Estudio PDFs.

These indicators are the one part of the curriculum that curriculumnacional.cl
does not publish in HTML or over its JSON:API - they exist only inside the
*Programa de Estudio* PDFs linked from each subject page. This module resolves
those links, downloads the PDFs and reads the indicator tables out of them.

Every Programa, across the 1°-6° Básico, 7° Básico-2° Medio and 3°-4° Medio
formats, renders the same two-column table:

    OBJETIVOS DE APRENDIZAJE          INDICADORES DE EVALUACIÓN (SUGERIDOS)
    Se espera que ... capaces de:     Los estudiantes que han alcanzado ...
    ----------------------------------------------------------------------
    OA 1                              • Cuentan de 1 en 1 números dados ...
    Contar números naturales del       • Leen representaciones pictóricas ...
    0 al 100 ...

Reading order alone cannot separate the two columns, because an objective's own
sub-bullets use the same bullet glyph as the indicators. So the table is read
geometrically: objective markers anchor the rows, and blocks to the right of the
column boundary are indicators, assigned to the row band they sit in.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

# An objective marker cell: exactly "OA 1", "OA 12", "OA a", "OA F".
OA_MARKER = re.compile(r"^\s*OA\s*([0-9]{1,2}|[A-Za-z])\s*\.?\s*$")

# Some Programas put the code inline at the head of the objective cell, either
# bare ("a. Observar y describir ...", Ciencias Naturales habilidades tables)
# or prefixed ("OA 2: Tomar decisiones ...", the 2021 3° y 4° Medio format).
INLINE_MARKER = re.compile(r"^\s*([0-9]{1,2}|[A-Za-z])[.)]\s+(?=[A-ZÁÉÍÓÚÑ¿])")
# The separator after the code is optional: the Inglés Programas head the cell
# with the code and a strand label, "OA 1 Comprensión auditiva". Anchored at
# the start of a cell, so a mention in running prose cannot match.
PREFIXED_MARKER = re.compile(r"^\s*OA\s*([0-9]{1,2}|[A-Za-z])\s*[.:)]?\s+(?=\S)")

# The per-objective tables always caption their columns with these phrases.
# The 2021 3° y 4° Medio "Actividad de Evaluación" tables have no captions, and
# there the indicator set covers the listed objectives *jointly* rather than
# row by row - so the caption is what tells the two apart.
_PER_OBJECTIVE_CAPTION = re.compile(
    r"(?:se espera que.*capaces de|que han alcanzado este aprendizaje)", re.I
)

# Bullet glyphs used across the three Programa layouts.
BULLETS = ("•", "›", ">>", "‣", "●", "·", "- ")
BULLET_RE = re.compile(r"^\s*(?:•|›|>>|‣|●|·)\s*")

# Header cells. "Objetivos" is plural in the real tables; the singular
# "Objetivo de Aprendizaje" belongs to the per-unit evaluation and class
# suggestions, which are a different construct and are handled separately.
_OBJ_HEADER = re.compile(r"objetivos\s+de\s+aprendizaje", re.I)
_IND_HEADER = re.compile(r"indicadores\s+de\s+evaluaci", re.I)
_OBJ_HEADER_SINGULAR = re.compile(r"objetivo\s+de\s+aprendizaje\s*$", re.I | re.M)

# Bullet glyphs, one set per Programa typeface.
_BULLET_GLYPHS = (
    r"•|›|>>|‣|●"
    # A lone ">" bullets the Tecnología Programas. Guarded by a following
    # capital so an inequality ("x > 3", "y > z") is never split on.
    r"|>(?=\s+[A-ZÁÉÍÓÚÑ])"
    # Several Programas bullet with a Symbol-font character that decodes to
    # "ú"; it counts only when it stands alone, since no Spanish word is a
    # bare "ú", so real accented text is untouched.
    r"|(?<![^\W\d_])ú(?=\s)"
)
_BULLET_ANY = re.compile(f"(?:{_BULLET_GLYPHS})")
_BULLET_SPLIT = re.compile(f"\\s*(?:{_BULLET_GLYPHS})\\s*")
_BULLET_START = re.compile(f"^\\s*(?:{_BULLET_GLYPHS})")

# Unit tabs, page numbers and eje labels bleed into the right-hand column on
# some layouts; they are never indicators.
_FURNITURE = re.compile(
    r"^(?:U\s*\d+|UNIDAD\s*\d+|EJE\b.*|\d+|[IVX]+|Pág\.?\s*\d+)$", re.I
)
_COLUMN_SUBHEADS = (
    "se espera que",
    "los estudiantes que",
    "las y los estudiantes que",
    "los y las estudiantes que",
    "el estudiante que",
)

MIN_INDICATOR_LEN = 12
COLUMN_GAP = 55.0             # pt; minimum horizontal gap between the columns
ROW_TOLERANCE = 10.0          # pt; an indicator may start just above its marker
MARKER_X_TOLERANCE = 40.0     # pt; how far a marker may drift from the column
HEADER_EDGE_MARGIN = 15.0     # pt; header labels are indented inside their column
STATEMENT_SAMPLE_LEN = 400    # chars of objective text kept for join verification
MIN_FONT_SIZE = 6.0          # pt; below this a page is a shrunken facsimile
BULLET_X_TOLERANCE = 20.0     # pt; a bullet sits on the column edge
CONTINUATION_X_TOLERANCE = 45.0  # pt; wrapped lines are indented a little


@dataclass
class TableRow:
    """One row of an objective/indicator table: a code, its statement, its indicators.

    Rows are kept separate rather than merged by code. The same code appears in
    several unit tables, and some Programas include a shrunken facsimile of
    another grade's table as an illustration; keeping rows independent lets each
    one be verified against the published objective on its own.
    """

    code: str
    page: int
    statement: str = ""
    indicators: List[str] = field(default_factory=list)
    # True when the table lists one indicator set for a group of objectives
    # instead of one set per objective.
    joint: bool = False


@dataclass
class PdfIndicators:
    """Everything read out of one Programa de Estudio PDF."""

    pdf_url: str
    pages: int = 0
    table_pages: int = 0
    rows: List[TableRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(len(row.indicators) for row in self.rows)

    @property
    def codes(self) -> set:
        return {row.code for row in self.rows if row.indicators}


# --------------------------------------------------------------------------- #
# link resolution
# --------------------------------------------------------------------------- #
def resolve_pdf_url(html: str, page_url: str) -> Optional[str]:
    """Find the PDF attached to a ``/recursos/...`` document page."""
    tree = HTMLParser(html)
    candidates: List[str] = []
    for link in tree.css("a[href]"):
        href = link.attributes.get("href") or ""
        if ".pdf" in href.lower():
            candidates.append(urljoin(page_url, href))
    if not candidates:
        return None
    # Programas are published as "articles-<id>_programa.pdf"; prefer that over
    # any incidental attachment.
    for url in candidates:
        if "programa" in url.lower():
            return url
    return candidates[0]


# --------------------------------------------------------------------------- #
# PDF table reading
# --------------------------------------------------------------------------- #
def _median_font_size(page) -> float:
    """Median glyph size on a page, weighted by how many characters use it."""
    sizes: List[float] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                stripped = span["text"].strip()
                if stripped:
                    sizes.extend([span["size"]] * len(stripped))
    if not sizes:
        return 0.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def _clean(text: str) -> str:
    text = text.replace("­", "")           # soft hyphen
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # de-hyphenate line wraps
    return re.sub(r"\s+", " ", text).strip()


def _is_bullet(text: str) -> bool:
    return bool(BULLET_RE.match(text.lstrip()))


def _strip_bullet(text: str) -> str:
    return BULLET_RE.sub("", text.lstrip(), count=1).strip()


def _split_bullets(text: str) -> List[str]:
    """Split a table cell into its bullet items.

    In the 1° a 6° Básico layout the whole indicator cell arrives as one block
    with the bullets inside it; in the 7° Básico onward layouts each bullet is
    its own block. Splitting on the glyph handles both.
    """
    if not _BULLET_ANY.search(text):
        return [text.strip()] if text.strip() else []
    parts = _BULLET_SPLIT.split(text)
    # Anything before the first bullet is a stray fragment, not an indicator.
    return [part.strip() for part in parts[1:] if part.strip()]


def _is_page_decoration(text: str) -> bool:
    """Unit tabs, page numbers, eje labels and column captions."""
    flat = text.strip()
    if not flat or _FURNITURE.match(flat):
        return True
    if _IND_HEADER.search(flat) or _OBJ_HEADER.search(flat):
        return True
    return flat.lower().startswith(_COLUMN_SUBHEADS)


def _is_furniture(text: str) -> bool:
    """Anything that cannot start an indicator: decoration, or too short."""
    return len(text.strip()) < MIN_INDICATOR_LEN or _is_page_decoration(text)


def _find_table(blocks: List[tuple]) -> Tuple[bool, Optional[float]]:
    """Decide whether a page holds an objective/indicator table.

    Returns ``(is_table_page, explicit_column_edge)``. The header may be one
    merged block or two blocks on a shared baseline; only the latter reveals
    the column edge directly, so the edge is optional.
    """
    has_obj = False
    has_ind = False
    obj_cells: List[Tuple[float, float]] = []
    ind_cells: List[Tuple[float, float]] = []
    for x0, y0, _x1, _y1, text, *_ in blocks:
        flat = _clean(text)
        if not flat:
            continue
        obj_here = bool(_OBJ_HEADER.search(flat))
        ind_here = bool(_IND_HEADER.search(flat))
        has_obj = has_obj or obj_here
        has_ind = has_ind or ind_here
        if obj_here and flat.lower().startswith("objetivos de aprendizaje"):
            obj_cells.append((x0, y0))
        if ind_here and _IND_HEADER.match(flat):
            ind_cells.append((x0, y0))
    if not (has_obj and has_ind):
        return False, None
    for ix, iy in ind_cells:
        for ox, oy in obj_cells:
            if abs(iy - oy) < 8 and ix - ox > COLUMN_GAP:
                return True, ix - 2.0
    return True, None


def _infer_column_edge(blocks: List[tuple], marker_x: float) -> Optional[float]:
    """Infer the indicator column's left edge from the bulleted cells."""
    xs = sorted(
        x0 for x0, _y0, _x1, _y1, text, *_ in blocks
        if _BULLET_ANY.search(_clean(text)) and x0 - marker_x > COLUMN_GAP
    )
    return xs[0] - 2.0 if xs else None


def _find_markers(
    blocks: List[tuple], per_objective: bool = True
) -> List[Tuple[str, float, float]]:
    """Locate the objective markers on a table page, as ``(code, x0, y0)``.

    Standalone "OA 1" cells are preferred. Failing that, the code may sit
    inline at the head of the objective cell, either prefixed ("OA 2: ...") or
    bare ("a. ...").

    The bare form is only trusted on pages that caption their columns, because
    an activity page's numbered steps ("4. Elabora un modelo ...") look exactly
    like it. Captioned pages are the per-objective tables, and those are the
    only ones that use the bare form.
    """
    standalone = [
        (OA_MARKER.match(_clean(text)).group(1), x0, y0)
        for x0, y0, _x1, _y1, text, *_ in blocks
        if OA_MARKER.match(_clean(text))
    ]
    if standalone:
        return standalone

    patterns = (PREFIXED_MARKER, INLINE_MARKER) if per_objective else (PREFIXED_MARKER,)
    for pattern in patterns:
        inline = [
            (pattern.match(_clean(text)).group(1), x0, y0)
            for x0, y0, _x1, _y1, text, *_ in blocks
            if pattern.match(_clean(text))
        ]
        if inline:
            return inline
    return []


def _is_per_objective(blocks: List[tuple]) -> bool:
    """Whether this page's table pairs each objective with its own indicators."""
    return any(
        _PER_OBJECTIVE_CAPTION.search(_clean(text))
        for _x0, _y0, _x1, _y1, text, *_ in blocks
    )


def _column_of(markers: List[Tuple[str, float, float]]) -> Optional[float]:
    """The objective column's left edge: the modal marker x0."""
    if not markers:
        return None
    xs = sorted(x0 for _code, x0, _y0 in markers)
    return xs[len(xs) // 2]


def _left_fragments(
    blocks: List[tuple], column_edge: float, marker_x: float
) -> List[Tuple[float, str]]:
    """Collect the objective-column text on one page, for join verification."""
    out: List[Tuple[float, str]] = []
    for x0, y0, _x1, _y1, text, *_ in blocks:
        flat = _clean(text)
        if not flat or x0 >= column_edge:
            continue
        if x0 < marker_x - MARKER_X_TOLERANCE:
            continue  # rotated strand labels and page furniture
        if _IND_HEADER.search(flat) or _OBJ_HEADER.search(flat):
            continue
        if flat.lower().startswith(_COLUMN_SUBHEADS) or _FURNITURE.match(flat):
            continue
        out.append((y0, flat))
    out.sort(key=lambda f: f[0])
    return out


def _page_fragments(
    blocks: List[tuple], column_edge: float
) -> List[Tuple[float, str, bool]]:
    """Collect the indicator-column fragments on one page."""
    fragments: List[Tuple[float, str, bool]] = []
    for x0, y0, _x1, _y1, text, *_ in blocks:
        flat = _clean(text)
        if not flat:
            continue
        offset = x0 - column_edge
        if offset < 0:
            continue
        starts_bullet = bool(_BULLET_START.match(flat))
        # Bullets sit on the column edge; wrapped continuation lines are
        # indented a little. Anything further right belongs to another region
        # of the page (side notes, facsimiles, a third column).
        limit = BULLET_X_TOLERANCE if starts_bullet else CONTINUATION_X_TOLERANCE
        if offset > limit:
            continue
        if starts_bullet:
            for item in _split_bullets(flat):
                if not _is_furniture(item):
                    fragments.append((y0, item, True))
        elif not _is_page_decoration(flat):
            # Continuation lines are appended to the bullet above them, so they
            # are exempt from the length floor - a wrapped tail can be a single
            # word ("viceversa.").
            fragments.append((y0, flat, False))
    fragments.sort(key=lambda f: f[0])
    if fragments and not any(is_bullet for _y, _text, is_bullet in fragments):
        # Some 2021 Programas (Química, for one) set the indicators as plain
        # paragraphs with no bullet glyph at all. With nothing to split on,
        # each block in the column is one indicator.
        fragments = [(y0, text, True) for y0, text, _bullet in fragments]
    return fragments


def parse_page(
    blocks: List[tuple], page_number: int, page_text: str = ""
) -> List[TableRow]:
    """Read one page's objective/indicator table, if it holds one.

    This is the entire per-page decision, kept separate from PDF handling so it
    can be exercised against block layouts captured from the real Programas.
    """
    is_table, header_edge = _find_table(blocks)
    if not is_table:
        return []

    per_objective = _is_per_objective(blocks)
    markers = _find_markers(blocks, per_objective=per_objective)
    marker_x = _column_of(markers)
    if marker_x is None:
        return _joint_from_text(page_text, page_number)

    aligned = [
        (code, y0) for code, x0, y0 in markers
        if abs(x0 - marker_x) < MARKER_X_TOLERANCE
    ]
    aligned.sort(key=lambda marker: marker[1])

    # The bullets themselves locate the column better than the header cell
    # does: header labels are indented relative to their own column.
    column_edge = _infer_column_edge(blocks, marker_x)
    if column_edge is None and header_edge is not None:
        column_edge = header_edge - HEADER_EDGE_MARGIN
    if column_edge is None:
        return _joint_from_text(page_text, page_number)

    fragments = _page_fragments(blocks, column_edge)
    if not fragments:
        return _joint_from_text(page_text, page_number)

    if per_objective:
        rows = _assign_page(aligned, fragments, page_number)
    else:
        rows = _joint_page(aligned, fragments, page_number)
    if not rows:
        return []
    _assign_statements(rows, aligned, _left_fragments(blocks, column_edge, marker_x))
    return [row for row in rows if row.indicators]


def extract_from_pdf(path: Path, pdf_url: str = "") -> PdfIndicators:
    """Read every objective/indicator table in one Programa de Estudio PDF.

    Only pages that carry the table header are parsed. MINEDUC repeats the
    header on every page of a multi-page table, in every Programa layout, so
    each table page is self-contained -- which means no state has to be carried
    across page breaks, and activity pages (which also mix objective markers
    with bullet lists) can never be mistaken for tables.
    """
    import fitz  # PyMuPDF; imported lazily so the HTML pipeline needs no PDF deps

    # Several Programas have malformed content streams that MuPDF recovers from
    # while printing to stderr; the recovered text is fine, the noise is not.
    fitz.TOOLS.mupdf_display_errors(False)

    result = PdfIndicators(pdf_url=pdf_url)
    document = fitz.open(path)
    result.pages = document.page_count
    try:
        for index in range(document.page_count):
            page = document[index]
            if _median_font_size(page) < MIN_FONT_SIZE:
                # Both Básico layouts illustrate the table format with a
                # shrunken screenshot of *another grade's* Programa. It parses
                # perfectly and would contribute the wrong grade's indicators.
                continue
            rows = parse_page(page.get_text("blocks"), index + 1, page.get_text())
            if rows:
                result.table_pages += 1
                result.rows.extend(rows)
    finally:
        document.close()

    return result



# In the "extracto" Programas the whole objectives cell - caption and all its
# objectives - arrives as one block, and the indicators cell can sit to the
# *left* of it, so geometry gives out. These tables are joint anyway, so the
# page text is enough: read the codes, then read the bullets.
_OBJ_CAPTION_ANY = re.compile(r"objetivos\s+de\s+aprendizaje", re.I)
_IND_CAPTION_ANY = re.compile(r"indicadores\s+de\s+evaluaci\w*", re.I)
_OA_IN_TEXT = re.compile(r"\bOA\s*([0-9]{1,2}|[A-Za-z])\s*[.:)]\s")
_SECTION_END = re.compile(
    r"^\s*(?:DURACI[ÓO]N|Duraci[óo]n|DESARROLLO|INICIO|CIERRE|RECURSOS|"
    r"ORIENTACIONES|Observaciones al docente|Actividad|Recordemos|"
    r"Se puede usar|Se sugiere delimitar)\b",
    re.M,
)


def _joint_from_text(text: str, page_number: int) -> List[TableRow]:
    """Read a joint evaluation table straight from the page text."""
    obj = _OBJ_CAPTION_ANY.search(text)
    ind = _IND_CAPTION_ANY.search(text, obj.end() if obj else 0)
    if not obj or not ind:
        return []

    codes: List[Tuple[str, str]] = []
    objectives_region = text[obj.end():ind.start()]
    found = list(_OA_IN_TEXT.finditer(objectives_region))
    for position, match in enumerate(found):
        end = found[position + 1].start() if position + 1 < len(found) else len(objectives_region)
        codes.append((match.group(1), _clean(objectives_region[match.end():end])))
    if not codes:
        return []

    tail = text[ind.end():]
    stop = _SECTION_END.search(tail)
    if stop:
        tail = tail[:stop.start()]
    indicators: List[str] = []
    for item in _split_bullets(tail):
        cleaned = _clean(item)
        if not _is_furniture(cleaned) and cleaned not in indicators:
            indicators.append(cleaned)
    if not indicators:
        return []

    return [
        TableRow(code=code, page=page_number, statement=statement,
                 indicators=list(indicators), joint=True)
        for code, statement in codes
    ]


def _assign_page(
    markers: List[Tuple[str, float]],
    fragments: List[Tuple[float, str, bool]],
    page_number: int,
) -> List[TableRow]:
    """Turn a per-objective table page into rows, by vertical row band."""
    rows: List[TableRow] = [TableRow(code=code, page=page_number) for code, _y in markers]
    current: Optional[TableRow] = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal buffer
        text = _clean(" ".join(buffer))
        buffer = []
        if current is None or len(text) < MIN_INDICATOR_LEN:
            return
        if text not in current.indicators:
            current.indicators.append(text)

    pointer = 0
    for y0, text, is_bullet in fragments:
        while pointer < len(markers) and markers[pointer][1] <= y0 + ROW_TOLERANCE:
            flush()
            current = rows[pointer]
            pointer += 1
        if current is None:
            continue
        if is_bullet:
            flush()
            buffer = [text]
        elif buffer:
            buffer.append(text)
    flush()
    return rows


def _joint_page(
    markers: List[Tuple[str, float]],
    fragments: List[Tuple[float, str, bool]],
    page_number: int,
) -> List[TableRow]:
    """Turn a joint evaluation table into one row per objective, sharing the set.

    The 2021 3° y 4° Medio Programas present an "Actividad de Evaluación" whose
    indicators evaluate the listed objectives together; splitting them by
    vertical position would invent a precision the source does not have.
    """
    indicators: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        nonlocal buffer
        text = _clean(" ".join(buffer))
        buffer = []
        if len(text) >= MIN_INDICATOR_LEN and text not in indicators:
            indicators.append(text)

    for _y0, text, is_bullet in fragments:
        if is_bullet:
            flush()
            buffer = [text]
        elif buffer:
            buffer.append(text)
    flush()
    if not indicators:
        return []
    return [
        TableRow(code=code, page=page_number, indicators=list(indicators), joint=True)
        for code, _y in markers
    ]


def _assign_statements(
    rows: List[TableRow],
    markers: List[Tuple[str, float]],
    left: List[Tuple[float, str]],
) -> None:
    """Record the objective statement printed beside each row's code.

    ``rows`` is expected to be parallel to ``markers``; a caller that returned
    fewer rows (a joint page with no indicators at all) has nothing to annotate.
    """
    if len(rows) != len(markers):
        return
    current: Optional[TableRow] = None
    pointer = 0
    for y0, text in left:
        while pointer < len(markers) and markers[pointer][1] <= y0 + ROW_TOLERANCE:
            current = rows[pointer]
            pointer += 1
        if current is None or len(current.statement) >= STATEMENT_SAMPLE_LEN:
            continue
        current.statement = _clean(f"{current.statement} {text}")[:STATEMENT_SAMPLE_LEN]


# --------------------------------------------------------------------------- #
# joining PDF indicators onto the dataset
# --------------------------------------------------------------------------- #
from .normalize import parse_code  # noqa: E402  (imported here to keep the join local)

CATEGORY_CONOCIMIENTO = "conocimiento"
CATEGORY_HABILIDAD = "habilidad"
CATEGORY_ACTITUD = "actitud"

# Minimum statement similarity before indicators are attached, plus the margin
# the best match must hold over the runner-up. Genuine matches score ~0.9-1.0
# and near-misses below 0.35, so the gap is wide; these thresholds exist to
# reject mis-parsed rows, not to permit fuzzy matching.
MATCH_THRESHOLD = 0.55
MATCH_MARGIN = 0.10      # the winner must beat the runner-up by this much
NGRAM_SIZE = 5
MIN_MATCH_CHARS = 25     # below this a statement is too short to match safely


def objective_key(code: str, category: str) -> Optional[Tuple[str, str]]:
    """Join key for a dataset objective: (category, normalised index)."""
    _marker, suffix = parse_code(code)
    if not suffix:
        return None
    digits = re.findall(r"\d+", suffix)
    if digits:
        return (category, str(int(digits[-1])))
    letters = re.sub(r"[^A-Za-z]", "", suffix)
    if len(letters) == 1:
        return (category, letters)
    return None


def pdf_code_candidates(pdf_code: str) -> List[Tuple[str, str]]:
    """Candidate join keys for a short PDF code, most likely first.

    Programas write the bare index: digits for thematic objectives, a lowercase
    letter for skills and an uppercase letter for attitudes. The case
    convention is consistent across the Programas sampled, but both readings
    are offered so a subject that departs from it still joins.
    """
    code = pdf_code.strip()
    if code.isdigit():
        index = str(int(code))
        return [
            (CATEGORY_CONOCIMIENTO, index),
            (CATEGORY_HABILIDAD, index),
            (CATEGORY_ACTITUD, index),
        ]
    if code.islower():
        return [(CATEGORY_HABILIDAD, code), (CATEGORY_ACTITUD, code.upper())]
    return [(CATEGORY_ACTITUD, code), (CATEGORY_HABILIDAD, code.lower())]


def _normalise(text: str) -> str:
    """Fold a statement to comparable characters.

    NFKD is deliberate: it decomposes the ligatures the Programas are typeset
    with (``Identiﬁ car``), which would otherwise not match the HTML text.
    Spaces are dropped too, so the PDF's hyphenated line breaks
    (``relacio- narlas``) and stray ligature spacing stop mattering.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


def _ngrams(text: str, size: int = NGRAM_SIZE) -> set:
    return {text[i:i + size] for i in range(max(0, len(text) - size + 1))}


def statement_similarity(pdf_text: str, html_text: str) -> float:
    """How much of the shorter statement appears in the longer one, 0..1.

    Containment rather than Jaccard: the PDF row text is truncated and carries
    the objective's sub-bullets, while the HTML statement is the full published
    sentence, so the two are never the same length. Character n-grams rather
    than words, because PDF extraction breaks words at ligatures and line-wrap
    hyphens.
    """
    a = _normalise(re.sub(r"^\s*OA\s*[0-9A-Za-z]{1,2}[.)]?\s*", "", pdf_text))
    b = _normalise(html_text)
    if len(a) < MIN_MATCH_CHARS or len(b) < MIN_MATCH_CHARS:
        return 0.0
    ga, gb = _ngrams(a), _ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


@dataclass
class JoinReport:
    subjects_with_pdf: int = 0
    pdfs_read: int = 0
    pdfs_failed: List[dict] = field(default_factory=list)
    objectives_matched: int = 0
    indicators_attached: int = 0
    codes_unmatched: List[str] = field(default_factory=list)
    rejected_low_similarity: List[dict] = field(default_factory=list)
    rejected_ambiguous: List[dict] = field(default_factory=list)
    shared_pdf_warnings: List[str] = field(default_factory=list)
    # Rows whose printed code differs from the matched objective's code: the
    # Básico Programas predate a renumbering of the Bases Curriculares.
    renumbered_rows: int = 0
    # Rows from joint "Actividad de Evaluación" tables, where one indicator set
    # covers several objectives at once.
    joint_rows: int = 0


def attach_to_subject(
    subject: dict,
    extracted: PdfIndicators,
    level_id: str,
    report: JoinReport,
    threshold: float = MATCH_THRESHOLD,
) -> int:
    """Attach one PDF's indicator rows to a subject's objectives.

    Matching is driven by the objective *statement*, not by its code. The
    1° a 6° Básico Programas were published under an earlier decree and number
    their objectives differently from the Bases Curriculares the site publishes
    today - "OA 12" in the Matemática 1° básico Programa is MA01 OA 14 on the
    site. Joining on the code would therefore attach a large share of the
    Básico indicators to the wrong objective, silently. The printed code is
    still used, as a tie-breaker when two objectives score alike.
    """
    objectives = subject.get("learning_objectives", [])
    attached = 0
    matched_objectives = set()
    renumbered = 0

    for row in extracted.rows:
        scored = sorted(
            ((statement_similarity(row.statement, o["statement"]), o) for o in objectives),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored:
            report.codes_unmatched.append(f"{level_id}/{subject['subject_id']}")
            continue

        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        where = f"{level_id}/{subject['subject_id']}/OA {row.code} (p{row.page})"

        if best_score < threshold:
            # Record the row in full, indicator text included. A row dropped
            # here is source material the dataset does not otherwise keep, so
            # discarding it silently would make the gap unauditable.
            report.rejected_low_similarity.append(
                {
                    "where": where,
                    "level_id": level_id,
                    "subject_id": subject["subject_id"],
                    "pdf_code": row.code,
                    "pdf_page": row.page,
                    "pdf_url": extracted.pdf_url,
                    "similarity": round(best_score, 3),
                    "closest_code": best["code"],
                    "closest_oa_id": best["oa_id"],
                    "pdf_statement": row.statement,
                    "indicators": row.indicators,
                    "joint": row.joint,
                }
            )
            continue
        if best_score - runner_up < MATCH_MARGIN:
            # Two objectives read alike; prefer the one whose printed index
            # matches, and give up if that does not disambiguate either.
            tied = [o for score, o in scored if best_score - score < MATCH_MARGIN]
            by_code = [
                o for o in tied
                if objective_key(o.get("code", ""), o["category"])
                in pdf_code_candidates(row.code)
            ]
            if len(by_code) != 1:
                report.rejected_ambiguous.append(
                    {
                        "where": where,
                        "level_id": level_id,
                        "subject_id": subject["subject_id"],
                        "pdf_code": row.code,
                        "pdf_page": row.page,
                        "pdf_url": extracted.pdf_url,
                        "similarity": round(best_score, 3),
                        "candidates": [o["code"] for o in tied],
                        "pdf_statement": row.statement,
                        "indicators": row.indicators,
                    }
                )
                continue
            best = by_code[0]

        if objective_key(best.get("code", ""), best["category"]) not in pdf_code_candidates(row.code):
            renumbered += 1

        bucket = best.setdefault("indicators", [])
        for indicator in row.indicators:
            if indicator not in bucket:
                bucket.append(indicator)
                attached += 1
        scope = "unit" if row.joint else "objective"
        previous = best.get("indicators_scope")
        best["indicators_scope"] = scope if previous in (None, scope) else "mixed"
        if row.joint:
            report.joint_rows += 1
        sources = best.setdefault("indicators_source", [])
        if extracted.pdf_url and extracted.pdf_url not in sources:
            sources.append(extracted.pdf_url)
        matched_objectives.add(best["oa_id"])

    report.objectives_matched += len(matched_objectives)
    report.indicators_attached += attached
    report.renumbered_rows += renumbered
    return attached


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
PROGRAMA_DOC_TYPE = "Programa de estudio"


def _pdf_filename(url: str) -> str:
    name = url.rstrip("/").split("/")[-1] or "programa.pdf"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def programa_documents(database: dict) -> Dict[str, List[Tuple[str, dict]]]:
    """Map each Programa de Estudio page URL to the subjects that cite it."""
    citations: Dict[str, List[Tuple[str, dict]]] = {}
    for level_id, level in database.get("levels", {}).items():
        for subject in level.get("subjects", {}).values():
            for document in subject.get("documents", []):
                if document.get("doc_type") == PROGRAMA_DOC_TYPE:
                    citations.setdefault(document["url"], []).append((level_id, subject))
    return citations


def enrich(
    client,
    database: dict,
    pdf_cache: Path,
    limit: Optional[int] = None,
    threshold: float = MATCH_THRESHOLD,
) -> JoinReport:
    """Download every Programa de Estudio and attach its indicators in place."""
    citations = programa_documents(database)
    report = JoinReport()
    report.subjects_with_pdf = sum(len(v) for v in citations.values())
    pdf_cache = Path(pdf_cache)

    pages = sorted(citations)
    if limit:
        pages = pages[:limit]
    log.info("%d Programa de Estudio documents to process", len(pages))

    for position, page_url in enumerate(pages, start=1):
        subjects = citations[page_url]
        try:
            pdf_url = resolve_pdf_url(client.get_text(page_url), page_url)
            if not pdf_url:
                report.pdfs_failed.append({"url": page_url, "error": "no PDF link on page"})
                continue
            path = client.download(pdf_url, pdf_cache / _pdf_filename(pdf_url))
            extracted = extract_from_pdf(path, pdf_url=pdf_url)
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run
            log.error("indicator pass failed for %s: %s", page_url, exc)
            report.pdfs_failed.append({"url": page_url, "error": str(exc)})
            continue

        report.pdfs_read += 1
        distinct_subjects = {subject["subject_id"] for _level, subject in subjects}
        if len(distinct_subjects) > 2:
            report.shared_pdf_warnings.append(
                f"{pdf_url} is cited by {len(distinct_subjects)} different subjects"
            )
        for level_id, subject in subjects:
            attach_to_subject(subject, extracted, level_id, report, threshold=threshold)

        if position % 20 == 0 or position == len(pages):
            log.info("  %d/%d documents (%d indicators attached)",
                     position, len(pages), report.indicators_attached)
    return report


def coverage(database: dict) -> dict:
    """Count how much of the dataset now carries indicators."""
    total = 0
    with_indicators = 0
    indicators = 0
    by_category: Dict[str, List[int]] = {}
    for level in database.get("levels", {}).values():
        for subject in level.get("subjects", {}).values():
            for objective in subject.get("learning_objectives", []):
                total += 1
                count = len(objective.get("indicators") or [])
                stats = by_category.setdefault(objective["category"], [0, 0])
                stats[0] += 1
                if count:
                    with_indicators += 1
                    indicators += count
                    stats[1] += 1
    return {
        "objectives": total,
        "objectives_with_indicators": with_indicators,
        "indicators": indicators,
        "by_category": {
            category: {"objectives": counts[0], "with_indicators": counts[1]}
            for category, counts in sorted(by_category.items())
        },
    }
