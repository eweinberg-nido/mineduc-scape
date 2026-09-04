"""Normalization: canonical global IDs, objective numbers and keyword tags.

Every function here is deterministic - the same page always yields the same
ids and keywords, so regenerating the dataset produces a stable diff.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .taxonomy import (
    CATEGORY_TOKEN,
    derive_abbrev,
    slugify,
    strip_accents,
    subject_abbrev,
)

# Strand kinds that describe *content* organisation and therefore belong in the
# canonical id. Habilidad/Actitud groupings are already implied by the category.
_ID_STRAND_KINDS = {"Eje", "Núcleo", "Módulo", "Ámbito", "Unidad"}

_CODE_MARKER = re.compile(r"\b(OAC|OAH|OAA|OAT|OAF|OA)\b[\s.\-]*([A-Za-z0-9]*)")

# Spanish function words plus curriculum boilerplate that carries no search value.
STOPWORDS = {
    "a", "al", "ante", "asi", "aun", "aunque", "cada", "como", "con", "contra",
    "cual", "cuales", "cuando", "cuanto", "de", "del", "desde", "donde", "dos",
    "e", "el", "ella", "ellas", "ellos", "en", "entre", "era", "es", "esa",
    "esas", "ese", "eso", "esos", "esta", "estas", "este", "estos", "etc",
    "ha", "hacia", "han", "hasta", "hay", "la", "las", "le", "les", "lo", "los",
    "mas", "me", "mediante", "mi", "mis", "mucho", "muy", "ni", "no", "nos",
    "o", "otra", "otras", "otro", "otros", "para", "pero", "por", "porque",
    "que", "quien", "se", "segun", "sean", "ser", "si", "sin", "sobre", "solo",
    "son", "su", "sus", "tal", "tales", "tambien", "tanto", "te", "tras", "tu",
    "un", "una", "unas", "uno", "unos", "usando", "vez", "y", "ya", "yo",
    # curriculum boilerplate
    "acuerdo", "ejemplo", "forma", "manera", "modo", "tipo", "traves", "partir",
    "distintos", "distintas", "diversos", "diversas", "diferentes", "propios",
    "propias", "siguientes", "otras",
}

MIN_KEYWORD_LEN = 4
MAX_KEYWORDS = 12


def parse_code(code: str) -> Tuple[Optional[str], Optional[str]]:
    """Split an official code into its marker and suffix.

    >>> parse_code("MA1M OA 07")
    ('OA', '07')
    >>> parse_code("MA1M OAH a")
    ('OAH', 'a')
    >>> parse_code("AR-AVAM-3y4-OAC-01")
    ('OAC', '01')
    """
    match = _CODE_MARKER.search(code or "")
    if not match:
        return None, None
    return match.group(1), (match.group(2) or None)


def objective_number(code: str, fallback: int) -> int:
    """Derive the objective's ordinal from its official code.

    Letter-indexed objectives (``OAH a``, ``OAA E``) map onto 1, 5, ...;
    ``fallback`` (the 1-based position inside its group) is used when the code
    carries no usable index.
    """
    _, suffix = parse_code(code)
    if suffix:
        digits = re.findall(r"\d+", suffix)
        if digits:
            return int(digits[-1])
        letters = re.sub(r"[^A-Za-z]", "", suffix)
        if len(letters) == 1:
            return ord(letters.lower()) - ord("a") + 1
    # Some pages omit the marker; fall back to any trailing number in the code.
    trailing = re.search(r"(\d+)\s*\.?\s*$", code or "")
    if trailing:
        return int(trailing.group(1))
    return fallback


def _id_suffix(code: str, number: int) -> str:
    """Render the numeric part of a canonical id ("01", or "A" for letters)."""
    _, suffix = parse_code(code)
    if suffix:
        letters = re.sub(r"[^A-Za-z]", "", suffix)
        digits = re.findall(r"\d+", suffix)
        if letters and not digits and len(letters) == 1:
            return letters.upper()
        if letters and digits:
            # Codes such as "LC01 OA LF01" carry a meaningful letter group.
            return f"{letters.upper()}{int(digits[-1]):02d}"
    return f"{number:02d}"


def strand_id(strand_name: Optional[str]) -> Optional[str]:
    return slugify(strand_name) if strand_name else None


def canonical_oa_id(
    subject_slug: str,
    level_token: str,
    category: str,
    code: str,
    number: int,
    strand_name: Optional[str] = None,
    strand_kind: Optional[str] = None,
) -> str:
    """Build the global canonical id, e.g. ``CL_MAT_3M_GEO_OA01``."""
    pieces = ["CL", subject_abbrev(subject_slug), level_token]
    if strand_name and strand_kind in _ID_STRAND_KINDS:
        pieces.append(derive_abbrev(slugify(strand_name, "-"), 4))
    pieces.append(f"{CATEGORY_TOKEN[category]}{_id_suffix(code, number)}")
    return "_".join(pieces)


def code_slug(code: str) -> str:
    """URL/lookup-friendly form of an official code: ``MA1M OA 07`` -> ``ma1m-oa-07``."""
    return slugify(code, "-")


def extract_keywords(statement: str, limit: int = MAX_KEYWORDS) -> List[str]:
    """Pull search tags out of an objective statement.

    The leading word of a Chilean OA is nearly always the cognitive verb
    ("Calcular...", "Analizar..."), so it is kept first and always retained.
    """
    if not statement:
        return []
    cleaned = re.sub(r"[^\wáéíóúñüÁÉÍÓÚÑÜ\s-]", " ", statement, flags=re.UNICODE)
    tokens = [t for t in re.split(r"[\s\-]+", cleaned.lower()) if t]
    if not tokens:
        return []

    keywords: List[str] = []
    seen = set()

    def add(token: str) -> None:
        key = strip_accents(token)
        if key in seen:
            return
        seen.add(key)
        keywords.append(token)

    verb = tokens[0]
    if len(verb) >= MIN_KEYWORD_LEN and strip_accents(verb) not in STOPWORDS:
        add(verb)

    for token in tokens[1:]:
        if len(keywords) >= limit:
            break
        if len(token) < MIN_KEYWORD_LEN or token.isdigit():
            continue
        if strip_accents(token) in STOPWORDS:
            continue
        add(token)
    return keywords[:limit]
