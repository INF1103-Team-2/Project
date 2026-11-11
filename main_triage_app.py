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

    # ======================================================================
    # Menu actions
    # ======================================================================
    def _handle_single_entry(self) -> None:
        log = self._ui.prompt_error_log()
        if log is None:
            self._ui.display_message("Cancelled")
            return    
        self._ui.display_message("Sending to the AI for assessment...")
        processed = self._pipeline.process_batch([log], datetime.now())
        self._ui.display_record(processed[0])

    def _handle_file_ingest(self) -> None:
        path = self._ui.prompt_file_path()
        if path is None:
            self._ui.display_message("Cancelled.")
            return

        logs, problems = self._reader.read(path)
        self._ui.display_batch_problems(problems)
        if not logs:
            self._ui.display_error(LogFileReader.INVALID_FILE_MESSAGE)
            return

        self._ui.display_message(f"Processing {len(logs)} record(s)...")
        processed = self._pipeline.process_batch(logs, datetime.now())
        self._ui.display_list(processed)

    def _handle_view_all(self) -> None:
        logs = self._repository.load_all()
        logs.sort(key=lambda log: -int(log.decision.score if log.decision else 0))
        self._ui.display_list(logs)
        if logs and self._ui.confirm("Show the full detail of the top record?"):
            self._ui.display_record(logs[0])

    def _handle_query(self) -> None:
        predicate = self._ui.prompt_query_filter()
        if predicate is None:
            self._ui.display_message("Cancelled.")
            return
        self._ui.display_list(self._repository.query(predicate))

    def _handle_review_queue(self) -> None:
        """Let an operator approve the AI severity or enter their own."""
        pending = self._pipeline.pending_reviews()
        if not pending:
            self._ui.display_message("There are no records awaiting human review.")
            return

        self._ui.display_message(f"{len(pending)} record(s) awaiting human review.")
        for log in pending:
            self._ui.display_record(log)
            ai = log.ai_assessment
            action = self._ui.prompt_review_action(can_approve_ai=ai is not None)
            if action == "Stop reviewing":
                break
            if action == "Leave pending":
                continue

            if action == "Approve AI severity":
                severity, safety_risk, source = ai.severity, ai.patient_safety_risk, "ai_approved"
            else:
                severity = self._ui.prompt_review_severity()
                if severity is None:
                    self._ui.display_message("Review cancelled; record remains pending.")
                    continue
                safety_risk = self._ui.prompt_review_safety_risk()
                if safety_risk is None:
                    self._ui.display_message("Review cancelled; record remains pending.")
                    continue
                source = "human_assessed"
            self._pipeline.apply_review(log, severity, safety_risk, source)

    def _handle_generate_report(self) -> None:
        self._ui.display_summary(self._analyzer.summarise(self._repository.load_all()))

    def _handle_generate_report(self) -> None:
        """New feature: save the fleet report as an HTML or Markdown file."""
        format_name = self._ui.prompt_report_format(self._report_manager.available_formats())
        if format_name is None:
            self._ui.display_message("Cancelled.")
            return
        path = self._report_manager.generate(self._repository.load_all(), format_name)
        if path is None:
            self._ui.display_error("The report could not be saved.")
        else:
            self._ui.display_message(f"Report saved to {path}")