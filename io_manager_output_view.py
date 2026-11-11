"""io_manager_output_view.py - interface for showing pipeline progress to the user."""

from abc import ABC, abstractmethod

from logic_manager_error_log import ErrorLog


class OutputView(ABC):
    """Interface: the three things the processing pipeline needs to show.

    ConsoleUI prints them; GuiWindow puts them in its activity panel.
    The pipeline only knows this interface (DIP), so it works with either.
    """

    @abstractmethod
    def display_message(self, text: str) -> None:
        """Show an informational line."""

    @abstractmethod
    def display_error(self, text: str) -> None:
        """Show a problem without stopping the program."""

    @abstractmethod
    def display_result(self, log: ErrorLog) -> None:
        """Show the outcome of processing one log."""
