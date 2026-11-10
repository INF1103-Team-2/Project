"""logic_manager_alert_scheduler.py - when alerts go out (Rules 1, 2, 3, 5)."""

from datetime import datetime, timedelta

from logic_manager_error_log import ErrorLog


class AlertScheduler:
    """Bundles repeated errors and decides which alerts are due."""

    BUNDLE_WINDOW_MINUTES = 10   # Business Rule 3

    def __init__(self) -> None:
        self._bundle_window: timedelta = timedelta(minutes=self.BUNDLE_WINDOW_MINUTES)

    def bundle_repeats(self, logs: list[ErrorLog]) -> None:
        """Rule 3: repeats of the same error_code on the same machine within the
        window are covered by the first (lead) log's notification."""
        ordered = sorted(logs, key=lambda log: (log.machine_id, log.error_code, log.timestamp))
        followers: dict[str, str] = {}
        counts: dict[str, int] = {}
        lead = None
        lead_time = None
        for log in ordered:
            when = datetime.strptime(log.timestamp, ErrorLog.TIME_FORMAT)
            is_repeat = (
                lead is not None
                and log.machine_id == lead.machine_id
                and log.error_code == lead.error_code
                and when - lead_time <= self._bundle_window
            )
            if is_repeat:
                followers[log.log_id] = lead.log_id
                counts[lead.log_id] = counts.get(lead.log_id, 1) + 1
            else:
                lead, lead_time = log, when

        for log in logs:
            if log.log_id in followers:
                log.decision.mark_suppressed(followers[log.log_id])
            if log.log_id in counts:
                log.decision.set_bundled_count(counts[log.log_id])

    def should_send_now(self, log: ErrorLog) -> bool:
        """Rules 1 + 5: urgent, not yet sent, and not waiting for human review."""
        decision = log.decision
        return (decision is not None
                and decision.notify_now
                and not decision.requires_human_review
                and not decision.notification_sent)

    def get_due_alerts(self, logs: list[ErrorLog], now: datetime) -> list[ErrorLog]:
        """Rule 2: deferred, unsent alerts whose 07:00 send time has arrived."""
        current_time = now.strftime(ErrorLog.TIME_FORMAT)
        due = []
        for log in logs:
            decision = log.decision
            if decision is None:
                continue
            if decision.notify_now or decision.requires_human_review:
                continue
            if decision.notification_sent:
                continue
            send_time = decision.scheduled_send_time
            if send_time and send_time <= current_time:   # same format, text compare works
                due.append(log)
        return due
