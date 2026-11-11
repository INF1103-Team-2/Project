"""io_manager_console_notifier.py - shows urgent alerts on the operator's screen."""

import logging

from io_manager_console_ui import ConsoleUI
from io_manager_notifier import Notifier
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class ConsoleNotifier(Notifier):
    """Implements Notifier by printing the alert through ConsoleUI."""

    def __init__(self, ui: ConsoleUI) -> None:
        self._ui: ConsoleUI = ui   # association: uses the UI, does not own it

    def notify_urgent(self, log: ErrorLog) -> tuple[bool, str]:
        self._ui.display_alert(self._format_alert(log))
        logger.info("Alert displayed for %s", log.log_id)
        # Showing it on screen does not reach an engineer, so delivered=False.
        return False, ""

    def _format_alert(self, log: ErrorLog) -> str:
        ai = log.ai_assessment
        decision = log.decision
        route = decision.route if decision else "alert"
        return (
            f"[{route.upper()}] {log.machine_id} ({log.machine_type})\n"
            f"Severity {ai.severity if ai else '?'}/5 | "
            f"priority {decision.score if decision else '?'}/100\n"
            f"Subsystem: {ai.machine_subsystem if ai else 'unknown'}\n"
            f"Likely cause: {ai.root_cause_hypothesis if ai else 'unknown'}\n"
            f"Action: {ai.recommended_action if ai else 'inspect device'}\n"
            f"Logged: {log.timestamp} | ref {log.log_id}"
        )
