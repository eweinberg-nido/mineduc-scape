from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def matematica_1_medio():
    return load_fixture("matematica_1_medio.html")


@pytest.fixture
def especialidad_tp():
    return load_fixture("especialidad_administracion_3_medio_tp.html")


@pytest.fixture
def parvularia():
    return load_fixture("comunicacion_integral_nm.html")


@pytest.fixture
def epja():
    return load_fixture("epja_artes_visuales_n1_media.html")


def load_bases_page(name: str) -> str:
    """The extracted text of one Bases Curriculares page, captured from the real PDF."""
    import json

    payload = json.loads(
        (FIXTURES / "bases_pages" / f"{name}.json").read_text(encoding="utf-8")
    )
    return payload["text"]


@pytest.fixture
def bases_page():
    return load_bases_page
