"""io_manager.py - Input layer (INF1103 Phase 1).

All boundaries between the system and the outside world live in this module.
Every print() and input() call in the entire codebase is in this file, and so is
the Telegram alert send, because that is also a user-facing output boundary.

This module never imports the other managers. It only collects, validates and
displays. Orchestration happens in main.py.
"""

import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

# --- Validation rules for user-supplied input -------------------------------
MACHINE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{2,19}$")
MIN_MESSAGE_LENGTH = 10
MAX_MESSAGE_LENGTH = 500
MAX_NAME_LENGTH = 40

MACHINE_TYPES = (
    "infusion_pump",
    "patient_monitor",
    "ventilator",
    "imaging_system",
    "dialysis_machine",
    "sterilisation_unit",
    "other",
)

# --- Log file ingestion format ---------------------------------------------
# timestamp | machine_id | machine_type | raw_message
LOG_FIELD_SEPARATOR = "|"
EXPECTED_LOG_FIELDS = 4

# --- Telegram output boundary ----------------------------------------------
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_TIMEOUT_SECONDS = 15

LINE = "-" * 68


# ===========================================================================
# Low-level prompt helpers
# ===========================================================================
def _ask(prompt: str) -> Optional[str]:
    """Read one line from the user.

    Returns the stripped string, or None if the input stream closed or the
    user pressed Ctrl-C. Callers treat None as "abort this operation".
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        logger.info("Input aborted by user")
        return None


def _ask_required(prompt: str, max_length: int = MAX_NAME_LENGTH) -> Optional[str]:
    """Prompt until the user supplies a non-empty value within the length limit."""
    while True:
        value = _ask(prompt)
        if value is None:
            return None
        if not value:
            print("  ! This field is required. Please enter a value.")
            continue
        if len(value) > max_length:
            print(f"  ! Too long (max {max_length} characters). Please shorten it.")
            continue
        return value


def _ask_choice(prompt: str, options: tuple) -> Optional[str]:
    """Present a numbered list and return the chosen option string."""
    for index, option in enumerate(options, start=1):
        print(f"    {index}. {option}")
    while True:
        value = _ask(prompt)
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


def _parse_timestamp(value: str) -> Optional[str]:
    """Validate an ISO-8601 timestamp and return it normalised, else None."""
    cleaned = value.replace("Z", "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return None


def make_log_id(machine_id: str, timestamp: str, raw_message: str) -> str:
    """Build a stable, repeatable id for a log entry.

    Hashing the content (rather than using a counter or the clock) means the
    same input always produces the same id, which is what lets data_manager
    de-duplicate and satisfy the 'same output across runs' constraint.
    """
    payload = f"{machine_id}|{timestamp}|{raw_message}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


# ===========================================================================
# Input collection
# ===========================================================================
def prompt_main_menu() -> Optional[str]:
    """Display the main menu and return the selected action key."""
    actions = (
        "Enter a single error log",
        "Ingest a log file",
        "View all stored records",
        "Query stored records",
        "Fleet summary report",
        "Exit",
    )
    print()
    print(LINE)
    print("  BIOMEDICAL EQUIPMENT ERROR LOG TRIAGE")
    print(LINE)
    choice = _ask_choice("  Select an option: ", actions)
    if choice is None:
        return "Exit"
    return choice


def prompt_error_log() -> Optional[dict]:
    """Collect one error log from the user and return a clean, typed dict.

    Every field is validated here. No raw, unchecked string leaves this
    function - ai_manager receives a dict it can trust.
    """
    print()
    print("  New error log (blank timestamp = now, Ctrl-C to cancel)")

    while True:
        machine_id = _ask("  Machine ID (e.g. PUMP-114): ")
        if machine_id is None:
            return None
        if MACHINE_ID_PATTERN.match(machine_id):
            break
        print("  ! Machine ID must be 3-20 characters: letters, digits or hyphens.")

    print("  Machine type:")
    machine_type = _ask_choice("  Select type: ", MACHINE_TYPES)
    if machine_type is None:
        return None

    while True:
        raw_timestamp = _ask("  Timestamp [YYYY-MM-DDTHH:MM:SS]: ")
        if raw_timestamp is None:
            return None
        if not raw_timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            break
        parsed = _parse_timestamp(raw_timestamp)
        if parsed:
            timestamp = parsed
            break
        print("  ! Could not read that date. Try 2026-09-14T03:12:44.")

    reported_by = _ask_required("  Reported by: ")
    if reported_by is None:
        return None

    while True:
        raw_message = _ask("  Error message from the machine: ")
        if raw_message is None:
            return None
        if len(raw_message) < MIN_MESSAGE_LENGTH:
            print(f"  ! Too short - give at least {MIN_MESSAGE_LENGTH} characters of detail.")
            continue
        if len(raw_message) > MAX_MESSAGE_LENGTH:
            print(f"  ! Too long (max {MAX_MESSAGE_LENGTH} characters).")
            continue
        break

    return {
        "log_id": make_log_id(machine_id, timestamp, raw_message),
        "machine_id": machine_id,
        "machine_type": machine_type,
        "timestamp": timestamp,
        "reported_by": reported_by,
        "raw_message": raw_message,
    }


def prompt_file_path() -> Optional[str]:
    """Ask for a log file path and confirm it is readable before returning it."""
    print()
    print("  Expected line format:")
    print("    timestamp | machine_id | machine_type | error message")
    while True:
        path = _ask("  Path to log file [sample_data/sample_error_logs.txt]: ")
        if path is None:
            return None
        if not path:
            path = "sample_data/sample_error_logs.txt"
        if not os.path.isfile(path):
            print(f"  ! No file found at '{path}'. Check the path and try again.")
            continue
        if not os.access(path, os.R_OK):
            print(f"  ! '{path}' exists but cannot be read.")
            continue
        return path


def read_log_file(path: str) -> tuple:
    """Read a machine log file into clean record dicts.

    Returns (records, problems). A malformed line is skipped and reported, not
    fatal - one bad line must never stop the batch.
    """
    records: list = []
    problems: list = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as error:
        logger.error("Could not read log file %s: %s", path, error)
        return [], [f"File could not be opened: {error}"]

    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue

        parts = [part.strip() for part in text.split(LOG_FIELD_SEPARATOR)]
        if len(parts) < EXPECTED_LOG_FIELDS:
            problems.append(f"Line {number}: expected {EXPECTED_LOG_FIELDS} fields, got {len(parts)}")
            continue

        raw_timestamp, machine_id, machine_type, *message_parts = parts
        raw_message = LOG_FIELD_SEPARATOR.join(message_parts).strip()

        timestamp = _parse_timestamp(raw_timestamp)
        if timestamp is None:
            problems.append(f"Line {number}: unreadable timestamp '{raw_timestamp}'")
            continue
        if not MACHINE_ID_PATTERN.match(machine_id):
            problems.append(f"Line {number}: invalid machine id '{machine_id}'")
            continue
        if len(raw_message) < MIN_MESSAGE_LENGTH:
            problems.append(f"Line {number}: message too short to triage")
            continue

        records.append({
            "log_id": make_log_id(machine_id, timestamp, raw_message),
            "machine_id": machine_id,
            "machine_type": machine_type if machine_type in MACHINE_TYPES else "other",
            "timestamp": timestamp,
            "reported_by": "log_file_import",
            "raw_message": raw_message[:MAX_MESSAGE_LENGTH],
        })

    logger.info("Read %d records and %d problem lines from %s", len(records), len(problems), path)
    return records, problems


def prompt_query_filter() -> Optional[Callable]:
    """Build a filter function for data_manager.query() from user choices."""
    filters = (
        "Immediate escalations only",
        "Records flagged as a patient safety risk",
        "Records needing human review",
        "By machine ID",
    )
    print()
    print("  Query stored records:")
    choice = _ask_choice("  Select a filter: ", filters)
    if choice is None:
        return None

    if choice == "Immediate escalations only":
        return lambda record: record.get("decision", {}).get("route") == "immediate_escalation"
    if choice == "Records flagged as a patient safety risk":
        return lambda record: bool(record.get("ai", {}).get("patient_safety_risk"))
    if choice == "Records needing human review":
        return lambda record: bool(record.get("decision", {}).get("requires_human_review"))

    machine_id = _ask_required("  Machine ID to search for: ")
    if machine_id is None:
        return None
    wanted = machine_id.upper()
    return lambda record: record.get("machine_id", "").upper() == wanted


def confirm(question: str) -> bool:
    """Ask a yes/no question. Anything other than an explicit yes is a no."""
    answer = _ask(f"  {question} [y/N]: ")
    return answer is not None and answer.lower() in ("y", "yes")


# ===========================================================================
# Output display
# ===========================================================================
def display_message(text: str) -> None:
    """Show a single informational line."""
    print(f"  {text}")


def display_error(text: str) -> None:
    """Show a problem to the user without crashing the program."""
    print(f"  ! {text}")


def display_record(record: dict) -> None:
    """Show one record in full, including AI enrichment and the decision."""
    ai = record.get("ai") or {}
    decision = record.get("decision") or {}

    print()
    print(LINE)
    print(f"  {record.get('log_id', '?')}  |  {record.get('machine_id', '?')}"
          f"  |  {record.get('machine_type', '?')}")
    print(f"  Logged at : {record.get('timestamp', '?')}")
    print(f"  Reported  : {record.get('reported_by', '?')}")
    print(f"  Message   : {record.get('raw_message', '')}")

    if ai:
        print("  --- AI assessment ---")
        print(f"  Subsystem      : {ai.get('machine_subsystem', '?')}")
        print(f"  Severity       : {ai.get('severity', '?')}/5")
        print(f"  Safety risk    : {'YES' if ai.get('patient_safety_risk') else 'no'}")
        print(f"  Recurring      : {'YES' if ai.get('recurrence_indicator') else 'no'}")
        print(f"  Likely cause   : {ai.get('root_cause_hypothesis', '?')}")
        print(f"  Action         : {ai.get('recommended_action', '?')}")
        print(f"  Confidence     : {ai.get('confidence', '?')}")
    else:
        print(f"  --- AI assessment unavailable: {record.get('ai_error', 'unknown reason')}")

    if decision:
        print("  --- Triage decision ---")
        print(f"  Route          : {decision.get('route', '?')}")
        print(f"  Priority score : {decision.get('score', '?')}/100")
        print(f"  Notify now     : {'YES' if decision.get('notify_now') else 'no'}")
        print(f"  Alert due      : {decision.get('scheduled_send_time', '-')}")
        print(f"  Human review   : {'YES' if decision.get('requires_human_review') else 'no'}")
        rules = decision.get("rules_fired") or []
        print(f"  Rules fired    : {', '.join(rules) if rules else 'none'}")
    print(LINE)


def display_list(records: list) -> None:
    """Show a compact table of records."""
    print()
    if not records:
        print("  No records to show.")
        return
    header = f"  {'LOG ID':<14}{'MACHINE':<14}{'SEV':<5}{'SCORE':<7}ROUTE"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for record in records:
        ai = record.get("ai") or {}
        decision = record.get("decision") or {}
        print(f"  {str(record.get('log_id', '?')):<14}"
              f"{str(record.get('machine_id', '?')):<14}"
              f"{str(ai.get('severity', '-')):<5}"
              f"{str(decision.get('score', '-')):<7}"
              f"{decision.get('route', '-')}")
    print(f"  {len(records)} record(s).")


def display_result(record: dict) -> None:
    """Show the outcome of processing a single record."""
    decision = record.get("decision") or {}
    route = decision.get("route", "unknown")
    score = decision.get("score", "-")
    print(f"  -> {record.get('machine_id', '?')}: {route} (score {score}/100)")


def display_batch_problems(problems: list) -> None:
    """Report lines that could not be parsed during file ingestion."""
    if not problems:
        return
    print()
    print(f"  {len(problems)} line(s) were skipped:")
    for problem in problems[:10]:
        print(f"    - {problem}")
    if len(problems) > 10:
        print(f"    ... and {len(problems) - 10} more (see logs/app.log)")


def display_summary(summary: dict) -> None:
    """Show the fleet-level summary produced by logic_manager.summarise()."""
    print()
    print(LINE)
    print("  FLEET SUMMARY")
    print(LINE)
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
    print(LINE)


def display_goodbye() -> None:
    """Closing message."""
    print()
    print("  Done. Records saved. Goodbye.")


# ===========================================================================
# Telegram output boundary
# ===========================================================================
def format_alert(record: dict) -> str:
    """Turn a processed record into the alert text an engineer receives."""
    ai = record.get("ai") or {}
    decision = record.get("decision") or {}
    return (
        f"[{decision.get('route', 'alert').upper()}] "
        f"{record.get('machine_id', '?')} ({record.get('machine_type', '?')})\n"
        f"Severity {ai.get('severity', '?')}/5 | priority {decision.get('score', '?')}/100\n"
        f"Subsystem: {ai.get('machine_subsystem', 'unknown')}\n"
        f"Likely cause: {ai.get('root_cause_hypothesis', 'unknown')}\n"
        f"Action: {ai.get('recommended_action', 'inspect device')}\n"
        f"Logged: {record.get('timestamp', '?')} | ref {record.get('log_id', '?')}"
    )


def send_alert(record: dict) -> bool:
    """Send a Telegram alert for a record. Returns True only if it was sent.

    Alerting is an output boundary, so it lives here rather than in
    logic_manager. logic_manager decides *whether* to alert; this sends it.
    Disabled by default so the pipeline runs without any bot credentials.
    """
    text = format_alert(record)

    if not TELEGRAM_ENABLED:
        print("  [alert suppressed - TELEGRAM_ENABLED is false]")
        for line in text.splitlines():
            print(f"    {line}")
        logger.info("Alert suppressed for %s", record.get("log_id"))
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        display_error("Telegram is enabled but credentials are missing; alert not sent.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error("Telegram send failed for %s: %s", record.get("log_id"), error)
        display_error("Could not reach Telegram; the record was still saved.")
        return False

    logger.info("Telegram alert sent for %s", record.get("log_id"))
    display_message(f"Alert sent to engineer for {record.get('machine_id', '?')}.")
    return True
