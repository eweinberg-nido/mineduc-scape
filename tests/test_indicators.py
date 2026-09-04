"""Indicator extraction tests.

The Programas are 2-10 MB each, so instead of shipping PDFs the fixtures in
`tests/fixtures/pdf_pages/` hold the text blocks captured from one real page of
each layout, with their true coordinates. `parse_page` consumes exactly that,
so these tests exercise the real geometry - column detection, row banding,
bullet splitting, per-objective vs joint tables - without a PDF at all.

Covered layouts:
  * 1° a 6° Básico       - standalone "OA n" cells, whole indicator cell in one block
  * 7° Básico a 2° Medio - standalone "OA n" cells, one block per bullet
  * habilidades tables   - codes inline and bare: "a. Observar ..."
  * 2021 3° y 4° Medio   - joint "Actividad de Evaluación" table, "OA 2:" codes
  * "extracto" Programas - objectives cell merged into one block
  * activity pages       - numbered steps that must NOT be read as objectives
"""

import json
from pathlib import Path

from mineduc_scraper.indicators import (
    JoinReport,
    PdfIndicators,
    TableRow,
    _split_bullets,
    attach_to_subject,
    objective_key,
    parse_page,
    pdf_code_candidates,
    resolve_pdf_url,
    statement_similarity,
)

PAGES = Path(__file__).parent / "fixtures" / "pdf_pages"


def load_page(name: str):
    payload = json.loads((PAGES / f"{name}.json").read_text(encoding="utf-8"))
    blocks = [tuple(block) + (index, 0) for index, block in enumerate(payload["blocks"])]
    return blocks, payload["text"], payload["page"]


def rows_for(name: str):
    blocks, text, page = load_page(name)
    return parse_page(blocks, page, text)


def by_code(rows):
    return {row.code: row for row in rows}


# --------------------------------------------------------------------------- #
# per-objective tables
# --------------------------------------------------------------------------- #
def test_basico_table_pairs_each_objective_with_its_own_indicators():
    rows = by_code(rows_for("basico_per_objective"))
    assert set(rows) == {"11", "16", "17", "2"}
    assert all(not row.joint for row in rows.values())

    # OA 11 is the patterns objective; its indicators must be about patterns
    assert "patrones repetitivos" in rows["11"].statement
    assert len(rows["11"].indicators) == 5
    assert all("patr" in indicator.lower() for indicator in rows["11"].indicators)

    # this page's whole indicator cell arrives as one block, so the bullets
    # have to be split out of it
    assert rows["16"].indicators[0].startswith("Miden con unidades no estandarizadas")

    # and the objective the site now numbers differently is still read as
    # printed, so the join can correct it later
    assert "números ordinales" in rows["2"].statement


def test_secundaria_table_rows():
    rows = by_code(rows_for("secundaria_per_objective"))
    assert set(rows) == {"1", "2", "3"}
    assert all(not row.joint for row in rows.values())
    assert rows["1"].indicators[0].startswith("Identifican el tipo de número")
    # the objective's own sub-bullets sit in the left column and must not leak
    assert not any("Transfiriendo propiedades" in i for i in rows["2"].indicators)
    assert len(rows["3"].indicators) >= 6


def test_inline_bare_codes_are_read():
    rows = by_code(rows_for("inline_letter_codes"))
    assert set(rows) == {"a", "b", "c"}
    assert rows["a"].indicators[0].startswith("Registran observaciones")
    assert rows["c"].indicators[0].startswith("Identifican una hipótesis")
    assert all(not row.joint for row in rows.values())


def test_wrapped_indicator_lines_are_rejoined():
    rows = by_code(rows_for("secundaria_per_objective"))
    joined = [i for i in rows["1"].indicators if i.endswith("involucradas.")]
    assert joined, "a bullet split across two blocks should come back as one string"
    assert joined[0].startswith("Identifican el tipo de número")


def test_a_one_word_wrapped_tail_is_kept():
    """Continuation lines are exempt from the length floor for new indicators."""
    rows = by_code(rows_for("secundaria_per_objective"))
    tails = [i for i in rows["1"].indicators if i.endswith("viceversa.")]
    assert tails, "the wrapped tail 'viceversa.' must not be dropped as furniture"
    assert tails[0].startswith("Transforman expresiones del lenguaje natural")


# --------------------------------------------------------------------------- #
# joint tables
# --------------------------------------------------------------------------- #
def test_joint_table_shares_one_set_across_its_objectives():
    rows = by_code(rows_for("joint_prefixed_codes"))
    assert set(rows) == {"2", "c", "d"}
    assert all(row.joint for row in rows.values())
    # one indicator set for the activity, not split by vertical position
    assert rows["2"].indicators == rows["c"].indicators == rows["d"].indicators
    assert len(rows["2"].indicators) == 5


def test_joint_table_with_a_merged_objectives_cell():
    rows = by_code(rows_for("joint_merged_cell"))
    assert set(rows) == {"3", "c", "d", "f", "i"}
    assert all(row.joint for row in rows.values())
    assert rows["3"].statement.startswith("Modelar los efectos del cambio climático")
    assert len(rows["3"].indicators) == 4
    # the section must stop before the activity that follows it
    assert not any("Recordemos" in i for i in rows["3"].indicators)


# --------------------------------------------------------------------------- #
# pages that must be ignored
# --------------------------------------------------------------------------- #
def test_activity_page_is_not_mistaken_for_a_table():
    """Its numbered steps ("4. Elabora un modelo ...") are not objectives."""
    rows = rows_for("activity_page_not_table")
    for row in rows:
        assert not row.statement.startswith(("4. Elabora", "2. Cada estudiante"))


def test_page_without_a_table_header_yields_nothing():
    blocks = [(50.0, 60.0, 200.0, 80.0, "Bibliografía recomendada", 0, 0)]
    assert parse_page(blocks, 1, "Bibliografía recomendada") == []


# --------------------------------------------------------------------------- #
# bullet splitting
# --------------------------------------------------------------------------- #
def test_split_bullets_handles_every_glyph():
    for glyph in ("•", "›", ">>", "‣", "●", "ú"):
        cell = f"{glyph} Primero. {glyph} Segundo. {glyph} Tercero."
        assert _split_bullets(cell) == ["Primero.", "Segundo.", "Tercero."]


def test_the_symbol_font_bullet_does_not_eat_real_accents():
    """Several Programas bullet with a Symbol glyph that decodes to "ú"."""
    # a bare "ú" is a bullet ...
    assert _split_bullets("ú Explican los flujos de energía. ú Distinguen los organismos.") == [
        "Explican los flujos de energía.",
        "Distinguen los organismos.",
    ]
    # ... but "ú" inside a word is just a letter
    prose = "El número púrpura y la raíz cúbica de un número."
    assert _split_bullets(prose) == [prose]
    assert _split_bullets("Calculan el perímetro y el área.") == [
        "Calculan el perímetro y el área."
    ]
    # text before the first bullet is a stray fragment, not an indicator
    assert _split_bullets("Encabezado suelto • Uno. • Dos.") == ["Uno.", "Dos."]
    # a cell with no bullets at all is kept whole
    assert _split_bullets("Una sola frase.") == ["Una sola frase."]
    assert _split_bullets("   ") == []


# --------------------------------------------------------------------------- #
# joining onto the dataset
# --------------------------------------------------------------------------- #
def test_objective_key_and_candidates():
    assert objective_key("MA1M OA 07", "conocimiento") == ("conocimiento", "7")
    assert objective_key("MA1M OAH a", "habilidad") == ("habilidad", "a")
    assert objective_key("MA1M OAA E", "actitud") == ("actitud", "E")
    assert objective_key("sin codigo", "conocimiento") is None
    assert pdf_code_candidates("7")[0] == ("conocimiento", "7")
    assert pdf_code_candidates("a")[0] == ("habilidad", "a")
    assert pdf_code_candidates("E")[0] == ("actitud", "E")


def test_statement_similarity_survives_pdf_artefacts():
    """Ligatures and line-wrap hyphens must not break the match."""
    pdf = "OA 12 Identiﬁ car en el entorno ﬁ gu- ras 3D y ﬁ guras 2D y relacio- narlas."
    html = ("Identificar en el entorno figuras 3D y figuras 2D y relacionarlas, "
            "usando material concreto.")
    assert statement_similarity(pdf, html) > 0.9
    assert statement_similarity(pdf, "Leer números del 0 al 20 y representarlos.") < 0.3
    assert statement_similarity("", html) == 0.0
    assert statement_similarity("corto", html) == 0.0


def _subject(*objectives):
    return {"subject_id": "matematica", "learning_objectives": list(objectives)}


def _objective(oa_id, code, category, statement):
    return {"oa_id": oa_id, "code": code, "category": category, "statement": statement}


def test_join_follows_the_statement_not_the_code():
    """The Básico Programas renumber objectives; the statement is authoritative."""
    subject = _subject(
        _objective("CL_MAT_1B_OA12", "MA01 OA 12", "conocimiento",
                   "Describir y registrar la igualdad y la desigualdad como equilibrio."),
        _objective("CL_MAT_1B_OA14", "MA01 OA 14", "conocimiento",
                   "Identificar en el entorno figuras 3D y figuras 2D y relacionarlas, "
                   "usando material concreto."),
    )
    extracted = PdfIndicators(pdf_url="http://example.test/programa.pdf")
    extracted.rows = [
        TableRow(
            code="12", page=79,
            statement="OA 12 Identiﬁ car en el entorno ﬁ guras 3D y ﬁ guras 2D y "
                      "relacionarlas, usando material concreto.",
            indicators=["Clasifican figuras 2D y explican el criterio usado."],
        )
    ]
    report = JoinReport()
    attach_to_subject(subject, extracted, "1_basico", report)

    renumbered = subject["learning_objectives"][1]
    assert renumbered["code"] == "MA01 OA 14"
    assert renumbered["indicators"] == [
        "Clasifican figuras 2D y explican el criterio usado."
    ]
    assert renumbered["indicators_scope"] == "objective"
    assert renumbered["indicators_source"] == ["http://example.test/programa.pdf"]
    assert "indicators" not in subject["learning_objectives"][0]
    assert report.renumbered_rows == 1


def test_join_rejects_a_mismatched_row():
    subject = _subject(
        _objective("CL_X_1M_OA04", "CN1M OA 04", "conocimiento",
                   "Explicar la formación de los fósiles a partir de evidencias."),
    )
    extracted = PdfIndicators(pdf_url="p.pdf")
    extracted.rows = [
        TableRow(code="4", page=143,
                 statement="4. Elabora un modelo que indique las variaciones de "
                           "cantidad de organismos en una población de pulgones.",
                 indicators=["Algo que no corresponde a este objetivo."])
    ]
    report = JoinReport()
    attach_to_subject(subject, extracted, "1_medio", report)
    assert "indicators" not in subject["learning_objectives"][0]
    assert len(report.rejected_low_similarity) == 1
    assert report.rejected_low_similarity[0]["closest_code"] == "CN1M OA 04"


def test_joint_rows_are_marked_as_unit_scope():
    statement = "Tomar decisiones en situaciones de incerteza que involucren datos."
    subject = _subject(_objective("CL_X_3M_OA02", "MA3M OA 02", "conocimiento", statement))
    extracted = PdfIndicators(pdf_url="p.pdf")
    extracted.rows = [
        TableRow(code="2", page=56, statement=statement, joint=True,
                 indicators=["Extraen e interpretan información estadística."])
    ]
    report = JoinReport()
    attach_to_subject(subject, extracted, "3_medio", report)
    assert subject["learning_objectives"][0]["indicators_scope"] == "unit"
    assert report.joint_rows == 1


def test_indicators_are_deduplicated_across_pdfs():
    statement = "Calcular operaciones con números racionales en forma simbólica."
    subject = _subject(_objective("CL_X_1M_OA01", "MA1M OA 01", "conocimiento", statement))
    report = JoinReport()
    for _pass in range(2):
        extracted = PdfIndicators(pdf_url="p.pdf")
        extracted.rows = [
            TableRow(code="1", page=70, statement=statement,
                     indicators=["Identifican el tipo de número."])
        ]
        attach_to_subject(subject, extracted, "1_medio", report)
    assert subject["learning_objectives"][0]["indicators"] == [
        "Identifican el tipo de número."
    ]
    assert subject["learning_objectives"][0]["indicators_source"] == ["p.pdf"]


def test_resolve_pdf_url_prefers_the_programa():
    html = """
    <a href="/sites/default/files/otro.pdf">Otro</a>
    <a href="/sites/default/files/articles-1_programa.pdf">Programa</a>
    """
    assert resolve_pdf_url(html, "https://www.curriculumnacional.cl/recursos/x") == (
        "https://www.curriculumnacional.cl/sites/default/files/articles-1_programa.pdf"
    )
    assert resolve_pdf_url("<a href='/x.html'>no pdf</a>", "https://x.test/") is None


def test_joint_page_without_indicators_does_not_crash():
    """A joint table whose indicator column is empty must yield nothing, quietly.

    Regression: `_assign_statements` used to index a rows list that the joint
    path had returned empty, taking down the whole PDF.
    """
    blocks = [
        (85.0, 60.0, 300.0, 75.0, "Objetivos de Aprendizaje", 0, 0),
        (312.0, 60.0, 530.0, 75.0, "Indicadores de evaluación", 1, 0),
        (85.0, 120.0, 300.0, 200.0, "OA 2: Tomar decisiones en situaciones de incerteza.", 2, 0),
        (312.0, 120.0, 530.0, 140.0, "• x", 3, 0),  # too short to be an indicator
    ]
    assert parse_page(blocks, 56, "") == []


def test_unbulleted_indicator_column_is_read_one_per_block():
    """Some 2021 Programas set the indicators as plain paragraphs, no glyph."""
    blocks = [
        (90.7, 107.3, 300.0, 120.0, "OBJETIVOS DE APRENDIZAJE", 0, 0),
        (346.9, 107.3, 540.0, 120.0, "INDICADORES DE EVALUACIÓN", 1, 0),
        (90.7, 132.7, 300.0, 210.0,
         "OA 2: Explicar, por medio de investigaciones experimentales, fenómenos "
         "químicos cotidianos.", 2, 0),
        (346.9, 128.8, 540.0, 190.0,
         "Explican comportamientos y propiedades de diversas sustancias químicas.", 3, 0),
        (347.0, 196.6, 540.0, 250.0,
         "Argumentan implicancias éticas, sociales y ambientales de iniciativas.", 4, 0),
    ]
    rows = parse_page(blocks, 57, "")
    assert len(rows) == 1
    assert rows[0].code == "2"
    assert rows[0].joint
    assert rows[0].indicators == [
        "Explican comportamientos y propiedades de diversas sustancias químicas.",
        "Argumentan implicancias éticas, sociales y ambientales de iniciativas.",
    ]


def test_single_angle_bracket_bullet_is_recognised_but_not_inequalities():
    """The Tecnología Programas bullet with a lone ">"."""
    assert _split_bullets(
        "> Establecen necesidades del entorno. > Identifican procedimientos."
    ) == ["Establecen necesidades del entorno.", "Identifican procedimientos."]
    prose = "Resuelven inecuaciones del tipo x > 3 y también y > z en el plano."
    assert _split_bullets(prose) == [prose]
    # ">>" still wins over ">"
    assert _split_bullets(">> Registran observaciones. >> Describen procesos.") == [
        "Registran observaciones.",
        "Describen procesos.",
    ]


def test_rejected_rows_keep_their_indicator_text():
    """A dropped row is source material, so it must survive in full."""
    subject = _subject(
        _objective("CL_X_1M_OA04", "CN1M OA 04", "conocimiento",
                   "Explicar la formación de los fósiles a partir de evidencias."),
    )
    extracted = PdfIndicators(pdf_url="http://example.test/p.pdf")
    extracted.rows = [
        TableRow(code="4", page=143,
                 statement="4. Elabora un modelo de las variaciones de una población.",
                 indicators=["Un indicador que no corresponde a este objetivo."])
    ]
    report = JoinReport()
    attach_to_subject(subject, extracted, "1_medio", report)

    assert "indicators" not in subject["learning_objectives"][0]
    (dropped,) = report.rejected_low_similarity
    assert dropped["indicators"] == ["Un indicador que no corresponde a este objetivo."]
    assert dropped["pdf_url"] == "http://example.test/p.pdf"
    assert dropped["pdf_code"] == "4"
    assert dropped["pdf_page"] == 143
    assert dropped["closest_oa_id"] == "CL_X_1M_OA04"
    assert dropped["pdf_statement"].startswith("4. Elabora un modelo")
