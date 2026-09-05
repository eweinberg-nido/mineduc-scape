"""Objetivos de Aprendizaje Transversales (OAT), read from the site's JSON:API.

curriculumnacional.cl runs Drupal 10 with JSON:API enabled, and OATs are stored
as a two-level paragraph structure hanging off each curriculum base:

    curriculum_base --field_dimensiones--> paragraph/dimension
                                             --field_oat--> paragraph/oat

Only ``paragraph/dimension`` and ``paragraph/oat`` are readable anonymously, but
each carries ``parent_id``, which is enough to rebuild the tree. Learning
objectives themselves are *not* exposed over JSON:API (field-level access
control hides everything but ``code``), which is why the OAs are parsed from
HTML instead.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from .http import PoliteClient
from .taxonomy import slugify

log = logging.getLogger(__name__)

JSONAPI = "https://www.curriculumnacional.cl/jsonapi"

# MINEDUC's internal curriculum_base ids, recovered from the "Evaluaciones
# relacionadas" links on every subject page (``?f[0]=bases:<id>``). The crawl
# re-reads these ids per page, and `validate` flags any drift.
BASE_ID_TO_SLUG: Dict[str, str] = {
    "1": "1o-6o-basico",
    "2": "3o-4o-medio",
    "3": "3o-4o-medio-tecnico-profesional",
    "4": "7o-basico-2o-medio",
    "5": "educacion-parvularia",
    "8": "bases-curriculares-educacion-personas-jovenes-adultas-epja",
}

BASE_TOKEN: Dict[str, str] = {
    "1o-6o-basico": "1A6B",
    "3o-4o-medio": "3Y4M",
    "3o-4o-medio-tecnico-profesional": "3Y4MTP",
    "7o-basico-2o-medio": "7BA2M",
    "educacion-parvularia": "PARV",
    "bases-curriculares-educacion-personas-jovenes-adultas-epja": "EPJA",
}


def _https(url: Optional[str]) -> Optional[str]:
    """Force a JSON:API link back onto https.

    Drupal builds ``links.next.href`` from its configured base URL, and this
    site emits it as ``http://``. The host does not serve plain HTTP at all, so
    following the link verbatim fails with a connection error on the *second*
    page of every collection - which looks like a flaky network rather than a
    truncated fetch, and silently caps a collection at its first 50 records.
    """
    if url and url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _collection(client: PoliteClient, path: str, limit: int = 50) -> List[dict]:
    """Fetch every page of a JSON:API collection."""
    url: Optional[str] = f"{JSONAPI}/{path}?page%5Blimit%5D={limit}"
    items: List[dict] = []
    seen: set = set()
    while url:
        if url in seen:  # a self-referential next link would loop forever
            log.warning("JSON:API pagination revisited %s; stopping", url)
            break
        seen.add(url)
        payload = client.get_json(url)
        items.extend(payload.get("data") or [])
        next_link = (payload.get("links") or {}).get("next")
        url = _https(next_link.get("href")) if isinstance(next_link, dict) else None
    return items


def _oat_number(raw: Optional[str], fallback: int) -> int:
    match = re.search(r"(\d+)", raw or "")
    return int(match.group(1)) if match else fallback


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


# OATs actually rendered per curriculum base, counted on the base landing pages
# (/curriculum/<base>). Used to confirm the JSON:API de-duplication below.
EXPECTED_OAT_COUNTS: Dict[str, int] = {
    "1o-6o-basico": 32,
    "7o-basico-2o-medio": 30,
    "3o-4o-medio-tecnico-profesional": 12,
}


def _dedupe_dimensions(dimensions: List[dict]) -> Dict[str, dict]:
    """Index dimension paragraphs by internal id, dropping superseded drafts.

    The site keeps at least one abandoned draft dimension (an older
    "Dimensión física" under 7° Básico a 2° Medio holding a single OAT that the
    published page does not show). Duplicates are identified by
    (curriculum base, normalised title); the richest, then newest, one wins.
    """
    candidates: Dict[tuple, dict] = {}
    dropped: List[str] = []
    for node in dimensions:
        attrs = node["attributes"]
        internal_id = str(attrs.get("drupal_internal__id"))
        base_slug = BASE_ID_TO_SLUG.get(str(attrs.get("parent_id")))
        if base_slug is None:
            log.warning("OAT dimension %s has unmapped curriculum base %s",
                        internal_id, attrs.get("parent_id"))
            continue
        title = _clean(attrs.get("field_titulo")) or "Sin dimensión"
        entry = {
            "internal_id": internal_id,
            "base_slug": base_slug,
            "dimension": title,
            "dimension_description": _clean(attrs.get("field_bajada")) or None,
            "child_count": int(attrs.get("_child_count", 0)),
            "created": attrs.get("created") or "",
        }
        key = (base_slug, slugify(title))
        previous = candidates.get(key)
        if previous is None:
            candidates[key] = entry
            continue
        winner, loser = (
            (entry, previous)
            if (entry["child_count"], entry["created"])
            > (previous["child_count"], previous["created"])
            else (previous, entry)
        )
        candidates[key] = winner
        dropped.append(f"{loser['base_slug']}/{loser['dimension']} (paragraph {loser['internal_id']})")
    if dropped:
        log.info("dropped %d superseded OAT dimension(s): %s", len(dropped), "; ".join(dropped))
    return {entry["internal_id"]: entry for entry in candidates.values()}


def fetch_transversal_objectives(client: PoliteClient) -> Dict[str, List[dict]]:
    """Return OATs grouped by curriculum base slug, ordered by dimension."""
    dimensions = _collection(client, "paragraph/dimension")
    oats = _collection(client, "paragraph/oat")

    # Count children first so de-duplication can prefer the populated draft.
    child_counts: Dict[str, int] = {}
    for node in oats:
        parent = str(node["attributes"].get("parent_id"))
        child_counts[parent] = child_counts.get(parent, 0) + 1
    for node in dimensions:
        internal_id = str(node["attributes"].get("drupal_internal__id"))
        node["attributes"]["_child_count"] = child_counts.get(internal_id, 0)

    dim_index = _dedupe_dimensions(dimensions)

    grouped: Dict[str, List[dict]] = {}
    for node in oats:
        attrs = node["attributes"]
        parent = dim_index.get(str(attrs.get("parent_id")))
        if parent is None:
            log.debug("skipping OAT %s: parent dimension %s was superseded or unreadable",
                      attrs.get("drupal_internal__id"), attrs.get("parent_id"))
            continue
        base_slug = parent["base_slug"]
        bucket = grouped.setdefault(base_slug, [])
        number = _oat_number(attrs.get("field_oat_numero"), len(bucket) + 1)
        dim_slug = slugify(parent["dimension"]).replace("dimension_", "")
        bucket.append(
            {
                "oat_id": f"CL_OAT_{BASE_TOKEN.get(base_slug, 'GEN')}_"
                          f"{dim_slug.upper()}_{number:02d}",
                "oat_number": number,
                "code": _clean(attrs.get("field_oat_numero")) or f"OAT {number}",
                "dimension": parent["dimension"],
                "dimension_description": parent["dimension_description"],
                "title": _clean(attrs.get("field_titulo")) or None,
                "statement": _clean(attrs.get("field_descripcion")),
                "curriculum_base": base_slug,
            }
        )

    for base_slug, bucket in grouped.items():
        bucket.sort(key=lambda o: o["oat_number"])
        expected = EXPECTED_OAT_COUNTS.get(base_slug)
        if expected is not None and len(bucket) != expected:
            log.warning(
                "%s: collected %d OATs, expected %d (base landing page count)",
                base_slug, len(bucket), expected,
            )
    return grouped


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
# Which curriculum bases define OATs at all. Three do; three do not, and their
# absence is a property of the curriculum rather than a gap:
#
# * Educación Parvularia organises its transversal aims through the ámbitos and
#   núcleos themselves, and defines no separate OAT set.
# * The 3° y 4° Medio base defines no OAT paragraphs of its own; the OATs that
#   apply there come from 7° Básico a 2° Medio, and the Formación Diferenciada
#   Técnico-Profesional base carries its own twelve.
# * The EPJA 2024 Bases replace the OAT structure with the Habilidades y
#   Actitudes para el siglo XXI framework, which is not an OAT set.
#
# Recorded so "no OATs here" is an answer with a reason attached, instead of a
# hole in a table.
BASES_WITHOUT_OATS: Dict[str, str] = {
    "educacion-parvularia":
        "Las Bases Curriculares de Educación Parvularia no definen un conjunto "
        "separado de Objetivos de Aprendizaje Transversales: los propósitos "
        "transversales se integran en los ámbitos y núcleos de aprendizaje.",
    "3o-4o-medio":
        "La base de 3° y 4° Medio no define párrafos OAT propios en el sitio; los "
        "OAT aplicables provienen de la base de 7° Básico a 2° Medio, y la "
        "Formación Diferenciada Técnico-Profesional publica los suyos.",
    "bases-curriculares-educacion-personas-jovenes-adultas-epja":
        "Las Bases Curriculares EPJA 2024 no usan la estructura de OAT: articulan "
        "lo transversal mediante el marco de Habilidades y Actitudes para el "
        "siglo XXI.",
}


def verify(stored: Dict[str, List[dict]], live: Dict[str, List[dict]]) -> dict:
    """Compare the stored OATs field by field against a freshly fetched set.

    Codes, dimensions and complete statements are all compared; a difference in
    any of them is reported rather than resolved, because two readings of the
    same official source disagreeing is a finding.
    """
    differences: List[str] = []
    missing: List[str] = []
    extra: List[str] = []

    for base_slug, bucket in live.items():
        by_id = {oat["oat_id"]: oat for oat in stored.get(base_slug, [])}
        for oat in bucket:
            current = by_id.get(oat["oat_id"])
            if current is None:
                missing.append(f"{base_slug}/{oat['oat_id']} ({oat.get('code')})")
                continue
            for field in ("code", "dimension", "statement"):
                if (current.get(field) or "") != (oat.get(field) or ""):
                    differences.append(f"{base_slug}/{oat['oat_id']}: {field} differs")
        for oat_id in sorted(set(by_id) - {oat["oat_id"] for oat in bucket}):
            extra.append(f"{base_slug}/{oat_id}")

    for base_slug in set(stored) - set(live):
        extra.extend(f"{base_slug}/{oat['oat_id']}" for oat in stored[base_slug])

    return {
        "verified_at_source": True,
        "bases_with_oats": {slug: len(bucket) for slug, bucket in sorted(live.items())},
        "expected_counts": dict(EXPECTED_OAT_COUNTS),
        "bases_without_oats": dict(BASES_WITHOUT_OATS),
        "total": sum(len(bucket) for bucket in live.values()),
        "records_compared": sum(len(bucket) for bucket in live.values()),
        "differences": differences,
        "missing_from_dataset": missing,
        "not_in_source": extra,
        "count_mismatches": [
            f"{slug}: {len(live.get(slug, []))} collected, {expected} expected "
            f"from the base landing page"
            for slug, expected in EXPECTED_OAT_COUNTS.items()
            if len(live.get(slug, [])) != expected
        ],
    }
