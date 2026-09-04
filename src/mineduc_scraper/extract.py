"""HTML extraction: turn one subject/grade page into raw records.

The site (Drupal 10) renders every curriculum page with the same markup, so a
small set of selectors covers 1° Básico through 4° Medio, plus Parvularia, EPJA
and the Técnico-Profesional specialities:

    div.documents-wrapper article            -> curricular documents
    div.items-wrapper                        -> one strand group
      h3[id]                                 -> strand name + taxonomy term id
      div.item-wrapper[.prioritized]         -> one objective
        h4 span.oa-title                     -> full title ("... de Habilidad MA1M OAH a")
        h4 span.number-title                 -> official MINEDUC code ("MA1M OAH a")
        div.field--name-description          -> statement body
        a.link-more                          -> per-objective detail page
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from selectolax.parser import HTMLParser, Node

from .taxonomy import (
    CATEGORY_ACTITUD,
    CATEGORY_CONOCIMIENTO,
    CATEGORY_HABILIDAD,
    STRAND_KINDS,
)

BASE_URL = "https://www.curriculumnacional.cl"

# The site prefixes every objective title with its kind.
_TITLE_HABILIDAD = "objetivo de aprendizaje de habilidad"
_TITLE_ACTITUD = "objetivo de aprendizaje de actitud"


@dataclass
class RawObjective:
    title: str
    code: str
    statement: str
    category: str
    strand_name: Optional[str] = None
    strand_kind: Optional[str] = None
    strand_term_id: Optional[str] = None
    prioritized: bool = False
    detail_url: Optional[str] = None


@dataclass
class RawDocument:
    doc_type: Optional[str]
    title: str
    url: str


@dataclass
class RawPage:
    url: str
    base_slug: str
    subject_slug: str
    grade_slug: str
    page_title: str
    base_name: Optional[str] = None
    subject_name: Optional[str] = None
    source_subject_id: Optional[str] = None
    source_grade_id: Optional[str] = None
    source_base_id: Optional[str] = None
    objectives: List[RawObjective] = field(default_factory=list)
    documents: List[RawDocument] = field(default_factory=list)


def _text(node: Optional[Node]) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.text(deep=True)).strip()


def statement_text(node: Optional[Node]) -> str:
    """Flatten a description field, preserving its list structure.

    Many objectives are written as a stem followed by bullet points; collapsing
    them into one blob loses meaning, so list items are kept on their own lines
    with a leading "- ".
    """
    if node is None:
        return ""
    chunks: List[str] = []

    def walk(current: Node) -> None:
        tag = current.tag
        if tag == "li":
            text = re.sub(r"\s+", " ", current.text(deep=True)).strip()
            if text:
                chunks.append(f"- {text}")
            return
        if tag in ("p", "td", "th"):
            text = re.sub(r"\s+", " ", current.text(deep=True)).strip()
            if text:
                chunks.append(text)
            return
        for child in current.iter(include_text=False):
            walk(child)

    for child in node.iter(include_text=False):
        walk(child)

    if not chunks:
        flat = re.sub(r"\s+", " ", node.text(deep=True)).strip()
        return flat
    # De-duplicate consecutive repeats caused by nested tex2jax wrappers.
    out: List[str] = []
    for chunk in chunks:
        if not out or out[-1] != chunk:
            out.append(chunk)
    return "\n".join(out)


def classify(title: str) -> str:
    lowered = title.lower()
    if lowered.startswith(_TITLE_HABILIDAD):
        return CATEGORY_HABILIDAD
    if lowered.startswith(_TITLE_ACTITUD):
        return CATEGORY_ACTITUD
    return CATEGORY_CONOCIMIENTO


def _parse_strand(heading: Optional[Node]) -> Dict[str, Optional[str]]:
    """Read a strand heading: ``<h3 id="eje-109--176">Números</h3>``."""
    if heading is None:
        return {"strand_name": None, "strand_kind": None, "strand_term_id": None}
    anchor_id = heading.attributes.get("id") or ""
    kind_slug, _, tail = anchor_id.partition("-")
    term_id = tail.split("--")[-1] if "--" in tail else None
    return {
        "strand_name": _text(heading) or None,
        "strand_kind": STRAND_KINDS.get(kind_slug, kind_slug.capitalize() or None),
        "strand_term_id": term_id or None,
    }


def _extract_documents(tree: HTMLParser, page_url: str) -> List[RawDocument]:
    documents: List[RawDocument] = []
    for wrapper in tree.css("div.documents-wrapper article"):
        link = wrapper.css_first("h3 a")
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        badge = wrapper.css_first("span.badge")
        documents.append(
            RawDocument(
                doc_type=_text(badge) or None,
                title=_text(link),
                url=urljoin(page_url, href),
            )
        )
    return documents


def _extract_source_ids(tree: HTMLParser) -> Dict[str, Optional[str]]:
    """Recover MINEDUC's internal subject/grade ids from the sidebar links.

    The "Arma tu evaluación" link carries ``field_cn_subjects`` and
    ``field_cn_grades``, which are the same ids used by the site's JSON:API.
    """
    ids = {
        "source_subject_id": None,
        "source_grade_id": None,
        "source_base_id": None,
    }
    for link in tree.css("a.link-button-more"):
        href = link.attributes.get("href") or ""
        query = parse_qs(urlparse(href).query)
        if "field_cn_subjects" in query and ids["source_subject_id"] is None:
            ids["source_subject_id"] = query["field_cn_subjects"][0]
            ids["source_grade_id"] = (query.get("field_cn_grades") or [None])[0]
        # "Evaluaciones relacionadas" / "Recursos" point at the faceted search,
        # whose f[n]=bases:<id> facet reveals the internal curriculum base id.
        if ids["source_base_id"] is None:
            match = re.search(r"bases(?::|%3A)(\d+)", href)
            if match:
                ids["source_base_id"] = match.group(1)
    return ids


def _extract_breadcrumb(tree: HTMLParser) -> List[str]:
    return [_text(item) for item in tree.css("ol.breadcrumb li")]


def parse_subject_page(html: str, url: str) -> RawPage:
    """Parse one ``/curriculum/<base>/<subject>/<grade>`` page."""
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < 4:
        raise ValueError(f"not a subject/grade curriculum URL: {url}")
    _, base_slug, subject_slug, grade_slug = parts[:4]

    tree = HTMLParser(html)
    page = RawPage(
        url=url,
        base_slug=base_slug,
        subject_slug=subject_slug,
        grade_slug=grade_slug,
        page_title=_text(tree.css_first("h1")),
    )

    crumbs = _extract_breadcrumb(tree)
    # Inicio / Currículum / <base> / <subject> / <this page>
    if len(crumbs) >= 4:
        page.base_name = crumbs[2] or None
        page.subject_name = crumbs[3] or None
    page.documents = _extract_documents(tree, url)
    for key, value in _extract_source_ids(tree).items():
        setattr(page, key, value)

    for group in tree.css("div.items-wrapper"):
        strand = _parse_strand(group.css_first("h3"))
        for item in group.css("div.item-wrapper"):
            title = _text(item.css_first("span.oa-title"))
            code = _text(item.css_first("span.number-title"))
            statement = statement_text(item.css_first("div.field--name-description"))
            if not title and not code:
                continue
            classes = (item.attributes.get("class") or "").split()
            more = item.css_first("a.link-more")
            page.objectives.append(
                RawObjective(
                    title=title,
                    code=code or _fallback_code(title),
                    statement=statement,
                    category=classify(title),
                    prioritized="prioritized" in classes,
                    detail_url=(
                        urljoin(url, more.attributes.get("href") or "") if more else None
                    ),
                    **strand,
                )
            )
    return page


def _fallback_code(title: str) -> str:
    """Recover a code from the title when ``span.number-title`` is missing."""
    for prefix in (
        "Objetivo de Aprendizaje de Habilidad ",
        "Objetivo de Aprendizaje de Actitud ",
        "Objetivo de aprendizaje ",
        "Objetivo de Aprendizaje ",
    ):
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title.strip()


def parse_index_page(html: str, url: str = BASE_URL) -> List[str]:
    """Collect every ``/curriculum/<base>/<subject>/<grade>`` path from an index."""
    tree = HTMLParser(html)
    found = []
    seen = set()
    for link in tree.css("a[href]"):
        href = (link.attributes.get("href") or "").split("#")[0].split("?")[0]
        if not href.startswith("/curriculum/"):
            continue
        parts = href.strip("/").split("/")
        if len(parts) != 4 or parts[2] == "curso":
            continue
        if href not in seen:
            seen.add(href)
            found.append(href)
    return found
