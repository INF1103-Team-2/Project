import json #parses model's replies
import logging #logging of errors and warnings so no need to print
import os #reads enviroment variables
import time
from typing import Optional

import requests #HTTP calls
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# AI API configuration
AI_BASE_URL = os.getenv(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

SEVERITY_MIN = 1
SEVERITY_MAX = 5
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

response_schema = {
    "machine_subsystem": str,
    "severity": int,
    "root_cause_hypothesis": str,
    "patient_safety_risk": bool,
    "recurrence_indicator": bool,
    "recommended_action": str,
    "confidence": float,
}

#------------------------------------------------------------
#Prompt
#------------------------------------------------------------
=======
# Prompt

>>>>>>> 4c0ad6eaeafb942137f704d569806b526ee2e6a2
def build_prompt(record: dict) -> str:
    """Build a prompt for structured AI analysis of an error log."""
    return (
        "Assess the following medical device error logs and return your assessment as JSON.\n\n"
        f"Machine ID: {record.get('machine_id', 'unknown')}\n"
        f"Machine type: {record.get('machine_type', 'unknown')}\n"
        f"Timestamp: {record.get('timestamp', 'unknown')}\n"
        f"Raw error message: {record.get('raw_message', '')}\n\n"
        "Return exactly these keys:\n"
        '  "machine_subsystem": string, the specific component or subsystem at fault\n'
        f'  "severity": integer {SEVERITY_MIN}-{SEVERITY_MAX} '
        "(1 = cosmetic or informational, 3 = degraded function, "
        "5 = device unusable or actively dangerous)\n"
        '  "root_cause_hypothesis": string, one sentence on the most likely cause\n'
        '  "patient_safety_risk": boolean, true only if this fault could directly '
        "harm a patient or produce a clinically misleading reading\n"
        '  "recurrence_indicator": boolean, true if the message itself shows the '
        "fault is repeating (repeat counts, cycling, 'again', multiple occurrences)\n"
        '  "recommended_action": string, the concrete next step for the technician\n'
        f'  "confidence": float {CONFIDENCE_MIN}-{CONFIDENCE_MAX}, your certainty '
        "in this assessment; be honest and use a low value when the message is "
        "vague or ambiguous\n\n"
        "Respond with the JSON object only."
    )

<<<<<<< HEAD
#------------------------------------------------------------
#API call
#------------------------------------------------------------
def call_api(prompt: str) -> Optional[str]:
    """Send prompt to Gemini via the OpenAI-compatible endpoint"""
    """Catches errors and returns None instead of letting the program crash"""
=======
# Ai response validation

def validate_ai_response(content: str) -> Optional[dict]:
    """Validate and return the AI JSON response."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("AI returned invalid JSON.")
        return None

    for key in response_schema:
        if key not in data:
            logger.error("AI response is missing key: %s", key)
            return None

    if not isinstance(data["severity"], int) or not 1 <= data["severity"] <= 5:
        logger.error("Invalid severity value.")
        return None

    if not 0 <= data["confidence"] <= 1:
        logger.error("Invalid confidence value.")
        return None

    return data

# API call

def call_api(prompt: str) -> Optional[dict]:
    """Send a prompt to Gemini and return the JSON response as text.
    Returns None if the API request fails.
    """

>>>>>>> 4c0ad6eaeafb942137f704d569806b526ee2e6a2
    if not AI_API_KEY:
        logger.error("AI_API_KEY is not set in .env file.")
        return None

    url = f"{AI_BASE_URL}/chat/completions"
    payload = {
        "model": AI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert equipment engineer. "
                    "Respond ONLY with valid JSON matching the requested keys."
                ),
                },
                {"role": "user", "content": prompt},
            ],
        }
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

<<<<<<< HEAD
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        logger.error("API call failed: %s", e)
        return None 

#------------------------------------------------------------
#Breaking down the response to Python dictionary
#------------------------------------------------------------
def parse_response(raw: Optional[str]) -> Optional[dict]:
    if not raw or not isinstance(raw, str):
        logger.error("Nothing to parse from the AI response.")
        return None

    text = raw.strip()
    if text.startswith("'''"):
        text = text.strip("'")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}") #reverse find
    if start == -1 or end == -1 or end < start:
        logger.error("No JSON object found in the AI response: %r",raw[:120])
        return None

    try:
        parsed = json.loads(text[start:end +1])
    except json.JSONDecodeError as error:
        logger.error("AI response was not a valid JSON value: %s", error)
        return None
    if not isinstance(parsed, dict):
        logger.error("AI response parsed to %s, expected an object", type(parsed).__name__)
        return None
    return parsed

#------------------------------------------------------------
#Validate response so that bad data doesn't reach data_manager
#------------------------------------------------------------
def validate_response(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        logger.error("Validation failed: response is not a dictionary.")
        return False

    for key, expected_type in response_schema.items():
        if key not in data:
            logger.error("Validation failed: missing required key '%s'", key)
            return False

        value = data[key]

        if expected_type is bool:
            if not isinstance(value, bool):
                logger.error("Validation failed: '%s' must be a boolean, got %r", key, value)
                return False
        elif expected_type is int:
            if isinstance(value, bool) or not isinstance(value, int):
                logger.error("Validation failed: '%s' must be a integer, got %r", key, value)
                return False
        elif expected_type is float:
            if isinstance(value, bool):
                logger.error("Validation failed: '%s' must be a number, got %r", key, value)
                return False
        elif expected_type is str:
            if not isinstance(value, str) or not value.strip():
                logger.error("Validation failed: '%s' must be a non-empty string", key)
                return False

    severity = data["severity"]
    if not SEVERITY_MAX >= severity >= SEVERITY_MIN:
        logger.error("Validation failed: severity %s outside %d-%d",
                     severity, SEVERITY_MIN, SEVERITY_MAX)
        return False
    confidence = data["confidence"]
    if not CONFIDENCE_MIN <= confidence <= CONFIDENCE_MAX:
        logger.error("Validation failed: confidence %s outside %.1f-%.1f",
                     confidence, CONFIDENCE_MIN, CONFIDENCE_MAX)
        return False
    return True

#------------------------------------------------------------
#Build a clean copy and return it 
#------------------------------------------------------------
def normalize_response(data: dict) -> dict:
    return {
        "machine_subsystem": data["machine_subsystem"].strip(),
        "severity": int(data["severity"]),
        "root_cause_hypothesis": data["root_cause_hypothesis"].strip(),
        "patient_safety_risk": bool(data["patient_safety_risk"]),
        "recurrence_indicator": bool(data["recurrence_indicator"]),
        "recommended_action": data["recommended_action"].strip(),
        "confidence": round(float(data["confidence"]), 2),
        }

#------------------------------------------------------------
#Returns a copy of either the AI results or an error
#------------------------------------------------------------
def enrich_record(record: dict) -> dict:
    enriched = dict(record)

    if not AI_API_KEY:
        enriched["ai"] = None
        enriched["ai_error"] = "AI_API_KEY is not configured"
        logger.error("Record %s not enriched: AI_API_KEY is not configured",
                     record.get("log_id"))
        return enriched

    prompt = build_prompt(record)
    last_error = "unknown failure"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = call_api(prompt)
        if raw is None:
            last_error = "AI API unreachable or returned an error"
        else:
            parsed = parse_response(raw)
            if parsed is None:
                last_error = "AI response could not be parsed as JSON"
            elif not validate_response(parsed):
                last_error = "AI response failed schema validation"
            else:
                enriched["ai"] = normalize_response(parsed)
                enriched.pop("ai_error", None)
                logger.info("Record %s enriched on attempt %d",
                            record.get("log_id"), attempt)
                return enriched
        logger.warning("Attempt %d/%d failed for record %s: %s",
                       attempt, MAX_ATTEMPTS, record.get("log_id"), last_error)
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    enriched["ai"] = None
    enriched["ai_error"] = last_error
    logger.error("Record %s could not be enriched: %s", record.get("log_id", last_error))
    return enriched

if __name__ == "__main__":
    record = {
        "machine_id": "MACHINE_001",
        "machine_type": "Infusion Pump",
        "timestamp": "2026-10-03 21:30:05",
        "raw_message": "Temperature exceeded 90°C"
    }

    result = enrich_record(record)

    print("\n--- AI Analysis Result ---")
    print(result)
    