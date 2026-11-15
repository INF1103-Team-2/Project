"""data_manager_record_repository.py - stores ErrorLogs in a JSON file."""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Callable, Optional

from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class RecordRepository:
    """Saves and loads ErrorLogs (aggregation: the logs exist before they are saved).

    The file is re-read on every load, so the result is always what is on disk,
    exactly as in Phase 1.

    Part 2 error handling:
      * A missing file is normal (first run) and reads as an empty list.
      * A corrupt or unreadable file is logged, and a corrupt file is renamed to
        ``<name>.corrupt-<time>`` before the next save, so old records are kept
        for inspection instead of being silently overwritten.
      * One lock guards every read and write, because the GUI worker thread and the
        background due-report thread can both save at the same time.
    """

    def __init__(self, data_file: str) -> None:
        self._data_file: str = data_file
        self._records: list[ErrorLog] = []
        self._lock: threading.RLock = threading.RLock()
        self._last_problem: Optional[str] = None

    @property
    def last_problem(self) -> Optional[str]:
        """Why the last read failed (None if it was fine). Lets the UI explain it."""
        return self._last_problem

    def load_all(self) -> list[ErrorLog]:
        """Every stored log; an empty list if the file is missing or corrupt."""
        with self._lock:
            self._records = [ErrorLog.from_dict(item) for item in self._read_file()
                             if isinstance(item, dict)]
            return list(self._records)

    def save(self, log: ErrorLog) -> bool:
        """Add the log, or replace the stored one with the same log_id."""
        if not isinstance(log, ErrorLog) or not log.log_id:
            return False
        with self._lock:                       # read-modify-write is one step
            stored = self._read_file(backup_if_corrupt=True)
            if self._last_problem is not None and os.path.exists(self._data_file):
                # The old file is still there and could not be read or moved aside:
                # refuse to overwrite it rather than lose every stored record.
                logger.error("Not saving %s: %s", log.log_id, self._last_problem)
                return False
            new_item = log.to_dict()
            for index, item in enumerate(stored):
                if isinstance(item, dict) and item.get("log_id") == log.log_id:
                    stored[index] = new_item
                    break
            else:
                stored.append(new_item)
            return self._write_file(stored)

    def get(self, log_id: str) -> Optional[ErrorLog]:
        for log in self.load_all():
            if log.log_id == log_id:
                return log
        return None

    def query(self, predicate: Callable[[ErrorLog], bool]) -> list[ErrorLog]:
        return [log for log in self.load_all() if predicate(log)]

    # ----- file access -------------------------------------------------------
    def _read_file(self, backup_if_corrupt: bool = False) -> list:
        """Return the stored list. Never raises; problems are logged instead."""
        self._last_problem = None
        try:
            with open(self._data_file, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return []                          # first run: nothing saved yet
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._last_problem = f"Records file is corrupt ({type(error).__name__})"
            logger.error("Records file %s is corrupt: %s", self._data_file, error)
            if backup_if_corrupt:
                self._backup_corrupt_file()
            return []
        except OSError as error:               # PermissionError, IsADirectoryError, ...
            self._last_problem = f"Records file could not be read ({type(error).__name__})"
            logger.error("Could not read records file %s: %s", self._data_file, error)
            return []

        if not isinstance(data, list):
            self._last_problem = "Records file does not contain a list"
            logger.error("Records file %s does not contain a list", self._data_file)
            if backup_if_corrupt:
                self._backup_corrupt_file()
            return []
        return data

    def _backup_corrupt_file(self) -> None:
        """Keep the corrupt file under a new name so the next save cannot destroy it."""
        backup = f"{self._data_file}.corrupt-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            os.replace(self._data_file, backup)
            logger.warning("Corrupt records file kept as %s", backup)
        except OSError as error:
            logger.error("Could not back up corrupt records file %s: %s",
                         self._data_file, error)

    def _write_file(self, items: list) -> bool:
        try:
            with open(self._data_file, "w", encoding="utf-8") as file:
                json.dump(items, file, indent=4)
            return True
        except OSError as error:
            logger.error("Could not write records file %s: %s", self._data_file, error)
            return False
