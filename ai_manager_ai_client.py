"""ai_manager_ai_client.py - asks an OpenAI-compatible model to assess error logs."""

import json
import logging
import time
from typing import Optional

import requests

from logic_manager_ai_assessment import AIAssessment
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class AIClient:
    """Calls the AI API (OpenRouter / Gemini) and attaches an AIAssessment to a log."""

    MAX_ATTEMPTS = 3
    RETRY_BACKOFF_SECONDS = 2
    RESPONSE_SCHEMA = {
        "machine_subsystem": str,
        "severity": int,
        "root_cause_hypothesis": str,
        "patient_safety_risk": bool,
        "recurrence_indicator": bool,
        "recommended_action": str,
        "confidence": float,
    }

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self._base_url: str = (base_url or "").rstrip("/")
        self._model: str = model
        self._api_key: str = (api_key or "").strip()
        self._max_attempts: int = self.MAX_ATTEMPTS
        self._retry_backoff_seconds: int = self.RETRY_BACKOFF_SECONDS

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def enrich(self, log: ErrorLog) -> None:
        """Try up to 3 times; attach the assessment, or the reason it failed."""
        if not self.is_configured():
            log.set_ai_error("AI_API_KEY is not configured")
            logger.error("Record %s not enriched: AI_API_KEY is not configured", log.log_id)
            return

        prompt = self._build_prompt(log)
        last_error = "unknown failure"
        for attempt in range(1, self._max_attempts + 1):
            raw = self._call_api(prompt)
            if raw is None:
                last_error = "AI API unreachable or returned an error"
            else:
                parsed = self._parse_response(raw)
                if parsed is None:
                    last_error = "AI response could not be parsed as JSON"
                elif not self._validate(parsed):
                    last_error = "AI response failed schema validation"
                else:
                    log.set_ai_assessment(self._to_assessment(parsed))
                    logger.info("Record %s enriched successfully on attempt %d", log.log_id, attempt)
                    return
            logger.warning("Attempt %d/%d failed for record %s: %s", 
                           attempt, self._max_attempts, log.log_id, last_error)
            if attempt < self._max_attempts:
                time.sleep(self._retry_backoff_seconds * attempt)

        log.set_ai_assessment(last_error)
        logger.error("Record %s could not be enriched: %s", log.log_id, last_error)

    def build_prompt(self, log: ErrorLog) -> str:
        smin, smax = AIAssessment.SEVERITY_MIN, AIAssessment.SEVERITY_MAX
        cmin, cmax = AIAssessment.CONFIDENCE_MIN, AIAssessment.CONFIDENCE_MAX
        return (
            "Assess the following medical device error logs and return your assessment in Json.\n\n"
            f"Machine ID: {log.machine_id or 'unknown'}\n"
            f"Machine type: {log.machine_type or 'unknown'}\n"
            f"Timestamp: {log.timestamp or 'unknown'}\n"
            f"Raw error message: {log.raw_message}\n\n"
            "Return exactly these keys:\n"
            ' "machine_subsystem": string, the specific component or subsystem at fault\n'
            f' "severity": integer {smin}-{smax} '
            "(1 = cosmetic or informational, 3 = degraded function, "
            "5 = device unsuable or actively dangerous)\n"
            ' "root_cause hypothesis": string, one sentence on the most likely cause\n'
            '  "patient_safety_risk": boolean, true only if this fault could directly '
            "harm a patient or produce a clinically misleading reading\n"
            '  "recurrence_indicator": boolean, true if the message itself shows the '
            "fault is repeating (repeat counts, cycling, 'again', multiple occurrences)\n"
            '  "recommended_action": string, the concrete next step for the technician\n'
            f'  "confidence": float {cmin}-{cmax}, your certainty '
            "in this assessment; be honest and use a low value when the message is "
            "vague or ambiguous\n\n"
            "Respond with the JSON object only."
        )
    def _call_api(self, prompt: str) -> Optional[str]:
        """Return the model's reply text, or None if the request failed."""
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert equipment engineer. "
                        "Respong ONLY with valid JSON matching requested keys."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(f"{self._base_url}/chat/completions",
                                     json = payload, headers = headers, timeout = 30)
            response.raise_for_status()
            body = response.json()
            return body["choices"][0]["message"]["content"]
        except requests.RequestException as error:
            logger.error("API call failed: %s", error)
            return None

    def _parse_response(self, raw: Optional[str]) -> Optional[dict]:
        """Pulls the JSON object out of the reply (it may be wrapped in ``` fences)"""
        if not raw or not isinstance(raw, str):
            logger.error("Nothing to parse from the AI response.")
            return None

        text = raw.strip()
        if text.startswith("```"):      #Checks for ```
            text = text.strip()
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        start = text.find("{")
        end = text.find("}")
        if start == -1 or end == -1 or end < start:
            logger.error("No JSON object found in the AI response: %r", raw[:120])
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