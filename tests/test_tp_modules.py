"""Técnico-Profesional módulo extraction tests.

Same fixture approach as the indicator tests: the block layout of two real
pages of the Especialidad Electricidad Programa - a módulo's first page and a
continuation page - drive the parser directly, with no PDF involved.
"""

import json
from pathlib import Path

from mineduc_scraper.tp_modules import (
    Module,
    TpReport,
    _link_objectives,
    consume_page,
    coverage,
    module_from_text,
)

PAGES = Path(__file__).parent / "fixtures" / "pdf_pages"


def load_page(name: str):
    payload = json.loads((PAGES / f"{name}.json").read_text(encoding="utf-8"))
    blocks = [tuple(block) + (index, 0) for index, block in enumerate(payload["blocks"])]
    return blocks, payload["text"]


def test_module_header_is_parsed():
    _blocks, text = load_page("tp_module_first_page")
    module = module_from_text(text)
    assert module is not None
    assert module.number == 1
    assert module.name == "INSTALACIÓN DE MOTORES ELÉCTRICOS Y EQUIPOS DE CALEFACCIÓN"
    assert module.hours == 152
    assert module.grade == "Tercero medio"


def test_module_header_handles_a_name_that_wraps():
    module = module_from_text(
        "MóDULO 4 · MANTENIMIENTO DE MÁQUINAS, EQUIPOS\nY SISTEMAS ELÉCTRICOS\n"
        "228 Horas Cuarto Medio"
    )
    assert module.number == 4
    assert module.name == "MANTENIMIENTO DE MÁQUINAS, EQUIPOS Y SISTEMAS ELÉCTRICOS"
    assert module.hours == 228
    assert module.grade == "Cuarto medio"


def test_module_header_absent():
    assert module_from_text("Bibliografía recomendada") is None


def test_first_page_yields_objectives_learnings_and_criteria():
    blocks, text = load_page("tp_module_first_page")
    module = module_from_text(text)
    consume_page(module, blocks)

    # the speciality objective the módulo addresses, read with its statement
    assert module.objective_codes == ["4"]
    assert module.objective_statements["4"].startswith("Ejecutar instalaciones de calefacción")

    # "1." is an Aprendizaje Esperado, "1.1"/"1.2" its Criterios de Evaluación
    assert sorted(module.expected_learnings) == [1]
    learning = module.expected_learnings[1]
    assert learning.statement.startswith("Instala motores eléctricos en baja tensión")
    assert len(learning.criteria) == 4
    assert learning.criteria[0].startswith("1.1 Analiza manuales y diagramas técnicos")
    # OAG letters sit in the third column
    assert learning.generic_objectives == ["B", "I", "K"]


def test_continuation_page_extends_the_open_learning():
    module = Module(number=1)
    first_blocks, text = load_page("tp_module_first_page")
    open_learning = consume_page(module, first_blocks)
    assert open_learning == 1

    more_blocks, _text = load_page("tp_module_continuation")
    consume_page(module, more_blocks, open_learning)

    learning = module.expected_learnings[1]
    assert len(learning.criteria) == 8
    assert any(c.startswith("1.8 Elabora un informe técnico") for c in learning.criteria)
    # criteria stay ordered as printed
    assert [c.split()[0] for c in learning.criteria] == [
        f"1.{n}" for n in range(1, 9)
    ]


def test_criteria_are_deduplicated():
    module = Module(number=1)
    blocks, text = load_page("tp_module_first_page")
    consume_page(module, blocks)
    before = len(module.expected_learnings[1].criteria)
    consume_page(module, blocks)
    assert len(module.expected_learnings[1].criteria) == before


def test_module_as_dict_shape():
    blocks, text = load_page("tp_module_first_page")
    module = module_from_text(text)
    consume_page(module, blocks)
    payload = module.as_dict()
    assert payload["module_number"] == 1
    assert payload["objective_codes"] == ["OA 4"]
    assert payload["expected_learnings"][0]["number"] == 1
    assert payload["expected_learnings"][0]["criteria"]


def test_objectives_are_linked_by_statement():
    blocks, text = load_page("tp_module_first_page")
    module = module_from_text(text)
    consume_page(module, blocks)

    subject = {
        "subject_id": "especialidad_electricidad",
        "learning_objectives": [
            {"oa_id": "CL_ELC_3M_OA01", "code": "OA 1.", "category": "conocimiento",
             "statement": "Leer y utilizar especificaciones técnicas, planos y diagramas."},
            {"oa_id": "CL_ELC_3M_OA04", "code": "OA 4.", "category": "conocimiento",
             "statement": "Ejecutar instalaciones de calefacción y fuerza motriz en baja "
                          "tensión, con un máximo de 10 kW de potencia."},
        ],
    }
    assert _link_objectives(subject, module, 0.55) == ["CL_ELC_3M_OA04"]


def test_objective_link_is_dropped_when_nothing_matches():
    module = Module(number=9)
    module.objective_codes = ["1"]
    module.objective_statements["1"] = "Un objetivo que no existe en esta especialidad."
    subject = {
        "subject_id": "x",
        "learning_objectives": [
            {"oa_id": "A", "code": "OA 1.", "category": "conocimiento",
             "statement": "Leer y utilizar especificaciones técnicas y planos eléctricos."}
        ],
    }
    assert _link_objectives(subject, module, 0.55) == []


def test_coverage_counts_only_tp_subjects():
    database = {
        "levels": {
            "3_medio": {
                "subjects": {
                    "especialidad_x": {
                        "track": "plan_diferenciado_tp",
                        "modules": [
                            {"module_number": 1, "module_name": "M",
                             "expected_learnings": [
                                 {"number": 1, "statement": "s", "criteria": ["a", "b"]}
                             ]}
                        ],
                    },
                    "matematica": {"track": "plan_comun", "learning_objectives": []},
                }
            }
        }
    }
    stats = coverage(database)
    assert stats == {
        "tp_subjects": 1,
        "tp_subjects_with_modules": 1,
        "modules": 1,
        "expected_learnings": 1,
        "criteria": 2,
    }


def test_report_defaults():
    report = TpReport()
    assert report.modules == 0 and report.criteria == 0 and report.pdfs_failed == []


def test_grade_to_level_mapping_covers_both_years():
    from mineduc_scraper.tp_modules import GRADE_TO_LEVEL

    assert GRADE_TO_LEVEL["tercero medio"] == "3_medio"
    assert GRADE_TO_LEVEL["cuarto medio"] == "4_medio"


def test_modules_are_keyed_by_grade_and_name_not_number():
    """A speciality with menciones restarts numbering, so keys must not collide."""
    from mineduc_scraper.tp_modules import TpProgramme

    common = Module(number=1, name="UTILIZACIÓN DE INFORMACIÓN CONTABLE",
                    grade="Tercero medio")
    rrhh = Module(number=1, name="LEGISLACIÓN LABORAL", grade="Cuarto medio")
    logistica = Module(number=1, name="operaciones de almacenamiento",
                       grade="Cuarto medio")
    programme = TpProgramme(pdf_url="p.pdf")
    for module in (common, rrhh, logistica):
        programme.modules[TpProgramme.key(module)] = module
    assert len(programme.modules) == 3
    # Tercero medio módulos come first, then Cuarto medio, then by number/name
    assert [m.name for m in programme.ordered()] == [
        "UTILIZACIÓN DE INFORMACIÓN CONTABLE",
        "LEGISLACIÓN LABORAL",
        "operaciones de almacenamiento",
    ]


def test_expected_learning_without_a_period_is_read():
    """Some Programas print the AE number bare: "4 Analiza funcionamiento ..."."""
    module = Module(number=1)
    blocks = [
        (80.5, 63.5, 500.0, 75.0,
         "Aprendizajes Esperados Criterios de Evaluación Objetivos de Aprendizaje Genéricos", 0, 0),
        (78.5, 93.6, 190.0, 140.0,
         "4 Analiza funcionamiento de equipos electrónicos y diagnostica fallas.", 1, 0),
        (199.6, 94.1, 440.0, 140.0,
         "4.1 Diagnostica fallas en equipos electrónicos según el síntoma presentado.", 2, 0),
        (451.3, 113.2, 460.0, 125.0, "b", 3, 0),
    ]
    consume_page(module, blocks)
    learning = module.expected_learnings[4]
    assert learning.statement.startswith("Analiza funcionamiento de equipos")
    assert len(learning.criteria) == 1
    # OAG letters are normalised to upper case whatever the Programa prints
    assert learning.generic_objectives == ["B"]


def test_bare_numbers_that_are_page_furniture_are_ignored():
    module = Module(number=1)
    blocks = [
        (80.0, 60.0, 500.0, 72.0,
         "Aprendizajes Esperados Criterios de Evaluación", 0, 0),
        (78.0, 90.0, 190.0, 102.0, "4 horas pedagógicas semanales", 1, 0),
    ]
    consume_page(module, blocks)
    assert module.expected_learnings == {}


def test_expected_learning_split_across_two_cells():
    """Some Programas put the AE number in one cell and its text in the next."""
    module = Module(number=7)
    blocks = [
        (77.3, 63.5, 500.0, 75.0,
         "Aprendizajes Esperados Criterios de Evaluación Objetivos de Aprendizaje Genéricos", 0, 0),
        (76.3, 94.0, 90.0, 105.0, "3.", 1, 0),
        (104.7, 94.6, 190.0, 150.0,
         "Aplica técnicas de limpieza y protección de superficies metálicas.", 2, 0),
        (199.6, 94.5, 440.0, 150.0,
         "3.1 Prepara las máquinas, los equipos y los elementos de protección.", 3, 0),
        (451.0, 134.5, 470.0, 146.0, "B C H", 4, 0),
    ]
    consume_page(module, blocks)
    learning = module.expected_learnings[3]
    assert learning.statement == (
        "Aplica técnicas de limpieza y protección de superficies metálicas."
    )
    assert len(learning.criteria) == 1


def test_a_lone_number_cell_off_baseline_is_ignored():
    """A rotated page tab ("7." down the edge) must not open an empty AE."""
    module = Module(number=1)
    blocks = [
        (77.0, 63.0, 500.0, 75.0, "Aprendizajes Esperados Criterios de Evaluación", 0, 0),
        (593.3, 247.1, 605.0, 260.0, "7.", 1, 0),          # page tab, alone
        (199.0, 94.0, 440.0, 150.0,
         "3.1 Prepara las máquinas y los equipos necesarios.", 2, 0),
    ]
    consume_page(module, blocks)
    assert 7 not in module.expected_learnings
    assert len(module.expected_learnings[3].criteria) == 1


def test_doubled_number_typo_is_tolerated():
    """The Programas contain "5. 5. Empaqueta ..." more than once."""
    module = Module(number=5)
    blocks = [
        (63.1, 63.5, 500.0, 75.0, "Aprendizajes Esperados Criterios de Evaluación", 0, 0),
        (62.4, 400.3, 190.0, 450.0,
         "5. 5. Empaqueta artículos textiles para el hogar y prendas de vestir.", 1, 0),
    ]
    consume_page(module, blocks)
    assert module.expected_learnings[5].statement == (
        "Empaqueta artículos textiles para el hogar y prendas de vestir."
    )


def test_page_footer_is_not_read_as_an_expected_learning():
    module = Module(number=5)
    blocks = [
        (63.1, 63.5, 500.0, 75.0, "Aprendizajes Esperados Criterios de Evaluación", 0, 0),
        (56.7, 745.6, 400.0, 758.0,
         "76 Especialidad VESTUARIO Y CONFECCIÓN TEXTIL | 3° y 4º medio | Programa de Estudio",
         1, 0),
    ]
    consume_page(module, blocks)
    assert module.expected_learnings == {}
