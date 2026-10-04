"""data_manager.py - Data layer (INF1103 Phase 1).

The system's memory. All records are written to and read from a flat JSON
file. No printing and no user interaction happens here; failures are logged
and reported through return values so the caller can decide what to display.

Records are keyed by log_id and the file is always written in sorted order, so
re-running the program on the same input produces an identical file.
"""

import json
import logging
import os
import tempfile
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DATA_FILE_PATH = os.getenv("DATA_FILE_PATH", os.path.join("data", "processed_records.json"))


def _ensure_directory(path: str) -> None:
    """Create the parent directory for a data file if it is missing."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        logger.error("Could not create data directory %s: %s", directory, error)


def load(path: Optional[str] = None) -> list:
    """Read and return all stored records.

    Returns an empty list if the file is missing, empty, corrupt or the wrong
    shape. Never raises and never crashes the program - a damaged data file
    means starting from nothing, not stopping.
    """
    target = path or DATA_FILE_PATH

    if not os.path.exists(target):
        logger.info("No data file at %s yet; starting with an empty set", target)
        return []

    try:
        with open(target, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError as error:
        logger.error("Could not read data file %s: %s", target, error)
        return []

    if not content:
        logger.warning("Data file %s is empty", target)
        return []

    try:
        records = json.loads(content)
    except json.JSONDecodeError as error:
        logger.error("Data file %s is corrupt (%s); continuing with an empty set", target, error)
        return []

    if not isinstance(records, list):
        logger.error("Data file %s holds %s, expected a list", target, type(records).__name__)
        return []

    valid = [record for record in records if isinstance(record, dict) and record.get("log_id")]
    skipped = len(records) - len(valid)
    if skipped:
        logger.warning("Skipped %d malformed record(s) in %s", skipped, target)

    logger.info("Loaded %d record(s) from %s", len(valid), target)
    return valid


def _write_all(records: list, path: str) -> bool:
    """Write the full record set atomically, sorted by log_id."""
    _ensure_directory(path)
    ordered = sorted(records, key=lambda record: str(record.get("log_id", "")))

    directory = os.path.dirname(os.path.abspath(path))
    handle = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        json.dump(ordered, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
        return True
    except (OSError, TypeError, ValueError) as error:
        logger.error("Could not write data file %s: %s", path, error)
        if handle is not None:
            try:
                handle.close()
                if os.path.exists(handle.name):
                    os.remove(handle.name)
            except OSError:
                pass
        return False


def save(record: dict, path: Optional[str] = None) -> bool:
    """Append one processed record to storage, or replace it if already present.

    Replacing rather than blindly appending makes the operation idempotent: the
    same log processed twice leaves one row, so separate runs on the same input
    produce the same file.
    """
    target = path or DATA_FILE_PATH

    if not isinstance(record, dict) or not record.get("log_id"):
        logger.error("Refusing to save a record with no log_id")
        return False

    records = load(target)
    log_id = record["log_id"]
    replaced = False

    for index, existing in enumerate(records):
        if existing.get("log_id") == log_id:
            records[index] = record
            replaced = True
            break
    if not replaced:
        records.append(record)

    if not _write_all(records, target):
        return False

    logger.info("%s record %s in %s", "Updated" if replaced else "Saved", log_id, target)
    return True


def save_many(records: list, path: Optional[str] = None) -> int:
    """Save a batch of records. Returns how many were written successfully."""
    saved = 0
    for record in records:
        if save(record, path=path):
            saved += 1
    return saved


def query(filter_fn: Callable, path: Optional[str] = None) -> list:
    """Return stored records for which filter_fn(record) is true.

    A record whose filter call raises is skipped and logged, so one odd row
    cannot break a search.
    """
    matches = []
    for record in load(path):
        try:
            if filter_fn(record):
                matches.append(record)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            logger.warning("Filter failed on record %s: %s", record.get("log_id"), error)
    logger.info("Query matched %d record(s)", len(matches))
    return matches


def exists(log_id: str, path: Optional[str] = None) -> bool:
    """Report whether a log_id is already stored."""
    return any(record.get("log_id") == log_id for record in load(path))
