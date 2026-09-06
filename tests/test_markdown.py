"""The Markdown export, and the TP sector grouping it relies on.

This output exists for tools that take Markdown rather than JSON and cap a
notebook at 50 sources. Two properties therefore matter more than anything
about formatting: the file count has to stay inside that budget, and nothing
may be lost on the way out. The dataset is the only copy of this text that has
been verified against the ministry's sources, so a rendering step that drops
5 024 evaluation criteria, or flattens a bulleted objective onto one line, has
produced something that reads as complete and is not.
"""

from __future__ import annotations

import pytest

from mineduc_scraper import sectors
from mineduc_scraper.markdown import (
    AREA_EPJA,
    AREA_GENERAL,
    AREA_HC,
    AREA_PARVULARIA,
    AREA_TP,
    canonical_subject_name,
    collect,
    group_key,
    render_document,
    render_module,
    render_objective,
    render_subject,
    statement_markdown,
    write_markdown,
)


# --------------------------------------------------------------------------- #
# Nothing may be lost in the rendering
# --------------------------------------------------------------------------- #
def test_a_stem_and_its_list_stay_a_list():
    """Joining these lines truncates the objective at its colon.

    518 objectives in the dataset are a stem introducing a list. Collapsing the
    newlines is the single easiest way to ship something that looks complete and
    is not, which is why the integrity audit flags exactly this shape.
    """
    rendered = statement_markdown(
        "Demostrar que comprenden las fracciones propias:\n"
        "- representándolas de manera concreta\n"
        "- creando grupos de fracciones equivalentes"
    )
    assert rendered.split("\n") == [
        "Demostrar que comprenden las fracciones propias:",
        "- representándolas de manera concreta",
        "- creando grupos de fracciones equivalentes",
    ]


def test_a_stored_bullet_does_not_get_a_second_marker():
    assert "- - " not in statement_markdown("Stem:\n- uno\n- dos")


def test_a_single_line_statement_is_left_alone():
    assert statement_markdown("Calcular operaciones.") == "Calcular operaciones."


def test_tp_criteria_are_written_from_the_field_the_schema_defines():
    """`criteria` — reading any other name silently drops all 5 024 of them."""
    rendered = render_module({
        "module_number": 1, "module_name": "INSTALACIÓN DE MOTORES", "hours": 152,
        "grade": "Tercero medio", "objective_codes": ["OA 4"],
        "expected_learnings": [{
            "number": 1, "statement": "Instala motores eléctricos.",
            "criteria": ["1.1 Analiza manuales.", "1.2 Selecciona herramientas."],
            "generic_objectives": ["B", "I"],
        }],
    })
    assert "Módulo 1: INSTALACIÓN DE MOTORES" in rendered
    assert "Criterios de evaluación (2)" in rendered
    assert "- 1.1 Analiza manuales." in rendered
    assert "- 1.2 Selecciona herramientas." in rendered
    assert "B, I" in rendered


def test_indicators_are_written_with_their_scope():
    rendered = render_objective({
        "code": "MA1M OA 01", "category": "conocimiento", "statement": "Calcular.",
        "indicators": ["Identifican el tipo de número."], "indicators_scope": "unit",
    })
    assert "Indicadores de evaluación (1)" in rendered
    assert "evaluación conjunta" in rendered


# --------------------------------------------------------------------------- #
# Claims the documents must not overstate
# --------------------------------------------------------------------------- #
def test_status_is_printed_as_its_label_and_never_defaulted():
    """A renderer that defaults an unknown status to "Vigente" asserts the one
    thing this dataset is built not to assert."""
    assert "**Estado del currículum:** Propuesta" in render_objective({
        "code": "EN01 OA 01", "category": "conocimiento", "statement": "Participar.",
        "curriculum_status": "propuesta",
    })
    assert "Estado del currículum" not in render_objective({
        "code": "X", "category": "conocimiento", "statement": "Algo.",
    })


def test_prioritization_is_printed_with_its_period():
    rendered = render_objective({
        "code": "MA1M OA 01", "category": "conocimiento", "statement": "Calcular.",
        "prioritized": True,
        "prioritization": {"programme": "Priorización Curricular",
                           "period": "2023-2025", "status": "historico"},
    })
    assert "Priorización Curricular 2023-2025" in rendered
    assert "histórico" in rendered


def test_a_correction_is_shown_with_the_text_it_replaced():
    rendered = render_objective({
        "code": "OA 04 CES SC", "category": "conocimiento",
        "statement": "Explorar utensilios domésticos.",
        "correction": {
            "original_value": "Manifestar interés por canciones.",
            "explanation": "El sitio publica el enunciado de OA 03 bajo ambos códigos.",
            "authoritative_source_url": "https://example.test/bases.pdf",
            "authoritative_source_page": 93,
        },
    })
    assert "Manifestar interés por canciones." in rendered
    assert "p. 93" in rendered


def test_every_objective_carries_its_source():
    rendered = render_objective({
        "code": "OA 1", "category": "conocimiento", "statement": "Analizar.",
        "provenance": {"source_type": "base_curricular_pdf",
                       "source_document": "Bases Curriculares EPJA 2024",
                       "source_page": 137,
                       "source_url": "https://example.test/bases.pdf"},
    })
    assert "Bases Curriculares (PDF)" in rendered
    assert "Bases Curriculares EPJA 2024" in rendered
    assert "p. 137" in rendered


def test_a_subject_with_no_objectives_says_why():
    """Religión must read as a documented property of the source."""
    rendered = render_subject("1° Básico", {
        "subject_name": "Religión", "track": "plan_comun",
        "learning_objectives": [],
        "no_objectives_reason": {
            "explanation": "Se rige por el Decreto N° 924.",
            "source_url": "https://example.test/924",
        },
    })
    assert "Sin objetivos de aprendizaje publicados" in rendered
    assert "Decreto N° 924" in rendered
    assert "https://example.test/924" in rendered


def test_a_subject_whose_objectives_live_elsewhere_points_at_that_level():
    rendered = render_subject("EPJA Nivel 1 Media", {
        "subject_name": "Filosofía", "track": "plan_comun",
        "learning_objectives": [], "objectives_in_level": "epja_media",
    })
    assert "epja_media" in rendered
    assert "nivel combinado" in rendered


# --------------------------------------------------------------------------- #
# Grouping: the 50-source budget
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("printed,expected", [
    ("Matemática 3º Medio", "Matemática"),
    ("Inglés 4º Medio", "Inglés"),
    ("Educación Ciudadana 3° Medio", "Educación Ciudadana"),
    ("Educación Física y Salud 1", "Educación Física y Salud"),
    ("Lengua y Literatura", "Lengua y Literatura"),
    ("Historia, Geografía y Ciencias Sociales", "Historia, Geografía y Ciencias Sociales"),
])
def test_grade_suffixed_names_fold_onto_their_subject(printed, expected):
    """A mechanical read of the published name, not a judgement about subjects."""
    assert canonical_subject_name(printed) == expected


def test_plan_comun_gets_one_file_per_subject():
    area, slug, _title = group_key("3_medio", {
        "subject_name": "Matemática 3º Medio", "track": "plan_comun",
    })
    assert area == AREA_GENERAL
    assert slug == "matematica"


def test_tp_is_grouped_by_the_ministrys_own_sector():
    area, slug, title = group_key("3_medio", {
        "subject_name": "Especialidad Contabilidad",
        "track": "plan_diferenciado_tp", "tp_sector": "Administración",
    })
    assert area == AREA_TP
    assert slug == "TP_administracion"
    assert "Administración" in title


def test_an_untagged_speciality_gets_its_own_file_rather_than_being_absorbed():
    _area, slug, _title = group_key("3_medio", {
        "subject_name": "Especialidad Nueva", "track": "plan_diferenciado_tp",
    })
    assert slug == "TP_especialidad_nueva"


@pytest.mark.parametrize("level_id,subject,area,slug", [
    ("epja_media", {"subject_name": "Filosofía", "track": "plan_comun"},
     AREA_EPJA, "EPJA"),
    ("nivel_medio", {"subject_name": "Comunicación Integral", "track": "plan_comun",
                     "curriculum_base": "educacion-parvularia"},
     AREA_PARVULARIA, "Educacion_Parvularia"),
    ("3_medio", {"subject_name": "Geometría 3D", "track": "plan_diferenciado_hc"},
     AREA_HC, "Formacion_Diferenciada_HC"),
])
def test_the_remaining_areas_each_get_one_file(level_id, subject, area, slug):
    got_area, got_slug, _title = group_key(level_id, subject)
    assert (got_area, got_slug) == (area, slug)


def test_documents_order_their_subjects_by_curriculum_level():
    database = {"metadata": {}, "levels": {
        "4_medio": {"level_id": "4_medio", "level_name": "4° Medio", "subjects": {
            "m": {"subject_name": "Matemática", "track": "plan_comun",
                  "learning_objectives": []}}},
        "1_basico": {"level_id": "1_basico", "level_name": "1° Básico", "subjects": {
            "m": {"subject_name": "Matemática", "track": "plan_comun",
                  "learning_objectives": []}}},
    }}
    documents = collect(database)
    assert [e["level_id"] for e in documents["matematica"]["entries"]] == [
        "1_basico", "4_medio",
    ]


def test_the_whole_export_stays_inside_the_50_source_budget(tmp_path):
    """The constraint the format exists to satisfy."""
    database = {"metadata": {"built_at": "2026-09-06T00:00:00+00:00"}, "levels": {}}
    for index in range(60):
        database["levels"][f"{index}_x"] = {
            "level_id": f"{index}_x", "level_name": f"Nivel {index}",
            "subjects": {"m": {"subject_name": "Matemática", "track": "plan_comun",
                               "learning_objectives": []}},
        }
    paths = write_markdown(database, tmp_path)
    # 60 levels of one subject collapse into one document, plus the index.
    assert len(paths) == 2
    assert (tmp_path / "matematica.md").exists()
    assert (tmp_path / "00_indice.md").exists()


def test_the_document_header_reports_what_it_contains(tmp_path):
    database = {"metadata": {"built_at": "2026-09-06T00:00:00+00:00",
                             "scraped_at": "2026-09-04T00:00:00+00:00"},
                "levels": {"1_basico": {
                    "level_id": "1_basico", "level_name": "1° Básico", "subjects": {
                        "m": {"subject_name": "Matemática", "track": "plan_comun",
                              "learning_objectives": [
                                  {"code": "MA01 OA 01", "category": "conocimiento",
                                   "statement": "Contar.", "indicators": ["Cuentan."]}]}}}}}
    document = collect(database)["matematica"]
    rendered = render_document(document, database["metadata"])
    assert rendered.startswith("# Matemática")
    assert "1 objetivos de aprendizaje · 1 indicadores" in rendered
    assert "2026-09-06" in rendered


# --------------------------------------------------------------------------- #
# The sector mapping, read from the ministry's own index
# --------------------------------------------------------------------------- #
INDEX_HTML = """
<body>
  <h2>Administración</h2>
  <a href="/curriculum/3o-4o-medio-tecnico-profesional/especialidad-administracion/3-medio-tp">A</a>
  <a href="/curriculum/3o-4o-medio-tecnico-profesional/especialidad-contabilidad/3-medio-tp">C</a>
  <h2>Minero</h2>
  <a href="/curriculum/3o-4o-medio-tecnico-profesional/especialidad-mineria/3-medio-tp">M</a>
  <h2>Curriculum por asignatura</h2>
  <a href="/curriculum/1o-6o-basico/matematica/1-basico">Matemática</a>
</body>
"""


def test_sectors_are_read_from_the_index_rather_than_hardcoded():
    found = sectors.parse_sectors(INDEX_HTML)
    assert found == {
        "especialidad-administracion": "Administración",
        "especialidad-contabilidad": "Administración",
        "especialidad-mineria": "Minero",
    }


def test_links_after_the_last_sector_are_not_swept_into_it():
    """The index continues past the sectors with its own subject listings."""
    assert "matematica" not in sectors.parse_sectors(INDEX_HTML)


def test_annotate_tags_tp_subjects_and_reports_the_rest():
    database = {"levels": {"3_medio": {"level_id": "3_medio", "subjects": {
        "a": {"subject_id": "a", "track": "plan_diferenciado_tp",
              "source_url": "https://x/curriculum/b/especialidad-administracion/3-medio-tp"},
        "z": {"subject_id": "z", "track": "plan_diferenciado_tp",
              "source_url": "https://x/curriculum/b/especialidad-desconocida/3-medio-tp"},
        "m": {"subject_id": "m", "track": "plan_comun",
              "source_url": "https://x/curriculum/b/matematica/3-medio-fg"},
    }}}}
    report = sectors.annotate(database, {"especialidad-administracion": "Administración"})
    subjects = database["levels"]["3_medio"]["subjects"]
    assert subjects["a"]["tp_sector"] == "Administración"
    assert "tp_sector" not in subjects["z"]
    assert "tp_sector" not in subjects["m"], "only TP subjects have a sector"
    assert report["subjects_tagged"] == 1
    assert report["subjects_unmapped"] == ["3_medio/z"]
