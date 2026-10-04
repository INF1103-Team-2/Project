"""main.py - Entry point (INF1103 Phase 1).

Wires the pipeline together:

    user / file -> io_manager -> ai_manager -> logic_manager -> data_manager

This file performs no direct terminal interaction of its own. Every message
shown to the user goes through an io_manager display function, and every value
read from the user comes back from an io_manager prompt function.
"""

import logging
import os
from datetime import datetime

import ai_manager
import data_manager
import io_manager
import logic_manager

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


def process_one(record: dict, now: datetime) -> dict:
    """Run a single record through AI enrichment, business rules and storage."""
    enriched = ai_manager.enrich_record(record)
    processed = logic_manager.process_record(enriched, now=now)

    if not data_manager.save(processed):
        io_manager.display_error(f"Could not save record {processed.get('log_id')}.")

    if processed["decision"]["notify_now"]:
        io_manager.send_alert(processed)

    return processed


def handle_single_entry() -> None:
    """Menu action: collect one error log from the keyboard and process it."""
    record = io_manager.prompt_error_log()
    if record is None:
        io_manager.display_message("Cancelled.")
        return

    io_manager.display_message("Sending to the AI for assessment...")
    processed = process_one(record, datetime.now())
    io_manager.display_record(processed)


def handle_file_ingest() -> None:
    """Menu action: read a machine log file and process every valid line."""
    path = io_manager.prompt_file_path()
    if path is None:
        io_manager.display_message("Cancelled.")
        return

    records, problems = io_manager.read_log_file(path)
    io_manager.display_batch_problems(problems)

    if not records:
        io_manager.display_error("No usable records found in that file.")
        return

    io_manager.display_message(f"Processing {len(records)} record(s)...")
    now = datetime.now()
    processed_records = []
    for record in records:
        processed = process_one(record, now)
        processed_records.append(processed)
        io_manager.display_result(processed)

    io_manager.display_list(processed_records)


def handle_view_all() -> None:
    """Menu action: list everything in storage, highest priority first."""
    records = data_manager.load()
    records.sort(key=lambda record: -int((record.get("decision") or {}).get("score", 0)))
    io_manager.display_list(records)

    if records and io_manager.confirm("Show the full detail of the top record?"):
        io_manager.display_record(records[0])


def handle_query() -> None:
    """Menu action: build a filter and hand it to data_manager.query()."""
    filter_fn = io_manager.prompt_query_filter()
    if filter_fn is None:
        io_manager.display_message("Cancelled.")
        return
    io_manager.display_list(data_manager.query(filter_fn))


def handle_summary() -> None:
    """Menu action: show the consolidated fleet report."""
    io_manager.display_summary(logic_manager.summarise(data_manager.load()))


def main() -> None:
    """Run the interactive triage loop."""
    configure_logging()
    logging.getLogger(__name__).info("Application started")

    stored = data_manager.load()
    io_manager.display_message(f"Loaded {len(stored)} previously processed record(s).")

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
