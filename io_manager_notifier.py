"""io_manager_notifier.py - interface for anything that can raise an urgent alert."""

from abc import ABC, abstractmethod

from logic_manager_error_log import ErrorLog


class Notifier(ABC):
    """Interface: every notifier can announce an urgent error log.

    notify_urgent() returns (delivered, info):
      delivered - True only if an engineer was actually reached remotely,
                  which is when the log may be marked as sent.
      info      - a status line for the operator ("" when there is nothing to say).
    """

    @abstractmethod
    def notify_urgent(self, log: ErrorLog) -> tuple[bool, str]:
        """Announce an urgent error log."""
