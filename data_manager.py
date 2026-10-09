import json
import os


DATA_FILE = "processed_records.json"

# Function 1: Load all stored records
def load_records():
    try:
        with open(DATA_FILE, "r") as file:
            records = json.load(file)

        return records

    except FileNotFoundError:
        return []

    except json.JSONDecodeError:
        return []

    # Function 2: Save all records into the JSON file
def save_records(records):
    try:
        with open(DATA_FILE, "w") as file:
            json.dump(records, file, indent=4)

        return True

    except OSError:
        return False

# Function 3
# : Store one processed error record
def add_record(record):
    # Make sure the record is a dictionary
    if not isinstance(record, dict):
        return False

    # Every record should have a log_id
    if "log_id" not in record:
        return False

    records = load_records()

    # Check whether this log already exists
    for index in range(len(records)):
    
            if records[index]["log_id"] == record["log_id"]:
                # Replace the existing record
                records[index] = record
                return save_records(records)
    
        # If it does not exist, add it
    records.append(record)
    
    return save_records(records)

# FUNCTION 4: Find a record using log_id
def get_record(log_id):
    records = load_records()

    for record in records:

        if record["log_id"] == log_id:
            return record

    return None

# FUNCTION 5: Find all errors from one machine
def get_machine_records(machine_id):
    records = load_records()

    results = []

    for record in records:

        if record.get("machine_id") == machine_id:
            results.append(record)

    return results

# FUNCTION 6: Update notification status
def update_notification_status(log_id, new_status):
    records = load_records()

    for record in records:

        if record["log_id"] == log_id:
            record["notification_status"] = new_status

            return save_records(records)

    return False

# FUNCTION 7: Check whether a record already exists
def record_exists(log_id):
    records = load_records()

    for record in records:

        if record["log_id"] == log_id:
            return True

    return False


def save(record):
    """Save one processed record (framework name for add_record)."""
    return add_record(record)


def load():
    """Load all records; empty list if the file is missing or corrupt."""
    return load_records()


def query(filter_fn):
    """Return every stored record for which filter_fn(record) is True."""
    return [record for record in load_records() if filter_fn(record)]
