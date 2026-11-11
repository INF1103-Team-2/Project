"""main_triage_app.py - the command-line menu (one of two front ends)."""

import logging
from datetime import datetime

from data_manager_phase2 import RecordRepository
from io_manager_console_ui import ConsoleUI
from io_manager_log_file_reader import LogFileReader
from io_manager_report_manager import ReportManager
from logic_manager_fleet_analyzer import FleetAnalyzer
from main_triage_pipeline import TriagePipeline

logger = logging.getLogger(__name__)