import os
import logging
import csv
from typing import Dict

KNOWN_PROGRAM_IDS: Dict[str, str] = {}

def load_program_ids_from_csv(file_path: str):
    global KNOWN_PROGRAM_IDS
    KNOWN_PROGRAM_IDS = {}
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        raise FileNotFoundError(f"Program IDs CSV file not found or is empty: {file_path}")
    with open(file_path, mode='r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if 'program_address' in row and 'project_name' in row:
                KNOWN_PROGRAM_IDS[row['program_address']] = row['project_name']

# Load program IDs at startup
try:
    load_program_ids_from_csv('data/program_ids.csv')
except FileNotFoundError as e:
    logging.error(f"Failed to load program IDs: {e}")
    # Depending on criticality, you might want to exit or use a fallback
    # For now, we'll let it proceed with an empty dict if the file is missing/empty
except Exception as e:
    logging.error(f"An unexpected error occurred while loading program IDs: {e}")
