"""End-to-end tests over the fixtures: build -> validate -> export, no network."""

import json
import sqlite3
from pathlib import Path

from mineduc_scraper.build import _subject_record, refresh_totals
from mineduc_scraper.export import _flatten_statement, split_by_level, to_slim, write_sqlite
from mineduc_scraper.extract import parse_subject_page
from mineduc_scraper.taxonomy import level_for
from mineduc_scraper.validate import audit, validate, validate_schema

PAGES = [
    (
        "matematica_1_medio.html",
        "https://www.curriculumnacional.cl/curriculum/7o-basico-2o-medio/matematica/1-medio",
    ),
    (
        "especialidad_administracion_3_medio_tp.html",
        "https://www.curriculumnacional.cl/curriculum/3o-4o-medio-tecnico-profesional/"
        "especialidad-administracion/3-medio-tp",
    ),
    (
        "comunicacion_integral_nm.html",
        "https://www.curriculumnacional.cl/curriculum/educacion-parvularia/"
        "comunicacion-integral/nm-nivel-medio",
    ),
]


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _database():
    levels = {}
    for name, url in PAGES:
        page = parse_subject_page(load_fixture(name), url)
        level = level_for(page.grade_slug)
        bucket = levels.setdefault(
            level.level_id,
            {"level_id": level.level_id, "level_name": level.level_name, "subjects": {}},
        )
        subject = _subject_record(page, level.token)
        bucket["subjects"][subject["subject_id"]] = subject

    database = {
        "metadata": {
            "scraped_at": "2026-01-01T00:00:00+00:00",
            "source_url": "https://www.curriculumnacional.cl",
            "schema_version": "1.0.0",
            "dataset_variant": "full",
            "total_oas": 0,
        },
        "levels": levels,
        "transversal_objectives": {},
    }
    return refresh_totals(database)


def test_built_database_matches_the_schema():
    assert validate_schema(_database()) == []


def test_audit_reports_no_errors():
    errors, _warnings, report = audit(_database())
    assert errors == []
    assert report["total_objectives"] == report["unique_oa_ids"]
    assert report["by_category"]["conocimiento"] > 0


def test_totals_are_recomputed_from_content():
    database = _database()
    counted = sum(
        len(subject["learning_objectives"])
        for level in database["levels"].values()
        for subject in level["subjects"].values()
    )
    assert database["metadata"]["total_oas"] == counted


def test_audit_flags_an_empty_statement():
    database = _database()
    subject = next(iter(database["levels"]["1_medio"]["subjects"].values()))
    subject["learning_objectives"][0]["statement"] = "   "
    errors, _warnings, _report = audit(database)
    assert any("empty statement" in e for e in errors)


def test_audit_flags_a_stale_counter():
    database = _database()
    database["metadata"]["total_oas"] += 1
    errors, _warnings, _report = audit(database)
    assert any("total_oas" in e for e in errors)


def test_audit_flags_duplicate_ids():
    database = _database()
    subject = next(iter(database["levels"]["1_medio"]["subjects"].values()))
    subject["learning_objectives"][1]["oa_id"] = subject["learning_objectives"][0]["oa_id"]
    errors, _warnings, _report = audit(database)
    assert any("duplicate oa_id" in e for e in errors)


def test_slim_export_is_valid_and_smaller():
    database = _database()
    slim = to_slim(database)
    assert validate_schema(slim) == []
    assert slim["metadata"]["dataset_variant"] == "slim"
    assert slim["metadata"]["total_oas"] == database["metadata"]["total_oas"]
    assert len(json.dumps(slim)) < len(json.dumps(database))
    objective = slim["levels"]["1_medio"]["subjects"]["matematica"]["learning_objectives"][1]
    assert "\n" not in objective["statement"]
    assert "keywords" not in objective


def test_flatten_statement_keeps_the_bullets_readable():
    flat = _flatten_statement("Mostrar que comprenden:\n- Uno.\n- Dos.")
    assert flat == "Mostrar que comprenden: Uno; Dos."
    assert _flatten_statement("Una sola linea.") == "Una sola linea."
    assert _flatten_statement("") == ""


def test_split_by_level_writes_one_file_per_level(tmp_path):
    database = _database()
    files = split_by_level(database, tmp_path)
    names = {f.name for f in files}
    assert "index.json" in names
    assert len(files) == len(database["levels"]) + 1
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "levels" not in index  # it is a manifest, not a dataset
    for level_id, entry in index["files"].items():
        payload = json.loads((tmp_path / entry["file"]).read_text(encoding="utf-8"))
        assert validate_schema(payload) == []
        assert list(payload["levels"]) == [level_id]


def test_validate_rejects_the_split_manifest_cleanly(tmp_path):
    """Pointing `validate` at index.json must explain itself, not traceback."""
    split_by_level(_database(), tmp_path)
    manifest = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    errors, _warnings, report = validate(manifest)
    assert any("does not look like a curriculum dataset" in e for e in errors)
    assert report["total_objectives"] == 0


def test_validate_rejects_malformed_input():
    errors, _warnings, _report = validate({"levels": {"1_medio": {"subjects": []}}})
    assert any("expected an object keyed by subject_id" in e for e in errors)
    errors, _warnings, _report = validate([1, 2, 3])
    assert any("expected a JSON object" in e for e in errors)


def test_sqlite_export_is_queryable(tmp_path):
    database = _database()
    path = write_sqlite(database, tmp_path / "curriculum.db")
    connection = sqlite3.connect(path)
    try:
        total = connection.execute("SELECT COUNT(*) FROM objectives").fetchone()[0]
        assert total == database["metadata"]["total_oas"]
        # FTS5 index is diacritic-insensitive
        rows = connection.execute(
            "SELECT o.code FROM objectives_fts f JOIN objectives o USING(oa_id) "
            "WHERE objectives_fts MATCH 'numeros'"
        ).fetchall()
        assert rows
        assert connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "1.0.0"
    finally:
        connection.close()


def test_query_is_accent_insensitive_and_searches_indicators(tmp_path, capsys):
    """`query fotosintesis` must find "fotosíntesis", including in indicators."""
    from mineduc_scraper.cli import main

    database = _database()
    objective = database["levels"]["1_medio"]["subjects"]["matematica"][
        "learning_objectives"
    ][0]
    objective["indicators"] = ["Explican el proceso de fotosíntesis en las plantas."]
    path = tmp_path / "db.json"
    path.write_text(json.dumps(database, ensure_ascii=False), encoding="utf-8")

    assert main(["query", "fotosintesis", "-f", str(path), "--indicators"]) == 0
    output = capsys.readouterr().out
    assert objective["code"] in output
    assert "proceso de fotosíntesis" in output

    assert main(["query", "no-existe-esto", "-f", str(path)]) == 0
    assert "0 match(es)" in capsys.readouterr().out
