import json
import os
from typing import Callable

from logic_manager_ErrorLog import ErrorLog


class RecordRepository:
    """Manage hospital equipment error records in a JSON file."""

    # FUNCTION 1: Initialise the repository
    def __init__(self, data_file: str | None = None):
        self._data_file = data_file or os.getenv(
            "DATA_FILE", "processed_records.json"
        )
        self._records: list[ErrorLog] = []

    # FUNCTION 2: Read records from JSON
    def _read_file(self) -> list[dict]:
        try:
            with open(self._data_file, "r", encoding="utf-8") as file:
                items = json.load(file)

            return items if isinstance(items, list) else []

        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

        # FUNCTION 3: Write records into JSON
    def _write_file(self, items: list[dict]) -> bool:
        try:
            folder = os.path.dirname(
                os.path.abspath(self._data_file)
            )
            os.makedirs(folder, exist_ok=True)

            with open(self._data_file, "w", encoding="utf-8") as file:
                json.dump(
                    items, file, indent=4, ensure_ascii=False
                )
            return True

        except (OSError, TypeError, ValueError):
            return False
        

        # FUNCTION 4: Load all ErrorLog objects
    def load_all(self) -> list[ErrorLog]:
        records = []

        for item in self._read_file():

            if not isinstance(item, dict):
                continue

            try:
                log = ErrorLog.from_dict(item)
                records.append(log)

            except (KeyError, ValueError, TypeError):
                continue

        self._records = records
        return self._records.copy()
    

    # FUNCTION 5: Save or update an ErrorLog
    def save(self, log: ErrorLog) -> bool:

        if not isinstance(log, ErrorLog):
            return False

        records = self.load_all()

        for index, existing in enumerate(records):

            if existing.log_id == log.log_id:
                records[index] = log
                break

        else:
            records.append(log)

        try:
            items = [
                record.to_dict() for record in records
            ]

        except (AttributeError, TypeError, ValueError):
            return False

        if not self._write_file(items):
            return False

        self._records = records
        return True

    # FUNCTION 6: Find one record using log_id
    def get(self, log_id: str) -> ErrorLog | None:

        records = self.load_all()

        for record in records:

            if record.log_id == log_id:
                return record

        return None

     # FUNCTION 7: Filter stored records
    def query(
        self, predicate: Callable[[ErrorLog], bool]
    ) -> list[ErrorLog]:

        records = self.load_all()

        results = []

        for record in records:

            if predicate(record):
                results.append(record)

        return results

    