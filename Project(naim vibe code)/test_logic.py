"""tests/test_logic.py - Automated tests (INF1103 Phase 1 deliverable 5.3).

Verifies the core logic independently of the live API. Every AI response used
here is hardcoded, so the suite runs with no network access and no API key,
inside or outside Docker.

Run with:  python tests/test_logic.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_manager
import data_manager
import logic_manager

PASSED = []
FAILED = []

FIXED_NOW = datetime(2026, 9, 16, 14, 30, 0)


# ===========================================================================
# Hardcoded AI responses
# ===========================================================================
def make_record(log_id: str, ai: dict, machine_id: str = "PUMP-114") -> dict:
    """Build a record that looks exactly like one ai_manager would return."""
    return {
        "log_id": log_id,
        "machine_id": machine_id,
        "machine_type": "infusion_pump",
        "timestamp": "2026-09-14T03:12:44",
        "reported_by": "test_fixture",
        "raw_message": "Downstream occlusion alarm repeated 6 times in 20 minutes",
        "ai": ai,
    }


AI_CRITICAL = {
    "machine_subsystem": "downstream occlusion sensor",
    "severity": 5,
    "root_cause_hypothesis": "Occlusion sensor calibration drift",
    "patient_safety_risk": True,
    "recurrence_indicator": True,
    "recommended_action": "Remove from service and recalibrate",
    "confidence": 0.91,
}

AI_HIGH_BUT_UNSURE = {
    "machine_subsystem": "unknown",
    "severity": 4,
    "root_cause_hypothesis": "Message too vague to attribute",
    "patient_safety_risk": True,
    "recurrence_indicator": False,
    "recommended_action": "Manual inspection required",
    "confidence": 0.35,
}

AI_RECURRING_MODERATE = {
    "machine_subsystem": "display backlight",
    "severity": 3,
    "root_cause_hypothesis": "Intermittent backlight inverter fault",
    "patient_safety_risk": False,
    "recurrence_indicator": True,
    "recommended_action": "Schedule inverter replacement",
    "confidence": 0.8,
}

AI_MINOR = {
    "machine_subsystem": "firmware logger",
    "severity": 1,
    "root_cause_hypothesis": "Informational log rotation notice",
    "patient_safety_risk": False,
    "recurrence_indicator": False,
    "recommended_action": "No action required",
    "confidence": 0.95,
}


# ===========================================================================
# Harness
# ===========================================================================
def check(name: str, condition: bool) -> None:
    """Record the outcome of one assertion without stopping the run."""
    try:
        assert condition
        PASSED.append(name)
    except AssertionError:
        FAILED.append(name)


# ===========================================================================
# logic_manager - routing rules
# ===========================================================================
def test_routing() -> None:
    check(
        "R1 confident high-severity safety risk escalates immediately",
        logic_manager.route(make_record("t1", AI_CRITICAL)) == logic_manager.ROUTE_IMMEDIATE,
    )
    check(
        "R2 high severity with low confidence goes to human triage, not auto-page",
        logic_manager.route(make_record("t2", AI_HIGH_BUT_UNSURE)) == logic_manager.ROUTE_HUMAN_TRIAGE,
    )
    check(
        "R3 recurring moderate fault goes to recurring fault review",
        logic_manager.route(make_record("t3", AI_RECURRING_MODERATE)) == logic_manager.ROUTE_RECURRING,
    )
    check(
        "R4 low severity with no safety risk is batched for scheduled maintenance",
        logic_manager.route(make_record("t4", AI_MINOR)) == logic_manager.ROUTE_SCHEDULED,
    )
    check(
        "Missing AI enrichment routes to manual review",
        logic_manager.route({"log_id": "t5", "ai": None}) == logic_manager.ROUTE_AI_UNAVAILABLE,
    )

    borderline = dict(AI_CRITICAL)
    borderline["confidence"] = logic_manager.CONFIDENT
    check(
        "Confidence exactly at the threshold still escalates",
        logic_manager.route(make_record("t6", borderline)) == logic_manager.ROUTE_IMMEDIATE,
    )

    no_risk = dict(AI_CRITICAL)
    no_risk["patient_safety_risk"] = False
    check(
        "High severity without a safety risk does not escalate immediately",
        logic_manager.route(make_record("t7", no_risk)) != logic_manager.ROUTE_IMMEDIATE,
    )


# ===========================================================================
# logic_manager - scoring
# ===========================================================================
def test_scoring() -> None:
    critical_score = logic_manager.score(make_record("s1", AI_CRITICAL))
    minor_score = logic_manager.score(make_record("s2", AI_MINOR))

    check("Critical fault scores higher than a minor one", critical_score > minor_score)
    check("Scores stay within 0-100", 0 <= critical_score <= 100 and 0 <= minor_score <= 100)
    check("A record with no AI output scores 0", logic_manager.score({"ai": None}) == 0)

    unsure = dict(AI_RECURRING_MODERATE)
    unsure["confidence"] = 0.2
    check(
        "Low confidence reduces the score",
        logic_manager.score(make_record("s3", unsure))
        < logic_manager.score(make_record("s4", AI_RECURRING_MODERATE)),
    )
    check(
        "Scoring is repeatable for identical input",
        logic_manager.score(make_record("s5", AI_CRITICAL))
        == logic_manager.score(make_record("s6", AI_CRITICAL)),
    )


# ===========================================================================
# logic_manager - evaluate and scheduling
# ===========================================================================
def test_evaluate() -> None:
    urgent = logic_manager.evaluate(make_record("e1", AI_CRITICAL), now=FIXED_NOW)
    check("Urgent decisions notify immediately", urgent["notify_now"] is True)
    check("Urgent decisions do not need human review", urgent["requires_human_review"] is False)
    check("Rule R1 is recorded in the audit trail",
          "R1_confident_high_severity_safety_risk" in urgent["rules_fired"])

    deferred = logic_manager.evaluate(make_record("e2", AI_MINOR), now=FIXED_NOW)
    check("Low priority decisions are deferred", deferred["notify_now"] is False)
    check("Deferred alerts are scheduled for the 07:00 working-day start",
          deferred["scheduled_send_time"].endswith("T07:00:00"))
    check("Deferred alerts are scheduled in the future",
          deferred["scheduled_send_time"] > FIXED_NOW.strftime("%Y-%m-%dT%H:%M:%S"))

    unsure = logic_manager.evaluate(make_record("e3", AI_HIGH_BUT_UNSURE), now=FIXED_NOW)
    check("Uncertain high-severity records are flagged for a human",
          unsure["requires_human_review"] is True)

    check(
        "evaluate is deterministic for a fixed 'now'",
        logic_manager.evaluate(make_record("e4", AI_MINOR), now=FIXED_NOW)
        == logic_manager.evaluate(make_record("e5", AI_MINOR), now=FIXED_NOW),
    )

    failed = logic_manager.evaluate({"log_id": "e6", "ai": None, "ai_error": "timeout"},
                                    now=FIXED_NOW)
    check("An AI failure still produces a usable decision",
          failed["route"] == logic_manager.ROUTE_AI_UNAVAILABLE
          and failed["requires_human_review"] is True)


def test_summarise() -> None:
    records = [
        logic_manager.process_record(make_record("m1", AI_CRITICAL, "PUMP-114"), now=FIXED_NOW),
        logic_manager.process_record(make_record("m2", AI_MINOR, "PUMP-114"), now=FIXED_NOW),
        logic_manager.process_record(make_record("m3", AI_RECURRING_MODERATE, "MON-007"), now=FIXED_NOW),
    ]
    summary = logic_manager.summarise(records)

    check("Summary counts every record", summary["total"] == 3)
    check("Summary counts patient safety flags", summary["safety_risk_count"] == 1)
    check("Summary groups by route", sum(summary["by_route"].values()) == 3)
    check("Summary identifies repeat offenders",
          summary["repeat_offenders"] and summary["repeat_offenders"][0][0] == "PUMP-114")
    check("Empty input produces an empty summary, not a crash",
          logic_manager.summarise([])["total"] == 0)


# ===========================================================================
# ai_manager - parsing and validation (no network involved)
# ===========================================================================
def test_parse_response() -> None:
    check("Plain JSON parses", ai_manager.parse_response(json.dumps(AI_CRITICAL)) is not None)
    check(
        "JSON wrapped in a markdown fence parses",
        ai_manager.parse_response("```json\n" + json.dumps(AI_MINOR) + "\n```") is not None,
    )
    check(
        "JSON with surrounding prose parses",
        ai_manager.parse_response("Here you go: " + json.dumps(AI_MINOR) + " Hope that helps!")
        is not None,
    )
    check("Free text returns None", ai_manager.parse_response("The pump seems broken.") is None)
    check("Truncated JSON returns None", ai_manager.parse_response('{"severity": 4,') is None)
    check("Empty input returns None", ai_manager.parse_response("") is None)
    check("None input returns None", ai_manager.parse_response(None) is None)
    check("A JSON list is rejected", ai_manager.parse_response("[1, 2, 3]") is None)


def test_validate_response() -> None:
    check("A complete response validates", ai_manager.validate_response(AI_CRITICAL) is True)

    missing = dict(AI_CRITICAL)
    del missing["severity"]
    check("A missing required key is rejected", ai_manager.validate_response(missing) is False)

    wrong_type = dict(AI_CRITICAL)
    wrong_type["severity"] = "high"
    check("A string severity is rejected", ai_manager.validate_response(wrong_type) is False)

    out_of_range = dict(AI_CRITICAL)
    out_of_range["severity"] = 9
    check("Severity above 5 is rejected", ai_manager.validate_response(out_of_range) is False)

    bad_confidence = dict(AI_CRITICAL)
    bad_confidence["confidence"] = 1.8
    check("Confidence above 1.0 is rejected", ai_manager.validate_response(bad_confidence) is False)

    bad_bool = dict(AI_CRITICAL)
    bad_bool["patient_safety_risk"] = "yes"
    check("A string in place of a boolean is rejected",
          ai_manager.validate_response(bad_bool) is False)

    empty_string = dict(AI_CRITICAL)
    empty_string["machine_subsystem"] = "   "
    check("A blank string field is rejected", ai_manager.validate_response(empty_string) is False)

    check("None is rejected", ai_manager.validate_response(None) is False)


# ===========================================================================
# data_manager - persistence against a temporary file
# ===========================================================================
def test_data_manager() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "records.json")

        check("Loading a missing file returns an empty list", data_manager.load(path) == [])

        record = logic_manager.process_record(make_record("d1", AI_CRITICAL), now=FIXED_NOW)
        check("Saving a record succeeds", data_manager.save(record, path=path) is True)
        check("The saved record can be loaded back", len(data_manager.load(path)) == 1)

        check("Saving the same log_id again replaces it rather than duplicating",
              data_manager.save(record, path=path) and len(data_manager.load(path)) == 1)

        second = logic_manager.process_record(make_record("d2", AI_MINOR, "MON-007"), now=FIXED_NOW)
        data_manager.save(second, path=path)
        check("A second distinct record is appended", len(data_manager.load(path)) == 2)

        matches = data_manager.query(
            lambda item: item.get("decision", {}).get("route") == logic_manager.ROUTE_IMMEDIATE,
            path=path,
        )
        check("query() filters by route", len(matches) == 1 and matches[0]["log_id"] == "d1")

        check("query() with a filter that never matches returns an empty list",
              data_manager.query(lambda item: False, path=path) == [])
        check("query() survives a filter that raises",
              isinstance(data_manager.query(lambda item: item["nope"], path=path), list))

        check("exists() finds a stored log_id", data_manager.exists("d1", path=path) is True)
        check("exists() returns False for an unknown log_id",
              data_manager.exists("nope", path=path) is False)

        check("A record with no log_id is refused",
              data_manager.save({"machine_id": "X"}, path=path) is False)

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        check("A corrupt file loads as an empty list instead of crashing",
              data_manager.load(path) == [])

        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"log_id": "x"}')
        check("A JSON object where a list is expected loads as empty",
              data_manager.load(path) == [])


def test_determinism() -> None:
    """The same input must produce an identical stored file across runs."""
    records = [make_record("z1", AI_CRITICAL), make_record("z2", AI_MINOR, "MON-007")]
    outputs = []

    for _ in range(2):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "records.json")
            for record in records:
                data_manager.save(
                    logic_manager.process_record(record, now=FIXED_NOW), path=path
                )
            with open(path, "r", encoding="utf-8") as handle:
                outputs.append(handle.read())

    check("Two runs on the same input produce byte-identical files",
          outputs[0] == outputs[1])


# ===========================================================================
# Runner
# ===========================================================================
def run() -> int:
    """Run every test group and report. Returns a shell exit code."""
    for test in (
        test_routing,
        test_scoring,
        test_evaluate,
        test_summarise,
        test_parse_response,
        test_validate_response,
        test_data_manager,
        test_determinism,
    ):
        test()

    total = len(PASSED) + len(FAILED)
    print(f"\n{'=' * 68}")
    print(f"  INF1103 Phase 1 test suite: {len(PASSED)}/{total} passed")
    print(f"{'=' * 68}")

    for name in PASSED:
        print(f"  PASS  {name}")
    for name in FAILED:
        print(f"  FAIL  {name}")

    if FAILED:
        print(f"\n  {len(FAILED)} test(s) failed.\n")
        return 1
    print("\n  All tests passed. No API connection was used.\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
