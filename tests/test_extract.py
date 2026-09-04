"""Extraction tests against saved copies of real curriculumnacional.cl pages."""

from mineduc_scraper.extract import parse_index_page, parse_subject_page

MAT_URL = "https://www.curriculumnacional.cl/curriculum/7o-basico-2o-medio/matematica/1-medio"
TP_URL = (
    "https://www.curriculumnacional.cl/curriculum/3o-4o-medio-tecnico-profesional/"
    "especialidad-administracion/3-medio-tp"
)
PARV_URL = (
    "https://www.curriculumnacional.cl/curriculum/educacion-parvularia/"
    "comunicacion-integral/nm-nivel-medio"
)
EPJA_URL = (
    "https://www.curriculumnacional.cl/curriculum/"
    "bases-curriculares-educacion-personas-jovenes-adultas-epja/artes-visuales/"
    "nivel-1-educacion-media-1-2-ano-medio"
)


def test_parses_url_segments(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    assert page.base_slug == "7o-basico-2o-medio"
    assert page.subject_slug == "matematica"
    assert page.grade_slug == "1-medio"
    assert page.subject_name == "Matemática"


def test_all_three_categories_are_recognised(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    counts = {}
    for objective in page.objectives:
        counts[objective.category] = counts.get(objective.category, 0) + 1
    assert counts == {"conocimiento": 15, "habilidad": 15, "actitud": 6}


def test_every_objective_has_code_and_statement(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    assert page.objectives
    for objective in page.objectives:
        assert objective.code.strip()
        assert objective.statement.strip()


def test_strand_and_priority_flags(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    first = page.objectives[0]
    assert first.code == "MA1M OA 01"
    assert first.strand_name == "Números"
    assert first.strand_kind == "Eje"
    assert first.strand_term_id == "176"
    assert first.prioritized is True
    assert any(o.prioritized is False for o in page.objectives)


def test_bullet_lists_are_preserved(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    oa02 = next(o for o in page.objectives if o.code == "MA1M OA 02")
    lines = oa02.statement.split("\n")
    assert lines[0].startswith("Mostrar que comprenden las potencias")
    assert len(lines) > 1
    assert all(line.startswith("- ") for line in lines[1:])


def test_habilidad_titles_are_classified(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    oah = next(o for o in page.objectives if o.code == "MA1M OAH a")
    assert oah.category == "habilidad"
    assert oah.strand_name == "Resolver problemas"


def test_documents_and_source_ids(matematica_1_medio):
    page = parse_subject_page(matematica_1_medio, MAT_URL)
    types = {d.doc_type for d in page.documents}
    assert "Programa de estudio" in types
    assert all(d.url.startswith("https://") for d in page.documents)
    assert page.source_subject_id == "109"
    assert page.source_grade_id == "15"
    assert page.source_base_id == "4"


def test_tp_page_without_strands(especialidad_tp):
    page = parse_subject_page(especialidad_tp, TP_URL)
    assert page.subject_name == "Especialidad Administración"
    assert len(page.objectives) == 6
    assert all(o.strand_name is None for o in page.objectives)
    assert page.objectives[0].code == "OA 1."


def test_parvularia_uses_nucleo_strands(parvularia):
    page = parse_subject_page(parvularia, PARV_URL)
    assert {o.strand_kind for o in page.objectives} == {"Núcleo"}
    assert "Lenguaje verbal" in {o.strand_name for o in page.objectives}
    assert page.objectives[0].code == "OA 01 LV NM"


def test_pdf_only_page_yields_no_objectives(epja):
    page = parse_subject_page(epja, EPJA_URL)
    assert page.objectives == []
    assert page.documents  # the Programa de Estudio link is still captured


def test_index_page_finds_subject_grade_paths():
    html = """
    <a href="/curriculum/7o-basico-2o-medio/matematica/1-medio">x</a>
    <a href="/curriculum/7o-basico-2o-medio/matematica">subject only</a>
    <a href="/curriculum/7o-basico-2o-medio/curso/1-medio">course page</a>
    <a href="/curriculum/7o-basico-2o-medio/matematica/1-medio#eje-1">dup w/ anchor</a>
    <a href="/recursos/algo">unrelated</a>
    """
    assert parse_index_page(html) == [
        "/curriculum/7o-basico-2o-medio/matematica/1-medio"
    ]
