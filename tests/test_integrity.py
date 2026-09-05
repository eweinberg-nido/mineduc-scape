"""Integrity audits: text damage, duplicates, conflicts, provenance and status.

The classification is the point. Two grades publishing one objective under one
code is how MINEDUC publishes 3° and 4° Medio; two codes carrying one statement
inside a single subject is the Sala Cuna defect. An audit that reported both as
"duplicates" would have hidden the second among 233 instances of the first.
"""

from __future__ import annotations

import pytest

from mineduc_scraper import integrity
from mineduc_scraper.integrity import text_findings


# --------------------------------------------------------------------------- #
# Text integrity
# --------------------------------------------------------------------------- #
def test_flags_a_statement_truncated_at_its_colon():
    assert "ends on a colon with no components captured" in text_findings(
        "Demostrar que comprenden las fracciones propias:"
    )


def test_accepts_a_stem_that_has_its_list():
    assert text_findings(
        "Demostrar que comprenden las fracciones propias:\n"
        "- representándolas de manera concreta.\n"
        "- creando grupos de fracciones equivalentes."
    ) == []


def test_flags_mojibake_and_lost_spaces():
    assert "contains a replacement character (U+FFFD)" in text_findings(
        "Calcular la superficie del tri�ngulo."
    )
    assert "contains joined words (a lost space after punctuation)" in text_findings(
        "Analizar el problema.Los estudiantes describen el resultado."
    )


def test_flags_a_question_mark_standing_inside_a_word():
    """A dropped accented character extracts as a "?" mid-word."""
    assert "contains a suspicious '?' glyph" in text_findings(
        "Comprender la funci?n de los seres vivos."
    )
    assert "contains a suspicious '?' glyph" in text_findings("How do you say?? I'm?")


def test_a_question_mark_ending_a_question_is_not_damage():
    """Inglés statements quote example questions; those are correct text."""
    assert text_findings(
        "Formular preguntas sobre rutinas; por ejemplo: Does he cook? Yes, he does."
    ) == []


def test_flags_broken_hyphenation_but_not_a_hyphen_used_as_a_parenthesis():
    assert "contains broken line-wrap hyphenation" in text_findings(
        "Desarrollar habili- dades de investigación científica."
    )
    # Spanish sets parenthetical asides with hyphens, and the closing one has
    # exactly the shape of a line break. Flagging it would bury the real ones.
    assert text_findings(
        "Descubrir regularidades matemáticas -la estructura de las operaciones "
        "inversas, el valor posicional- y comunicar los hallazgos."
    ) == []


def test_flags_a_line_repeated_verbatim_but_not_a_repeated_phrase():
    assert "contains a line repeated verbatim" in text_findings(
        "Participar en actividades:\n- Integrarse en talleres.\n- Integrarse en talleres."
    )
    # A phrase recurring across the items of a list is ordinary curriculum prose.
    assert text_findings(
        "Participar en una variedad de actividades físicas y/o deportivas; por "
        "ejemplo: integrarse en talleres de actividades físicas y/o deportivas "
        "extraprogramáticas de su comunidad."
    ) == []


def test_flags_an_empty_or_one_word_statement():
    assert text_findings("") == ["empty statement"]
    assert "statement is only 1 word(s) long" in text_findings("Explicar")
    # "Trabajar colaborativamente." is short and is exactly what MINEDUC prints.
    assert text_findings("Trabajar colaborativamente.") == []


# --------------------------------------------------------------------------- #
# Duplicates and conflicts
# --------------------------------------------------------------------------- #
def make_db(objectives_by_scope, oats=None):
    levels = {}
    for (level_id, subject_id), objectives in objectives_by_scope.items():
        level = levels.setdefault(level_id, {
            "level_id": level_id, "level_name": level_id, "subjects": {},
        })
        level["subjects"][subject_id] = {
            "subject_id": subject_id, "subject_name": subject_id,
            "track": "plan_comun", "curriculum_base": "1o-6o-basico",
            "source_url": f"https://example.test/{level_id}/{subject_id}",
            "learning_objectives": objectives,
        }
    return {"metadata": {}, "levels": levels,
            "transversal_objectives": oats or {}}


def oa(oa_id, code, statement, **extra):
    return {"oa_id": oa_id, "oa_number": 1, "category": "conocimiento",
            "code": code, "statement": statement, **extra}


def test_two_codes_carrying_one_statement_in_one_subject_is_a_conflict():
    """The shape of the Sala Cuna OA 03 / OA 04 defect."""
    database = make_db({("sala_cuna", "ice"): [
        oa("A", "OA 03 CES SC", "Manifestar interés por canciones, juegos y bailes."),
        oa("B", "OA 04 CES SC", "Manifestar interés por canciones, juegos y bailes."),
    ]})
    report = integrity.audit_duplicates(database)
    assert report["counts"]["same_text_different_codes"] == 1
    clash = report["same_text_different_codes"][0]
    assert clash["where"] == "sala_cuna/ice"
    assert clash["codes"] == ["OA 03 CES SC", "OA 04 CES SC"]


def test_a_corrected_sala_cuna_pair_is_clean():
    database = make_db({("sala_cuna", "ice"): [
        oa("A", "OA 03 CES SC", "Manifestar interés por canciones, juegos y bailes."),
        oa("B", "OA 04 CES SC", "Explorar utensilios domésticos y objetos tecnológicos."),
    ]})
    report = integrity.audit_duplicates(database)
    assert report["counts"]["same_text_different_codes"] == 0


def test_one_code_with_two_statements_in_one_subject_is_a_conflict():
    database = make_db({("1_medio", "matematica"): [
        oa("A", "MA1M OA 01", "Calcular operaciones con números racionales."),
        oa("B", "MA1M OA 01", "Algo completamente distinto."),
    ]})
    report = integrity.audit_duplicates(database)
    assert report["counts"]["same_code_different_text"] == 1
    assert report["same_code_different_text"][0]["where"] == "1_medio/matematica"


def test_a_code_reused_across_subjects_is_the_published_numbering_not_a_conflict():
    """Every TP speciality, and every EPJA asignatura, numbers from "OA 1"."""
    database = make_db({
        ("3_medio", "acuicultura"): [oa("A", "OA 1.", "Manejar reproductores.")],
        ("3_medio", "electricidad"): [oa("B", "OA 1.", "Instalar motores eléctricos.")],
    })
    report = integrity.audit_duplicates(database)
    assert report["counts"]["same_code_different_text"] == 0
    assert report["counts"]["code_scoped_to_subject"] == 1


def test_the_3_and_4_medio_pair_is_classified_as_expected():
    """The same objective published under both grades — a documented pattern."""
    statement = "Aplicar cuidados básicos de enfermería."
    database = make_db({
        ("3_medio", "atencion"): [oa("A", "OA 1.", statement)],
        ("4_medio", "atencion"): [oa("B", "OA 1.", statement)],
    })
    report = integrity.audit_duplicates(database)
    assert report["counts"]["shared_code_across_levels_expected"] == 1
    assert report["counts"]["shared_code_across_levels_unexpected"] == 0
    assert report["shared_code_across_levels_expected"][0]["levels"] == [
        "3_medio", "4_medio",
    ]


def test_a_code_shared_across_unrelated_levels_is_not_treated_as_that_pattern():
    statement = "Un enunciado idéntico."
    database = make_db({
        ("1_basico", "musica"): [oa("A", "MU OA 01", statement)],
        ("6_basico", "musica"): [oa("B", "MU OA 01", statement)],
    })
    report = integrity.audit_duplicates(database)
    assert report["counts"]["shared_code_across_levels_unexpected"] == 1


def test_conflicting_records_under_one_deterministic_id_are_reported():
    database = make_db({("1_medio", "matematica"): [
        oa("CL_MAT_1M_OA01", "MA1M OA 01", "Un enunciado."),
        oa("CL_MAT_1M_OA01", "MA1M OA 02", "Otro enunciado distinto."),
    ]})
    report = integrity.audit_duplicates(database)
    assert report["counts"]["duplicate_oa_ids"] == 1
    assert report["conflicting_oa_ids"][0]["oa_id"] == "CL_MAT_1M_OA01"


def test_a_route_recorded_twice_is_reported():
    database = make_db({
        ("1_basico", "a"): [oa("A", "X", "Uno.")],
        ("1_basico", "b"): [oa("B", "Y", "Dos.")],
    })
    database["levels"]["1_basico"]["subjects"]["b"]["source_url"] = (
        "https://example.test/1_basico/a"
    )
    assert integrity.audit_routes(database)["source_url_used_twice"] == [
        {"url": "https://example.test/1_basico/a", "count": 2},
    ]


def test_a_subject_with_no_site_page_may_point_at_its_base_document():
    """The absence of a route is not a duplicate route."""
    database = make_db({
        ("epja_media", "a"): [oa("A", "OA 1", "Uno.")],
        ("epja_media", "b"): [oa("B", "OA 1", "Dos.")],
    })
    for subject in database["levels"]["epja_media"]["subjects"].values():
        subject["source_url"] = "https://example.test/bases-epja"
        subject["site_page_published"] = False
    assert integrity.audit_routes(database)["source_url_used_twice"] == []


# --------------------------------------------------------------------------- #
# Provenance and status
# --------------------------------------------------------------------------- #
PROV = {"source_url": "https://example.test/x", "source_type": "html_curriculum_page",
        "retrieved_at": "2026-09-05", "extraction_method": "selectolax"}


def test_missing_provenance_is_reported_per_record():
    database = make_db({("1_medio", "matematica"): [
        oa("A", "X", "Con procedencia.", provenance=PROV),
        oa("B", "Y", "Sin procedencia."),
    ]})
    report = integrity.audit_provenance(database)
    assert report["missing"] == ["1_medio/matematica/B"]
    assert report["by_source_type"] == {"html_curriculum_page": 1}


def test_a_pdf_record_without_a_page_number_is_reported():
    database = make_db({("epja_media", "filosofia"): [
        oa("A", "OA 1", "Analizar.", provenance={
            **PROV, "source_type": "base_curricular_pdf"}),
    ]})
    assert integrity.audit_provenance(database)["pdf_records_without_page"] == [
        "epja_media/filosofia/A",
    ]


def test_a_status_asserted_without_a_source_is_reported():
    database = make_db({("1_medio", "matematica"): [
        oa("A", "X", "Con fuente.", curriculum_status="vigente",
           status_source={"url": "https://example.test", "note": "n",
                          "verified_on": "2026-09-05"}),
        oa("B", "Y", "Sin fuente.", curriculum_status="vigente"),
        oa("C", "Z", "No verificado.", curriculum_status="desconocido"),
    ]})
    report = integrity.audit_status(database)
    assert report["asserted_without_source"] == ["1_medio/matematica/B"]
    assert report["by_status"] == {"desconocido": 1, "vigente": 2}


def test_a_status_outside_the_vocabulary_is_reported():
    database = make_db({("1_medio", "m"): [
        oa("A", "X", "Uno.", curriculum_status="mas_o_menos_vigente"),
    ]})
    assert integrity.audit_status(database)["unknown_value"]


def test_prioritized_without_its_programme_metadata_is_reported():
    database = make_db({("1_medio", "m"): [
        oa("A", "X", "Uno.", prioritized=True),
        oa("B", "Y", "Dos.", prioritized=True, prioritization={
            "programme": "Priorización Curricular", "period": "2023-2025",
            "status": "historico"}),
    ]})
    report = integrity.audit_prioritization(database)
    assert report["flagged"] == 2
    assert report["without_metadata"] == ["1_medio/m/A"]


# --------------------------------------------------------------------------- #
# Regression between builds
# --------------------------------------------------------------------------- #
def test_an_objective_that_disappears_between_builds_is_named():
    """A total alone cannot show this: an equal number of new records hides it."""
    before = make_db({("1_medio", "m"): [oa("A", "X", "Uno."), oa("B", "Y", "Dos.")]})
    after = make_db({("1_medio", "m"): [oa("A", "X", "Uno."), oa("C", "Z", "Tres.")]})
    report = integrity.audit_regression(after, before)

    assert report["baseline_objectives"] == report["objectives"] == 2
    assert report["removed"] == 1 and report["removed_ids"] == ["B"]
    assert report["added"] == 1


def test_regression_is_skipped_without_a_baseline():
    assert integrity.audit_regression(make_db({}), None) == {"compared": False}


def test_run_returns_every_audit():
    report = integrity.run(make_db({("1_medio", "m"): [oa("A", "X", "Uno.")]}))
    assert set(report) == {
        "text", "duplicates", "routes", "provenance", "status",
        "prioritization", "regression",
    }
