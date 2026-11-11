"""main_gui_app.py - the desktop front end: decides what each button does."""

import logging
from datetime import datetime
from typing import Callable, Optional

from data_manager_record_repository import RecordRepository
from io_manager_gui_window import GuiWindow
from io_manager_log_file_reader import LogFileReader
from io_manager_report_manager import ReportManager
from logic_manager_error_log import ErrorLog
from logic_manager_fleet_analyzer import FleetAnalyzer
from main_triage_pipeline import TriagePipeline

logger = logging.getLogger(__name__)


class GuiApp:
    """GUI controller. Uses the same TriagePipeline as the console app, so the
    business rules, alerts and storage behave identically in both front ends."""

    def __init__(self, window: GuiWindow, reader: LogFileReader, pipeline: TriagePipeline,
                 repository: RecordRepository, analyzer: FleetAnalyzer,
                 report_manager: ReportManager) -> None:
        self._window: GuiWindow = window
        self._reader: LogFileReader = reader
        self._pipeline: TriagePipeline = pipeline
        self._repository: RecordRepository = repository
        self._analyzer: FleetAnalyzer = analyzer
        self._report_manager: ReportManager = report_manager
        # Open/Closed: a new filter is one new entry here.
        self._filters: dict[str, Callable[[ErrorLog], bool]] = {
            "All records": lambda log: True,
            "Immediate escalations": lambda log: (
                log.decision is not None and log.decision.route == "immediate_escalation"),
            "Patient safety risk": lambda log: (
                log.ai_assessment is not None and log.ai_assessment.patient_safety_risk),
            "Needing human review": lambda log: (
                log.decision is not None and log.decision.requires_human_review),
        }

    def run(self) -> None:
        logger.info("GUI started")
        self._window.bind_actions({
            "add": self._on_add,
            "import": self._on_import,
            "review": self._on_review,
            "report": self._on_report,
            "refresh": self._refresh,
            "filter": self._refresh,
            "select": self._window.show_details,
            "close": self._pipeline.stop_background_checks,
        })
        stored = self._repository.load_all()
        self._window.display_message(f"Loaded {len(stored)} previously processed record(s).")
        self._refresh()
        self._window.run_background("Checking due reports...",
                                    self._pipeline.dispatch_due_reports,
                                    lambda _result: self._refresh())
        self._pipeline.start_background_checks()
        self._window.run()

    # ======================================================================
    # Button handlers
    # ======================================================================
    def _refresh(self, select_id: Optional[str] = None) -> None:
        all_logs = self._repository.load_all()
        filter_name, machine = self._window.current_filter()
        predicate = self._filters.get(filter_name, self._filters["All records"])
        shown = [log for log in all_logs
                 if predicate(log) and (not machine or log.machine_id.upper() == machine.upper())]
        shown.sort(key=lambda log: -int(log.decision.score if log.decision else 0))
        self._window.show_records(shown)
        self._window.show_summary(self._analyzer.summarise(all_logs))
        self._window.set_pending_count(len(self._pipeline.pending_reviews()))
        if select_id:
            self._window.select(select_id)

    def _on_add(self) -> None:
        log = self._window.ask_new_log()
        if log is None:
            return
        self._window.display_message("Sending to the AI for assessment...")
        self._process([log])

    def _on_import(self) -> None:
        path = self._window.ask_file_path()
        if path is None:
            return
        logs, problems = self._reader.read(path)
        if problems:
            self._window.display_message(f"{len(problems)} line(s) were skipped:")
            for problem in problems[:10]:
                self._window.display_message(f"  - {problem}")
        if not logs:
            self._window.display_error(LogFileReader.INVALID_FILE_MESSAGE)
            self._window.show_error("Import failed", LogFileReader.INVALID_FILE_MESSAGE)
            return
        self._window.display_message(f"Processing {len(logs)} record(s)...")
        self._process(logs)

    def _process(self, logs: list[ErrorLog]) -> None:
        """AI calls are slow, so the pipeline runs on a worker thread."""
        def done(processed: Optional[list[ErrorLog]]) -> None:
            first = processed[0].log_id if processed else None
            self._refresh(select_id=first)
        self._window.run_background(f"Assessing {len(logs)} log(s) with AI...",
                                    lambda: self._pipeline.process_batch(logs, datetime.now()),
                                    done)

    def _on_review(self) -> None:
        pending = self._pipeline.pending_reviews()
        if not pending:
            self._window.show_info("Human review", "There are no records awaiting human review.")
            return
        self._window.display_message(f"{len(pending)} record(s) awaiting human review.")
        self._review_next(pending, 0)

    def _review_next(self, pending: list[ErrorLog], index: int) -> None:
        """One dialog per record; saving may send Telegram, so it runs in the background."""
        if index >= len(pending):
            self._refresh()
            return
        log = pending[index]
        self._window.select(log.log_id)
        self._window.show_details(log)
        answer = self._window.ask_review(log, f"({index + 1} of {len(pending)})")
        if answer is None:
            self._refresh()
            return
        if answer == "skip":
            self._review_next(pending, index + 1)
            return
        severity, safety_risk, source = answer
        self._window.run_background(
            "Saving review...",
            lambda: self._pipeline.apply_review(log, severity, safety_risk, source),
            lambda _ok: self._review_next(pending, index + 1),
        )

    def _on_report(self) -> None:
        format_name = self._window.ask_report_format(self._report_manager.available_formats())
        if format_name is None:
            return
        path = self._report_manager.generate(self._repository.load_all(), format_name)
        if path is None:
            self._window.display_error("The report could not be saved.")
            self._window.show_error("Report", "The report could not be saved.")
            return
        self._window.display_message(f"Report saved to {path}")
        self._window.offer_open(path)
