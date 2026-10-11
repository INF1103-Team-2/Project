"""Minimal offline tests for core logic_manager functions.

Run with: python test_logic.py
AI assessments and Telegram HTTP calls are mocked; no live Telegram messages
are sent by this test script.
"""

import os
from datetime import datetime
from pprint import pformat
from types import SimpleNamespace
from unittest.mock import patch

import io_manager as io
import logic_manager as lm
import main


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


def test_malformed_ai_assessment() -> None:
    malformed_record = {
        **URGENT_RECORD,
        "ai": {**URGENT_RECORD["ai"], "severity": "high"},
    }
    decision = lm.evaluate(malformed_record, now=TEST_TIME)

    assert lm.score(malformed_record) == 0
    assert lm.route(malformed_record) == lm.ROUTE_AI_UNAVAILABLE
    assert lm.rules_fired(malformed_record) == ["R0_ai_unavailable"]
    assert decision["route"] == lm.ROUTE_AI_UNAVAILABLE
    assert decision["score"] == 0
    assert decision["requires_human_review"] is True


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
    }), patch.object(io.logger, "warning"), \
            patch.object(io.requests, "post") as post:
        results["missing config"] = io.send_telegram(text)
        post.assert_not_called()

    success_response = SimpleNamespace(
        status_code=200,
        text='{"ok":true}',
        json=lambda: {"ok": True, "result": {"message_id": 1}},
    )
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
    }), patch.object(io.requests, "post", return_value=success_response) as post:
        results["simulated success"] = io.send_telegram(text)
        post.assert_called_once_with(
            io.TELEGRAM_URL.format(token=token),
            data={"chat_id": chat_id, "text": text},
            timeout=10,
        )

    error_response = SimpleNamespace(status_code=503, text="service unavailable")
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
    }), patch.object(io.requests, "post", return_value=error_response), \
            patch.object(io.logger, "error"):
        results["simulated HTTP error"] = io.send_telegram(text)

    rejected_response = SimpleNamespace(
        status_code=200,
        text='{"ok":false,"description":"bot was blocked by the user"}',
        json=lambda: {"ok": False, "description": "bot was blocked by the user"},
    )
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
    }), patch.object(io.requests, "post", return_value=rejected_response), \
            patch.object(io.logger, "error"):
        results["Telegram rejection in HTTP 200"] = io.send_telegram(text)

    assert results == {
        "missing config": (False, "DRY RUN (Telegram not configured)"),
        "simulated success": (True, "Sent"),
        "simulated HTTP error": (False, "Telegram error 503"),
        "Telegram rejection in HTTP 200": (
            False,
            "Telegram rejected the message: bot was blocked by the user",
        ),
    }


def test_telegram_message_builders() -> None:
    review_text = io.build_human_review_message(
        {"log_id": "abc123", "machine_id": "CT-114"}
    )
    assert "A record needs human review" in review_text
    assert "Please check the CLI" in review_text
    assert "CT-114" in review_text
    assert "abc123" in review_text

    alert_text = io.build_alert_message({
        "log_id": "urgent-1",
        "machine_id": "CT-114",
        "machine_type": "CT scanner",
        "decision": {"notify_now": True, "score": 90},
        "ai": {"severity": 5, "patient_safety_risk": True},
    })
    assert "URGENT MACHINE ERROR" in alert_text
    assert "CT-114" in alert_text

    report_text = io.build_daily_report([{
        "machine_id": "XR-008",
        "ai": {"severity": 3, "machine_subsystem": "cooling"},
        "decision": {"route": "recurring_fault_review"},
    }])
    assert "DAILY MACHINE REPORT (1 item(s))" in report_text
    assert "XR-008" in report_text


def test_manual_review_recalculates_and_escalates() -> None:
    record = lm.process_record(
        {
            "log_id": "test-review",
            "machine_id": "CT-114",
            "machine_type": "CT scanner",
            "ai": None,
            "ai_error": "AI assessment unavailable",
        },
        now=datetime(2026, 10, 9, 10, 43),
    )

    with patch.object(main.data_manager, "query", return_value=[record]), \
            patch.object(main.data_manager, "add_record", return_value=True) as save, \
            patch.object(main.io_manager, "display_record") as display, \
            patch.object(main.io_manager, "display_message"), \
            patch.object(main.io_manager, "prompt_review_action",
                         return_value="Enter severity manually"), \
            patch.object(main.io_manager, "prompt_review_severity", return_value=5), \
            patch.object(main.io_manager, "prompt_review_safety_risk", return_value=True), \
            patch.object(main, "send_urgent_alert", side_effect=lambda item: item) as alert:
        main.handle_review_queue()

    updated = save.call_args_list[0].args[0]
    assert display.call_count == 1
    assert updated["ai"] is None
    assert updated["human_review"]["severity"] == 5
    assert updated["human_review"]["patient_safety_risk"] is True
    assert updated["decision"]["route"] == lm.ROUTE_IMMEDIATE
    assert updated["decision"]["requires_human_review"] is False
    assert alert.call_count == 1
    assert save.call_count == 2


def test_process_batch_sends_human_review_notification() -> None:
    record = {
        "log_id": "new-review",
        "machine_id": "CT-114",
        "machine_type": "CT scanner",
        "error_code": "E102",
        "timestamp": "2026-10-09T10:43:00",
        "ai": {
            "severity": 3,
            "patient_safety_risk": False,
            "recurrence_indicator": False,
            "confidence": 0.4,
        },
    }

    with patch.object(main.data_manager, "load_records", return_value=[]), \
            patch.object(main.ai_manager, "enrich_record", side_effect=lambda item: item), \
            patch.object(main.data_manager, "add_record", return_value=True) as save, \
            patch.object(main.io_manager, "send_telegram",
                         return_value=(True, "Sent")) as send, \
            patch.object(main.io_manager, "display_message"), \
            patch.object(main.io_manager, "display_result"):
        processed = main.process_batch([record], datetime(2026, 10, 9, 10, 43))

    assert send.call_count == 1
    assert "A record needs human review" in send.call_args.args[0]
    assert "Please check the CLI" in send.call_args.args[0]
    assert "new-review" in send.call_args.args[0]
    assert processed[0]["decision"]["requires_human_review"] is True
    assert processed[0]["decision"]["human_review_notification_sent"] is True
    assert save.call_count == 2


def test_process_batch_does_not_repeat_review_notification() -> None:
    record = {
        "log_id": "already-notified",
        "machine_id": "CT-114",
        "machine_type": "CT scanner",
        "error_code": "E102",
        "timestamp": "2026-10-09T10:43:00",
        "ai": {
            "severity": 3,
            "patient_safety_risk": False,
            "recurrence_indicator": False,
            "confidence": 0.4,
        },
    }
    stored = {
        **record,
        "decision": {"human_review_notification_sent": True},
    }

    with patch.object(main.data_manager, "load_records", return_value=[stored]), \
            patch.object(main.ai_manager, "enrich_record", side_effect=lambda item: item), \
            patch.object(main.data_manager, "add_record", return_value=True), \
            patch.object(main.io_manager, "send_telegram") as send, \
            patch.object(main.io_manager, "display_result"):
        processed = main.process_batch([record], datetime(2026, 10, 9, 10, 43))

    send.assert_not_called()
    assert processed[0]["decision"]["human_review_notification_sent"] is True


def test_background_dispatch_marks_reports_sent_without_cli_output() -> None:
    due_record = {
        "log_id": "test-due",
        "decision": {
            "route": lm.ROUTE_STANDARD,
            "score": 42,
            "notify_now": False,
            "requires_human_review": False,
            "notification_sent": False,
            "scheduled_send_time": "2026-10-10T07:00:00",
        },
    }

    with patch.object(main.data_manager, "load_records", return_value=[due_record]), \
            patch.object(main.logic_manager, "get_due_alerts", return_value=[due_record]), \
            patch.object(main.io_manager, "build_daily_report", return_value="Daily report"), \
            patch.object(main.io_manager, "send_telegram", return_value=(True, "Sent")) as send, \
            patch.object(main.data_manager, "add_record", return_value=True) as save, \
            patch.object(main.io_manager, "display_message") as display:
        main.dispatch_due_reports(show_message=False)

    send.assert_called_once_with("Daily report")
    assert save.call_args.args[0]["decision"]["notification_sent"] is True
    display.assert_not_called()


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
    test_malformed_ai_assessment,
    test_summarise,
    test_send_telegram,
    test_telegram_message_builders,
    test_manual_review_recalculates_and_escalates,
    test_process_batch_sends_human_review_notification,
    test_process_batch_does_not_repeat_review_notification,
    test_background_dispatch_marks_reports_sent_without_cli_output,
    test_should_send_now,
    test_get_due_alerts,
)


if __name__ == "__main__":
    print(
        "Running project tests (mocked AI/Telegram; no live network calls)..."
    )
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(TESTS)} tests passed.")
