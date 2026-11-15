"""Offline tests for the Phase 2 (OOP) classes.

Run with: python test_logic.py
AI and Telegram are mocked; no live network calls are made.
"""

import logging
import os
import tempfile
from datetime import datetime
from pprint import pformat
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ai_manager_ai_client as ai_module
import io_manager_telegram_notifier as telegram_module
from ai_manager_ai_client import AIClient
from data_manager_record_repository import RecordRepository
from io_manager_console_ui import ConsoleUI
from io_manager_log_file_reader import LogFileReader
from io_manager_telegram_notifier import TelegramNotifier
from logic_manager_ai_assessment import AIAssessment
from logic_manager_alert_scheduler import AlertScheduler
from logic_manager_error_log import ErrorLog
from logic_manager_fleet_analyzer import FleetAnalyzer
from logic_manager_triage_engine import TriageEngine
from io_manager_html_report_formatter import HTMLReportFormatter
from io_manager_markdown_report_formatter import MarkdownReportFormatter
from io_manager_report_manager import ReportManager
from main_triage_app import TriageApp
from main_triage_pipeline import TriagePipeline

TEST_TIME = datetime(2026, 10, 9, 10, 43, 0)
ENGINE = TriageEngine()
SCHEDULER = AlertScheduler()


def make_log(log_id: str, machine_id: str, severity=None, safety=False,
             recurring=False, confidence=0.9, timestamp="2026-10-09T10:43:00") -> ErrorLog:
    """Build an ErrorLog with an AI assessment (or none if severity is None)."""
    log = ErrorLog(machine_id, "E102", "CT scanner", timestamp, "test",
                   "test message text", log_id=log_id)
    if severity is not None:
        log.set_ai_assessment(AIAssessment("subsystem", severity, "cause", safety,
                                           recurring, "action", confidence))
    return log


def urgent() -> ErrorLog:
    return make_log("test-urgent", "CT-114", 5, safety=True, confidence=0.95)


def needs_review() -> ErrorLog:
    return make_log("test-review", "CT-114", 5, confidence=0.4)


def deferred() -> ErrorLog:
    return make_log("test-deferred", "XR-008", 3, recurring=True, confidence=0.9)


def evaluated(log: ErrorLog) -> ErrorLog:
    ENGINE.evaluate(log, now=TEST_TIME)
    return log


def make_pipeline(**overrides) -> TriagePipeline:
    """A TriagePipeline whose collaborators are all mocks unless overridden."""
    parts = dict(view=MagicMock(), ai=MagicMock(), engine=ENGINE, scheduler=SCHEDULER,
                 repository=MagicMock(), notifiers=[], telegram=MagicMock())
    parts.update(overrides)
    return TriagePipeline(**parts)


def make_app(ui, repository, pipeline) -> TriageApp:
    return TriageApp(ui=ui, reader=MagicMock(), pipeline=pipeline, repository=repository,
                     analyzer=FleetAnalyzer(), report_manager=MagicMock())


# ---------------------------------------------------------------------------
def test_evaluate() -> None:
    logs = {"urgent": evaluated(urgent()), "human review": evaluated(needs_review()),
            "deferred": evaluated(deferred())}
    decisions = {name: log.decision.to_dict() for name, log in logs.items()}
    print("evaluate decisions:")
    print(pformat(decisions))
    assert decisions["urgent"] == {
        "route": TriageEngine.ROUTE_IMMEDIATE,
        "score": 90,
        "notify_now": True,
        "scheduled_send_time": "2026-10-09T10:43:00",
        "requires_human_review": False,
        "rules_fired": ["R1_confident_high_severity_safety_risk"],
    }
    assert decisions["human review"]["route"] == TriageEngine.ROUTE_HUMAN_TRIAGE
    assert decisions["human review"]["requires_human_review"] is True
    assert decisions["deferred"]["route"] == TriageEngine.ROUTE_RECURRING
    assert decisions["deferred"]["scheduled_send_time"] == "2026-10-10T07:00:00"


def test_invalid_assessment_is_rejected() -> None:
    """Encapsulation: an Assessment with a bad severity can't even be created."""
    try:
        AIAssessment("subsystem", "high", "cause", True, False, "action", 0.95)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid severity was accepted")

    log = evaluated(make_log("no-ai", "CT-114"))      # no AI assessment at all
    assert log.decision.route == TriageEngine.ROUTE_AI_UNAVAILABLE
    assert log.decision.score == 0
    assert log.decision.rules_fired == ["R0_ai_unavailable"]
    assert log.decision.requires_human_review is True


def test_human_assessment_overrides_ai() -> None:
    """Polymorphism/LSP: the engine treats a HumanAssessment like an AIAssessment."""
    log = needs_review()
    log.record_human_review(severity=5, safety_risk=True, source="human_assessed")
    evaluated(log)
    assert log.effective_assessment().confidence() == 1.0
    assert log.decision.route == TriageEngine.ROUTE_IMMEDIATE
    assert log.decision.rules_fired[0] == "R6_human_assessment_approved"


def test_summarise() -> None:
    summary = FleetAnalyzer().summarise([evaluated(urgent()), evaluated(needs_review())])
    print("summarise result:")
    print(pformat(summary))
    assert summary == {
        "total": 2,
        "safety_risk_count": 1,
        "human_review_count": 1,
        "mean_score": 72.5,
        "by_route": {TriageEngine.ROUTE_IMMEDIATE: 1, TriageEngine.ROUTE_HUMAN_TRIAGE: 1},
        "repeat_offenders": [("CT-114", 2)],
    }
    assert FleetAnalyzer().summarise([])["total"] == 0


def test_json_round_trip() -> None:
    """to_dict() / from_dict() keep the Phase 1 JSON format unchanged."""
    log = evaluated(urgent())
    log.decision.mark_sent()
    assert ErrorLog.from_dict(log.to_dict()).to_dict() == log.to_dict()

    with tempfile.TemporaryDirectory() as folder:
        repository = RecordRepository(os.path.join(folder, "records.json"))
        assert repository.load_all() == []
        assert repository.save(log) is True
        assert repository.save(log) is True              # replaced, not duplicated
        assert len(repository.load_all()) == 1
        assert repository.get("test-urgent").decision.notification_sent is True


def test_send_telegram() -> None:
    text = "Offline test alert"
    results = {}
    with patch.object(telegram_module.requests, "post") as post:
        results["missing config"] = TelegramNotifier("", "")._post(text)
        post.assert_not_called()

    notifier = TelegramNotifier("test-token", "12345")
    success = SimpleNamespace(status_code=200, text='{"ok":true}',
                              json=lambda: {"ok": True, "result": {"message_id": 1}})
    with patch.object(telegram_module.requests, "post", return_value=success) as post:
        results["simulated success"] = notifier._post(text)
        post.assert_called_once_with(
            TelegramNotifier.TELEGRAM_URL.format(token="test-token"),
            data={"chat_id": "12345", "text": text}, timeout=10)

    error = SimpleNamespace(status_code=503, text="service unavailable")
    with patch.object(telegram_module.requests, "post", return_value=error):
        results["simulated HTTP error"] = notifier._post(text)

    rejected = SimpleNamespace(
        status_code=200, text="",
        json=lambda: {"ok": False, "description": "bot was blocked by the user"})
    with patch.object(telegram_module.requests, "post", return_value=rejected):
        results["Telegram rejection in HTTP 200"] = notifier._post(text)

    assert results == {
        "missing config": (False, "DRY RUN (Telegram not configured)"),
        "simulated success": (True, "Sent"),
        "simulated HTTP error": (False, "Telegram error 503"),
        "Telegram rejection in HTTP 200": (
            False, "Telegram rejected the message: bot was blocked by the user"),
    }


def test_telegram_message_builders() -> None:
    notifier = TelegramNotifier("t", "c")
    sent = []
    notifier._post = lambda text: (sent.append(text), (True, "Sent"))[1]

    notifier.send_review_request(make_log("abc123", "CT-114"))
    assert "A record needs human review" in sent[-1]
    assert "Please check the CLI" in sent[-1]
    assert "CT-114" in sent[-1] and "abc123" in sent[-1]

    assert notifier.notify_urgent(evaluated(urgent())) == (True, "Telegram: Sent")
    assert "URGENT MACHINE ERROR" in sent[-1] and "CT-114" in sent[-1]

    notifier.send_daily_report([evaluated(deferred())])
    assert "DAILY MACHINE REPORT (1 item(s))" in sent[-1]
    assert "XR-008" in sent[-1]


def test_manual_review_recalculates_and_escalates() -> None:
    log = evaluated(make_log("test-review", "CT-114"))   # AI unavailable
    ui = MagicMock()
    ui.prompt_review_action.return_value = "Enter severity manually"
    ui.prompt_review_severity.return_value = 5
    ui.prompt_review_safety_risk.return_value = True
    repository = MagicMock()
    repository.query.return_value = [log]
    repository.save.return_value = True
    pipeline = make_pipeline(view=ui, repository=repository)
    app = make_app(ui=ui, repository=repository, pipeline=pipeline)

    with patch.object(pipeline, "_send_urgent_alert") as alert:
        app._handle_review_queue()

    assert ui.display_record.call_count == 1
    assert log.ai_assessment is None
    assert log.human_assessment.severity == 5
    assert log.human_assessment.patient_safety_risk is True
    assert log.decision.route == TriageEngine.ROUTE_IMMEDIATE
    assert log.decision.requires_human_review is False
    assert alert.call_count == 1
    assert repository.save.call_count == 2


def test_process_batch_sends_human_review_notification() -> None:
    log = make_log("new-review", "CT-114", 3, confidence=0.4)
    repository = MagicMock()
    repository.load_all.return_value = []
    repository.save.return_value = True
    telegram = MagicMock()
    telegram.send_review_request.return_value = (True, "Sent")
    pipeline = make_pipeline(repository=repository, telegram=telegram)

    processed = pipeline.process_batch([log], TEST_TIME)

    assert telegram.send_review_request.call_count == 1
    assert processed[0].decision.requires_human_review is True
    assert processed[0].decision.review_notification_sent is True
    assert repository.save.call_count == 2


def test_process_batch_does_not_repeat_review_notification() -> None:
    log = make_log("already-notified", "CT-114", 3, confidence=0.4)
    stored = ErrorLog.from_dict({**log.to_dict(),
                                 "decision": {"human_review_notification_sent": True}})
    repository = MagicMock()
    repository.load_all.return_value = [stored]
    repository.save.return_value = True
    telegram = MagicMock()
    pipeline = make_pipeline(repository=repository, telegram=telegram)

    processed = pipeline.process_batch([log], TEST_TIME)

    telegram.send_review_request.assert_not_called()
    assert processed[0].decision.review_notification_sent is True


def test_background_dispatch_marks_reports_sent_without_cli_output() -> None:
    due = evaluated(deferred())
    repository = MagicMock()
    repository.load_all.return_value = [due]
    repository.save.return_value = True
    telegram = MagicMock()
    telegram.send_daily_report.return_value = (True, "Sent")
    view = MagicMock()
    pipeline = make_pipeline(view=view, repository=repository, telegram=telegram)

    with patch("main_triage_pipeline.datetime") as clock:
        clock.now.return_value = datetime(2026, 10, 10, 7, 0)
        pipeline.dispatch_due_reports(show_message=False)

    telegram.send_daily_report.assert_called_once_with([due])
    assert repository.save.call_args.args[0].decision.notification_sent is True
    view.display_message.assert_not_called()


def test_should_send_now() -> None:
    sent_urgent = evaluated(urgent())
    sent_urgent.decision.mark_sent()
    results = {
        "urgent, unsent": SCHEDULER.should_send_now(evaluated(urgent())),
        "human review": SCHEDULER.should_send_now(evaluated(needs_review())),
        "deferred": SCHEDULER.should_send_now(evaluated(deferred())),
        "already sent": SCHEDULER.should_send_now(sent_urgent),
    }
    print("should_send_now eligibility (True means attempt to send):")
    print(pformat(results))
    assert results == {"urgent, unsent": True, "human review": False,
                       "deferred": False, "already sent": False}


def test_get_due_alerts() -> None:
    waiting = evaluated(deferred())
    already_sent = evaluated(deferred())
    already_sent.decision.mark_sent()
    candidates = [waiting, already_sent, evaluated(urgent()), evaluated(needs_review())]
    before = SCHEDULER.get_due_alerts(candidates, datetime(2026, 10, 10, 6, 59, 59))
    at_due = SCHEDULER.get_due_alerts(candidates, datetime(2026, 10, 10, 7, 0, 0))
    results = {"before due": [log.machine_id for log in before],
               "at due": [log.machine_id for log in at_due]}
    print("get_due_alerts eligible machine IDs:")
    print(pformat(results))
    assert results == {"before due": [], "at due": ["XR-008"]}
    assert at_due == [waiting]


def test_confidence_threshold_is_70_percent() -> None:
    """Business Rule 5: below 70% confidence -> human review; 70% or more is trusted."""
    below = evaluated(make_log("c69", "CT-114", 3, confidence=0.69))
    at = evaluated(make_log("c70", "CT-114", 3, confidence=0.70))
    above = evaluated(make_log("c72", "CT-114", 3, confidence=0.72))
    assert TriageEngine.CONFIDENT == 0.70
    assert below.decision.route == TriageEngine.ROUTE_HUMAN_TRIAGE
    assert at.decision.route == TriageEngine.ROUTE_STANDARD
    assert above.decision.route == TriageEngine.ROUTE_STANDARD
    assert "R2_low_confidence_pending_review" not in at.decision.rules_fired


def test_bundle_repeats() -> None:
    """Rule 3: same machine + error code within 10 minutes -> one notification."""
    first = evaluated(make_log("a", "CT-114", 5, True, timestamp="2026-10-09T08:00:00"))
    second = evaluated(make_log("b", "CT-114", 5, True, timestamp="2026-10-09T08:04:00"))
    later = evaluated(make_log("c", "CT-114", 5, True, timestamp="2026-10-09T08:30:00"))
    SCHEDULER.bundle_repeats([first, second, later])
    assert first.decision.bundled_count == 2
    assert second.decision.suppressed_by == "a"
    assert second.decision.notification_sent is True
    assert later.decision.suppressed_by is None


def test_bug_fix_query_safety_risk_without_ai() -> None:
    """Phase 1 crashed here when a record had no AI assessment."""
    ui = ConsoleUI()
    with patch.object(ui, "_ask_choice",
                      return_value="Records flagged as a patient safety risk"), \
            patch("builtins.print"):
        predicate = ui.prompt_query_filter()
    assert predicate(make_log("no-ai", "CT-114")) is False
    assert predicate(evaluated(urgent())) is True


def test_bug_fix_text_confidence_is_rejected() -> None:
    """Phase 1 crashed on a text confidence; now it fails validation and retries."""
    client = AIClient("http://fake", "model", "key")
    bad = {"machine_subsystem": "x", "severity": 3, "root_cause_hypothesis": "y",
           "patient_safety_risk": False, "recurrence_indicator": False,
           "recommended_action": "z", "confidence": "high"}
    assert client._validate(bad) is False
    log = make_log("bad-ai", "CT-114")
    with patch.object(client, "_call_api", return_value='{"severity": 3}'), \
            patch("ai_manager_ai_client.time.sleep"):
        client.enrich(log)
    assert log.ai_assessment is None
    assert log.ai_error == "AI response failed schema validation"


def test_notifiers_are_substitutable() -> None:
    """LSP: the pipeline treats every Notifier the same way; only a real delivery
    (Telegram) marks the log as sent."""
    screen = MagicMock()
    screen.notify_urgent.return_value = (False, "")
    phone = MagicMock()
    phone.notify_urgent.return_value = (True, "Telegram: Sent")
    view = MagicMock()
    log = evaluated(urgent())
    make_pipeline(view=view, notifiers=[screen, phone])._send_urgent_alert(log)
    assert log.decision.notification_sent is True
    view.display_message.assert_called_once_with("Telegram: Sent")

    log = evaluated(urgent())
    make_pipeline(notifiers=[screen])._send_urgent_alert(log)
    assert log.decision.notification_sent is False


def test_html_report() -> None:
    """New feature: the HTML report is written to a file and escapes log text."""
    log = evaluated(make_log("x1", "CT-114", 5, True, confidence=0.95))
    log._raw_message = "<script>alert('x')</script> pump failure"
    with tempfile.TemporaryDirectory() as folder:
        manager = ReportManager(folder, [HTMLReportFormatter(), MarkdownReportFormatter()])
        assert manager.available_formats() == ["HTML", "Markdown"]
        path = manager.generate([log], "HTML", now=datetime(2026, 11, 7, 2, 0))
        assert path.endswith("report_20261107_020000.html")
        html = open(path, encoding="utf-8").read()
    assert html.startswith("<!DOCTYPE html>")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "immediate_escalation" in html and "CT-114" in html
    assert manager.generate([log], "PDF") is None


def test_markdown_report() -> None:
    """Polymorphism: same ReportManager call, different formatter, different file."""
    logs = [evaluated(urgent()), evaluated(needs_review())]
    with tempfile.TemporaryDirectory() as folder:
        manager = ReportManager(folder, [HTMLReportFormatter(), MarkdownReportFormatter()])
        path = manager.generate(logs, "Markdown", now=datetime(2026, 11, 7, 2, 0))
        text = open(path, encoding="utf-8").read()
    assert path.endswith(".md")
    assert text.startswith("# Biomedical Equipment Error Report")
    assert "| Records stored | 2 |" in text
    assert "Awaiting human review" in text


def test_gui_notifier() -> None:
    """The GUI pop-up notifier behaves like ConsoleNotifier (skipped without Tkinter)."""
    try:
        from io_manager_gui_notifier import GuiNotifier
    except ImportError:
        print("  (Tkinter not installed - GUI notifier test skipped)")
        return
    window = MagicMock()
    assert GuiNotifier(window).notify_urgent(evaluated(urgent())) == (False, "")
    assert "CT-114" in window.show_alert.call_args.args[0]


# ---------------------------------------------------------------------------
# Part 2 error-handling tests (API failure, bad AI replies, missing/corrupt
# files, bad input). All offline: requests.post is patched, files are temporary.
# ---------------------------------------------------------------------------
GOOD_AI_REPLY = ('{"machine_subsystem": "Cooling", "severity": 4, '
                 '"root_cause_hypothesis": "Pump failure.", "patient_safety_risk": true, '
                 '"recurrence_indicator": false, "recommended_action": "Check pump.", '
                 '"confidence": 0.9}')


def fake_ai_response(body) -> SimpleNamespace:
    """A stand-in for requests.Response with HTTP 200 and the given JSON body."""
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


def ai_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def offline_client() -> AIClient:
    client = AIClient("http://fake", "model", "key")
    client._retry_backoff_seconds = 0          # no real waiting in tests
    return client


def test_ai_api_down_retries_then_human_review() -> None:
    """API unreachable 3 times -> no crash, reason stored, record goes to human review."""
    log = make_log("api-down", "CT-114")
    with patch.object(ai_module.requests, "post",
                      side_effect=ai_module.requests.ConnectionError("down")) as post:
        offline_client().enrich(log)
    assert post.call_count == AIClient.MAX_ATTEMPTS
    assert log.ai_assessment is None
    assert log.ai_error == "AI API unreachable or returned an error"
    ENGINE.evaluate(log, now=TEST_TIME)
    assert log.decision.requires_human_review is True


def test_ai_retry_then_success() -> None:
    """One timeout, then a good reply -> the record is still enriched."""
    log = make_log("retry-ok", "CT-114")
    replies = [ai_module.requests.Timeout("slow"), fake_ai_response(ai_body(GOOD_AI_REPLY))]
    with patch.object(ai_module.requests, "post", side_effect=replies) as post:
        offline_client().enrich(log)
    assert post.call_count == 2
    assert log.ai_assessment.severity == 4
    assert log.ai_error is None


def test_ai_wrong_shape_reply_does_not_crash() -> None:
    """Bug fix (Part 2): HTTP 200 without 'choices' used to raise KeyError/IndexError."""
    bodies = {
        "error object": {"error": {"message": "Provider returned error"}},
        "empty choices": {"choices": []},
        "body is a list": [1, 2, 3],
    }
    for name, body in bodies.items():
        log = make_log(f"shape-{name}", "CT-114")
        with patch.object(ai_module.requests, "post", return_value=fake_ai_response(body)):
            offline_client().enrich(log)           # must not raise
        assert log.ai_assessment is None, name
        assert log.ai_error == "AI API unreachable or returned an error", name


def test_ai_bad_replies_are_rejected() -> None:
    """Not JSON / out-of-range values -> rejected after 3 tries; fenced JSON is accepted."""
    cases = {
        "not json": ("Sorry, I cannot help.", "AI response could not be parsed as JSON"),
        "severity 9": (GOOD_AI_REPLY.replace('"severity": 4', '"severity": 9'),
                       "AI response failed schema validation"),
        "confidence 1.5": (GOOD_AI_REPLY.replace('0.9}', '1.5}'),
                           "AI response failed schema validation"),
    }
    for name, (content, expected) in cases.items():
        log = make_log(f"bad-{name}", "CT-114")
        with patch.object(ai_module.requests, "post",
                          return_value=fake_ai_response(ai_body(content))):
            offline_client().enrich(log)
        assert log.ai_error == expected, name

    fenced = make_log("fenced", "CT-114")
    with patch.object(ai_module.requests, "post",
                      return_value=fake_ai_response(ai_body("```json\n" + GOOD_AI_REPLY + "\n```"))):
        offline_client().enrich(fenced)
    assert fenced.ai_assessment is not None


def test_missing_api_key_skips_the_call() -> None:
    log = make_log("no-key", "CT-114")
    with patch.object(ai_module.requests, "post") as post:
        AIClient("http://fake", "model", "").enrich(log)
    post.assert_not_called()
    assert log.ai_error == "AI_API_KEY is not configured"


def test_corrupt_records_file_is_backed_up_not_lost() -> None:
    """Bug fix (Part 2): a corrupt JSON file used to be silently overwritten."""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "records.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('[{"log_id": "old-record"} THIS IS BROKEN')
        repository = RecordRepository(path)
        assert repository.load_all() == []
        assert "corrupt" in repository.last_problem

        assert repository.save(evaluated(urgent())) is True
        backups = [name for name in os.listdir(folder) if ".corrupt-" in name]
        assert len(backups) == 1                                  # old data kept
        with open(os.path.join(folder, backups[0]), encoding="utf-8") as handle:
            assert "old-record" in handle.read()
        assert [log.log_id for log in repository.load_all()] == ["test-urgent"]
        assert repository.last_problem is None


def test_unreadable_records_file_does_not_crash() -> None:
    """Bug fix (Part 2): a non-UTF-8 file or a folder path used to crash load_all()."""
    with tempfile.TemporaryDirectory() as folder:
        binary = os.path.join(folder, "binary.json")
        with open(binary, "wb") as handle:
            handle.write(b"\xff\xfe\x00 not text")
        assert RecordRepository(binary).load_all() == []

        as_folder = RecordRepository(folder)                      # path is a directory
        assert as_folder.load_all() == []
        assert as_folder.save(evaluated(urgent())) is False       # reported, not raised


def test_pipeline_reports_corrupt_records_file() -> None:
    """The user is told about a corrupt file instead of it failing silently."""
    repository = MagicMock()
    repository.load_all.return_value = []
    repository.last_problem = "Records file is corrupt (JSONDecodeError)"
    view = MagicMock()
    make_pipeline(view=view, repository=repository).process_batch([], TEST_TIME)
    assert "corrupt" in view.display_error.call_args.args[0]


def test_log_file_bad_input() -> None:
    """Missing file, bad lines and an all-bad file (Business Rule 4) never crash."""
    reader = LogFileReader()
    logs, problems = reader.read("this_file_does_not_exist.txt")
    assert logs == [] and problems[0].startswith("File could not be opened")

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "errors.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("2026-09-16 21:30:05 | CT-114 | E102 | CT scanner | "
                         "Coolant temperature exceeded 90C\n"
                         "not | enough | fields\n"
                         "yesterday | CT-114 | E102 | CT scanner | Bad timestamp line here\n"
                         "2026-09-16 21:31:00 | ! | E102 | CT scanner | Bad machine id line\n")
        logs, problems = reader.read(path)
        assert len(logs) == 1 and len(problems) == 3

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("garbage\nmore garbage\n")
        ui, pipeline = MagicMock(), MagicMock()
        ui.prompt_file_path.return_value = path
        app = TriageApp(ui=ui, reader=reader, pipeline=pipeline, repository=MagicMock(),
                        analyzer=FleetAnalyzer(), report_manager=MagicMock())
        app._handle_file_ingest()
        ui.display_error.assert_called_once_with(LogFileReader.INVALID_FILE_MESSAGE)
        pipeline.process_batch.assert_not_called()


TESTS = (
    test_evaluate,
    test_invalid_assessment_is_rejected,
    test_human_assessment_overrides_ai,
    test_summarise,
    test_json_round_trip,
    test_send_telegram,
    test_telegram_message_builders,
    test_manual_review_recalculates_and_escalates,
    test_process_batch_sends_human_review_notification,
    test_process_batch_does_not_repeat_review_notification,
    test_background_dispatch_marks_reports_sent_without_cli_output,
    test_should_send_now,
    test_get_due_alerts,
    test_confidence_threshold_is_70_percent,
    test_bundle_repeats,
    test_bug_fix_query_safety_risk_without_ai,
    test_bug_fix_text_confidence_is_rejected,
    test_notifiers_are_substitutable,
    test_html_report,
    test_markdown_report,
    test_gui_notifier,
    test_ai_api_down_retries_then_human_review,
    test_ai_retry_then_success,
    test_ai_wrong_shape_reply_does_not_crash,
    test_ai_bad_replies_are_rejected,
    test_missing_api_key_skips_the_call,
    test_corrupt_records_file_is_backed_up_not_lost,
    test_unreadable_records_file_does_not_crash,
    test_pipeline_reports_corrupt_records_file,
    test_log_file_bad_input,
)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)   # keep log noise out of the test output
    print("Running project tests (mocked AI/Telegram; no live network calls)...")
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(TESTS)} tests passed.")
