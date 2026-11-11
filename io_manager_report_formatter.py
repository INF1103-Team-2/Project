"""io_manager_report_formatter.py - abstract base for every report file format."""

from abc import ABC, abstractmethod
from typing import Optional

from logic_manager_error_log import ErrorLog


class ReportFormatter(ABC):
    """Turns a fleet summary and its logs into the text of one report file.

    Open/Closed: a new format (e.g. CSV) is a new subclass; ReportManager,
    the CLI and the GUI do not change.
    """

    @abstractmethod
    def name(self) -> str:
        """Label shown to the user, e.g. "HTML"."""

    @abstractmethod
    def file_extension(self) -> str:
        """Extension including the dot, e.g. ".html"."""

    @abstractmethod
    def format(self, summary: dict, logs: list[ErrorLog], generated_at: str) -> str:
        """Return the complete report text."""

    # ----- helpers shared by every format ---------------------------------
    @staticmethod
    def sort_by_priority(logs: list[ErrorLog]) -> list[ErrorLog]:
        """Highest priority score first (same order as 'View all stored records')."""
        return sorted(logs, key=lambda log: -int(log.decision.score if log.decision else 0))

    @staticmethod
    def status_of(log: ErrorLog) -> str:
        """Plain-English notification status for one log."""
        decision = log.decision
        if decision is None:
            return "Not triaged"
        if decision.requires_human_review:
            return "Awaiting human review"
        if decision.suppressed_by:
            return "Bundled with earlier alert"
        if decision.notification_sent:
            return "Engineer notified"
        if decision.notify_now:
            return "Urgent - not delivered"
        return f"Scheduled {decision.scheduled_send_time.replace('T', ' ')}"

    @staticmethod
    def severity_of(log: ErrorLog) -> Optional[int]:
        """Severity the rules used (a human review overrides the AI)."""
        assessment = log.effective_assessment()
        return assessment.severity if assessment else None
