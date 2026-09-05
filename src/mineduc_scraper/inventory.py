"""Expected curriculum inventory, and the coverage report derived from it.

Coverage was previously asserted against the total the last run happened to
produce, which can only ever confirm that nothing changed. This module builds
the expected inventory from the ministry's own indexes instead, and then reports
each expected offering as covered, absent at source, or unparsed.

Discovery has two arms, because the ministry publishes through two channels:

* the **site's own indexes** - ``/curriculum/ambitos-y-asignaturas`` plus each
  curriculum base landing page - which enumerate every level x subject page the
  site navigates, whether or not that page renders objectives;
* the **Base Curricular documents**, which define offerings the site does not
  always navigate. The EPJA Bases define (asignatura, nivel) combinations with
  no corresponding page, and they are part of the published curriculum whether
  or not the site has a URL for them.

The distinction the report exists to draw is between:

``ingested``          objectives were found and stored
``source_absent``     the ministry publishes no objectives here, with a reason
``parser_gap``        the source does have objectives and none were extracted
``defined_elsewhere`` the objectives exist, under another level (combined EPJA)

Only the third is a defect of this project. Collapsing the four - or dropping
the warnings so the totals look clean - is exactly the failure this report is
meant to prevent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .bases_pdf import EPJA_BASES_2024
from .extract import BASE_URL, parse_index_page
from .http import PoliteClient
from .taxonomy import BASES, level_for, slugify

log = logging.getLogger(__name__)

INDEX_PATH = "/curriculum/ambitos-y-asignaturas"

STATUS_INGESTED = "ingested"
STATUS_SOURCE_ABSENT = "source_absent"
STATUS_PARSER_GAP = "parser_gap"
STATUS_DEFINED_ELSEWHERE = "defined_elsewhere"
STATUS_NOT_IN_DATASET = "missing_from_dataset"

FORMAT_HTML = "html"
FORMAT_BASE_PDF = "base_curricular_pdf"


@dataclass
class Offering:
    """One expected level x subject curriculum offering."""

    curriculum_base: str
    curriculum_base_name: Optional[str]
    level_id: Optional[str]
    level_name: Optional[str]
    subject_slug: str
    subject_id: str
    expected_source: str
    source_format: str
    source_url: str
    grade_slug: Optional[str] = None

    def key(self) -> tuple:
        return (self.level_id or self.grade_slug or "?", self.subject_id)


@dataclass
class CoverageRow:
    curriculum_base: str
    curriculum_base_name: Optional[str]
    level_id: Optional[str]
    level_name: Optional[str]
    subject_id: str
    subject_name: Optional[str]
    track: Optional[str]
    expected_source: str
    source_format: str
    source_url: str
    objectives_found: bool
    objectives_ingested: int
    source_parsed: bool
    status: str
    unresolved_reason: Optional[str] = None
    documents: int = 0


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _base_landing_paths(html: str) -> List[str]:
    """Curriculum base landing pages linked from the master index."""
    tree = HTMLParser(html)
    found: List[str] = []
    for link in tree.css("a[href]"):
        href = (link.attributes.get("href") or "").split("#")[0].split("?")[0]
        parts = href.strip("/").split("/")
        if href.startswith("/curriculum/") and len(parts) == 2 and parts[1] not in {"curso"}:
            if href not in found:
                found.append(href)
    return found


def discover_site_offerings(client: PoliteClient) -> List[Offering]:
    """Enumerate every level x subject page the site navigates.

    Reads the master index and then each curriculum base landing page, because
    the two do not carry the same set: a base landing page lists offerings (the
    EPJA ones, in particular) that the ámbitos index does not surface.
    """
    index_html = client.get_text(BASE_URL + INDEX_PATH)
    paths = set(parse_index_page(index_html, BASE_URL + INDEX_PATH))

    for landing in _base_landing_paths(index_html):
        try:
            html = client.get_text(BASE_URL + landing)
        except Exception as exc:  # noqa: BLE001 - one index must not kill discovery
            log.warning("could not read base landing page %s: %s", landing, exc)
            continue
        paths.update(parse_index_page(html, BASE_URL + landing))

    offerings: List[Offering] = []
    for path in sorted(paths):
        parts = path.strip("/").split("/")
        if len(parts) != 4:
            continue
        _, base_slug, subject_slug, grade_slug = parts
        level = level_for(grade_slug)
        offerings.append(
            Offering(
                curriculum_base=base_slug,
                curriculum_base_name=BASES.get(base_slug),
                level_id=level.level_id if level else None,
                level_name=level.level_name if level else None,
                subject_slug=subject_slug,
                subject_id=slugify(subject_slug),
                grade_slug=grade_slug,
                expected_source="Página de currículum del sitio",
                source_format=FORMAT_HTML,
                source_url=BASE_URL + path,
            )
        )
    return offerings


def bases_document_offerings(sections: Sequence) -> List[Offering]:
    """Offerings a Base Curricular defines, from parsed sections.

    Takes ``bases_pdf.BasesSection`` objects. These are expected offerings in
    their own right: the ministry defines them in an approved document, so an
    audit that only counted site pages would under-count the curriculum.
    """
    from .taxonomy import SYNTHETIC_LEVELS, LEVELS

    names = {level.level_id: level.level_name for level in LEVELS.values()}
    names.update({lvl.level_id: lvl.level_name for lvl in SYNTHETIC_LEVELS.values()})

    offerings: List[Offering] = []
    for section in sections:
        offerings.append(
            Offering(
                curriculum_base=EPJA_BASES_2024["curriculum_base"],
                curriculum_base_name=BASES.get(EPJA_BASES_2024["curriculum_base"]),
                level_id=section.level_id,
                level_name=names.get(section.level_id),
                subject_slug=section.subject_slug,
                subject_id=slugify(section.subject_slug),
                expected_source=EPJA_BASES_2024["title"],
                source_format=FORMAT_BASE_PDF,
                source_url=f"{EPJA_BASES_2024['pdf_url']}#page={section.pdf_page}",
            )
        )
    return offerings


def merge_offerings(*groups: Sequence[Offering]) -> List[Offering]:
    """Combine discovery arms, preferring the most structured source per key."""
    ranked = {FORMAT_HTML: 0, FORMAT_BASE_PDF: 1}
    best: Dict[tuple, Offering] = {}
    for group in groups:
        for offering in group:
            current = best.get(offering.key())
            if current is None or ranked[offering.source_format] < ranked[current.source_format]:
                best[offering.key()] = offering
    return sorted(best.values(), key=lambda o: (o.level_id or "~", o.subject_id))


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def build_report(database: dict, offerings: Sequence[Offering]) -> dict:
    """Compare the expected inventory with the dataset."""
    rows: List[CoverageRow] = []
    seen: set = set()

    for offering in offerings:
        subject = (
            database.get("levels", {})
            .get(offering.level_id or "", {})
            .get("subjects", {})
            .get(offering.subject_id)
        )
        seen.add((offering.level_id, offering.subject_id))

        if subject is None:
            rows.append(
                CoverageRow(
                    curriculum_base=offering.curriculum_base,
                    curriculum_base_name=offering.curriculum_base_name,
                    level_id=offering.level_id,
                    level_name=offering.level_name,
                    subject_id=offering.subject_id,
                    subject_name=None,
                    track=None,
                    expected_source=offering.expected_source,
                    source_format=offering.source_format,
                    source_url=offering.source_url,
                    objectives_found=False,
                    objectives_ingested=0,
                    source_parsed=False,
                    status=STATUS_NOT_IN_DATASET,
                    unresolved_reason=(
                        "La oferta aparece en el índice oficial pero no está en el "
                        "dataset: la página no fue recorrida en esta construcción."
                    ),
                )
            )
            continue

        count = len(subject.get("learning_objectives") or [])
        reason = subject.get("no_objectives_reason") or {}
        if count:
            status, unresolved = STATUS_INGESTED, None
        elif subject.get("objectives_in_level"):
            status = STATUS_DEFINED_ELSEWHERE
            unresolved = None
        elif reason:
            status = STATUS_SOURCE_ABSENT
            unresolved = None
        else:
            status = STATUS_PARSER_GAP
            unresolved = (
                "La oferta existe y no registra objetivos ni una razón verificada "
                "de ausencia en la fuente: hay que revisar si la fuente publica "
                "objetivos que el parser no está leyendo."
            )

        rows.append(
            CoverageRow(
                curriculum_base=subject.get("curriculum_base") or offering.curriculum_base,
                curriculum_base_name=subject.get("curriculum_base_name")
                or offering.curriculum_base_name,
                level_id=offering.level_id,
                level_name=offering.level_name,
                subject_id=offering.subject_id,
                subject_name=subject.get("subject_name"),
                track=subject.get("track"),
                expected_source=offering.expected_source,
                source_format=offering.source_format,
                source_url=offering.source_url,
                objectives_found=bool(count),
                objectives_ingested=count,
                source_parsed=status != STATUS_PARSER_GAP,
                status=status,
                unresolved_reason=unresolved,
                documents=len(subject.get("documents") or []),
            )
        )

    # Anything in the dataset that the inventory did not expect. Not an error -
    # a route can be reachable without being indexed - but it has to be visible,
    # because it is the signal that discovery has drifted from the site.
    unexpected: List[dict] = []
    for level_id, level in database.get("levels", {}).items():
        for subject_id, subject in level.get("subjects", {}).items():
            if (level_id, subject_id) in seen:
                continue
            unexpected.append(
                {
                    "level_id": level_id,
                    "subject_id": subject_id,
                    "objectives": len(subject.get("learning_objectives") or []),
                    "source_url": subject.get("source_url"),
                }
            )

    by_status: Dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1

    return {
        "generated_from": "official source inventory (site indexes + Bases Curriculares)",
        "expected_offerings": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "objectives_ingested": sum(row.objectives_ingested for row in rows),
        "parser_gaps": [
            {"level_id": r.level_id, "subject_id": r.subject_id, "source_url": r.source_url}
            for r in rows if r.status == STATUS_PARSER_GAP
        ],
        "source_absent": [
            {"level_id": r.level_id, "subject_id": r.subject_id, "source_url": r.source_url}
            for r in rows if r.status == STATUS_SOURCE_ABSENT
        ],
        "offerings_not_in_dataset": [
            {"level_id": r.level_id, "subject_id": r.subject_id, "source_url": r.source_url}
            for r in rows if r.status == STATUS_NOT_IN_DATASET
        ],
        "unexpected_in_dataset": unexpected,
        "rows": [asdict(row) for row in rows],
    }


def summarise(report: dict) -> dict:
    """The subset of the coverage report a client needs, without the row detail."""
    return {
        "expected_offerings": report["expected_offerings"],
        "by_status": report["by_status"],
        "parser_gaps": len(report["parser_gaps"]),
        "source_absent": len(report["source_absent"]),
        "offerings_not_in_dataset": len(report["offerings_not_in_dataset"]),
        "unexpected_in_dataset": len(report["unexpected_in_dataset"]),
    }
