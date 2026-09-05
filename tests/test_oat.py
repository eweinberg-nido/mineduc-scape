"""Transversal objectives: verification, and the pagination bug that hid a truncation."""

from __future__ import annotations

import pytest

from mineduc_scraper import oat


def make_oat(oat_id, code="OAT 1", dimension="Dimensión física",
             statement="Favorecer el desarrollo físico personal."):
    return {"oat_id": oat_id, "oat_number": 1, "code": code,
            "dimension": dimension, "statement": statement,
            "curriculum_base": "1o-6o-basico"}


def test_identical_sets_verify_clean():
    live = {"1o-6o-basico": [make_oat("A"), make_oat("B", code="OAT 2")]}
    report = oat.verify({"1o-6o-basico": [make_oat("A"), make_oat("B", code="OAT 2")]},
                        live)
    assert report["differences"] == []
    assert report["missing_from_dataset"] == []
    assert report["not_in_source"] == []
    assert report["records_compared"] == 2


@pytest.mark.parametrize("field,value", [
    ("statement", "Un enunciado distinto."),
    ("dimension", "Dimensión cognitiva"),
    ("code", "OAT 99"),
])
def test_a_field_that_drifted_is_reported_not_resolved(field, value):
    """Two readings of one official source disagreeing is a finding."""
    stored = {"1o-6o-basico": [{**make_oat("A"), field: value}]}
    report = oat.verify(stored, {"1o-6o-basico": [make_oat("A")]})
    assert report["differences"] == [f"1o-6o-basico/A: {field} differs"]
    # The stored record is untouched.
    assert stored["1o-6o-basico"][0][field] == value


def test_records_missing_from_the_dataset_are_reported():
    report = oat.verify({"1o-6o-basico": []}, {"1o-6o-basico": [make_oat("A")]})
    assert report["missing_from_dataset"] == ["1o-6o-basico/A (OAT 1)"]


def test_records_no_longer_in_the_source_are_reported():
    report = oat.verify({"1o-6o-basico": [make_oat("A"), make_oat("B")]},
                        {"1o-6o-basico": [make_oat("A")]})
    assert report["not_in_source"] == ["1o-6o-basico/B"]


def test_a_whole_base_that_vanished_from_the_source_is_reported():
    report = oat.verify({"3o-4o-medio-tecnico-profesional": [make_oat("A")]},
                        {"1o-6o-basico": [make_oat("B")]})
    assert "3o-4o-medio-tecnico-profesional/A" in report["not_in_source"]


def test_a_count_that_disagrees_with_the_landing_page_is_reported():
    report = oat.verify({}, {"1o-6o-basico": [make_oat("A")]})
    assert any("1 collected, 32 expected" in m for m in report["count_mismatches"])


def test_every_base_without_oats_has_a_stated_reason():
    """"No OATs here" must be an answer with a reason, not a hole in a table."""
    report = oat.verify({}, {})
    assert set(report["bases_without_oats"]) == {
        "educacion-parvularia", "3o-4o-medio",
        "bases-curriculares-educacion-personas-jovenes-adultas-epja",
    }
    for reason in report["bases_without_oats"].values():
        assert len(reason.split()) > 10


def test_jsonapi_pagination_links_are_forced_back_onto_https():
    """The site emits `links.next.href` as http://, and refuses plain HTTP.

    Following the link verbatim fails on the *second* page of every collection,
    which reads as a flaky network rather than as a fetch that stopped at 50
    records — so it would silently cap the OAT set and every other collection.
    """
    assert oat._https("http://www.curriculumnacional.cl/jsonapi/paragraph/oat?x=1") == (
        "https://www.curriculumnacional.cl/jsonapi/paragraph/oat?x=1"
    )
    assert oat._https("https://already.secure/x") == "https://already.secure/x"
    assert oat._https(None) is None


def test_collection_follows_every_page_and_stops_on_a_self_reference():
    pages = {
        "https://www.curriculumnacional.cl/jsonapi/paragraph/oat?page%5Blimit%5D=50": {
            "data": [{"id": "1"}],
            # The site returns this over plain http.
            "links": {"next": {"href": "http://www.curriculumnacional.cl/p2"}},
        },
        "https://www.curriculumnacional.cl/p2": {
            "data": [{"id": "2"}],
            "links": {"next": {"href": "https://www.curriculumnacional.cl/p2"}},
        },
    }

    class Client:
        def __init__(self):
            self.seen = []

        def get_json(self, url):
            self.seen.append(url)
            return pages[url]

    client = Client()
    items = oat._collection(client, "paragraph/oat")
    assert [item["id"] for item in items] == ["1", "2"]
    assert client.seen[1] == "https://www.curriculumnacional.cl/p2"
