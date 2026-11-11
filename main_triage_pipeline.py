"""main_triage_pipeline.py - the processing pipeline shared by the CLI and the GUI.

    file / form -> AIClient -> TriageEngine + AlertScheduler -> Notifiers -> RecordRepository
"""

import logging
import threading
from datetime import datetime
from typing import Optional

from ai_manager_ai_client import AIClient
from data_manager_phase2 import RecordRepository
from io_manager_notifier import Notifier
from io_manager_output_view import OutputView
from io_manager_telegram_notifier import TelegramNotifier
from logic_manager_alert_scheduler import AlertScheduler
from logic_manager_error_log import ErrorLog
from logic_manager_triage_engine import TriageEngine

logger = logging.getLogger(__name__)

class TriagePipeline:
    """
    Runs logs through AI -> rules -> alerts -> storage.
    It has no menu and never calls print(): progress goes to an OutputView,
    so the console and the GUI share exactly the same business flow.
    """

    DUE_REPORT_CHECK_SECONDS = 60

    def __init__(self, view: OutputView, ai: AIClient, engine: TriageEngine,
                 scheduler: AlertScheduler, repository: RecordRepository,
                 notifiers: list[Notifier], telegram: TelegramNotifier) -> None:
        self._view: OutputView = view
        self._ai: AIClient = ai
        self._engine: TriageEngine = engine
        self._scheduler: AlertScheduler = scheduler
        self._repository: RecordRepository = repository
        self._notifiers: list[Notifier] = list(notifiers)   # aggregation
        self._telegram: TelegramNotifier = telegram
        self._stop_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ======================================================================
    # Processing
    # ======================================================================
    def process_batch(self, logs: list[ErrorLog], now: datetime) -> list[ErrorLog]:
        """AI enrichment -> business rules -> notification -> storage."""
        stored_by_id = {log.log_id: log for log in self._repository.load_all()}

        # The same log line uploaded twice has the same log_id; process it once.
        unique: dict[str, ErrorLog] = {}
        for log in logs:
            unique.setdefault(log.log_id, log)

        processed: list[ErrorLog] = []
        for log in unique.values():
            self._ai.enrich(log)
            self._engine.evaluate(log, now=now)
            previous = stored_by_id.get(log.log_id)
            if previous and previous.decision and previous.decision.review_notification_sent:
                log.decision.mark_review_notified()
            processed.append(log)

        # Rule 3: only the first of a burst of identical errors notifies.
        self._scheduler.bundle_repeats(processed)

        # Rules 1 and 5: urgent now; records needing human review never go out.
        for log in processed:
            if self._scheduler.should_send_now(log):
                self._send_urgent_alert(log)

        for log in processed:
            if not self._repository.save(log):
                self._view.display_error(f"Could not save record {log.log_id}.")
                self._view.display_result(log)
                continue

            decision = log.decision
            if decision.requires_human_review and not decision.review_notification_sent:
                ok, info = self._telegram.send_review_request(log)
                self._view.display_message(f"Human review Telegram: {info}")
                if ok:
                    decision.mark_review_notified()
                    if not self._repository.save(log):
                        self._view.display_error(
                            "Human review notification was sent, but its status "
                            f"could not be saved for {log.log_id}."
                        )
            self._view.display_result(log)
        return processed       