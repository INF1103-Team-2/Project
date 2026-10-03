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

# Configuration settings
AI_BASE_URL = os.getenv(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()

max_attempts = 3
retry_backoff_seconds = 2

severity_min = 1
severity_max = 5
confidence_min = 0.0
confidence_max = 1.0

Response_Schema = {
    "machine_subsystem": str,
    "severity": int,
    "root_cause_hypothesis": str,
    "patient_safety_risk": bool,
    "recurrence_indicator": bool,
    "recommended action": str,
    "confidence": float,
}

system_instructions = {
    ""
}

#------------------------------------------------------------
#Prompt
#------------------------------------------------------------
def build_prompt(record: dict) -> str:
    """Creating a schema-bound prompt"""
    return(
        "Assess the following medical device error logs and return your assesment as JSON.\n\n"
        f"Machine ID: {record.get('machine_id', 'unknown')}\n"
        f"Machine type: {record.get('machine_type', 'unknown')}\n"
        f"Timestamp: {record.get('timestamp', 'unknown')}\n"
        f"Raw error message: {record.get('raw_message', '')}\n\n"
        "Return exactly these keys:\n"
        '  "machine_subsystem": string, the specific component or subsystem at fault\n'
        f'  "severity": integer {severity_min}-{severity_max} '
        "(1 = cosmetic or informational, 3 = degraded function, "
        "5 = device unusable or actively dangerous)\n"
        '  "root_cause_hypothesis": string, one sentence on the most likely cause\n'
        '  "patient_safety_risk": boolean, true only if this fault could directly '
        "harm a patient or produce a clinically misleading reading\n"
        '  "recurrence_indicator": boolean, true if the message itself shows the '
        "fault is repeating (repeat counts, cycling, 'again', multiple occurrences)\n"
        '  "recommended_action": string, the concrete next step for the technician\n'
        f'  "confidence": float {confidence_min}-{confidence_max}, your certainty '
        "in this assessment; be honest and use a low value when the message is "
        "vague or ambiguous\n\n"
        "Respond with the JSON object only."
    )

#------------------------------------------------------------
#API call
#------------------------------------------------------------
def call_api(prompt: str) -> Optional[str]:
    """Send prompt to Gemini via the OpenAI-compatible endpoint"""
    """Catches errors and returns None instead of letting the program crash"""
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
    except json.JSONDecodeRorror as error:
        logger.error("AI response was not a valid JSON value: %s", error)
        return None
    if not isinstance(parsed, dict):
        logger.error("AI response parsed to %s, expected an object", type(parsed).__name__)
        return None
    return parsed