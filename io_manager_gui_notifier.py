"""io_manager_gui_notifier.py - urgent alerts as a pop-up in the desktop window."""

import logging

from io_manager_gui_window import GuiWindow
from io_manager_notifier import Notifier
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class GuiNotifier(Notifier):
    """Implements Notifier for the GUI: a warning pop-up plus an activity line.

    The pipeline treats it exactly like ConsoleNotifier (LSP): it shows the alert
    and returns delivered=False, because a pop-up does not reach an engineer.
    """

    def __init__(self, window: GuiWindow) -> None:
        self._window: GuiWindow = window   # association: uses the window, does not own it

    def notify_urgent(self, log: ErrorLog) -> tuple[bool, str]:
        self._window.show_alert(self._format_alert(log))
        logger.info("Alert shown in GUI for %s", log.log_id)
        return False, ""

    def _format_alert(self, log: ErrorLog) -> str:
        assessment = log.effective_assessment()
        ai = log.ai_assessment
        decision = log.decision
        return (
            f"{log.machine_id} ({log.machine_type}) needs attention now.\n\n"
            f"Severity: {assessment.severity if assessment else '?'}/5    "
            f"Priority: {decision.score if decision else '?'}/100\n"
            f"Patient safety risk: "
            f"{'YES' if assessment and assessment.patient_safety_risk else 'no'}\n"
            f"Subsystem: {ai.machine_subsystem if ai else 'unknown'}\n"
            f"Action: {ai.recommended_action if ai else 'Inspect the machine'}\n\n"
            f"Logged {log.timestamp.replace('T', ' ')} · ref {log.log_id}"
        )
