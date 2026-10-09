"""Minimal offline tests for core logic_manager functions.

Run with: python test_logic.py
AI assessments are hardcoded and Telegram HTTP calls are mocked.
"""

import os
from datetime import datetime
from pprint import pformat
from types import SimpleNamespace
from unittest.mock import patch

import logic_manager as lm


TEST_TIME = datetime(2026, 10, 9, 10, 43, 0)

URGENT_RECORD = {
    "log_id": "test-urgent",
    "machine_id": "CT-114",
    "ai": {
        "severity": 5,
        "patient_safety_risk": True,
        "recurrence_indicator": False,
        "confidence": 0.95,
    },
}
REVIEW_RECORD = {
    "log_id": "test-review",
    "machine_id": "CT-114",
    "ai": {
        "severity": 5,
        "patient_safety_risk": False,
        "recurrence_indicator": False,
        "confidence": 0.4,
    },
}
DEFERRED_RECORD = {
    "log_id": "test-deferred",
    "machine_id": "XR-008",
    "ai": {
        "severity": 3,
        "patient_safety_risk": False,
        "recurrence_indicator": True,
        "confidence": 0.9,
    },
}


def test_process_record() -> None:
    records = {
        "urgent": lm.process_record(URGENT_RECORD, now=TEST_TIME),
        "human review": lm.process_record(REVIEW_RECORD, now=TEST_TIME),
        "deferred": lm.process_record(DEFERRED_RECORD, now=TEST_TIME),
    }
    decisions = {name: record["decision"] for name, record in records.items()}
    print("process_record decisions:")
    print(pformat(decisions))
    assert decisions["urgent"] == {
        "route": lm.ROUTE_IMMEDIATE,
        "score": 90,
        "notify_now": True,
        "scheduled_send_time": "2026-10-09T10:43:00",
        "requires_human_review": False,
        "rules_fired": ["R1_confident_high_severity_safety_risk"],
    }
    assert decisions["human review"]["route"] == lm.ROUTE_HUMAN_TRIAGE
    assert decisions["human review"]["requires_human_review"] is True
    assert decisions["deferred"]["route"] == lm.ROUTE_RECURRING
    assert decisions["deferred"]["scheduled_send_time"] == "2026-10-10T07:00:00"
    assert "decision" not in URGENT_RECORD


def test_summarise() -> None:
    records = [
        lm.process_record(URGENT_RECORD, now=TEST_TIME),
        lm.process_record(REVIEW_RECORD, now=TEST_TIME),
    ]
    summary = lm.summarise(records)
    print("summarise result:")
    print(pformat(summary))
    assert summary == {
        "total": 2,
        "safety_risk_count": 1,
        "human_review_count": 1,
        "mean_score": 72.5,
        "by_route": {
            lm.ROUTE_IMMEDIATE: 1,
            lm.ROUTE_HUMAN_TRIAGE: 1,
        },
        "repeat_offenders": [("CT-114", 2)],
    }
    assert lm.summarise([])["total"] == 0


def test_send_telegram() -> None:
    text = "Offline test alert"
    token = "test-token"
    chat_id = "12345"
    results = {}

    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }), patch.object(lm.logger, "warning"), \
            patch.object(lm.requests, "post") as post:
        results["missing config"] = lm.send_telegram(text)
        post.assert_not_called()

    success_response = SimpleNamespace(status_code=200, text='{"ok":true}')
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
    }), patch.object(lm.requests, "post", return_value=success_response) as post:
        results["simulated success"] = lm.send_telegram(text)
        post.assert_called_once_with(
            lm.TELEGRAM_URL.format(token=token),
            data={"chat_id": chat_id, "text": text},
            timeout=10,
        )

    error_response = SimpleNamespace(status_code=503, text="service unavailable")
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
    }), patch.object(lm.requests, "post", return_value=error_response), \
            patch.object(lm.logger, "error"):
        results["simulated HTTP error"] = lm.send_telegram(text)

    print("send_telegram results (simulated; no live Telegram request):")
    print(pformat(results))
    assert results == {
        "missing config": (False, "DRY RUN (Telegram not configured)"),
        "simulated success": (True, "Sent"),
        "simulated HTTP error": (False, "Telegram error 503"),
    }


def test_should_send_now() -> None:
    urgent = lm.process_record(URGENT_RECORD, now=TEST_TIME)
    needs_review = lm.process_record(REVIEW_RECORD, now=TEST_TIME)
    deferred = lm.process_record(DEFERRED_RECORD, now=TEST_TIME)
    results = {
        "urgent, unsent": lm.should_send_now(urgent),
        "human review": lm.should_send_now(needs_review),
        "deferred": lm.should_send_now(deferred),
        "already sent": lm.should_send_now(lm.mark_sent(urgent)),
    }
    print("should_send_now eligibility (True means attempt to send):")
    print(pformat(results))
    assert results == {
        "urgent, unsent": True,
        "human review": False,
        "deferred": False,
        "already sent": False,
    }


def test_get_due_alerts() -> None:
    deferred = lm.process_record(DEFERRED_RECORD, now=TEST_TIME)
    urgent = lm.process_record(URGENT_RECORD, now=TEST_TIME)
    needs_review = lm.process_record(REVIEW_RECORD, now=TEST_TIME)
    candidates = [
        deferred,
        lm.mark_sent(deferred),
        urgent,
        needs_review,
    ]
    before_due = lm.get_due_alerts(candidates, "2026-10-10T06:59:59")
    at_due = lm.get_due_alerts(candidates, "2026-10-10T07:00:00")
    results = {
        "before due": [record["machine_id"] for record in before_due],
        "at due": [record["machine_id"] for record in at_due],
    }
    print("get_due_alerts eligible machine IDs:")
    print(pformat(results))
    assert results == {"before due": [], "at due": ["XR-008"]}
    assert at_due == [deferred]


TESTS = (
    test_process_record,
    test_summarise,
    test_send_telegram,
    test_should_send_now,
    test_get_due_alerts,
)


if __name__ == "__main__":
    print(
        "Running logic_manager tests (hardcoded AI data; "
        "Telegram responses simulated; no live network calls)..."
    )
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(TESTS)} tests passed.")
