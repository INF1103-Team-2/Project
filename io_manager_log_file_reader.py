"""io_manager_log_file_reader.py - reads and writes machine log files."""

import logging

from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class LogFileReader:
    """Turns a log file into ErrorLog objects.

    Line format: timestamp | machine_id | error_code | machine_type | message
    """

    INVALID_FILE_MESSAGE = "Invalid log format. Upload aborted."   # Business Rule 4

    def __init__(self) -> None:
        self._separator: str = "|"
        self._expected_fields: int = 5

    def read(self, path: str) -> tuple[list[ErrorLog], list[str]]:
        """Return (logs, problems). A bad line is skipped and reported, never fatal."""
        logs: list[ErrorLog] = []
        problems: list[str] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except OSError as error:
            logger.error("Could not read log file %s: %s", path, error)
            return [], [f"File could not be opened: {error}"]

        for number, line in enumerate(lines, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue

            parts = [part.strip() for part in text.split(self._separator)]
            if len(parts) < self._expected_fields:
                problems.append(f"Line {number}: expected {self._expected_fields} fields, "
                                f"got {len(parts)}")
                continue

            raw_timestamp, machine_id, error_code, machine_type, *message_parts = parts
            raw_message = self._separator.join(message_parts).strip()

            timestamp = ErrorLog.parse_timestamp(raw_timestamp)
            if timestamp is None:
                problems.append(f"Line {number}: unreadable timestamp '{raw_timestamp}'")
                continue
            if not ErrorLog.MACHINE_ID_PATTERN.match(machine_id):
                problems.append(f"Line {number}: invalid machine id '{machine_id}'")
                continue
            if not ErrorLog.ERROR_CODE_PATTERN.match(error_code):
                problems.append(f"Line {number}: missing or invalid error code '{error_code}'")
                continue
            if len(raw_message) < ErrorLog.MIN_MESSAGE_LENGTH:
                problems.append(f"Line {number}: message too short to triage")
                continue

            # The id is built from the full message, as in Phase 1.
            logs.append(ErrorLog(
                machine_id=machine_id,
                error_code=error_code,
                machine_type=machine_type if machine_type in ErrorLog.MACHINE_TYPES else "other",
                timestamp=timestamp,
                reported_by="log_file_import",
                raw_message=raw_message[:ErrorLog.MAX_MESSAGE_LENGTH],
                log_id=ErrorLog.make_log_id(machine_id, timestamp, raw_message),
            ))

        logger.info("Read %d records and %d problem lines from %s",
                    len(logs), len(problems), path)
        return logs, problems

    def save(self, path: str, logs: list[ErrorLog]) -> None:
        """Write logs back out in the standard log-file format."""
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for log in logs:
                    handle.write(f"{log.timestamp} | {log.machine_id} | {log.error_code} | "
                                 f"{log.machine_type} | {log.raw_message}\n")
        except OSError as error:
            logger.error("Could not save log file %s: %s", path, error)
