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
from abc import ABC, abstractmethod

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------- Exceptions (inheritance) ----------------
class AIError(Exception):
    """Base class for all AI Manager errors."""


class AIConfigError(AIError):
    """API key missing. Retrying will not help."""


class AIConnectionError(AIError):
    """API unreachable, timed out or returned an error."""


class AIResponseError(AIError):
    """Reply is not valid JSON or does not match the schema."""


# ---------------- AI clients (abstract class / interface) ----------------
class AIClient(ABC):
    """Every AI client must return the model's reply as text."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        pass


class GeminiClient(AIClient):
    """Real client: calls Gemini's OpenAI-compatible API."""

    def __init__(self):
        self._base_url = os.getenv(
            "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
        ).rstrip("/")
        self._model = os.getenv("AI_MODEL", "gemini-2.0-flash")
        self.__api_key = os.getenv("AI_API_KEY", "").strip()  # private

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.__api_key:
            raise AIConfigError("AI_API_KEY is not configured")
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.__api_key}"}
        try:
            response = requests.post(f"{self._base_url}/chat/completions",
                                     json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError) as error:
            raise AIConnectionError(f"API call failed: {error}") from error


class MockAIClient(AIClient):
    """Fake client for tests: returns preset replies (or raises preset errors)."""

    def __init__(self, replies):
        self._replies = list(replies)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


# ---------------- Prompt ----------------
class PromptBuilder:
    SYSTEM_PROMPT = ("You are an expert equipment engineer. "
                     "Respond ONLY with valid JSON matching the requested keys.")

    def build(self, record: dict) -> str:
        return (
            "Assess the following medical device error logs and return your assessment as JSON.\n\n"
            f"Machine ID: {record.get('machine_id', 'unknown')}\n"
            f"Machine type: {record.get('machine_type', 'unknown')}\n"
            f"Timestamp: {record.get('timestamp', 'unknown')}\n"
            f"Raw error message: {record.get('raw_message', '')}\n\n"
            "Return exactly these keys:\n"
            '  "machine_subsystem": string, the specific component or subsystem at fault\n'
            '  "severity": integer 1-5 (1 = cosmetic or informational, '
            "3 = degraded function, 5 = device unusable or actively dangerous)\n"
            '  "root_cause_hypothesis": string, one sentence on the most likely cause\n'
            '  "patient_safety_risk": boolean, true only if this fault could directly '
            "harm a patient or produce a clinically misleading reading\n"
            '  "recurrence_indicator": boolean, true if the message itself shows the '
            "fault is repeating (repeat counts, cycling, 'again', multiple occurrences)\n"
            '  "recommended_action": string, the concrete next step for the technician\n'
            '  "confidence": float 0.0-1.0, your certainty in this assessment; be honest '
            "and use a low value when the message is vague or ambiguous\n\n"
            "Respond with the JSON object only."
        )


# ---------------- Parse + validate the reply ----------------
class ResponseValidator:
    SCHEMA = {
        "machine_subsystem": str,
        "severity": int,
        "root_cause_hypothesis": str,
        "patient_safety_risk": bool,
        "recurrence_indicator": bool,
        "recommended_action": str,
        "confidence": float,
    }

    def parse(self, raw: str) -> dict:
        """Pull the JSON object out of the reply text."""
        if not isinstance(raw, str):
            raise AIResponseError("AI response could not be parsed as JSON")
        start, end = raw.find("{"), raw.rfind("}")  # also skips ```json fences
        try:
            data = json.loads(raw[start:end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            raise AIResponseError("AI response could not be parsed as JSON")
        return data

    def validate(self, data: dict) -> dict:
        """Check keys, types and ranges, then return a clean copy."""
        for key, expected in self.SCHEMA.items():
            if key not in data or not self._is_type(data[key], expected):
                logger.error("Bad or missing key '%s': %r", key, data.get(key))
                raise AIResponseError("AI response failed schema validation")
        if not 1 <= data["severity"] <= 5 or not 0 <= data["confidence"] <= 1:
            raise AIResponseError("AI response failed schema validation")

        clean = {key: data[key] for key in self.SCHEMA}
        for key in ("machine_subsystem", "root_cause_hypothesis", "recommended_action"):
            clean[key] = clean[key].strip()
        clean["confidence"] = round(float(clean["confidence"]), 2)
        return clean

    @staticmethod
    def _is_type(value, expected) -> bool:
        if isinstance(value, bool):          # bool counts as int in Python
            return expected is bool
        if expected is float:
            return isinstance(value, (int, float))
        if expected is str:
            return isinstance(value, str) and value.strip() != ""
        return isinstance(value, expected)


# ---------------- AI Manager ----------------
class AIManager:
    def __init__(self, client: AIClient, max_attempts: int = 3, backoff_seconds: float = 2):
        self._client = client                  # association: passed in from outside
        self._prompts = PromptBuilder()        # composition: created and owned here
        self._validator = ResponseValidator()  # composition
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds

    def enrich_record(self, record: dict) -> dict:
        """Return a copy of the record with "ai" results, or "ai_error" on failure."""
        enriched = dict(record)
        prompt = self._prompts.build(record)
        last_error = "unknown failure"

        for attempt in range(1, self._max_attempts + 1):
            try:
                raw = self._client.complete(PromptBuilder.SYSTEM_PROMPT, prompt)
                enriched["ai"] = self._validator.validate(self._validator.parse(raw))
                enriched.pop("ai_error", None)
                return enriched
            except AIConfigError as error:
                last_error = str(error)
                break                                     # no point retrying
            except AIConnectionError as error:
                logger.warning("Attempt %d failed: %s", attempt, error)
                last_error = "AI API unreachable or returned an error"
            except AIResponseError as error:
                logger.warning("Attempt %d failed: %s", attempt, error)
                last_error = str(error)
            if attempt < self._max_attempts:
                time.sleep(self._backoff * attempt)

        enriched["ai"] = None
        enriched["ai_error"] = last_error
        logger.error("Record %s not enriched: %s", record.get("log_id"), last_error)
        return enriched


# Keeps teammates' existing `enrich_record(record)` calls working
def enrich_record(record: dict) -> dict:
    return AIManager(GeminiClient()).enrich_record(record)


if __name__ == "__main__":
    sample = {
        "machine_id": "MACHINE_001",
        "machine_type": "Infusion Pump",
        "timestamp": "2026-10-03 21:30:05",
        "raw_message": "Temperature exceeded 90°C",
    }
    manager = AIManager(GeminiClient())
    print(json.dumps(manager.enrich_record(sample), indent=2, ensure_ascii=False))