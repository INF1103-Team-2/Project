"""io_manager_report_manager.py - builds a fleet report and saves it to a file."""

import logging
import os
from datetime import datetime
from typing import Optional

from io_manager_report_formatter import ReportFormatter
from logic_manager_error_log import ErrorLog
from logic_manager_fleet_analyzer import FleetAnalyzer

logger = logging.getLogger(__name__)


class ReportManager:
    """Summarises the logs (FleetAnalyzer), formats them, and writes the file."""

    def __init__(self, output_dir: str, formatters: list[ReportFormatter]) -> None:
        self._analyzer: FleetAnalyzer = FleetAnalyzer()          # composition: owns it
        self._formatters: list[ReportFormatter] = list(formatters)   # aggregation
        self._output_dir: str = output_dir

    def available_formats(self) -> list[str]:
        return [formatter.name() for formatter in self._formatters]

    def generate(self, logs: list[ErrorLog], format_name: str,
                 now: Optional[datetime] = None) -> Optional[str]:
        """Write the report and return its path, or None if it could not be saved."""
        formatter = self._find(format_name)
        if formatter is None:
            logger.error("Unknown report format %s", format_name)
            return None
        now = now or datetime.now()
        # Polymorphism: HTML or Markdown, ReportManager does the same thing.
        text = formatter.format(self._analyzer.summarise(logs), logs,
                                now.strftime("%Y-%m-%d %H:%M"))
        path = os.path.join(self._output_dir,
                            f"report_{now.strftime('%Y%m%d_%H%M%S')}{formatter.file_extension()}")
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            logger.error("Could not write report %s: %s", path, error)
            return None
        logger.info("Report written to %s", path)
        return path

    def _find(self, format_name: str) -> Optional[ReportFormatter]:
        for formatter in self._formatters:
            if formatter.name() == format_name:
                return formatter
        return None
