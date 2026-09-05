"""The Base Curricular PDF adapter.

Every fixture here is the verbatim extracted text of one page of the real
*Bases Curriculares EPJA 2024*, so the tests exercise the actual typography -
the tab-plus-glyph list markers, the hard line wraps, the eje printed on its own
line under a sub-list - rather than an idealised reconstruction of it.

Two of the fixtures are pages that must **not** parse. They are the ones that
cost real work to find: a worked example that reproduces a nivel's objectives
inside an illustration, and the progression grid that repeats every objective of
an asignatura across all five niveles.
"""

from __future__ import annotations

import pytest

from mineduc_scraper.bases_pdf import (
    EPJA_SUBJECTS,
    BasesSection,
    parse_document,
    parse_page,
)
from conftest import load_bases_page


def page(name: str) -> str:
    return load_bases_page(name)


# --------------------------------------------------------------------------- #
# Definition pages
# --------------------------------------------------------------------------- #
def test_reads_a_formacion_general_section():
    section = parse_page(page("epja_lenguaje_n1_basica"), 57)
    assert section is not None
    assert section.subject_slug == "lenguaje-comunicacion"
    assert section.level_id == "epja_n1_basica"
    assert section.formation_area == "formacion_general"
    assert section.pdf_page == 57
    assert [o.number for o in section.objectives] == [1, 2, 3, 4, 5]
    assert not section.problems


def test_statements_match_the_html_route_character_for_character():
    """The one EPJA section the site also publishes as HTML.

    Having a second official route for the same content is the strongest check
    available on this parser, so it is asserted rather than merely noted: if the
    PDF reader ever starts dropping a clause or mangling an accent, this fails
    before the data reaches the dataset.
    """
    section = parse_page(page("epja_lenguaje_n1_basica"), 57)
    published = {
        1: ("Leer en voz alta textos variados de manera fluida y adecuada entonación.",
            "Lectura"),
        2: ("Leer textos de diversos géneros (orales, escritos y audiovisuales) para "
            "desarrollar la comprensión global.", "Lectura"),
        3: ("Escribir con letra legible para una variedad de propósitos personales y "
            "sociales.", "Escritura"),
        4: ("Expresarse de manera coherente y articulada utilizando un vocabulario "
            "variado y gestos, posturas, volumen y dicción adecuados al propósito y la "
            "situación comunicativa.", "Comunicación oral"),
        5: ("Buscar y seleccionar información con honestidad, a partir de un propósito.",
            "Investigación"),
    }
    for objective in section.objectives:
        statement, eje = published[objective.number]
        assert objective.statement == statement
        assert objective.strand_eje == eje


def test_keeps_a_statements_subordinate_list():
    """A statement ending in a colon must arrive with the list it introduces.

    Ciencias Naturales OA 3 is a stem, four sub-items, and then its eje on a
    line of its own. Cutting the objective column at the first list marker - the
    obvious reading, since the same marker introduces the conocimientos
    esenciales column further down - truncates this objective at the colon and
    swallows OA 4 through OA 7 with it.
    """
    section = parse_page(page("epja_ciencias_n2_basica"), 92)
    assert [o.number for o in section.objectives] == [1, 2, 3, 4, 5, 6, 7]

    oa3 = next(o for o in section.objectives if o.number == 3)
    lines = oa3.statement.split("\n")
    assert lines[0].endswith("considerando:")
    assert len(lines) == 5
    assert all(line.startswith("- ") for line in lines[1:])
    assert lines[1] == "- La pregunta de investigación y predicción de los resultados."
    # The wrapped last sub-item is rejoined, not left broken across two lines.
    assert lines[4].endswith("uso de la tecnología digital cuando corresponda.")
    # The eje printed under the list belongs to the objective, not to the list.
    assert oa3.strand_eje == "Planificar y conducir una investigación"


def test_reads_a_combined_educacion_media_level():
    """Formación Instrumental is defined for "Nivel 1 y 2" as one block."""
    section = parse_page(page("epja_responsabilidad_media"), 122)
    assert section is not None
    assert section.subject_slug == "responsabilidad-personal-social"
    assert section.level_id == "epja_media"
    assert section.formation_area == "formacion_instrumental"
    assert len(section.objectives) == 5


def test_page_without_the_se_espera_lead_in_still_parses():
    """Responsabilidad Personal y Social omits the lead-in every other page has.

    Requiring it looked harmless and silently dropped this asignatura's only
    definition page, which is why the page test keys on the two column captions
    instead.
    """
    text = page("epja_responsabilidad_media")
    assert "Se espera que los y las estudiantes sean capaces de:" not in text
    assert parse_page(text, 122) is not None


def test_reads_formacion_diferenciada_humanistico_cientifica():
    section = parse_page(page("epja_filosofia_media"), 137)
    assert section.subject_slug == "filosofia"
    assert section.formation_area == "formacion_diferenciada_hc"
    assert section.level_id == "epja_media"
    assert [o.strand_eje for o in section.objectives] == [
        "Pensamiento analítico", "Pensamiento analítico",
        "Pensamiento crítico", "Pensamiento crítico",
    ]


def test_captures_conocimientos_esenciales_and_big_ideas():
    section = parse_page(page("epja_lenguaje_n1_basica"), 57)
    assert len(section.big_ideas) == 4
    assert section.big_ideas[0].startswith("Leer diferentes tipos de textos")
    assert len(section.essential_knowledge) == 7
    assert section.essential_knowledge[0].startswith("Código escrito:")
    # Wrapped knowledge items are rejoined into one entry, not split per line.
    assert all("\n" not in item for item in section.essential_knowledge)


# --------------------------------------------------------------------------- #
# Pages that must not parse
# --------------------------------------------------------------------------- #
def test_refuses_the_worked_example_facsimile():
    """A page that reproduces real objectives inside an illustration.

    "¿Cómo se implementan las Bases Curriculares en el aula?" prints Matemática
    Nivel 1 Básica's six objectives verbatim as an example. It parses cleanly and
    would contribute six duplicate records citing the wrong page, so it has to be
    refused - which it is, because it carries no "Asignaturas de Formación ..."
    running header, having been printed before those parts begin.
    """
    text = page("epja_example_facsimile")
    assert "OA 1." in text and "Objetivos de Aprendizaje" in text
    assert "Asignaturas de Formación" not in text
    assert parse_page(text, 40) is None


def test_refuses_the_progression_grid():
    """The Visión panorámica table repeats every objective across five niveles."""
    text = page("epja_vision_panoramica")
    assert "Visión panorámica" in text
    assert parse_page(text, 62) is None


# --------------------------------------------------------------------------- #
# Whole-document behaviour
# --------------------------------------------------------------------------- #
def test_parse_document_only_keeps_definition_pages():
    pages = [
        page("epja_example_facsimile"),
        page("epja_lenguaje_n1_basica"),
        page("epja_vision_panoramica"),
        page("epja_ciencias_n2_basica"),
    ]
    report = parse_document(pages)
    assert [s.subject_slug for s in report.sections] == [
        "lenguaje-comunicacion", "ciencias-naturales",
    ]
    assert report.pages_skipped_not_definition == 2
    assert not report.problems
    # Page numbers are the document's own, 1-based, as a reader would cite them.
    assert [s.pdf_page for s in report.sections] == [2, 4]


def test_every_objective_carries_its_eje():
    """A missing eje is the signal that the column flow was misread.

    It is reported rather than guessed at, so a layout change surfaces as a
    named problem instead of as objectives silently filed under no eje.
    """
    report = parse_document([page(n) for n in (
        "epja_lenguaje_n1_basica", "epja_ciencias_n2_basica",
        "epja_responsabilidad_media", "epja_filosofia_media",
    )])
    assert report.problems == []
    assert all(o.strand_eje for o in report.objectives)


def test_subject_map_covers_every_asignatura_the_bases_title():
    """The double-named asignaturas are mapped explicitly, not slugified.

    "Lenguaje y Comunicación / Lengua y Literatura" is one asignatura renamed
    between ciclos; deriving a slug from whichever half the page prints would
    split it into two.
    """
    slugs = {slug for slug, _ in EPJA_SUBJECTS.values()}
    assert len(slugs) == len(EPJA_SUBJECTS)
    assert EPJA_SUBJECTS["lenguaje y comunicación / lengua y literatura"] == (
        "lenguaje-comunicacion", "Lenguaje y Comunicación",
    )


@pytest.mark.parametrize("name,expected", [
    ("epja_lenguaje_n1_basica", 5),
    ("epja_ciencias_n2_basica", 7),
    ("epja_responsabilidad_media", 5),
    ("epja_filosofia_media", 4),
])
def test_objective_counts(name, expected):
    section = parse_page(page(name), 1)
    assert isinstance(section, BasesSection)
    assert len(section.objectives) == expected
