"""The coverage report, and the manifest summary the explorer reads.

Coverage used to be asserted against whatever total the last run produced, which
can only confirm that nothing changed. It is now computed against the inventory
the ministry publishes, and its job is to keep four situations apart that a
single "pages without objectives" number ran together.
"""

from __future__ import annotations

import pytest

from mineduc_scraper import inventory
from mineduc_scraper.export import summarise
from mineduc_scraper.inventory import (
    STATUS_DEFINED_ELSEWHERE,
    STATUS_INGESTED,
    STATUS_NOT_IN_DATASET,
    STATUS_PARSER_GAP,
    STATUS_SOURCE_ABSENT,
    Offering,
    build_report,
    merge_offerings,
)


def offering(level_id, subject_id, fmt=inventory.FORMAT_HTML):
    return Offering(
        curriculum_base="base", curriculum_base_name="Base",
        level_id=level_id, level_name=level_id,
        subject_slug=subject_id, subject_id=subject_id,
        expected_source="fuente", source_format=fmt,
        source_url=f"https://example.test/{level_id}/{subject_id}",
    )


def subject(objectives=0, **extra):
    return {
        "subject_id": "s", "subject_name": "S", "track": "plan_comun",
        "curriculum_base": "base", "documents": [],
        "learning_objectives": [
            {"oa_id": f"A{i}", "oa_number": i + 1, "category": "conocimiento",
             "code": f"OA {i + 1}", "statement": "Un enunciado."}
            for i in range(objectives)
        ],
        **extra,
    }


def db(subjects):
    levels = {}
    for (level_id, subject_id), payload in subjects.items():
        level = levels.setdefault(level_id, {
            "level_id": level_id, "level_name": level_id, "subjects": {}})
        level["subjects"][subject_id] = {**payload, "subject_id": subject_id}
    return {"metadata": {}, "levels": levels, "transversal_objectives": {}}


# --------------------------------------------------------------------------- #
def test_an_offering_with_objectives_is_ingested():
    report = build_report(db({("1_medio", "mat"): subject(3)}),
                          [offering("1_medio", "mat")])
    assert report["by_status"] == {STATUS_INGESTED: 1}
    assert report["objectives_ingested"] == 3
    assert report["rows"][0]["source_parsed"] is True


def test_an_empty_offering_with_a_verified_reason_is_source_absence():
    """Religión: the ministry publishes no objectives, and says why."""
    report = build_report(
        db({("1_basico", "religion"): subject(0, no_objectives_reason={
            "code": "governed_separately_no_published_objectives",
            "explanation": "Decreto N° 924.",
            "source_url": "https://example.test/924", "verified_on": "2026-09-05"})}),
        [offering("1_basico", "religion")],
    )
    assert report["by_status"] == {STATUS_SOURCE_ABSENT: 1}
    assert report["parser_gaps"] == []
    assert report["rows"][0]["source_parsed"] is True


def test_an_empty_offering_whose_objectives_live_elsewhere_is_not_a_gap():
    report = build_report(
        db({("epja_n1_media", "filo"): subject(0, objectives_in_level="epja_media")}),
        [offering("epja_n1_media", "filo")],
    )
    assert report["by_status"] == {STATUS_DEFINED_ELSEWHERE: 1}
    assert report["parser_gaps"] == []


def test_an_unexplained_empty_offering_is_a_parser_gap():
    """The only one of the four that is a defect in this project."""
    report = build_report(db({("1_medio", "mat"): subject(0)}),
                          [offering("1_medio", "mat")])
    assert report["by_status"] == {STATUS_PARSER_GAP: 1}
    assert report["parser_gaps"] == [
        {"level_id": "1_medio", "subject_id": "mat",
         "source_url": "https://example.test/1_medio/mat"},
    ]
    assert report["rows"][0]["source_parsed"] is False
    assert report["rows"][0]["unresolved_reason"]


def test_an_expected_offering_absent_from_the_dataset_is_reported():
    report = build_report(db({}), [offering("1_medio", "mat")])
    assert report["by_status"] == {STATUS_NOT_IN_DATASET: 1}
    assert report["offerings_not_in_dataset"]


def test_a_dataset_route_the_inventory_did_not_expect_is_surfaced():
    """Not an error, but the signal that discovery has drifted from the site."""
    report = build_report(db({("1_medio", "sorpresa"): subject(2)}), [])
    assert report["unexpected_in_dataset"] == [
        {"level_id": "1_medio", "subject_id": "sorpresa", "objectives": 2,
         "source_url": None},
    ]


def test_completeness_is_not_measured_against_a_previous_total():
    assert "official source inventory" in build_report(db({}), [])["generated_from"]


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_the_more_structured_source_wins_for_one_offering():
    """HTML beats a Base Curricular PDF when both publish the same offering."""
    merged = merge_offerings(
        [offering("epja_n1_basica", "len", inventory.FORMAT_BASE_PDF)],
        [offering("epja_n1_basica", "len", inventory.FORMAT_HTML)],
    )
    assert len(merged) == 1
    assert merged[0].source_format == inventory.FORMAT_HTML


def test_an_offering_only_a_base_document_defines_is_still_expected():
    """The Bases define offerings the site navigates no page for."""
    merged = merge_offerings(
        [offering("1_medio", "mat")],
        [offering("epja_media", "filo", inventory.FORMAT_BASE_PDF)],
    )
    assert {o.subject_id for o in merged} == {"mat", "filo"}


def test_base_landing_pages_are_discovered_from_the_master_index():
    html = """
      <a href="/curriculum/1o-6o-basico">1° a 6° Básico</a>
      <a href="/curriculum/1o-6o-basico/matematica/1-basico">Matemática</a>
      <a href="/curriculum/1o-6o-basico/curso/x">no</a>
      <a href="https://otro.test/">externo</a>
    """
    assert inventory._base_landing_paths(html) == ["/curriculum/1o-6o-basico"]


# --------------------------------------------------------------------------- #
# The manifest summary the explorer's coverage panel reads
# --------------------------------------------------------------------------- #
def test_offerings_and_subjects_are_counted_separately():
    """Labelling level x subject pages "asignaturas" overstated the dataset."""
    database = db({
        ("1_basico", "mat"): {**subject(2), "subject_name": "Matemática"},
        ("2_basico", "mat"): {**subject(2), "subject_name": "Matemática"},
        ("2_basico", "len"): {**subject(1), "subject_name": "Lenguaje"},
    })
    stats = summarise(database)
    assert stats["total_offerings"] == 3
    assert stats["distinct_subjects"] == 2


def test_the_summary_reports_epja_religion_status_and_source():
    database = db({
        ("epja_media", "filo"): {
            **subject(2, curriculum_status="en_implementacion"),
            "subject_name": "Filosofía"},
        ("1_basico", "religion"): {**subject(0), "subject_name": "Religión"},
    })
    for objective in (database["levels"]["epja_media"]["subjects"]["filo"]
                      ["learning_objectives"]):
        objective["curriculum_status"] = "en_implementacion"
        objective["provenance"] = {"source_type": "base_curricular_pdf"}

    stats = summarise(database)
    assert stats["total_epja_objectives"] == 2
    assert stats["total_religion_objectives"] == 0
    assert stats["offerings_without_objectives"] == 1
    assert stats["status_summary"] == {"en_implementacion": 2}
    assert stats["total_by_source_type"] == {"base_curricular_pdf": 2}


def test_distinct_codes_counts_a_shared_3_4_medio_code_once():
    database = db({
        ("3_medio", "aten"): subject(0),
        ("4_medio", "aten"): subject(0),
    })
    for level in ("3_medio", "4_medio"):
        database["levels"][level]["subjects"]["aten"]["learning_objectives"] = [
            {"oa_id": f"{level}-1", "oa_number": 1, "category": "conocimiento",
             "code": "OA 1.", "statement": "Aplicar cuidados básicos."},
        ]
    stats = summarise(database)
    assert stats["distinct_official_codes"] == 1
    assert stats["total_offerings"] == 2
