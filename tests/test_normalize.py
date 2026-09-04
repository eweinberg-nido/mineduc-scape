"""Canonical id, numbering and keyword tests."""

import pytest

from mineduc_scraper.normalize import (
    canonical_oa_id,
    code_slug,
    extract_keywords,
    objective_number,
    parse_code,
)
from mineduc_scraper.taxonomy import (
    SUBJECT_ABBREV,
    derive_abbrev,
    resolve_level_tokens,
    slug_fingerprint,
    slugify,
    subject_abbrev,
    track_for,
)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("MA1M OA 07", ("OA", "07")),
        ("OA 1.", ("OA", "1")),
        ("MA1M OAH a", ("OAH", "a")),
        ("MA1M OAA E", ("OAA", "E")),
        ("AR-AVAM-3y4-OAC-01", ("OAC", "01")),
        ("LC01 OA LF01", ("OA", "LF01")),
        ("OA 01 LV NM", ("OA", "01")),
        ("sin codigo", (None, None)),
    ],
)
def test_parse_code(code, expected):
    assert parse_code(code) == expected


@pytest.mark.parametrize(
    "code,expected",
    [
        ("MA1M OA 07", 7),
        ("OA 1.", 1),
        ("MA1M OAH a", 1),
        ("MA1M OAA E", 5),
        ("AR-AVAM-3y4-OAC-01", 1),
        ("LC01 OA LF01", 1),
        ("OA 15 CM NT", 15),
    ],
)
def test_objective_number(code, expected):
    assert objective_number(code, fallback=99) == expected


def test_objective_number_falls_back_to_position():
    assert objective_number("codigo raro", fallback=4) == 4


def test_canonical_ids_follow_the_spec_shape():
    assert (
        canonical_oa_id("matematica", "3M", "conocimiento", "MA3M OA 01", 1, "Geometría", "Eje")
        == "CL_MAT_3M_GMTR_OA01"
    )
    # habilidad/actitud groupings stay out of the id; the category token carries them
    assert (
        canonical_oa_id("matematica", "1M", "habilidad", "MA1M OAH a", 1,
                        "Resolver problemas", "Habilidad")
        == "CL_MAT_1M_OAHA"
    )
    # a TP speciality without strands
    assert (
        canonical_oa_id("especialidad-administracion", "3M", "conocimiento", "OA 1.", 1)
        == "CL_ADM_3M_OA01"
    )


def test_canonical_ids_are_deterministic():
    args = ("ciencias-naturales", "1M", "conocimiento", "CN1M OA 02", 2, "Biología", "Eje")
    assert canonical_oa_id(*args) == canonical_oa_id(*args)


def test_letter_groups_survive_in_the_id():
    assert canonical_oa_id(
        "lengua-cultura-pueblos-originarios-ancestrales", "1B", "conocimiento",
        "LC01 OA LF01", 1, "Cosmovisión de los pueblos originarios", "Eje",
    ).endswith("_OALF01")


def test_code_slug_matches_site_urls():
    assert code_slug("MA1M OA 07") == "ma1m-oa-07"
    assert code_slug("AR-AVAM-3y4-OAC-01") == "ar-avam-3y4-oac-01"


def test_keywords_lead_with_the_cognitive_verb():
    keywords = extract_keywords(
        "Calcular operaciones con números racionales en forma simbólica."
    )
    assert keywords[0] == "calcular"
    assert "números" in keywords
    # stopwords and boilerplate are dropped
    assert "con" not in keywords
    assert "forma" not in keywords


def test_keywords_are_deduplicated_ignoring_accents():
    keywords = extract_keywords("Analizar analisis análisis de datos")
    assert keywords.count("analisis") + keywords.count("análisis") == 1


def test_keywords_are_capped():
    long_statement = " ".join(f"palabra{i}" for i in range(50))
    assert len(extract_keywords(long_statement)) == 12


def test_track_mapping():
    assert track_for("7o-basico-2o-medio", "1-medio") == "plan_comun"
    assert track_for("3o-4o-medio", "3-medio-fg") == "plan_comun"
    assert track_for("3o-4o-medio", "3-medio-hc") == "plan_diferenciado_hc"
    assert track_for("3o-4o-medio-tecnico-profesional", "3-medio-tp") == "plan_diferenciado_tp"


def test_slug_and_abbrev_helpers():
    assert slugify("Álgebra y funciones") == "algebra_y_funciones"
    assert derive_abbrev("probabilidad-y-estadistica", 4) == "PYE"
    assert derive_abbrev("geometria", 4) == "GMTR"


def test_level_token_resolution():
    assert resolve_level_tokens(["SECUNDARIA"]) == ["7B", "8B", "1M", "2M", "3M", "4M"]
    assert resolve_level_tokens(["1M", "1M", "2M"]) == ["1M", "2M"]
    with pytest.raises(ValueError):
        resolve_level_tokens(["9M"])


def test_frozen_subject_tokens_are_unique():
    """Canonical ids depend on these being injective; a duplicate would collide."""
    assert len(set(SUBJECT_ABBREV.values())) == len(SUBJECT_ABBREV)
    assert all(len(token) >= 3 for token in SUBJECT_ABBREV.values())
    assert all(token.isupper() and token.isalnum() for token in SUBJECT_ABBREV.values())


def test_similar_speciality_slugs_get_distinct_tokens():
    similar = [
        "especialidad-electricidad",
        "especialidad-electronica",
        "especialidad-mecanica-industrial",
        "especialidad-montaje-industrial",
        "especialidad-mecanica-industrial-mencion-mantenimiento-electromecanico",
        "especialidad-mecanica-industrial-mencion-maquinas-herramientas",
        "especialidad-mecanica-industrial-mencion-matriceria",
    ]
    tokens = [subject_abbrev(slug) for slug in similar]
    assert len(set(tokens)) == len(tokens)


def test_unknown_subject_gets_a_stable_fingerprinted_token():
    """A subject added to the site after the map was frozen must not collide."""
    slug = "especialidad-robotica-industrial"
    token = subject_abbrev(slug)
    assert token == subject_abbrev(slug)  # deterministic
    assert token not in set(SUBJECT_ABBREV.values())
    assert slug_fingerprint(slug) != slug_fingerprint(slug + "-mencion-x")
