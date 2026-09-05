"""EPJA ingestion, the Religión finding, corrections, provenance and status.

These are the passes that turned a dataset with a documented hole in it into one
that can say, for every published curriculum offering, whether it has objectives
and — when it does not — why not on the ministry's own authority.
"""

from __future__ import annotations

import copy

import pytest

from conftest import load_bases_page

from mineduc_scraper import corrections, epja, integrity, provenance, religion
from mineduc_scraper.bases_pdf import parse_document
from mineduc_scraper.taxonomy import (
    SOURCE_BASE_PDF,
    SOURCE_HTML,
    STATUS_DESCONOCIDO,
    STATUS_EN_IMPLEMENTACION,
    STATUS_PROPUESTA,
    STATUS_VIGENTE,
)

RETRIEVED = "2026-09-05T00:00:00+00:00"
EPJA_BASE = "bases-curriculares-educacion-personas-jovenes-adultas-epja"

# The five objectives the site publishes in HTML for EPJA Lenguaje y Comunicación,
# Nivel 1 de Educación Básica — the one EPJA page that renders objectives, and so
# the only place a second official route exists to check the PDF reader against.
HTML_LENGUAJE_N1 = [
    {"oa_id": "CL_LEN_E1B_LCTR_OA01", "oa_number": 1, "category": "conocimiento",
     "code": "EPJA LEN1 OA01", "strand_eje": "Lectura",
     "statement": "Leer en voz alta textos variados de manera fluida y adecuada "
                  "entonación."},
    {"oa_id": "CL_LEN_E1B_LCTR_OA02", "oa_number": 2, "category": "conocimiento",
     "code": "EPJA LEN1 OA02", "strand_eje": "Lectura",
     "statement": "Leer textos de diversos géneros (orales, escritos y "
                  "audiovisuales) para desarrollar la comprensión global."},
    {"oa_id": "CL_LEN_E1B_ESCR_OA03", "oa_number": 3, "category": "conocimiento",
     "code": "EPJA LEN1 OA03", "strand_eje": "Escritura",
     "statement": "Escribir con letra legible para una variedad de propósitos "
                  "personales y sociales."},
    {"oa_id": "CL_LEN_E1B_CO_OA04", "oa_number": 4, "category": "conocimiento",
     "code": "EPJA LEN1 OA04", "strand_eje": "Comunicación oral",
     "statement": "Expresarse de manera coherente y articulada utilizando un "
                  "vocabulario variado y gestos, posturas, volumen y dicción "
                  "adecuados al propósito y la situación comunicativa."},
    {"oa_id": "CL_LEN_E1B_INVS_OA05", "oa_number": 5, "category": "conocimiento",
     "code": "EPJA LEN1 OA05", "strand_eje": "Investigación",
     "statement": "Buscar y seleccionar información con honestidad, a partir de "
                  "un propósito."},
]


def sections(*names):
    return parse_document([load_bases_page(name) for name in names]).sections


def empty_db():
    return {
        "metadata": {"scraped_at": RETRIEVED, "total_oas": 0},
        "levels": {},
        "transversal_objectives": {},
    }


# --------------------------------------------------------------------------- #
# EPJA
# --------------------------------------------------------------------------- #
def test_ingests_epja_objectives_with_full_provenance():
    database = empty_db()
    report = epja.merge(database, sections("epja_filosofia_media"), RETRIEVED)

    assert report.objectives_added == 4
    assert report.levels_created == 1
    subject = database["levels"]["epja_media"]["subjects"]["filosofia"]
    objective = subject["learning_objectives"][0]

    assert objective["code"] == "OA 1"
    assert objective["provenance"]["source_type"] == SOURCE_BASE_PDF
    assert objective["provenance"]["source_page"] == 1
    assert objective["provenance"]["curriculum_base"] == EPJA_BASE
    assert objective["provenance"]["retrieved_at"] == RETRIEVED
    assert "Bases Curriculares" in objective["provenance"]["source_document"]
    assert objective["curriculum_status"] == STATUS_EN_IMPLEMENTACION
    assert objective["status_source"]["url"]


def test_combined_media_level_is_not_split_across_the_sites_two_levels():
    """The Bases define these asignaturas for "Nivel 1 y 2" as one block.

    Writing them into both site levels would duplicate every statement; writing
    them into one would assert a split the source does not make. They go into a
    combined level that names the two it covers.
    """
    database = empty_db()
    epja.merge(database, sections("epja_filosofia_media"), RETRIEVED)

    assert "epja_media" in database["levels"]
    assert database["levels"]["epja_media"]["level_scope"] == [
        "epja_n1_media", "epja_n2_media",
    ]
    objective = database["levels"]["epja_media"]["subjects"]["filosofia"][
        "learning_objectives"][0]
    assert objective["level_scope"] == ["epja_n1_media", "epja_n2_media"]
    # And nothing was written into the site's own two Nivel levels.
    assert "epja_n1_media" not in database["levels"]


def test_site_pages_for_a_combined_level_say_where_the_objectives_went():
    """An empty page must not read as a coverage hole when it is not one."""
    database = empty_db()
    database["levels"]["epja_n1_media"] = {
        "level_id": "epja_n1_media", "level_name": "EPJA Nivel 1 Media",
        "subjects": {"filosofia": {
            "subject_id": "filosofia", "subject_name": "Filosofía",
            "track": "plan_comun", "curriculum_base": EPJA_BASE,
            "learning_objectives": [],
        }},
    }
    report = epja.merge(database, sections("epja_filosofia_media"), RETRIEVED)

    deferred = database["levels"]["epja_n1_media"]["subjects"]["filosofia"]
    assert deferred["objectives_in_level"] == "epja_media"
    assert deferred["no_objectives_reason"]["code"] == (
        "objectives_defined_for_combined_level"
    )
    assert report.site_pages_deferred == [
        {"level_id": "epja_n1_media", "subject_id": "filosofia",
         "objectives_in_level": "epja_media"},
    ]


def test_structured_html_wins_over_the_pdf_and_verifies_it():
    """The one EPJA page published in HTML keeps its HTML records.

    The PDF is used to check them, not to replace them — extracting from a PDF
    when the same authoritative content exists as structured HTML would trade a
    better source for a worse one.
    """
    database = empty_db()
    database["levels"]["epja_n1_basica"] = {
        "level_id": "epja_n1_basica", "level_name": "EPJA Nivel 1 Básica",
        "subjects": {"lenguaje_comunicacion": {
            "subject_id": "lenguaje_comunicacion",
            "subject_name": "Lenguaje y Comunicación",
            "track": "plan_comun", "curriculum_base": EPJA_BASE,
            "learning_objectives": HTML_LENGUAJE_N1,
        }},
    }
    report = epja.merge(database, sections("epja_lenguaje_n1_basica"), RETRIEVED)

    subject = database["levels"]["epja_n1_basica"]["subjects"]["lenguaje_comunicacion"]
    assert report.objectives_added == 0
    assert len(subject["learning_objectives"]) == 5
    assert subject["learning_objectives"][0]["code"] == "EPJA LEN1 OA01"
    # All five agree with the Bases, character for character.
    assert report.verified_against_html == 5
    assert report.html_mismatches == []


def test_a_disagreement_between_the_html_and_the_bases_is_reported_not_resolved():
    database = empty_db()
    database["levels"]["epja_n1_basica"] = {
        "level_id": "epja_n1_basica", "level_name": "EPJA Nivel 1 Básica",
        "subjects": {"lenguaje_comunicacion": {
            "subject_id": "lenguaje_comunicacion",
            "subject_name": "Lenguaje y Comunicación",
            "track": "plan_comun", "curriculum_base": EPJA_BASE,
            "learning_objectives": [
                {**HTML_LENGUAJE_N1[0],
                 "statement": "Algo distinto de lo que imprimen las Bases."},
                *HTML_LENGUAJE_N1[1:],
            ],
        }},
    }
    report = epja.merge(database, sections("epja_lenguaje_n1_basica"), RETRIEVED)

    assert len(report.html_mismatches) == 1
    assert "statement differs" in report.html_mismatches[0]
    # Nothing was overwritten: two official routes disagreeing is a finding.
    subject = database["levels"]["epja_n1_basica"]["subjects"]["lenguaje_comunicacion"]
    assert subject["learning_objectives"][0]["statement"].startswith("Algo distinto")


def test_a_page_the_bases_do_not_define_is_recorded_as_source_absence():
    """Ciencias Naturales has a Nivel 1 Básica page; the Bases start at Nivel 2."""
    database = empty_db()
    database["levels"]["epja_n1_basica"] = {
        "level_id": "epja_n1_basica", "level_name": "EPJA Nivel 1 Básica",
        "subjects": {"ciencias_naturales": {
            "subject_id": "ciencias_naturales", "subject_name": "Ciencias Naturales",
            "track": "plan_comun", "curriculum_base": EPJA_BASE,
            "learning_objectives": [],
        }},
    }
    report = epja.merge(database, sections("epja_ciencias_n2_basica"), RETRIEVED)

    subject = database["levels"]["epja_n1_basica"]["subjects"]["ciencias_naturales"]
    assert subject["no_objectives_reason"]["code"] == "not_defined_in_bases"
    assert subject["no_objectives_reason"]["source_url"]
    assert report.pages_not_defined == [
        {"level_id": "epja_n1_basica", "subject_id": "ciencias_naturales"},
    ]


def test_formation_area_is_carried_on_the_subject():
    database = empty_db()
    epja.merge(database, sections("epja_filosofia_media",
                                  "epja_responsabilidad_media"), RETRIEVED)
    subjects = database["levels"]["epja_media"]["subjects"]
    assert subjects["filosofia"]["formation_area"] == "formacion_diferenciada_hc"
    assert subjects["filosofia"]["track"] == "plan_diferenciado_hc"
    assert subjects["responsabilidad_personal_social"]["formation_area"] == (
        "formacion_instrumental"
    )


def test_merge_is_idempotent():
    database = empty_db()
    parsed = sections("epja_filosofia_media")
    epja.merge(database, parsed, RETRIEVED)
    again = epja.merge(database, parsed, RETRIEVED)
    assert again.objectives_added == 0
    assert len(database["levels"]["epja_media"]["subjects"]["filosofia"]
               ["learning_objectives"]) == 4


# --------------------------------------------------------------------------- #
# Religión
# --------------------------------------------------------------------------- #
def religion_db(objectives=()):
    return {
        "metadata": {},
        "levels": {"1_basico": {"level_id": "1_basico", "level_name": "1° Básico",
                                "subjects": {"religion": {
                                    "subject_id": "religion", "subject_name": "Religión",
                                    "track": "plan_comun", "curriculum_base": "1o-6o-basico",
                                    "documents": [{"doc_type": "Marco Legal",
                                                   "title": "Decreto N° 924",
                                                   "url": "https://example.test/924"}],
                                    "learning_objectives": list(objectives),
                                }}}},
        "transversal_objectives": {},
    }


def test_religion_absence_is_recorded_with_its_governing_source():
    database = religion_db()
    report = religion.annotate(database)

    subject = database["levels"]["1_basico"]["subjects"]["religion"]
    reason = subject["no_objectives_reason"]
    assert reason["code"] == "governed_separately_no_published_objectives"
    assert "924" in reason["explanation"]
    assert reason["source_url"].startswith("https://www.curriculumnacional.cl/")
    assert reason["evidence_urls"]
    assert report["pages_annotated"] == 1


def test_religion_is_modelled_as_one_programme_per_credo():
    """Different confessions' programmes must not be merged into one subject."""
    database = religion_db()
    religion.annotate(database)
    model = database["levels"]["1_basico"]["subjects"]["religion"]["programme_model"]
    assert model["model"] == "por_credo"
    assert model["shared_national_objectives"] is False
    assert model["published_on_curriculumnacional"] is False


def test_the_religion_documents_are_kept():
    database = religion_db()
    religion.annotate(database)
    subject = database["levels"]["1_basico"]["subjects"]["religion"]
    assert len(subject["documents"]) == 1


def test_religion_finding_never_overwrites_real_objectives():
    """If the ministry starts publishing them, the finding must stand aside."""
    database = religion_db([{"oa_id": "X", "oa_number": 1, "category": "conocimiento",
                             "code": "RE01 OA 01", "statement": "Algo."}])
    report = religion.annotate(database)
    subject = database["levels"]["1_basico"]["subjects"]["religion"]
    assert "no_objectives_reason" not in subject
    assert report["pages_with_objectives"] == ["1_basico/religion"]


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
CORRECTION = {
    "id": "test-fix", "scope": "objective",
    "level_id": "sala_cuna", "subject_id": "ice", "code": "OA 04 CES SC",
    "field": "statement",
    "original_value": "Manifestar interés por canciones, juegos y bailes.",
    "corrected_value": "Explorar utensilios domésticos y objetos tecnológicos.",
    "authoritative_source_url": "https://example.test/bases.pdf",
    "authoritative_source_page": 93,
    "defect_origin": "mineduc_html",
    "explanation": "El sitio publica el enunciado de OA 03 también bajo OA 04.",
    "verified_on": "2026-09-05",
}


def correction_db(statement):
    return {
        "metadata": {},
        "levels": {"sala_cuna": {"level_id": "sala_cuna", "level_name": "Sala Cuna",
                                 "subjects": {"ice": {
                                     "subject_id": "ice", "subject_name": "ICE",
                                     "track": "plan_comun",
                                     "learning_objectives": [
                                         {"oa_id": "A", "oa_number": 4,
                                          "category": "conocimiento",
                                          "code": "OA 04 CES SC",
                                          "statement": statement},
                                     ]}}}},
    }


def test_correction_rewrites_the_field_and_keeps_the_original():
    database = correction_db(CORRECTION["original_value"])
    applied, skipped = corrections.apply_corrections(database, [CORRECTION])

    objective = database["levels"]["sala_cuna"]["subjects"]["ice"][
        "learning_objectives"][0]
    assert objective["statement"] == CORRECTION["corrected_value"]
    assert objective["correction"]["original_value"] == CORRECTION["original_value"]
    assert objective["correction"]["authoritative_source_page"] == 93
    assert objective["correction"]["defect_origin"] == "mineduc_html"
    assert len(applied) == 1 and not skipped


def test_correction_is_skipped_when_the_source_no_longer_matches():
    """Drift means the conflict needs re-verifying, not overwriting."""
    database = correction_db("Otro texto completamente distinto.")
    applied, skipped = corrections.apply_corrections(database, [CORRECTION])
    assert not applied
    assert len(skipped) == 1 and "no longer matches" in skipped[0]
    objective = database["levels"]["sala_cuna"]["subjects"]["ice"][
        "learning_objectives"][0]
    assert objective["statement"] == "Otro texto completamente distinto."


def test_correction_is_idempotent():
    database = correction_db(CORRECTION["original_value"])
    corrections.apply_corrections(database, [CORRECTION])
    applied, skipped = corrections.apply_corrections(database, [CORRECTION])
    assert applied[0]["id"] == "test-fix"
    assert not skipped


@pytest.mark.parametrize("field", ["authoritative_source_url", "explanation",
                                   "original_value", "verified_on"])
def test_a_correction_missing_its_evidence_is_refused(field):
    """A correction nobody can check is an undocumented rewrite of official text."""
    bad = {key: value for key, value in CORRECTION.items() if key != field}
    with pytest.raises(ValueError, match=field):
        corrections.apply_corrections(correction_db(CORRECTION["original_value"]), [bad])


def test_the_shipped_corrections_file_is_reviewable():
    """Every shipped correction carries the evidence a reviewer needs."""
    entries = corrections.load_corrections()
    assert entries, "the corrections file should not be empty"
    for entry in entries:
        for field in corrections.REQUIRED_FIELDS:
            assert entry.get(field), f"{entry['id']} is missing {field}"
        assert entry["explanation"].count(" ") > 20, (
            f"{entry['id']}: the explanation should say why the sources disagree"
        )


def test_the_sala_cuna_conflict_is_the_regression_fixture():
    """OA 03 / OA 04 CES SC, the duplicate that started this.

    curriculumnacional.cl publishes OA 03's statement under both codes, on the
    núcleo listing *and* on each objective's own detail page. The defect is in
    the ministry's HTML rather than in this project's parser, and the Bases
    Curriculares de Educación Parvularia settle it.
    """
    entry = next(e for e in corrections.load_corrections()
                 if e["id"] == "sala-cuna-ces-oa04")
    assert entry["code"] == "OA 04 CES SC"
    assert entry["defect_origin"] == "mineduc_html"
    assert entry["original_value"].startswith("Manifestar interés por canciones")
    assert entry["corrected_value"].startswith("Explorar utensilios domésticos")
    assert entry["authoritative_source_page"] == 93


# --------------------------------------------------------------------------- #
# Provenance, status and prioritization
# --------------------------------------------------------------------------- #
def annotated_db(**subject_overrides):
    database = {
        "metadata": {"scraped_at": RETRIEVED},
        "levels": {"1_medio": {"level_id": "1_medio", "level_name": "1° Medio",
                               "subjects": {"matematica": {
                                   "subject_id": "matematica",
                                   "subject_name": "Matemática",
                                   "track": "plan_comun",
                                   "curriculum_base": "7o-basico-2o-medio",
                                   "source_url": "https://example.test/mat",
                                   "learning_objectives": [
                                       {"oa_id": "A", "oa_number": 1,
                                        "category": "conocimiento",
                                        "code": "MA1M OA 01", "statement": "Calcular.",
                                        "prioritized": True,
                                        "source_url": "https://example.test/oa"},
                                   ],
                                   **subject_overrides,
                               }}}},
        "transversal_objectives": {"1o-6o-basico": [
            {"oat_id": "CL_OAT_1A6B_FISICA_01", "dimension": "Dimensión física",
             "statement": "Favorecer el desarrollo físico personal."},
        ]},
    }
    counts = provenance.annotate(database)
    return database, counts


def test_html_objectives_are_backfilled_with_provenance():
    database, counts = annotated_db()
    objective = database["levels"]["1_medio"]["subjects"]["matematica"][
        "learning_objectives"][0]
    assert objective["provenance"]["source_type"] == SOURCE_HTML
    assert objective["provenance"]["source_url"] == "https://example.test/oa"
    assert objective["provenance"]["retrieved_at"] == RETRIEVED
    assert objective["provenance"]["extraction_method"]
    assert counts["objectives"] == 1


def test_oats_are_backfilled_from_the_jsonapi():
    database, counts = annotated_db()
    oat = database["transversal_objectives"]["1o-6o-basico"][0]
    assert oat["provenance"]["source_type"] == "jsonapi"
    assert oat["curriculum_status"] == STATUS_VIGENTE
    assert counts["oats"] == 1


def test_provenance_is_never_overwritten():
    """An engine that recorded its own provenance keeps it."""
    database = empty_db()
    epja.merge(database, sections("epja_filosofia_media"), RETRIEVED)
    provenance.annotate(database)
    objective = database["levels"]["epja_media"]["subjects"]["filosofia"][
        "learning_objectives"][0]
    assert objective["provenance"]["source_type"] == SOURCE_BASE_PDF
    assert objective["provenance"]["source_page"] == 1


def test_prioritized_gains_the_programme_and_period_it_records():
    """`prioritized: true` is not a present-tense property and must not read as one."""
    database, counts = annotated_db()
    objective = database["levels"]["1_medio"]["subjects"]["matematica"][
        "learning_objectives"][0]
    assert objective["prioritized"] is True          # kept for compatibility
    assert objective["prioritization"]["period"] == "2023-2025"
    assert objective["prioritization"]["status"] == "historico"
    assert objective["prioritization"]["source_url"]
    assert counts["prioritized"] == 1


def test_a_status_the_site_states_beats_the_one_inherited_from_the_base():
    """"Inglés (Propuesta)" is labelled a proposal by the ministry itself."""
    database, counts = annotated_db(
        subject_name="Inglés (Propuesta)",
        source_url="https://www.curriculumnacional.cl/curriculum/"
                   "7o-basico-2o-medio/ingles-propuesta/1-medio",
    )
    subject = database["levels"]["1_medio"]["subjects"]["matematica"]
    assert subject["curriculum_status"] == STATUS_PROPUESTA
    assert subject["status_source"]["note"]
    assert counts["subject_status_overrides"] == 1


def test_an_unbacked_base_stays_unknown_rather_than_vigente():
    """A live page is not evidence that a curriculum is legally in force."""
    result = provenance.status_for_base("una-base-sin-fuente-verificada")
    assert result["curriculum_status"] == STATUS_DESCONOCIDO
    assert result["status_source"] is None


def test_every_declared_base_status_names_its_source():
    for base_slug, entry in provenance.BASE_STATUS.items():
        assert entry["source_url"].startswith("https://"), base_slug
        assert entry["note"], base_slug
        assert entry["verified_on"], base_slug
