import json

import pytest

from ai_manager import (AIConfigError, AIConnectionError, AIManager,
                        AIResponseError, MockAIClient, ResponseValidator)

RECORD = {"log_id": "L1", "machine_id": "M1", "raw_message": "Temperature exceeded 90°C"}
VALID = {
    "machine_subsystem": " Heater ", "severity": 4,
    "root_cause_hypothesis": "Thermostat failure.", "patient_safety_risk": True,
    "recurrence_indicator": False, "recommended_action": "Replace thermostat.",
    "confidence": 0.876,
}


def reply(**changes):
    return json.dumps({**VALID, **changes})


def manager(replies):
    return AIManager(MockAIClient(replies), backoff_seconds=0)


def test_success():
    result = manager([reply()]).enrich_record(RECORD)
    assert result["ai"]["severity"] == 4
    assert result["ai"]["machine_subsystem"] == "Heater"
    assert result["ai"]["confidence"] == 0.88
    assert "ai_error" not in result


def test_input_record_not_changed():
    original = dict(RECORD)
    manager([reply()]).enrich_record(RECORD)
    assert RECORD == original


def test_parses_markdown_fenced_reply():
    assert manager(["```json\n" + reply() + "\n```"]).enrich_record(RECORD)["ai"]


def test_retry_then_success():
    assert manager([AIConnectionError("down"), reply()]).enrich_record(RECORD)["ai"]


@pytest.mark.parametrize("replies, expected", [
    ([AIConnectionError("x")] * 3, "AI API unreachable or returned an error"),
    (["not json"] * 3, "AI response could not be parsed as JSON"),
    ([reply(severity=9)] * 3, "AI response failed schema validation"),
])
def test_gives_up_after_3_attempts(replies, expected):
    result = manager(replies).enrich_record(RECORD)
    assert result["ai"] is None
    assert result["ai_error"] == expected


def test_missing_api_key_stops_immediately():
    result = manager([AIConfigError("AI_API_KEY is not configured")]).enrich_record(RECORD)
    assert result["ai_error"] == "AI_API_KEY is not configured"


@pytest.mark.parametrize("changes", [
    {"severity": 0}, {"severity": "4"}, {"severity": True}, {"confidence": 1.5},
    {"confidence": "0.8"}, {"patient_safety_risk": "yes"}, {"machine_subsystem": " "},
])
def test_validator_rejects_bad_values(changes):
    with pytest.raises(AIResponseError):
        ResponseValidator().validate(json.loads(reply(**changes)))


def test_validator_rejects_missing_key():
    data = json.loads(reply())
    del data["severity"]
    with pytest.raises(AIResponseError):
        ResponseValidator().validate(data)