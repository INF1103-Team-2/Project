"""main_triage_app.py - the command-line menu (one of two front ends)."""

import logging
from datetime import datetime

from data_manager_phase2 import RecordRepository
from io_manager_console_ui import ConsoleUI
from io_manager_log_file_reader import LogFileReader
from io_manager_report_manager import ReportManager
from logic_manager_fleet_analyzer import FleetAnalyzer
from main_triage_pipeline import TriagePipeline

logger = logging.getLogger(__name__)

class TraigeApp:
    """Command-line front end: menu, prompts and results; work goes to the pipeline"""

    def __init__(self, ui: ConsoleUI, reader: LogFileReader, pipeline: TriagePipeline,
                 repository: RecordRepository, analyzer: FleetAnalyzer,
                 report_manager: ReportManager) -> None:
        self._ui: ConsoleUI = ui
        self._reader: LogFileReader = reader
        self._pipeline: TriagePipeline = pipeline
        self._repository: RecordRepository = repository
        self._analyzer: FleetAnalyzer = analyzer
        self._report_manager: ReportManager = report_manager

    def run(self) -> None:
        logger.info("Application started")
        stored = self._repository.load_all()
        self._ui.display_message(f"Loaded {len(stored)} previously processed record(s).")
        self._pipeline.dispatch_due_reports()
        self._pipeline.start_background_checks()

        actions = {
            "Enter a single error log": self._handle_single_entry,
            "Ingest a log file": self._handle_file_ingest,
            "View all stored records": self._handle_view_all,
            "Query stored records": self._handle_query,
            "Review pending records": self._handle_review_queue,
            "Fleet summary report": self._handle_summary,
            "Generate HTML / Markdown report": self._handle_generate_report,
        }

        try:
            while True:
                choice = self._ui.prompt_main_menu()
                if choice == "Exit":
                    self._ui.display_goodbye()
                    return
                action = actions.get(choice)
                if action is None:
                    self._ui.display_error("That option is not available.")
                    continue
                try:
                    action()
                except KeyboardInterrupt:
                    self._ui.display_message("Interrupted; returning to the menu.")
                except Exception as error:   # last line of defence: never crash the CLI
                    logger.exception("Unhandled error in %s", choice)
                    self._ui.display_error(
                        f"Something went wrong ({error}). Returning to the menu.")
        finally:
            self._pipeline.stop_background_checks()