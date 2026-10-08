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