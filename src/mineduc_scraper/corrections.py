"""Reviewable corrections to official curriculum text.

Official sources sometimes contradict each other. When they do, silently
rewriting one of them would make the dataset unauditable: a reader could not
tell what the site actually says, nor why this project disagrees with it.

So corrections live in a data file (``data/corrections.json``), not in code, and
each one has to carry:

* the official code it applies to, and where it lives in the dataset
* the value that was extracted
* the value this dataset publishes instead
* the authoritative source URL, and its page when that source is a PDF
* an explanation of *why* the sources disagree and which one wins
* the date the conflict was verified

Applying a correction rewrites the field **and** stores the whole record on the
objective under ``correction``, so the original text is still in the dataset and
the change is visible wherever the objective is. Every applied correction is
also summarised in ``metadata.corrections``.

A correction whose ``original_value`` no longer matches what was extracted is
*not* applied: that means the source changed underneath it, and the right
response is to re-verify the conflict rather than to overwrite whatever is
there now.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CORRECTIONS_PATH = Path(__file__).parent / "data" / "corrections.json"

REQUIRED_FIELDS = (
    "id",
    "scope",
    "field",
    "original_value",
    "corrected_value",
    "authoritative_source_url",
    "explanation",
    "verified_on",
)


def validate_corrections(entries: List[dict]) -> List[dict]:
    """Reject any correction that a reviewer could not check.

    Applied on load *and* on apply, because a correction is only legitimate if
    someone can follow it back to the source that settles the conflict. A
    correction with no authoritative source is an undocumented rewrite of
    official text, which is the thing this whole mechanism exists to prevent.
    """
    for entry in entries:
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise ValueError(
                f"correction {entry.get('id', '<unnamed>')!r} is missing "
                f"required field(s): {', '.join(missing)}"
            )
    return entries


def load_corrections(path: Optional[Path] = None) -> List[dict]:
    """Load the corrections file, rejecting entries that are not reviewable."""
    with Path(path or CORRECTIONS_PATH).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return validate_corrections(payload.get("corrections", []))


def _find_objective(database: dict, entry: dict) -> Optional[dict]:
    subjects = (
        database.get("levels", {})
        .get(entry.get("level_id", ""), {})
        .get("subjects", {})
    )
    subject = subjects.get(entry.get("subject_id", ""))
    if subject is None:
        return None
    for objective in subject.get("learning_objectives", []):
        if objective.get("code") == entry.get("code"):
            return objective
    return None


def apply_corrections(
    database: dict, entries: Optional[List[dict]] = None
) -> Tuple[List[dict], List[str]]:
    """Apply every correction that still matches what was extracted.

    Returns ``(applied, skipped)``: a summary record per applied correction, and
    a human-readable reason per one that was not applied. A skipped correction
    is always reported - it means the dataset and the corrections file have
    drifted apart, which is a thing to look at, not to swallow.
    """
    entries = load_corrections() if entries is None else validate_corrections(entries)
    applied: List[dict] = []
    skipped: List[str] = []

    for entry in entries:
        if entry.get("scope") != "objective":
            skipped.append(f"{entry['id']}: unsupported scope {entry.get('scope')!r}")
            continue
        objective = _find_objective(database, entry)
        if objective is None:
            skipped.append(
                f"{entry['id']}: no objective {entry.get('code')!r} at "
                f"{entry.get('level_id')}/{entry.get('subject_id')}"
            )
            continue
        field = entry["field"]
        current = objective.get(field)
        if current == entry["corrected_value"]:
            applied.append({**_summary(entry), "already_applied": True})
            continue
        if current != entry["original_value"]:
            skipped.append(
                f"{entry['id']}: extracted {field} no longer matches the recorded "
                f"original - the source changed and the conflict needs re-verifying"
            )
            continue

        objective[field] = entry["corrected_value"]
        objective["correction"] = _record(entry)
        applied.append(_summary(entry))

    return applied, skipped


def _record(entry: dict) -> dict:
    """The correction as stored on the corrected objective itself."""
    keys = (
        "id", "field", "original_value", "corrected_value",
        "authoritative_source_url", "authoritative_source_title",
        "authoritative_source_page", "conflicting_source_url",
        "defect_origin", "explanation", "verified_on",
    )
    return {key: entry[key] for key in keys if entry.get(key) is not None}


def _summary(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "code": entry.get("code"),
        "where": f"{entry.get('level_id')}/{entry.get('subject_id')}",
        "field": entry["field"],
        "defect_origin": entry.get("defect_origin"),
        "authoritative_source_url": entry["authoritative_source_url"],
        "authoritative_source_page": entry.get("authoritative_source_page"),
        "verified_on": entry["verified_on"],
    }
