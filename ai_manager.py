import json
import logging
import os
import time
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Load variables from .env file into environment
load_dotenv()

logger = logging.getLogger(__name__)

# Configuration settings
AI_BASE_URL = os.getenv(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()



Response_Schema = {
    "machine_subsystem": str,
    "severity": int,
    "root_cause_hypothesis": str,
    "recurrence_indicator": bool,
    "recommended action": str,
    "confidence": float,
}

