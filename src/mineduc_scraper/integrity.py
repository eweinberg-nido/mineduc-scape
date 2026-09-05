"""Integrity audits: duplicates, conflicts, text damage, provenance and status.

These checks exist because the previous audit could only catch structural
breakage - an empty statement, a repeated id, a counter that disagreed with the
contents. It could not have caught the two defects that were actually in the
dataset: an objective carrying another objective's text under a different code,
and a statement that ended in a colon with the list it introduces missing.

Everything here is classified rather than merely counted, because the same
symptom can be a defect or a faithful reproduction of the source:

* two grades publishing the same objective under the same code is how MINEDUC
  publishes 3° and 4° Medio, and is **expected**;
* two *different* codes carrying the same statement in one subject and level is
  a conflict, and is what the Sala Cuna OA 03 / OA 04 defect looked like;
* one code carrying two different statements is a conflict wherever it appears.

So the duplicate audit reports each class separately and only raises the ones
the sources do not explain.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from .taxonomy import CURRICULUM_STATUSES, SOURCE_TYPES, STATUS_DESCONOCIDO

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def normalize_statement(statement: str) -> str:
    """Fold a statement for equality comparison: accent-free, punctuation-free."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", statement or "")
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def _iter_objectives(database: dict):
    for level_id, level in (database.get("levels") or {}).items():
        for subject_id, subject in (level.get("subjects") or {}).items():
            for objective in subject.get("learning_objectives") or []:
                yield level_id, subject_id, subject, objective


# --------------------------------------------------------------------------- #
# text integrity
# --------------------------------------------------------------------------- #
MIN_STATEMENT_WORDS = 2

# Every pattern below is deliberately narrow. A text-integrity check that fires
# on correct ministry text is worse than useless: it trains the reader to skim
# past the list, which is exactly how a real truncation gets shipped. Curriculum
# text legitimately contains English example sentences ending in question marks,
# Chilean institution names written as one CamelCase word ("BancoEstado"),
# hyphens used as parentheses ("-la estructura de las operaciones-"), and
# phrases repeated across the items of a list. None of those is damage.

# A statement announcing a list, with the list missing. The single most likely
# way for an objective to be quietly truncated between source and dataset.
_ENDS_OPEN = re.compile(r"[:;]\s*$")

# Mojibake proper: the decoder gave up on a byte.
_REPLACEMENT = "\ufffd"

# "?" standing *inside* a word, which is what a dropped accented character
# extracts as - not "?" ending a question, which is ordinary text.
_STRAY_QUESTION = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]\?[A-Za-zÁÉÍÓÚÑáéíóúñ]|\?{2,}")

# A space lost right after sentence punctuation ("cotidiana.Los"). Bare
# CamelCase is *not* matched, because that is how the ministry prints several
# proper nouns.
_JOINED_WORDS = re.compile(r"[a-záéíóúñ][.,;][A-ZÁÉÍÓÚÑ][a-záéíóúñ]")

# Hyphenation that survived the line unwrap ("habili- dades"). Spanish uses the
# hyphen as a parenthesis too, which produces the same shape, so a match only
# counts when the dashes on that line do not pair up.
_HYPHEN_BREAK = re.compile(r"[a-záéíóúñ]-\s+[a-záéíóúñ]")
_DASH_OPEN = re.compile(r"\s-[A-Za-zÁÉÍÓÚÑáéíóúñ]")
_DASH_CLOSE = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]-\s")


def _unbalanced_dashes(line: str) -> bool:
    """True when a hyphen-space looks like a line break rather than a parenthesis."""
    return len(_DASH_CLOSE.findall(line)) > len(_DASH_OPEN.findall(line))


def text_findings(statement: str) -> List[str]:
    """Return every text-integrity problem visible in one statement."""
    problems: List[str] = []
    lines = [line for line in (statement or "").split("\n") if line.strip()]
    if not lines:
        return ["empty statement"]

    head, *rest = lines
    if _ENDS_OPEN.search(lines[-1]):
        problems.append("ends on a colon with no components captured")
    elif _ENDS_OPEN.search(head) and not rest:
        problems.append("stem ends on a colon with no components captured")

    flat = " ".join(lines)
    if _REPLACEMENT in flat:
        problems.append("contains a replacement character (U+FFFD)")
    if _STRAY_QUESTION.search(flat):
        problems.append("contains a suspicious '?' glyph")
    if _JOINED_WORDS.search(flat):
        problems.append("contains joined words (a lost space after punctuation)")
    if any(_HYPHEN_BREAK.search(line) and _unbalanced_dashes(line) for line in lines):
        problems.append("contains broken line-wrap hyphenation")
    if len(flat.split()) < MIN_STATEMENT_WORDS:
        problems.append(f"statement is only {len(flat.split())} word(s) long")

    # A whole line repeated verbatim is what a mis-merged column, or the nested
    # wrappers the site's maths markup produces, leaves behind. Repeated
    # *phrases* are ordinary inside a list of examples and are not flagged.
    if len(lines) != len(set(lines)):
        problems.append("contains a line repeated verbatim")
    return problems


def audit_text(database: dict) -> Dict[str, object]:
    findings: List[dict] = []
    for level_id, subject_id, _subject, objective in _iter_objectives(database):
        problems = text_findings(objective.get("statement", ""))
        if problems:
            findings.append(
                {
                    "where": f"{level_id}/{subject_id}",
                    "oa_id": objective.get("oa_id"),
                    "code": objective.get("code"),
                    "problems": problems,
                    "statement": (objective.get("statement") or "")[:300],
                }
            )
    by_problem: Counter = Counter()
    for finding in findings:
        for problem in finding["problems"]:
            by_problem[problem] += 1
    return {
        "objectives_flagged": len(findings),
        "by_problem": dict(sorted(by_problem.items())),
        "findings": findings,
    }


# --------------------------------------------------------------------------- #
# duplicates and conflicts
# --------------------------------------------------------------------------- #
def audit_duplicates(database: dict) -> Dict[str, object]:
    """Classify every repetition of a statement, a code or an id."""
    by_scope_statement: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    by_code: Dict[str, List[dict]] = defaultdict(list)
    by_oa_id: Dict[str, List[dict]] = defaultdict(list)

    for level_id, subject_id, _subject, objective in _iter_objectives(database):
        entry = {
            "level_id": level_id,
            "subject_id": subject_id,
            "oa_id": objective.get("oa_id"),
            "code": objective.get("code"),
            "statement": objective.get("statement", ""),
            "normalized": normalize_statement(objective.get("statement", "")),
        }
        by_scope_statement[(f"{level_id}/{subject_id}", entry["normalized"])].append(entry)
        by_code[entry["code"] or ""].append(entry)
        by_oa_id[entry["oa_id"] or ""].append(entry)

    # 1. Same text, different codes, same subject and level -> conflict.
    same_text_different_codes: List[dict] = []
    for (scope, _normalized), entries in by_scope_statement.items():
        codes = sorted({e["code"] for e in entries})
        if len(entries) > 1 and len(codes) > 1:
            same_text_different_codes.append(
                {
                    "where": scope,
                    "codes": codes,
                    "oa_ids": sorted(e["oa_id"] for e in entries),
                    "statement": entries[0]["statement"][:300],
                }
            )

    # 2. Same code, different text.
    #
    # Scope matters. Many official codes are only unique inside their own
    # subject: every Técnico-Profesional speciality numbers its objectives
    # "OA 1", "OA 2", ..., and so does every EPJA asignatura, because that is
    # what the Bases print. The same code carrying different text in two
    # *different* subjects is therefore the published numbering scheme working
    # as intended; the same code carrying different text inside one subject and
    # level is a genuine conflict.
    same_code_different_text: List[dict] = []
    code_scoped_to_subject: List[dict] = []
    # 3. Same code, same text, different level -> how 3°/4° Medio is published.
    shared_across_grades: List[dict] = []
    for code, entries in by_code.items():
        if len(entries) < 2 or not code:
            continue
        texts = {e["normalized"] for e in entries}
        levels = sorted({e["level_id"] for e in entries})
        scopes = {f"{e['level_id']}/{e['subject_id']}" for e in entries}
        if len(texts) > 1 and len(scopes) == 1:
            same_code_different_text.append(
                {
                    "code": code,
                    "where": sorted(scopes)[0],
                    "variants": sorted({e["statement"][:200] for e in entries}),
                    "oa_ids": sorted(e["oa_id"] for e in entries),
                }
            )
        elif len(texts) > 1:
            code_scoped_to_subject.append(
                {"code": code, "subjects": len(scopes), "levels": levels}
            )
        elif len(levels) > 1:
            shared_across_grades.append({"code": code, "levels": levels})

    duplicate_oa_ids = [
        {"oa_id": oa_id, "count": len(entries)}
        for oa_id, entries in by_oa_id.items()
        if len(entries) > 1
    ]
    conflicting_oa_ids = [
        {"oa_id": oa_id, "codes": sorted({e["code"] for e in entries})}
        for oa_id, entries in by_oa_id.items()
        if len(entries) > 1 and len({e["normalized"] for e in entries}) > 1
    ]

    # 3°/4° Medio equivalence is the documented, legitimate case; anything else
    # sharing a code across levels is not, and is separated out.
    legitimate = {"3_medio", "4_medio"}
    legitimate_pairs = [
        entry for entry in shared_across_grades if set(entry["levels"]) <= legitimate
    ]
    unexpected_pairs = [
        entry for entry in shared_across_grades if not set(entry["levels"]) <= legitimate
    ]

    return {
        "same_text_different_codes": same_text_different_codes,
        "same_code_different_text": same_code_different_text,
        "code_scoped_to_subject": code_scoped_to_subject,
        "duplicate_oa_ids": duplicate_oa_ids,
        "conflicting_oa_ids": conflicting_oa_ids,
        "shared_code_across_levels_expected": legitimate_pairs,
        "shared_code_across_levels_unexpected": unexpected_pairs,
        "counts": {
            "same_text_different_codes": len(same_text_different_codes),
            "same_code_different_text": len(same_code_different_text),
            "code_scoped_to_subject": len(code_scoped_to_subject),
            "duplicate_oa_ids": len(duplicate_oa_ids),
            "shared_code_across_levels_expected": len(legitimate_pairs),
            "shared_code_across_levels_unexpected": len(unexpected_pairs),
        },
    }


def audit_routes(database: dict) -> Dict[str, object]:
    """Duplicate routes: the same page reachable, or recorded, twice."""
    seen: Counter = Counter()
    urls: Counter = Counter()
    for level in (database.get("levels") or {}).values():
        for subject in (level.get("subjects") or {}).values():
            # A subject the Bases define but the site navigates no page for
            # legitimately points at the Base document; that is not a duplicate
            # route, it is the absence of a route.
            if subject.get("source_url") and subject.get("site_page_published") is not False:
                urls[subject["source_url"]] += 1
            for alias in subject.get("alias_urls") or []:
                seen[alias] += 1
    return {
        "source_url_used_twice": [
            {"url": url, "count": count} for url, count in urls.items() if count > 1
        ],
        "recorded_aliases": sum(seen.values()),
        "declared_duplicate_routes": len(
            (database.get("metadata") or {}).get("duplicate_routes") or []
        ),
    }


# --------------------------------------------------------------------------- #
# provenance and status
# --------------------------------------------------------------------------- #
PROVENANCE_REQUIRED = ("source_url", "source_type", "retrieved_at", "extraction_method")


def audit_provenance(database: dict) -> Dict[str, object]:
    missing: List[str] = []
    bad_type: List[str] = []
    pdf_without_page: List[str] = []
    by_source_type: Counter = Counter()

    def check(where: str, record: dict) -> None:
        provenance = record.get("provenance")
        if not provenance:
            missing.append(where)
            return
        for field in PROVENANCE_REQUIRED:
            if not provenance.get(field):
                missing.append(f"{where}: provenance.{field}")
                return
        source_type = provenance["source_type"]
        by_source_type[source_type] += 1
        if source_type not in SOURCE_TYPES:
            bad_type.append(f"{where}: unknown source_type {source_type!r}")
        if source_type.endswith("_pdf") and not provenance.get("source_page"):
            pdf_without_page.append(where)

    for level_id, subject_id, _subject, objective in _iter_objectives(database):
        check(f"{level_id}/{subject_id}/{objective.get('oa_id')}", objective)
    for base_slug, bucket in (database.get("transversal_objectives") or {}).items():
        for oat in bucket:
            check(f"OAT {base_slug}/{oat.get('oat_id')}", oat)

    return {
        "missing": missing,
        "unknown_source_type": bad_type,
        "pdf_records_without_page": pdf_without_page,
        "by_source_type": dict(sorted(by_source_type.items())),
    }


def audit_status(database: dict) -> Dict[str, object]:
    """Status must be from the vocabulary, and anything asserted must be sourced."""
    unknown_value: List[str] = []
    unsourced: List[str] = []
    by_status: Counter = Counter()

    def check(where: str, record: dict) -> None:
        status = record.get("curriculum_status", STATUS_DESCONOCIDO)
        by_status[status] += 1
        if status not in CURRICULUM_STATUSES:
            unknown_value.append(f"{where}: {status!r}")
            return
        if status != STATUS_DESCONOCIDO and not record.get("status_source"):
            unsourced.append(where)

    for level_id, subject_id, _subject, objective in _iter_objectives(database):
        check(f"{level_id}/{subject_id}/{objective.get('oa_id')}", objective)
    for base_slug, bucket in (database.get("transversal_objectives") or {}).items():
        for oat in bucket:
            check(f"OAT {base_slug}/{oat.get('oat_id')}", oat)

    return {
        "by_status": dict(sorted(by_status.items())),
        "unknown_value": unknown_value,
        "asserted_without_source": unsourced,
    }


def audit_prioritization(database: dict) -> Dict[str, object]:
    """`prioritized: true` must always come with the programme it belongs to."""
    flagged = 0
    without_metadata: List[str] = []
    for level_id, subject_id, _subject, objective in _iter_objectives(database):
        if not objective.get("prioritized"):
            continue
        flagged += 1
        if not objective.get("prioritization"):
            without_metadata.append(f"{level_id}/{subject_id}/{objective.get('oa_id')}")
    return {"flagged": flagged, "without_metadata": without_metadata}


# --------------------------------------------------------------------------- #
# completeness against the previous build
# --------------------------------------------------------------------------- #
def audit_regression(database: dict, baseline: Optional[dict]) -> Dict[str, object]:
    """Compare against a previous build: what appeared, and what disappeared.

    An objective vanishing between builds is the failure mode a total alone
    cannot show, because an equal number of new records hides it exactly.
    """
    if not baseline:
        return {"compared": False}

    def index(payload: dict) -> Dict[str, str]:
        return {
            objective["oa_id"]: f"{level_id}/{subject_id}"
            for level_id, subject_id, _subject, objective in _iter_objectives(payload)
        }

    before, after = index(baseline), index(database)
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    return {
        "compared": True,
        "baseline_objectives": len(before),
        "objectives": len(after),
        "added": len(added),
        "removed": len(removed),
        "removed_ids": removed[:200],
        "removed_truncated": max(0, len(removed) - 200),
    }


# --------------------------------------------------------------------------- #
def run(database: dict, baseline: Optional[dict] = None) -> Dict[str, object]:
    """Run every integrity audit and return the combined report."""
    return {
        "text": audit_text(database),
        "duplicates": audit_duplicates(database),
        "routes": audit_routes(database),
        "provenance": audit_provenance(database),
        "status": audit_status(database),
        "prioritization": audit_prioritization(database),
        "regression": audit_regression(database, baseline),
    }
