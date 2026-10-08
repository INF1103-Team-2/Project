"""Test for the Telegram part. Functions only, no print().

Run:  python test_telegram.py
- With no token in .env  -> checks the dry run works.
- With a token in .env   -> really sends a sample alert; check your phone!
"""

from dotenv import load_dotenv

load_dotenv()

import logic_manager as lm   # noqa: E402


SAMPLE = {
    "log_id": "test001", "machine_id": "CT-114", "machine_type": "CT scanner",
    "timestamp": "2026-10-03T21:30:05",
    "ai": {"machine_subsystem": "cooling system", "severity": 5,
           "root_cause_hypothesis": "Cooling fan failure", "patient_safety_risk": True,
           "recurrence_indicator": False, "recommended_action": "Stop scans, inspect fan",
           "confidence": 0.9},
    "decision": {"route": "immediate_escalation", "score": 90, "notify_now": True,
                 "scheduled_send_time": "2026-10-03T21:30:05",
                 "requires_human_review": False, "rules_fired": ["R1"]},
}


def test_message_has_key_info():
    text = lm.build_alert_message(SAMPLE)
    assert "CT-114" in text and "URGENT" in text and "Cooling fan failure" in text


def test_should_send_now_rules():
    assert lm.should_send_now(SAMPLE)
    review = {**SAMPLE, "decision": {**SAMPLE["decision"], "requires_human_review": True}}
    assert not lm.should_send_now(review)                 # Rule 5: never auto-send
    assert not lm.should_send_now(lm.mark_sent(SAMPLE))  # never send twice


def test_due_alerts_wait_until_7am():
    later = {**SAMPLE, "decision": {**SAMPLE["decision"], "notify_now": False,
                                    "scheduled_send_time": "2026-10-04T07:00:00"}}
    assert lm.get_due_alerts([later], "2026-10-04T06:59:59") == []
    assert lm.get_due_alerts([later], "2026-10-04T07:00:00") == [later]


def test_send_sample_alert():
    ok, info = lm.send_telegram(lm.build_alert_message(SAMPLE))
    assert ok or info.startswith("DRY RUN"), info


if __name__ == "__main__":
    for name, func in list(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
    # No print() here (spec rule) - if you see no error, all tests passed.
