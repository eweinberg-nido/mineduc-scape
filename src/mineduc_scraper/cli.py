"""Command-line interface for mineduc-scraper."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import SCHEMA_VERSION, __version__
from .bases_pdf import EPJA_BASES_2024, fetch_epja_bases, parse_document
from .build import (
    EPJA_BASES_NOTE,
    INDICATOR_SOURCE_NOTE,
    RELIGION_NOTE,
    TP_MODULE_NOTE,
    build,
    refresh_totals,
)
from .corrections import apply_corrections
from .epja import merge as epja_merge
from .inventory import (
    bases_document_offerings,
    build_report as build_coverage_report,
    discover_site_offerings,
    merge_offerings,
    summarise as summarise_coverage,
)
from .oat import fetch_transversal_objectives, verify as verify_oats
from .provenance import annotate as annotate_provenance
from .religion import annotate as annotate_religion
from .export import split_by_level, to_slim, write_json, write_manifest, write_sqlite
from .http import DEFAULT_DELAY, PoliteClient
from .indicators import MATCH_THRESHOLD, coverage as indicator_coverage, enrich
from .tp_modules import coverage as tp_coverage, enrich as tp_enrich
from .taxonomy import LEVEL_GROUPS, resolve_level_tokens, strip_accents
from .validate import validate

log = logging.getLogger("mineduc_scraper")


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING if verbosity < 0 else (
        logging.INFO if verbosity == 0 else logging.DEBUG
    )
    logging.basicConfig(level=level, format="%(levelname)-7s %(message)s")


def _load(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _report(report: dict, errors: List[str], warnings: List[str]) -> None:
    print("\nCoverage report")
    print("---------------")
    print(f"  levels                 {report['levels']}")
    print(f"  subjects               {report['subjects']}")
    print(f"  objectives             {report['total_objectives']}")
    for category, count in report["by_category"].items():
        print(f"    {category:<20} {count}")
    print(f"  transversal (OAT)      {report['transversal_objectives']}")
    print(f"  with strand/eje        {report['with_strand']}")
    print(f"  priorizacion flagged   {report['prioritized']}")
    print(f"  with indicators        {report['with_indicators']}"
          f"  ({report['indicators']} indicators)")
    if report["tp_modules"]:
        print(f"  TP módulos             {report['tp_modules']}"
              f"  ({report['tp_criteria']} criterios de evaluación)")
    print(f"  distinct official codes {report['distinct_official_codes']}"
          f"  (a 3°/4° Medio OA is listed under both grades)")
    print("\n  objectives per level")
    for level_id, count in report["by_level"].items():
        print(f"    {level_id:<22} {count}")
    reference = report["jsonapi_reference_counts"]
    print("\n  MINEDUC JSON:API reference counts")
    for key, count in reference.items():
        print(f"    {key:<22} {count}")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for warning in warnings:
            print(f"  ! {warning}")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for error in errors[:60]:
            print(f"  x {error}")
        if len(errors) > 60:
            print(f"  ... and {len(errors) - 60} more")
    else:
        print("\nOK: schema valid and all integrity checks passed.")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_scrape(args: argparse.Namespace) -> int:
    try:
        tokens = resolve_level_tokens(args.levels.split(",")) if args.levels else None
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
        database = build(
            client,
            level_tokens=tokens,
            limit=args.limit,
            include_oats=not args.no_oats,
        )
        log.info("http: %d fetched, %d from cache", client.stats["network"], client.stats["cache"])

    output = write_json(database, args.output, indent=None if args.compact else 2)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")

    if args.slim:
        slim = write_json(to_slim(database, with_indicators=args.slim_indicators),
                          args.slim, indent=None if args.compact else 2)
        print(f"wrote {slim} ({slim.stat().st_size / 1_048_576:.2f} MB)")
    if args.sqlite:
        db_path = write_sqlite(database, args.sqlite)
        print(f"wrote {db_path} ({db_path.stat().st_size / 1_048_576:.2f} MB)")
    if args.split:
        files = split_by_level(database, args.split)
        print(f"wrote {len(files)} per-level files in {args.split}")

    errors, warnings, report = validate(database)
    _report(report, errors, warnings)
    return 1 if errors else 0


def cmd_indicators(args: argparse.Namespace) -> int:
    """Download the Programa de Estudio PDFs and attach evaluation indicators."""
    database = _load(args.file)
    with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
        report = enrich(
            client, database,
            pdf_cache=args.pdf_cache,
            limit=args.limit,
            threshold=args.threshold,
        )
    stats = indicator_coverage(database)
    database.setdefault("metadata", {})["indicators"] = {
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Programas de Estudio (PDF) publicados en curriculumnacional.cl",
        "pdfs_read": report.pdfs_read,
        "pdfs_failed": report.pdfs_failed,
        "objectives_with_indicators": stats["objectives_with_indicators"],
        "total_indicators": stats["indicators"],
        "rows_renumbered": report.renumbered_rows,
        "rows_joint": report.joint_rows,
        "rows_rejected_low_similarity": len(report.rejected_low_similarity),
        "rows_rejected_ambiguous": len(report.rejected_ambiguous),
        "match_threshold": args.threshold,
        # Every dropped row, in full, including its indicator text. These rows
        # were read from a Programa but could not be tied to a published
        # objective; keeping them means nothing extracted is lost silently.
        "rejected_rows": report.rejected_low_similarity,
        "ambiguous_rows": report.rejected_ambiguous,
    }
    notes = database["metadata"].setdefault("coverage_notes", [])
    notes = [n for n in notes if "indicadores de evaluación no se publican" not in n]
    notes.append(INDICATOR_SOURCE_NOTE)
    database["metadata"]["coverage_notes"] = notes

    output = write_json(database, args.output or args.file,
                        indent=None if args.compact else 2)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")

    print("\nIndicator pass")
    print("--------------")
    print(f"  Programa PDFs read       {report.pdfs_read}")
    print(f"  Programa PDFs failed     {len(report.pdfs_failed)}")
    print(f"  indicators attached      {stats['indicators']}")
    print(f"  objectives covered       {stats['objectives_with_indicators']}"
          f"/{stats['objectives']}")
    for category, counts in stats["by_category"].items():
        print(f"    {category:<18} {counts['with_indicators']}/{counts['objectives']}")
    print(f"  rows renumbered by MINEDUC {report.renumbered_rows}")
    print(f"  rows from joint evaluation tables {report.joint_rows}")
    print(f"  rows rejected (statement mismatch) {len(report.rejected_low_similarity)}"
          f"  -> kept in metadata.indicators.rejected_rows")
    print(f"  rows rejected (ambiguous)          {len(report.rejected_ambiguous)}")
    for rejection in report.rejected_low_similarity[:5]:
        print(f"    ~ {rejection['where']} sim={rejection['similarity']} "
              f"closest={rejection['closest_code']}")
    for warning in report.shared_pdf_warnings[:5]:
        print(f"  ! {warning}")
    for failure in report.pdfs_failed[:10]:
        print(f"  x {failure['url']}: {failure['error']}")

    errors, warnings, audit = validate(database)
    _report(audit, errors, warnings)
    return 1 if errors else 0


def cmd_tp_modules(args: argparse.Namespace) -> int:
    """Attach módulo / Aprendizaje Esperado / Criterio data from the TP Programas."""
    database = _load(args.file)
    with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
        report = tp_enrich(
            client, database,
            pdf_cache=args.pdf_cache,
            limit=args.limit,
            threshold=args.threshold,
        )
    stats = tp_coverage(database)
    database.setdefault("metadata", {})["tp_modules"] = {
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Programas de Estudio Técnico-Profesional (PDF), "
                  "curriculumnacional.cl",
        "pdfs_read": report.pdfs_read,
        "pdfs_failed": report.pdfs_failed,
        **stats,
        "objective_links": report.objective_links,
        "match_threshold": args.threshold,
    }
    notes = database["metadata"].setdefault("coverage_notes", [])
    if TP_MODULE_NOTE not in notes:
        notes.append(TP_MODULE_NOTE)

    output = write_json(database, args.output or args.file,
                        indent=None if args.compact else 2)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")

    print("\nTécnico-Profesional module pass")
    print("-------------------------------")
    print(f"  Programa PDFs read        {report.pdfs_read}")
    print(f"  Programa PDFs failed      {len(report.pdfs_failed)}")
    print(f"  TP subjects with módulos  {stats['tp_subjects_with_modules']}"
          f"/{stats['tp_subjects']}")
    print(f"  módulos                   {stats['modules']}")
    print(f"  aprendizajes esperados    {stats['expected_learnings']}")
    print(f"  criterios de evaluación   {stats['criteria']}")
    print(f"  módulo->objetivo links    {report.objective_links}")
    for failure in report.pdfs_failed[:10]:
        print(f"  x {failure['url']}: {failure['error']}")

    errors, warnings, audit = validate(database)
    _report(audit, errors, warnings)
    return 1 if errors else 0


def cmd_augment(args: argparse.Namespace) -> int:
    """Complete the canonical dataset from the sources the HTML crawl cannot reach.

    Four passes, in this order and for this reason:

    1. **EPJA** - read the Bases Curriculares EPJA 2024 PDF and ingest the
       objectives the site publishes no HTML for. Runs first because everything
       after it has to see the new records.
    2. **Religión** - record the source-backed reason those twelve pages carry no
       objectives, so the coverage report can tell source absence from a parser
       gap.
    3. **Corrections** - apply the reviewed corrections where official sources
       contradict each other, keeping the original text on the record.
    4. **Provenance / status / prioritization** - backfill the records that
       predate the provenance model, and replace the timeless `prioritized`
       reading with the 2023-2025 programme it actually recorded.
    """
    database = _load(args.file)
    metadata = database.setdefault("metadata", {})
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Stamp the build identity. `scraped_at` stays what it is - the date the
    # HTML crawl ran, which is a real and separate fact - and `built_at` records
    # when these artefacts were generated. The browser versions its cached copy
    # on `built_at`, so augmenting a dataset without re-crawling still
    # invalidates every client's copy, which stamping only `scraped_at` would
    # have got wrong in both directions.
    metadata["built_at"] = retrieved_at
    metadata["schema_version"] = SCHEMA_VERSION
    metadata["generator"] = f"mineduc-scraper/{__version__}"

    # -- 1. EPJA -----------------------------------------------------------
    epja_report = None
    if not args.no_epja:
        with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
            pdf_path, pages = fetch_epja_bases(client, args.pdf_cache)
        parsed = parse_document(pages)
        epja_report = epja_merge(
            database, parsed.sections, retrieved_at, parsed.problems
        )
        metadata["epja_bases"] = {
            "extracted_at": retrieved_at,
            "source": EPJA_BASES_2024["title"],
            "source_url": EPJA_BASES_2024["pdf_url"],
            "landing_url": EPJA_BASES_2024["landing_url"],
            "pdf_pages": parsed.pages_scanned,
            "definition_sections": epja_report.sections,
            "objectives_added": epja_report.objectives_added,
            "subjects_created": epja_report.subjects_created,
            "subjects_filled": epja_report.subjects_filled,
            "levels_created": epja_report.levels_created,
            "verified_against_html": epja_report.verified_against_html,
            "html_mismatches": epja_report.html_mismatches,
            "skipped_html_published": epja_report.skipped_html_published,
            "site_pages_deferred": epja_report.site_pages_deferred,
            "pages_not_defined_in_bases": epja_report.pages_not_defined,
            "parser_problems": epja_report.parser_problems,
        }

    # -- 1b. OAT verification ---------------------------------------------
    # The OATs were read from the JSON:API in an earlier pass. Re-reading them
    # here and comparing field by field is what turns "74 OATs" from a number
    # this project produced once into a number it can still stand behind.
    oat_report = None
    if not args.no_oat_check:
        with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
            live = fetch_transversal_objectives(client)
        oat_report = verify_oats(database.get("transversal_objectives") or {}, live)
        oat_report["verified_on"] = retrieved_at
        metadata["oat_verification"] = oat_report

    # -- 2. Religión -------------------------------------------------------
    religion_report = annotate_religion(database)
    metadata["religion"] = religion_report

    # -- 3. corrections ----------------------------------------------------
    applied, skipped = apply_corrections(database)
    metadata["corrections"] = {"applied": applied, "skipped": skipped}

    # -- 4. provenance, status, prioritization -----------------------------
    counts = annotate_provenance(database)
    metadata["provenance"] = {"annotated_at": retrieved_at, **counts}

    notes = metadata.setdefault("coverage_notes", [])
    for note in (EPJA_BASES_NOTE, RELIGION_NOTE):
        if note not in notes:
            notes.append(note)

    refresh_totals(database)
    output = write_json(database, args.output or args.file,
                        indent=None if args.compact else 2)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")

    print("\nAugmentation pass")
    print("-----------------")
    if epja_report:
        print(f"  EPJA definition sections    {epja_report.sections}")
        print(f"  EPJA objectives added       {epja_report.objectives_added}")
        print(f"  EPJA subjects created/filled {epja_report.subjects_created}"
              f"/{epja_report.subjects_filled}")
        print(f"  EPJA verified against HTML  {epja_report.verified_against_html}")
        print(f"  EPJA HTML/PDF mismatches    {len(epja_report.html_mismatches)}")
        print(f"  EPJA pages not defined in Bases {len(epja_report.pages_not_defined)}")
        print(f"  EPJA parser problems        {len(epja_report.parser_problems)}")
        for problem in epja_report.parser_problems[:10]:
            print(f"    ! {problem}")
        for mismatch in epja_report.html_mismatches[:10]:
            print(f"    ! {mismatch}")
    if oat_report:
        print(f"  OATs re-read and compared   {oat_report['records_compared']}")
        print(f"  OAT bases with objectives   {oat_report['bases_with_oats']}")
        print(f"  OAT differences             {len(oat_report['differences'])}")
        for problem in (oat_report["differences"] + oat_report["missing_from_dataset"]
                        + oat_report["not_in_source"] + oat_report["count_mismatches"])[:10]:
            print(f"    ! {problem}")
    print(f"  Religión pages annotated    {religion_report['pages_annotated']}")
    print(f"  corrections applied         {len(applied)}")
    for record in applied:
        print(f"    ~ {record['id']} ({record['code']}) <- {record['authoritative_source_url']}")
    for reason in skipped:
        print(f"    x skipped: {reason}")
    print(f"  objectives with provenance  {counts['objectives']}")
    print(f"  OATs with provenance        {counts['oats']}")
    print(f"  prioritization annotated    {counts['prioritized']}")

    errors, warnings, report = validate(database)
    _report(report, errors, warnings)
    return 1 if errors else 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """Build the coverage report from the official source inventory."""
    database = _load(args.file)

    site: list = []
    if not args.offline:
        with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
            site = discover_site_offerings(client)

    document: list = []
    if not args.no_bases:
        with PoliteClient(delay=args.delay, cache_dir=args.cache) as client:
            _, pages = fetch_epja_bases(client, args.pdf_cache)
        document = bases_document_offerings(parse_document(pages).sections)

    offerings = merge_offerings(site, document)
    report = build_coverage_report(database, offerings)
    report["discovered"] = {"site_pages": len(site), "bases_sections": len(document)}

    output = write_json(report, args.output)
    print(f"wrote {output} ({output.stat().st_size / 1024:.0f} KB)")

    print("\nCoverage against the official inventory")
    print("---------------------------------------")
    print(f"  expected offerings        {report['expected_offerings']}")
    for status, count in report["by_status"].items():
        print(f"    {status:<24} {count}")
    print(f"  objectives ingested       {report['objectives_ingested']}")
    for gap in report["parser_gaps"][:20]:
        print(f"    ! parser gap: {gap['level_id']}/{gap['subject_id']} {gap['source_url']}")
    for missing in report["offerings_not_in_dataset"][:20]:
        print(f"    ! not in dataset: {missing['level_id']}/{missing['subject_id']}")
    for extra in report["unexpected_in_dataset"][:20]:
        print(f"    ? unexpected: {extra['level_id']}/{extra['subject_id']}")

    if args.embed:
        database.setdefault("metadata", {})["coverage"] = summarise_coverage(report)
        write_json(database, args.file, indent=None if args.compact else 2)
        print(f"embedded the coverage summary in {args.file}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    database = _load(args.file)
    errors, warnings, report = validate(database)
    _report(report, errors, warnings)
    return 1 if errors else 0


def cmd_export_slim(args: argparse.Namespace) -> int:
    database = _load(args.file)
    output = write_json(to_slim(database, with_indicators=args.with_indicators),
                        args.output, indent=None if args.compact else 2)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")
    return 0


def cmd_export_sqlite(args: argparse.Namespace) -> int:
    database = _load(args.file)
    output = write_sqlite(database, args.output)
    print(f"wrote {output} ({output.stat().st_size / 1_048_576:.2f} MB)")
    return 0


def cmd_export_manifest(args: argparse.Namespace) -> int:
    database = _load(args.file)
    files = {}
    for label, candidate in (
        ("full", args.file),
        ("slim", args.slim),
        ("sqlite", args.sqlite),
    ):
        if candidate and Path(candidate).exists():
            files[label] = {
                "path": Path(candidate).name,
                "bytes": Path(candidate).stat().st_size,
            }
    output = write_manifest(database, args.output, files)
    print(f"wrote {output} ({output.stat().st_size} bytes)")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    database = _load(args.file)
    files = split_by_level(database, args.output)
    print(f"wrote {len(files)} files in {args.output}")
    return 0


def cmd_levels(_: argparse.Namespace) -> int:
    from .taxonomy import LEVELS

    print("Level tokens accepted by --levels:\n")
    seen = set()
    for level in sorted(LEVELS.values(), key=lambda l: l.order):
        if level.cli in seen:
            continue
        seen.add(level.cli)
        print(f"  {level.cli:<6} {level.level_id:<22} {level.level_name}")
    print("\nGroup aliases:\n")
    for name, tokens in LEVEL_GROUPS.items():
        print(f"  {name:<12} {', '.join(tokens)}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Grep the dataset from the shell - handy for spot-checking a scrape.

    Accent-insensitive, so "fotosintesis" finds "fotosíntesis", and it searches
    the evaluation indicators too.
    """
    database = _load(args.file)
    needle = strip_accents(args.text).lower()
    hits = 0
    for level_id, level in database.get("levels", {}).items():
        if args.level and args.level != level_id:
            continue
        for subject_id, subject in level.get("subjects", {}).items():
            if args.subject and args.subject not in subject_id:
                continue
            for objective in subject.get("learning_objectives", []):
                if args.category and objective.get("category") != args.category:
                    continue
                haystack = strip_accents(
                    " ".join(
                        [
                            objective.get("statement", ""),
                            objective.get("code", ""),
                            objective.get("oa_id", ""),
                            " ".join(objective.get("keywords") or []),
                            " ".join(objective.get("indicators") or []),
                        ]
                    )
                ).lower()
                if needle and needle not in haystack:
                    continue
                hits += 1
                indicators = objective.get("indicators") or []
                print(f"[{objective['oa_id']}] {objective.get('code','')} "
                      f"| {level_id} / {subject_id} / "
                      f"{objective.get('strand_eje','-')}"
                      + (f" | {len(indicators)} indicadores" if indicators else ""))
                print(f"    {objective['statement'].splitlines()[0][:160]}")
                if args.indicators:
                    for indicator in indicators:
                        print(f"      - {indicator[:150]}")
                if hits >= args.limit:
                    print(f"\n(stopped at {args.limit} hits)")
                    return 0
    print(f"\n{hits} match(es)")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mineduc-scraper",
        description="Scrape and validate the Chilean MINEDUC national curriculum "
                    "into a structured JSON dataset.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-q", "--quiet", dest="verbosity", action="store_const",
                        const=-1, default=0, help="only warnings and errors")
    parser.add_argument("-v", "--verbose", dest="verbosity", action="store_const",
                        const=1, help="debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="crawl curriculumnacional.cl")
    scrape.add_argument("--levels", default=None,
                        help="comma-separated level tokens or group aliases "
                             "(default: every level). Run `mineduc-scraper levels`.")
    scrape.add_argument("--output", "-o", type=Path,
                        default=Path("output/mineduc_curriculum_full.json"))
    scrape.add_argument("--slim", type=Path, default=None,
                        help="also write the slim variant to this path")
    scrape.add_argument("--slim-indicators", action="store_true",
                        help="keep evaluation indicators in the slim variant")
    scrape.add_argument("--sqlite", type=Path, default=None,
                        help="also write a SQLite build (with FTS5) to this path")
    scrape.add_argument("--split", type=Path, default=None,
                        help="also write one JSON file per level into this directory")
    scrape.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"seconds between requests (default {DEFAULT_DELAY})")
    scrape.add_argument("--cache", type=Path, default=None,
                        help="directory for cached HTML, so re-runs skip the network")
    scrape.add_argument("--limit", type=int, default=None,
                        help="stop after N pages (for smoke tests)")
    scrape.add_argument("--no-oats", action="store_true",
                        help="skip the JSON:API fetch of transversal objectives")
    scrape.add_argument("--compact", action="store_true", help="minified JSON output")
    scrape.set_defaults(func=cmd_scrape)

    indicators = subparsers.add_parser(
        "indicators",
        help="download the Programa de Estudio PDFs and attach evaluation indicators",
        description="Evaluation indicators exist only inside the Programa de Estudio "
                    "PDFs. This downloads them (~220 files, ~800 MB the first time; "
                    "cached afterwards) and attaches each objective's indicators.",
    )
    indicators.add_argument("--file", "-f", type=Path, required=True,
                            help="dataset produced by `scrape`")
    indicators.add_argument("--output", "-o", type=Path, default=None,
                            help="where to write the enriched dataset (default: in place)")
    indicators.add_argument("--pdf-cache", type=Path, default=Path(".cache/pdfs"),
                            help="directory for downloaded PDFs (default .cache/pdfs)")
    indicators.add_argument("--cache", type=Path, default=None,
                            help="directory for cached HTML")
    indicators.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    indicators.add_argument("--limit", type=int, default=None,
                            help="stop after N Programa documents (for smoke tests)")
    indicators.add_argument("--threshold", type=float, default=MATCH_THRESHOLD,
                            help="minimum statement similarity to accept a match "
                                 f"(default {MATCH_THRESHOLD})")
    indicators.add_argument("--compact", action="store_true")
    indicators.set_defaults(func=cmd_indicators)

    tp = subparsers.add_parser(
        "tp-modules",
        help="attach módulos, aprendizajes esperados and criterios de evaluación "
             "from the Técnico-Profesional Programas",
        description="The Técnico-Profesional Programas de Estudio publish no "
                    "per-objective indicators. They organise each speciality into "
                    "módulos with Aprendizajes Esperados and Criterios de "
                    "Evaluación; this reads that structure.",
    )
    tp.add_argument("--file", "-f", type=Path, required=True)
    tp.add_argument("--output", "-o", type=Path, default=None)
    tp.add_argument("--pdf-cache", type=Path, default=Path(".cache/pdfs"))
    tp.add_argument("--cache", type=Path, default=None)
    tp.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    tp.add_argument("--limit", type=int, default=None)
    tp.add_argument("--threshold", type=float, default=MATCH_THRESHOLD)
    tp.add_argument("--compact", action="store_true")
    tp.set_defaults(func=cmd_tp_modules)

    augment = subparsers.add_parser(
        "augment",
        help="complete the dataset: EPJA Bases Curriculares, the Religión finding, "
             "reviewed corrections, provenance and curriculum status",
        description="The HTML crawl cannot reach everything the ministry publishes. "
                    "This reads the Bases Curriculares EPJA 2024 PDF, records the "
                    "source-backed reason Religión publishes no objectives, applies "
                    "the reviewed corrections, and attaches provenance, curriculum "
                    "status and historical prioritization to every record.",
    )
    augment.add_argument("--file", "-f", type=Path, required=True)
    augment.add_argument("--output", "-o", type=Path, default=None)
    augment.add_argument("--pdf-cache", type=Path, default=Path(".cache/pdfs"))
    augment.add_argument("--cache", type=Path, default=None)
    augment.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    augment.add_argument("--no-epja", action="store_true",
                         help="skip the Bases Curriculares EPJA pass")
    augment.add_argument("--no-oat-check", action="store_true",
                         help="skip re-reading the OATs from the JSON:API to verify them")
    augment.add_argument("--compact", action="store_true")
    augment.set_defaults(func=cmd_augment)

    coverage = subparsers.add_parser(
        "coverage",
        help="build the coverage report from the official source inventory",
        description="Enumerates every curriculum offering the ministry publishes - "
                    "from the site's own indexes and from the Bases Curriculares "
                    "documents - and reports each one as ingested, absent at "
                    "source, defined in another level, or an unresolved parser gap.",
    )
    coverage.add_argument("--file", "-f", type=Path, required=True)
    coverage.add_argument("--output", "-o", type=Path,
                          default=Path("data/coverage_report.json"))
    coverage.add_argument("--pdf-cache", type=Path, default=Path(".cache/pdfs"))
    coverage.add_argument("--cache", type=Path, default=None)
    coverage.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    coverage.add_argument("--offline", action="store_true",
                          help="skip site discovery and use only the Bases documents")
    coverage.add_argument("--no-bases", action="store_true",
                          help="skip the Bases Curriculares discovery arm")
    coverage.add_argument("--embed", action="store_true",
                          help="also write the coverage summary into the dataset "
                               "metadata, so the manifest can carry it")
    coverage.add_argument("--compact", action="store_true")
    coverage.set_defaults(func=cmd_coverage)

    validate_cmd = subparsers.add_parser(
        "validate", help="schema + coverage audit of an existing dataset"
    )
    validate_cmd.add_argument("--file", "-f", type=Path, required=True)
    validate_cmd.set_defaults(func=cmd_validate)

    slim = subparsers.add_parser(
        "export-slim", help="OAs only, one-line statements (browser / LLM context)"
    )
    slim.add_argument("--file", "-f", type=Path, required=True)
    slim.add_argument("--output", "-o", type=Path, required=True)
    slim.add_argument("--with-indicators", action="store_true",
                      help="keep evaluation indicators (roughly triples the size)")
    slim.add_argument("--compact", action="store_true")
    slim.set_defaults(func=cmd_export_slim)

    sqlite_cmd = subparsers.add_parser(
        "export-sqlite", help="SQLite build with an FTS5 full-text index"
    )
    sqlite_cmd.add_argument("--file", "-f", type=Path, required=True)
    sqlite_cmd.add_argument("--output", "-o", type=Path, required=True)
    sqlite_cmd.set_defaults(func=cmd_export_sqlite)

    manifest = subparsers.add_parser(
        "export-manifest",
        help="small manifest identifying a build, for browser clients to version-check",
    )
    manifest.add_argument("--file", "-f", type=Path, required=True)
    manifest.add_argument("--output", "-o", type=Path, required=True)
    manifest.add_argument("--slim", type=Path, default=None)
    manifest.add_argument("--sqlite", type=Path, default=None)
    manifest.set_defaults(func=cmd_export_manifest)

    split = subparsers.add_parser("split", help="one JSON file per level, plus index.json")
    split.add_argument("--file", "-f", type=Path, required=True)
    split.add_argument("--output", "-o", type=Path, required=True)
    split.set_defaults(func=cmd_split)

    levels = subparsers.add_parser("levels", help="list valid --levels tokens")
    levels.set_defaults(func=cmd_levels)

    query = subparsers.add_parser("query", help="search a dataset from the shell")
    query.add_argument("text", nargs="?", default="")
    query.add_argument("--file", "-f", type=Path, required=True)
    query.add_argument("--level", default=None)
    query.add_argument("--subject", default=None)
    query.add_argument("--category", default=None,
                       choices=["conocimiento", "habilidad", "actitud"])
    query.add_argument("--indicators", action="store_true",
                       help="also print each objective's evaluation indicators")
    query.add_argument("--limit", type=int, default=20)
    query.set_defaults(func=cmd_query)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbosity)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
