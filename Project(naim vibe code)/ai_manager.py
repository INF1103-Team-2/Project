"""ai_manager.py - AI processing layer (INF1103 Phase 1).

The core engine. Every record processed by the system passes through here.
Delete this module and the application cannot triage anything - the severity,
subsystem, root-cause hypothesis, safety-risk flag and confidence that
logic_manager depends on are all produced by the model reading free-text
machine output. There is no keyword fallback, by design.

This file contains no domain rules. It builds a prompt, calls the API, parses
the response and validates the schema. Nothing else.

Provider configuration is environment-driven and uses an OpenAI-compatible
chat completions endpoint, so the same code works against Gemini (default),
Groq, OpenRouter, Ollama or OpenAI.
"""

import json
import logging
import os
import time 
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

AI_BASE_URL = os.getenv(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

# Severity and confidence bounds that validate_response() enforces.
SEVERITY_MIN = 1
SEVERITY_MAX = 5
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

# The contract the model must honour. Keys map to Python types.
RESPONSE_SCHEMA = {
    "machine_subsystem": str,
    "severity": int,
    "root_cause_hypothesis": str,
    "patient_safety_risk": bool,
    "recurrence_indicator": bool,
    "recommended_action": str,
    "confidence": float,
}

SYSTEM_INSTRUCTION = (
    "You are a biomedical equipment reliability engineer triaging error logs "
    "from hospital medical devices. You reply with a single JSON object and "
    "nothing else: no prose, no markdown, no code fences."
)


# ===========================================================================
# 1. Prompt construction
# ===========================================================================
def build_prompt(record: dict) -> str:
    """Construct a specific, schema-bound prompt from one record dict."""
    return (
        "Assess the following medical device error log and return your "
        "assessment as JSON.\n\n"
        f"Machine ID: {record.get('machine_id', 'unknown')}\n"
        f"Machine type: {record.get('machine_type', 'unknown')}\n"
        f"Timestamp: {record.get('timestamp', 'unknown')}\n"
        f"Reported by: {record.get('reported_by', 'unknown')}\n"
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


# ===========================================================================
# 2. API call
# ===========================================================================
def call_api(prompt: str) -> Optional[str]:
    """Send a prompt to the AI API and return the raw response text.

    Catches connection errors, timeouts and HTTP errors. Logs and returns None
    rather than raising, so a single bad call never stops a batch.
    Temperature is pinned to 0 to keep output as repeatable as possible.
    """
    if not AI_API_KEY:
        logger.error("AI_API_KEY is not set; cannot call the AI API")
        return None

    url = f"{AI_BASE_URL}/chat/completions"
    payload = {
        "model": AI_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=AI_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except requests.Timeout:
        logger.error("AI API timed out after %ss", AI_TIMEOUT_SECONDS)
    except requests.ConnectionError as error:
        logger.error("AI API connection failed: %s", error)
    except requests.HTTPError as error:
        logger.error("AI API returned HTTP error: %s", error)
    except (KeyError, IndexError, ValueError) as error:
        logger.error("AI API response envelope was not in the expected shape: %s", error)
    return None


# ===========================================================================
# 3. Response parsing
# ===========================================================================
def parse_response(raw: Optional[str]) -> Optional[dict]:
    """Extract and parse the JSON object from a raw response string.

    Tolerates markdown code fences and surrounding prose, which models add
    even when told not to. Returns None if no JSON object can be recovered.
    """
    if not raw or not isinstance(raw, str):
        logger.error("Nothing to parse from the AI response")
        return None

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        logger.error("No JSON object found in AI response: %r", raw[:120])
        return None

    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError as error:
        logger.error("AI response was not valid JSON: %s", error)
        return None

    if not isinstance(parsed, dict):
        logger.error("AI response parsed to %s, expected an object", type(parsed).__name__)
        return None
    return parsed


# ===========================================================================
# 4. Schema validation
# ===========================================================================
def validate_response(data: Optional[dict]) -> bool:
    """Check that a parsed AI response matches the required schema.

    Verifies required keys, types and value ranges. Returns False and logs the
    reason on any violation, so malformed output is rejected before any field
    reaches logic_manager.
    """
    if not isinstance(data, dict):
        logger.error("Validation failed: response is not a dict")
        return False

    for key, expected_type in RESPONSE_SCHEMA.items():
        if key not in data:
            logger.error("Validation failed: missing required key '%s'", key)
            return False

        value = data[key]

        if expected_type is bool:
            if not isinstance(value, bool):
                logger.error("Validation failed: '%s' must be a boolean, got %r", key, value)
                return False
        elif expected_type is int:
            # Booleans are ints in Python; reject them explicitly.
            if isinstance(value, bool) or not isinstance(value, int):
                logger.error("Validation failed: '%s' must be an integer, got %r", key, value)
                return False
        elif expected_type is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                logger.error("Validation failed: '%s' must be a number, got %r", key, value)
                return False
        elif expected_type is str:
            if not isinstance(value, str) or not value.strip():
                logger.error("Validation failed: '%s' must be a non-empty string", key)
                return False

    severity = data["severity"]
    if not SEVERITY_MIN <= severity <= SEVERITY_MAX:
        logger.error("Validation failed: severity %s outside %d-%d",
                     severity, SEVERITY_MIN, SEVERITY_MAX)
        return False

    confidence = float(data["confidence"])
    if not CONFIDENCE_MIN <= confidence <= CONFIDENCE_MAX:
        logger.error("Validation failed: confidence %s outside %s-%s",
                     confidence, CONFIDENCE_MIN, CONFIDENCE_MAX)
        return False

    return True


def normalise_response(data: dict) -> dict:
    """Return a copy of a validated response with consistent types."""
    return {
        "machine_subsystem": data["machine_subsystem"].strip(),
        "severity": int(data["severity"]),
        "root_cause_hypothesis": data["root_cause_hypothesis"].strip(),
        "patient_safety_risk": bool(data["patient_safety_risk"]),
        "recurrence_indicator": bool(data["recurrence_indicator"]),
        "recommended_action": data["recommended_action"].strip(),
        "confidence": round(float(data["confidence"]), 2),
    }


# ===========================================================================
# Orchestration within this layer
# ===========================================================================
def enrich_record(record: dict) -> dict:
    """Run one record through the full AI step and return an enriched copy.

    On success the copy carries an 'ai' key. On failure it carries 'ai_error'
    instead, and logic_manager routes it for manual review. The function never
    raises.
    """
    enriched = dict(record)

    # A missing key is a configuration fault, not a transient one - retrying
    # and backing off on every record would only slow the batch down.
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
                enriched["ai"] = normalise_response(parsed)
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
    logger.error("Record %s could not be enriched: %s", record.get("log_id"), last_error)
    return enriched
