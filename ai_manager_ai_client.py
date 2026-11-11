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