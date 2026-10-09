"""main.py - Entry point (INF1103 Phase 1).

Wires the pipeline together:

    user / file -> io_manager -> ai_manager -> logic_manager -> data_manager

This file performs no direct terminal interaction of its own. Every message
shown to the user goes through an io_manager display function, and every value
read from the user comes back from an io_manager prompt function.
"""

import logging
import os
from datetime import datetime, timedelta

# ai_manager calls load_dotenv() on import, which makes the .env values
# (AI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) visible to every module.
import ai_manager
import data_manager
import io_manager
import logic_manager

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"   # io_manager normalises every timestamp to this
BUNDLE_WINDOW_MINUTES = 10          # Business Rule 3


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


# ===========================================================================
# Rule 3: bundle repeats of the same error within a 10-minute window
# ===========================================================================
def find_bundles(records: list) -> tuple:
    """Group repeats of the same error_code on the same machine inside the window.

    The first occurrence is the lead and the window is measured from it.

    Returns (followers, counts):
      followers: {follower log_id: lead log_id}
      counts:    {lead log_id: total occurrences including the lead}
    """
    ordered = sorted(records, key=lambda r: (r["machine_id"], r["error_code"], r["timestamp"]))
    window = timedelta(minutes=BUNDLE_WINDOW_MINUTES)
    followers: dict = {}
    counts: dict = {}
    lead = None
    lead_time = None

    for record in ordered:
        when = datetime.strptime(record["timestamp"], TIME_FORMAT)
        is_repeat = (
            lead is not None
            and record["machine_id"] == lead["machine_id"]
            and record["error_code"] == lead["error_code"]
            and when - lead_time <= window
        )
        if is_repeat:
            followers[record["log_id"]] = lead["log_id"]
            counts[lead["log_id"]] = counts.get(lead["log_id"], 1) + 1
        else:
            lead, lead_time = record, when
    return followers, counts


# ===========================================================================
# Pipeline
# ===========================================================================
def send_urgent_alert(record: dict) -> dict:
    """Show the alert, send it to Telegram, and mark it sent if delivery worked."""
    text = logic_manager.build_alert_message(record)
    repeats = (record.get("decision") or {}).get("bundled_count")
    if repeats:
        text += f"\n(Same error occurred {repeats} times within {BUNDLE_WINDOW_MINUTES} minutes)"

    io_manager.display_alert(record)
    ok, info = logic_manager.send_telegram(text)
    io_manager.display_message(f"Telegram: {info}")
    return logic_manager.mark_sent(record) if ok else record


def process_batch(records: list, now: datetime) -> list:
    """Run records through AI enrichment, business rules, notification and storage."""
    # The same log line uploaded twice has the same log_id; process it once.
    unique = {}
    for record in records:
        unique.setdefault(record["log_id"], record)

    processed = []
    for record in unique.values():
        enriched = ai_manager.enrich_record(record)
        processed.append(logic_manager.process_record(enriched, now=now))

    # Rule 3: only the first of a burst of identical errors notifies.
    followers, counts = find_bundles(processed)
    for record in processed:
        decision = record["decision"]
        if record["log_id"] in followers:
            decision["suppressed_by"] = followers[record["log_id"]]
            decision["notification_sent"] = True    # covered by the lead's message
        if record["log_id"] in counts:
            decision["bundled_count"] = counts[record["log_id"]]

    # Rules 1 and 5: urgent now; records needing human review never go out.
    for index, record in enumerate(processed):
        if logic_manager.should_send_now(record):
            processed[index] = send_urgent_alert(record)

    for record in processed:
        if not data_manager.add_record(record):
            io_manager.display_error(f"Could not save record {record.get('log_id')}.")
        io_manager.display_result(record)
    return processed


def dispatch_due_reports() -> None:
    """Rule 2: send one combined report for non-urgent alerts whose 07:00 time has arrived."""
    now_text = datetime.now().strftime(TIME_FORMAT)
    due = logic_manager.get_due_alerts(data_manager.load_records(), now_text)
    if not due:
        return

    ok, info = logic_manager.send_telegram(logic_manager.build_daily_report(due))
    io_manager.display_message(f"Daily report ({len(due)} item(s)): {info}")
    if ok:
        for record in due:
            data_manager.add_record(logic_manager.mark_sent(record))


# ===========================================================================
# Menu actions
# ===========================================================================
def handle_single_entry() -> None:
    """Menu action: collect one error log from the keyboard and process it."""
    record = io_manager.prompt_error_log()
    if record is None:
        io_manager.display_message("Cancelled.")
        return

    io_manager.display_message("Sending to the AI for assessment...")
    processed = process_batch([record], datetime.now())
    io_manager.display_record(processed[0])


def handle_file_ingest() -> None:
    """Menu action: read a machine log file and process every valid line."""
    path = io_manager.prompt_file_path()
    if path is None:
        io_manager.display_message("Cancelled.")
        return

    records, problems = io_manager.read_log_file(path)
    io_manager.display_batch_problems(problems)

    if not records:
        io_manager.display_error(io_manager.INVALID_FILE_MESSAGE)
        return

    io_manager.display_message(f"Processing {len(records)} record(s)...")
    processed = process_batch(records, datetime.now())
    io_manager.display_list(processed)


def handle_view_all() -> None:
    """Menu action: list everything in storage, highest priority first."""
    records = data_manager.load_records()
    records.sort(key=lambda record: -int((record.get("decision") or {}).get("score", 0)))
    io_manager.display_list(records)

    if records and io_manager.confirm("Show the full detail of the top record?"):
        io_manager.display_record(records[0])


def handle_query() -> None:
    """Menu action: build a filter and apply it to the stored records."""
    filter_fn = io_manager.prompt_query_filter()
    if filter_fn is None:
        io_manager.display_message("Cancelled.")
        return
    io_manager.display_list(data_manager.query(filter_fn))


def handle_summary() -> None:
    """Menu action: show the consolidated fleet report."""
    io_manager.display_summary(logic_manager.summarise(data_manager.load_records()))


def main() -> None:
    """Run the interactive triage loop."""
    configure_logging()
    logging.getLogger(__name__).info("Application started")

    stored = data_manager.load_records()
    io_manager.display_message(f"Loaded {len(stored)} previously processed record(s).")
    dispatch_due_reports()

    actions = {
        "Enter a single error log": handle_single_entry,
        "Ingest a log file": handle_file_ingest,
        "View all stored records": handle_view_all,
        "Query stored records": handle_query,
        "Fleet summary report": handle_summary,
    }

    while True:
        choice = io_manager.prompt_main_menu()
        if choice == "Exit":
            io_manager.display_goodbye()
            return

        action = actions.get(choice)
        if action is None:
            io_manager.display_error("That option is not available.")
            continue

        try:
            action()
        except KeyboardInterrupt:
            io_manager.display_message("Interrupted; returning to the menu.")
        except Exception as error:  # last line of defence: never crash the CLI
            logging.getLogger(__name__).exception("Unhandled error in %s", choice)
            io_manager.display_error(f"Something went wrong ({error}). Returning to the menu.")


if __name__ == "__main__":
    main()
