"""data_manager_record_repository.py - stores ErrorLogs in a JSON file."""

import json
import logging
from typing import Callable, Optional

from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class RecordRepository:
    """Saves and loads ErrorLogs (aggregation: the logs exist before they are saved).

    The file is re-read on every load, so the result is always what is on disk,
    exactly as in Phase 1.
    """

    def __init__(self, data_file: str) -> None:
        self._data_file: str = data_file
        self._records: list[ErrorLog] = []

    def load_all(self) -> list[ErrorLog]:
        """Every stored log; an empty list if the file is missing or corrupt."""
        self._records = [ErrorLog.from_dict(item) for item in self._read_file()
                         if isinstance(item, dict)]
        return list(self._records)

    def save(self, log: ErrorLog) -> bool:
        """Add the log, or replace the stored one with the same log_id."""
        if not isinstance(log, ErrorLog) or not log.log_id:
            return False
        stored = self._read_file()
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
    def _read_file(self) -> list:
        try:
            with open(self._data_file, "r") as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _write_file(self, items: list) -> bool:
        try:
            with open(self._data_file, "w") as file:
                json.dump(items, file, indent=4)
            return True
        except OSError:
            return False
