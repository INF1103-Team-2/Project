"""logic_manager_decision.py - the triage outcome for one ErrorLog."""

from typing import Optional


class Decision:
    """Route, priority and notification state for one error log.

    Composition: only ErrorLog.apply_decision() creates a Decision, and a
    Decision never moves to another ErrorLog.
    """

    def __init__(self, route: str, score: int, notify_now: bool,
                 scheduled_send_time: str, requires_human_review: bool,
                 rules_fired: list[str]) -> None:
        self._route: str = route
        self._score: int = score
        self._notify_now: bool = notify_now
        self._scheduled_send_time: str = scheduled_send_time
        self._requires_human_review: bool = requires_human_review
        self._rules_fired: list[str] = list(rules_fired)
        # Optional flags: None means "not set" and is left out of the JSON.
        self._notification_sent: Optional[bool] = None
        self._review_notification_sent: Optional[bool] = None
        self._bundled_count: Optional[int] = None
        self._suppressed_by: Optional[str] = None

    # ----- read-only properties -------------------------------------------
    @property
    def route(self) -> str:
        return self._route

    @property
    def score(self) -> int:
        return self._score

    @property
    def notify_now(self) -> bool:
        return self._notify_now

    @property
    def scheduled_send_time(self) -> str:
        return self._scheduled_send_time

    @property
    def requires_human_review(self) -> bool:
        return self._requires_human_review

    @property
    def rules_fired(self) -> list[str]:
        return list(self._rules_fired)

    @property
    def notification_sent(self) -> bool:
        return bool(self._notification_sent)

    @property
    def review_notification_sent(self) -> bool:
        return bool(self._review_notification_sent)

    @property
    def bundled_count(self) -> Optional[int]:
        return self._bundled_count

    @property
    def suppressed_by(self) -> Optional[str]:
        return self._suppressed_by

    # ----- state changes --------------------------------------------------
    def mark_sent(self) -> None:
        """The engineer has been notified; never send this one again."""
        self._notification_sent = True

    def mark_review_notified(self) -> None:
        self._review_notification_sent = True

    def mark_suppressed(self, lead_log_id: str) -> None:
        """Rule 3: covered by the lead log's message, so treat as sent."""
        self._suppressed_by = lead_log_id
        self._notification_sent = True

    def set_bundled_count(self, count: int) -> None:
        self._bundled_count = count

    # ----- JSON -----------------------------------------------------------
    def to_dict(self) -> dict:
        data = {
            "route": self._route,
            "score": self._score,
            "notify_now": self._notify_now,
            "scheduled_send_time": self._scheduled_send_time,
            "requires_human_review": self._requires_human_review,
            "rules_fired": list(self._rules_fired),
        }
        if self._suppressed_by is not None:
            data["suppressed_by"] = self._suppressed_by
        if self._bundled_count is not None:
            data["bundled_count"] = self._bundled_count
        if self._notification_sent is not None:
            data["notification_sent"] = self._notification_sent
        if self._review_notification_sent is not None:
            data["human_review_notification_sent"] = self._review_notification_sent
        return data

    @staticmethod
    def from_dict(data: dict) -> "Decision":
        """Rebuild a stored decision (only ErrorLog.from_dict calls this)."""
        decision = Decision(
            route=data.get("route", ""),
            score=data.get("score", 0),
            notify_now=data.get("notify_now", False),
            scheduled_send_time=data.get("scheduled_send_time", ""),
            requires_human_review=data.get("requires_human_review", False),
            rules_fired=data.get("rules_fired") or [],
        )
        decision._notification_sent = data.get("notification_sent")
        decision._review_notification_sent = data.get("human_review_notification_sent")
        decision._bundled_count = data.get("bundled_count")
        decision._suppressed_by = data.get("suppressed_by")
        return decision
