"""io_manager_console_ui.py - every print() and input() in the program lives here."""

import logging
import os
from datetime import datetime
from typing import Callable, Optional

from io_manager_output_view import OutputView
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class ConsoleUI(OutputView):
    """Collects and validates user input, and shows results on the terminal."""

    MAX_NAME_LENGTH = 40
    DEFAULT_LOG_PATH = "sample_error_logs.txt"

    MENU_OPTIONS = (
        "Enter a single error log",
        "Ingest a log file",
        "View all stored records",
        "Query stored records",
        "Review pending records",
        "Fleet summary report",
        "Generate HTML / Markdown report",
        "Exit",
    )

    def __init__(self) -> None:
        self._line: str = "-" * 68

    # ======================================================================
    # Low-level prompt helpers
    # ======================================================================
    def _ask(self, prompt: str) -> Optional[str]:
        """Read one line; None means the user aborted (Ctrl-C / end of input)."""
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info("Input aborted by user")
            return None

    def _ask_required(self, prompt: str, max_length: int = MAX_NAME_LENGTH) -> Optional[str]:
        while True:
            value = self._ask(prompt)
            if value is None:
                return None
            if not value:
                print("  ! This field is required. Please enter a value.")
                continue
            if len(value) > max_length:
                print(f"  ! Too long (max {max_length} characters). Please shorten it.")
                continue
            return value

    def _ask_choice(self, prompt: str, options: tuple) -> Optional[str]:
        for index, option in enumerate(options, start=1):
            print(f"    {index}. {option}")
        while True:
            value = self._ask(prompt)
            if value is None:
                return None
            if not value.isdigit():
                print("  ! Please enter the number next to your choice.")
                continue
            choice = int(value)
            if not 1 <= choice <= len(options):
                print(f"  ! Please enter a number between 1 and {len(options)}.")
                continue
            return options[choice - 1]

    # ======================================================================
    # Input collection
    # ======================================================================
    def prompt_main_menu(self) -> str:
        print()
        print(self._line)
        print("  BIOMEDICAL EQUIPMENT ERROR LOG TRIAGE")
        print(self._line)
        return self._ask_choice("  Select an option: ", self.MENU_OPTIONS) or "Exit"

    def prompt_error_log(self) -> Optional[ErrorLog]:
        """Collect one error log; every field is validated before it leaves here."""
        print()
        print("  New error log (blank timestamp = now, Ctrl-C to cancel)")

        while True:
            machine_id = self._ask("  Machine ID (e.g. CT-114): ")
            if machine_id is None:
                return None
            if ErrorLog.MACHINE_ID_PATTERN.match(machine_id):
                break
            print("  ! Machine ID must be 3-20 characters: "
                  "letters, digits, hyphens or underscores.")

        while True:
            error_code = self._ask("  Error code (e.g. E102): ")
            if error_code is None:
                return None
            if ErrorLog.ERROR_CODE_PATTERN.match(error_code):
                break
            print("  ! Error code must be 2-20 characters: "
                  "letters, digits, hyphens or underscores.")

        print("  Machine type:")
        machine_type = self._ask_choice("  Select type: ", ErrorLog.MACHINE_TYPES)
        if machine_type is None:
            return None

        while True:
            raw_timestamp = self._ask("  Timestamp [YYYY-MM-DDTHH:MM:SS]: ")
            if raw_timestamp is None:
                return None
            if not raw_timestamp:
                timestamp = datetime.now().strftime(ErrorLog.TIME_FORMAT)
                break
            parsed = ErrorLog.parse_timestamp(raw_timestamp)
            if parsed:
                timestamp = parsed
                break
            print("  ! Could not read that date. Try 2026-09-14T03:12:44.")

        reported_by = self._ask_required("  Reported by: ")
        if reported_by is None:
            return None

        while True:
            raw_message = self._ask("  Error message from the machine: ")
            if raw_message is None:
                return None
            if len(raw_message) < ErrorLog.MIN_MESSAGE_LENGTH:
                print(f"  ! Too short - give at least {ErrorLog.MIN_MESSAGE_LENGTH} "
                      "characters of detail.")
                continue
            if len(raw_message) > ErrorLog.MAX_MESSAGE_LENGTH:
                print(f"  ! Too long (max {ErrorLog.MAX_MESSAGE_LENGTH} characters).")
                continue
            break

        return ErrorLog(machine_id, error_code, machine_type, timestamp,
                        reported_by, raw_message)

    def prompt_file_path(self) -> Optional[str]:
        print()
        print("  Expected line format:")
        print("    timestamp | machine_id | error_code | machine_type | error message")
        while True:
            path = self._ask(f"  Path to log file [{self.DEFAULT_LOG_PATH}]: ")
            if path is None:
                return None
            if not path:
                path = self.DEFAULT_LOG_PATH
            if not os.path.isfile(path):
                print(f"  ! No file found at '{path}'. Check the path and try again.")
                continue
            if not os.access(path, os.R_OK):
                print(f"  ! '{path}' exists but cannot be read.")
                continue
            return path

    def prompt_query_filter(self) -> Optional[Callable[[ErrorLog], bool]]:
        """Build a filter for RecordRepository.query() from the user's choice."""
        filters = (
            "Immediate escalations only",
            "Records flagged as a patient safety risk",
            "Records needing human review",
            "By machine ID",
        )
        print()
        print("  Query stored records:")
        choice = self._ask_choice("  Select a filter: ", filters)
        if choice is None:
            return None

        if choice == "Immediate escalations only":
            return lambda log: (log.decision is not None
                                and log.decision.route == "immediate_escalation")
        if choice == "Records flagged as a patient safety risk":
            # Bug fix: Phase 1 crashed here when a record had no AI assessment.
            return lambda log: (log.ai_assessment is not None
                                and log.ai_assessment.patient_safety_risk)
        if choice == "Records needing human review":
            return lambda log: (log.decision is not None
                                and log.decision.requires_human_review)

        machine_id = self._ask_required("  Machine ID to search for: ")
        if machine_id is None:
            return None
        wanted = machine_id.upper()
        return lambda log: log.machine_id.upper() == wanted

    def confirm(self, question: str) -> bool:
        answer = self._ask(f"  {question} [y/N]: ")
        return answer is not None and answer.lower() in ("y", "yes")

    def prompt_review_action(self, can_approve_ai: bool) -> str:
        actions = (
            ("Approve AI severity", "Enter severity manually", "Leave pending", "Stop reviewing")
            if can_approve_ai
            else ("Enter severity manually", "Leave pending", "Stop reviewing")
        )
        return self._ask_choice("  Review action: ", actions) or "Stop reviewing"

    def prompt_report_format(self, format_names: list[str]) -> Optional[str]:
        """Ask which report format to generate (e.g. HTML or Markdown)."""
        print()
        print("  Report format:")
        return self._ask_choice("  Select a format: ", tuple(format_names))

    def prompt_review_severity(self) -> Optional[int]:
        choice = self._ask_choice(
            "  Human-assessed severity: ",
            ("1 - Minimal", "2 - Low", "3 - Moderate", "4 - High", "5 - Critical"),
        )
        if choice is None:
            return None
        return int(choice[0])

    def prompt_review_safety_risk(self) -> Optional[bool]:
        choice = self._ask_choice("  Patient-safety risk? ", ("Yes", "No"))
        if choice is None:
            return None
        return choice == "Yes"

    # ======================================================================
    # Output display
    # ======================================================================
    def display_message(self, text: str) -> None:
        print(f"  {text}")

    def display_error(self, text: str) -> None:
        print(f"  ! {text}")

    def display_alert(self, text: str) -> None:
        print()
        print("  *** ALERT ***")
        for line in text.splitlines():
            print(f"    {line}")

    def display_record(self, log: ErrorLog) -> None:
        """Show one log in full: input, AI assessment, human review and decision."""
        ai = log.ai_assessment
        decision = log.decision

        print()
        print(self._line)
        print(f"  {log.log_id}  |  {log.machine_id}  |  {log.machine_type}")
        print(f"  Logged at : {log.timestamp}")
        print(f"  Reported  : {log.reported_by}")
        print(f"  Error code: {log.error_code}")
        print(f"  Message   : {log.raw_message}")

        if ai is not None:
            print("  --- AI assessment ---")
            print(f"  Subsystem      : {ai.machine_subsystem}")
            print(f"  Severity       : {ai.severity}/5")
            print(f"  Safety risk    : {'YES' if ai.patient_safety_risk else 'no'}")
            print(f"  Recurring      : {'YES' if ai.recurrence_indicator else 'no'}")
            print(f"  Likely cause   : {ai.root_cause_hypothesis}")
            print(f"  Action         : {ai.recommended_action}")
            print(f"  Confidence     : {ai.confidence()}")
        else:
            print(f"  --- AI assessment unavailable: {log.ai_error or 'unknown reason'}")

        human = log.human_assessment
        if human is not None:
            print("  --- Human-approved assessment ---")
            print(f"  Severity       : {human.severity}/5")
            print(f"  Safety risk    : {'YES' if human.patient_safety_risk else 'no'}")
            print(f"  Reviewed at    : {human.reviewed_at}")

        if decision is not None:
            print("  --- Triage decision ---")
            print(f"  Route          : {decision.route}")
            print(f"  Priority score : {decision.score}/100")
            print(f"  Notify now     : {'YES' if decision.notify_now else 'no'}")
            print(f"  Alert due      : {decision.scheduled_send_time}")
            print(f"  Human review   : {'YES' if decision.requires_human_review else 'no'}")
            rules = decision.rules_fired
            print(f"  Rules fired    : {', '.join(rules) if rules else 'none'}")
        print(self._line)

    def display_list(self, logs: list[ErrorLog]) -> None:
        print()
        if not logs:
            print("  No records to show.")
            return
        header = f"  {'LOG ID':<14}{'MACHINE':<14}{'SEV':<5}{'SCORE':<7}ROUTE"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for log in logs:
            severity = log.ai_assessment.severity if log.ai_assessment else "-"
            score = log.decision.score if log.decision else "-"
            route = log.decision.route if log.decision else "-"
            print(f"  {str(log.log_id):<14}"
                  f"{str(log.machine_id):<14}"
                  f"{str(severity):<5}"
                  f"{str(score):<7}"
                  f"{route}")
        print(f"  {len(logs)} record(s).")

    def display_result(self, log: ErrorLog) -> None:
        route = log.decision.route if log.decision else "unknown"
        score = log.decision.score if log.decision else "-"
        print(f"  -> {log.machine_id}: {route} (score {score}/100)")

    def display_batch_problems(self, problems: list[str]) -> None:
        if not problems:
            return
        print()
        print(f"  {len(problems)} line(s) were skipped:")
        for problem in problems[:10]:
            print(f"    - {problem}")
        if len(problems) > 10:
            print(f"    ... and {len(problems) - 10} more (see logs/app.log)")

    def display_summary(self, summary: dict) -> None:
        print()
        print(self._line)
        print("  FLEET SUMMARY")
        print(self._line)
        print(f"  Records stored        : {summary.get('total', 0)}")
        print(f"  Patient safety flags  : {summary.get('safety_risk_count', 0)}")
        print(f"  Needing human review  : {summary.get('human_review_count', 0)}")
        print(f"  Mean priority score   : {summary.get('mean_score', 0)}")

        by_route = summary.get("by_route") or {}
        if by_route:
            print("  By route:")
            for route, count in sorted(by_route.items()):
                print(f"    {route:<32}{count}")

        repeat_offenders = summary.get("repeat_offenders") or []
        if repeat_offenders:
            print("  Machines with repeat faults:")
            for machine_id, count in repeat_offenders:
                print(f"    {machine_id:<32}{count} logs")
        print(self._line)

    def display_goodbye(self) -> None:
        print()
        print("  Done. Records saved. Goodbye.")
