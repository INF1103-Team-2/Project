"""main.py - entry point (INF1103 Phase 2, OOP).

    python main.py          command-line menu
    python main.py --gui    desktop window (Tkinter)

Builds one object of each class, connects them, and starts a front end.
No class lives in this file.
"""

import logging
import os
import sys

from dotenv import load_dotenv

from ai_manager_ai_client import AIClient
from data_manager_record_repository import RecordRepository
from io_manager_console_notifier import ConsoleNotifier
from io_manager_console_ui import ConsoleUI
from io_manager_html_report_formatter import HTMLReportFormatter
from io_manager_log_file_reader import LogFileReader
from io_manager_markdown_report_formatter import MarkdownReportFormatter
from io_manager_notifier import Notifier
from io_manager_output_view import OutputView
from io_manager_report_manager import ReportManager
from io_manager_telegram_notifier import TelegramNotifier
from logic_manager_alert_scheduler import AlertScheduler
from logic_manager_fleet_analyzer import FleetAnalyzer
from logic_manager_triage_engine import TriageEngine
from main_triage_app import TriageApp
from main_triage_pipeline import TriagePipeline

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def configure_logging() -> None:
    """Send diagnostic logging to a file so it never mixes with the CLI output."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    except OSError:
        handlers = []

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-14s %(message)s",
        handlers=handlers,
    )
    if not handlers:
        logging.disable(logging.CRITICAL)


def build_shared() -> dict:
    """Objects both front ends use."""
    return {
        "telegram": TelegramNotifier(
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        ),
        "ai": AIClient(
            base_url=os.getenv("AI_BASE_URL",
                               "https://generativelanguage.googleapis.com/v1beta/openai"),
            model=os.getenv("AI_MODEL", "gemini-2.0-flash"),
            api_key=os.getenv("AI_API_KEY", ""),
        ),
        "repository": RecordRepository(os.getenv("DATA_FILE", "processed_records.json")),
        "report_manager": ReportManager(
            output_dir=os.getenv("REPORT_DIR", "reports"),
            formatters=[HTMLReportFormatter(), MarkdownReportFormatter()],
        ),
    }


def build_pipeline(view: OutputView, screen_notifier: Notifier, shared: dict) -> TriagePipeline:
    return TriagePipeline(
        view=view,
        ai=shared["ai"],
        engine=TriageEngine(),
        scheduler=AlertScheduler(),
        repository=shared["repository"],
        notifiers=[screen_notifier, shared["telegram"]],   # screen first, then Telegram
        telegram=shared["telegram"],
    )


def build_console_app() -> TriageApp:
    shared = build_shared()
    ui = ConsoleUI()
    return TriageApp(
        ui=ui,
        reader=LogFileReader(),
        pipeline=build_pipeline(ui, ConsoleNotifier(ui), shared),
        repository=shared["repository"],
        analyzer=FleetAnalyzer(),
        report_manager=shared["report_manager"],
    )



def build_gui_app():
    """Imported lazily so the CLI (and Docker) never needs Tkinter."""
    from io_manager_gui_notifier import GuiNotifier
    from io_manager_gui_window import GuiWindow
    from main_gui_app import GuiApp

    shared = build_shared()
    window = GuiWindow()
    return GuiApp(
        window=window,
        reader=LogFileReader(),
        pipeline=build_pipeline(window, GuiNotifier(window), shared),
        repository=shared["repository"],
        analyzer=FleetAnalyzer(),
        report_manager=shared["report_manager"],
    )


def main() -> None:
    load_dotenv()          # AI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID from .env
    configure_logging()
    if "--gui" in sys.argv[1:]:
        try:
            app = build_gui_app()
        except ImportError:
            print("The GUI needs Tkinter, which is not installed here "
                  "(e.g. inside Docker). Run 'python main.py' for the menu.")
            return
        app.run()
    else:
        build_console_app().run()


if __name__ == "__main__":
    main()
