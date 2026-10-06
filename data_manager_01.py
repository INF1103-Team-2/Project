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