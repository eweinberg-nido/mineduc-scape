"""Sectores económicos of the Técnico-Profesional specialities.

The 34 TP specialities are organised into 15 *sectores económicos*
(Administración, Agropecuario, Metalmecánica, ...). That grouping is MINEDUC's
own — it is the structure the site's master index
``/curriculum/ambitos-y-asignaturas`` renders the TP specialities under — so it
is read from the source rather than hand-written here, and a speciality moving
sector is picked up without a code change.

It is recorded on the subject in the canonical dataset (`tp_sector`), not
computed inside an exporter. Anything derived from the curriculum belongs in the
dataset: an exporter that re-derived it would be a second, divergent copy of a
fact the ministry publishes once.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from selectolax.parser import HTMLParser

from .extract import BASE_URL
from .http import PoliteClient

log = logging.getLogger(__name__)

INDEX_PATH = "/curriculum/ambitos-y-asignaturas"

# The sector headings the index prints. Matching against a known set, rather
# than "every h2", is what keeps the site's own navigation headings ("Curriculum
# por asignatura", "Navegación principal") from being read as sectors.
SECTOR_HEADINGS = (
    "Administración",
    "Agropecuario",
    "Alimentación",
    "Confección",
    "Construcción",
    "Electricidad",
    "Gráfico",
    "Hotelería y Turismo",
    "Maderero",
    "Marítimo",
    "Metalmecánica",
    "Minero",
    "Química e Industria",
    "Salud y Educación",
    "Tecnología y Comunicaciones",
)


def parse_sectors(html: str) -> Dict[str, str]:
    """Map each speciality's subject slug to its sector, from the master index.

    The index is a flat document: a sector ``<h2>`` followed by the links to the
    specialities in it. So the parse walks in document order, remembering the
    most recent sector heading, and clears it on any other ``<h2>`` — otherwise
    the links that follow the final sector (the site's own "Curriculum por
    asignatura" listings) would all be swept into the last one.
    """
    tree = HTMLParser(html)
    sectors = set(SECTOR_HEADINGS)
    current: Optional[str] = None
    found: Dict[str, str] = {}

    def walk(node) -> None:
        nonlocal current
        if node.tag == "h2":
            title = re.sub(r"\s+", " ", node.text()).strip()
            current = title if title in sectors else None
        elif node.tag == "a" and current:
            href = (node.attributes.get("href") or "").split("#")[0].split("?")[0]
            parts = href.strip("/").split("/")
            if href.startswith("/curriculum/") and len(parts) == 4:
                found.setdefault(parts[2], current)
        for child in node.iter(include_text=False):
            walk(child)

    if tree.body is not None:
        walk(tree.body)
    return found


def fetch_sectors(client: PoliteClient) -> Dict[str, str]:
    return parse_sectors(client.get_text(BASE_URL + INDEX_PATH))


def annotate(database: dict, sectors: Dict[str, str]) -> dict:
    """Record each TP subject's sector, and report any left unmapped."""
    tagged = 0
    unmapped = []
    for level in (database.get("levels") or {}).values():
        for subject in (level.get("subjects") or {}).values():
            if subject.get("track") != "plan_diferenciado_tp":
                continue
            slug = (subject.get("source_url") or "").strip("/").split("/")
            slug = slug[-2] if len(slug) >= 2 else ""
            sector = sectors.get(slug)
            if sector:
                subject["tp_sector"] = sector
                tagged += 1
            else:
                unmapped.append(f"{level.get('level_id')}/{subject.get('subject_id')}")
    return {
        "source": BASE_URL + INDEX_PATH,
        "sectors": len(set(sectors.values())),
        "subjects_tagged": tagged,
        "subjects_unmapped": unmapped,
    }
